# 多 Agent 协作配置指南

OmicHub 将协作入口统一为 Router 决策，但不会合并既有机制：**Handoff**、**多专家会诊**、**对话内 Fan-out**、**AgentTeams Case** 和 **MAS 工作流**仍有各自边界。

当 Router 判定为 `dag` 时，系统会优先使用当前会话可用的 MAS 计划预览能力；未配置 MAS 时会明确说明需要管理员启用 MAS，并引导用户先准备流程输入，而不会把工作流请求静默改成普通聊天。

## 协作档位

在“AI 配置中心 → AgentTeams”中选择档位：

| 档位 | 系统行为 | 适用场景 |
| --- | --- | --- |
| 轻量协作 | 启用统一意图路由和多专家会诊 | 咨询、方案评估、转交专家 |
| 并行增强 | 轻量协作 + 子 Agent Fan-out | 2–5 个可独立完成的短子任务 |
| 全流程闭环 | 并行增强 + Case 创建入口 | 审批、正式执行、质控和交付 |
| 自定义 | 保留管理员手动设置 | 灰度或特殊部署 |

档位配置保存于平台设置；环境变量 `UNIFIED_INTENT_ROUTER_ENABLED`、`MULTI_EXPERT_CONSULTATION_ENABLED`、`SUBAGENT_FANOUT_ENABLED` 仍可强制开启对应能力。关闭统一路由开关会恢复此前 Router 行为。

管理页会在应用档位前展示将被原子写入的开关差异。页面同时显示近 7 天因能力未开启而触发的降级次数，便于决定是否开启 Fan-out、会诊、Case 或 MAS。

## 降级文案

在“协作降级文案”区域可选择默认语言（中文或 English），并分别编辑模板。模板可使用 `{intent}`、`{setting}`、`{alternative}` 占位符；系统会在被选中的协作能力未开启时渲染对应提示和实际可用的替代方案。无效占位符会安全回退到内置中文模板，避免静默降级。

## AgentTeams Bridge

全流程闭环还需要 Bridge 真实接通。配置下列环境变量或在管理页保存等价的加密配置：

```dotenv
AGENTTEAMS_BRIDGE_ENABLED=true
AGENTTEAMS_CHAT_ENTRY_ENABLED=true
AGENTTEAMS_BRIDGE_URL=http://omichub-agentteams-bridge:8080
AGENTTEAMS_BRIDGE_MANAGER_TOKEN=...
AGENTTEAMS_BRIDGE_DATA_STEWARD_TOKEN=...
AGENTTEAMS_BRIDGE_APPROVAL_TOKEN=...
AGENTTEAMS_BRIDGE_WORKFLOW_OPERATOR_TOKEN=...
```

Bridge 自身还需要在 `deploy/agentteams/bridge.env` 配置 `BRIDGE_IDENTITIES`。除基础身份外，`agent-code`、`agent-viz`、`agent-scrna` 也必须有独立身份令牌，才能领取只读 Work Item。

执行部署前检查：

```bash
deploy/agentteams/check_setup.sh deploy/agentteams/bridge.env
```

脚本会检查身份、Bridge 连通性（若提供 URL）和流程白名单。它会提示 `scrna_seq` 是否仍不在 `BRIDGE_ALLOWED_FLOW_IDS` 中；不在白名单时，单细胞专家仍可咨询/领取只读工作项，但不能提交单细胞流程。

Bridge 运行后，管理页与脚本还会实际验证四个 OmicHub 身份令牌，并根据 `agent-code`、`agent-viz`、`agent-scrna` 最近一次认证拉取 `/v1/work-items/assigned` 的时间判断 Worker 心跳。未在 `BRIDGE_WORKER_HEARTBEAT_TTL_SECONDS`（默认 180 秒）内轮询的 Worker 会报红。

## Worker 部署边界

`agent-code`、`agent-viz`、`agent-scrna` 的 Worker 由 AgentTeams 控制面独立部署。仅更新 OmicHub 数据库或 `.env` **不会**启动 Worker。Worker 必须使用自己的 Bridge 身份轮询 `GET /v1/work-items/assigned`，并只能认领和回写分配给自己的只读 Work Item。

## 用户体验与回退

统一路由会展示选择原因。低置信度时会先反问；Fan-out、会诊、Case 或 MAS 未开启时会展示明确的降级说明和可用替代方案，而不会静默串行降级。Case 无论如何仍必须经过用户确认卡和人工审批。

## 会诊升级为 Case

多专家会诊结果卡提供“基于此创建协作 Case”入口。点击后会将会诊纪要预填入聊天输入框；智能体仍会先收集项目与流程信息，并展示原有确认卡。创建时会把 `origin_consultation_id` 和 `consultation_summary` 一并写入 Bridge Case 与预检输入快照，供后续审批、执行和审计追溯。该来源字段为可选字段，因此既有的直接创建 Case 调用保持兼容。
