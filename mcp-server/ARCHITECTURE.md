# CygnusX MCP 架构（整改后终态）与扩展指南

> 本文档描述 2026-09 一致性整改后的最终架构：确认门人类凭证模型、内外双端一致性防线、
> builtin 通道加固与运行时可靠性设计。旧版"目录结构 + 扩展指南"章节保留并更新。

## 1. 双端全景

平台有两套并存的 MCP 表面（double surface），共享同一应用服务层：

```
┌───────────────────────── 外部通道（第三方 AI 客户端）─────────────────────────┐
│ Claude Desktop / Cursor / CLI                                                │
│   │ stdio / SSE(默认绑 127.0.0.1)                                            │
│   ▼                                                                          │
│ mcp-server/  FastMCP Server ── tools.yaml 声明 + tools/*.py 注册              │
│   │  X-API-Key                                                               │
│   ▼                                                                          │
│ REST API  /api/v1/* (FastAPI)                                                 │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       ▼
                              application services（TaskService / DownloadService /
                              PipelineController / AnalysisFlowToolService …）
                                       ▲
┌──────────────────────────────────────┴───────────────────────────────────────┐
│ 内部通道（平台自带 AI Copilot/Studio/Agent 聊天）                              │
│   LangGraph runtime → MCPClient(builtin transport)                            │
│     ├─ cygnusx-platform preset   PLATFORM_PRESET_TOOLS ↔ PLATFORM_HANDLERS    │
│     ├─ cygnusx-pipelines preset  PIPELINE_TOOLS ↔ PIPELINE_HANDLERS           │
│     └─ cygnusx-tools preset      tools_schema.yaml + 动态 Flow → ToolBridge    │
│   携带 ToolInvocationContext(user_id/session_id/db/extra) 进程内直调，零网络   │
└───────────────────────────────────────────────────────────────────────────────┘

人类凭证唯一入口（JWT 登录态）：
  POST /api/v1/ai/tool-confirmations/{id}/approve|reject   ← task 记录（分析流程）
  POST /api/v1/ai/tool-invocations/{id}/approve|reject     ← tool 记录（requires_confirm 工具）
```

### 核心不变式

1. **模型永不能自证确认**。旧的 `_confirmed: true` 参数自证通道已废弃；执行凭证是
   服务端确认记录的 `APPROVED` 状态，而 `APPROVED` 只能由人类 JWT 端点写入。
2. **凭证一次性 + 绑参数**。`_confirmation_id` 重试时服务端校验归属、SHA-256 参数哈希
   （剔除控制参数后）、过期时间，原子置 `CONSUMED`，改参数即 `ARGS_CHANGED` 作废。
3. **内外同名同能力**。流水线/工作区工具在内外两端使用同一工具名（`rna_seq_*` 等），
   由启动自校验 + 一致性测试守护（见 §5）。

## 2. 人类确认门状态机

`src/cygnusx/application/services/tool_confirmation_service.py`

```
                 人类点卡(JWT, tool 记录)          模型携带 _confirmation_id 重试
  PENDING ────────────────────────────▶ APPROVED ────────────────────────────▶ CONSUMED
     │  ▲                                  │                        │
     │  │ 人类点卡(task 记录, JWT,          │ 参数被改                 │ 重复使用
     │  │ 一步消费并直接提交任务)            ▼                        ▼
     │  └─────────────────────────────  INVALID            ALREADY_CONSUMED(拒绝)
     │ 用户拒绝                                ▲
     ▼                                        │
  REJECTED            超时 ──▶ EXPIRED        │ args ≠ 首次预检参数
     │                                        │
     └── 已 SUBMITTED 的记录: 幂等回放 task_id（模型重发不重复建任务）
```

### 两类记录

| kind | 创建者 | 消费端点（人类） | 消费语义 |
|------|--------|----------------|----------|
| `task` | `AnalysisFlowToolService.prepare()`（流水线预检） | `/ai/tool-confirmations/{id}/approve` | JWT `human_confirmed` 一步 PENDING→SUBMITTED，**点击即提交任务**；模型端 `*_submit` 工具随后幂等拿到同一 `task_id` |
| `tool` | `ToolBridgeService` requires_confirm 门 / `platform_submit_download` 首次调用 | `/ai/tool-invocations/{id}/approve` | 仅 PENDING→APPROVED（不执行）；模型必须携带 `_confirmation_id` 以完全相同参数重试才真正执行 |

### 各通道确认路径

| 通道 | 首次调用 | 确认 | 执行 |
|------|---------|------|------|
| 内部聊天（builtin preset） | 返回确认卡 `ui_payload.confirm_card + confirmation_id + actions` | 用户点卡 → JWT approve（`McpToolCallCard.vue` POST） | 模型携 `_confirmation_id` 同参重试 |
| 外部 REST（JWT 或 API-Key） | — | `human_confirmed=True` 是请求体/端点内声明 | 允许 PENDING 一步消费（CLI 场景：终端前的人即确认人；此为文档化的残余信任假设） |
| 外部 MCP（mcp-server） | `user_confirmed=False` → 返回 `_needs_confirmation` 摘要 | 用户在客户端确认 | `user_confirmed=True` → REST submit 带 `user_confirmed` → 服务端按人类通道一步消费 |
| AgentTeams 协作 Case | `record_confirmation_request` | 真实用户 ChatMessage（服务端校验 marker 元数据与时间序） | `create_agentteams_case` 仅在该消息存在后放行 |

### 存储与多 worker

- **首选 Redis**（`settings.redis_url`）：key 带 TTL（默认 30 分钟），状态迁移用 Lua 脚本
  原子完成（expected-status CAS），多 worker/多重启进程共享同一确认事实。
- **回退内存 `_MemoryStore`**（asyncio.Lock + save 时惰性清除过期），仅单 worker 可用；
  Redis 不可达时自动降级并在日志中说明。
- 旧版"进程内 dict + 从不执行的 cleanup_expired"导致的跨 worker ACCESS_DENIED 与
  内存泄漏已由此消除。

## 3. 内部 builtin 通道加固

`src/cygnusx/infrastructure/mcp/`

| 项 | 设计 |
|----|------|
| 身份注入 | `_cygnusx_tools_handler` 拒绝无 user_id 调用；**移除** `arguments["_user_id"]` 回退（模型不可再通过参数伪造身份） |
| `ToolInvocationContext` | 进程内对象，禁止序列化（`model_dump` 抛错）；`extra["human_confirmed"]` 仅由 REST 端点构造，聊天 runtime 上下文永不携带 |
| Prompt 文件加载 | `_WORKSPACE_FILES_PROMPT_MD` 以 `Path(__file__).parents[4]` 锚定仓库根，不再随进程 CWD 漂移 |
| Preset 快照自愈 | `mcp_service._sync_preset_server()` 每次 `ensure_presets` 对比代码内 preset 工具与 DB 注册表：描述/schema 漂移自动重同步并 bump patch 版本（尊重 `preset_version_pinned` / `force_preset_sync`）；`cygnusx-tools` 与 platform/pipelines 同口径，消除"preset 快照漂移" |
| Builder AST 门禁 | `builder/safety.py`：禁用调用的**别名追踪**（`f = eval`、海象/多重赋值/for 目标）、`MODULE_SCOPED_FORBIDDEN_ATTRIBUTES`（`os.remove`/`shutil.move`/`subprocess.*` 按接收者拦截而不误伤 `df.rename`）、路径拼接**常量折叠**（`"/et"+"c/passwd"` 命中敏感前缀）、`GENERATED_MARKER` 按行精确匹配（防字符串伪造） |
| Builder 审批链 | 注册即 `review_status=pending` 且 `pool=experimental`；`agent_service` 挂载/暴露工具时过滤未批准 server（SQL 谓词 + `assemble_context` 双保险）；沙箱测试通过或人工 review approved 才置 `APPROVED`；注册 args 改为 `mcp-builds/<name>/server.py` + `working_dir=/workspace` 相对形态并经 `validate_stdio_args` 校验，`mcp_name` 消毒防注入 |
| 会话池 | `_with_external_session`：锁只保护建连阶段（MCP SDK 单会话按 jsonrpc id 多路复用，天然并发），工具调用不持锁 → stdio 慢调用不再队头阻塞全体用户；失效摘除按连接对象**身份**比对；`close_external_connections` 置 `pool_closing` 标志拒绝借用，关闭竞态受控 |
| 熔断 | `reliability.py` 按 `failure_kind` 分流：`tool_error/validation/file_reference`（调用方错误，server 存活）不再计入熔断；timeout/网络类计入；半开试探收到 tool_error 时 `release_probe()` 释放占位防永久 open；最终错误保留根因透传 |

## 4. 外部 mcp-server 要点

- **传输**：stdio（默认）或 SSE；`server.host` 默认 `127.0.0.1`，SSE 绑定非回环地址时
  启动打印安全告警（SSE 本身无鉴权，可达者即持有 API Key）。
- **REST 客户端**：`client/api_client.py` 按 content-type 解析响应（HTML 错误页不再炸
  JSONDecodeError）；`submit_pipeline` 请求体 `{"prepared_params":…, "user_confirmed": True}`；
  reports 资源 JSON 序列化 bug 已修。
- **确认门**：`rna_seq_submit`/`atac_seq_submit` 缺 `user_confirmed` 时返回
  `_needs_confirmation` 摘要卡（含样本数/比较组预览）；`cygnusx_submit_analysis`/
  `cygnusx_submit_download`/`cygnusx_cancel_task` 同口径。
- **启动自校验**：`tools/__init__.py::_verify_tools_yaml_consistency` 比对
  tools.yaml 声明组 ↔ `_GROUP_REGISTRY`、声明工具名 ↔ FastMCP 实际注册集（仅告警不阻断）。

## 5. 一致性防线（防双端漂移）

| 层 | 机制 | 位置 |
|----|------|------|
| 外部进程内 | 启动 self-check（yaml↔注册工具集） | `mcp-server/tools/__init__.py` |
| 平台进程内 | preset 重同步（代码↔DB 注册表漂移自愈+版本 bump） | `infrastructure/mcp/mcp_service.py` |
| CI 单测 | `tests/unit/test_mcp_dual_surface_parity.py`：platform/pipeline preset 的 tool↔handler 闭合；内外流水线工具名集合相等；`*_submit` 必须有 `requires_confirm` 声明且注册函数含 `user_confirmed` 参数；`platform_submit_download` schema 必须声明 `_confirmation_id` 且 handler 源码含 create/consume 门；`ToolBridgeService.execute` 源码禁止重新出现 `_confirmed` 自证旁路 | 本仓库 tests/unit |
| 确认服务单测 | `test_requires_confirm_returns_confirm_card`（PENDING 拒消费→人类 APPROVED→CONSUMED→重放 ALREADY_CONSUMED→改参 ARGS_CHANGED）、`test_analysis_flow_confirm_and_submit`（模型拒→人类通道提交→幂等回放） | `tests/unit/tools/` |

## 6. 残余风险（文档化接受）

1. **外部 API-Key 通道的 `user_confirmed=True`**：服务端将其视为"终端前的人类确认"，
   无法区分 CLI 用户本人与其驱动的模型——这是外部 CLI 可用性的有意妥协；对外发 API Key
   前应评估该信任级别。
2. **内存回退存储**：Redis 不可用时确认状态仅存单进程内存，多 worker 部署下会退化为
   偶发 ACCESS_DENIED（正确但体验受损）；生产建议常备 Redis。
3. **SSE 无内建鉴权**：依赖回环绑定 + 可信内网/反代，启动有告警。
4. **AgentTeams `_confirmed` 提示语**：前端协作 Case 文案仍提到 `_confirmed`，真正的门是
   服务端"用户消息 marker 校验"，该参数仅剩路由提示作用。

## 7. 目录结构

```
mcp-server/
├── config.yaml          # 服务配置 (连接、传输、host、工具组开关、限制)
├── tools.yaml           # 工具注册表 (元数据声明，启动时与实际注册自校验)
├── pyproject.toml       # 依赖管理
├── main.py              # 入口: FastMCP 实例 + 全组注册 + SSE host 告警
├── pipelines_main.py    # 独立 cygnusx-pipelines Server 入口（只注册流水线组）
├── start.sh             # 启动脚本
├── core/
│   ├── config.py        # 配置加载 (YAML + 环境变量覆盖, host 默认 127.0.0.1)
│   └── logger.py        # 日志
├── client/
│   └── api_client.py    # 平台 REST API 客户端 (httpx, X-API-Key, content-type 防御解析)
├── tools/               # 工具模块 (每组一个文件，_GROUP_REGISTRY 驱动注册)
│   ├── __init__.py      # 注册 + tools.yaml 一致性自校验
│   ├── tasks.py / flows.py / analysis.py / downloads.py / files.py
│   ├── reports.py / sandbox.py / platform.py / pipelines.py
├── resources/           # MCP Resources (只读数据源)
│   └── catalog.py
├── prompts/             # MCP Prompts (工作流引导)
│   └── workflows.py
└── models/              # Pydantic 模型 (可选)
```

## 8. 配置体系

### config.yaml

```yaml
server:        # 服务元数据 + 传输模式 (transport, host 默认 127.0.0.1, port)
connection:    # 平台 API 连接 (base_url, api_key, timeout)
limits:        # 输出限制 (行数、超时)
tool_groups:   # 工具组开关 (true/false)
```

**优先级**: 环境变量 (`CYGNUSX_BASE_URL`) > `config.yaml` > 代码默认值

### tools.yaml

声明式工具注册表，记录每个工具的元数据（名称、描述、是否只读、`requires_confirm`）。
运行时注册由 `tools/__init__.py` 的 `_GROUP_REGISTRY` 驱动；两者不一致会在启动日志告警，
并被 `test_mcp_dual_surface_parity.py` 在 CI 拦截。

## 9. 扩展指南

### 新增外部工具组 (3 步)

#### 1. 创建工具模块 `tools/<group>.py`

```python
"""<group> 工具"""

from fastmcp import FastMCP
from client.api_client import CygnusXAPIClient, CygnusXAPIError


def register(mcp: FastMCP, api: CygnusXAPIClient) -> None:

    @mcp.tool()
    async def cygnusx_<group>_<action>(param: str) -> dict:
        """工具描述（AI 助手看到的说明）。"""
        try:
            data = await api.get(f"/<endpoint>", params={"param": param})
            return {
                "success": True,
                "summary": "人类可读的摘要",
                "data": data,
                "next_steps": ["建议的后续操作"],
            }
        except CygnusXAPIError as e:
            return {"success": False, "summary": f"失败: {e.detail}"}
```

#### 2. 注册到 `tools/__init__.py`

```python
_GROUP_REGISTRY: dict[str, str] = {
    ...
    "<group>": "tools.<group>",  # 新增这行
}
```

#### 3. 在 config.yaml 和 tools.yaml 中声明

```yaml
# config.yaml
tool_groups:
  <group>: true

# tools.yaml
groups:
  - id: <group>
    module: tools.<group>
    description: "..."
    tools:
      - name: cygnusx_<group>_<action>
        description: "..."
        read_only: true
```

启动时自校验会确认三处（registry / yaml / FastMCP 实例）闭合。

### 新增"破坏性"工具（需确认门）

- **外部 mcp-server**：加 `user_confirmed: bool = False` 参数，缺省返回
  `_needs_confirmation` 摘要（参考 `tools/pipelines.py`），tools.yaml 标
  `requires_confirm: true`。
- **内部 ToolBridge 工具**（tools_schema.yaml）：标 `requires_confirm: true` 即可——
  桥接层自动生成 tool 确认记录并下发确认卡，无需写任何确认代码。
- **内部 platform preset handler**（presets.py）：仿照 `_platform_submit_download`，
  用 `get_tool_confirmation_service().create_for_tool/consume_tool_confirmation`
  显式加门，并在 inputSchema 声明 `_confirmation_id`。

### 新增内部 builtin 工具

1. `presets.py`：`PLATFORM_PRESET_TOOLS` 加入 schema + `PLATFORM_HANDLERS` 注册 handler
   （两者必须同名闭合，CI 会测）。
2. handler 签名统一 `(arguments, user_id=None, **_kw)`；需要会话/DB 时用
   `context: ToolInvocationContext | None`，且**必须**在 user_id/context 缺失时直接报错，
   不得从 arguments 兜底取身份。
3. 如需系统提示词联动，改 `data/ai/` 下对应 prompt 文件（仓库根锚定加载）。

### 扩展新 Resource

在 `resources/catalog.py` 的 `register()` 中添加:

```python
@mcp.resource("cygnusx://<domain>/<id>")
async def my_resource(id: str) -> str:
    """资源描述"""
    data = await api.get(f"/<endpoint>/{id}")
    return json.dumps(data, ensure_ascii=False, indent=2)
```

### 扩展新 Prompt

在 `prompts/workflows.py` 的 `register()` 中添加:

```python
@mcp.prompt()
def my_workflow(param: str = "default") -> str:
    """工作流描述"""
    return f"""引导文本...
1. 步骤一
2. 步骤二
"""
```

### 扩展平台 API 客户端

在 `client/api_client.py` 的 `CygnusXAPIClient` 类中添加方法:

```python
async def my_endpoint(self, param: str) -> dict:
    return await self.get("/my-endpoint", params={"param": param})
```

## 10. 设计约定

| 约定 | 说明 |
|------|------|
| 工具命名 | `cygnusx_<group>_<action>`，全小写下划线；例外：与平台内部 preset 对齐的工具（`list_workspace_files`/`search_workspace_files`/`rna_seq_*`/`atac_seq_*` 等）沿用内部命名，保证内外双端同名（CI parity 测试锁定） |
| 确认门 | 破坏性操作：外部用 `user_confirmed: bool = False`；内部桥接用 `requires_confirm` + `_confirmation_id`。**`_confirmed` 不再具有任何放行能力** |
| 控制参数 | 下划线开头参数被桥接层豁免校验、豁免参数哈希（`_CONTROL_ARGUMENT_KEYS`），不会进入工具实现 |
| 返回格式 | `{"success": bool, "summary": str, "data": Any, "next_steps"?: list[str]}`；内部双通道 `llm_payload`（精简回灌）+ `ui_payload`（完整渲染） |
| 错误处理 | 外部捕获 `CygnusXAPIError` 返回 `{"success": False, …}`；内部按 `failure_kind` 分流（网络类计入熔断，调用方错误不计入）且保留根因 |
| 输出上限 | `cygnusx_read_file_content` 行数、`cygnusx_get_task_logs` 条数、`cygnusx_sandbox_execute` 超时均 clamp 到 `config.yaml` 的 `limits.*`（默认 50 行 / 100 条 / 300 秒） |
| 认证 | 平台→服务：`X-API-Key` 统一注入；服务→人类：JWT approve/reject 端点是确认状态机的唯一人类写入点；SSE 传输本身无鉴权，host 默认回环，仅可信内网使用 |

## 11. 平台侧对应关系

| MCP 工具组 | 平台 API 路由 | 服务层 |
|-----------|-------------|--------|
| tasks | `/api/v1/tasks` | `TaskService` |
| flows | `/api/v1/flows` | `FlowService` |
| analysis | `/api/v1/tasks` (POST) | `TaskService.submit()` |
| downloads | `/api/v1/downloads` | `DownloadService` |
| files | `/api/v1/files` | `FileService` |
| reports | `/api/v1/reports` | `ReportService` |
| sandbox | `/api/v1/sandbox` | `SandboxService` |
| platform | `/api/v1/auth/me` + `/api/v1/stats` | — |
| pipelines | `/api/v1/pipelines` | `PipelineController`（prepare/submit/status/results，submit 过确认门） |
| 确认门 | `/api/v1/ai/tool-confirmations/*`、`/api/v1/ai/tool-invocations/*` | `ToolConfirmationService`（Redis/内存双后端） |

## 12. 关键测试地图

| 测试 | 守护内容 |
|------|---------|
| `tests/unit/test_mcp_dual_surface_parity.py` | 内外双端工具名/确认门/preset 闭合、`_confirmed` 旁路禁止回归 |
| `tests/unit/tools/test_tool_bridge.py::test_requires_confirm_returns_confirm_card` | tool 记录完整生命周期（含 ARGS_CHANGED / 一次性消费） |
| `tests/unit/tools/test_analysis_flow_tool.py::test_analysis_flow_confirm_and_submit` | task 记录模型拒→人类提交→幂等回放 |
| `tests/unit/test_mcp_circuit_breaker_kinds.py` | 熔断按 failure_kind 分流、半开占位释放 |
| `tests/unit/test_mcp_session_pool_lock.py` | 会话池锁范围、并发借用、关闭竞态 |
| `tests/unit/test_mcp_preset_resync.py` | preset 漂移自愈 / pin / 别名守卫 |
| `tests/unit/test_mcp_builder_approval_and_safety.py` | Builder AST 绕过场景与审批链门禁 |
