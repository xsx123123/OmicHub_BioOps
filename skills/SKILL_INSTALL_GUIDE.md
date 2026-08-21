# Skill 安装与配置指南

本仓库存在**两套相互独立的 Skill 体系**，请不要混淆：

1. **Kimi Code CLI Agent Skills** —— 给本仓库里的 AI 编码助手（Kimi Code CLI）使用的技能。
2. **OmicHub 平台内部 Skill** —— 给 OmicHub 产品里的业务 Agent（如「单细胞分析师」`agent-scrna`）使用的技能。

---

## 一、Kimi Code CLI Agent Skills

### 1. 是什么

一个 Skill 就是一个带 YAML frontmatter 的 Markdown 文件，无需任何"安装命令"，**放进扫描目录即被加载**（新会话生效）。

两种文件形式：

- **目录形式（推荐）**：`<技能名>/SKILL.md`，配套脚本、`references/`、`examples/` 放同目录。frontmatter 中 `name`、`description` **必填**，缺一则解析失败。
- **扁平形式**：单个 `<技能名>.md`。

### 2. 扫描目录（四级，优先级：项目 > 用户 > 额外 > 内置）

| 级别 | 路径 | 说明 |
|---|---|---|
| 项目级 | `<仓库根>/.kimi-code/skills/`、`<仓库根>/.agents/skills/` | 项目根 = 向上最近的含 `.git` 的目录；本仓库使用 `.agents/skills/` |
| 用户级 | `~/.kimi-code/skills/`、`~/.agents/skills/` | 所有项目共享 |
| 额外目录 | `config.toml` 顶层 `extra_skill_dirs = ["skills"]` | 想把自定义目录注册为扫描路径时使用（**TOML，不是 YAML**） |
| 内置 | 随 CLI 分发 | 优先级最低 |

注意：**不存在"编辑某个 yaml 清单即可注册 skill"的机制**，加载纯靠目录扫描。Skill 文件自身的 frontmatter 才是 YAML。

### 3. 调用方式

- 手动：`/skill:<name>`，可带参数，如 `/skill:bio-single-cell-preprocessing`
- 自动：模型根据 frontmatter 的 `description` / `whenToUse` 自动触发（`disableModelInvocation: true` 或 `type: flow` 可关闭）

### 4. 本仓库的 bio_skills 安装

`skills/bio_skills/` 是 561 个生信技能的合集（目录约定：`<分类>/<技能>/SKILL.md`，安装后统一命名 `bio-<分类>-<技能>`）。安装到 Kimi Code CLI：

```bash
# 项目级安装（推荐，装入本仓库 .agents/skills/）
./skills/bio_skills/install-kimi.sh --project

# 只装某几个分类
./skills/bio_skills/install-kimi.sh --project --categories "single-cell,variant-calling"

# 用户级安装（所有项目可用，装入 ~/.kimi-code/skills/）
./skills/bio_skills/install-kimi.sh

# 预览 / 更新 / 卸载
./skills/bio_skills/install-kimi.sh --project --dry-run
./skills/bio_skills/install-kimi.sh --project --update
./skills/bio_skills/install-kimi.sh --project --uninstall
```

> 提示：全量安装 561 个技能会让每个会话的技能索引显著变长（所有 name+description 常驻上下文）。日常建议用 `--categories` 按需安装。

---

## 二、OmicHub 平台内部 Skill

### 1. 目录与机制

| 位置 | 作用 |
|---|---|
| `data/ai/skill_marketplace/<skill_id>/` | 内置技能市场：随仓库发布的**可安装**技能文件夹，文件夹名即 `skill_id` |
| `data/ai/skills/<skill_id>/` | 已安装技能目录（磁盘真相源，含 L3 `scripts/`、`references/`、`assets/`） |
| DB `SkillModel` | 技能索引（L1 元数据 + L2 正文缓存） |
| `data/ai/<agent>.yaml` 的 `skill_ids` | **Agent 与 Skill 的挂载点** |

挂载流程：在 Agent 的 YAML（如 `data/ai/scrna.yaml`）的 `skill_ids` 中声明技能 id；服务启动时 `AgentService._ensure_configured_marketplace_skills()` 会检查 `skill_marketplace/<skill_id>/SKILL.md` 是否存在，存在且未入库则自动安装（`SkillImportService.install_marketplace`），无需手工入库。

SKILL.md 解析要求（`src/omichub/infrastructure/skills/skillmd.py`）：frontmatter 必填 `name`、`description`；单技能文件夹总量上限 1 MiB，单文件 512 KiB。

### 2. 单细胞 Agent 的技能挂载

单细胞分析师 `agent-scrna`（`data/ai/scrna.yaml`）当前已挂载：

- 细胞注释：`human-mouse-cell-annotation`、`plant-cell-annotation`
- scRNA 可执行技能集（来源 `pipelines/scrna/skills/`）：`scrna-pipeline-overview`、`scrna-object-convert`、`scrna-recluster`、`scrna-annotation-ref`、`scrna-tcell-projectils`、`scrna-deg-analysis`、`scrna-annotation-stats`、`scrna-quarto-report`
- inferCNV 工具：`scrna-seq`

此外已将 bio_skills 的 17 个单细胞技能发布到市场并挂载到 `agent-scrna`（id 均为 `bio-single-cell-*`，对应 `skills/bio_skills/single-cell/` 下的同名子目录）：

`bio-single-cell-batch-integration`、`bio-single-cell-cell-annotation`、`bio-single-cell-cell-communication`、`bio-single-cell-clustering`、`bio-single-cell-cnv-inference`、`bio-single-cell-data-io`、`bio-single-cell-differential-abundance`、`bio-single-cell-doublet-detection`、`bio-single-cell-hashing-demultiplexing`、`bio-single-cell-lineage-tracing`、`bio-single-cell-markers-annotation`、`bio-single-cell-metabolite-communication`、`bio-single-cell-multimodal-integration`、`bio-single-cell-perturb-seq`、`bio-single-cell-preprocessing`、`bio-single-cell-scatac-analysis`、`bio-single-cell-trajectory-inference`

新增挂载的标准操作：

1. 把技能文件夹复制到 `data/ai/skill_marketplace/<skill_id>/`（文件夹名 = skill_id，含 `SKILL.md`）。
2. 在目标 Agent 的 `data/ai/<agent>.yaml` 的 `skill_ids` 列表追加该 id。
3. 重启服务，自动安装生效。

---

## 参考

- Kimi Code CLI 官方文档：https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html
- OmicHub Skill 设计规范：`Protocol/Skill_design.md`
- bio_skills 合集说明：`skills/bio_skills/README.md`
