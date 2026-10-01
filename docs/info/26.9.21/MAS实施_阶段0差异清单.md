# MAS 最小实现 · 阶段 0 差异清单（只查不改）

> 基线日期：2026-09-20。逐项核实《生物信息部门页面_MAS最小实现实施手册》Part 0 假设与真实接口的差异。
> 环境：子代理不可用（400 模型未找到），全部由主会话直接核实。

## 1. assemble_context()（`application/services/agent_service.py:802`）

```python
async def assemble_context(
    agent_id: str, user_id: str | None = None, tool_query: str | None = None,
    model_id: uuid.UUID | None = None,
) -> AgentContext | None
```

- 返回 `AgentContext | None`：agent 不存在或 `is_active=False` 返回 **None**（不抛异常），与手册假设一致。
- ⚠️ 差异 1：手册说"产出 `AgentContext`（system_prompt/tools/...）"。实际有两个同名 `AgentContext`：
  - `application/services/agent_service.py:201` 的 dataclass：**`agent` + `assembled` 风格**（agent/model_config/system_prompt/tools/mcp_servers/skills/features/temperature/max_tokens）——`assemble_context` 返回的是这个。
  - `domain/execution/agent_context.py:10`：`session/assembled/mode/execution_path/trace_id/run_id`，是**聊天 Runtime 的上下文**，与 `assemble_context` 无关。
  - 施工采用 `agent_service.py` 版本；Worker 的 system_prompt/tools/features 均可直接取。
- `features` 已含用户能力合并（`_effective_user_features`），Worker 剥离 `parallel_subagents`/`transfer_to_agent` 须从该 dict 剥离。

## 2. LangGraphChatRuntime / ChatRuntimeRequest（`runtimes/base.py:16`）

- `ChatRuntimeRequest` 必填仅 3 个：`user_id: str`、`agent_id: str`、`messages: list[dict[str, str]]`；其余全有默认（session_id/model_id/mode/multi_agent/overdrive/auto_approve 等）。✅ 与手册假设一致，无需改既有类。
- `ChatRuntime.run(request) -> AsyncIterator[ChatChunk]`；`LangGraphChatRuntime(DelegatingAgentRuntime)` 委托 `ChatService._stream_agent_chat_inner(...)`（`chat_service.py:2570`，21 参数）。
- ⚠️ 差异 2（重要）：`_stream_agent_chat_inner` **会自动取/建 chat_session**（session_id=None 时隐式 create_session，`chat_service.py:2806`），并做 cookie 余额预检、写 `chat_messages` 落库等副作用。Worker 委托它会写入聊天链路表。手册红线 8 数据隔离要求"不动 chat_sessions/chat_messages 表结构"——写新记录不算改结构，但每次 Worker turn 会新建一条会话。**决策：阶段 2 先按手册 2.3 委托 `LangGraphChatRuntime`（每 Worker turn 一个内部会话，run_id 记入 metadata 便于追踪）；如用户不接受隐式会话，阶段 0 上报后改走更底层的直连路径（需另行评估）。**
- ChatChunk（`infrastructure/ai_provider/openai_compatible.py:191`）：`type / content / metadata`；type 枚举：`text | tool_calls | tool_call | tool_output | tool_result | plan | ask_request | approval_request | approval_resolved | error | done`。
- 最终 assistant 文本识别：`type == "text"` 的增量拼接，`done`/`error` 终结；`agent_final_result`（execution_chunk）也携带最终文本。
- 审批 chunk：`type="approval_request"`（resolution 走 StudioApprovalService 既有链路）；Worker 中直接透传 SSE。

## 3. AgentState 与截断常量（`domain/execution/agent_state.py`）

- AgentState：`messages: Annotated[list[dict], operator.add]`、`rounds/usage/error/handoff/ask_request/finalize/code_cell_only_round`。MASState 照此风格，手册骨架直接可用。
- `TOOL_RESULT_MAX_CHARS = 4000`（`infrastructure/execution/langgraph_nodes.py:36`）✅ 与手册 2.4 假设一致。

## 4. orchestrator_graph.py 图惯例（`infrastructure/execution/orchestrator_graph.py`）

- `StateGraph(OrchestratorState)` + `add_node` + `add_conditional_edges` + `builder.compile(checkpointer=...)`（:412-435）。
- interrupt：节点内 `decision = interrupt(payload)`（:178）；resume 经 `Command(resume=...)`；调用方从结果 `__interrupt__` 键读挂起 payload（:452）。
- checkpointer 工厂已存在**可直接复用**：`infrastructure/execution/checkpointer.py` 的 `postgres_checkpointer()`（AsyncPostgresSaver + setup()）与 `memory_checkpointer()`。thread_id = run_id（`configurable.thread_id`，:439）。✅ 无需新建 mas_checkpointer.py。

## 5. 路由注册与 SSE 先例

- 接线点：`api/v1/router.py:137` 风格——新增 `api_router.include_router(mas_rooms.router, prefix="/mas/rooms", tags=[...])`，不改 main.py。
- SSE 先例：`api/v1/goals.py:140-168`（StreamingResponse + `text/event-stream` + `data: {...}\n\n` + `: heartbeat` + X-Accel-Buffering: no + 每 1s 轮询 DB + pubsub）。MAS 房间 SSE 按此惯例（进程内 asyncio Queue 广播 + DB 轮询兜底）。

## 6. 迁移惯例

- Alembic：`alembic/versions/<rev>_<slug>.py`，revision 为语义串（如 `cacheprice0001`），`down_revision` 链式。⚠️ 备忘：历史上有多 head 分叉前科，新迁移的 down_revision 必须 `alembic heads` 实查后填（当前 head 链尾 `cacheprice0001`，施工时再确认）。

## 7. 账本选型

- `overdrive_runs`（`infrastructure/database/models/overdrive.py:16`）**强绑定 chat_sessions.session_id（FK CASCADE、非空）**与 Overdrive 语义（plan/manager_tasks/assistant_instances 等）——不可直接承载 MAS 房间 run。
- ⚠️ 差异 3：项目已有 `mas_runs`/`mas_plans`/`mas_nodes`/`mas_a2a_events` 表（`infrastructure/database/models/mas.py`，旧 A2A 系统）但字段同样强绑定 `plan_id 非空 + users.id UUID FK`。为满足手册"独立新表"与"node 级事件可审计"，**新建 `mas_room_runs` + `mas_room_events` 两表**（字段对齐 runs/events 模式，room_id 维度），不碰 overdrive_* / mas_*（旧 A2A）任何结构。

## 8. 前端事实

- SSE：`useAgentChatStream.ts` 用 **fetch + ReadableStream 手解 SSE**（非 EventSource），POST body、Bearer token、retry 有 `isRetryableStreamStatus`。部门页面的 SSE（GET 订阅流）将按同款 fetch-stream 写法新写 `stores/masRoom.ts`（EventSource 不便带 token）。
- 消息渲染：`KimiMessageItem.vue` 依赖会话上下文较重；部门页面时间线**新写轻量渲染**（头像 = avatar emoji + color 底，Markdown 复用项目现有渲染函数——施工时从 KimiMessageItem 引同一 markdown 组件/函数）。
- avatar/color：`AgentTemplateDTO`（`application/schemas/agent.py:29`）直接给 `avatar: str`（emoji，如 🧬）、`color: str`（hex）。部门成员列表直接用 `GET /api/v1/agents`（启用中列表）。
- 路由/导航：`frontend/src/router/index.ts`（DefaultLayout children 懒加载）+ `DefaultLayout.vue:257-289` `mainNavItems` 数组（一行加导航项）。
- 部门成员名册：YAML category 分布——`analysis` 类（rnaseq/atacseq/qc/scrna*/data/delivery/explorer 等）即"生物信息"主力气；MVP 用 `category in {analysis, visualization}` 或前端按 `GET /agents` 全量 + 指定 agent_id 白名单渲染。

## 9. 与手册假设冲突需用户知晓的点（不阻塞开工）

1. Worker 委托 `LangGraphChatRuntime` 会产生隐式 chat_session（见差异 2）——手册红线只禁"改结构"，落新记录不违规，但请知悉。
2. 账本新建 `mas_room_runs`/`mas_room_events`（overdrive_runs 有 chat_sessions FK 非空，不可复用；旧 mas_runs 绑 plan_id 非空，也不宜复用）。
3. `assemble_context` 失败返回 None 而非异常——Worker 执行器须自行产出错误信封文本。
