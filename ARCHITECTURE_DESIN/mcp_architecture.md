# MCP 架构与自生成框架设计

> **用途**：本文件记录 CygnusX MCP（Model Context Protocol）子系统的完整架构现状、"Agent 自生成 MCP"可行性分析与三阶段提案的历史注记（§4），以及 MCP 构建师 `agent-mcp-builder` 的最终落地实现（§5，as-built）。
>
> **最后更新**：2026-09-18
>
> **时点说明**：§1–§3、§6–§10 为 2026-07-29 时点的架构快照，所述现状已演进，部分引用（路径、行号）已失效；当前实现以代码为准。§4 为历史注记（2026-09-18 精简），§5 为 2026-07-30 时点的 as-built 实现记录。

> **适用范围**：MCP 注册/发现/调用、沙箱隔离、AI 代码生成、实验性 MCP 生命周期管理。

> **合并说明（2026-09-18）**：本文档与 `mcp_builder_agent.md`（as-built 实现文档）合一——后者全部内容并入为 §5"MCP 构建师 agent-mcp-builder（as-built）"，原文件已删除；本文档原 §4–§5"Agent 自生成 MCP 可行性分析与三阶段提案"压缩为历史注记（新 §4），保留能力复用度结论要点，删除被最终实现取代的重复设计稿（双份 AST 规则表、schema 扩展 SQL、`/mcp/*` 端点提案、五阶段部署流水线图）。最终实现见 §5。

---

## 1. MCP 子系统架构现状

### 1.1 三层 MCP 体系

CygnusX 的 MCP 能力由三层构成：

| 层级 | 说明 | 传输方式 | 延迟 |
|------|------|----------|------|
| 内置 Preset | 平台工具 + 管线工具，进程内执行 | `BUILTIN`（函数调用） | 零延迟 |
| 外部 MCP Server | 独立进程/容器，标准 MCP 协议 | `STDIO` / `SSE` / `STREAMABLE_HTTP` | 网络延迟 |
| 管线专属 MCP | RNAFlow / ATACFlow 各自的 FastMCP 服务 | `SSE`（端口 8900+） | 网络延迟 |

### 1.2 核心代码定位

| 功能 | 文件路径 |
|------|----------|
| Preset 注册与工具定义 | `src/cygnusx/infrastructure/mcp/presets.py` |
| 管线 Preset（RNA/ATAC） | `src/cygnusx/infrastructure/mcp/pipeline_preset.py` |
| 统一 MCP 客户端 | `src/cygnusx/infrastructure/mcp/client.py` |
| 域实体与服务 | `src/cygnusx/domain/mcp/entities.py`, `services.py`, `repositories.py` |
| 值对象（Transport/Status） | `src/cygnusx/domain/mcp/value_objects.py` |
| Admin API 路由 | `src/cygnusx/api/v1/mcp.py` |
| 渐进式能力加载 | `src/cygnusx/application/services/studio_capabilities.py` |
| 独立 MCP Server | `mcp-server/main.py` + `mcp-server/config.yaml` |
| 数据库模型 | `src/cygnusx/infrastructure/database/models/` (mcp_servers, mcp_logs 表) |
| 前端 Store | `frontend/src/stores/mcp.ts` |

### 1.3 内置 Preset 工具清单

**cygnusx-platform**（22 个工具）：

```
platform_list_tasks, platform_get_task, platform_list_flows,
platform_sandbox_execute, platform_read_file,
list_workspace_files, search_workspace_files,
workspace_list_files, workspace_read_file, workspace_get_file_info,
find_session_uploads,
europe_pmc_search, arxiv_search,
platform_get_user_info, platform_get_current_time,
platform_list_agent_skills, platform_admin_health_check,
platform_submit_download, platform_list_downloads, platform_get_download_progress,
ability_catalog_query, room_state_query
```

（完整定义见 `infrastructure/mcp/presets.py:1389-1790`。）

**cygnusx-pipelines**（10 个工具）：

```
rna_seq_prepare, rna_seq_submit, rna_seq_status, rna_seq_results,
atac_seq_prepare, atac_seq_submit, atac_seq_status, atac_seq_results,
list_available_pipelines, check_workspace_data
```

**cygnusx-tools**（动态构建）：从 `tools_schema.yaml` + 启用了 `ai.enabled=True` 的 Flow 配置动态生成。

### 1.4 MCP 注册与发现流程

```text
启动阶段:
  main.py → _init_mcp_presets() → MCPService.ensure_presets()
    → 幂等写入 DB (mcp_servers 表, is_preset=True)

运行时注册:
  Admin API POST /api/v1/mcp/servers → 验证 → 写入 DB
  Agent YAML (data/ai/*.yaml) mcp_ids 字段 → 绑定到 Agent

会话加载:
  ChatService → AgentService.assemble_context(agent_id)
    → 读取 Agent 绑定的 mcp_ids → 加载 MCPServer 实体
    → studio_capabilities 渐进式加载 → LLM 获得工具 schema

工具调用:
  LLM 输出 tool_call → ChatService 路由到所属 MCPServer
    → MCPClient.call_tool()
      ├─ BUILTIN: 直接调用 PLATFORM_HANDLERS[name](args)
      └─ 外部: _open_session(server) → MCP SDK session.call_tool()
```

### 1.5 安全验证

`MCPClient` 内置三层安全校验：

| 校验函数 | 防护目标 |
|----------|----------|
| `validate_stdio_command()` | 禁止 shell 解释器、路径穿越、绝对路径 |
| `validate_sse_url()` | 禁止内网/回环/元数据 IP（169.254.x, 10.x, 127.x） |
| `validate_stdio_args()` | 禁止 shell 元字符（`;`, `|`, `&&`, `$()` 等） |

外部调用统一包裹 `asyncio.wait_for` 超时（默认 30s，`mcp_default_timeout` 配置）。

### 1.6 MCP API 端点

| 方法 | 路径 | 权限 | 用途 |
|------|------|------|------|
| GET | `/api/v1/mcp/servers` | Admin | 列出所有 MCP Server |
| POST | `/api/v1/mcp/servers` | Admin | 注册外部 Server |
| PUT | `/api/v1/mcp/servers/{id}` | Admin | 更新配置 |
| DELETE | `/api/v1/mcp/servers/{id}` | Admin | 删除 |
| POST | `/api/v1/mcp/servers/{id}/test` | Admin | 测试连接 |
| GET | `/api/v1/mcp/servers/{id}/tools` | Admin | 发现工具 |
| POST | `/api/v1/mcp/servers/{id}/tools/{name}/invoke` | Admin | 调用工具 |
| POST | `/api/v1/mcp/pipelines/tools/{name}/invoke` | User | 调用管线工具 |
| GET | `/api/v1/mcp/servers/{id}/logs` | Admin | 查看日志 |

### 1.7 数据库 Schema

```sql
-- mcp_servers 表
id            UUID PK
name          VARCHAR UNIQUE
description   TEXT
transport     VARCHAR (stdio/sse/streamable_http/builtin)
command       VARCHAR
args          JSON
url           VARCHAR
env           JSON
registry      VARCHAR
working_dir   VARCHAR
version       VARCHAR
status        VARCHAR (online/offline/error/starting)
is_enabled    BOOLEAN
tools         JSON          -- 工具快照
timeout       INTEGER
auto_restart  BOOLEAN
is_preset     BOOLEAN

-- mcp_logs 表
id            SERIAL PK
service_id    FK → mcp_servers.id
timestamp     TIMESTAMP
level         VARCHAR
message       TEXT
source        VARCHAR
```

### 1.8 热重载现状

| 组件 | 热重载支持 | 机制 |
|------|-----------|------|
| cygnusx-tools preset | 部分支持 | 每次 `get_preset_by_name()` 动态构建，新 Flow 自动出现 |
| 外部 MCP Server | 支持 | `MCPClient` 每次调用新建 session，注册后立即可用 |
| Preset 工具定义变更 | 支持 | `POST /api/v1/mcp/presets/reload` 热重载（`api/v1/mcp.py:32-39`，内部 `ensure_presets(force_preset_sync=True)`），无需重启 |
| workspace_files_prompt.md | 不支持 | import 时加载，需重启 |
| Prompt 系统 | 支持 | mtime 检测自动重载 |

---

## 2. 沙箱隔离体系

### 2.1 双沙箱架构

| 系统 | 用途 | 关键文件 |
|------|------|----------|
| SandboxPool（基础池） | 简单代码执行（MCP/API 调用） | `infrastructure/sandbox/pool.py` |
| StudioSandboxManager | AI 工作台，每会话独立容器 | `infrastructure/studio/manager.py` |

### 2.2 Studio 沙箱生命周期

```text
创建:
  ensure_running(session_id) → Docker 容器 "studio-{session_id[:8]}"
  容器内运行 sandbox_agent.py (FastAPI, UDS /workspace/.agent.sock)

通信:
  宿主机 httpx → Unix Domain Socket → 容器内 FastAPI
  无暴露端口，无 docker exec

执行:
  POST /exec → 流式 NDJSON 输出 → 超时 killpg

回收:
  Celery beat 每 5 分钟 → recycle_idle()
  空闲超过 idle_ttl_minutes (10min) → stop + remove
  Redis ZSET 执行租约 → 防止运行中被回收
```

### 2.3 资源限制

```yaml
# data/ai/studio.yaml
sandbox:
  cpu: 2                    # cpu_shares = 2048
  memory: 4g               # mem_limit
  exec_timeout_seconds: 600

# src/cygnusx/core/config.py (基础池)
sandbox_default_cpu: 2.0
sandbox_default_memory: "4g"
sandbox_exec_timeout: 300
sandbox_session_timeout: 300
sandbox_network_isolated: true
```

### 2.4 网络隔离

**模式一：`none`（默认）**
- `network_mode="none"`，容器无任何网络接口
- Agent 通信仍通过 UDS（文件系统，非网络）

**模式二：`whitelist`（当前 studio.yaml 配置）**
- 每会话创建 Docker `internal` 桥接网络（无互联网网关）
- 仅两个容器接入：沙箱 + `cygnusx-studio-egress-proxy`
- Egress Proxy（`deploy/studio/egress_proxy.py`）强制域名白名单：
  - 仅允许 HTTP 80 / HTTPS CONNECT 443
  - 当前白名单：`conda.anaconda.org, pypi.org, files.pythonhosted.org, mirrors.aliyun.com, mirrors.ustc.edu.cn`
  - 拒绝 IP 字面量、通配符、私有/保留地址
  - DNS 解析固定公网 IP（防 DNS rebinding）
- Proxy 容器加固：`read_only: true, cap_drop: [ALL], no-new-privileges, pids_limit: 128, mem_limit: 256m`

### 2.5 安全控制清单

- 非 root 执行（uid 10001）
- `realpath()` + 路径包含检查（写严格限制，读允许 platform 符号链接）
- Per-user 数据隔离（仅挂载 `users/{user_id}`，只读）
- 执行超时 + 进程组 SIGKILL
- 输出大小上限（10KB 流内，溢出写磁盘）
- Worker 节点无 Docker socket 访问权限
- 控制面认证：HMAC-SHA256 派生 token

---

## 3. AI 模型接入架构

### 3.1 Provider 抽象层

```text
┌─────────────────────────────────────────────────────┐
│  ProviderManager (单例注册表, 按 config ID 缓存)      │
│    chat_stream(config, messages, system_prompt, ...) │
└──────────────────────┬──────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
OpenAICompatible   LiteLLM         Kimi (Legacy)
  Provider         Provider
(httpx SSE 直连)  (100+ 模型)
```

### 3.2 当前配置的模型

| 名称 | 模型 | 端点 |
|------|------|------|
| deepseek-v4-flash | deepseek-v4-flash | DeepSeek（`https://api.deepseek.com`） |
| qwen3.8-flash | qwen3.8-flash | 阿里云 DashScope 兼容端点 |
| doubao-seed-evolving（默认） | doubao-seed-evolving | 火山方舟 |

### 3.3 多模型路由

```text
用户消息 → Router Agent (features.router: true)
  → LLM 意图分类 (temperature=0, max_tokens=200)
  → 输出 {"agent_id": "...", "reason": "...", "consult_agent_ids": [...]}
  → 组装目标 Agent 上下文 (模型/提示词/工具/MCP)
  → LangGraph ReAct 循环执行
```

### 3.4 LangGraph 执行引擎

```text
StateGraph:
  __start__ → llm_call ──[has tool_calls]──→ tool_exec ──→ llm_call (循环)
                   └──[no tool_calls]──→ __end__

约束: 最多 8 轮 tool 循环
依赖注入: NodeDeps (model_config, system_prompt, tools, tool_executor, event_emitter)
```

文件：`src/cygnusx/infrastructure/execution/langgraph_runtime.py`

---

## 4. Agent 自生成 MCP 可行性分析与三阶段提案（历史注记）

> **历史注记（2026-09-18 精简）**：本节为原 §4"Agent 自生成 MCP 可行性分析"与原 §5"实施方案"（2026-07-29 时点）的压缩版，提案其后已落地为 `agent-mcp-builder`，**最终实现见 §5（as-built）**。为免与 as-built 并存漂移，已删除被实现取代的重复设计稿：双份 AST 安全检查规则表（原 §5.4）、`mcp_servers` schema 扩展 SQL（原 §5.3）、sandbox_agent `/mcp/*` 端点提案（原 §5.3）与五阶段部署流水线图（原 §5.5）。以下仅保留当时的论证结论。

### 4.1 能力复用度结论（保留要点）

2026-07-29 时点评估：现有基础设施可直接支撑"Agent 自生成 MCP"的绝大部分能力——

| 所需能力 | 现有对应 | 复用度 |
|----------|----------|--------|
| LLM 代码生成 | `ProviderManager.chat_stream()` + LangGraph | 90% |
| 隔离运行环境 | `StudioSandboxManager` / `SandboxPool` | 95% |
| MCP 注册/挂载 | `MCPService` + Admin API + `MCPClient` | 80% |
| 网络安全隔离 | Egress Proxy + network_mode=none | 95% |
| 命令安全验证 | `validate_stdio_command()` | 70% |
| 用户级隔离 | Agent YAML `mcp_ids` + per-user 数据挂载 | 60% |

结论：仅需新建 5 个组件（AST 静态安全检查器、实验性 MCP 池 `pool` 字段 + TTL、生成→部署 Pipeline、MCP 健康检查、sandbox_agent MCP 端点），复杂度均为低/中——五者其后全部以 §5 形态落地。有利前提：`MCPClient` 无连接池（注册即用、无需热重载）、Studio 沙箱生命周期管理完备、Egress Proxy 域名白名单天然限网、`cygnusx-tools` preset 动态构建先例、新增 Agent 仅需 YAML 配置。

### 4.2 当时判定的主要障碍与最终落点

| 障碍 | 当时解法 | 最终实现落点 |
|------|----------|-------------|
| MCP 进程模型（外部 MCP 为长驻进程，生成代码须在沙箱内运行） | sandbox_agent 增加 `/mcp/start`，容器内启 SSE Server | 端点思路成立，但实现改为 `stdio_client` 拉起 STDIO 子进程 + 宿主 UDS 桥接，不暴露 TCP 端口（见 §5.5） |
| 热重载 | `MCPClient` 每次调用新建 session，注册即可用 | 与预判一致，无需热重载 |
| Prompt Injection | MCP 输出消毒 + 工具结果截断 | 防线改前置到代码侧：违规直接拒绝落库的 AST 静态检查 + 沙箱隔离 + 人工审核（见 §5.4、§10），输出侧消毒未单独实现 |
| 依赖安装 | 沙箱镜像预装白名单包 + 禁止运行时安装 | 以沙箱镜像预装依赖（`requirements-agent.txt`）+ egress 域名白名单落实（见 §5.5） |

### 4.3 三阶段提案（已落地）

原方案分三阶段推进：Phase 1 MVP（新建 `data/ai/mcp_builder.yaml`、studio_tools 增加 mcp_generate / mcp_validate 工具、生成代码写入 Studio 沙箱验证，约 2 天）→ Phase 2 隔离运行（`/mcp/start` 端点、`pool="experimental"` + `expires_at`、Celery beat 清理过期实验 MCP、UDS 代理，约 3 天）→ Phase 3 安全加固（AST 分析、结构验证、输出消毒、审计日志，约 2 天）。该路径其后整体落地；与原提案的偏差（如工具形态由 studio_tools 的 mcp_generate/mcp_validate 改为 `POST /api/v1/mcp-builder/builds` API 链、实验 MCP 采用 STDIO 而非 SSE、新增审核转正与版本回滚能力）一律以 §5 as-built 为准。

---

## 5. MCP 构建师 agent-mcp-builder（as-built）

> **章节说明（2026-09-18 并入）**：本节由 `mcp_builder_agent.md`（as-built 实现文档，最后更新 2026-07-30；其上游原始设计文档为 `docs/26.7.30/mcp_builder_framework.md`）全文并入，原文件已删除。本节即 §4 提案的最终实现记录，提案与本节冲突处以本节为准。用途：让平台 AI 根据自然语言需求自动生成、安全检查、沙箱测试并注册 MCP Server。

### 5.1 定位与边界

| 维度 | 说明 |
|------|------|
| 是什么 | 一个配置驱动的内置 Agent（非 Python 模块），驱动"需求 → 可用 MCP"全流程 |
| 产出物 | 实验池 MCP Server（带 TTL、仅创建者 + Admin 可见）+ 构建记录 + 文档 |
| 运行环境 | AI 交互在 Studio 沙箱会话内；生成的 MCP 以 STDIO 子进程运行于同一容器体系 |
| 不负责 | 实验 MCP 的 LLM 自动路由（后续项）、前端管理页（后续项）、非 Python 运行时 |

**红线**（对应本文 §10）：生成代码必须过 AST 检查且在 Docker 沙箱内运行；实验 MCP 必须有 TTL；网络受 egress 白名单约束；所有操作记入 `mcp_logs`（`source='builder'`）。

### 5.2 总体架构与六阶段工作流

六阶段（规划 → 搜索 → 编码 → 测试 → 文档 → 注册）由 Prompt 驱动（见 §5.3）；提交注册链路为 `POST /api/v1/mcp-builder/builds` → `MCPBuilderService`：

```text
用户（Studio 会话）
    │ 自然语言需求
    ▼
agent-mcp-builder（qdoubao-seed-evolving, temperature=0.2）
    │ 六阶段工作流（Prompt 驱动）
    │ ① 规划 → ② 搜索 → ③ 编码 → ④ 测试 → ⑤ 文档 → ⑥ 注册
    │
    ├─ workspace_write  ──→  /workspace/mcp-builds/{name}/server.py（沙箱内）
    ├─ sandbox_execute  ──→  语法/结构自检 + 业务逻辑测试
    │
用户/前端确认提交
    ▼
POST /api/v1/mcp-builder/builds
    │
    ▼
MCPBuilderService.submit_build()
    ├─ 配额检查（默认 5 个/用户）
    ├─ （无 code 时）MCPCodeGenerator → ProviderManager.chat_stream()
    ├─ StaticSafetyChecker.analyze()  ← 违规直接拒绝落库
    ├─ 注册 MCPServer（pool=experimental, expires_at=now+TTL）
    └─ 落库 mcp_builds + mcp_logs
    ▼
POST /api/v1/mcp-builder/builds/{id}/test
    │
    ▼
StudioSandboxManager（宿主）
    │ UDS（/workspace/{session}/.agent.sock）
    ▼
sandbox-agent /mcp/start（容器内）
    │ stdio_client 启动子进程 → MCP 握手 → tools/list
    ├─ /mcp/call 逐工具验证 → test_cases 落库
    ▼
审核（平台开关 mcp_builder_requires_review）
    ├─ Admin: POST /builds/{id}/review → approved → 版本快照 mcp_versions
    └─ 关闭审核：测试通过即发布
    ▼
Celery beat（每 5 分钟）
    └─ expire_experimental → 过期 MCP 自动下线
```

### 5.3 Agent 配置

| 文件 | 内容 |
|------|------|
| `data/ai/mcp_builder.yaml` | Agent 配置：`agent-mcp-builder`，model `qdoubao-seed-evolving`，temperature 0.2，max_tokens 65536，`tool_packs: [workspace, memory, handoff]`（handoff.allowed_targets=[agent-general, agent-code]，max_hops_per_session=10），`skill_ids: [mcp-server-builder]`（六阶段工作流与代码模板由该 Skill 承载），studio.enabled + default_mode=studio + runtime_profile=analysis-core，`features.agentteams`（expert 可招募、execution_modes=[readonly_consultation, workspace_execution]、max_parallel_work_items=1 等）+ `features.mcp_builder`（配额/TTL/产物目录元数据） |
| `data/ai/prompts/mcp_builder.md` | 六阶段系统提示词（约 5.8KB）：规划/搜索/编码/测试/文档/注册；不含代码模板——模板已迁移到 Skill `mcp-server-builder` 的 `references/`（`template_local_computation.py` 本地计算版 + `template_external_api.py` 外部 API 版），Prompt 要求接到构建需求后先加载该 Skill；保留安全红线、"绝不代为提交"约束（注册须用户/前端触发 API） |
| `data/CygnusX.yaml` | `agents.enabled` 追加 `mcp_builder`（加载白名单） |
| `data/ai/prompts/router.md` | 不维护静态候选名单——router 依据运行时可用 Agent 目录路由，构建师随 Agent 目录上线即可被路由（"创建/生成 MCP Server、给 AI 加新工具"类请求） |

**加载链路**：`agent_loader.load_agent_configs()` → 幂等落库 `agent_templates` → 会话时 `assemble_context()` 组装模型/Prompt/工具。Agent 是纯 YAML+Markdown 配置，非 Python 包。

**模型配置两处**：
- Agent 对话/生成：`mcp_builder.yaml` 的 `model` 字段（改后需重启 web）
- 后端 API 直连生成：`core/config.py` 的 `mcp_builder_default_model`（可被环境变量 `MCP_BUILDER_DEFAULT_MODEL` 或请求体 `model_name` 覆盖）

### 5.4 安全检查器（`infrastructure/mcp/builder/safety.py`）

`StaticSafetyChecker.analyze(code) -> SafetyReport{passed, violations[], warnings[], dependencies[]}`，纯静态 AST 分析，不执行被测代码。

| 维度 | 规则 | 级别 |
|------|------|------|
| 语法 | `ast.parse` 失败 / 超 512KB | violation |
| import | 黑名单（subprocess/ctypes/pickle/socket/shutil/sys/threading/importlib…） | violation |
| import | 白名单外（mcp/pydantic/httpx/pandas/numpy + 标准库安全子集之外） | warning（人工审核兜底） |
| import | 相对导入 | violation |
| 调用 | `eval/exec/compile/open/getattr/__import__/globals…` 裸调用 | violation |
| 调用 | `.system/.popen/.exec*/.fork/.kill` 等属性调用（任意接收者） | violation |
| 调用 | `.loads/.load/.dumps/.dump` 仅当接收者为 pickle/marshal/shelve（不误伤 `json.dumps`） | violation |
| 属性 | `__globals__/__subclasses__/__bases__/__mro__…` dunder 访问 | violation |
| 字符串 | `/etc//proc//sys//root//dev/`、docker.sock | violation |
| 字符串 | 内网/元数据 IP | warning（egress proxy 兜底） |
| 结构 | 缺 `__exp_mcp_generated__ = True` 标记 | violation |
| 结构 | 缺 MCP handler（`list_tools`+`call_tool` 或 FastMCP `@tool`） | violation |

检查失败时构建以 `rejected` 状态落库（保留记录供用户查看违规项），不注册 Server。

### 5.5 沙箱执行层

#### 5.5.1 容器内端点（`deploy/studio/sandbox_agent.py`）

| 端点 | 行为 |
|------|------|
| `POST /mcp/start` | 路径校验（必须落在 /workspace 内）→ `mcp.client.stdio.stdio_client` 以当前解释器启动 server.py 子进程 → `ClientSession.initialize()` 握手 → `list_tools()` → 返回 `{server_id, path, tools}`；单容器上限 8 个 |
| `POST /mcp/call` | `session.call_tool(tool, arguments)`，30s 超时，返回 `{content, is_error}` |
| `GET /mcp/tools` | 重查工具清单（失效退回启动缓存） |
| `POST /mcp/stop` | 关闭 AsyncExitStack（子进程组随之终止） |
| `GET /mcp/list` | 列出运行中的实验 MCP |

子进程继承容器的全部隔离属性：非 root（uid 10001）、network_mode=none / egress 白名单、CPU/内存配额。无 TCP 端口暴露，宿主只经 UDS 可达。

#### 5.5.2 宿主封装（`infrastructure/studio/manager.py`）

`start_mcp_server / stop_mcp_server / list_mcp_servers / mcp_list_tools / mcp_call_tool`——统一走 `_agent_call(session_id, method, endpoint)` 的 UDS httpx 封装，带 busy lease 防回收竞态。工作区预建目录含 `mcp-builds/`（chown 10001）。

#### 5.5.3 镜像依赖

`deploy/studio/requirements-agent.txt` 增加 `mcp>=1.2.0`（重建镜像后生效：`deploy/studio/build.sh`）。

### 5.6 数据模型

迁移 `h6i7j8k9l1m3`（down: `g4h5i6j7k8l9`），四张新表 + `mcp_servers` 扩展：

| 表 | 用途 | 关键字段 |
|----|------|----------|
| `mcp_builds` | 构建记录（核心） | user_id, requirement, generated_code, safety_report(JSON), mcp_server_id, version, parent_build_id（版本链）, status, test_cases(JSON), test_passed, build_doc, architecture_doc, model_used |
| `mcp_versions` | 版本快照 | mcp_server_id, version（与 server 联合唯一）, code_snapshot, tools_snapshot, changelog |
| `mcp_visibility` | 用户级共享授权（预留） | mcp_server_id+user_id 唯一, access_level, expires_at |
| `mcp_reviews` | 审核记录 | build_id, reviewer_id, decision, comment |
| `mcp_servers`（扩展） | — | pool(production/experimental/deprecated), expires_at, created_by, current_version, generation_meta(JSON), review_status, is_template |

**构建状态机**（`mcp_builds.status`）：`planning → coding → testing → reviewing → approved/rejected → published → deprecated`；审核 `request_changes` 回退到 `planning`。

**实体/值对象**：`domain/mcp/entities.py` MCPServer 扩展同名字段 + `is_expired()`；`value_objects.py` 新增 `ServerPool / BuildStatus / ReviewStatus / ReviewDecision / AccessLevel`。

### 5.7 API（`/api/v1/mcp-builder`，15 条路由）

| 方法 | 路径 | 权限 | 用途 |
|------|------|------|------|
| POST | `/builds` | User | 提交构建（附 code 直接检查；缺省 LLM 生成） |
| POST | `/generate` | User | 仅生成代码 + 安全预览，不落库 |
| GET | `/builds` | User | 我的构建历史（?status=&limit=） |
| GET | `/builds/{id}` | User（本人） | 构建详情 |
| DELETE | `/builds/{id}` | User（本人） | 删除构建（联动删其实验 MCP） |
| POST | `/builds/{id}/test` | User（本人） | 指定 session 沙箱内逐工具测试 |
| GET | `/review-queue` | Admin | 审核队列 |
| POST | `/builds/{id}/review` | Admin | 审核决定（approved 自动发布 + 版本快照） |
| GET | `/servers/experimental` | User | 我的实验 MCP 列表 |
| POST | `/servers/{id}/renew` | Owner/Admin | TTL 续期 |
| DELETE | `/servers/{id}` | Owner/Admin | 删除实验 MCP |
| POST | `/servers/{id}/promote` | Admin | 实验 MCP 转正为正式（清 TTL + publish 版本行） |
| POST | `/servers/{id}/invoke` | Owner/Admin | 经沙箱 UDS 桥接调用工具 |
| GET | `/servers/{id}/versions` | User | 版本历史 |
| POST | `/servers/{id}/rollback` | Owner/Admin | 回滚到指定版本 |

实验 MCP 的调用路径（invoke）：宿主 → UDS → sandbox-agent `/mcp/start`（确保子进程在）→ `/mcp/call` → 原路返回。不经过 `MCPClient` 的 stdio/sse 校验路径（生成代码从不落宿主文件系统）。

### 5.8 生命周期与运维

| 事项 | 机制 |
|------|------|
| TTL 过期 | Celery beat `mcp-builder-expire-experimental`（每 5 分钟）→ `expire_stale_servers()`：过期实验 MCP 置 offline + 禁用；容器侧子进程随 Studio 空闲回收销毁 |
| 配额 | `mcp_builder_max_per_user`（默认 5），按活跃构建数计 |
| 默认 TTL | `mcp_builder_default_ttl_hours`（默认 24） |
| 审核开关 | `mcp_builder_requires_review`（默认 true；关闭则测试通过即发布） |
| 功能总开关 | `mcp_builder_enabled` |
| 审计 | 关键操作写 `mcp_logs`（source=builder，含 actor） |

**部署注意**（本仓库既有约束）：
- 改后端代码/YAML 后 `docker restart cygnusx-web`（不热重载）；改 Celery 任务同步重启 `cygnusx-worker` + `cygnusx-beat`
- 迁移用容器内 `/app/.venv/bin/alembic upgrade head`
- 沙箱镜像改了 `requirements-agent.txt` 后需 `deploy/studio/build.sh` 重建

### 5.9 关键文件与测试清单

```text
data/ai/mcp_builder.yaml                          # Agent 配置
data/ai/prompts/mcp_builder.md                    # 六阶段 Prompt（约 5.8KB，不含代码模板）
data/ai/skill_marketplace/mcp-server-builder/references/  # 代码模板（template_local_computation.py / template_external_api.py）
data/CygnusX.yaml                                 # agents.enabled 注册
data/ai/prompts/router.md                         # 路由（依据运行时可用 Agent 目录，非静态名单）

src/cygnusx/infrastructure/mcp/builder/
├── safety.py                                     # AST 安全检查器
├── versioning.py                                 # SemVer 推导
├── generator.py                                  # LLM 代码生成（ProviderManager 封装）
└── doc_generator.py                              # build.md / architecture.md 模板

src/cygnusx/application/services/mcp_builder_service.py   # 编排中枢
src/cygnusx/application/schemas/mcp_builder.py            # DTO
src/cygnusx/api/v1/mcp_builder.py                         # 15 条路由
src/cygnusx/infrastructure/celery_app/tasks/mcp_builder.py # 过期清理

src/cygnusx/infrastructure/database/models/mcp_builder.py  # 4 个 ORM 模型
alembic/versions/h6i7j8k9l1m3_add_mcp_builder_tables.py    # 迁移

deploy/studio/sandbox_agent.py                    # /mcp/* 容器端点
deploy/studio/requirements-agent.txt              # mcp>=1.2.0
src/cygnusx/infrastructure/studio/manager.py      # host 侧 UDS 封装

tests/unit/mcp/                                   # builder 相关 37 个单测（test_builder_safety.py 19 + test_builder_versioning.py 10 + test_builder_docs_and_generator.py 8）；目录含非 builder 测试共 58 个
tests/unit/test_agent_loader_studio.py            # agent 加载回归测试
```

### 5.10 后续项（设计文档 Phase 2/3 范畴）

| 项 | 基础已就位 | 待做 |
|----|-----------|------|
| 实验 MCP 的 LLM 自动路由 | generation_meta/tools 快照在库 | ChatService 工具发现纳入实验池（按 created_by 过滤） |
| 审核"转正"为正式 MCP | mcp_versions 快照 + review 状态机 | ~~pool experimental→production 提升流程~~ 已实现（`mcp_builder_service.promote_server()`：置 pool=PRODUCTION、清 TTL、打 publish 版本行；API `POST /servers/{id}/promote`，Admin）；待做：前端管理页 |
| 前端页面 | API 完备 | `/admin/mcp-builder`（仪表盘/审核队列/版本对比）、`/studio/mcp-builder`（用户构建历史） |
| 反馈闭环 / 成本管控 | mcp_builds.tokens_consumed | mcp_feedback 表、token_budget_per_user |

---

## 6. 独立 MCP Server（mcp-server/）

### 6.1 用途

面向外部 AI 助手（QoderCN CLI、Claude Desktop）暴露平台能力的独立 FastMCP 服务。

### 6.2 架构

```text
外部 AI 助手
    │ stdio / SSE (port 8900)
    ▼
mcp-server/main.py (FastMCP)
    │
    ├─ tools/ (9 组: tasks, flows, analysis, downloads, files, reports, sandbox, platform, pipelines)
    ├─ resources/ (任务详情、流程信息)
    ├─ prompts/ (分析模板)
    └─ client/api_client.py (httpx → 平台 REST API, X-API-Key 认证)
```

### 6.3 配置

```yaml
# mcp-server/config.yaml
transport: stdio          # stdio | sse
port: 8900
base_url: http://web:8000
tool_groups:
  tasks: true
  flows: true
  analysis: true
  downloads: true
  files: true
  reports: true
  sandbox: true
  platform: true
  pipelines: true
```

---

## 7. 管线 MCP（RNAFlow / ATACFlow）

各管线拥有独立的 FastMCP Server，提供管线专属操作：

```text
pipelines/RNAFlow/mcp/
├── main.py           # FastMCP 入口
├── mcp_config.yaml   # conda 路径、snakemake、host/port
├── services/         # 业务逻辑
└── db/               # 独立数据层

pipelines/ATACFlow/mcp/
├── main.py
├── mcp_config.yaml
├── services/         # project_mgr, snakemake, system
├── models/
└── db/
```

工具示例（ATACFlow）：项目初始化、配置生成、Snakemake 执行、Conda 环境检查、资源监控。

---

## 8. 配置管理汇总

| 配置文件 | 用途 |
|----------|------|
| `src/cygnusx/core/config.py` | 平台级 MCP 开关与超时 |
| `data/ai/*.yaml` | Agent 绑定 `mcp_ids` |
| `data/ai/studio.yaml` | Studio 沙箱配置 |
| `mcp-server/config.yaml` | 独立 MCP Server 配置 |
| `pipelines/*/mcp/mcp_config.yaml` | 管线 MCP 配置 |
| `data/ai/providers.yaml` | AI 模型提供商配置 |
| DB `mcp_servers` 表 | 运行时 MCP 注册信息 |

---

## 9. 前端集成

| 组件 | 文件 | 功能 |
|------|------|------|
| MCP Store | `frontend/src/stores/mcp.ts` | Server CRUD、工具发现、调用 |
| MCP 选择菜单 | `frontend/src/components/.../McpSelectionMenu.vue` | 聊天中附加 MCP Server |
| 工具调用卡片 | `frontend/src/components/.../McpToolCallCard.vue` | 展示工具调用结果 |
| 管理面板 | `frontend/src/components/.../McpResourceTab.vue` | Admin MCP 管理 |

---

## 10. 约束与红线

1. **安全**：生成的 MCP 代码必须通过 AST 检查 + 在 Docker 沙箱内运行，禁止直接在宿主机执行
2. **隔离**：实验性 MCP 仅对创建者可见，不得影响其他用户
3. **生命周期**：实验性 MCP 必须有 TTL，过期自动注销 + 销毁容器
4. **网络**：生成代码的网络访问受 Egress Proxy 白名单约束
5. **依赖**：仅允许沙箱镜像预装的包，禁止运行时 `pip install` 非白名单包
6. **审计**：所有生成/注册/调用/销毁操作记入 `mcp_logs`
7. **回退**：实验 MCP 异常不得影响平台内置 Preset 的正常运行
