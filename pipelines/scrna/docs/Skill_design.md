# OmicHub 技能设计与接入规范（Skill Design Protocol）v1.0

> **规范名称**: OmicHub Skill Design Protocol（OSDP）
> **版本**: 1.0（草案，待评审）
> **状态**: RFC — 征求实现反馈
> **日期**: 2026-08-03
> **适用对象**: 所有接入 OmicHub 平台、挂载到 AI Agent 的技能（Skill）的作者与评审者；包括但不限于单细胞（scRNA）、转录组（RNA-seq）、ATAC、变异分析等生信分析技能的创建者
> **关联文档**:
> - `docs/26.7.27/OmicHub技能加载方案与助手管理页美化实现计划.md`（平台 Skill 三层加载机制设计，本规范的上游架构依据）
> - `docs/26.8.1/阿里云Skills接入与Skill治理实现计划.md`（外部技能源接入与治理）
> - `docs/26.8.3/单细胞脚本Skill化改造与整合规范.md`（scRNA 技能集参考实现方案）
> - `Protocol/分析流程结果交付协议_v1.md`（ARDP，分析产物交付契约，可执行技能的输出契约需与对齐）
> - `data/ai/README.md`（Agent 声明式配置目录约定）

---

## 目录

1. [背景与定位](#一背景与定位)
2. [术语与三层加载模型](#二术语与三层加载模型)
3. [技能包目录结构规范](#三技能包目录结构规范)
4. [SKILL.md frontmatter 规范](#四skillmd-frontmatter-规范)
5. [SKILL.md 正文编写规范（五段式）](#五skillmd-正文编写规范五段式)
6. [可执行脚本（scripts/）规范](#六可执行脚本scripts规范)
7. [参考资源（references/ 与 assets/）规范](#七参考资源references-与-assets规范)
8. [硬性限制与红线](#八硬性限制与红线)
9. [技能拆分与路由边界规范](#九技能拆分与路由边界规范)
10. [挂载到 Agent 的接入流程](#十挂载到-agent-的接入流程)
11. [版本管理与变更规范](#十一版本管理与变更规范)
12. [安全规范](#十二安全规范)
13. [评审与验收清单](#十三评审与验收清单)
14. [参考实现：scRNA 技能集](#十四参考实现scrna-技能集)
15. [附录：关键源码索引](#附录关键源码索引)

---

## 一、背景与定位

### 1.1 问题陈述

OmicHub 的 AI Agent（如 `agent-scrna` 单细胞分析师）通过 Skill 获得领域知识与执行能力。但当前技能创建**没有正式规范**，导致：

1. **知识型与可执行型不分**：现有市场技能（`human-mouse-cell-annotation` 等 4 个）全部是纯指令文本，Agent 只会"给建议"不会"跑分析"；把脚本转成技能时不知道脚本放哪、如何被调用；
2. **格式凭模仿**：frontmatter 字段、正文结构靠抄现有技能，缺了 `description` 才会在运行时报错才发现；
3. **边界重叠**：新技能与已有技能触发场景含糊，L1 路由互相打架；
4. **红线不清**：把大型参考数据库（SingleR rds、CellMarker 表）塞进技能包导致超限；
5. **硬编码遗留**：源仓库脚本中的宿主机绝对路径（`/titan3/...`、`/home/zj/miniconda3/...`）被原样带入沙盒，必然运行失败。

### 1.2 目标

定义一份**从"仓库脚本/文档"到"平台可挂载技能"的全流程规范**：

- **一个格式**：技能 = 一个文件夹（`SKILL.md` + 可选 `scripts/`、`references/`、`assets/`）；
- **一个模板**：SKILL.md 正文五段式（触发 → 输入契约 → 执行步骤 → 输出契约 → 质控与限制）；
- **一套契约**：可执行脚本统一 CLI 签名与结构化输出，Agent 可读、平台可验；
- **一张清单**：创建 → 自查 → 挂载 → 端到端验证的评审 checklist。

### 1.3 适用范围

本规范适用于**平台技能体系**（`data/ai/skill_marketplace/` 与 `data/ai/skills/`），**不适用**于：

- `pipelines/*/skills/SKILL.md`：Flow 流程仓库自带的 Claude Code 风格技能，frontmatter 含 `tool_type`/`depends_on`/`qc_checkpoints`，是另一套独立规范，**禁止混用**；
- `tool_configs/`：传统 GUI 工具箱配置，与 Agent Skill 体系无关；
- MCP 工具（`mcp-server/`）：MCP 提供"动作与数据"，Skill 提供"知识与流程"，二者互补而非替代，分工见 §9.3。

---

## 二、术语与三层加载模型

| 术语 | 定义 |
|---|---|
| **Skill（技能）** | 一个文件夹形式的领域能力包，含指令文本与可选可执行脚本 |
| **知识型技能** | 只含 SKILL.md（+references），无 scripts；为模型提供判断框架与领域知识 |
| **可执行型技能** | 含 `scripts/` 的 skill；SKILL.md 指导模型在沙盒中调用脚本，产出真实分析结果 |
| **skill_id** | 技能唯一标识 = 文件夹名；小写字母/数字/连字符，≤48 字符 |
| **L1 / L2 / L3** | 渐进式披露三层，见下 |

平台遵循 Anthropic Agent Skills 渐进式披露模型（实现见 `src/omichub/infrastructure/skills/skillmd.py`、`src/omichub/domain/skill/services.py`）：

- **L1 索引层**：启动时仅将每个技能的 `name + skill_id + description` 注入 system prompt（约 100 tokens/技能）。**`description` 是唯一的路由依据**，决定模型何时想到这个技能；
- **L2 正文层**：模型判断任务匹配后，通过内置工具 `use_skill` 加载 SKILL.md 全文。正文必须是"自包含的工作手册"——模型读完就能干活；
- **L3 资源层**：正文通过 `skill_resource` 工具按需引用 `references/`、`assets/`（单文件 ≤200KB），用于参数详解、marker 表、模板等"用得着才读"的材料。

设计推论：**正文里每一处细节都要问"每次任务都需要它吗？"——不是，就下沉到 references。**

---

## 三、技能包目录结构规范

### 3.1 标准结构

```
<skill-id>/
├── SKILL.md          # 必填：YAML frontmatter + Markdown 正文
├── scripts/          # 可选（可执行型必填）：CLI 脚本，R/Python/Shell
├── references/       # 可选：L3 参考文档（.md/.tsv/.csv/.json）
└── assets/           # 可选：模板、静态资源
```

规则：

1. **文件夹名即 skill_id**，创建后不得随意改名（agent YAML、DB 索引、会话 pin 均引用它）；
2. 除此四个条目外**禁止**放其他内容（禁止 `__pycache__/`、测试数据、`.git`、README.md——说明性内容一律写进 SKILL.md 或 references/）；
3. `scripts/` 内脚本必须可直接执行或通过解释器调用，且符合 §6 的 CLI 契约；
4. 一个技能包内脚本数量建议 **≤5 个**；超过说明该技能应承担多个职责，按 §9 拆分。

### 3.2 存放位置（二选一）

| 位置 | 用途 | 生效方式 |
|---|---|---|
| `data/ai/skill_marketplace/<skill-id>/` | **内置市场技能（默认选择）** | 服务启动时 `agent_service._ensure_configured_marketplace_skills()` 自动安装并挂载到声明了它的 agent |
| `data/ai/skills/<skill-id>/` | 运行时安装产物 | 由管理 API（`src/omichub/api/v1/admin/skills.py`）导入 zip/JSON 时落盘，**不要手工写入** |

个人/第三方开发的技能先放自建 git 仓库，经 §13 评审后合入 `skill_marketplace/`。

---

## 四、SKILL.md frontmatter 规范

### 4.1 字段表

| 字段 | 必填 | 类型 | 规范 |
|---|---|---|---|
| `name` | **是** | string | 技能显示名，可中文；面向用户与模型，需达意（如"单细胞差异表达分析"） |
| `description` | **是** | string | **触发路由依据**。必须写清三要素：①输入是什么 ②用户意图是什么 ③与相邻技能的区分点。缺失直接报错 |
| `version` | 建议 | semver | 会话内版本 pin 依赖它；**不改版本号 = 改内容不生效**（见 §11） |
| `author` | 建议 | string | 作者/团队 |
| `icon` | 可选 | emoji | 单个 emoji |
| `category` | 可选 | string | 默认 `general`；分析类统一用 `analysis` |
| `skill_id` | 可选 | string | 显式指定 id；**中文 name 时必须显式指定**（否则 slug 生成结果不可控）。一旦发布不得变更 |

### 4.2 description 写作规范

`description` 不是宣传语，是路由判据。公式：

> 当【输入条件】且用户要求【具体意图】时触发。【与相邻技能的边界】。

- ✅ 好例：`当用户需要对已注释的 scRNA-seq Seurat 对象按"细胞类型 × 分组"做批量差异表达分析（FindMarkers）、基因注释和火山图可视化时触发。输入为 RDS/H5AD 对象路径与分组列名。`——输入、意图、边界俱全；
- ❌ 坏例：`单细胞分析相关工具。`——模型无法判断何时用它；
- ❌ 坏例：与已有技能 `differential-expression` 描述几乎相同——路由冲突。

### 4.3 禁止事项

- 禁止添加解析器不认识的字段（`tool_type`、`depends_on` 等 pipelines 体系字段）；
- 禁止在 frontmatter 写多行富文本（触发细节放正文"何时使用"段）。

---

## 五、SKILL.md 正文编写规范（五段式）

正文是模型的工作手册。统一采用五段式结构（知识型技能可省略 §3 命令细节，但段序不变）：

```markdown
# <技能名>

## 何时使用（Trigger）
- 触发场景的具体条件（输入形态、前置步骤、用户意图）；
- 不适用场景（一句话划界，指向相邻技能）。

## 输入契约（Input）
| 参数 | 必填 | 说明 |
（表格列出全部输入；必填项缺失时"先简短追问，不要臆测默认值"）

## 执行步骤（Workflow）
1. 前置校验（文件存在性、列名存在性、样本量阈值）；
2. 确切可复制的命令行（可执行型）或分析逻辑（知识型）；
3. 结果读取与汇报方式（读 summary.json，汇报关键统计量）；
4. 分支与异常处理。

## 输出契约（Output）
- 产物路径模式、文件格式、固定文件名；
- 必须含结构化摘要 summary.json（见 §6.3）。

## 质控与限制（QC & Constraints）
- 默认阈值与用户可覆盖项；
- 失败时的行为（原样返回 stderr，禁止伪造结果）；
- 严格限制（不改输入文件、产物只写指定目录等）。
```

写作要求：

1. **正文 < 20000 字符（约 5000 tokens）**——超过仅告警，但每字都占上下文，细节下沉 references/；
2. **命令行必须可直接复制执行**，参数用 `{占位符}` 并标注来源（用户输入/前置产物）；
3. **写失败路径**：脚本报错、输入缺失、阈值不满足时模型该做什么，必须写明；
4. 禁止在正文堆砌背景知识（"什么是 UMAP"），模型已知；只写**本工具特有**的接口、阈值、判读规则；
5. 语言：正文用中文还是英文跟随技能目标用户，但参数名、路径、命令保持原文。

---

## 六、可执行脚本（scripts/）规范

### 6.1 来源与改造前置条件

仓库脚本进入技能包前必须完成三项改造（阻塞项）：

1. **清除一切硬编码路径**：宿主机绝对路径（`/home/...`、`/titan3/...`）、conda 环境路径、参考库路径全部参数化；参考库路径用环境变量（如 `SCRNA_REF_DIR`）或 CLI 参数注入；
2. **函数库补 CLI wrapper**：R 函数库（`source()` 调用形态）必须用 `optparse` 包一层独立 CLI；Python 用 `argparse`；
3. **环境自查**：对照技能 `references/environment.md` 中的依赖清单（包名+版本），确认沙盒运行时画像（如 `analysis-scrna` 的 `required_capabilities`）已覆盖；未覆盖的包先补沙盒镜像，再上架技能。

### 6.2 CLI 签名契约（统一）

```bash
Rscript scripts/<tool>.R --input <rds/h5ad路径> --output <输出目录> [--<param> <value> ...]
python scripts/<tool>.py --input ... --output ...
```

- 必有参数：`--input`（单个输入对象路径）、`--output`（产物目录，脚本负责创建）；
- 参数名全小写连字符（`--group-col`、`--celltype-col`）；
- 退出码：0 成功，非 0 失败且 stderr 输出可读错误信息。

### 6.3 结构化输出契约

每个脚本必须在 `{output}/summary.json` 写出产物清单与关键统计量，与 ARDP（`Protocol/分析流程结果交付协议_v1.md`）对齐：

```json
{
  "tool": "FindMarkers_Celltype_group",
  "version": "1.0.0",
  "status": "success",
  "outputs": [
    {"path": "DEG/Tcell_Treat_vs_Control-DEG-infor.csv", "type": "table"},
    {"path": "figure/Tcell_Treat_vs_Control_volcano.png", "type": "figure"}
  ],
  "stats": {"n_celltypes": 5, "n_deg_total": 1320},
  "warnings": ["B cell: 细胞数 18 < 30，统计功效不足，已跳过"]
}
```

模型执行后**只读 summary.json 向用户汇报**，不解析大结果文件。

### 6.4 脚本选型纪律

- **一个技能一个权威实现**：源仓库功能重叠的脚本（如 4 个 DEG 变体、2 个 propplot）只选一个进技能包，其余变体能力通过参数体现在 SKILL.md；
- 一次性脚本、硬编码无法救回的历史模板（如 `Seurat.r`、`MCA_Altas_merge.py`）**禁止进包**，经验证的知识可改写进 references/；
- 脚本需通过危险模式静态扫描（`skillmd.py` 内置，仅告警）：禁止 `rm -rf`、`system("curl ...")` 外联、写沙盒外路径。

---

## 七、参考资源（references/ 与 assets/）规范

| 目录 | 放什么 | 读取方式 |
|---|---|---|
| `references/` | 参数详解、阈值依据、marker 参考表（小体积）、环境依赖清单 `environment.md`、示例输入输出说明 | 模型经 `skill_resource` 按需读，单文件 ≤200KB |
| `assets/` | 报告模板、静态配色/样式文件 | 同上 |

红线：**大型参考数据禁止进技能包**。SingleR 参考 rds、CellMarker/PanglaoDB 全库、基因组注释等一律放共享数据卷/对象存储，SKILL.md 正文只写：①路径约定（环境变量名）②缺失时的报错与指引。

---

## 八、硬性限制与红线

平台解析器强制执行（`skillmd.py`），违反即拒绝或降级：

| 限制 | 阈值 | 违反后果 |
|---|---|---|
| 技能包总大小 | ≤ 1 MiB | 拒绝 |
| 单文件大小 | ≤ 512 KB | 拒绝 |
| SKILL.md 正文 | 建议 < 20000 字符 | 告警（但浪费上下文，视为评审不通过项） |
| L3 资源单文件 | ≤ 200 KB | `skill_resource` 无法读取 |
| skill_id | ≤48 字符，小写/数字/连字符 | 拒绝 |
| frontmatter `name`/`description` | 必填 | 报错 |

上架前自查命令：`du -sh <skill-id>/` 与 `find <skill-id>/ -size +512k`。

---

## 九、技能拆分与路由边界规范

### 9.1 拆分原则

1. **单一职责**：一个技能 = 一个明确的分析任务（"格式转换"、"细胞类型×分组 DEG"、"比例统计"），不是"单细胞分析大全"；
2. **按产物衔接拆分**：上游技能的输出契约 = 下游技能的输入契约（如重聚类技能产出 RDS → 注释技能消费 RDS → DEG 技能消费注释后 RDS），形成可串联链；
3. **知识型 / 可执行型配对**：执行型技能跑工具产出候选结果，知识型技能提供专家判断框架对结果裁决（参考 scRNA 注释技能对）。

### 9.2 主流程 vs 技能

重量级全量管线（如 `scRNAseqMulticommand` 主流程）**不直接 skill 化**——它适合作为独立容器任务（Docker/沙盒任务）运行。只为它创建一个"编排型"知识技能，内容是：何时调用完整管线、如何准备配置（conf.csv）、如何解读输出目录结构。

### 9.3 Skill vs MCP 分工

- MCP 工具：平台资源动作（创建任务、查文件、读数据库）——"能做什么"；
- Skill：领域知识与分析流程——"该怎么做"。
SKILL.md 正文应写明何时调用哪个 MCP/沙盒工具，禁止在 skill 脚本里重新实现平台能力（如直接连数据库）。

### 9.4 边界登记

新技能上架前，作者在 SKILL.md "何时使用"段明确"不适用场景"，并在评审时与现有技能 description 逐条比对，确认无路由重叠（参考 `docs/26.8.3/单细胞脚本Skill化改造与整合规范.md` 第五节的边界表格式）。

---

## 十、挂载到 Agent 的接入流程

按序执行：

1. 在 `data/ai/skill_marketplace/` 创建 `<skill-id>/` 目录并完成技能包；
2. 在目标 agent YAML（如 `data/ai/scrna.yaml`）的 `skill_ids` 列表追加 skill_id（与文件夹名严格一致）；agent YAML 与 tool_packs 内的 `skill_ids` 自动合并去重（`agent_loader.py`）；
3. 视需要更新 agent prompt（`data/ai/prompts/*.md`）：注明"对应步骤优先调用技能 scripts，而非自行重写代码"；
4. 重启服务，检查启动日志确认市场技能自动安装成功；
5. **端到端验证**：用真实/测试数据让目标 agent 完整跑通技能声明的场景，核对：L1 正确触发 → `use_skill` 加载 → 脚本在沙盒执行成功 → summary.json 被读取汇报；
6. 验证通过后回填技能 `version: 1.0.0`，进入正式维护。

---

## 十一、版本管理与变更规范

1. 平台在会话首轮做技能版本 pin（`skill_pins`），会话内使用快照——**改内容必须 bump `version`**，否则进行中的会话与缓存索引不会感知变更；
2. 版本号语义（semver）：改脚本行为/接口 → minor 或 major；改正文措辞/补充 references → patch；
3. 接口破坏性变更（CLI 参数改名、输出文件改名）→ major，且必须检查所有引用该技能的 agent prompt 与其他技能的衔接契约；
4. 平台支持版本管理与回滚（`skill_service.py`），上架前无需保留历史版本在技能包内——历史版本由 git 仓库管理，技能包永远只含当前版本。

---

## 十二、安全规范

1. 脚本禁止：写沙盒/工作区之外的路径、网络外联（下载参考数据属平台预置职责）、`eval`/`source` 用户传入的未校验内容、读取平台密钥文件；
2. 脚本只读输入文件，所有写入限定在 `--output` 目录内；
3. references 中禁止包含真实样本的隐私数据，示例数据必须脱敏或使用公开数据集（如 PBMC 1k）；
4. 外部来源技能（阿里云市场等）须经安装前审查流程（`docs/26.8.1/阿里云Skills接入与Skill治理实现计划.md`），本规范 §13 清单同样适用。

---

## 十三、评审与验收清单

技能合入 `skill_marketplace/` 前逐项过检：

**格式**
- [ ] 目录结构符合 §3.1，无多余文件
- [ ] frontmatter 必填字段齐全，中文 name 已显式指定 `skill_id`
- [ ] description 符合 §4.2 三要素公式
- [ ] 正文五段式齐全、< 20000 字符
- [ ] `du -sh` ≤ 1MiB，无 >512KB 文件，references 单文件 ≤200KB

**脚本（可执行型）**
- [ ] 无硬编码绝对路径，参考数据走环境变量
- [ ] CLI 签名符合 §6.2，退出码规范
- [ ] 输出含 `summary.json`（§6.3 结构）
- [ ] 依赖清单 `references/environment.md` 与沙盒画像核对通过
- [ ] 无 §12 禁止行为

**整合**
- [ ] 与现有技能 description 无路由重叠（§9.4 边界表）
- [ ] 输入/输出契约与上下游技能衔接（§9.1）
- [ ] agent YAML `skill_ids` 已追加，prompt 已更新
- [ ] 端到端验证通过（§10 第 5 步）
- [ ] `version` 已正确设置

---

## 十四、参考实现：scRNA 技能集

单细胞技能集是本规范的首个参考实现，拆分方案详见 `docs/26.8.3/单细胞脚本Skill化改造与整合规范.md`：

| skill_id | 类型 | 说明 |
|---|---|---|
| `scrna-pipeline-overview` | 知识型（编排） | 主流程 `scRNAseqMulticommand` 的调用编排（§9.2 模式） |
| `scrna-object-convert` | 可执行型 | RDS↔H5AD 等格式转换与子集操作（现成 CLI 直接封装范例） |
| `scrna-recluster` | 可执行型 | 单样本重聚类（函数库 + wrapper 范例） |
| `scrna-annotation-ref` | 知识型+薄脚本 | SingleR/ScType/CellID 自动注释策略与参考库路径约定 |
| `scrna-tcell-projectils` | 可执行型 | T 细胞 ProjecTIL 精细注释 |
| `scrna-deg-analysis` | 可执行型 | 细胞类型×分组批量 DEG（§6.3 输出契约范例） |
| `scrna-annotation-stats` | 可执行型 | 细胞比例统计与可视化 |

后续 RNA-seq、ATAC 等技能集创建时，照此表结构先出拆分方案再动手。

---

## 附录：关键源码索引

- Skill 解析与限制：`src/omichub/infrastructure/skills/skillmd.py`
- 磁盘存储与 L3 读取：`src/omichub/infrastructure/skills/skill_store.py`
- 运行时注入（L1 索引 / `use_skill` / `skill_resource`）：`src/omichub/domain/skill/services.py`
- Agent 声明式定义与 skill 合并：`src/omichub/infrastructure/config/agent_loader.py`、`data/ai/*.yaml`
- 市场自动安装：`agent_service._ensure_configured_marketplace_skills()`
- 版本/回滚/统计管理：`src/omichub/application/services/skill_service.py`
- 导入链路：`src/omichub/application/services/skill_import_service.py`
- 管理 API：`src/omichub/api/v1/admin/skills.py`
- 配置项（skills_dir、marketplace 目录）：`src/omichub/core/config.py:167-181`
