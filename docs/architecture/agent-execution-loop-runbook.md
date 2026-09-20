# Agent 执行闭环排查与验收手册

> 适用范围：普通 AI 助手、OmicStudio、AgentTeams 协助室的受控工具执行与 Worker ReAct。
>
> 本手册描述当前代码中的实际事件名与执行路径；默认用户视图只显示结构化进度，技术事件模式才显示调用追踪详情。

## 1. 用户可见阶段

| 阶段 | 用户可见文案 | 说明 |
| --- | --- | --- |
| 分析开始 | `开始处理` / `正在分析` | Worker 或 Manager 已接手请求。 |
| 工具请求 | `正在调用 {工具}` | 模型请求工具，尚未证明工具执行成功。 |
| 工具执行 | `工具执行中：{工具}` | 后端开始执行该工具。 |
| 工具完成 | `{工具} 调用完成` | 工具返回成功结果。 |
| 工具失败 | `{工具} 调用失败` | 工具失败，不能把该动作表述为已完成。 |
| 上下文回灌 | `工具结果已纳入下一步分析` | 工具结果已写回下一轮模型上下文。 |
| 下一轮 | `Worker 已进入下一轮分析` | 模型准备根据已回灌结果继续。 |
| 运行保护 | `运行保护已触发` | 重复调用、无进展或轮次预算触发；查看原因后决定重试、补充输入或调整任务。 |

协助室普通讨论保持为 Manager 会诊，不强制调用工具。明确要求读取、查看、检索或只读复核时，系统会路由到 `agentteams_tool_execution`；缺少文件、路径或检索条件时，系统以 `room.ask_user` 请求补充信息。

## 2. 执行路径与事件链

| `execution_path` | 入口 | 关键事件 |
| --- | --- | --- |
| `chat_legacy` | `ChatService` 手写循环（**已退化为逃生舱**：仅 `engine:"legacy"` 或 `chat_force_legacy_runtime`，2026-09-19 起） | `agent_turn_started` → `agent_tool_call` → `agent_tool_result` → `agent_context_reinjected` → `agent_turn_continued` → `agent_final_result` |
| `chat_langgraph` | LangGraph 聊天运行时（**普通聊天默认全量**，单 Runtime 收敛已落地） | 与传统聊天使用相同语义事件；终止态额外含 `awaiting_input`（ask_user 澄清）与 `action="finalize"`（submit_output 显式 Finalize）。 |
| `studio_chat_loop` | Studio 沙盒工具循环 | 与聊天相同事件，工具结果可包含受控产物信息。 |
| `agentteams_manager_consultation` | 协助室纯会诊 | Manager 生成会诊回复；不应伪装为工具已执行。 |
| `agentteams_tool_execution` | 协助室单步只读工具请求 | 路由决策 → 受控只读工具 → 结果回灌 → Manager 房间回复。 |
| `agentteams_worker_react` | AgentTeams Worker 子循环 | Worker 工具事件投影为房间 `agent.*` 证据事件。 |

所有统一执行事件应至少携带 `session_id`、`run_id`、`agent_id`、`round`、`execution_path` 与 UTC `timestamp`。工具事件还应携带 `tool_call_id`；无法提供时必须显式为空，而不是前端猜测。

## 3. 协助室技术事件模式

在协助室设置中开启“默认展开底层事件”后，Worker 时间线可展开查看以下已截断字段：

- `tool_call_id`：关联同一次工具调用、执行、结果回灌；
- `round`：该事件所属模型轮次；
- `execution_path`：后端权威执行路径；
- 参数摘要与结果摘要：仅用于排查，不展示完整原始 reasoning 或完整工具返回包。

关闭该选项时，默认界面只展示结构化阶段、工具状态与最终结果，避免长 reasoning 或技术字段刷屏。

## 4. 研发排查步骤

1. 先按 `run_id`、`session_id` 或 `case_id` 聚合日志与 SSE/Case 证据事件。
2. 确认事件的 `execution_path` 与请求场景一致；不要仅从前端文案推断路径。
3. 对每个 `agent_tool_call`，检查相同 `tool_call_id` 是否出现 `agent_tool_started`、`agent_tool_result` 和后续 `agent_context_reinjected`。
4. 确认 `agent_turn_continued` 发生在下一次模型调用前，且其 `previous_round` 与回灌轮次连续。
5. 如果出现 `agent_loop_guard_triggered`，检查 `reason`、`tool_name`、`round`，并确认之后没有盲目继续同一工具调用。
6. 协助室路径同时检查 `AgentConsultationService._BridgeEvidenceProjector` 是否将 Worker 事件写为 `agent.tool_call`、`agent.tool_started`、`agent.tool_result`、`agent.context_reinjected`、`agent.turn_continued` 或 `agent.loop_guard_triggered`。

关键实现位置：

- `src/cygnusx/application/services/execution_events.py`
- `src/cygnusx/application/services/chat_service.py`
- `src/cygnusx/infrastructure/execution/langgraph_nodes.py`
- `src/cygnusx/application/services/parallel_subagent_service.py`
- `src/cygnusx/application/services/agent_consultation_service.py`
- `src/cygnusx/application/services/agentteams_room_response_service.py`
- `frontend/src/utils/agentTeamsRoom.ts`
- `frontend/src/views/AgentTeamsRoomView.vue`

## 5. 标准验收用例

1. **三轮工具闭环**：Fake provider 依次返回读取工具、计算工具、最终正文；验证第 2/3 次模型输入包含前序 `role=tool`，并产生回灌与继续事件。
2. **协助室纯讨论**：发送“你怎么看这个方案”；验证未进入 `agentteams_tool_execution`。
3. **协助室只读请求**：发送“读取这个文件并判断”；验证路由为 `tool_execute`、执行路径为 `agentteams_tool_execution`，最终回复引用工具结果。
4. **缺少对象**：发送无文件/路径的执行请求；验证产生 `room.ask_user`，而不是伪造执行完成。
5. **Worker 工具追溯**：验证工具调用、执行、结果、回灌和下一轮在协助室按同一 `tool_call_id` 可关联；技术事件模式可见摘要、轮次和路径。
6. **重复工具保护**：连续等价调用同一工具；验证 `agent_loop_guard_triggered` 出现且不再继续盲目调用。

建议命令：

```bash
.venv/bin/pytest tests/unit/test_agent_consultation_service.py::test_evidence_projection_emits_agent_events_with_truncated_args -q
.venv/bin/pytest tests/unit/test_parallel_subagent_service.py::test_fanout_emits_correlated_tool_reinjection_events -q
.venv/bin/pytest tests/unit/test_agentteams_room_response_service.py::test_readonly_file_request_routes_to_tool_execution_without_planning -q
cd frontend && ./node_modules/.bin/vitest run src/utils/__tests__/agentTeamsRoom.spec.ts
```
