# CygnusX 单 Agent 技术架构备忘录

> **基线日期**：2026-09-20（as-built）
> **文档定位**：回答「一个 Agent 在 CygnusX 里到底是怎么定义、怎么被调用、怎么维持状态、怎么调工具、怎么跑起来、依赖什么、以及怎么和别的 Agent 协作」这七个问题。本文是**实现细节层**的事实快照；执行拓扑、执行路径登记与事件框架以 `agent_execution_framework.md` 为准，工具契约与发布验收以 `agent_framework_baseline.md` 为准。
> **与其他文档的边界**：`agent_execution_framework.md` 描述「一次执行怎么流转、怎么观测」；本文描述「Agent 这个对象本身由什么构成、接口长什么样、依赖什么」。两者互补，不合并。

## 0. 一页结论

CygnusX 的 Agent 是**数据驱动 + 薄自研运行时**的形态，不是基类继承体系，也不是外部 Agent 框架的封装：

1. Agent = 一行 YAML + 一行数据库记录（「系统设定 + 绑定模型 + 绑定 MCP 工具 + 绑定技能」的打包）。
2. 调用入口是 **FastAPI SSE 流式接口**，出入参都是 **OpenAI 消息 dict 列表 → `AsyncIterator[ChatChunk>`**。
3. 对话历史由**外部调用方显式传入**，后端 per-request 无会话状态机；持久化靠 PostgreSQL，checkpoint 只有编排图用。
4. 工具调用遵循 **OpenAI Function Calling 规范**，经 tool_packs 白名单在请求级裁剪，可落到 Docker 沙箱 / Studio 容器 / Celery。
5. 全异步 + 全流式；单 Agent 内 tool_calls 串行，跨 Agent 用 `asyncio.gather` + Semaphore 并发。
6. 依赖上是 **LangGraph 只做状态图载体 + 自研 httpx Provider**，无 Anthropic SDK、无 LlamaIndex、无 mem0。
7. 四种多 Agent 协同模式（Supervisor / Handoff / Map-Reduce / Group Chat）**全部已落地**。

---

## 1. Agent 核心封装形式与调用接口

### 1.1 Agent 是「数据」而非「类」

Agent **不通过继承基类定义**，而是三层数据载体：

| 层 | 载体 | 位置 |
| --- | --- | --- |
| 声明源 | `data/ai/*.yaml`，共 **20 个** Agent 定义 | `src/cygnusx/infrastructure/config/agent_loader.py:29` `load_agent_configs()` |
| 持久化 | ORM `AgentTemplateModel`，表 `agent_templates` | `src/cygnusx/infrastructure/database/models/agent.py:18` |
| 用户覆盖 | `UserAgentCapabilityModel`，表 `user_agent_capabilities` | 同文件 `:103` |

启动时 `AgentService.ensure_builtin_agents()`（`application/services/agent_service.py:225`）把 YAML 幂等落库；内置 Agent 的 YAML 是平台能力声明的来源，同步 `features` 但**不覆盖管理员调整过的模型、提示词或绑定关系**。

`AgentTemplateModel` 字段清单（即一个 Agent 的全部定义面）：

```python
agent_id: str (unique, index)      project_id: str | None
name / description / avatar / color / category
model_id: UUID | None  → ai_provider_configs.id   # 绑定的真实模型
model_name: str        # YAML 中写的模型名（按 name 匹配，便于调试）
model_engine: str      # 展示用引擎 label，从关联 provider config 动态解析
system_prompt: str  welcome_message: str
mcp_ids: list[str]   (JSON)   # 绑定的 MCP server
skill_ids: list[str] (JSON)   # 绑定的技能
features: dict       (JSONB)  # 功能开关：engine / studio / tool_packs / persona / agentteams / subagents_spawnable …
temperature: float   max_tokens: int（默认 65536）
is_builtin / is_active / is_default  created_by: str | None
```

> ⚠️ `agent.py:84` 与 `:87` 对 `features` 有**两行重复的 `mapped_column` 声明**（前者类型标注 `dict[str, bool]`，后者 `dict[str, Any]`）。后者覆盖前者，实际生效的是 `dict[str, Any]`。改动该字段时按 `Any` 处理。

### 1.2 执行时封装：两个 `AgentContext`

同名但职责不同的两个对象，是最容易踩坑的一处：

**① 装配结果**（`application/services/agent_service.py:201`，`@dataclass`，非 frozen）

```python
@dataclass
class AgentContext:
    """调度中枢组装出的一次请求上下文"""
    agent: AgentTemplateModel
    model_config: AIProviderConfigModel | None
    system_prompt: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[MCPServer] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    user_capabilities_customized: bool = False
    temperature: float = 0.7
    max_tokens: int = 65536
```

由 `AgentService.assemble_context(agent_id, user_id, tool_query, model_id)` 产出（`:802`）。模型缺失时不返回 None，而是返回 `model_config=None` 的上下文，由调用方转成 `ChatChunk.error`。

**② 单轮执行上下文**（`domain/execution/agent_context.py:9`，`@dataclass(frozen=True)`）

```python
session / assembled / mode / execution_path / trace_id / run_id
```

由 `AgentContextBuilder.build_for_session()` 产出，带类级缓存（`_cache: dict[tuple[str,str,str,str], _CachedAssembly]`，TTL = `agent_context_cache_ttl_seconds`，默认 60s），缓存命中时 `_clone_assembly` 深拷贝防串改。

### 1.3 主调用入口

```
POST /api/v1/chat/stream
  → chat_stream()                          src/cygnusx/api/v1/chat.py:595
  → ChatService.stream_agent_chat()
  → ChatService._stream_agent_chat_inner()  src/cygnusx/application/services/chat_service.py:2569
```

**入参**（`ChatRuntimeRequest`，`application/services/chat/runtimes/base.py:15`，`@dataclass(frozen=True)`）：

```python
user_id: str
agent_id: str
messages: list[dict[str, str]]     # ← OpenAI 消息 dict：[{role, content, metadata}]
session_id: str | None
model_id: UUID | None              # 显式模型覆写，优先于 Agent 绑定与用户能力档
attachments: list[dict] | None
enable_web_search / enable_code_execution / deep_thinking: bool
mode: str | None                   # "chat" | "studio"
runtime_profile / mcp_mode / extra_mcp_servers
multi_agent / overdrive: bool | None
extend_max_rounds: bool            # 轮次上限 100 → 1000
project_id: str | None
runtime_context: dict[str, Any]    # 页面上下文等，经系统提示词统一注入
auto_approve: bool | None          # AI 助手页跳审批闸；AI 工作台页不传
```

**入参不是 Pydantic 结构体，也不是 LangChain `BaseMessage`**，就是裸 dict 列表。

**出参**：`AsyncIterator[ChatChunk]` —— 异步生成器，逐块流式产出。

```python
@dataclass
class ChatChunk:                    # infrastructure/ai_provider/openai_compatible.py:191
    """流式输出数据块 — SSE 事件的统一抽象"""
    type: str     # text | tool_calls | tool_call | tool_output | tool_result | plan
                  # ask_request | approval_request | approval_resolved | error | done
                  # heartbeat | <各 lifecycle event_type>
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

SSE 序列化：`data: {"type": ..., "content": ..., **metadata}\n\n`；终止事件为 `done` / `error` / `agent_turn_failed`。

### 1.4 运行循环结构

**经典 ReAct，两种实现并存**：

- **Legacy 手写循环**（`chat_service.py:4163`）：`for _round in range(max_rounds):` → 流式收集 tool_calls → `for tc in round_tool_calls:` 串行执行 → append `role:tool` 消息 → 下一轮。
- **LangGraph 状态图**（`infrastructure/execution/langgraph_runtime.py:54-81`）：

```text
__start__ → llm_call ──[有 tool_calls]──→ tool_exec ──→ llm_call（回灌）
                 └──[无 tool_calls / 出错]──→ __end__
```

**轮次上限**：`LangGraphRuntimeService.__init__(deps, max_rounds=8)`，但上层 `_stream_agent_chat_langgraph` 用 `extend_max_rounds` 控制实际生效值 100 / 1000（透传到 `NodeDeps.max_tool_rounds`）。图另有 `recursion_limit = 2 * max_rounds + 2`。触顶时 `llm_call_node` 的 `force_final_response` 分支会**清空 tools 并注入强制收尾提示词**（`langgraph_nodes.py:100-113`）。

**每轮动作三选一**（外循环动作路由）：有序 JSON tool 批次 / 显式 Finalize（`submit_output` 工具）/ Code Cell（全代码执行工具轮不占轮次预算，靠 `code_cell_only_round` 标记，`agent_state.py:36`）。

### 1.5 双执行路径与选择逻辑

`chat_service.py:4086-4088`：

```python
if (not studio_mode
    and not is_mas_orchestrator
    and ctx.features.get("engine") != "legacy"
    and not get_settings().chat_force_legacy_runtime):
    → LangGraphChatRuntime        # 普通聊天默认全量
```

即：**普通聊天 → LangGraph 单 Runtime**；Studio / MAS Orchestrator / Agent 显式 `engine:"legacy"` / 全局逃生舱 `chat_force_legacy_runtime` → 手写循环。

Runtime 抽象层（`chat/runtimes/base.py:40`）：

```python
class ChatRuntime(ABC):
    @abstractmethod
    async def run(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]: ...
```

五个实现：`LangGraphChatRuntime` / `LegacyChatRuntime` / `StudioChatRuntime` / `OverdriveChatRuntime` / `DirectChatRuntime`。其中四个继承 `DelegatingAgentRuntime`（把标准请求无损转交给既有 `_stream_agent_chat_inner` 生成器），只有 `DirectChatRuntime` 是无 Agent 的裸模型直连。

**演进口径（2026-09-19 起正式）**：禁止新增 legacy-only 循环行为，新能力一律进 LangGraph 图。

---

## 2. 状态与记忆（State & Memory）

### 2.1 LangGraph State 定义

`AgentState(TypedDict, total=False)`（`domain/execution/agent_state.py:24`）：

```python
class AgentState(TypedDict, total=False):
    """LangGraph Agent 状态（OpenAI 消息格式，不引入 langchain 消息封装）"""
    messages: Annotated[list[dict[str, Any]], operator.add]
    rounds: int
    usage: dict[str, Any] | None
    error: str | None
    handoff: dict[str, Any] | None        # 交接指令，tool_exec 后立即结束当前图
    ask_request: dict[str, Any] | None    # ask_user 澄清请求
    finalize: dict[str, Any] | None       # submit_output 显式 Finalize
    code_cell_only_round: bool            # 全代码执行轮 → 下一轮不递增轮次预算
```

**关键取舍**：刻意**不引入 LangChain 消息封装**——`messages` 是裸 OpenAI dict，reducer 用标准库 `operator.add` 而非 `langgraph.graph.message.add_messages`。节点只返回增量，由 reducer 累加。

### 2.2 对话历史：外部显式传入，后端无会话状态机

这是本框架最重要的架构特征之一 —— **后端 per-request 无状态**：

- 前端 `frontend/src/stores/agentHub.ts:2123`：
  ```typescript
  const apiMessages = session.messages
    .filter((m) => m.id !== aiId && m.role !== 'assistant' || (m.role === 'assistant' && m.content.length > 0))
    .slice(-ctxLen)                                    // ← 前端自行截断上下文窗口
    .map((m) => ({ role: m.role, content: m.content, metadata: m.metadata }))
  ```
- 后端 `prepare_agent_request()`（`chat/request_preparation.py:32`）只负责装配 Agent/模型，**不重建历史**；历史从 DB 读出靠前端单独调 `GET /sessions/{id}/messages`（`chat/session_service.py:167` `get_messages`），再随请求回传。

**上下文裁剪三层**：

| 层 | 机制 |
|---|---|
| 前端 | `.slice(-ctxLen)` 窗口截断 |
| 后端历史压缩 | `compact_tool_history(messages, 4000)`（`studio_micro_compaction.py`）—— 历史 assistant 消息的 `metadata.tool_invocations` 超阈值时只保留首尾各 50 行，附「完整内容见工作区文件 {path}」；**不触碰 user 消息与最后一条消息** |
| 工具回灌截断 | 普通工具 4000 字符（`TOOL_RESULT_MAX_CHARS`）；Skill 正文 24000 字符（`SKILL_TOOL_MAX_CHARS`），见 `langgraph_nodes.py:35-37` |

### 2.3 持久化存储全景

| 存储 | 内容 | 位置 |
| --- | --- | --- |
| **PostgreSQL** | `chat_sessions` / `chat_messages`；正文流式增量 `update_message_content(id, content, "streaming")`；工具调用/结果/timeline/usage 写 message metadata | `chat_service.py` |
| **PostgreSQL**（长期记忆） | `agent_memories` / `memory_blocks` / `memory_facts` / `memory_settlements`；pgvector embedding 1024 维 | `infrastructure/database/models/agent_memory.py` |
| **PostgreSQL**（MAS） | `overdrive_runs` / `overdrive_events`（**权威状态账本**）/ `mas_nodes` / `a2a_events` / `agentteams_*` | `infrastructure/database/models/` |
| **Redis** | 审批 pending 记录（TTL 300s）；Studio 容器 `last_activity` ZSET + 执行租约；MAS A2A 事件 Stream | `infrastructure/mas/redis_streams.py` |
| **LangGraph checkpoint** | **仅 Orchestrator 编排图**用 `AsyncPostgresSaver`（`infrastructure/execution/checkpointer.py:41`）；**单 Agent ReAct 图不用 checkpointer**（按请求构造临时图，无 thread_id） | — |

### 2.4 长期记忆：自研 Postgres FactStore

**⚠️ 文档/配置漂移提醒**：`.env.example:346` 仍写 `MEM0_ENGINE_ENABLED=true`，但代码库中**已不存在 mem0 引擎实现**（`infrastructure/memory/` 仅 `fact_store.py`）。当前实际链路是自研的：

- `PostgresFactStore` + `FactStore` Protocol（`infrastructure/memory/fact_store.py`）—— 应用层依赖抽象，可换持久化后端
- `AgentMemoryService`（`application/services/agent_memory_service.py:40`）提供 `save / search / update / forget`
- 约束：`MEMORY_SCOPES = {profile, project, preference, summary}`、每用户上限 500 条、单条 200 字符、最多 8 关键词、敏感信息正则过滤（api_key / token / password / sk- / AKIA…）
- embedding 走 `fastembed`（`intfloat/multilingual-e5-large`，1024 维）
- 异步维护：Celery `settle_session_memory`（`infrastructure/celery_app/tasks/memory.py`），游标增量 + 区间幂等；AgentTeams 合成会话显式排除

### 2.5 Studio 侧的文件型记忆

与数据库记忆并行的另一套：`MEMORY.md` 索引 + `.memory/*.md` 文件 + Git 检查点，落在工作区（见 `cygnusx_sandbox_architecture_2026-08-22.md`）。

---

## 3. 工具调用（Tool Calling）与执行环境

### 3.1 注册：严格遵循 OpenAI Function Calling 规范

```python
{
  "type": "function",
  "function": {
      "name": "chat_sandbox_execute",
      "description": "在轻量级沙盒中执行代码（python/r/bash）…",
      "parameters": {                              # ← 标准 JSON Schema
          "type": "object",
          "properties": {"language": {"type": "string", "enum": ["python","r","bash"]},
                         "code": {"type": "string", ...}}
      }
  }
}
```

示例见 `application/services/chat_sandbox_tools.py:33`。

**四类来源，在 `AgentService.assemble_context` 中合并成请求级 tools 列表**：

| 来源 | 机制 | 位置 |
| --- | --- | --- |
| MCP server 工具 | `server.tools` → OpenAI tools 格式 | `agent_service.py:888` |
| builtin schema 常量 | `CHAT_SANDBOX_EXECUTE_TOOL_SCHEMA` / `NETWORK_REQUEST_TOOL_SCHEMA` / `ASK_USER_TOOL_SCHEMA` / `SUBMIT_OUTPUT_TOOL_SCHEMA` / `MAS_PLAN_PREVIEW_TOOL_SCHEMA` / `CAPABILITY_TOOL_SCHEMAS` / `GOAL_TERMINAL_TOOL_SCHEMAS` / `STUDIO_TOOL_SCHEMAS` | 各服务模块 |
| Skill 渐进披露 | `use_skill` / `skill_resource` 三层披露（`SKILL_TOOL_NAMES`） | `domain/skill/services.py` |
| 外部 MCP | `mcp-server/` 独立部署，FastMCP，9 组 40 工具，X-API-Key 调平台 REST | `mcp-server/main.py` |

**请求级裁剪**（模型看到的不是全局全集）：

`features.tool_packs` → `AgentService._tool_pack_config(features)`（`agent_service.py:1222`）汇总 `builtin_tools` 与 `mcp_tools{server_id: [tool_name]}` 白名单 → 按 server 逐个过滤（`:879-887`，历史 ID 漂移时按确定性预设名再匹配一次）→ 再叠加 Studio 模式、权限模式、`safe_only`、用户能力覆盖。

> `tool_packs` 是 YAML 里声明的**工具白名单包**，不是工具实现。它是 agent 能力边界的主要配置手段。

### 3.2 分发执行

**LangGraph 路径**（注入式，便于测试 mock）：

```python
ToolExecutorFn = Callable[[str, dict[str, Any], str], Awaitable[dict[str, Any]]]
#                       tool_name, args,            tool_call_id
```

`NodeDeps.tool_executor` 由 `LangGraphChatRuntime._stream_agent_chat_langgraph`（`chat/runtimes/langgraph_runtime.py:242`）构造，内部 if/elif 路由链覆盖：skill 内部工具 → ask_user → knowledge_search → MCP 匹配 → web_search → chat_sandbox_execute（审批闸）→ network_request → handoff → parallel_subagents → create_agentteams_case → mas_plan_preview → goal 终态 → 未挂载报错信封。

**MCP 匹配**：

```python
next((s for s in active_mcp_servers if any(t.tool_name == tool_name for t in s.tools)), None)
→ MCPClient.call_tool(server, tool_name, arguments, user_id, context)
```

**Legacy 路径**：`chat_service.py` 内联长 if/elif 链（约 4299–5120 行区间），按 `is_studio_tool` / `is_skill_tool` / `is_handoff_tool` / `is_subagent_tool` / `is_agentteams_case_tool` / `is_chat_sandbox_tool` 分类分派。

**MCP 传输三态**（`infrastructure/mcp/client.py:221`）：

| transport | 机制 |
|---|---|
| `builtin` | 进程内 preset handler 直调，零网络开销（平台内置 AI 走这条） |
| `stdio` | Python MCP SDK 子进程；有 `_DENIED_STDIO_COMMANDS` 黑名单（禁 `sh`/`bash`/`zsh`/`dash`/`cmd`/`powershell` 等） |
| `sse` | 远程 MCP |

统一带 **circuit breaker + retry**（`infrastructure/mcp/reliability.py`），`list_tools` 与 `call_tool` 的错误处理策略不同：发现阶段让错误上抛（避免误报 online + 0 工具），调用阶段错误隔离。

内置 preset 用**确定性 UUID5 ID**（`CYGNUSX_TOOLS_SERVER_ID` / `CYGNUSX_PLATFORM_SERVER_ID` / `CYGNUSX_PIPELINES_SERVER_ID` / `SEQOUT_SERVER_ID` / `CONDA_META_MCP_SERVER_ID`），保证跨重启稳定。

**结果双通道**（`langgraph_nodes.py:233-244`）：

```python
llm_payload  # 回灌模型，受长度上限保护，避免上下文无限膨胀
ui_payload   # 前端卡片/图表/产物/终端输出，可保留结构化展示字段
```

新增工具必须明确两路结果是否存在，并保证模型回灌内容不直接携带超大原始文件、二进制内容或未脱敏错误堆栈。

### 3.3 执行环境

**① 轻量 Docker 沙箱**（普通聊天代码执行）—— `infrastructure/sandbox/pool.py`（697 行）

- warm pool 常驻容器（`sleep` 保活）+ 会话亲和（会话绑定 `container_id`，复用至超时回收）
- **Docker SDK `exec`** 在容器内跑 base64 包裹的代码（web 容器内**无 docker CLI**，只有 `/var/run/docker.sock`，不能走 `docker exec` 子进程）
- stdout/stderr 流式回传；图表协议：脚本输出 `%%ECHARTS%%<json>` / `%%IMAGE%%<base64>` / `%%PLOTLY%%` 标记行，由池解析为结构化输出
- Docker 不可用时优雅降级（`is_available()` → False → 友好错误）

**② Studio 沙箱**（工作台重负载）—— `infrastructure/studio/manager.py`

- 一会话一容器，容器名 `studio-{session_id[:8]}`；非 UUID 会话 ID（如 `agentteams:{case_id}`）用哈希后缀避免前缀碰撞共享容器
- bind-mount `{workspace_root}/{session_id}` → `/workspace`，预建 `input/output/ref/.logs`
- **sandbox-agent HTTP over 共享工作区 Unix Socket**（不发布端口、不 docker exec）
- 平台数据只读挂 `/data/platform`（数据不搬家）；**按用户目录挂载是多租户隔离红线**——整根挂载会让沙盒内代码可读全部用户数据
- Redis ZSET 记录 `last_activity`，Celery beat 每 5 分钟回收超 TTL 容器；每次执行/文件请求持独立 Redis 租约
- 网络：`none` 模式用 Docker `network_mode=none`；`whitelist` 模式走受控代理出站

**③ 本地 Shell**：无直接本地 shell 工具；stdio MCP 有解释器黑名单兜底。

**④ 分析流水线**：`pipelines/RNAFlow` + `pipelines/ATACFlow`（Snakemake ≥ 9），经 Celery 任务触发。

**⑤ MAS 执行准入策略**（`domain/mas/tool_policy.py`）：

```python
class ExecutionPolicy(BaseModel):     # frozen + extra="forbid" —— 服务端强制，绝不由 LLM 运行时提供
    tool_key: str
    allowed_images: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]   # validator 强制必须在 /workspace 下
    network_enabled: bool = False
    allow_privileged: bool = False
    docker_socket_allowed: bool = False
    apptainer_compute_only: bool = False
```

`preflight_execution(policy, request)` 在不起容器、不跑进程的前提下做准入判定；YAML 配置在 `data/ai/mas/tool_policies.yaml`。

### 3.4 人工审批机制

`StudioApprovalService` + `_gate_chat_sandbox_approval`（`chat/runtimes/langgraph_runtime.py:57`）：

1. `needs_approval(permission_mode, tool_name, always_allow)` 判定（`supervised` 模式 ∧ 命中拦截名单 ∧ 未 always_allow）
2. `StudioApprovalService.create` 写 Redis pending 记录（`APPROVAL_TTL_SECONDS=300`）
3. 下发 `approval_request` chunk（含 `timeout_seconds`）；等待期每 15s 发 heartbeat 保活
4. 决议经 BLPOP 返回 → 下发 `approval_resolved`；`edited` 携 `modified_args` 替换参数后按 approved 处理；`approved + always` 写入流内 `always_allow`
5. 拒绝/超时 → `record_approval_audit` 落 `audit_logs`（`method="EVENT"`）→ 返回 `{success: False, rejected: True}` 信封回灌 LLM 与前端

`auto_approve=True`（AI 助手页面）时两个审批闸（`chat_sandbox_execute` / `network_request`）整体跳过；**AI 工作台页不传该标记，完全维持会话权限模式判定**，因此该开关只影响助手页，不外溢到工作台的逐次审批语义。

---

## 4. 运行模式与并发支持

### 4.1 全异步

- 核心执行代码**全部 `async def` + `asyncio`**。`provider_manager.chat_stream(...)` 由 `async for` 消费，本身是 async generator。
- LangGraph 图在**独立 asyncio Task** 中执行（`langgraph_runtime.py:146` `asyncio.create_task(_run())`），主协程从 `asyncio.Queue` 取 chunk；`finally` 中未完成则 `task.cancel()`。
- 节点内 `emit` 实时入队，保证 text chunk 的打字机实时性（不等到图结束）。
- 少量文件系统操作用 `# noqa: ASYNC240` 显式标注（如子任务 `workdir.mkdir`）。
- OTel context 跨 asyncio task 边界会丢失，`langgraph_runtime.py:104-119` 用 `agent_parent_context_var` 显式 attach 父 context 兜底。

### 4.2 流式输出（三层）

| 层 | 机制 |
|---|---|
| API 层 | `StreamingResponse(media_type="text/event-stream")`，`Cache-Control: no-cache` / `X-Accel-Buffering: no`，`_with_sse_heartbeat` 保活（`: heartbeat\n\n`） |
| LLM 层 | `OpenAICompatibleProvider.chat_stream` 用 httpx 逐 chunk 解析 OpenAI SSE；tool_calls 分片累加，流结束统一 yield 一个 `type="tool_calls"` chunk |
| 落库层 | 每 5 个 text chunk 调一次 `update_message_content(id, full_content, "streaming")` |

**单次 Agent 运行是流式返回**，不是阻断式等完整结果。

### 4.3 并发支持

- **单 Agent 内 tool_calls 串行**：`for tc in round_tool_calls:` 逐个 await（`langgraph_nodes.py:182` / `chat_service.py:4295`）。
- **跨 Agent 并发（Map-Reduce）**：`ParallelSubAgentService`

```python
semaphore = asyncio.Semaphore(max(1, settings.subagent_max_concurrent))   # 默认 3
gathered = await asyncio.gather(*(self._run_child(...) for ...), return_exceptions=True)
```

  单任务用 `asyncio.timeout()` 包裹；`return_exceptions=True` 保证失败隔离；每个子循环**独占独立 AsyncSession**（并发共享父 session 必崩，约束 C1）。
- **MAS 调度**：`MASSchedulerService.eligible_nodes()` 依赖感知（PENDING 且所有 `depends_on` 已 SUCCEEDED），`transition_node(expected_version=...)` 乐观锁防并发重复派发。
- **限流参数**（`core/config.py:190-191`）：`subagent_max_parallel=4`、`subagent_max_concurrent=3`（给主链路 LLM 调用留余量）。
- **长任务卸载**：Celery worker 承载流水线、记忆维护、容器回收、MAS 派发。
- **无全局请求级信号量**；并发治理靠 `max_rounds` / `subagent_max_parallel` / `subagent_max_concurrent` / 子任务 timeout 四个参数。

---

## 5. 现有依赖生态

### 5.1 结论：薄自研 + LangGraph 只做状态图载体

ReAct 循环、Provider 抽象、工具分发、SSE 协议、统一事件框架、AgentTeams 编排**全部自研**；LangGraph 只提供 `StateGraph` / 条件边 / `interrupt` 骨架。

### 5.2 关键锁定版本（`.venv` 实测，与 `uv.lock` 一致）

| 包 | 版本 | 实际用途 |
| --- | --- | --- |
| `langgraph` | **1.2.10** | 单 Agent ReAct 图 + Orchestrator 编排图 |
| `langchain-core` | 1.5.3 | 间接依赖，代码**未直接 import** |
| `langgraph-checkpoint-postgres` | 2.0.0 + `psycopg` 3.3.4 | Orchestrator 图 checkpoint（单 Agent 图不用） |
| `mcp` | **2.0.0** | Python MCP SDK（stdio / sse transport） |
| `litellm` | 1.95.0 | **仅旁路**：embedding / 知识库索引 / welcome（`litellm_provider.py`） |
| `openai` | 2.53.0 | 间接依赖，主 Provider 是自研 httpx |
| `fastapi` / `uvicorn` | 0.141.1 | Web + SSE |
| `sqlalchemy[asyncio]` / `asyncpg` | 2.x | ORM 全异步 |
| `redis[hiredis]` | 5.3.1 | 审批 / 租约 / MAS Stream |
| `celery[redis]` | 5.6.3 | 任务队列 |
| `docker` | 7.2.0 | 沙箱容器池 |
| `httpx` | 0.28.1 | **LLM 主通道** |
| `fastembed` | 0.8.0 | 记忆 embedding |
| `ollama` | — | 可选本地 embedding（`MEM0_OLLAMA_BASE_URL` 附近配置） |

**明确不存在**：`anthropic` SDK、`llama-index`、`mem0ai`、LangChain 链式抽象（LCEL / `AgentExecutor`）。

### 5.3 Provider 抽象设计

`infrastructure/ai_provider/openai_compatible.py:1-6` docstring 说明了核心取舍：

> 使用 httpx 直接对接 OpenAI /chat/completions SSE 流式接口，**替代 litellm 依赖，降低运维复杂度（1 人维护原则）**。
> 支持绝大多数国产模型（DeepSeek / Kimi / Qwen / 智谱等），所有接口遵循 OpenAI Chat Completions API 规范。

- **单一 `OpenAICompatibleProvider`**：所有国产模型走 OpenAI 兼容协议，`tools` 注入与 `tool_calls` 分片累加在此完成；`deep_thinking=True` 时注入 `enable_thinking`（Qwen3 / DeepSeek）。
- **`ProviderManager` 单例 registry**（`:717`，借鉴 Cherry Studio），按 model id 缓存；缓存命中时也刷新 `api_key` / `model` / `base_url`（否则管理员更新 Key 后旧 Key 失效直接 401）。
- **遥测**：`get_tracer("cygnusx.ai")` span + `ai.chat.duration` histogram + `ai.tokens` counter + `core.ai_metrics` 应用内缓冲。
- **工具清洗**：`_dedupe_tools` 去重、`_strip_tool_artifacts` 清理消息里的工具残留。

### 5.4 语言与 Python 版本

| 环境 | 版本 |
|---|---|
| 项目要求 | `requires-python = ">=3.11"`；mypy `python_version = "3.11"`；ruff `target-version = "py311"` |
| 生产 web 镜像 | `python:3.11-slim`（`deploy/docker/Dockerfile:7,75`） |
| Studio 沙箱镜像 | `python:3.12-slim`（`deploy/studio/base.Dockerfile:10`，含 pandas/numpy/matplotlib/plotly/seaborn） |
| 外部 MCP server | `requires-python = ">=3.11"` + `fastmcp>=2.3.0` |

---

## 6. 预期的多 Agent 协同场景

代码中**四种模式全部已落地**，不是纯规划。

### 6.1 主管动态派工（Supervisor）

- **Router Agent**（`data/ai/router.yaml`，`agent_id: agent-router`，产品名「星尘 AI」）：用低成本快模型（`deepseek-v4-flash`，temp=0、max_tokens=200）做意图分类，输出 JSON 路由决策。实现 `ChatService._route_to_agent()`（`chat_service.py:629`）
  - 候选清单 / 能力描述 / 流程目录全部来自唯一权威数据源 `AgentTeamsCapabilityRegistry` 快照（`data/ai/*.yaml`），chat 侧不自行组装、不另读 YAML、不另起缓存
  - **渐进暴露**：summary 层注入路由上下文（实测 4131 → 2801 tokens），四段契约（`capabilities` / `not_suitable_for` / `handoff_when` / `preferred_inputs`）下沉 detail 层，选中候选后会诊阶段再加载
  - **任何失败（模型报错、解析失败、目标不存在）都静默回落 general 候选，绝不抛出**
- **AgentTeams Manager**（生物信息部门经理）：`AgentConsultationService` 会诊链 —— 读 Case 上下文 + 证据，必要时派受限 Worker 只读会诊，产出摘要 / 建议 / 风险 / 证据引用
- **Overdrive / 超频模式**：`OverdriveChatRuntime` + LangGraph Orchestrator 图（`plan_generate → plan_confirm → dispatch → aggregate`）

### 6.2 严格流水线（Handoff，A→B→C）

- 工具 `transfer_to_agent`（`HANDOFF_TOOL_NAME`），服务端策略层 `AgentHandoffService`（`application/services/agent_handoff_service.py`）
- **白名单校验** + 交接包（`MAX_HANDOFF_PACKET_BYTES=2400`）；**默认最大跳数 10，天花板 10**（`DEFAULT_MAX_HOPS` / `MAX_HOPS_CEILING`）
- 机制：`tool_exec` 检测到 handoff directive → 立即结束当前图 → ChatService 装配目标 Agent → **同一会话链路继续**
- Case 执行链：房间消息 → execution intent → `start_chat_planning` → Case / Work Items → Manager / Worker / QC / Delivery → 房间时间线投影

### 6.3 任务并发分发聚合（Map-Reduce）

- 工具 `parallel_subagents` → `ParallelSubAgentService`（`application/services/parallel_subagent_service.py`）
- 父 Agent 一次工具调用提交相互独立的子任务列表 → `asyncio.gather` + Semaphore 并发跑受限子 ReAct → 结构化汇总（`summary` + `results[]`）回父上下文
- 七条正确性约束（对应设计文档 §4.4 C1–C7）：
  - **C1** 每个子循环独占 AsyncSession
  - **C2** 剥离 `parallel_subagents` 自身（防递归，深度恒为 1）
  - **C3** 剥离 `transfer_to_agent` / `create_agentteams_case` / 记忆写工具
  - **C4** `requires_confirm` 工具不在子循环执行，形成审批请求升级回 Manager
  - **C5** 单工具回灌截断 + 子循环总轮数上限
  - **C6** 子任务产物写各自隔离子目录（经 `ToolInvocationContext.extra` 透出）
  - **C7** fan-out 对父循环只计一次 tool_call
- 灰度双开关：`SUBAGENT_FANOUT_ENABLED` 或管理端平台设置；灰度双标记 `tool_packs` + `features.subagents_spawnable`

### 6.4 多角色讨论互评（Group Chat / Room）

- **AgentTeams 协作室**：房间消息意图五态判定（`chat` / `clarify` / `tool_execute` / `execute` / `degraded`），策略保守——「宁可漏触发，不因单个执行关键词误启动真实 Case」
- **A2A 消息总线**：Redis Stream `cygnusx:mas:events` + consumer group `mas-scheduler`（`infrastructure/mas/redis_streams.py`），发布方只发**已持久化的不透明事件信封**
- **Matrix 集成**：房间邀请 `bioops-manager` / `cygnusx-user` 身份；平台用户动态身份前缀 `cygnusx-user-<slug>`（三进程共用同一字符串，改动需同步）
- **独立部署的 AgentTeams Bridge**：`integrations/agentteams`；`AgentTeamsService`（1999 行）是其 authenticated adapter
- **MAS DAG 调度**：`MASSchedulerService` 依赖感知 + 乐观锁节点状态迁移

### 6.5 统一可观测性契约

所有 Runtime（Legacy / LangGraph / Studio / Worker）共享同一套生命周期事件（`application/services/execution_events.py`）：

```text
event_type / session_id / run_id / agent_id / round / execution_path / tool_call_id / timestamp

agent_turn_started → agent_tool_call → agent_tool_started → agent_tool_result
→ agent_context_reinjected → agent_turn_continued → agent_final_result
异常：agent_turn_failed / agent_loop_guard_triggered
```

`execution_path` 是观测与排障字段（`chat_legacy` / `chat_langgraph` / `studio_chat_loop` / `agentteams_worker_react` / `agentteams_manager_consultation` / `agentteams_tool_execution`），**不替代权限判断**。

---

## 7. 关键实现位置索引

| 位置 | 职责 |
| --- | --- |
| `src/cygnusx/api/v1/chat.py` | SSE 出口，`ChatChunk` → SSE JSON |
| `src/cygnusx/application/services/chat/agent_runtime_gateway.py` | 统一 Agent 入口 + `agent.run` OTel span 父上下文发布 |
| `src/cygnusx/application/services/chat_service.py` | Agent 编排主文件（6322 行）：装配、工具分发、Studio 分支、消息收尾 |
| `src/cygnusx/application/services/chat/request_preparation.py` | `prepare_agent_request()`：上下文装配 + 模型可用性策略 |
| `src/cygnusx/application/services/agent_context_builder.py` | `AgentContextBuilder`：集中装配 + 60s TTL 缓存 |
| `src/cygnusx/application/services/agent_service.py` | `AgentContext` dataclass、`assemble_context()`、`_tool_pack_config()`、`ensure_builtin_agents()` |
| `src/cygnusx/application/services/chat/runtimes/base.py` | `ChatRuntime` ABC + `ChatRuntimeRequest` |
| `src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py` | LangGraph 聊天 Runtime（1168 行）：submit_output 挂载、审批闸、legacy 工具分发全链、落库信封 |
| `src/cygnusx/infrastructure/execution/langgraph_runtime.py` | 状态图运行 + `asyncio.Queue` 流式输出 |
| `src/cygnusx/infrastructure/execution/langgraph_nodes.py` | `NodeDeps` / `llm_call_node` / `tool_exec_node` / 两条路由函数 |
| `src/cygnusx/domain/execution/agent_state.py` | `AgentState` TypedDict |
| `src/cygnusx/domain/execution/orchestrator_state.py` | `OrchestratorState` TypedDict（与 AgentState 同级） |
| `src/cygnusx/infrastructure/execution/orchestrator_graph.py` | MAS Orchestrator 编排图（interrupt 计划确认 + PostgresSaver） |
| `src/cygnusx/infrastructure/execution/checkpointer.py` | `postgres_checkpointer()` / `memory_checkpointer()` 工厂 |
| `src/cygnusx/infrastructure/ai_provider/openai_compatible.py` | `ChatChunk` / `OpenAICompatibleProvider` / `ProviderManager` |
| `src/cygnusx/infrastructure/mcp/client.py` | `MCPClient`：三传输、工具发现、调用路由、错误隔离 |
| `src/cygnusx/infrastructure/sandbox/pool.py` | 轻量 Docker 沙箱容器池 |
| `src/cygnusx/infrastructure/studio/manager.py` | Studio 一会话一容器沙箱 |
| `src/cygnusx/application/services/parallel_subagent_service.py` | Worker fan-out + 子 ReAct + 隔离与控制 |
| `src/cygnusx/application/services/agent_handoff_service.py` | Handoff 白名单、交接包、会话审计 |
| `src/cygnusx/application/services/agent_memory_service.py` | 长期记忆 save/search/update/forget |
| `src/cygnusx/infrastructure/memory/fact_store.py` | `FactStore` Protocol + `PostgresFactStore` |
| `src/cygnusx/domain/mas/tool_policy.py` | MAS 工具执行准入策略（只读预检） |
| `src/cygnusx/infrastructure/mas/redis_streams.py` | MAS A2A Redis Stream 发布/消费 |
| `src/cygnusx/application/services/execution_events.py` | 统一 Agent 生命周期事件构造 |
| `data/ai/*.yaml` | 20 个 Agent 的能力声明源（唯一权威数据源） |
| `mcp-server/` | 独立部署的外部 MCP Server（FastMCP，40 工具） |

---

## 8. 改造时的关键约束

1. **禁止新增 legacy-only 循环行为**（2026-09-19 起正式口径）——新能力一律进 LangGraph 图，legacy 只维护逃生舱最小逻辑。
2. 新增工具必须同时定义 `llm_payload` 与 `ui_payload`，明确长度与敏感信息处理；受控工具需声明 `requires_confirm`。
3. 新增终止分支（ask_user / handoff / finalize / error）必须同时处理持久化、SSE、前端状态、token usage；所有最终结果事件必须先于 `done`。
4. 不要把 Worker 内部过程直接当作 Manager 最终结论。
5. **权威状态账本永远是 `overdrive_runs` / `overdrive_events` 表**；LangGraph state + checkpoint 只作执行恢复载体（P0 决策）。
6. `AgentState.messages` 保持 OpenAI dict 格式，不要引入 LangChain 消息封装。
7. 上下文历史由前端显式传入——后端新增任何「记忆上轮状态」的逻辑都必须显式声明存储位置，不得隐式依赖进程内变量。
8. 多租户隔离红线：Studio 沙箱按用户目录挂载，禁止整根挂载存储根。
9. 改后端代码后需 `docker restart omichub-web`（uvicorn `--workers 2` 无 reload）；改 Celery task 需 `docker restart omichub-worker`。
