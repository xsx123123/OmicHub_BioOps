# CygnusX 技能生成提示词模板（Skill Builder Prompt）

> 用途：让 AI 把某个源码目录改造成符合 `Protocol/Skill_design.md`（OSDP v1.3+）的平台技能时使用。
> 用法：把本文件全文 + 规范文件 + 目标源码目录一起交给 AI，并把末尾【任务参数】填好。
> 注意：本提示词是**任务指令**，规范是**验收标准**，两者必须同时使用——只给规范，AI 容易把任务做成"读源码写摘要"。
> v1.3 重点：依赖可达性（规范 §2.3/§6.8）——2026-08-04 全量冒烟发现 21/32 存量技能因"镜像缺包 + environment.md 教了白名单不可达的安装方式"开箱不可运行，生成时必须按规则 9-12 规避。

---

## 角色

你是 CygnusX 平台技能构建工程师。你的产出是**可直接挂载的技能包文件**（写入文件系统），不是调研报告、不是源码清单、不是使用说明。

## 任务

把【任务参数】中指定的源码目录，改造成一个（或多个）CygnusX 技能包，落盘到【输出目录】。

## 必须遵守的硬性规则（违反任何一条 = 返工）

1. **实体进包**：技能需要的每个脚本，必须把**文件本体复制**进 `scripts/`。禁止只登记源路径。脚本与源仓库从此解耦。
2. **缺什么补什么，不是记什么**：
   - 源码没有 CLI（是函数库 / 裸脚本 / 位置参数）→ **你必须用 argparse（Python）或 optparse（R）写一个 wrapper** 放进 `scripts/`；
   - 没有统一输出 → wrapper 统一为 `--input/--output` 签名，并在 `{output}/summary.json` 写产物清单与关键统计量；
   - 有硬编码绝对路径 → 参数化后再进包。
   **禁止**在文档里写"当前没有统一 CLI wrapper""没有 summary.json"然后停手——发现缺口就是你的工作量。
3. **运行时路径只有三种合法写法**：
   - 包内文档：`references/xxx.md`（相对路径）；
   - 包内脚本命令：`/workspace/.skills/<skill_id>/scripts/xxx.py`（物化路径）；
   - 外部数据：`ref/`（如 `ref/Celldex/`）或环境变量。
   除此之外任何路径（`src/...`、`pipelines/...`、`/home/...`、`/titan3/...`）禁止出现在技能包任何文件中。
4. **命令必须是运行时形态**：沙盒里怎么执行就怎么写。禁止 `cargo run`、`make`、`cd src/...`、`conda activate xxx &&`、`git checkout`。
5. **references 是自包含操作手册**：参数表（从源码 argparse/clap 核实）、至少一条端到端可复制命令、常见报错处置。禁止"使用前先查看脚本内容""详见 README""以源码为准"这类指针——写完手册后，模型不需要再看源码。
6. **外部数据（>512KB / 参考库）不进包**：写 `references/provisioning.md`（资源名、大小、管理员获取方式、`ref/` 目标位置、校验脚本），SKILL.md 里只写路径约定与缺失处置。
7. **SKILL.md 结构**：frontmatter 必填 `name`、`description`（按"当【输入】且用户要求【意图】时触发。【边界】"公式写）、显式 `skill_id`、`version: 0.9.0`、`category: analysis`；正文五段式：何时使用 → 输入契约（表格） → 执行步骤（含确切命令行） → 输出契约（含 summary.json） → 质控与限制。正文 < 20000 字符。
8. **大小红线**：技能包总量 ≤ 1MiB，单文件 ≤ 512KB，references 单文件 ≤ 200KB。
9. **依赖必须逐个标"可达级别"，安装命令只准白名单形态**（规范 §2.3/§6.8）：
   - `references/environment.md` 里每个依赖一行：包名（conda 形态 `r-xxx`/`bioconductor-xxx`/pypi 名）、版本、用途、级别、安装方式；
   - 级别 A=目标镜像已预装；B=白名单可现场装；C=GitHub 独占等装不了、需镜像预装；D=运行期要访问业务外网；
   - B 级安装命令只允许：`micromamba install -y -n base -c conda-forge -c bioconda <pkg>` / `uv pip install <pkg>` / `pip install -i https://pypi.org/simple <pkg>`；
   - **禁止写** `install.packages()`、`remotes::install_github()`、`BiocManager::install()`、`pip -i pypi.mirrors.ustc.edu.cn`——Studio 沙盒出站白名单（pypi.org / files.pythonhosted.org / conda.anaconda.org / mirrors.aliyun.com / mirrors.ustc.edu.cn）之外的域名一律 403，写了等于教 AI 走死路。
10. **GitHub 独占包（C 级）不许假装能装**：ProjecTILs、scCustomize、AnnoProbe、DoubletFinder、sceasy、loomR 这类只在 GitHub 分发的包，沙盒现场装不到。处理方式：environment.md 标"需管理员预装进镜像"；`check_env.sh` 检测到缺失时报"本技能无法运行，请联系管理员预装 X"；若技能核心功能依赖它，SKILL.md 质控段必须写"X 未预装时本技能不可运行"。有 conda 等价包的一律改用 conda 版。
11. **业务外网依赖（D 级）必须声明 + 降级**：脚本运行期要访问 KEGG/UniProt/NCBI/Ensembl 等非包源域名时，environment.md 单列"网络依赖"段（域名、用途、Studio 白名单不可达、降级策略）；降级二选一：参考数据预下载进 `ref/`（走 provisioning.md 供给流程）离线运行，或明示"仅聊天沙箱（有外网）可运行"。
12. **check_env.sh 三重检查**：可执行技能必须带 `scripts/check_env.sh`，且同时覆盖 ①系统命令 `command -v` ②R 包 `requireNamespace` ③Python 包 `import`——存量技能大量失败发生在包层而非命令层，只查命令不够。SKILL.md 执行步骤第一步运行它。

## 工作流程（按序执行，每步汇报）

1. **读源码**：通读目标目录每个脚本的 argparse/clap/函数签名，搞清真实接口、输入输出、依赖包（逐个核对 `library()`/`requireNamespace()`/`import` 的真实调用，不只看文档声明）。README 只作参考，接口以代码为准。
2. **出拆分方案**：列出你计划创建的技能清单（skill_id、类型、包含哪些脚本、外部数据依赖），并附**依赖可达性分级表**（每个依赖 → A 已预装 / B 白名单可装 / C 需镜像预装 / D 业务外网，规范 §2.3），**先给我确认，再动手写文件**。C/D 级依赖要在这里说明处置方案。
3. **写文件**：逐个技能落盘（SKILL.md + scripts/ + references/），wrapper 补全缺口；environment.md 按规则 9 的四级表格写，check_env.sh 按规则 12 三重覆盖。
4. **依赖冒烟（有沙盒环境时必做）**：在【任务参数】指定的目标镜像里实测——把技能目录复制进容器 `/workspace/.skills/<skill_id>/`，逐个脚本跑 `python/Rscript <script> --help`、跑 `bash check_env.sh`，B 级依赖先按 environment.md 的命令装一遍验证命令本身可达。没有可用沙盒时，必须在验收报告中逐条说明每个依赖的核实方式（对照目标镜像 Dockerfile/`data/ai/runtime_images.yaml` 声明清单），不得留空。平台有现成工具可复跑：`python3 scripts/skill_mcp_smoke.py --only skills --filter <skill_id>`。
5. **写台账**：在【输出目录】根部（即各技能文件夹的上一级）创建/更新 `SKILLS_REGISTRY.md`（格式见下节），登记本次每个技能；若文件已存在，只追加/更新对应条目，不覆盖历史记录。
6. **自检（空目录法）**：假想技能包被复制到一个空目录，逐条检查 SKILL.md 和 references 里出现的每个路径、每条命令——凡在"空目录 + 沙盒预置环境"下解析不了的，立即修正。
7. **交验收报告**：输出目录树 + 每个技能的自查结果（对照下方验收清单逐项 ✅/❌）+ 第 4 步冒烟的实测输出摘要。

## 技能台账（SKILLS_REGISTRY.md）

在【输出目录】根部维护一份 `SKILLS_REGISTRY.md`，作为该源码目录 skill 化的**版本台账与续作入口**——后续新增模块 skill 化时，先读本台账再决定拆分与衔接，避免重复劳动和路由冲突。固定格式：

```markdown
# <源仓库名> 技能台账（SKILLS_REGISTRY）

> 本文件记录本仓库脚本 skill 化的全部产出与版本历史。
> 新增模块 skill 化时：先读本表 → 确认无重复/冲突 → 按 Protocol/Skill_design.md 拆分 → 完成后回写本表。

## 技能清单

| skill_id | 名称 | 来源脚本（源仓库路径） | 类型 | 当前版本 | 状态 | 外部数据依赖 | 备注 |
|---|---|---|---|---|---|---|---|
| go-annotation-mgi | MGI/GAF 清洗 | src/GO_Annotation/MGI_gaf_parser.py | 可执行型 | 0.9.0 | 已验证 | 无 | wrapper 为新建 |
| go-annotation-uniprot | UniProt GAF 转换 | src/GO_Annotation/uniprot_gaf_converter_v2.py | 可执行型 | 0.9.0 | 待验证 | UniProt 在线映射（需网络/降级策略） | — |

状态取值：待验证（未跑通端到端）/ 已验证（沙盒实测通过）/ 已挂载（已加入 agent skill_ids）/ 已弃用（注明替代者）。

## 未 skill 化的剩余模块

| 源路径 | 说明 | 未做原因 / 计划 |
|---|---|---|
| src/GO_Annotation/xxx.py | 一次性硬编码脚本 | 不适合 skill 化（规范 §6.4） |

## 版本历史

| 日期 | 变更 | 涉及技能 |
|---|---|---|
| 2026-08-03 | 首次 skill 化，新建 2 个技能 | go-annotation-mgi, go-annotation-uniprot |
```

台账规则：

- **每个技能一行**，来源脚本列写源仓库路径（这里允许写源路径——台账给开发者看，不进技能包，不受自包含约束）；
- **版本跟踪**：技能 SKILL.md 的 `version` 变更时同步更新台账"当前版本"与"版本历史"；
- **新增模块记录**：后续每次 skill 化新脚本，追加技能清单行 + 版本历史行；"未 skill 化"表记录跳过原因，防止下次重复评估；
- 台账文件本身**不进技能包、不上传平台**，只留在源仓库/输出目录供开发与评审使用。

## 反面教材（这样输出 = 失败）

```markdown
# XXX 源码清单          ← 失败：这是调研笔记不是技能
- `src/XXX/yyy.py`：...  ← 失败：源仓库路径，运行时不存在
- 当前目录没有统一 CLI wrapper  ← 失败：发现缺口不补，等于没做
执行前优先查看对应脚本的 argparse  ← 失败：运行时没有源码可看
```

```markdown
# environment.md 反面教材（存量技能真实踩坑，全部被白名单拦截）
install.packages(c("Seurat", "optparse", "log4r"))     ← 失败：CRAN 不可达
remotes::install_github("carmonalab/ProjecTILs")        ← 失败：GitHub 不可达，应标"需镜像预装"
pip install <pkg> -i https://pypi.mirrors.ustc.edu.cn/simple  ← 失败：该域名不在白名单（403）
| ProjecTILs | ≥1.0 | 核心注释 | CRAN 无，install_github 安装 |  ← 失败：C 级包假装能现场装
依赖：需要网络（KEGG）                                    ← 失败：D 级一句带过，无降级策略
```

## 验收清单（交付前逐项自检）

- [ ] 每个脚本实体在 `scripts/` 内，无指针
- [ ] 无 CLI 的脚本已补 wrapper；wrapper 输出 summary.json
- [ ] SKILL.md 五段式齐全，命令全是运行时形态
- [ ] 包内无任何源仓库/宿主机路径
- [ ] 每个可执行技能至少一条端到端示例命令
- [ ] 外部数据有 provisioning.md，无"git/仓库恢复"式指引
- [ ] frontmatter 四个关键字段（name/description/skill_id/version）齐全
- [ ] `SKILLS_REGISTRY.md` 台账已创建/更新（技能清单 + 未 skill 化模块 + 版本历史三段齐全）
- [ ] 大小红线自查通过
- [ ] environment.md 每个依赖标 A/B/C/D 级别，安装命令全为白名单形态（无 install.packages / install_github / BiocManager::install / pypi.douban.com）
- [ ] C 级（GitHub 独占）依赖标"需镜像预装"，check_env.sh 缺失时报"无法运行"；核心功能依赖 C 级包时质控段已声明
- [ ] D 级（业务外网）依赖有网络依赖段 + 降级策略或沙盒限制声明
- [ ] check_env.sh 覆盖命令 + R 包 + Python 包三层
- [ ] 依赖冒烟（工作流程第 4 步）已实测或已逐条说明核实方式

---

## 【任务参数】（使用前填写）

- 目标源码目录：`<填路径，如 /home/zj/pipeline/GO_Annotation>`
- skill_id：`<填，如 go-annotation>`
- 输出目录：`<填，如 pipelines/go/skills/ 或 data/ai/skill_marketplace/>`
- 目标运行时镜像：`<core / plot / scrna / sandbox-base；决定 environment.md 的 A 级"已预装"基线——core=cygnusx-analysis:core-2026.07，scrna=cygnusx-analysis:scrna-2026.07，声明清单见 data/ai/runtime_images.yaml；不确定填 core>`
- 目标 Agent（可选）：`<如 agent-scrna；不确定则留空>`
- 外部数据/环境约束（可选）：`<如 UniProt 在线映射需要网络——属 D 级依赖，必须注明离线降级策略或"仅聊天沙箱可运行">`
