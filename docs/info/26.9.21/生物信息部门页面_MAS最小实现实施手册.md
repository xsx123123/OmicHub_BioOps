# 生物信息部门页面 × LangGraph MAS 最小实现实施手册

> **文档定位**：交给编码 Agent（Claude Code）施工的分阶段实施手册。验收权在用户手里，编码 Agent 自报通过不算数。
> **基线日期**：2026-09-20
> **一句话目标**：在 CygnusX 平台上新增一个"生物信息部门"页面——用户在房间里提出科学问题，一个 Supervisor Agent 组织若干专员 Agent（团队感讨论 + 派工执行），人可以在关键节点判断/驳回/修改，全过程 SSE 实时可见、Postgres 持久化、事件可审计。
> **技术底座既定，不允许更换**：langgraph 1.2.x（只做状态图载体）、裸 OpenAI dict 消息、`operator.add`、自研 httpx Provider、FastAPI SSE、PostgreSQL + SQLAlchemy async、Vue3 + Pinia 前端。**禁止引入** LangChain 消息封装、CrewAI/AutoGen 等外部 MAS 框架、Matrix、Redis Stream、任何新中间件。

---

## Part 0　平台现状事实（施工前必读，全部已存在于代码库）

编码 Agent 施工前必须先阅读并遵守以下既有实现，**新代码一律复用，不重写**：

| 既有资产 | 位置 | 本项目的复用方式 |
| --- | --- | --- |
| Agent 定义（20 个 YAML + ORM） | `data/ai/*.yaml`；`infrastructure/database/models/agent.py` `AgentTemplateModel`（含 avatar/color/name/category 字段） | 部门成员名册的唯一来源；`avatar/color/name` 直接渲染前端"团队感" |
| 上下文装配 | `application/services/agent_service.py` `assemble_context(agent_id, user_id, tool_query, model_id)` | Worker 节点执行器的入口，产出 `AgentContext`（system_prompt/tools/mcp_servers/skills/model_config） |
| 单 Agent ReAct 运行时 | `application/services/chat/runtimes/langgraph_runtime.py` `LangGraphChatRuntime` | Worker 的"一次完整 turn"直接委托它，不要新写 ReAct 循环 |
| 统一流式抽象 | `infrastructure/ai_provider/openai_compatible.py` `ChatChunk`（type/content/metadata） | MAS 所有节点的事件只准以 `ChatChunk` 形态产出 |
| 编排图先例 | `infrastructure/execution/orchestrator_graph.py`（`plan_generate → plan_confirm → dispatch → aggregate`，`AsyncPostgresSaver`） | MAS 图的写法、checkpoint 用法、interrupt 用法对齐它 |
| 状态规范 | `domain/execution/agent_state.py` `AgentState`（裸 dict + operator.add） | `MASState` 照抄该风格 |
| 生命周期事件 | `application/services/execution_events.py` | MAS 节点产生的事件走同一套 event_type 契约 |
| 账本 | `overdrive_runs` / `overdrive_events` 表 | MAS run 的权威状态账本（约束：LangGraph state 只作恢复载体） |
| 前端 | Vue3 + Pinia + SSE（`frontend/src/stores/agentHub.ts` 等） | 部门页面复用现有消息渲染、SSE 消费、agent 头像配色逻辑 |

**架构红线（来自平台架构备忘录，违反即打回）**：

1. 新能力一律进 LangGraph 图，禁止新增 legacy 手写循环。
2. `messages` 保持裸 OpenAI dict 格式，禁止引入 LangChain `BaseMessage`。
3. 权威状态账本是 `overdrive_runs` / `overdrive_events`（或本手册新建的房间/消息表），图内 state 与 checkpoint 只作执行恢复载体。
4. 上下文历史由调用方显式传入，禁止在 MAS 图内隐式依赖进程内变量记状态。
5. 每个 Worker 的持久化写操作独占独立 AsyncSession（并发共享父 session 必崩）。
6. 新增工具/节点产出必须区分 `llm_payload`（回灌模型，截断）与 `ui_payload`（前端展示）。
7. 审批类动作（沙箱执行等）沿用既有 `StudioApprovalService` 审批闸语义，不在 MAS 层另造审批。

---

## Part 1　MVP 边界（写死，编码 Agent 不得自由扩展）

### 必须交付

1. **部门页面**：新前端路由页面 `/department`，左侧部门成员列表（读 `agent_templates` 中 category=生物信息 或 YAML 指定标记的 Agent，展示 avatar/name/description），中间房间消息时间线（按 agent 渲染头像与名字，体现"团队感"），底部输入框。
2. **房间模型**：一个部门一个默认房间（MVP 不支持多房间创建），房间消息持久化。
3. **Supervisor-Worker MAS 图**：用户发消息 → Supervisor 决策（自己答 / 派给专员 / 发起 2~3 人短讨论）→ Worker turn → 回灌 Supervisor → 终结；带轮次熔断。
4. **全链路 SSE**：Supervisor 派工轨迹、各专员打字机输出、终结事件，全部实时推到部门页面时间线。
5. **人工判断点（interrupt）**：Supervisor 形成"实验/分析计划"时暂停，页面上出现 批准/驳回/修改 卡片；批准后继续执行。
6. **run 账本**：每次部门会话 run 落 `overdrive_runs` 或新建等价表，节点级事件可审计。

### 明确不做（负面清单）

| 不做 | 理由 |
| --- | --- |
| 多房间/建房间/邀请成员 | MVP 一个默认房间即可，避免房间管理 UI 膨胀 |
| Worker 内真实工具执行的审批链改造 | 复用既有审批闸原样，不动语义 |
| Map-Reduce 并行 Worker / Group Chat 自由发言 | 第二阶段；MVP 只串行 Supervisor→单 Worker |
| Handoff 跨 Agent 移交 | 现有 Handoff 已落地，部门页面暂不接入 |
| Matrix / AgentTeams Bridge / Redis Stream | 明确下线目标，禁止任何形式复活 |
| 长期记忆写入新逻辑 | 复用 `PostgresFactStore`，不新造 |
| 移动端适配、暗色主题专项改造 | 复用平台现有主题 |
| run 从 checkpoint 人工恢复的管理界面 | 后端崩溃恢复可用即可，不做 UI |

---

## Part 2　架构设计

### 2.1 MASState（对齐 AgentState 风格）

```python
# domain/execution/mas_state.py
class MASState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]   # 裸 OpenAI dict
    orchestration_rounds: int      # Supervisor 派工轮次（熔断计数，Worker 不递增此字段）
    next_worker: str | None        # supervisor 路由结果； "__finish__" 表终结
    room_id: str
    run_id: str
    pending_plan: dict[str, Any] | None   # interrupt: 待人审的实验计划
    plan_decision: dict[str, Any] | None  # resume:  {action: approve|reject|edit, edited_plan?}
    error: str | None
```

注意：第二个文档骨架里 Worker 也 +1 round 的写法废弃——协同轮次与 Worker 内部 ReAct 轮次分离，只有 Supervisor 决策计 1 轮，`max_orchestration_rounds` 默认 8。

### 2.2 图拓扑

```
START → supervisor
supervisor --(路由)--> worker_{agent_id}  /  plan_review(interrupt)  /  END
worker_{agent_id} --> supervisor
plan_review(interrupt: 人工批准/驳回/修改) --> supervisor 或 END
```

- Supervisor 节点：读 `messages` + 成员能力描述（来自 YAML 快照，渐进暴露：summary 层注入路由上下文），输出结构化 JSON `{next_worker, rationale}` 或 `{plan, need_human_review: true}`。解析失败静默回落"自己直接回答"并记事件，**绝不抛异常中断 run**。
- Worker 节点：调用 Worker 执行器（见 2.3），把产出的最终文本作为 `{"role":"assistant","name":agent_id,"content":...}` 增量回灌。Worker 产出不进 Supervisor 的完整历史原文——见 2.4 裁剪。
- `plan_review`：`interrupt()` 挂起，checkpoint 落 Postgres；人工决议经 API 写入 `plan_decision` 后 `Command(resume=...)` 继续。
- 图用 `AsyncPostgresSaver`，`thread_id = run_id`。

### 2.3 Worker 执行器（唯一允许的新执行适配层）

```python
# application/services/mas/mas_worker_executor.py
async def run_worker_turn(
    agent_id: str, user_id: str, messages: list[dict], emit: Callable[[ChatChunk], None]
) -> str:
    """
    1. assemble_context(agent_id, user_id, ...) 装配目标 Agent
    2. 构造 ChatRuntimeRequest（messages 为裁剪后的历史，见 2.4；mode="chat"）
    3. 委托 LangGraphChatRuntime.run()，消费其 AsyncIterator[ChatChunk]：
       - 逐 chunk 调 emit() 透传给房间 SSE（打字机实时性）
       - 收集最终 assistant 文本作为返回值
    4. 返回最终文本（失败时返回错误信封文本，不抛异常）
    """
```

关键约束：worker 的 `features` 必须剥离 `parallel_subagents` / `transfer_to_agent`（防递归）；审批类工具按 C4 语义升级回 Supervisor（MVP 简化为：requires_confirm 工具在 Worker 中直接按既有审批闸走，审批请求 chunk 正常透传 SSE）。

### 2.4 上下文裁剪（必须有，否则长讨论必爆）

Worker 收到的 messages 不是房间全量历史，而是：

1. 原始 user 问题；
2. 最近 N 条（默认 10 条）房间消息；
3. 更早历史折叠为一段 Supervisor 摘要（Supervisor 节点每轮顺手产出，≤500 字）。

Worker 产出回灌 Supervisor 前截断至 4000 字符（对齐 `TOOL_RESULT_MAX_CHARS`）。Supervisor 派工轨迹消息 `{"role":"system","name":"mas_trace",...}` 只用于前端时间线渲染与审计，**注入 Supervisor 自己的上下文时剔除 mas_trace 消息**，防止系统消息污染对话。

### 2.5 房间消息模型与 API（新建表，最小化）

```sql
-- 新表 mas_room_messages（不使用 chat_messages 加列，避免污染聊天链路）
id uuid pk
room_id text not null default 'bioinfo-dept'
run_id text null                -- 属于哪次 MAS run
agent_id text null              -- null=用户；否则=发言的 Agent（Supervisor 或专员）
role text not null              -- user | assistant | mas_trace | plan_card
content text not null
metadata jsonb default '{}'     -- rationale / plan 结构 / token usage / sse 已推送标记
created_at timestamptz default now()
```

API（挂在 `api/v1/` 下，新文件 `mas_rooms.py`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/mas/rooms/bioinfo-dept/messages?limit=100` | 拉历史（页面首屏） |
| POST | `/api/v1/mas/rooms/bioinfo-dept/messages` | 用户发言 → 落库 → 启动/续跑 MAS run |
| GET | `/api/v1/mas/rooms/bioinfo-dept/stream` | SSE 订阅（run 内事件 + 本房间新消息） |
| POST | `/api/v1/mas/runs/{run_id}/plan-decision` | 人工判断点决议（approve/reject/edit） |

SSE 事件格式复用既有 `ChatChunk` 序列化约定（`data: {...}\n\n`），新增 `type="mas_trace"` 与 `type="plan_card"` 两种，前端按 metadata 渲染。run 终态必须发 `done` 或 `error`；所有最终事件先于 `done` 到达。

### 2.6 run 账本

每次 POST 发言若当前房间无活跃 run 则新建 run：写 `overdrive_runs`（或若该表结构强绑定 Overdrive 语义，则新建 `mas_runs` 表，字段对齐 runs/events 模式——施工时先读 `overdrive_runs` 模型再定，**优先复用**）。节点级事件（supervisor_decided / worker_turn_started / worker_turn_finished / plan_interrupted / plan_resumed / run_finished / run_failed）落事件表。编码 Agent 不得只写 LangGraph checkpoint 而不落账本。

---

## Part 3　新增文件清单（模块结构）

```
src/cygnusx/
├── domain/execution/mas_state.py            # MASState TypedDict
├── domain/mas/
│   ├── room_models.py                       # mas_room_messages ORM
│   └── worker_policy.py                     # Worker 工具剥离/裁剪规则（纯函数，可单测）
├── application/services/mas/
│   ├── mas_graph.py                         # build_mas_graph() + supervisor/worker/plan_review 节点
│   ├── mas_worker_executor.py               # run_worker_turn()（2.3）
│   ├── mas_context.py                       # 历史裁剪/摘要折叠（2.4）
│   └── mas_room_service.py                  # 房间消息读写、run 启停、事件落账
├── api/v1/mas_rooms.py                      # 4 个 endpoint（2.5）
└── infrastructure/execution/mas_checkpointer.py  # 仅当 overdrive 的 checkpointer 工厂不能直接用才新建

frontend/src/
├── views/DepartmentView.vue                 # 部门页面（或按现有目录约定命名）
├── stores/masRoom.ts                        # Pinia store：SSE 消费 + 消息列表 + plan 卡片状态
└── components/department/                   # MemberList / Timeline / PlanCard / Composer
```

施工纪律：改 `chat_service.py` / `langgraph_runtime.py` 等既有大文件时**最小侵入**，新逻辑放新模块；需要触发的既有函数用调用而非拷贝。

---

## Part 4　分阶段施工（每阶段独立可验，顺序执行，不许跳阶段汇报）

### 阶段 0　现状对齐（只查不改）

**目标**：让编码 Agent 把 Part 0 的事实清单核实一遍，确认复用点的真实接口签名（施工期最大的坑是接口签名与文档假设不符）。

```text
只做代码级调研，禁止修改任何代码。逐条阅读以下位置并输出核实结果表：
- application/services/agent_service.py 的 assemble_context()：完整函数签名、返回值 AgentContext 各字段、失败行为
- application/services/chat/runtimes/langgraph_runtime.py 的 LangGraphChatRuntime.run()：入参 ChatRuntimeRequest 如何构造（列出全部必填字段）、返回的 ChatChunk 序列中最终文本如何识别、requires_confirm 工具的审批 chunk 长什么样
- infrastructure/execution/orchestrator_graph.py：图的节点定义方式、interrupt/resume 的写法、AsyncPostgresSaver 的挂载方式、thread_id 的用法
- domain/execution/agent_state.py 与 langgraph_nodes.py：消息增量返回的约定、tool 回灌截断常量
- overdrive_runs / overdrive_events 的 ORM 定义：字段清单，判断是否可直接承载 MAS run，还是必须新建 mas_runs
- frontend 现有 SSE 消费与消息渲染组件：agentHub.ts 中 SSE 订阅方式、消息按 role/agent 渲染头像的组件路径
- data/ai/*.yaml：找出哪些 Agent 属于生物信息部门（category 或 features 标记），列出 agent_id/name/avatar/color
交付：以上每项给出「文件路径:行号 + 关键签名/字段 + 与本手册假设的差异」。差异逐条列出，不得隐瞒。
```

**用户验收**：差异清单里没有"接口签名与本手册假设冲突但未声明"级别的遗漏。

### 阶段 1　房间消息 + API（无 AI）

**目标**：房间消息表、4 个 endpoint 中除 MAS 逻辑外的骨架（POST 发言只落库并返回，不启动 run）、SSE 能推送消息落库事件。

**提示词**：

```text
在 CygnusX 代码库中实现部门房间的消息层（本阶段不含任何 AI/MAS 逻辑）：
1. 按手册 Part 2.5 新建 mas_room_messages 表与 ORM（domain/mas/room_models.py），写 Alembic 迁移或沿用项目既有建表方式（先读项目现有迁移惯例再动手）。
2. 新建 api/v1/mas_rooms.py：
   - GET /messages：按 created_at 倒序分页，返回 {role, agent_id, content, metadata, created_at}
   - POST /messages：校验 content 非空，落库（role=user），返回消息记录；本阶段不触发 run
   - GET /stream：SSE，订阅本房间新消息（落库即推送，格式按 ChatChunk SSE 约定，type 沿用消息 role 或新增 room_message 事件类型——与前端 stores 对齐后定）
3. 前端 DepartmentView.vue + stores/masRoom.ts：部门页面骨架——成员列表（从 agent_templates 读，avatar/name/description 渲染）、消息时间线（复用现有消息渲染组件，用户消息在右、Agent 消息在左带头像）、输入框。SSE 断线按项目既有重连惯例处理。
约束：不改 chat_messages / chat_sessions 任何既有逻辑；SSE 心跳沿用平台既有实现。
```

**验收（用户手测）**：

| 操作 | 期望现象 | 不通过时 |
| --- | --- | --- |
| 打开 /department | 左侧出现生物信息部门成员列表（有头像名字），中间空白时间线，底部输入框 | 检查 agent_templates 是否有 category 匹配的 Agent；没有就先在 YAML 补一个测试 Agent |
| 输入"你好"发送 | 消息立即出现在时间线右侧，刷新页面后仍在（DB 持久化） | 查 mas_room_messages 表是否有记录；SSE 是否推送 |
| 两个浏览器标签同时打开页面 | A 标签发的消息 B 标签实时出现 | 查 SSE 订阅与广播范围 |

### 阶段 2　MAS 图核心（后端，无前端改动）

**目标**：Supervisor-Worker 图跑通：POST 发言触发 run，Supervisor 决策 → Worker turn（真实 Agent 执行）→ 回灌 → 终结；消息全部落 mas_room_messages；trace 事件落账本。

**提示词**：

```text
实现 MAS 编排核心（按手册 Part 2.1–2.4、Part 3）：
1. domain/execution/mas_state.py：MASState 按手册定义（orchestration_rounds 仅 Supervisor 递增）。
2. domain/mas/worker_policy.py：纯函数 strip_worker_tools(features)（剥离 parallel_subagents / transfer_to_agent）与 build_worker_messages(room_history, fold_summary, limit)（裁剪规则按手册 2.4）；每个函数配 pytest 单测。
3. application/services/mas/mas_worker_executor.py：run_worker_turn() 按手册 2.3 实现——assemble_context → 构造 ChatRuntimeRequest（字段以阶段 0 核实结果为准）→ 消费 LangGraphChatRuntime.run() 的 chunk 流，逐 chunk 落 mas_room_messages（role=assistant, agent_id=目标 Agent，metadata 记 chunk 序号）并同时 emit 到 SSE 分发器；收集最终文本返回；任何异常返回错误信封文本，不向上抛。
4. application/services/mas/mas_graph.py：
   - build_mas_graph(members, worker_executor, max_rounds=8)：supervisor 节点（提示词要求输出 JSON {next_worker, rationale} 或 {plan, need_human_review}；解析失败回落自己直接回答并落 mas_trace）、worker 节点工厂、条件路由、orchestration_rounds 熔断（触顶强制收尾）
   - supervisor 上下文注入时剔除 mas_trace 消息
   - 图挂 AsyncPostgresSaver（thread_id=run_id，复用阶段 0 确认的挂载方式）
5. application/services/mas/mas_room_service.py：POST 发言后启动/续跑 run——无活跃 run 则新建 run 并落账本（runs/events 表的选用按阶段 0 结论）；run 内每个 supervisor 决策落一条 mas_trace 消息；run 终态发 done 事件。
6. mas_room_messages 落库必须使用独立 AsyncSession（红线 5）；SSE 分发用进程内 asyncio Queue 广播即可（单 web 进程多 worker 的广播一致性本阶段不做，写明 TODO）。
约束：禁止新写 ReAct 循环；禁止引入 LangChain 消息封装；所有节点产出区分 llm_payload/ui_payload 语义（落库内容即 ui_payload，回灌模型的按 2.4 截断）。
```

**验收（用户手测 + Agent 跑测试）**：

| 操作 | 期望现象 | 不通过时 |
| --- | --- | --- |
| Agent 跑 worker_policy 单测 | 全部通过 | 先看裁剪规则实现 |
| 页面发送"帮我检查这批 RNA-seq 数据的质量" | 时间线依次出现：mas_trace（派工轨迹，含理由）→ 专员头像的打字机回复 → run 结束事件；刷新页面后全部仍在 | 先查账本事件表判断卡在哪一节点；再看 web 日志；**不接受"前端显示了就算通"——以后端事件表为准** |
| 连续发 3 条消息 | 同一房间复用活跃 run 或正确新建 run，轮次计数正确 | 查 orchestration_rounds 与账本 |
| 让 Supervisor 决策 8 轮以上 | 触发熔断强制收尾，时间线出现收尾提示，run 状态 finished 不挂死 | 查熔断分支 |

### 阶段 3　人工判断点（plan interrupt）

**目标**：Supervisor 产出"实验/分析计划"时 run 挂起，页面出现计划卡片，用户批准/驳回/修改后 run 继续或终结。

**提示词**：

```text
在阶段 2 的 MAS 图上增加人工判断点（对齐 orchestrator_graph.py 的 interrupt/resume 惯例）：
1. supervisor 节点输出 need_human_review=true 时，将 plan 写入 state.pending_plan 并 interrupt()；checkpoint 落 Postgres。
2. mas_room_service 检测 interrupt 后：落一条 role=plan_card 的消息（metadata 携带 plan 结构与 run_id），SSE 推送 plan_card 事件，run 进入 awaiting_review 状态（账本落事件）。
3. POST /api/v1/mas/runs/{run_id}/plan-decision：接收 {action: approve|reject|edit, edited_plan?}，写 state.plan_decision，Command(resume=...) 继续图：
   - approve → supervisor 按 plan 派工执行
   - edit → 以 edited_plan 替换 pending_plan 后继续
   - reject → 落 trace 消息，run 正常终结
4. 前端 PlanCard 组件：渲染计划步骤列表，三个按钮；决议后卡片变为已批准/已驳回状态并附用户决议记录。
5. 挂起的 run 在 web 进程重启后必须可从 checkpoint 恢复（用阶段 0 的 checkpointer 方式验证）。
约束：interrupt/resume 语义与既有 orchestrator 图保持一致，不自创 API；人工决议必须落账本事件。
```

**验收**：

| 操作 | 期望现象 | 不通过时 |
| --- | --- | --- |
| 发送会触发计划的消息（如"帮我设计一个差异分析流程并执行"） | 时间线出现计划卡片，run 停住，无后续 Worker 输出 | 查 interrupt 是否触发、plan_card 是否落库 |
| 点"批准" | 卡片变已批准，派工继续执行 | 查 plan-decision API 与 resume 链路 |
| 点"驳回" | 卡片变已驳回，run 终结，无执行 | 查 reject 分支 |
| 修改计划后提交 | 按修改后的计划执行 | 查 edit 分支 |
| 卡片挂起时重启 web 容器 | 重新打开页面卡片仍在，决议后 run 继续 | 查 checkpoint 恢复 |

### 阶段 4　打磨与边界

**提示词**：

```text
1. Worker turn 内触发审批类工具（如 chat_sandbox_execute，supervised 模式）：审批请求卡片正确出现在部门页面时间线，批准/拒绝后 Worker 继续，决议落审计日志（复用 StudioApprovalService 既有链路，语义不得改动）。
2. 故障注入测试：Worker 模型调用 401 / 超时 / 返回乱码 JSON 时，run 不落死——错误信封回灌 Supervisor，Supervisor 决策"自己兜底回答或终结"，页面可见兜底消息，账本落 run_failed 或 finished。
3. 并发红线回归：同房间两条消息几乎同时发送，不产生两个并发写同一 run 的会话（用 runs 表状态乐观锁：仅无活跃 run 才新建）。
4. token usage 每个 turn 落消息 metadata。
```

**验收**：编码 Agent 提交每项的测试证据（测试输出片段 + 后端事件表记录），用户抽查复现 2 和 3。

### 阶段 5（后续，不属于本 MVP）：并行 Worker、Handoff 接入、多房间、讨论式 Group Chat。

---

## Part 5　风险与回退

| 风险 | 对策 |
| --- | --- |
| `LangGraphChatRuntime` 委托时上下文装配与房间会话打架 | 阶段 0 必须核实 request 构造；Worker 的 session 概念与房间解耦，历史完全由 mas_context 显式构建 |
| SSE 多 worker 进程广播不一致 | MVP 接受进程内广播 + TODO；如生产部署多副本，回退方案为 Redis pubsub（**注意：这是唯一允许的 Redis 用途，与已下线的 A2A Stream 无关**） |
| Supervisor JSON 决策不稳定 | 解析失败静默兜底是硬要求；提示词中给 2-shot 示例；决策轨迹全落 trace 便于回放调优 |
| 长讨论上下文膨胀 | 2.4 裁剪规则必须实现且有单测；不通过则打回阶段 2 |
| 旧 AgentTeams/Matrix 组件并存干扰 | 本手册不改动、不删除旧组件；部门页面是完全独立新链路，旧链路下线另立任务 |

## Part 6　总验收 checklist（用户逐项打勾）

- [ ] 阶段 0 差异清单已确认
- [ ] 阶段 1：发消息、双标签实时同步、刷新持久
- [ ] 阶段 2：完整 run（trace→专员回复→done）走通，后端事件表有全链路事件
- [ ] 阶段 2：熔断强制收尾生效
- [ ] 阶段 3：计划卡片批准/驳回/修改三分支全部手测通过，重启后可恢复
- [ ] 阶段 4：审批卡片、故障兜底、并发红线回归通过
- [ ] 全程无 legacy 手写循环、无 LangChain 消息封装、无新中间件（让编码 Agent 自查 + 用户 grep 复核 `git diff` 中新增依赖）
