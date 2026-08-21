# Agent 思考—工具闭环可观测性升级

> 更新日期：2026-08-18  
> 关联计划：`docs/info/26.8.18/OmicHub-Agent思考工具闭环优化实施计划与编码提示词.md`  
> 关联基线：`ARCHITECTURE_DESIN/agent_current_execution_framework_2026-08.md`

## 1. 本次目标与范围

本次升级不合并 Legacy、LangGraph、Studio 与 AgentTeams Worker 的运行时实现，而是在保持既有兼容性的前提下统一它们的可观测语义：

```text
用户请求
→ 执行路径判定
→ 模型思考
→ 工具调用
→ 工具执行
→ 工具结果写回上下文
→ 下一轮继续分析
→ Guard / 最终结果
```

覆盖范围：

- 统一 `execution_path` 与生命周期事件；
- 协助室普通消息的只读工具路由；
- Worker ReAct 事件向 Case 房间时间线投影；
- 前端技术事件模式下的关联追溯；
- Loop Guard 状态可见性、测试与运行手册。

非目标：不以本次改动重写各执行 Runtime，不把纯讨论伪装为工具执行，也不默认展示模型原始 reasoning。

## 2. 执行路径与路由语义

| `execution_path` | 场景 | 路由/权限边界 |
| --- | --- | --- |
| `chat_legacy` | 普通 AI 助手的手写 ReAct | 由 Agent 配置和工具权限决定。 |
| `chat_langgraph` | LangGraph Agent | 使用图运行时，保持同一生命周期语义。 |
| `studio_chat_loop` | OmicStudio 沙盒工具循环 | 受 Studio 权限模式、审批和沙盒约束。 |
| `agentteams_manager_consultation` | 协助室纯讨论/会诊 | 给出解释、建议和证据；不能宣称未执行的工具已完成。 |
| `agentteams_tool_execution` | 协助室单步只读请求 | 仅允许受控读取、检索与只读复核；缺少对象时请求澄清。 |
| `agentteams_worker_react` | AgentTeams Worker 子循环 | Worker 只能使用受限工具，不能递归 fan-out 或越权操作父会话。 |

协助室消息意图分为 `chat`、`clarify`、`tool_execute`、`execute` 与降级处理：

- `chat`：如“你怎么看这个方案”，保持 Manager 会诊；
- `clarify`：有执行动作但缺少文件、路径、数据对象或检索条件，写入 `room.ask_user`；
- `tool_execute`：明确的读取、查看、打开、检索、查询、复核或判断请求，进入 `agentteams_tool_execution`；
- `execute`：需要真实分析/生成/运行，进入 Case planning 和审批边界；
- `degraded`：澄清轮次耗尽或受限条件不能满足时，明确说明未执行原因并回退会诊。

## 3. 统一事件契约

统一生命周期事件由 `execution_events.py` 生成，所有事件至少包含：

```json
{
  "event_type": "agent_tool_result",
  "session_id": "…",
  "run_id": "…",
  "agent_id": "…",
  "round": 2,
  "execution_path": "agentteams_worker_react",
  "timestamp": "2026-08-18T00:00:00+00:00"
}
```

工具相关事件还使用 `tool_call_id` 关联同一次调用的整个生命周期：

```text
agent_turn_started
→ agent_tool_call
→ agent_tool_started
→ agent_tool_result
→ agent_context_reinjected
→ agent_turn_continued
→ agent_final_result
```

异常或运行保护使用 `agent_turn_failed` 与 `agent_loop_guard_triggered`。旧版 `tool_call`、`tool_result`、`worker_tool_call`、`worker_tool_result` 和 `done` 仍保留，避免旧前端或 SSE 消费方断连。

## 4. Worker 证据投影与关联信息

`ParallelSubAgentService` 为每个 Worker 工具事件写入 `round`、`execution_path`、`tool_call_id`、工具名和受限摘要。`AgentConsultationService._BridgeEvidenceProjector` 再把它们投影为房间可消费的 `agent.*` Case 证据事件：

| Worker 事件 | 房间证据事件 | 关键载荷 |
| --- | --- | --- |
| `worker_tool_call` | `agent.tool_call` | 参数摘要、调用 ID、轮次、执行路径 |
| `worker_tool_started` | `agent.tool_started` | 调用 ID、轮次、执行路径 |
| `worker_tool_result` | `agent.tool_result` | 成功状态、耗时、结果摘要、调用 ID |
| `agent_context_reinjected` | `agent.context_reinjected` | 工具结果已写回的轮次与调用 ID |
| `agent_turn_continued` | `agent.turn_continued` | 当前/前一轮次与执行路径 |
| `agent_loop_guard_triggered` | `agent.loop_guard_triggered` | Guard 原因、工具、轮次与路径 |

结果摘要最多保留受限长度，前端不接收完整原始工具结果包或长 reasoning 作为默认展示内容。

## 5. 协助室前端投影

`agentTeamsRoom.ts` 将 Case 证据事件映射为用户可理解的结构化阶段：

| 事件 | 默认文案 |
| --- | --- |
| `agent.tool_call` | 正在调用工具 |
| `agent.tool_started` | 工具执行中 |
| `agent.tool_result` | 工具调用完成/失败 |
| `agent.context_reinjected` | 工具结果已纳入下一步分析 |
| `agent.turn_continued` | Worker 已进入下一轮分析 |
| `agent.loop_guard_triggered` | 运行保护已触发 |

默认房间视图只显示阶段、状态、耗时与最终结果。开启协助室设置中的“默认展开底层事件”后，才可按步骤查看：

- `tool_call_id`；
- `round`；
- `execution_path`；
- 已截断的参数摘要和结果摘要。

这确保 Worker 工具结果与后续思考之间可追溯，同时避免房间默认视图被底层技术信息或原始 reasoning 刷屏。

## 6. Guard 与失败语义

- 相同工具及等价参数连续重复时，Worker 触发 `duplicate_tool_call` Guard；
- 工具连续返回同样结果时，Worker 触发无进展保护；
- 达到最大轮次时，返回阶段性结论并发出 `agent_loop_guard_triggered`；
- 工具失败必须以失败状态和失败摘要回传；Manager 不得把失败描述为“已完成”；
- Guard 触发后，不再继续盲目执行同一工具调用。

## 7. 关键实现位置

| 文件 | 本次职责 |
| --- | --- |
| `src/omichub/application/services/execution_events.py` | 统一生命周期事件和稳定字段。 |
| `src/omichub/application/services/chat_service.py` | Legacy/Studio 事件、Loop Guard 与结果收尾。 |
| `src/omichub/infrastructure/execution/langgraph_nodes.py` | LangGraph LLM 与工具节点的同语义事件。 |
| `src/omichub/application/services/agentteams_execution_intent.py` | `tool_execute` 及协助室意图判定。 |
| `src/omichub/application/services/agentteams_room_response_service.py` | 只读工具路由、失败可见性与房间回复。 |
| `src/omichub/application/services/parallel_subagent_service.py` | Worker ReAct、回灌、Guard 和工具结果摘要。 |
| `src/omichub/application/services/agent_consultation_service.py` | Worker 事件到 Case 证据事件的投影。 |
| `frontend/src/utils/agentTeamsRoom.ts` | 事件到结构化房间消息的映射。 |
| `frontend/src/views/AgentTeamsRoomView.vue` | Worker 卡片与技术事件详情展示。 |

## 8. 验证基线

已覆盖的关键自动化验证：

- Worker 工具调用、结果回灌和下一轮事件按同一调用 ID 关联；
- 重复工具调用触发 Guard 并终止继续调用；
- LangGraph 工具回灌事件序列完整；
- 协助室明确读取文件请求进入 `agentteams_tool_execution`，不会启动 Case planning；
- 前端投影保留调试关联字段，但默认文案不泄露它们；
- 前端 `vue-tsc --noEmit` 与 AgentTeams 房间投影测试通过。

建议复验命令见 `docs/architecture/agent-execution-loop-runbook.md`；代码与文档发生冲突时，以当前代码和测试为准。
