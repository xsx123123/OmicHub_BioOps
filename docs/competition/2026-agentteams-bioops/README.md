# CygnusX BioOps 参赛材料包

> **作品名称：** CygnusX BioOps —— 面向生命科学研发的可审计多 Agent 协同基础设施  
> **赛道定位：** 企业级复杂任务下的多 Agent 基础设施与协同系统  
> **材料版本：** 初赛版 v1.0（2026-08-08）

## 一句话简介

CygnusX BioOps 面向药企、育种企业、医学检验与科研服务机构的组学数据分析交付场景，将“数据是否可用、流程如何运行、结果是否可信、交付是否完整”这一长链路任务，组织为可审批、可恢复、可验证、可审计的多 Agent 闭环。

项目以 **AgentTeams** 为协同设计基点：复用 CygnusX 已实现的通用协调与领域分析 Agent，并新增数据、质控、交付三个专职 Agent 组成 BioOps 工作组；CygnusX 负责受控工作流、Artifact Registry、共享工作区、质量门、证据归档与面向研究人员的工作台体验。

## 材料目录

| 文件 | 用途 |
| --- | --- |
| [01_初赛项目方案.md](01_初赛项目方案.md) | 初赛方案正文：场景、价值、技术架构、闭环与安全设计。 |
| [02_Agent_Identity清单.md](02_Agent_Identity清单.md) | Agent Identity 清单、角色边界和协同关系。 |
| [03_Skill与工具接口清单.md](03_Skill与工具接口清单.md) | 必选 Skill、Bridge/等价 MCP 工具契约、失败处理与复用设计。 |
| [04_Demo验证与审计证据.md](04_Demo验证与审计证据.md) | Demo 脚本、验证口径、证据清单、异常演示与部署边界。 |
| [05_路演PPT大纲.md](05_路演PPT大纲.md) | 12 页初赛/复赛路演 PPT 结构及每页讲述重点。 |
| [06_开源与推进计划.md](06_开源与推进计划.md) | 开源交付、版本治理和初赛至决赛推进计划。 |
| [07_评审要点对照.md](07_评审要点对照.md) | 对照赛题技术要求与评分维度的自检表。 |

## 作品边界与真实性声明

本材料以仓库当前实现为依据，刻意区分“**已实现/可验证**”与“**比赛期间拟完成**”，避免把设计稿写成上线事实。

- **已实现或已有可验证工程基础：** CygnusX MAS 的受控 DAG、计划确认门、Artifact Registry、Outbox + Redis Stream、有限重试、质量门、HITL 审批、受控 Worker；以及 AgentTeams Bridge、Case/Work Item、角色身份、短期审批令牌、幂等提交、质量决策、证据事件与交付 manifest 的集成边界。
- **默认关闭或待部署验收：** `MAS_ENABLED`、AgentTeams Gateway/Matrix 互通、真实 RNAFlow/Apptainer 环境下的端到端生产演练。Demo 采用独立 staging Bridge 及预检/受阻场景作为可重复验证路径。
- **比赛增量重点：** 复用 `agent-general` 与 `agent-rnaseq`/`agent-atacseq`/`agent-scrna` 等已实现 Agent；新增 `agent-data`、`agent-qc`、`agent-delivery` 三个专职角色，并将它们与 AgentTeams Case、CygnusX 受控工作流和证据投影串成可路演的“研究项目交付闭环”。

## 仓库证据索引

| 事实 | 仓库依据 |
| --- | --- |
| MAS 的目标、边界、状态机、Outbox、审批、质量门和验收项 | `ARCHITECTURE_DESIN/plan_ai.md` |
| 当前 Agent 装配、工具来源、MAS 启用条件与运行边界 | `ARCHITECTURE_DESIN/agent_framework_final_baseline.md` |
| AgentTeams 超频/房间交互与 Matrix Gateway 的渐进方案 | `ARCHITECTURE_DESIN/agentteams.md` |
| AgentTeams 非侵入式 Bridge、浏览器隔离和 staging Demo 边界 | `integrations/agentteams/README.md` |
| 角色 Team 定义与 Skill 调用契约 | `integrations/agentteams/teams/bioops-delivery.yaml`、`integrations/agentteams/skills/contracts.yaml` |
| 内置 Agent、提示词、工具包、Skill、MCP 与 MAS 配置加载机制 | `data/ai/README.md` |
| MAS 可分派 Agent 能力、Artifact 类型和编排器规则 | `data/ai/mas/agent_capabilities.yaml`、`data/ai/mas/artifact_schemas.yaml`、`data/ai/orchestrator.yaml` |

## 使用建议

1. 初赛提交时，将 `01` 导出为方案正文，将 `05` 制作为 PPT；`02`、`03`、`07` 作为附件或答辩备查材料。
2. 复赛前按 `04` 完成 staging Demo 录屏、可执行命令记录和证据包归档。
3. 任何对外宣传请沿用本包中的状态标记；尤其不要把“默认关闭”“待部署验收”的能力描述为已生产上线。
