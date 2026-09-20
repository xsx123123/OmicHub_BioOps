# CygnusX Agent 当前执行框架

> 更新时间：2026-08-18  
> 文档定位：记录仓库当前已经存在的 Agent 请求装配、思考—工具闭环、LangGraph、Studio、AgentTeams Worker、房间路由和前端事件投影。本文优先描述“现在代码实际怎么运行”，不把未来规划误写成已上线能力。

## 1. 一页结论

CygnusX 当前是一个**多入口、共享工具契约、部分统一事件、分路径执行**的 Agent 平台：

1. 用户消息先经过会话、Agent、模型、MCP、Skill、Studio 和功能开关装配。
2. 普通聊天有两条主执行引擎：Legacy 手写 ReAct 循环和 LangGraph 状态图。
3. OmicStudio 使用独立的 Studio 工具循环，并在工具执行期间提供审批、计划、沙盒和 loop guard。
4. `parallel_subagents` 会派生受限 Worker；Worker 自己拥有多轮 ReAct，但不能递归 fan-out 或越权切换父会话。
5. AgentTeams 协助室同时存在 Case 执行链、Manager 咨询链和单步只读工具链；普通房间消息按 `chat / clarify / tool_execute / execute / degraded` 处理，只有明确的只读请求才进入 `tool_execute`。
6. 后端通过 SSE 发送正文、思考增量、工具调用、工具结果、审批和统一执行生命周期事件；前端按事件类型投影为消息、工具卡片、Worker 时间线和调试事件。

当前最重要的架构事实是：**“工具闭环已经存在”不等于“所有入口都使用同一个 Runtime”**。因此新增能力必须先声明执行路径，再选择对应的循环、上下文和治理边界。

## 2. 当前执行拓扑

```text
用户请求
   │
   ├─ 会话/Agent/模型/权限/能力装配
   │
   ├─ 普通聊天
   │    ├─ chat_legacy       → ChatService 手写 ReAct
   │    └─ chat_langgraph   → LangGraphRuntimeService
   │
   ├─ OmicStudio
   │    └─ studio_chat_loop  → Studio 工具循环 + 审批/计划/沙盒
   │
   ├─ AgentTeams 协助室
   │    ├─ chat              → Manager 会诊/普通回复
   │    ├─ clarify           → 结构化追问补全对象
   │    ├─ tool_execute      → 受控只读工具执行 + 结果回灌
   │    └─ case_execute      → 创建/推进 Case 规划与 Work Item
   │
   └─ parallel_subagents
        └─ agentteams_worker_react → 受限 Worker 多轮工具闭环
```

### 2.1 执行路径登记

| `execution_path` | 当前用途 | 主要入口 | 是否默认启用 |
| --- | --- | --- | --- |
| `chat_legacy` | 普通 Agent 的手写 ReAct 工具循环 | `ChatService.stream_agent_chat` | 是，取决于 Agent 配置 |
| `chat_langgraph` | 普通 Agent 的图化 ReAct | `ChatService._stream_agent_chat_langgraph` | 由 `features.engine=langgraph` 控制 |
| `studio_chat_loop` | 工作台工具、代码、文件和沙盒闭环 | `ChatService` Studio 分支 | 进入 Studio 会话时启用 |
| `agentteams_manager_consultation` | Manager 对 Case/房间上下文进行只读会诊 | `AgentConsultationService` | AgentTeams 场景启用 |
| `agentteams_worker_react` | Worker 执行受限任务和工具调用 | `ParallelSubAgentService._child_loop` | 被 Manager/工具显式派生时启用 |
| `agentteams_tool_execution` | 协助室明确的单步只读请求 | `AgentTeamsRoomResponseService._run_room_tool_execution` | 按意图受控启用，非默认会诊链 |

`execution_path` 是观测和排障字段，不负责替代权限判断。权限、工具白名单、执行模式和 Case 状态仍由各自服务强制校验。

## 3. 请求装配层

### 3.1 Agent 装配

请求进入 `ChatService` 后，运行时至少需要确定以下上下文：

| 上下文 | 作用 |
| --- | --- |
| `session_id` / `message_id` | 会话隔离、消息落库、SSE 关联和历史重载 |
| `agent_id` | 当前身份、提示词、能力范围和 handoff 白名单 |
| `model_config` | provider、模型、采样参数、最大输出和思考开关 |
| `system_prompt` | Agent 人格、领域规则、工具使用契约和用户侧输出约束 |
| `tools` | 当前请求真正暴露给模型的工具 schema |
| `active_mcp_servers` | 工具所属 MCP Server、调用通道和 fallback 顺序 |
| `bound_skills` / `skill_pins` | Skill 渐进式披露和版本固定 |
| `ToolInvocationContext` | 用户、Agent、会话、数据库和运行时扩展上下文 |
| `studio_mode` / `features` | Studio、LangGraph、MAS 等执行分流开关 |

模型看到的工具集合不是全局工具全集，而是经过 Agent、preset、Skill、Studio 模式、权限和执行模式裁剪后的请求级集合。

### 3.2 工具结果双通道

工具执行结果通常分为两路：

- `llm_payload`：回灌模型的紧凑结果，受长度上限保护，避免上下文无限膨胀。
- `ui_payload`：给前端卡片、图表、产物、终端输出和历史重载使用，可保留结构化展示字段。

任何新增工具都必须明确两路结果是否存在，并保证模型回灌内容不会直接携带超大原始文件、二进制内容或未脱敏错误堆栈。

## 4. 三类核心闭环

### 4.1 Legacy 手写 ReAct

`chat_legacy` 的最小语义如下：

```text
用户消息
  → provider_manager.chat_stream
  → 正文/思考增量
  → tool_calls？
       ├─ 否：持久化正文 → agent_final_result → done
       └─ 是：执行工具 → tool_result
                  → 追加 role=tool 消息
                  → agent_context_reinjected
                  → 下一轮模型调用
```

当前行为：

- 每轮分别累计正文、reasoning、tool calls 和 token usage。
- 工具结果会追加到 `llm_messages`，下一轮模型可读取。
- `ask_user` 会中断当前闭环，返回结构化追问并等待下一条用户消息。
- `handoff` 会结束当前 Agent，装配目标 Agent 后继续同一会话链路。
- 默认工具轮次上限为 100；用户确认后可扩展至 1000。
- Studio 工具循环额外接入 `StudioLoopGuard`。

### 4.2 LangGraph ReAct

`chat_langgraph` 通过 `LangGraphRuntimeService` 构建临时状态图：

```text
START → llm_call ── 无 tool_calls ──→ END
          │
          └──── 有 tool_calls → tool_exec → llm_call
```

节点职责：

- `llm_call_node`：流式调用模型，透传正文/思考，收集本轮 tool calls。
- `tool_exec_node`：逐个执行工具，透传 `tool_call` / `tool_result`，追加 `role=tool`。
- `route_after_llm`：根据错误和 tool calls 决定结束或执行工具。
- `route_after_tool`：根据 handoff、ask_user 和轮次预算决定继续或结束。

LangGraph 不是另一套工具契约；它复用 Provider、工具执行器、MCP 匹配和 ChatService 收尾逻辑，目标是让状态转移显式化，同时保持 Legacy 事件兼容。

### 4.3 Worker 受限 ReAct

`agentteams_worker_react` 是父 Agent 工具 `parallel_subagents` 派生的子循环：

1. 为每个子任务创建独立 `child_session_id` 和隔离工作目录。
2. 按 Worker 能力、`safe_only`、`workspace_access` 和控制工具黑名单准备工具。
3. Worker 可多轮调用允许的 builtin/MCP/工作区工具。
4. 工具结果截断后回灌 Worker 上下文。
5. Worker 返回稳定协作包，父 Agent 只接收结论、状态、证据引用、产物和错误摘要。

明确禁止：

- Worker 再次调用 `parallel_subagents`。
- Worker 直接切换父会话 Agent。
- Worker 创建跨会话 AgentTeams Case。
- Worker 未经审批执行需要确认的高风险工具。
- Worker 将内部 reasoning 原文直接当作 Manager 的最终结论。

## 5. AgentTeams 协助室框架

### 5.1 房间消息意图

`agentteams_execution_intent.py` 当前使用保守策略：

| 状态 | 判定 | 当前动作 |
| --- | --- | --- |
| `chat` | 无执行动词，或命中咨询/寒暄否决词 | 走 Manager 普通会诊/回复 |
| `clarify` | 有执行动词，但没有明确文件或上下文对象 | 发送结构化追问，最多追问有限轮次 |
| `tool_execute` | 明确读取、查看、检索、查询或只读复核对象 | 仅使用受控只读工具，结果回灌后由 Manager 回复 |
| `execute` | 有执行动词且有明确对象，且未命中否决词 | 启动 Case planning |

执行对象可来自附件/上下文引用，或文本中的常见数据文件名。该判定宁可漏触发，不因“分析”“运行”等词单独启动真实工作流。

### 5.2 Case 执行链

```text
房间消息
  → execution intent
  → route decision（当前仅执行态外显）
  → start_chat_planning
  → Case / Work Items
  → Manager / Worker / QC / delivery
  → AgentTeams 事件流
  → 房间时间线投影
```

`room.route_decision` 是观察卡片，不改变现有规划和路由逻辑。高置信请求展示选定 flow、Lead Planner、参与者和阶段；模糊请求展示候选选项和通用规划选项。

### 5.3 Manager 会诊链

非执行态消息由 `AgentConsultationService` 处理：Manager 读取 Case 上下文和证据，必要时调用受限 Worker 完成只读会诊，再将摘要、建议、风险和证据引用写入房间事件。

当前必须区分：

- **会诊**：目标是解释、建议和证据整理，不自动创建可写执行计划。
- **Case 执行**：目标是生成并推进 Work Item，必须经过 Case 状态、权限和审批边界。
- **普通房间 tool_execute**：仅在明确的读取、查看、检索、查询或只读复核请求中启用；它不是纯会诊的默认路径，也不授予写入或真实计算权限。

## 6. 统一事件框架

### 6.1 后端事件构造

统一生命周期事件由 `src/cygnusx/application/services/execution_events.py` 构造，核心字段为：

| 字段 | 含义 |
| --- | --- |
| `event_type` | 统一事件语义名称 |
| `session_id` | 用户会话关联 |
| `run_id` | 一次 Agent 执行关联；普通消息使用 message 级 run，Worker 使用 fan-out run |
| `agent_id` | 产生事件的 Agent/Worker |
| `round` | 当前模型—工具循环轮次 |
| `execution_path` | 当前执行路径 |
| `tool_call_id` | 工具事件的调用关联，可选 |

当前统一生命周期事件：

| 事件 | 语义 |
| --- | --- |
| `agent_turn_started` | 一次 Agent turn 开始，已完成上下文和工具装配 |
| `agent_context_reinjected` | 工具结果已写回模型上下文，下一轮具备继续条件 |
| `agent_turn_continued` | 工具结果回灌后（或其他合法原因）同一执行链进入下一轮 |
| `agent_final_result` | 本次执行形成最终结果、等待输入或达到轮次边界 |
| `agent_turn_failed` | 模型、工具、运行时或上下文处理失败 |
| `agent_loop_guard_triggered` | 运行保护触发，循环被安全中止或降级 |

旧事件仍保留：`text`、`tool_call`、`tool_result`、`worker_tool_call`、`worker_tool_result`、`loop_guard_triggered`、`done` 等。新事件用于可观测性和结构化时间线，不能要求旧前端立即删除兼容分支。

### 6.2 SSE 发送约束

`src/cygnusx/api/v1/chat.py` 将 `ChatChunk.type`、`content` 和 `metadata` 合并为 SSE JSON。生命周期事件必须在 `done` 之前发出，因为 `done` 是客户端认为本次流结束的终止事件。

### 6.3 前端投影

`frontend/src/composables/useAgentChatStream.ts` 当前提供：

- `onText`：正文和 reasoning 增量。
- `onToolCall` / `onToolResult`：工具卡片。
- `onLoopGuardTriggered`：Studio/普通循环护栏提示。
- `onExecutionEvent`：统一生命周期事件，供调试时间线、Worker 进度和房间投影消费。

正常用户界面应优先显示“正在检索 / 正在执行 / 已获得结果 / 正在整理”，而不是默认展示完整内部 reasoning。协助室开启“默认展开底层事件”后，Worker 卡片可查看 `tool_call_id`、`round`、`execution_path` 以及截断后的参数/结果摘要。

## 7. 运行保护与停止语义

### 7.1 已有保护

| 保护 | 当前实现 |
| --- | --- |
| 普通聊天轮次 | Legacy/LangGraph 默认 100 轮，可由用户确认扩展至 1000 |
| Studio 工具调用总数 | `StudioLoopGuard.max_tool_calls_per_turn` |
| Studio 连续失败 | 同工具/错误类型连续失败达到阈值后触发护栏 |
| Studio 自动降级 | `auto` 权限模式可降级为 `supervised` |
| Worker 轮次 | 子循环 `max_rounds` |
| Worker 单任务超时 | `asyncio.timeout` 包裹子任务执行 |
| Worker 失败隔离 | 单 Worker 失败不直接中断兄弟 Worker |
| Worker 控制 | pause/terminate 在安全点检查 |
| 工具结果长度 | LLM 回灌和 Skill 结果分别限制字符数 |

### 7.2 当前边界

当前 loop guard 主要保护**总量和连续失败**，还不是完整的“重复工具参数、无新信息、无进展”判定器。后续增加推进判定时，必须先定义可观测的进展信号，不能用模糊的文本相似度直接误杀合法重复查询。

取消、超时、审批等待和断流恢复也必须保持幂等：不能因前端重连而重复执行有副作用工具。

## 8. 数据与状态边界

### 8.1 消息状态

- 正文流式内容写入 Assistant Message。
- 工具调用、结果、timeline 和部分 UI payload 写入消息 metadata，支持历史重载。
- Token usage 在多轮模型调用后累计，再应用到会话用量。
- `ask_user` 形成等待用户输入的终止状态，不应继续后台执行。

### 8.2 AgentTeams 状态

- Case 是跨消息、跨 Worker、可审批和可恢复的协作边界。
- Work Item 是单个 Worker/阶段的执行边界。
- Evidence/Event 是房间投影和审计的事实流，不等同于普通聊天正文。
- Manager 会诊结论必须保留 evidence refs、风险和是否需要用户输入的状态。

### 8.3 Workspace 状态

普通聊天、Studio 和 Worker 的工作区权限不能混用：

- 普通聊天默认不能因为模型请求就获得任意写权限。
- Studio 写入必须经过会话权限模式和工具 schema。
- Worker 写入只能落在任务隔离目录，并由 `workspace_access` / execution mode 控制。
- 产物应通过结构化 artifact/文件引用传递，不把完整文件内容塞入对话上下文。

## 9. 修改和扩展规则

### 9.1 新增工具

1. 先确定工具属于 builtin、MCP、Skill 还是 Studio 能力。
2. 定义 schema、权限级别、是否需要确认、是否允许 Worker 使用。
3. 定义 `llm_payload` 和 `ui_payload`，明确长度和敏感信息处理。
4. 在 Legacy、LangGraph、Worker 中确认是否需要同等语义支持。
5. 补 `tool_call`、`tool_result`、失败、取消和重试测试。

### 9.2 修改循环

1. 不要只修改模型 prompt 来“修复循环”；先确认工具结果是否真正回灌。
2. 保留 `tool_call_id`、`run_id`、`round` 和 `execution_path`。
3. 新增终止分支时，必须同时处理持久化、SSE、前端状态和 token usage。
4. 所有最终结果事件必须先于 `done`。
5. 不要把 Worker 内部过程直接当作 Manager 最终结论。

### 9.3 新增路由

路由至少要返回：

```json
{
  "route": "chat | clarify | tool_execute | case_execute | degraded",
  "reason": "可审计的短原因",
  "confidence": "high | medium | low",
  "requires_tool": false,
  "requested_capabilities": [],
  "execution_path": "chat_legacy"
}
```

默认策略仍然是宁可 `clarify` 或 `chat`，不要因单个执行关键词误启动真实 Case 或写操作。

## 10. 当前验证清单

修改 Agent 闭环后至少验证：

- [ ] Legacy 多轮 tool call 能看到 `agent_context_reinjected`。
- [ ] LangGraph 与 Legacy 的 `tool_call` / `tool_result` 语义一致。
- [ ] 工具结果能进入下一轮模型 messages，而不是只发给前端。
- [ ] `ask_user`、handoff、错误、超时、取消均能正常收尾。
- [ ] Studio loop guard 触发后能降级或安全结束。
- [ ] Worker 失败不影响兄弟任务，Worker 最终状态可投影。
- [ ] 所有生命周期事件早于 `done`。
- [ ] SSE 断流/重连不会重复执行副作用工具。
- [ ] 前端普通模式不泄露原始内部 reasoning。
- [ ] 房间 `chat / clarify / execute` 判定有对应测试，纯咨询不会启动 Case。

## 11. 关键实现位置

| 位置 | 职责 |
| --- | --- |
| `src/cygnusx/application/services/chat_service.py` | 普通聊天、Studio、Legacy/LangGraph 分流、工具执行和消息收尾 |
| `src/cygnusx/application/services/execution_events.py` | 统一 Agent 生命周期事件构造 |
| `src/cygnusx/infrastructure/execution/langgraph_nodes.py` | LangGraph LLM/工具节点和路由 |
| `src/cygnusx/infrastructure/execution/langgraph_runtime.py` | LangGraph 图运行和队列流式输出 |
| `src/cygnusx/application/services/studio_loop_guard.py` | Studio 工具循环护栏 |
| `src/cygnusx/application/services/parallel_subagent_service.py` | Worker fan-out、子 ReAct、隔离和控制 |
| `src/cygnusx/application/services/agentteams_execution_intent.py` | 协助室执行意图三态判定 |
| `src/cygnusx/application/services/agentteams_room_response_service.py` | 房间消息响应、澄清、Case 执行触发和路由卡片 |
| `src/cygnusx/application/services/agentteams_route_decision.py` | `room.route_decision` 观察卡片构造 |
| `src/cygnusx/application/services/agent_consultation_service.py` | Manager 会诊和 Worker 证据投影 |
| `src/cygnusx/api/v1/chat.py` | ChatChunk → SSE |
| `frontend/src/composables/useAgentChatStream.ts` | SSE 解析和前端事件回调 |
| `frontend/src/stores/agentHub.ts` | 普通助手、Studio、工具和护栏状态投影 |
| `frontend/src/utils/agentTeamsRoom.ts` | AgentTeams 事件到房间块/消息的纯函数投影 |
| `frontend/src/views/AgentTeamsRoomView.vue` | Worker 卡片、Guard 警示与技术事件详情展示 |

## 12. 与其他架构文档的关系

- 本文是“当前实现快照”，优先回答现在代码如何运行。
- `agent_framework_final_baseline.md` 是较早的 Agent 基线和发布验收文档。
- `agent_architecture_and_extension_guide.md` 侧重 Agent 配置、扩展和能力状态。
- `agentteams_room_plan.md` 侧重团队协作室的产品实施路线和里程碑。
- `cygnusx_studio.md` 侧重 OmicStudio 工作台的产品实现与交接。
- `docs/info/26.8.18/CygnusX-Agent思考工具闭环优化实施计划与编码提示词.md` 是本次闭环优化的实施计划、验收标准和编码提示词。
- `agent_execution_loop_observability_2026-08.md` 记录本轮事件关联、房间只读工具路由、Worker 时间线和验证基线。

当文档之间描述冲突时，以当前代码、测试和运行配置为事实来源；目标方案必须明确标记为“计划”或“待实现”。
