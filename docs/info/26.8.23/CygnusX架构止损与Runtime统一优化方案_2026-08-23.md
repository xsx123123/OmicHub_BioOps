# CygnusX 架构止损与 Runtime 统一优化方案

> **状态**：实施稿（待评审）  
> **日期**：2026-08-23  
> **范围**：针对 `ARCHITECTURE_DESIN/cygnusx_architecture.md` 架构审核中 P0/P1 级问题的优化方案，不含 MAS/Overdrive 路线选择（已确认：MAS 由 AgentTeams 协作室替代）。  
> **目标读者**：后端架构、Agent 执行、Studio、AgentTeams 相关开发。

---

## 1. 背景与范围

### 1.1 本次要解决的问题

根据 2026-08-22 架构审核，当前平台存在以下必须立即止损的架构问题：

| 优先级 | 问题 | 风险 |
|---|---|---|
| P0 | AgentTeams API 前缀文档 `/api/v1/agentteams` 与代码 `/api/v1/agent-teams` 不一致 | 前后端接口契约混乱、文档不可信 |
| P0 | `chat_service.py` 近 10,000 行，承载 Legacy/LangGraph/Studio/Overdrive/MAS/AgentTeams/Subagent 等多条路径 | 违反分层原则，改动风险极高，单测难以覆盖 |
| P1 | 各 Runtime 自行装配上下文，重复读取 Agent/模型/工具/MCP/Skill/记忆 | 装配逻辑分散，新增能力需要在多个入口重复改造 |
| P1 | 统一事件框架只有构造器，没有统一状态转移 | 各 Runtime 各自处理 `tool_result`、`done`、`handoff`、`ask_user` 等收尾 |
| P1 | AgentTeams 协作室与旧 MAS/Overdrive 的边界在产品层不清晰 | 用户/开发者无法判断“协作室 Case”与“Overdrive 计划”何时该用哪个 |

### 1.2 不在本次范围

- **MAS 产品路线**：已确认旧 MAS（`mas_enabled`）被 AgentTeams 协作室替代，不再复活。本方案只处理“如何标记废弃 MAS 残留”和“协作室与 Overdrive 的边界”，不重新设计 MAS。
- **沙箱合并**：Legacy Sandbox 与 Studio Sandbox 的合并属于独立的大变更，见同目录 `CygnusX沙箱安全加固实施手册_Codex施工版.md`。
- **前端重构**：只涉及后端接口契约和事件语义，前端按新契约适配。

---

## 2. P0：止损对齐

### 2.1 统一 API 前缀

#### 2.1.1 现状

- `ARCHITECTURE_DESIN/cygnusx_architecture.md:146` 写：`| AgentTeams | `/api/v1/agentteams` | ... |`
- 实际挂载：`src/cygnusx/api/v1/router.py:119` 为 `api_router.include_router(agentteams.router, prefix="/agent-teams", ...)`
- 部分前端/文档已使用 `/agent-teams`，部分旧文档使用 `/agentteams`。

#### 2.1.2 决策

**保留代码中的 `/api/v1/agent-teams`，统一所有文档和调用方。** 理由：

1. 代码和较新文档（如 `agentteams_room_current_architecture_2026-08-21.md`）已使用 `-` 分隔。
2. 前端 `frontend/src/api/agent.ts` 中 Agent 管理路径为 `/agents`，AgentTeams 路径目前分散在其他 API 文件中；需要统一排查。
3. 改名成本低于改代码，因为代码只有一处 `router.py:119`。

#### 2.1.3 修改清单

| 文件 | 修改内容 |
|---|---|
| `ARCHITECTURE_DESIN/cygnusx_architecture.md:146` | `/api/v1/agentteams` → `/api/v1/agent-teams` |
| `ARCHITECTURE_DESIN/agentteams.md`（如存在旧前缀） | 全部替换 |
| `docs/modules/*.md` 中涉及 AgentTeams 的接口 | 全部替换 |
| `frontend/src/api/agentteams*.ts` 或 `agent-teams*.ts` | 确认统一使用 `/agent-teams` |
| `tests/e2e/*agentteams*.py` | 确认统一使用 `/agent-teams` |
| `src/cygnusx/api/v1/agentteams.py` 内 `tags=["AgentTeams"]` | 保持不变，仅 URL 前缀统一 |

#### 2.1.4 验收

```bash
# 全仓库搜索旧前缀，应只剩历史记录/CHANGELOG
rg "api/v1/agentteams" --type md --type ts --type py
# 期望：无命中（或仅 CHANGELOG/历史文档明确标注为旧路径）

# 新前缀命中
rg "api/v1/agent-teams" --type md --type ts --type py
```

---

### 2.2 拆分 `chat_service.py`

#### 2.2.1 现状

`src/cygnusx/application/services/chat_service.py` 当前 9970 行，核心职责包括：

- 会话 CRUD
- 消息持久化
- SSE 流式聊天编排
- Legacy 手写 ReAct 循环
- LangGraph ReAct 调用
- Studio 工具循环与审批
- Overdrive 计划与执行
- MAS Plan Preview 适配
- AgentTeams 房间响应接入
- Subagent fan-out 调用
- 记忆上下文装配
- 文献检索触发
- 工具执行与结果回灌

直接违反了 `cygnusx_architecture.md:65` 的设计原则：

> API 层只负责协议、鉴权、参数校验和调用应用服务，不承载复杂编排。

#### 2.2.2 目标架构

将 `ChatService` 拆分为三层：

```text
ChatService（会话层，< 800 行）
  ├── SessionService（会话/消息 CRUD，从 ChatService 抽出）
  ├── ChatRouterService（根据 Agent/模式/请求选择 Runtime）
  │     ├── LegacyChatRuntime
  │     ├── LangGraphChatRuntime
  │     ├── StudioChatRuntime
  │     ├── OverdriveRuntime
  │     └── AgentTeamsChatRuntime（仅处理从协作室转过来的会话）
  └── ChatEventService（SSE 构造、事件顺序、历史重建）
```

#### 2.2.3 拆分原则

1. **每个 Runtime 一个文件**：Legacy、LangGraph、Studio、Overdrive、AgentTeams 各一个 `*_runtime.py`。
2. **ChatService 只负责**：
   - 接收请求参数
   - 调用 `ChatRouterService` 选择 Runtime
   - 流式透传事件
   - 最终消息落库
3. **公共逻辑下沉到**：
   - `AgentContextBuilder`：统一装配 Agent/模型/工具/MCP/Skill/记忆
   - `ToolExecutionService`：统一执行 ToolBridge/MCP/Skill
   - `ExecutionEventService`：统一事件构造与发送顺序
4. **不移动数据库模型和 schema**，只移动业务编排逻辑。

#### 2.2.4 文件拆分方案

**新增文件**

```text
src/cygnusx/application/services/
├── chat/
│   ├── __init__.py
│   ├── chat_service.py              # 精简后的入口，< 800 行
│   ├── chat_router_service.py       # Runtime 选择
│   ├── chat_event_service.py        # SSE/事件顺序/历史重建
│   ├── session_service.py           # 会话/消息 CRUD（从 chat_service.py 抽出）
│   └── runtimes/
│       ├── __init__.py
│       ├── legacy_runtime.py        # Legacy ReAct
│       ├── langgraph_runtime.py     # LangGraph ReAct（从 infrastructure/execution 迁入或委托）
│       ├── studio_runtime.py        # Studio 工具循环
│       ├── overdrive_runtime.py     # Overdrive 计划与执行（包装现有 overdrive_run_service）
│       └── agentteams_chat_runtime.py # 协作室会话处理
```

**保留/修改文件**

```text
src/cygnusx/application/services/
├── agent_service.py                  # 保持不变，但暴露统一装配接口
├── agent_memory_service.py           # 保持不变
├── tool_bridge_service.py            # 保持不变
├── studio_tools.py                   # 保持不变，被 studio_runtime.py 调用
├── parallel_subagent_service.py      # 保持不变，被 legacy/langgraph_runtime 调用
├── overdrive_run_service.py          # 保持不变，被 overdrive_runtime.py 调用
├── overdrive_runtime.py              # 可保留，但 overdrive_runtime.py（新）做高层编排
└── chat_service.py                   # 标记 deprecated，逐步迁移调用方后删除
```

#### 2.2.5 关键迁移步骤

**步骤 1：先抽出 `SessionService`（风险最低）**

把 `ChatService` 中的以下方法迁移到 `SessionService`：

- `create_session`
- `get_session`
- `list_sessions`
- `update_session`
- `delete_session`
- `get_messages`
- `create_message`
- `update_message`
- `search_sessions`

`ChatService` 通过依赖注入使用 `SessionService`。

**步骤 2：抽出 `ChatEventService`**

统一处理：

- `ChatChunk` 构造
- SSE `text/tool_call/tool_result/plan/done/error` 发送顺序
- `execution_events.py` 的生命周期事件透传
- 断流重连时的历史重建

**步骤 3：新建 `ChatRouterService`**

根据以下输入选择 Runtime：

```python
class ChatRouterService:
    async def select_runtime(self, request: ChatRequest, context: AgentContext) -> ChatRuntime:
        if context.session.mode == "studio":
            return StudioChatRuntime(...)
        if context.session.mode == "agentteams":
            return AgentTeamsChatRuntime(...)
        if context.agent.agent_id == "agent-orchestrator" and settings.orchestrator_engine == "langgraph":
            # 如果未来复活 orchestrator，走这里
            return LangGraphOrchestratorRuntime(...)
        if OverdrivePlanningService.is_overdrive_request(request, context):
            return OverdriveRuntime(...)
        if context.agent.features.engine == "langgraph":
            return LangGraphChatRuntime(...)
        return LegacyChatRuntime(...)
```

**步骤 4：逐个 Runtime 迁移**

顺序建议：

1. `LangGraphChatRuntime`：已有 `infrastructure/execution/langgraph_runtime.py`，迁移成本最低。
2. `StudioChatRuntime`：把 Studio 分支从 `chat_service.py` 抽出。
3. `LegacyChatRuntime`：最大的一块，最后迁移。
4. `OverdriveRuntime`：包装 `overdrive_run_service`。
5. `AgentTeamsChatRuntime`：仅处理从协作室转发的会话。

**步骤 5：灰度切换**

- 新增配置 `chat_runtime_refactor_enabled: bool = False`
- 关闭时走旧 `ChatService.stream_agent_chat`
- 开启时走新 `ChatService → ChatRouterService → Runtime`
- 单测通过后，逐步开启并监控

#### 2.2.6 验收标准

- `src/cygnusx/application/services/chat_service.py` 行数 < 1000 行。
- `src/cygnusx/application/services/chat/` 目录下各 Runtime 文件职责单一，可被独立单测。
- 现有 API `/api/v1/chat/stream` 行为不变。
- 旧 `chat_service.py` 在 deprecated 后保留一个转发函数，所有调用方迁移后删除。
- 新增至少覆盖 `ChatRouterService` 和 `LegacyChatRuntime` 的单元测试。

---

## 3. P1：减少 Runtime 分裂

### 3.1 统一 Agent 上下文装配层

#### 3.1.1 现状

当前 Agent 上下文由 `AgentService.assemble_context()` 提供，但：

- ChatService 额外注入记忆、实时搜索、Studio 模式、Overdrive 约束。
- AgentTeams Room Response Service 自己装配 Manager/专家上下文。
- Studio 工具自己读取 capability 和 runtime profile。
- Worker（`parallel_subagent_service.py`）自己裁剪工具白名单。

导致新增一个能力（如新的记忆注入点）需要在 4-5 个入口改造。

#### 3.1.2 目标

引入 `AgentContext` 值对象和 `AgentContextBuilder`，所有 Runtime 从同一 Builder 获取完整上下文。

```python
# src/cygnusx/domain/execution/agent_context.py
class AgentContext(BaseModel):
    session: ChatSession
    agent: AgentTemplate
    user: User
    project: Project | None
    model_config: ModelConfig
    system_prompt: str
    tools: list[ToolSchema]
    mcp_servers: list[MCPServerContext]
    skills: list[SkillContext]
    memory_context: str
    studio_meta: StudioMeta | None
    capabilities: CapabilityState | None
    execution_path: str
    guardrails: list[str]
    trace_id: str
    run_id: str
```

#### 3.1.3 AgentContextBuilder 职责

```python
# src/cygnusx/application/services/agent_context_builder.py
class AgentContextBuilder:
    async def build(
        self,
        session_id: UUID,
        agent_id: str,
        user_message: str | None = None,
        mode: str = "chat",
    ) -> AgentContext:
        ctx = AgentContext()
        ctx.session = await self.session_service.get(session_id)
        ctx.agent = await self.agent_service.get(agent_id)
        ctx.user = await self.user_service.get(ctx.session.user_id)
        ctx.project = await self.project_service.get(ctx.session.project_id)
        ctx.model_config = await self.model_service.resolve(ctx.agent.model_id)
        ctx.system_prompt = await self.prompt_service.render(ctx.agent, ctx.session, ctx.user)
        ctx.tools = await self.tool_registry.for_agent(ctx.agent, mode=mode)
        ctx.mcp_servers = await self.mcp_service.for_agent(ctx.agent, mode=mode)
        ctx.skills = await self.skill_service.for_agent(ctx.agent, mode=mode)
        ctx.memory_context = await self.memory_service.build_context(
            user_id=ctx.user.id,
            agent_id=agent_id,
            message=user_message,
            mode=mode,
        )
        ctx.studio_meta = await self.studio_service.get_meta(ctx.session) if mode == "studio" else None
        ctx.capabilities = await self.capability_service.load(ctx.agent, ctx.studio_meta)
        ctx.execution_path = self._resolve_execution_path(ctx, mode)
        ctx.guardrails = self._load_guardrails(ctx.agent, mode)
        ctx.trace_id = generate_trace_id()
        ctx.run_id = generate_run_id()
        return ctx
```

#### 3.1.4 关键规则

1. **不可信上下文统一包装**：记忆、workspace_memory、用户上传文件摘要等统一包裹在 `<untrusted_context>` 标签内，不覆盖 system prompt。
2. **工具白名单统一**：`tool_registry.for_agent()` 根据 `agent.tool_packs` + `mode` + `capability` 返回最终工具集合，各 Runtime 不再自行过滤。
3. **mode 扩展**：`chat` / `studio` / `agentteams` / `worker` / `overdrive`，Builder 根据 mode 注入不同侧载内容。
4. **实时搜索触发**：统一在 Builder 中通过 `BiomedicalLiteratureService._requires_fresh_web_search()` 判断，不在 ChatService 中硬编码。

#### 3.1.5 修改清单

| 文件 | 修改 |
|---|---|
| 新增 `src/cygnusx/domain/execution/agent_context.py` | 定义 `AgentContext` 值对象 |
| 新增 `src/cygnusx/application/services/agent_context_builder.py` | 统一装配逻辑 |
| 修改 `src/cygnusx/application/services/agent_service.py` | `assemble_context()` 改为委托 Builder，保留兼容接口 |
| 修改 `src/cygnusx/application/services/chat_service.py`（拆分后） | 直接调用 `AgentContextBuilder.build()` |
| 修改 `src/cygnusx/application/services/agentteams_room_response_service.py` | Manager/专家上下文通过 Builder 获取 |
| 修改 `src/cygnusx/application/services/parallel_subagent_service.py` | Worker 上下文通过 Builder 获取，只裁剪不能新增 |
| 修改 `src/cygnusx/application/services/studio_context_service.py` | Studio 侧载内容通过 Builder 注入 |

#### 3.1.6 验收

- 所有 Runtime 的上下文装配入口只有 `AgentContextBuilder.build()`。
- 新增一个工具/Skill/MCP 到 Agent，只需在 `tool_registry.for_agent()` 一处修改生效逻辑。
- 单测验证：同一 Agent 在不同 mode 下获得的 tools、mcp_servers、memory_context 符合预期。

---

### 3.2 统一事件状态机

#### 3.2.1 现状

`src/cygnusx/application/services/execution_events.py` 只提供事件构造器，各 Runtime 自行决定：

- 何时发 `agent_turn_started`
- 何时发 `agent_context_reinjected`
- 何时发 `agent_final_result`
- `done` 之前是否漏发生命周期事件
- `handoff`、`ask_user`、错误、超时、取消如何收尾

#### 3.2.2 目标

引入 `ChatRuntime` 抽象基类，所有 Runtime 必须实现统一状态转移：

```python
# src/cygnusx/application/services/chat/runtimes/base.py
class ChatRuntime(ABC):
    @abstractmethod
    async def run(self, ctx: AgentContext, user_message: ChatMessage) -> AsyncIterator[ChatEvent]:
        ...

    async def _emit_turn_started(self, ctx: AgentContext) -> ChatEvent:
        return execution_chunk("agent_turn_started", ...)

    async def _emit_tool_result(self, ctx: AgentContext, tool_call, result) -> ChatEvent:
        yield execution_chunk("agent_context_reinjected", ...)

    async def _emit_final(self, ctx: AgentContext, final_text: str) -> ChatEvent:
        yield execution_chunk("agent_final_result", ...)
        yield execution_chunk("done", ...)
```

#### 3.2.3 强制状态转移

所有 Runtime 必须遵守以下顺序：

```text
agent_turn_started
  → (text | reasoning | tool_call)*
  → agent_context_reinjected（每次 tool_result 回灌后）
  → agent_turn_continued（进入下一轮）
  → ...
  → agent_final_result
  → done
```

终止分支：

- `ask_user` → `agent_final_result` + `done`
- `handoff` → `agent_final_result` + `handoff` 事件 + `done`
- 错误 → `agent_turn_failed` + `done`
- 超时/取消 → `agent_loop_guard_triggered` + `agent_final_result`/`agent_turn_failed` + `done`

#### 3.2.4 修改清单

| 文件 | 修改 |
|---|---|
| 新增 `src/cygnusx/application/services/chat/runtimes/base.py` | `ChatRuntime` 抽象基类 |
| 修改 `src/cygnusx/application/services/execution_events.py` | 增加 `validate_event_sequence()` 和 `must_precede_done()` |
| 修改各 `*_runtime.py` | 继承 `ChatRuntime`，统一使用基类事件方法 |
| 新增 `tests/unit/chat/test_event_sequence.py` | 验证事件顺序约束 |

#### 3.2.5 验收

- 任意 Runtime 的 SSE 输出都能被 `validate_event_sequence()` 校验通过。
- `done` 之前必须有 `agent_final_result` 或 `agent_turn_failed`。
- 断流重连后，历史消息 + 事件能完整重建 UI 状态。

---

### 3.3 明确 AgentTeams 与 Overdrive 的边界

#### 3.3.1 现状

- **旧 MAS**（`mas_enabled`）已确认被 AgentTeams 协作室替代，但代码和文档中仍有残留：
  - `src/cygnusx/core/config.py:123-132` 保留 `mas_*` 配置。
  - `src/cygnusx/api/v1/mas.py` 仍暴露 MAS API。
  - `src/cygnusx/application/services/mas_service.py` 仍存在。
  - `plan_ai.md` 仍作为架构愿景文档存在。
- **Overdrive** 是当前活跃的多步骤任务编排实现，`chat_service.py` 中有大量调用。
- **AgentTeams 协作室** 也支持 Case/Work item/审批/派单，部分语义与 MAS 重叠。

#### 3.3.2 决策：三层执行模型

统一使用以下三层模型，所有产品入口必须归属其中一层：

| 层级 | 名称 | 触发方式 | 典型场景 | 当前实现 |
|---|---|---|---|---|
| L1 | 单 Agent 对话 | 普通 Chat / Studio | 问答、单步工具、代码探查 | Legacy/LangGraph/Studio Runtime |
| L2 | 协作室 Case | 用户进入 AgentTeams 房间 | 多人-多 Agent 协作、复杂分析项目、需要 Manager 汇总 | AgentTeams Room/Case/Worker |
| L3 | 确定性流程 | 传统流程表单 / 任务中心 | 标准化 RNA-seq / ATAC-seq 流程 | Celery + Snakemake / pipelines |

**Overdrive 定位为 L1 的增强**：在单 Agent 对话内，当请求可被拆为多个独立子任务且无需跨用户协作时，由 Overdrive 生成任务清单并在同一会话内串/并行执行。**Overdrive 不替代 L2 协作室，也不替代 L3 确定性流程。**

#### 3.3.3 旧 MAS 残留清理

| 动作 | 文件/配置 | 说明 |
|---|---|---|
| 标记 deprecated | `mas_enabled` 等 `config.py:123-132` | 保留字段但加注释说明由 AgentTeams 替代 |
| 隐藏 API | `src/cygnusx/api/v1/router.py:123` | `mas.router` 仍挂载，但文档中不再作为用户入口；建议加 admin-only 或完全移除 |
| 文档归档 | `ARCHITECTURE_DESIN/plan_ai.md` | 移动到 `ARCHITECTURE_DESIN/archive/` 或顶部加醒目状态“已归档，由 AgentTeams 替代” |
| 代码保留策略 | `src/cygnusx/application/services/mas_service.py` | 若 Overdrive 已覆盖其能力，进入 deprecation 倒计时；若仍有独立 API 被调用，先加 `@deprecated` |
| 数据库表 | `mas_runs`, `mas_nodes`, `mas_artifacts` 等 | 评估是否有生产数据；无数据则准备 drop 迁移，有数据则冻结只读 |

#### 3.3.4 AgentTeams vs Overdrive 边界定义

| 维度 | AgentTeams 协作室（L2） | Overdrive（L1 增强） |
|---|---|---|
| 入口 | AgentTeams 房间 | 普通 Chat / Studio |
| 协作方 | 用户 + Manager + 多领域 Agent + Worker | 用户 + 当前 Agent |
| 持久化 | Room / Case / Work item / Evidence | Session / Task manifest |
| 审批 | Case 级人工审批 | 会话内即时确认 |
| 适用任务 | 跨领域、长周期、需要多方会诊 | 单领域内多步骤、可一次性确认 |
| 状态可见性 | 房间时间线 + 任务监控 | 聊天流 + 任务进度卡 |
| 产物归属 | Case / Project | Session / User |

#### 3.3.5 防止越位的规则

1. **Overdrive 不创建 AgentTeams Case**：Overdrive 的 `parallel_subagents` 派生的是 Worker，不是协作室成员。
2. **AgentTeams 不直接走 Overdrive**：协作室内的多步骤任务由 Case/Work item 调度，不混用 Overdrive manifest。
3. **L3 流程不进入 Chat/Case**：RNAFlow/ATACFlow 通过传统任务中心提交，Agent 只提供查询/配置辅助入口。

#### 3.3.6 验收

- `plan_ai.md` 已归档或加状态说明。
- `config.py` 中 `mas_enabled` 注释明确说明“由 AgentTeams 替代，保留仅作回滚”。
- 新增文档 `ARCHITECTURE_DESIN/execution_layers.md` 明确 L1/L2/L3 边界。
- 单测/集成测试验证：Overdrive 派生的 Worker 不会创建 Case；AgentTeams Case 不会调用 Overdrive manifest。

---

## 4. P2：文档与实现同频

### 4.1 更新 `cygnusx_architecture.md`

在文档顶部增加“实现状态对照表”，例如：

```markdown
## 架构实现状态

| 能力 | 状态 | 说明 |
|---|---|---|
| 普通 Chat/Agent | 已启用 | Legacy + LangGraph |
| OmicStudio | 已启用 | 每会话独立容器 |
| AgentTeams 协作室 | 已启用（默认入口关闭） | `agentteams_chat_entry_enabled=False` |
| Subagent Fan-out | 灰度关闭 | `subagent_fanout_enabled=False` |
| 旧 MAS | 已弃用 | 由 AgentTeams 替代 |
| Overdrive | 已启用 | 单会话多步骤任务 |
| Memory v2 | 灰度关闭 | `memory_v2_enabled=False` |
```

### 4.2 模块分层修正

- 将 `knowledge`、`worker` 从架构图中“平台内部模块”改为“跨进程服务/能力集合”。
- 若后续需要独立包，再按包结构重构；当前不要误导为已有独立模块。

---

## 5. 实施路线图

### Phase 1：P0 止损（1 周）

1. 统一 API 前缀 `/api/v1/agent-teams`。
2. 归档 `plan_ai.md`，清理 `config.py` 中 MAS 注释。
3. 创建 `AgentContext` 和 `AgentContextBuilder` 骨架，先让 ChatService 和 AgentTeams 共用。

### Phase 2：ChatService 拆分（2-3 周）

1. 抽出 `SessionService` 和 `ChatEventService`。
2. 新建 `ChatRouterService` 和 Runtime 目录。
3. 逐个 Runtime 迁移，保持 `chat_runtime_refactor_enabled` 开关。
4. 单测覆盖率达到拆分前水平。

### Phase 3：事件状态机统一（1 周）

1. 所有 Runtime 继承 `ChatRuntime`。
2. 增加事件顺序校验。
3. 断流重连测试。

### Phase 4：边界文档化（0.5 周）

1. 编写 `ARCHITECTURE_DESIN/execution_layers.md`。
2. 更新 `cygnusx_architecture.md` 实现状态表。
3. 全仓库搜索旧 `agentteams` 前缀，确保无遗漏。

---

## 6. 风险与回滚

| 风险 | 缓解 |
|---|---|
| ChatService 拆分引入回归 | 保持 `chat_runtime_refactor_enabled` 开关，旧路径保留；灰度放量 |
| AgentContextBuilder 性能下降 | Builder 内部加缓存（Agent/工具白名单可缓存），避免每次请求重复装配 |
| 事件顺序变更导致前端异常 | 新增事件校验在测试环境跑满一周，前端按新契约适配 |
| MAS API 仍有隐藏调用 | 灰度期间加 access log 审计，确认无真实用户后再完全下线 |

---

## 7. 验收总清单

- [ ] 全仓库无 `/api/v1/agentteams` 残留（历史文档除外）。
- [ ] `chat_service.py` 行数 < 1000 行，且新 `chat/` 目录结构清晰。
- [ ] 所有 Runtime 通过 `AgentContextBuilder` 获取上下文。
- [ ] 所有 Runtime 继承 `ChatRuntime`，事件顺序通过校验。
- [ ] `plan_ai.md` 已归档或加状态说明；`config.py` MAS 配置已标记 deprecated。
- [ ] `cygnusx_architecture.md` 已更新实现状态表和模块分层。
- [ ] 新增/修改单元测试通过：`pytest tests/unit/chat tests/unit/agent_context tests/unit/execution_events -q`。
