# Demo、验证与审计证据说明

## 1. Demo 目标

现场展示一个真实可理解、可中断、可复核的 BioOps Case，而不是只展示多 Agent 对话。观众应能看到：

1. 用户输入一项 RNA-seq 分析交付需求；
2. `agent-general` 创建并拆解 Case，新增 `agent-data` 完成预检；
3. 缺少关键元数据时，系统阻断并提出结构化补充请求；
4. 预检通过后，用户审批，按任务模态选择的现有领域 Agent 以幂等方式提交并监控任务；
5. 新增 `agent-qc` 依据结构化质量门放行或转人工；
6. 新增 `agent-delivery` 生成 manifest、证据索引和交付总结；
7. 全程可查看角色、状态、trace、审批和 Artifact 引用。

## 2. 三条必演示链路

### 2.1 链路 A：预检成功并完成交付（主链路）

**输入：** 已准备样本表、分组、物种、参考版本和允许的 RNA-seq 流程配置的脱敏 Demo 项目。

| 步骤 | 预期现象 | 必留证据 |
| --- | --- | --- |
| 创建 Case | `agent-general` 生成目标、角色和依赖关系 | Case ID、创建事件、参与 Agent Identity。 |
| 项目预检 | `agent-data` 返回 `passed` | 预检报告、输入摘要、规则/模板版本。 |
| 人工确认 | 界面显示成本/范围/风险，用户批准 | approval ID、审批人、作用域、过期时间（不展示 token 本身）。 |
| 提交任务 | 当前领域执行 Agent 返回唯一 task ID | 幂等键、任务提交事件、trace。 |
| 运行监控 | 状态从 queued/running 到 terminal | 阶段事件、耗时、Artifact 注册记录。 |
| 质量门 | `agent-qc` 返回 `passed` 或可解释的决定 | QC 指标摘要、规则版本、质量决策 evidence。 |
| 交付 | `agent-delivery` 生成 manifest | 结果链接、必需 Artifact 列表、runbook、风险说明。 |

### 2.2 链路 B：预检受阻（异常链路）

**输入：** 缺失分组信息、参考基因组版本或样本映射的 Demo 项目。

**预期：** `agent-data` 的 `project-preflight` 返回 `blocked`，`agent-general` 通过审批/追问卡一次性说明缺失字段与示例；系统不生成任务、不消耗计算资源、不调用 `workflow-submit`。

**评审重点：** 证明多 Agent 系统不是“遇到不确定信息也继续编造并执行”，而是能够在正确的责任边界停下来。

### 2.3 链路 C：质量门转人工复核（异常链路）

**输入：** 一个 QC 指标低于门限、Artifact 不完整或质量规则版本缺失的已完成任务。

**预期：** `agent-qc` 返回 `failed` 或 `manual_review`；`agent-delivery` 被依赖关系阻断；界面展示规则版本、失败原因和人工复核请求。人工复核后才可形成最终交付。

**评审重点：** 证明结果验证由结构化证据和规则驱动，不由 LLM 自行“认可”。

## 3. 可重复验证入口

当前仓库包含独立 AgentTeams Bridge、Bridge contract test 和 demo 驱动。建议在隔离 staging 环境执行下列验证，所有真实任务动作需使用显式 staging 审批，不可将其视为生产审批替代。

| 验证项 | 建议入口 | 预期 |
| --- | --- | --- |
| Bridge 接口契约 | `PYTHONPATH=integrations/agentteams/bridge uv run pytest integrations/agentteams/bridge/tests/test_bridge_contract.py -q` | Bridge 输入输出、鉴权/边界相关契约通过。 |
| Bridge 共享状态 | `PYTHONPATH=integrations/agentteams/bridge uv run pytest integrations/agentteams/bridge/tests/test_redis_shared_state.py -q` | 共享状态与事件相关行为通过。 |
| Worker 行为 | `uv run pytest integrations/agentteams/worker/tests -q` | analysis/quality/delivery 等 Worker 单测通过。 |
| OmicHub MAS 契约 | `uv run pytest tests/unit/domain/mas/ tests/unit/test_agent_config_consistency.py -q` | MAS 域模型、能力与配置一致性通过。 |
| AgentTeams 服务集成 | `uv run pytest tests/unit/test_agentteams_service.py tests/unit/test_agentteams_case_tool_service.py tests/unit/test_agentteams_case_watch_service.py -q` | Case/工具/观察服务的单元行为通过。 |
| Staging 演示驱动 | `integrations/agentteams/demo/README.md` 所列命令 | 验证预检成功、预检阻断和经显式批准的完整链路。 |

> 验证前须按仓库当前环境准备依赖。实际 RNAFlow/Apptainer 全链路还依赖容器运行环境、RNAFlow 镜像、数据凭据和测试 FASTQ；该部分应标注为“部署验收”，不可用单元测试替代。

## 4. 审计证据模型

### 4.1 每个 Case 的最小证据包

```text
case/<case_id>/
├── case-summary.json               # 需求、范围、请求人、最终状态
├── plan-and-work-items.json        # Manager 分工和依赖图
├── approvals.json                  # 审批记录，不保存明文 token
├── preflight-report.json           # 输入完整性与阻断原因
├── task-events.ndjson              # 状态、attempt、trace、dedupe key
├── artifact-manifest.json          # 逻辑 Artifact 引用、类型、校验摘要
├── quality-decision.json           # 规则版本、QC 指标、放行/复核结论
├── evidence-events.ndjson          # 角色行为与引用关系
├── delivery-manifest.json          # 最终交付、风险、runbook、复盘链接
└── observability-summary.json      # 耗时、调用次数、错误类别、成本指标
```

### 4.2 统一关联字段

| 字段 | 作用 |
| --- | --- |
| `trace_id` | 将 Manager 决策、Bridge 调用、MAS 节点、Worker 执行和交付事件串联。 |
| `case_id` | AgentTeams 协作与审批的顶层业务边界。 |
| `run_id` / `node_id` | OmicHub MAS 的 DAG 执行与 Artifact 生产关系。 |
| `work_item_id` | 角色领取和完成的最小协作单元。 |
| `attempt` / `dedupe_key` | 有界重试与至少一次事件投递下的幂等审计依据。 |
| `skill_version` / `rule_version` | 解释“当时按照什么能力/规则做出了该决策”。 |
| `evidence_ref` / `artifact_ref` | 指向逻辑证据和产物，避免在日志中复制敏感文件内容。 |

## 5. 现场演示脚本（8 分钟）

| 时间 | 演示内容 | 讲述重点 |
| --- | --- | --- |
| 0:00–0:40 | 场景与痛点 | 一次 RNA-seq 交付为什么不是一个聊天机器人能安全完成的任务。 |
| 0:40–1:40 | 创建 Case 与角色分工 | AgentTeams Team、Case、Work Item 对应真实岗位职责。 |
| 1:40–2:30 | 预检阻断 | 缺失信息时停下来，避免无效计算与错误结论。 |
| 2:30–3:30 | 补全信息后审批 | 高风险计算需要用户可见的范围确认与短期授权。 |
| 3:30–4:50 | 受控提交与监控 | 幂等键、任务状态和 Artifact 如何被记录。 |
| 4:50–6:00 | 质量门与人工复核 | 不让 LLM 充当质量判定器。 |
| 6:00–7:10 | 交付 manifest 与证据 | 展示一个可复核交付包，而不是一个不透明下载链接。 |
| 7:10–8:00 | 架构与可复制性 | 同一 Case 模式可接入不同组学流程和企业科研项目。 |

## 6. Demo 安全约束

- 只使用脱敏数据、合成数据或明确授权的测试数据；不得在录屏中展示病人信息、原始样本名、密钥、数据库地址或宿主机路径。
- 现场展示审批记录的元数据，不展示 approval token；token 仅由服务端短期保管和校验。
- 完整工作流使用 staging 项目和资源配额；取消、重试、失败演示均保留审计轨迹。
- 若 AgentTeams Gateway/Matrix 未部署，使用 OmicHub 内置 Case/进度界面进行演示，并明确标注 Matrix/Element 为可选外部协作入口。
