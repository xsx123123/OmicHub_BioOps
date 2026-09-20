# Agent Identity 清单

> 本清单对应赛题“至少 3 个不同职能 Agent、清晰身份定义、能力边界和协同关系”的要求。  
> 所有角色以 AgentTeams Team/Case/Work Item 为协同单元，并由服务端签发或保管身份凭据；浏览器不直接持有 Worker 或 Bridge 的高权限凭据。

## 1. 核心角色一览

| Agent Identity | 身份与职责 | 可调用核心 Skill | 输入 | 输出 | 禁止能力 |
| --- | --- | --- | --- | --- | --- |
| `agent-general`（现有） | 项目主控；理解需求、创建 Case、编排工作项、汇总风险与交付结论 | Case 编排、`scientific-interpretation` | 需求、项目引用、角色进度 | Case 计划、分工、汇总结论、审批请求 | 直接提交/取消工作流、shell、数据库直连、原始文件写入。 |
| `agent-rnaseq` / `agent-atacseq` / `agent-scrna`（现有，按模态择一） | 领域执行者；在审批后提交、监控、取消允许的同模态分析流程，并负责领域分析 | `workflow-submit`、`workflow-monitor`、`workflow-cancel` 及已有领域 Skill | approval token、幂等键、允许的流程、逻辑任务引用 | task ID、状态、运行摘要、领域产物引用、取消记录 | 流程 YAML、任意命令、数据库访问、绕过审批。 |
| `agent-data`（新增） | 数据管理员；进行项目预检和元数据一致性核验 | `project-preflight` | 样本表、分组、物种、参考版本、项目元数据 | `passed`/`blocked`、缺失字段、预检证据 | 提交任务、修改工作流、shell、文件写入。 |
| `agent-qc`（新增） | 质量审计员；依据规则版本与 Artifact 校验结果做质量放行 | `quality-gate` | task 状态、Artifact 引用、QC 规则版本 | `passed`/`failed`/`manual_review`、质量决策证据 | 更改流程参数、直接渲染/发布文件、以 LLM 替代 QC 规则。 |
| `agent-delivery`（新增） | 交付报告员；汇聚合格产物、生成 manifest、记录交付风险 | `delivery-pack` | 已验证 Artifact、质量结论、参数摘要、evidence reference | Delivery Manifest、交付摘要、runbook、复盘条目 | 执行工作流、修改原始结果、跳过必需 Artifact。 |

## 2. 可选领域审查角色

这些角色在项目复杂时由 Manager 作为受限审查者并行调用，不替代核心责任链。

| Agent Identity | 使用时机 | 可调用能力 | 边界 |
| --- | --- | --- | --- |
| `agent-rnaseq` | 差异表达设计、对比组合理性、统计解释需要领域审查时 | RNA-seq 质量审查、科学解释 | 只产出带证据和不确定性的建议；不提交任务。 |
| `agent-scrna` | 单细胞扩展场景中的 QC、整合、细胞类型注释审查 | `scrna-interpretation`、上游/整合/注释审查 | 不访问原始 FASTQ，不修改工作流或 Artifact。 |
| `agent-viz` | 图表规范、火山图/报告表现形式复核时 | `visualization-review` | 只读审查，不渲染、不发布文件。 |
| `agent-code` | 分析脚本、复现说明或接口契约审查时 | `code-review` | 只读审查，不执行代码、不修改文件。 |

## 3. AgentTeams 协同关系

```text
研究人员 / 项目负责人
           │ 需求、数据引用、审批
           ▼
    ┌─────────────────┐
    │ agent-general   │──────────────┐
    └───────┬─────────┘              │
            │ Work Item              │ 可选领域审查
            ▼                        ▼
      agent-data ── passed ──► 领域执行 Agent ──► agent-qc
          │ blocked                      │                    │
          └── 补充元数据请求              │                    ▼
                                      task/artifacts   agent-delivery
                                                           │
                                                           ▼
                                                 manifest / 证据 / 复盘
```

## 4. 身份、权限与会话隔离

### 4.1 身份凭据

- 每个 AgentTeams 角色使用独立的 Bridge identity environment token，不共享 Worker 身份。
- 高风险操作不依赖“角色已登录”这一条件；还必须携带人工网关签发的、作用域受限且短时有效的 `approval_token`。
- CygnusX 通过服务端 Manager 身份代理 Bridge 调用；浏览器只访问 CygnusX API，不获得 Bridge secret 或 Worker 操作权限。

### 4.2 最小权限原则

- `agent-data` 与 `agent-qc` 均为只读角色。
- 被分派的领域执行 Agent 只接触被 allowlist 的同模态流程入口、指定 Case 与幂等请求，不接触 shell、Docker、流程 YAML 或数据库。
- `agent-delivery` 只能写入证据与逻辑交付 manifest；必需 Artifact 缺失时必须阻断。
- 领域专家通过科学解释网关获得只读工具，且有默认超时、单 Case 调用次数及 token 预算上限。

### 4.3 上下文最小化

角色间只共享：Case/Work Item ID、项目/任务逻辑引用、Artifact URI、摘要、规则版本、状态与 trace。原始测序文件、完整矩阵、长日志、数据库连接串、服务端路径和用户密钥不进入对话上下文。

## 5. 生命周期与异常协作

| 状态 | 责任角色 | 系统动作 | 用户可见动作 |
| --- | --- | --- | --- |
| `created` | Manager | 创建 Case、初始化 Work Item 和 trace | 显示任务目标、范围和待补充信息。 |
| `blocked` | `agent-data` / `agent-qc` | 写入结构化缺失或质量阻断原因 | 展示补充资料/人工复核卡。 |
| `approval_pending` | `agent-general` + 人工网关 | 等待审批，不调度高风险动作 | 用户批准、拒绝或修改范围。 |
| `in_progress` | 领域执行 Agent / 审查角色 | 领取工作项、更新进度、绑定证据 | 查看角色泳道和执行摘要。 |
| `manual_review` | `agent-qc` | 固化规则不足或边界异常证据 | 指定审计人员复核，不自动放行。 |
| `completed` | `agent-delivery` | 生成 manifest、runbook 和复盘条目 | 下载交付包、查看完整证据。 |
| `cancelled` / `failed` | `agent-general` + 领域执行 Agent | 记录原因、保留已产出 Artifact、停止后续调度 | 显示恢复/重试建议，不删除审计轨迹。 |

## 6. 实现映射

| 配置/工程位置 | 对应内容 |
| --- | --- |
| `integrations/agentteams/teams/bioops-delivery.yaml` | AgentTeams Team 的角色身份、Skill 和禁止能力。 |
| `integrations/agentteams/skills/contracts.yaml` | Skill actor、调用入口、审批要求、失败语义与边界。 |
| `data/ai/mas/agent_capabilities.yaml` | CygnusX MAS 的可分派 Agent 与能力校验表。 |
| `data/ai/orchestrator.yaml` | 受控 DAG 计划草案生成、确认门和工具包声明。 |
| `ARCHITECTURE_DESIN/plan_ai.md` | Run/Node/Artifact/Approval/Event、状态机、Outbox、HITL 和质量门设计。 |
