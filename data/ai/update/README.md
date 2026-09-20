# CygnusX AI Agent 配置与平台挂载指南

`data/ai/` 是 CygnusX 内置 AI Agent、提示词、工具权限、Skill、MCP 绑定和 Studio
运行时配置的声明式根目录。本文说明当前所有内置 Agent 的能力边界，重点记录 RNA-seq
Agent 的组成，并给出创建、挂载、同步和验证 Agent 的标准流程。

所有领域知识库源文件统一存放在 `docs/knowledge/`；目录规范见
`docs/knowledge/README.md`。

## 1. 目录职责

| 路径 | 用途 |
| --- | --- |
| `data/CygnusX.yaml` | 平台启用的内置 Agent 清单；只有加入 `agents.enabled` 的 YAML 才会加载。 |
| `data/ai/*.yaml` | 单个内置 Agent 的身份、能力、模型参数、工具包、Skill、MCP 和运行时声明。 |
| `data/ai/agent_ability.yaml` | 所有启用 Agent 的可路由能力、边界、转交条件和推荐输入；运行时按 mtime 热重载。 |
| `data/ai/prompts/*.md` | Agent 的权威系统提示词。 |
| `data/ai/prompts/shared/` | 多 Agent 共用的运行时协议；当前由加载器追加沙盒协议。 |
| `data/ai/prompts/legacy_agents/` | 迁移前提示词，仅供比对，不参与运行时加载。 |
| `data/ai/tools/*.yaml` | 可复用的最小权限工具包；详细格式见 `data/ai/tools/README.md`。 |
| `data/ai/skill_marketplace/<skill-id>/` | 内置 Skill 的可安装来源和版本元数据。 |
| `data/ai/skills/<skill-id>/` | 已安装到平台运行时、可由 Agent 挂载的 Skill。 |
| `data/ai/mas/` | 多 Agent 编排、路由和工具执行策略。 |
| `data/ai/providers.yaml` | 当前模型提供方实例配置。 |
| `data/ai/provider_templates.yaml` | 内置模型提供方模板。 |
| `data/ai/runtime_images.yaml` | Studio/沙盒运行时镜像定义。 |
| `data/ai/studio.yaml` | Studio 默认运行参数和沙盒配置。 |

所有默认路径由 `src/cygnusx/core/config.py` 管理，并可通过对应环境变量覆盖。

## 2. 平台加载与挂载链路

内置 Agent 的平台挂载链路如下：

```text
data/CygnusX.yaml: agents.enabled
        │
        ▼
data/ai/<agent>.yaml
        ├── prompt_file ──────► data/ai/prompts/*.md
        ├── tool_packs ───────► data/ai/tools/*.yaml
        │                         ├── builtin_tools
        │                         ├── platform_tools
        │                         ├── mcp_ids + mcp_tools
        │                         └── skill_ids
        ├── mcp_ids/mcp_tools ─► 已注册 MCP Server
        ├── skill_ids ─────────► Skill 市场自动安装并挂载
        └── runtime_profile ───► Studio 运行时镜像/资源配置
        │
        ▼
AgentLoader.load_agent_configs()
        │
        ▼
AgentService.ensure_builtin_agents()
        │
        ▼
数据库 Agent 模板、会话上下文和工具权限
```

关键实现位置：

- `src/cygnusx/infrastructure/config/agent_loader.py`：读取启用清单、Agent YAML、提示词、
  Tool Pack 和 Studio Runtime Profile，并合并最终声明。
- `src/cygnusx/application/services/agent_service.py`：将内置 Agent 同步到数据库，安装声明的
  Marketplace Skill，并在会话创建时组装模型、MCP、Skill、工具和交接上下文。
- `src/cygnusx/main.py`：应用启动时执行内置 Agent 同步。
- `scripts/sync_builtin_agents.py`：不重启服务时手动同步内置 Agent。

读取 Agent 列表也会触发幂等同步。配置中的 `mcp_ids` 和 `skill_ids` 会追加到已存在的内置
Agent；声明 `features.managed_prompt: true` 或 `features.managed_profile: true` 后，对应字段会以
YAML 为权威来源持续同步，避免后台临时编辑造成配置漂移。

## 3. 当前内置 Agent 清单

以下 Agent 均已在 `data/CygnusX.yaml` 的 `agents.enabled` 中启用。

| 配置 / Agent ID | 名称 | 主要能力范围 | 默认入口 | 引擎 / Runtime |
| --- | --- | --- | --- | --- |
| `router.yaml` / `agent-router` | 星尘 AI | 统一理解用户意图，选择专家并组织交接；不替代领域专家执行完整分析。 | Chat | Legacy / `analysis-core` |
| `general.yaml` / `agent-general` | 通用助手 | 需求澄清、研究设计、数据契约、质量控制计划、跨专家协调和综合方案。 | Chat | LangGraph / `analysis-core` |
| `rnaseq.yaml` / `agent-rnaseq` | RNA-seq 分析师 | Bulk RNA-seq 原理咨询、实验设计、QC、差异表达、富集、网络分析、流水线执行与结果解释。 | Studio | LangGraph / `analysis-core` |
| `atacseq.yaml` / `agent-atacseq` | ATAC-seq 分析师 | Bulk ATAC-seq、染色质开放性、实验设计、QC、峰识别、差异可及性、motif/footprinting 与多组学解释。 | Studio | LangGraph / `analysis-core` |
| `scrna.yaml` / `agent-scrna` | 单细胞分析师 | 单细胞质控、整合聚类、细胞注释、Marker、轨迹、通讯和完整分析规划。 | Studio | LangGraph / `analysis-scrna` |
| `scrna_upstream.yaml` / `agent-scrna-upstream` | 单细胞上游与样本质控专家 | FASTQ、Cell Ranger、建库 Chemistry、样本纳入、原始矩阵和上游 QC。 | Studio | LangGraph / `analysis-scrna` |
| `scrna_integration.yaml` / `agent-scrna-integration` | 单细胞整合与聚类专家 | 细胞 QC、双细胞、批次校正、HVG、降维、聚类和 Marker 初筛。 | Studio | LangGraph / `analysis-scrna` |
| `scrna_advanced.yaml` / `agent-scrna-advanced` | 单细胞注释与高级分析专家 | 注释验证、Pseudobulk、通路、可视化、轨迹和细胞通讯。 | Studio | LangGraph / `analysis-scrna` |
| `code.yaml` / `agent-code` | 代码助手 | Python、R、Bash 脚本设计、调试、沙盒执行和可复现性说明。 | Studio | Legacy / `analysis-core` |
| `viz.yaml` / `agent-viz` | 可视化助手 | 统计图、出版级绘图、图表说明、结果报告呈现和绘图脚本。 | Studio | Legacy / `analysis-plot` |
| `data.yaml` / `agent-data` | 数据管理员 | BioOps Case 内部的数据契约、项目元数据、样本表和输入完整性预检。当前为无专用 Skill 的骨架。 | Studio | LangGraph / `analysis-core` |
| `qc.yaml` / `agent-qc` | 质量审计员 | 测序原始数据、预处理、比对覆盖、变异/区间文件、跨样本报告与 Artifact 的独立质量审查。 | Studio | LangGraph / `analysis-core` |
| `delivery.yaml` / `agent-delivery` | 交付报告员 | BioOps Case 内部的交付 manifest、运行说明和证据汇总。当前为无专用 Skill 的骨架。 | Studio | LangGraph / `analysis-core` |
| `cloud_ops.yaml` / `agent-cloud-ops` | 云运维工程师 | 管理员平台健康巡检、云资源与存储检查、故障分诊、容量风险和变更/回滚方案审查。 | Studio | LangGraph / `analysis-core` |
| `shania.yaml` / `shania` | 傻妞 | 通用对话、数据与基因问题、多组学思路和研究陪伴。 | Chat | Legacy / `analysis-core` |
| `mcp_builder.yaml` / `agent-mcp-builder` | MCP 构建师 | 从自然语言生成、测试、注册和审查 MCP Server，支持临时 TTL 与人工复核。 | Studio | Legacy / `analysis-core` |
| `skill_builder.yaml` / `agent-skill-builder` | 技能构建师 | 把可复用任务样例沉淀为符合 OSDP 的 Skill 候选包，写入候选区等待人工晋升。 | Studio | Legacy / `analysis-core` |

### 3.1 Agent 工具与 Skill 范围

| Agent | Tool Pack | 主要 Skill |
| --- | --- | --- |
| 星尘 AI | `workspace`, `agentteams_case` | 无固定领域 Skill，主要负责路由和编排。 |
| 通用助手 | `workspace`, `research`, `memory`, `handoff`, `subagents`, `agentteams_case` | BLAST、基因组工具、ATAC、MAF/GISTIC2、突变模式。 |
| RNA-seq 分析师 | `workspace`, `research`, `rnaseq`, `memory`, `handoff`, `subagents`, `agentteams_case` | RNAFlow、DEG、富集、表达矩阵、文库链特异性、WGCNA、rMATS、组织特异基因、GFF/GO/KEGG、FASTQ Screen、交付与 MD5。 |
| ATAC-seq 分析师 | `workspace`, `research`, `atacseq`, `memory`, `handoff`, `subagents`, `agentteams_case` | ATACFlow、ATAC 工具集、基因组工具、差异分析、富集、FASTQ Screen、GFF/GO/KEGG、交付与 MD5。 |
| 单细胞分析师 | `workspace`, `research`, `memory`, `handoff`, `agentteams_case`, `scrna` | 人/鼠与植物注释、流程总览、对象转换、重聚类、参考注释、T 细胞映射、DEG、注释统计、Quarto 报告、scRNA-seq。 |
| 单细胞上游专家 | `workspace`, `research`, `memory`, `handoff`, `agentteams_case`, `scrna` | FASTQ Screen、scRNA 流程总览。 |
| 单细胞整合专家 | `workspace`, `research`, `memory`, `handoff`, `agentteams_case`, `scrna` | 对象转换、重聚类。 |
| 单细胞高级专家 | `workspace`, `research`, `memory`, `handoff`, `agentteams_case`, `scrna` | 注释、对象转换、重聚类、参考映射、T 细胞映射、DEG、统计和报告。 |
| 代码助手 | `workspace`, `handoff`, `subagents`, `agentteams_case` | 软件管理、日志插件、MD5、数据交付。 |
| 可视化助手 | `workspace`, `visualization`, `handoff`, `agentteams_case` | R 绘图库、DotPlot。 |
| 数据管理员 | `workspace`, `memory`, `handoff`, `agentteams_case` | 暂无专用 Skill；后续挂载项目预检与元数据校验 Skill。 |
| 质量审计员 | `workspace`, `memory`, `handoff`, `agentteams_case` | 暂无专用 Skill；后续挂载 QC 规则、任务状态与 Artifact 审查 Skill。 |
| 交付报告员 | `workspace`, `memory`, `handoff`, `agentteams_case` | 暂无专用 Skill；后续挂载交付 manifest、runbook 与证据归档 Skill。 |
| 云运维工程师 | `cloud_ops`, `research`, `memory`, `handoff`, `subagents`, `agentteams_case` | 管理员专用只读平台健康检查，以及任务、流程、账户和工作区证据读取。 |
| 傻妞 | `workspace`, `research`, `memory`, `handoff` | 无固定 Skill，按通用研究上下文工作。 |
| MCP 构建师 | `workspace`, `memory`, `handoff` | MCP Server 构建工作台（六阶段工作流与代码模板，见 §11.7）。 |
| 技能构建师 | `workspace`, `research`, `memory`, `handoff`, `agentteams_case` | 无固定 Skill；能力由提示词和沙箱生成逻辑提供。 |

Agent 的能力边界由提示词与实际挂载权限共同决定。只在提示词中写“可以调用某工具”不会产生
权限；必须通过 Tool Pack、`mcp_ids`、`mcp_tools` 或 `skill_ids` 完成真实挂载。

### 3.2 Agent 提示词统一章节规范

所有运行中的 Agent 源提示词都必须直接以以下 H2 章节、且按此顺序组织。领域 Agent 可以在
`## 领域补充规范` 中增加专业内容，但不能删除或依赖加载器补齐这些基础语义。

```text
角色与职责边界
对话与执行模式
输入确认
知识检索与证据规则
方法论与专业决策
工具、Skill 与工作区协议
执行确认与安全边界
输出与交付规范
失败、降级与诚实约束
转介、交接与协作
```

每个 Agent 的 Markdown 应保留自己的领域内容；上述章节负责回答“能做什么、不能做什么、需要
什么输入、何时检索、何时调用工具、何时等待确认、如何交付、失败如何降级、何时转交”。不要把
工具权限只写在提示词中，真实权限仍以 `data/ai/tools/*.yaml`、`mcp_ids`、`mcp_tools` 和
`skill_ids` 为准。

### 3.3 动态 Agent 能力目录

`data/ai/agent_ability.yaml` 是运行时转交目录的能力增强信息。每个启用 Agent 必须登记：

- `summary`：给其他 Agent 展示的一句话定位；
- `capabilities`：可处理的任务和专业能力；
- `not_suitable_for`：明确不应继续处理的任务；
- `handoff_when`：应触发转交的条件；
- `preferred_inputs`：转交或开始工作时优先收集的输入。

`AgentService` 会把当前数据库中 active 且通过 `handoff.allowed_targets` 白名单的 Agent，与
这份 YAML 合并成运行时目录并注入当前 Agent。修改该文件后不需要重启服务；下一次组装 Agent
上下文时会按文件 mtime 重新加载。能力目录只影响“如何判断与描述候选 Agent”，不会绕过现有
的 handoff 白名单、active 状态、路由 Agent 排除和最大跳转次数校验。

## 4. RNA-seq Agent

RNA-seq Agent 是当前 Bulk RNA-seq 的统一领域入口，配置文件为 `data/ai/rnaseq.yaml`。

### 4.1 能力范围

- **学习与咨询**：解释 RNA-seq 原理、测序设计、重复数、链特异性、批次效应、统计模型和常见误区。
- **方案设计**：根据研究问题、分组、协变量、物种、建库类型和输入文件生成分析计划与数据契约。
- **数据质控**：识别 FASTQ、计数矩阵、表达矩阵和样本表，规划原始数据、比对、定量和样本级 QC。
- **差异表达**：设计比较、协变量和对比矩阵，执行或指导 DEG 分析，并解释效应量、显著性和批次影响。
- **生物学解释**：进行 GO/KEGG 富集、组织特异基因、WGCNA、可变剪接和结果交叉验证。
- **平台执行**：准备 RNA-seq 任务、提交流水线、查询状态和结果，并生成火山图等基础图表。
- **协同交付**：可向代码、可视化或其他领域 Agent 交接，也可创建并行子任务和 AgentTeams Case。

默认输出包括分析计划、DEG 表、通路表和生物学解释。Agent 不应伪造未执行的结果，也不应在
缺少关键元数据时直接给出确定性结论。

### 4.2 RNA-seq 组成

| 资源 | 路径 | 作用 |
| --- | --- | --- |
| Agent 声明 | `data/ai/rnaseq.yaml` | 身份、能力、输入输出、模型参数和全部挂载关系。 |
| 系统提示词 | `data/ai/prompts/rnaseq.md` | 咨询、规划、执行、知识检索和交付规范。 |
| 专用工具包 | `data/ai/tools/rnaseq.yaml` | RNA-seq 内置工具、平台工具、MCP 和白名单。 |
| Skill 市场源 | `data/ai/skill_marketplace/rnaflow/SKILL.md` | RNAFlow Skill 的内置安装来源。 |
| 执行镜像 Skill | `pipelines/tools/skills/rnaflow/SKILL.md` | 流水线执行侧使用的 Skill 镜像。 |
| 已安装 Skill | `data/ai/skills/rnaflow/SKILL.md` | 平台运行时可挂载版本。 |
| 知识导入脚本 | `scripts/import_rnaseq_knowledge.py` | 将 RNA-seq 文档发布并索引到平台知识库。 |
| Agent 同步脚本 | `scripts/sync_builtin_agents.py` | 将 YAML 声明同步到 Agent 数据库。 |

### 4.3 RNA-seq 工具权限

`rnaseq` Tool Pack 按最小权限原则组合以下能力：

- **CygnusX 内置工具**：RNA-seq 任务准备、任务状态和摘要、KEGG 富集、火山图。
- **平台工具**：Flow/Task 查询、工作区文件读取和结果下载。
- **CygnusX Pipelines MCP**：流水线列表、参数检查、RNA-seq 输入准备、提交、状态与结果查询。
- **Ensembl MCP**：物种和组装查询、基因检索、转录本、外部引用、序列和 CDS 查询。
- **GO MCP**：GO 搜索、术语详情、ID 校验和统计。
- **Skill**：通过 `rnaflow` 获取完整执行约定；其他 RNA-seq Skill 由 Agent YAML 直接挂载。

外部 MCP UUID 和允许调用的精确工具名以 `data/ai/tools/rnaseq.yaml` 为准。修改 MCP Server
后应同步更新 `mcp_ids` 和 `mcp_tools`，不要仅依赖服务端自动发现的全部工具。

### 4.4 RNA-seq 知识库

RNA-seq Agent 的提示词要求先检索平台知识库，再使用本地 Skill 和工具执行。导入命令：

```bash
DATABASE_URL='postgresql+asyncpg://...' \
  uv run python scripts/import_rnaseq_knowledge.py \
  --admin-user-id '<管理员 UUID>'
```

导入前可执行预检：

```bash
uv run python scripts/import_rnaseq_knowledge.py \
  --admin-user-id '<管理员 UUID>' \
  --dry-run
```

脚本会创建或更新 `rnaseq` 知识库，发布 `docs/knowledge/rna-seq/RNA-seq.md`，修正文档中的
PDF 链接并重新建立检索分块。知识库负责稳定事实和平台规范，Skill 负责操作流程，实时工具负责
任务状态和实际结果，三者不应相互替代。

## 5. ATAC-seq Agent

ATAC-seq Agent 是 Bulk ATAC-seq 与染色质开放性分析的统一领域入口，配置文件为
`data/ai/atacseq.yaml`。

### 5.1 能力范围

- **原理与实验设计**：染色质开放性、核小体、Tn5、建库、重复、测序深度和参考选择。
- **ATAC 特异质控**：片段周期性、TSS enrichment、FRiP、library complexity、organellar
  reads、blacklist、重复一致性和样本相关性。
- **峰与差异分析**：MACS2/MACS3、pooled peaks、IDR、consensus peaks、峰计数矩阵和差异可及性。
- **调控解释**：peak annotation、GO/KEGG、已知/de novo motif、TF activity、TOBIAS
  footprinting 和 peak-to-gene 关联。
- **多组学整合**：与 RNA-seq 联合建立开放性、TF、靶基因表达证据链，并区分相关与因果。
- **平台执行**：通过 ATACFlow MCP 完成数据检查、预检、确认后提交、状态追踪和结果读取。

### 5.2 ATAC-seq 组成

| 资源 | 路径 | 作用 |
| --- | --- | --- |
| Agent 声明 | `data/ai/atacseq.yaml` | 身份、能力、输入输出、模型参数和挂载关系。 |
| 系统提示词 | `data/ai/prompts/atacseq.md` | 咨询、设计、执行、解释和安全护栏。 |
| 专用工具包 | `data/ai/tools/atacseq.yaml` | ATACFlow、Ensembl、GO、平台任务和结果工具白名单。 |
| 完整流程 Skill | `data/ai/skill_marketplace/atacflow/SKILL.md` | ATACFlow 输入、流程、QC 与平台确认协议。 |
| 专项工具 Skill | `data/ai/skill_marketplace/atac-tools/SKILL.md` | TSS BED 和峰计数矩阵构建。 |
| 知识库源 | `docs/knowledge/atac-seq/` | 3 篇 Markdown、12 个 PDF 和 24 个图片资源。 |
| 知识导入脚本 | `scripts/import_atacseq_knowledge.py` | 全量同步 Markdown 并索引到 `atacseq` 知识库。 |

### 5.3 ATAC-seq 知识库导入

```bash
DATABASE_URL='postgresql+asyncpg://...' \
  uv run python scripts/import_atacseq_knowledge.py \
  --admin-user-id '<管理员 UUID>'
```

预检使用 `--dry-run`。脚本会遍历 `docs/knowledge/atac-seq/**/*.md`，为每篇文档维护稳定 ID、
修订和检索分块；相对附件链接会改写为 `/docs-static/knowledge/atac-seq/...`。PDF 和图片作为
静态附件保留，所有 36 个附件均登记在 `docs/knowledge/atac-seq/README.md`。需要被 AI 检索的
PDF 信息应整理进 Markdown 正文。

## 6. 创建一个新的内置 Agent

内置 Agent 适合需要随代码部署、可审计、可在不同环境重复安装的专家。建议按以下顺序创建。

### 第一步：编写权威提示词

在 `data/ai/prompts/<agent-key>.md` 创建系统提示词，至少明确：

- 身份、服务对象和能力边界；
- 支持的输入和期望输出；
- 工具调用前置条件与禁止事项；
- 何时检索知识库、加载 Skill、调用 MCP 或交接其他 Agent；
- 证据、可复现性、隐私和高风险操作规则。

提示词正文按“3.2 Agent 提示词统一章节规范”组织。推荐先参考
`data/ai/prompts/rnaseq.md` 的领域写法，并在统一章节后维护领域补充规范。

### 第二步：创建 Agent YAML

在 `data/ai/<agent-key>.yaml` 创建声明。以下模板展示常用字段；字段名和已有 Agent 保持一致：

```yaml
agent_id: agent-example
name: 示例分析师
description: 示例领域的咨询、规划、执行和解释专家。
category: analysis
prompt_file: prompts/example.md

# 与 prompt_file 同步登记到 data/ai/agent_ability.yaml

tool_packs:
  - workspace
  - research
  - handoff

skill_ids:
  - example-skill

temperature: 0.4
is_active: true

features:
  engine: langgraph
  managed_prompt: true
  managed_profile: true
  capability_scope:
    - 示例质控
    - 示例统计分析
  accepts_inputs:
    - sample-metadata
    - example-matrix
  produces_outputs:
    - domain-analysis-plan
    - result-table

studio:
  enabled: true
  default_mode: studio
  runtime_profile: analysis-core
  required_capabilities:
    - python
    - statistics
```

建议使用稳定的 `id` 和文件键。Agent 已进入生产数据库后不要随意改 ID，否则同步时会被视为
一个新的 Agent。

### 第三步：加入启用清单

在 `data/CygnusX.yaml` 中把文件键加入：

```yaml
agents:
  enabled:
    - example
```

这里写的是 `data/ai/example.yaml` 的文件名，不是 `agent-example`。

### 第四步：挂载工具能力

优先复用 `data/ai/tools/` 中的 Tool Pack。需要新的权限集合时创建
`data/ai/tools/<pack-id>.yaml`：

```yaml
id: example-analysis
description: 示例 Agent 的最小工具集合。

builtin_tools:
  - cygnusx_example_tool

platform_tools:
  - list_workspace_files
  - read_workspace_file

mcp_ids:
  - "<已注册 MCP Server UUID>"

mcp_tools:
  "<已注册 MCP Server UUID>":
    - allowed_tool_one
    - allowed_tool_two

skill_ids:
  - example-skill
```

工具类别：

- `builtin_tools`：`tool_configs/tools_schema.yaml` 中注册的 CygnusX 内置函数。
- `platform_tools`：内置 `cygnusx-platform` MCP 暴露的平台工具。
- `mcp_ids`：已注册 MCP Server 的 UUID。
- `mcp_tools`：每个 MCP Server 对该 Agent 暴露的工具白名单。
- `skill_ids`：随 Tool Pack 一起附加的 Skill。

Agent YAML 可以直接声明 `mcp_ids`、`mcp_tools` 和 `skill_ids`，也可以通过 Tool Pack
复用。加载器会合并并去重；跨 Agent 通用的权限集合应放入 Tool Pack，专属能力可以直接写在
Agent YAML 中。

YAML 不直接执行任意 Python、R 或 Bash。自定义程序必须先注册为内置工具、平台工具或 MCP
工具，保留参数 Schema、认证、审计和确认闸门，再授权给 Agent。

### 第五步：创建并挂载 Skill

Skill 适合承载操作规程、领域工作流和按需读取的参考资料，不适合隐藏不可审计的执行代码。

1. 在 `data/ai/skill_marketplace/<skill-id>/SKILL.md` 创建可安装 Skill。
2. 如该 Skill 还被流水线执行环境使用，在 `pipelines/tools/skills/<skill-id>/` 维护执行镜像。
3. 在 Agent YAML 或 Tool Pack 的 `skill_ids` 中声明 `<skill-id>`。
4. 启动或手动同步时，内置 Marketplace Skill 会自动安装到平台并挂载到 Agent。

运行时先把 Skill 索引提供给模型；模型通过 `use_skill` 按需加载正文，并可继续读取 Skill
声明的资源文件。这能控制上下文体积，避免把长流程全部塞入系统提示词。

### 第六步：注册并挂载 MCP

MCP Server 必须先进入平台注册表，再把返回的 UUID 写入 Agent 或 Tool Pack。

- 管理员接口支持注册、更新、删除、连接测试、工具发现、版本查看和回滚。
- 内置 MCP 预设可通过 MCP 管理接口执行热加载。
- 注册后先测试连接并查看工具列表，再配置 `mcp_tools` 白名单。
- 涉及写文件、提交任务、外部网络或高成本操作时，仅暴露必要工具，并在提示词中定义确认条件。

不要把 MCP 显示名称写进 `mcp_ids`；该字段必须使用平台数据库中的 Server UUID。

### 第七步：选择 Studio Runtime

需要代码执行或大型依赖的 Agent 应指定 `runtime_profile`：

- `analysis-core`：通用分析、RNA-seq 和代码任务；
- `analysis-scrna`：单细胞依赖环境；
- `analysis-plot`：绘图与可视化环境。

新增 Runtime 时，同时更新 `data/ai/runtime_images.yaml` 和相关 Studio 配置，并确认镜像、
CPU、内存、工作目录和持久化策略符合平台安全要求。

### 第八步：同步到平台

应用启动会自动同步。需要立即刷新时执行：

```bash
DATABASE_URL='postgresql+asyncpg://...' \
  uv run python scripts/sync_builtin_agents.py
```

同步后从前台 Agent 列表或管理员 Agent 页面确认：Agent 已启用、提示词版本正确、Skill 已安装、
MCP 已绑定、默认会话类型和 Runtime Profile 正确。

## 7. 创建数据库自定义 Agent

平台同时提供管理员 Agent CRUD，可创建只存在于当前数据库的自定义 Agent：

- `GET /api/v1/admin/agents`：查看全部 Agent，包括停用项；
- `POST /api/v1/admin/agents`：创建 Agent；
- `PUT /api/v1/admin/agents/{agent_id}`：更新 Agent；
- `POST /api/v1/admin/agents/{agent_id}/toggle`：启用或停用；
- `POST /api/v1/admin/agents/{agent_id}/set-default`：设为默认 Agent；
- `DELETE /api/v1/admin/agents/{agent_id}`：删除 Agent。

普通用户通过 `GET /api/v1/agents` 获取已启用 Agent，通过
`GET /api/v1/agents/{agent_id}` 获取详情。

数据库自定义 Agent 适合临时验证和单环境运营配置，但不会自动生成 `data/ai/*.yaml`，也不能
代替代码仓库中的可复现声明。需要长期维护、跨环境部署或随版本发布的 Agent，应回写为内置
YAML；启用 `managed_prompt` 或 `managed_profile` 的内置 Agent 会覆盖数据库中的对应人工修改。

## 8. 交接、多 Agent 与记忆

- 挂载 `handoff` 后，Agent 可使用 `transfer_to_agent` 把结构化上下文交给其他专家。
- 挂载 `subagents` 后，Agent 可使用 `parallel_subagents` 拆分互不依赖的并行子任务。
- 挂载 `agentteams_case` 后，Agent 可创建长期、多角色协作 Case。
- 挂载 `memory` 后，Agent 可保存、更新、删除和检索当前认证用户的长期记忆。
- `memory` 工具始终从认证上下文读取 `user_id`，模型参数不能指定其他用户。

只有确实需要跨会话研究上下文的 Agent 才应挂载长期记忆。交接时应传递研究问题、输入文件、
样本设计、已完成步骤、关键结果、限制和期望产物，不应只发送一句自然语言任务。

### 8.1 Handoff 白名单与路由会话的源 Agent 规范

Agent YAML 顶层的 `handoff:` 段由加载器合并进 `features.handoff`（见
`agent_loader.py`），运行时白名单校验只读数据库中的 `features.handoff`：

```yaml
handoff:
  allowed_targets: ["agent-code", "agent-viz"]  # 或 ["*"] 放行全部活跃 Agent
  max_hops_per_session: 10                       # 可选，默认 10，上限 10
```

- `allowed_targets` 为空或未声明 `handoff:` 段时，该 Agent 发起的所有 `transfer_to_agent`
  都会被拒绝（"目标 Agent 不在当前 Agent 的转交白名单中"）。
- 使用 `"*"` 时仍不能转交给带 `features.router: true` 的路由 Agent。
- 每会话转交次数上限为 10（`max_hops_per_session`，默认值与服务端上限均为 10），第 11 次
  转交会被"本会话最多允许 10 次转交"拒绝。
- 回转交必须携带新增信息：转回本会话历史中曾经作为源出现过的 Agent 时，`reason` 少于
  16 个字符会被拒绝（"回转交必须在转交原因中说明新增信息"）。这两条规则已写入所有挂载
  `handoff` 的 Agent 可见的 `HANDOFF_SYSTEM_PROMPT_SUFFIX`，模型应主动遵守而不是依赖
  服务端报错。
- 提示词中的"当前可转交的 Agent"目录按同一白名单生成，配置变更后须重启或手动同步
  内置 Agent，避免目录与校验结果不一致。

**星尘 AI（agent-router）路由会话的关键约定**：路由入口会话的 `session.agent_id`
恒为 `agent-router`（每条消息重新路由、会话绑定不变），但路由后执行上下文 `ctx` 已切换为
目标专家。因此所有按"当前 Agent"校验的运行时逻辑——包括 handoff 白名单——必须以路由后的
实际执行 Agent（`ctx.agent.agent_id`）为准，严禁使用会话绑定的 `agent_id`。`agent-router`
自身不声明 `handoff:` 段、不挂载 `handoff` Tool Pack；若以会话绑定 Agent 校验，白名单恒为空，
会导致所有专家间转交被拒（2026-08 曾因此全平台转交流转失败，`chat_handoff_events` 零记录）。
参考实现：`chat_service.py` 主流路径的 `ToolInvocationContext(agent_id=str(ctx.agent.agent_id))`。

## 9. 配置校验清单

提交 Agent 变更前至少检查：

- Agent 文件键已加入 `data/CygnusX.yaml`，且 `id` 未与现有 Agent 冲突；
- `prompt_file`、Tool Pack、Skill 和 Runtime Profile 路径均存在；
- MCP UUID 已注册且健康，`mcp_tools` 名称与服务端发现结果一致；
- 写操作、高成本操作和外部网络操作遵守最小权限原则；
- Skill 市场源、运行时安装版本和流水线镜像没有无意漂移；
- `features.accepts_inputs` / `produces_outputs` 与提示词实际承诺一致；
- `studio.default_mode` 与 Agent 是否需要 Studio 执行环境一致；
- 配置同步后，前台可见性、欢迎语、头像、模型参数和工具调用均符合预期。

可执行针对性测试：

```bash
uv run pytest \
  tests/unit/test_agent_loader_studio.py \
  tests/unit/test_agent_router.py \
  tests/unit/test_agent_router_dispatch.py \
  tests/unit/test_prompt_config_contract.py \
  -q
```

## 10. 提示词体积护栏

新增或修改 `data/ai/prompts/*.md` 时，单个提示词超过 120 行必须在 PR 中说明为什么不能下沉到
Skill、知识文件或 Domain Pack。跨 Agent 复用的协议应放入 `data/ai/prompts/shared/`，由加载器
统一追加；稳定领域知识进入知识库，长操作流程进入 Skill，动态状态交给实时工具。

## 11. 框架现状评估与可优化项

通读加载链路（`agent_loader.py`）、运行时路由（`chat_service.py`）和当前全部 Agent
YAML 后，记录以下值得关注的设计债务，按影响面排序。

### 11.1 LangGraph / Legacy 双执行路径没有在文档中体现

当前 12 个内置 Agent 里，`general`、`rnaseq`、`atacseq`、`scrna`、`scrna_upstream`、
`scrna_integration`、`scrna_advanced` 声明了 `features.engine: langgraph`，其余
（`router`、`code`、`viz`、`shania`、`mcp_builder`、`orchestrator`）没有声明，走
`chat_service.py` 里手写的 legacy 循环。这两条路径对工具调用副作用（`tool_invocations`、
timeline 落库、handoff 事件等）是**各自独立实现**的，历史上已经出现过只改一条路径导致
另一条路径静默丢功能的问题（Plotly 图表卡片刷新后消失）。本文档第 3 节的 Agent 清单
只写了"引擎"列，却没有说明这一区分会带来的实际后果。建议：

- 在第 3 节表格旁补充一句提醒：改动工具调用副作用逻辑时必须确认两条路径都已同步；
- 制定收敛计划，逐步把 `code`/`viz`/`shania`/`mcp_builder` 迁移到 LangGraph，缩小需要
  双写的代码面。

### 11.2 Handoff 白名单一致性校验 ✅ 已解决（2026-08-09）

**曾经的问题**：每个 Agent YAML 手动维护 `handoff.allowed_targets`，随专家增减容易出现
`router.md` 候选表、各 Agent 的 `allowed_targets`、数据库中生效的 `features.handoff`
三处漂移，造成"提示词说可以转交，白名单里其实没有"的静默失败（历史事故见
[[router-session-handoff-source-agent]]）。

**解决方案**：新增 `tests/unit/test_agent_config_consistency.py`，在纯文件层（不触库、
不加载重依赖，全套 <0.2s）做静态回归，覆盖：

- `test_handoff_targets_are_valid_active_agents`：`allowed_targets` 中每个目标（`"*"`
  除外）必须是已启用的 `agent_id`；
- `test_handoff_never_targets_router_or_self`：禁止转交给 `features.router` 的路由
  Agent，也禁止自转交（与 `agent_service._build_handoff_catalog` 运行时语义对齐）；
- `test_handoff_max_hops_within_server_ceiling`：`max_hops_per_session` 必须落在
  服务端上限 `[1, 10]` 内；
- `test_router_prompt_catalog_ids_exist`：`router.md` 候选表中出现的 `agent_id` 必须
  存在于运行时目录，防止提示词引用幽灵专家。

后续增删专家时若忘记同步白名单或候选表，CI 会直接红灯。维护规范见 §12。

### 11.3 模型与 Provider 高度单一化 ✅ 已解决（2026-08-14）

**曾经的问题**：13 个 Agent YAML 的 `model` 字段全部是 `qdoubao-seed-evolving`，没有按任务复杂度分层（例如给
`router` 这类低延时诉求的入口用更快的模型，给 `mcp_builder` 这类需要强代码生成能力的
用更强模型）。同时 `data/ai/providers.yaml` 里 `deepseek-v4-flash` 和 `qdoubao-seed-evolving`
同时标注 `is_default: true`，虽然同步逻辑（`ai_provider_yaml_loader.py`）只会让最后
生效的一个成为真正默认值，但 YAML 层面两条 `is_default: true` 容易误导后续维护者。
单一 Provider 也是可用性单点故障：一旦 `qdoubao-seed-evolving` 服务异常，全部 Agent 同时不可用。

**解决方案**：按"任务认知负荷"分两档（当前 providers.yaml 只有两个可用 Provider，分档到
现有模型上）：

| 档位 | 模型 | Agent | 依据 |
| --- | --- | --- | --- |
| 轻量档 | `deepseek-v4-flash` | `router`、`data`、`delivery`、`shania` | 路由分类（运行时 temp=0、max_tokens=200 输出 JSON）、清单式核验、结构化汇总、陪伴式对话，均为低温度结构化任务 |
| 推理档 | `qdoubao-seed-evolving` | 其余全部领域专家、`qc`、`orchestrator`、`mcp_builder` | 实验设计、证据链推理、审计结论、计划生成、代码生成，容错率低 |

`qc` 虽以结构化三态结论输出，但其审计结论会阻断交付，错误代价高，明确保留在推理档。
同时把 `providers.yaml` 中 `deepseek-v4-flash` 的 `is_default` 改为 `false`，全局默认
Provider 只保留 `qdoubao-seed-evolving` 一个（与此前"最后生效"的实际行为一致，无语义变化）。
模型选型准则沉淀为 §12.5。

**尚未解决**：单一 Provider 的可用性单点故障仍在（flash 与 plus 分属火山与阿里两家，
已缓解一半）；后续接入第三家 Provider 时可把轻量档迁到独立厂商。

### 11.4 MAS 编排层全专家登记 ✅ 已解决（2026-08-09）

**曾经的问题**：`agent_capabilities.yaml` 只登记了 `agent-code`/`agent-rnaseq`/
`agent-viz`/`agent-scrna` 四个 Agent，其余 7 个专家（`general`、`atacseq`、三个 scrna
子专家、`mcp_builder`、`shania`）未登记。`mas_plan_validator` 对未登记 Agent 会直接抛
"计划引用了未注册的 MAS Agent"，导致 `settings.mas_enabled` 打开后这些专家在编排器眼里
彻底消失。

**解决方案**：把 `data/CygnusX.yaml` 中 `agents.enabled` 的**全部 11 个专家**补进
`agent_capabilities.yaml`（router 是纯分派入口、orchestrator 是编排器本身，二者不作为
可分派节点，按设计豁免）。登记时的关键机制：

- 能力键是自由词汇表（kebab-case 功能令牌），`mas_plan_validator` 只做"已注册 + 节点
  `required_capabilities` 是能力集合子集"两道校验，不强枚举；
- `flow_registry.agent_capabilities()` 会为 `data/ai/flows/*.yaml` 中 flow 的 `actor`
  （目前 `agent-rnaseq`、`agent-scrna`）自动派生 executor 能力（如 `rnaflow`/`deseq2`/
  `scrna-cellranger` 等）并在加载时并入，因此 actor 型 Agent 只需补充非 executor 的通用
  能力；scrna 三个子专家在 flow 中是 `assistant_agent_id`（不是 actor），拿不到自动派生，
  必须手工登记其分诊/审查能力。

覆盖率由 §11.2 引入的测试保护：`test_all_expert_agents_registered_in_mas_capabilities`
（漏登记即红灯）与 `test_mas_capabilities_have_no_stale_entries`（删专家后遗留孤儿条目
即红灯）。MAS 编排层三个文件的完整职责说明见 §12.1。

### 11.5 工具包与触发词去重 ✅ 已解决（2026-08-09）

**问题一：死工具包 `development.yaml`**。它的 `platform_tools` 与 `workspace.yaml`
完全相同，且经全仓检索确认**没有任何 Agent 引用它**——`code.yaml` 实际用的是
`tool_packs: [workspace, handoff, subagents, agentteams_case]`，README 3.1 表格此前
误写成了 `development`。**处理**：删除 `data/ai/tools/development.yaml`，并修正 3.1 表格。
代码 Agent 的只读上下文能力由 `workspace` 工具包提供，语义不变。

**问题二：触发词冗余**。运行时 `chat_service.py` 的 `_requires_fresh_web_search` 已经把
一份 28 词的公共基线常量 `FRESHNESS_SEARCH_TRIGGERS`（实时/最新/最近/今天/新闻/天气/
文献/论文/研究进展/临床试验/指南/数据库更新/latest/news/pubmed 等）与 Agent 配置的
`triggers` **合并**后再做命中判断（`triggers = [*FRESHNESS_SEARCH_TRIGGERS,
*configured_triggers]`）。因此各 Agent YAML 里凡是落在基线内的词都是纯冗余。**处理**：
把所有 Agent 的 `web_search.triggers` 收敛为"仅基线之外的领域增量词"：

| Agent | 精简后的 triggers |
| --- | --- |
| router / general / rnaseq / shania / orchestrator | `[]`（全部由基线覆盖） |
| code | `[版本, 发布说明, API, 文档]` |
| viz | `[标准, 配色规范]` |
| atacseq | `[方法更新, 软件版本]` |
| scrna | `[细胞图谱]` |

改一个通用时效词现在只需改 `FRESHNESS_SEARCH_TRIGGERS` 一处。规范见 §12.3。

### 11.6 三个 scrna 子专家工具能力空心 ✅ 已解决（2026-08-14）

**曾经的问题**：`scrna_upstream`、`scrna_integration`、`scrna_advanced` 中前两者没有任何
`builtin_tools`/`skill_ids`，仅挂载 `workspace`、`research`、`memory`、`handoff`，
第 3 节表格也如实写了"当前主要依赖提示词、平台研究工具和专家交接"。这意味着这两个
子专家无法真正执行任何专项分析，只能对话和转交，实用性有限——分诊链上半段是"嘴"
下半段是"手"。

**解决方案**（两条并行）：

1. **新建 `data/ai/tools/scrna.yaml` 工具包**，绑定与 rnaseq/atacseq 包同一组已注册
   MCP Server（Ensembl `9f3a3546-…`、GO `15bb9689-…`），但按单细胞场景收敛
   `mcp_tools` 白名单：Ensembl 只暴露 `list_species`/`search_genes`/`lookup_gene`/
   `get_xrefs`（不暴露序列/CDS 拉取），GO 只暴露 `search_go_terms`/`get_go_term`/
   `validate_go_id`。四个 scrna Agent 的 `tool_packs` 统一追加 `scrna`，marker
   验证和注释审查从此有实时基因/功能证据可查。
2. **按分工补齐可执行 Skill**：`scrna_upstream` 挂载 `fastq-screen` +
   `scrna-pipeline-overview`（FASTQ 污染筛查与流程认知）；`scrna_integration` 挂载
   `scrna-object-convert` + `scrna-recluster`（对象格式转换与重聚类）。
   `scrna_advanced` 此前已有全套下游技能，本次只补工具包。

注意：scrna 流程执行（Cell Ranger 等）能力不在本次范围——`flows/scrna.yaml` 的 executor
能力由 flow 注册表自动派生给 actor `agent-scrna`，子专家定位仍是分诊/审查/咨询，
但现在审查有实时证据（MCP）和可执行手段（Skill）支撑，不再是纯对话。

**顺带澄清一个此前的误评**：曾认为"所有 Agent 的 `mcp_ids` 都是空的，没有 Agent 挂载
MCP"。实际上 MCP 挂载发生在 Tool Pack 层（`agent_loader.py` 合并 `pack.mcp_ids` +
自动附加 `cygnusx-tools`/`cygnusx-platform` 预设），rnaseq/atacseq 一直通过工具包
绑定 3 个外部 MCP；真正的缺口是 scrna 团队没有领域 MCP，本次已补齐。

### 11.7 提示词体积护栏（部分缓解，2026-08-14）

第 10 节要求超过 120 行的提示词在 PR 中说明理由，但这只是文字约定，没有 CI 校验。

**已处理**：`prompts/mcp_builder.md` 从 498 行瘦身到 89 行；`prompts/skill_builder.md`
新建即控制在 98 行。工作流/模板下沉为 Skill/references，提示词只保留统一章节、每次
编码必须成立的常量摘要、进度块输出格式和约束红线。

**仍未解决**：`prompts/visualization.md`（288 行）仍超阈值；CI 行数提醒脚本仍未添加。
建议照 mcp_builder 的模式把 visualization.md 的绘图规范下沉为 Skill 的 references，
并补 CI 统计脚本让护栏真正可执行。

### 11.8 `viz` 的 `domain: phylo` 语义错位 ✅ 已解决（2026-08-14）

**曾经的问题**：`viz.yaml` 声明了 `features.domain: phylo`，把跨领域的可视化助手绑进
系统发育域。该字段的唯一消费方是 `chat_service.py` 路由目录构建时的
`DomainRegistry.router_notes_for(agent_id, domain)`：显式 `domain` 优先于
`agent_match` 反查，直接返回对应 Domain Pack 的 `router_notes`。

**解决方案**：删除 `viz.yaml` 的 `domain: phylo`。删除后行为不变，因为：

- `router_notes_for` 回退到 `agent_match` 反查时，`domains/phylo.yaml` 的
  `tree-viz-only`/`phylogeny-build` 规则本就含 `agent_match: [agent-viz, …]`，
  phylo 提示照常命中；
- phylo Pack 的 `router_notes` 目前为空字符串，显式 domain 本就没有注入任何内容；
- omics Pack 的 `agent_match` 不含 `agent-viz`，回退查找不会错配到 omics。

可视化是跨领域能力，归属判断应完全交给各 Domain Pack 的 `agent_match` 规则，而不是
在 Agent 上钉死单一领域。

### 11.9 BioOps 三角色的 handoff 图不对称 ✅ 已解决（2026-08-14）

**曾经的问题**：`data`/`qc`/`delivery` 的 `allowed_targets` 只有 `[agent-general]`，
而 `general` 可转所有人（`"*"`）。这三个角色实际是 general 的附庸：数据预检通过后
不能直接交给领域专家，审计不通过也不能直接回退给被审计方，全部要经 general 中转，
白白消耗跳数（每会话上限 10）。

**解决方案**：按各自在分析流水线中的邻居关系扩展白名单：

| Agent | 扩展后 allowed_targets | 依据 |
| --- | --- | --- |
| `agent-data` | `agent-general`, `agent-qc`, `agent-scrna`, `agent-rnaseq`, `agent-atacseq` | 预检通过直接交接领域专家；发现质量问题转审计 |
| `agent-qc` | `agent-general`, `agent-rnaseq`, `agent-atacseq`, `agent-scrna`, `agent-delivery` | 审计不通过回退被审计专家修复；通过后转交付汇总 |
| `agent-delivery` | `agent-general`, `agent-qc`, `agent-viz`, `agent-code` | 产物未验证回退审计；缺图表/复现脚本转可视化或代码补齐 |

一致性由 `tests/unit/test_agent_config_consistency.py` 守护（目标必须是已启用 Agent、
禁止指向 router/自转交、跳数上限），本次改动后该套件全绿。另外顺带修复了
`test_agent_router_dispatch.py::test_site_yaml_enabled_agents_have_config_files`
的一处存量漂移：`cloud_ops` 早已加入 `agents.enabled` 但测试期望列表未同步。

### 11.10 Skill Builder Agent 与候选区治理 ✅ 已解决（2026-08-14）

**曾经的问题**：用户反复让 AI 做同类任务（"帮我转成 rds 再重聚类"、"画火山图"）时，
成功执行上下文无法沉淀为可复用 Skill；每次都靠提示词里的临时指令重复造轮子，既浪费
上下文又无法保证一致性。同时，如果允许 AI 自动把生成物塞进 marketplace，会迅速导致
L1 路由冲突和技能质量失控。

**解决方案**：新增内置 `agent-skill-builder`（技能构建师），走"候选 → 评审 → 晋升"的
受控闭环：

1. **Agent 与提示词**
   - `data/ai/skill_builder.yaml` + `data/ai/prompts/skill_builder.md`（98 行，符合 §10 护栏）；
   - `model: deepseek-v4-flash`（轻量结构化生成），`tool_packs` 含 workspace/research/memory/handoff/agentteams_case；
   - 提示词保留 §3.2 统一十章节，明确"只生成候选包，不代为提交/自动挂载"；
   - 产物目录约定：`/workspace/skill-candidates/<skill_id>/`。

2. **候选区约定**
   - `data/ai/skill_candidates/README.md` 定义候选区职责、状态流转、评审 checklist；
   - 候选包必须含 `SKILL.md`（OSDP frontmatter + 五段式）、`references/guide.md`、
     可执行技能还须 `references/environment.md`（A/B/C/D 依赖分级）和
     `scripts/check_env.sh`；
   - 候选包带 `CANDIDATE_MANIFEST.json`（含 `pending_review_items`），状态为
     `candidate`，不进 marketplace，不会被自动安装。

3. **晋升脚本**
   - `scripts/promote_skill_candidate.py`：把候选包复制到
     `data/ai/skill_marketplace/<skill_id>/`，做文件级校验（OSDP 解析、包大小 ≤1MiB、
     skill_id 冲突检查），支持 `--dry-run` 和 `--replace`。

4. **高频发现脚本（第二阶段）**
   - `scripts/analyze_skill_invocations.py`：读取 `skill_invocations` 表，输出最近 N 天
     Top-N 高频 Skill 榜单，并对"同一会话中没有 use_skill 调用的用户消息"做简单关键词
     分组，给出候选 Skill ID 建议（如 `h5ad-rds-workflow`、`火山-workflow`）。
   - 这回答了"哪些内容被高强度重复使用"的问题，但**不自动执行生成**，最终是否沉淀
     仍由管理员触发 `agent-skill-builder` 决定。

5. **与现有治理体系对齐**
   - 加入 `data/CygnusX.yaml: agents.enabled`；
   - 加入 `data/ai/mas/agent_capabilities.yaml`（能力键：skill-design/osdp-review/
     candidate-generation/dependency-classification/artifact-validate）；
   - 加入 `data/ai/agent_ability.yaml`；
   - 新增 `tests/unit/test_skill_builder_prompt.py`、
     `tests/unit/test_skill_candidate_promote.py`、
     `tests/unit/test_analyze_skill_invocations.py`，与一致性测试共同守护。

**明确不做**：
- 不实现全自动"检测高频 → 生成 → 安装"；`analyze_skill_invocations.py` 只输出建议，
  生成和晋升仍需人工触发；
- 不修改 marketplace 自动安装机制；
- 候选包默认不进入任何 Agent 的 `skill_ids`。

## 12. MAS 编排层与配置维护规范

本节沉淀 §11.2 / §11.4 / §11.5 解决后必须持续遵守的约定，避免同类问题复发。

### 12.1 MAS 编排层（`data/ai/mas/`）职责

MAS（Multi-Agent System）编排层仅在 `settings.mas_enabled` 打开时进入内置 Agent 同步
（`agent_loader.py` 会动态把 `orchestrator` 追加进 enabled）。默认关闭，普通聊天入口
不暴露计划工具。三个文件各司其职：

| 文件 | 消费方 | 作用 |
| --- | --- | --- |
| `agent_capabilities.yaml` | `MASPlanValidator` | 声明每个可分派专家的能力集合；校验计划节点的 `agent_id` 已注册且 `required_capabilities` 是其子集。 |
| `artifact_schemas.yaml` | `MASPlanValidator` | 声明 Artifact 类型及 producer；校验下游消费的产物类型确由上游产出（`user_upload` 型可作为根输入）。 |
| `tool_policies.yaml` | `schema_loader` | 按 `tool_key` 声明沙盒执行策略（允许镜像、可写根、是否联网/特权/挂 docker socket）。 |

能力来源有两条并轨且自动合并：**手工登记**（本表的 `agents:` 段）+ **自动派生**
（`flow_registry.agent_capabilities()` 为 `data/ai/flows/*.yaml` 中 flow 的 `actor`
派生其 stage executor 的 `key`）。同一 `agent_id` 两者取并集。

### 12.2 增删专家时的 MAS / handoff 同步清单

新增或删除一个专家 Agent 时，除第 6 节的 8 步外，必须同步：

1. **MAS 能力登记**：在 `agent_capabilities.yaml` 的 `agents:` 段增/删该 `agent_id`
   （router/orchestrator 除外）。actor 型专家只补非 executor 通用能力，executor 能力
   由 flow YAML 自动派生；`assistant_agent_id` 型（如 scrna 子专家）须手工登记全部能力。
2. **handoff 白名单**：检查其它专家的 `handoff.allowed_targets` 是否需要增删该目标；
   目标不能指向 `features.router` 的 Agent，也不能自转交，`max_hops_per_session` ∈ [1,10]。
3. **路由候选表**：同步 `prompts/router.md` 的候选专家表格（`| agent-xxx | 名称 | 适用请求 |`）。
4. **回归验证**：`uv run pytest tests/unit/test_agent_config_consistency.py -q`
   会一次性校验上述 1~3 的一致性；漏改即红灯。

`test_agent_config_consistency.py` 是这套契约的守门员，任何一处漂移都会被它拦下。

### 12.3 web_search 触发词规范

- 通用时效词（最新/文献/论文/今天/news/pubmed 等）由运行时常量
  `FRESHNESS_SEARCH_TRIGGERS`（`chat_service.py`）统一提供，**禁止**在 Agent YAML 里
  重复声明；要调整通用词只改这一处常量。
- Agent YAML 的 `web_search.triggers` **只声明该领域特有、且不在基线中的增量词**
  （如 scrna 的"细胞图谱"、code 的"发布说明/API"）。没有领域增量词时写 `triggers: []`。
- 运行时命中判定用的是基线与 Agent 增量词的并集，因此增量词留空不会削弱通用时效检索。

### 12.4 工具包（`data/ai/tools/*.yaml`）去重原则

- 新建工具包前先确认没有既有包已覆盖同一权限集合；`workspace`（只读浏览当前用户工作区）
  是通用基础包，代码/开发类 Agent 直接复用它，不要再造内容雷同的包。
- 工具包必须至少被一个 enabled Agent 的 `tool_packs` 引用；无人引用的包应删除，避免像
  历史上的 `development.yaml` 那样成为误导维护者的死文件。
- 多个 Agent 需要绑定同一组 MCP Server 但白名单不同时，按领域建包并收敛 `mcp_tools`
  （先例：`scrna.yaml` 复用 rnaseq/atacseq 的 Ensembl/GO Server UUID，但只暴露
  基因检索与 GO 校验子集）。不要在 Agent YAML 里直接堆 `mcp_ids`。

### 12.5 模型分级准则

Agent YAML 的 `model` 按**任务认知负荷**选档，不按"这个 Agent 重不重要"选：

- **轻量档（当前 `deepseek-v4-flash`）**：输出结构化、温度 ≤0.4、错误可被下游校验或
  重试覆盖的任务——路由分类、清单核验、交付汇总、陪伴式对话、Skill 候选包生成。
- **推理档（当前 `qdoubao-seed-evolving`）**：结论会直接驱动实验设计、阻断交付或生成代码的
  任务——领域专家分析、`qc` 审计、`orchestrator` 计划、`mcp_builder` 代码生成。
- 新 Agent 默认进推理档；要进轻量档需在 YAML 注释里说明"错误代价为什么低"。
- `providers.yaml` 中 `is_default: true` 全局只能有一个（当前 `qdoubao-seed-evolving`）；
  其余 Provider 一律 `is_default: false`，靠 Agent 按名显式选用。

### 12.6 Skill 候选区治理规范

新增或演进 Skill 时，优先区分"临时指令"和"可复用能力"：

- 一次性、边界模糊、未经实测的任务样例，让 Agent 用系统提示词 + 知识库直接回答；
- 重复 ≥3 次、触发条件清晰、输入输出可契约化的工作流，才交给 `agent-skill-builder`
  沉淀为候选 Skill；
- 候选包必须进 `/workspace/skill-candidates/<skill_id>/`，带
  `CANDIDATE_MANIFEST.json` 和 `pending_review_items`；
- 晋升到 `data/ai/skill_marketplace/` 前必须通过 §11.10 的评审 checklist；
- 晋升脚本 `scripts/promote_skill_candidate.py` 只做文件级校验，不自动改 Agent YAML；
- 评审未通过或边界与现有 skill 冲突的候选，应退回修改或废弃，禁止为了"凑数量"硬晋升。

候选区与 MCP Builder 的实验态（`mcp-builds/` + TTL）对称：两者都是 AI 生成能力的
受控沙盒，只是产物形态不同（MCP Server vs Skill 包），治理核心都是"先生成、再校验、
后人工确认"。

## 13. AgentTeams 权威文档与维护边界

AgentTeams 的唯一有效目标、状态机、角色口径、部署形态和验收标准见：

- `AgentTeams_VISION_FINAL.md`
- `AgentTeams_CONVERGENCE_PLAN.md`

本 README 不再维护 MAS、Element 外链、静态按角色 Worker 或历史分支蓝图，避免与权威文档
重复和漂移。当前维护约束如下：

- 14 个可招募专家、1 个 companion、1 个 router 的声明来自 Agent YAML registry。
- AgentTeams 场景通过 Bridge Work Item 协作；常规助手 fan-out 保留，但绑定 Case 后禁用。
- 生产专家 Worker 使用 capability 资源池并按目标身份令牌认领，不按角色固定独占服务。
- 计划确认、审批、取消、专家发言、进度、产物下载和 HTML 沙箱预览均在 CygnusX 聊天内闭环。
- 共享执行协议以 `data/ai/prompts/shared/agentteams_workspace_execution.md` 为准。

## Agent Persona（仅影响表达与协作方式）
- 角色原型：...
- 工作方式：...
- 表达风格：...
- 质疑与追问方式：...
- 稳定特质：...

表达边界：
- 以上内容只用于调整表达、解释顺序、追问方式和风险提醒。
- 不得据此新增、移除或扩大工具、MCP、Skill、审批、配额或数据访问权限。
- 不得把 Persona 偏好当作事实、证据、质量标准或执行结果；事实仍以工具和真实结果为准。
```

字段约定：

- `archetype`、`traits`、`working_style`、`communication_style`、`challenge_style` 进入
  system prompt；字段缺失时跳过，渲染顺序不变。
- `status_lines` 是 UI 状态文案，只进入 Assistant Instance/前端状态卡，不进入模型提示词。
- `persona_context` 是本轮任务的临时补充，只能由编排器附加到当前任务上下文，不能写回稳定
  Persona，也不能覆盖工具白名单、MCP、Skill、审批、配额或事实标准。
- 渲染器只读取 Agent 模板的稳定 `features.persona`，不读取用户能力覆盖中的同名字段；用户
  能力配置可以调整模型和能力范围，但不能借 Persona 改变平台权限边界。
- Persona 段落放在 Agent 原始职责提示之后、Skill/MCP 工具提示和平台执行规范之前；后续平台
  安全与执行规范具有更高约束优先级。

传统 `assistant_id` 聊天仍使用 `ChatAssistantModel.system_prompt`，不会隐式继承 Agent YAML
Persona。若产品需要其人格化，应为该 Assistant 显式增加独立 style profile，或显式绑定某个
Agent 后再继承；不得因为同名或默认助手关系自动复制领域 Agent Persona。

定向验证：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin --noconftest \
  tests/unit/test_agent_handoff_service.py \
  tests/unit/test_overdrive_persona_config.py -q
```
