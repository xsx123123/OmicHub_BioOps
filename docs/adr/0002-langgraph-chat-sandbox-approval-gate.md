# ADR 0002: LangGraph 路径 chat_sandbox_execute 审批闸收敛（R8）

## Status

Accepted（2026-09-18，WP4 任务 2）

## Context

`chat_sandbox_execute` 在 supervised 权限模式下与 Studio `sandbox_execute`
同险，legacy 手写循环（`chat_service.py` 的 `is_chat_sandbox_tool` 分支）已实现
HITL 审批闸：Redis pending 记录（TTL 300s）+ `approval_request`/`approval_resolved`
SSE 事件 + BLPOP 决议等待 + `audit_logs` 留痕。

LangGraph 引擎路径（`features.engine == "langgraph"`，非 Studio）的工具执行在
`LangGraphChatRuntime._tool_executor` 中直调 `execute_chat_sandbox`，无任何审批
拦截，supervised 会话下形成审批旁路（R8）。

## Decision

选择方案 (a) 补齐审批闸，不复用方案 (b) 硬守卫，理由：

- legacy 审批语义已全部服务化于 `studio_approval_service.py`
  （`needs_approval` / `create` / `wait_resolution` / `record_approval_audit` /
  `always_allow_set`），LangGraph 侧接入成本约 130 行、单文件即可完成；
- 方案 (b) 只堵洞不治病，LangGraph 路径在 supervised 会话下永远无法启用。

落地（全部集中在
`src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py`）：

- 新增模块级 `_gate_chat_sandbox_approval()`：复用 StudioApprovalService 走
  Redis 审批记录与决议等待；审批事件经 `NodeDeps.emit`（图任务内入队，由
  runtime stream 透传）下发，与 legacy 事件协议逐点一致；
- `_stream_agent_chat_langgraph` 启动时读取会话 `sandbox_meta.permissions`
  得到 `chat_permission_mode` 与 `always_allow`（语义与 legacy 相同：仅当会话
  显式声明 `permissions.mode` 时启用，缺失则保持放行）；
- `CHAT_SANDBOX_TOOL_NAME` 执行前过闸：通过（含 `edited` 改参、`always` 入会
  话放行集合）才执行；拒绝/超时返回 rejection 信封回灌 LLM 与前端；
- timeout 决议由聊天流经 `record_approval_audit(method="EVENT")` 落
  `audit_logs`；approve/reject 的落库仍在 REST 端点（`api/v1/studio.py`，未改动）。

与 legacy 的对齐点：needs_approval 判定、审批记录字段与 TTL、approval_request
metadata（含 `timeout_seconds`、`risk_hint`）、等待期 15s heartbeat、
approval_resolved metadata、edited/always/timeout 分支语义、rejection 信封结构、
audit 留痕分工。

未改动：`sandbox/pool.py`、`studio/manager.py`、frontend、legacy/Studio 链路审批
代码、`chat_runtime_refactor_enabled` 配置闸（默认 false 行为不变）。

## Consequences

- supervised 会话下 LangGraph 路径不再存在审批旁路；默认（未声明权限模式）
  会话行为与之前完全一致。
- 审批事件在 LangGraph 路径经 asyncio.Queue 图内 emit，保序由 tool_exec 节点
  串行执行保证（单会话同刻仅一个审批卡）。
- R13（LangGraph 执行器缺少增量 `tool_output` 事件，stdout/stderr/产物随最终
  `ui_payload` 一次性透出）**在审批闸补齐前维持不改**，仅在此记录；后续如需
  对齐，应在 `_tool_executor` 的 chat_sandbox 分支接入
  `stream_chat_sandbox_tool` 的增量事件并经同一 emit 通道透出。
