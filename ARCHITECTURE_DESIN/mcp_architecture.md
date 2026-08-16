# MCP 架构与自生成框架设计

> **用途**：本文件记录 OmicHub MCP（Model Context Protocol）子系统的完整架构现状，并给出"Agent 自生成 MCP"的可行性分析与实施方案。
>
> **最后更新**：2026-07-29
> **适用范围**：MCP 注册/发现/调用、沙箱隔离、AI 代码生成、实验性 MCP 生命周期管理。

---

## 1. MCP 子系统架构现状

### 1.1 三层 MCP 体系

OmicHub 的 MCP 能力由三层构成：

| 层级 | 说明 | 传输方式 | 延迟 |
|------|------|----------|------|
| 内置 Preset | 平台工具 + 管线工具，进程内执行 | `BUILTIN`（函数调用） | 零延迟 |
| 外部 MCP Server | 独立进程/容器，标准 MCP 协议 | `STDIO` / `SSE` / `STREAMABLE_HTTP` | 网络延迟 |
| 管线专属 MCP | RNAFlow / ATACFlow 各自的 FastMCP 服务 | `SSE`（端口 8900+） | 网络延迟 |

### 1.2 核心代码定位

| 功能 | 文件路径 |
|------|----------|
| Preset 注册与工具定义 | `src/omichub/infrastructure/mcp/presets.py` |
| 管线 Preset（RNA/ATAC） | `src/omichub/infrastructure/mcp/pipeline_preset.py` |
| 统一 MCP 客户端 | `src/omichub/infrastructure/mcp/client.py` |
| 域实体与服务 | `src/omichub/domain/mcp/entities.py`, `services.py`, `repositories.py` |
| 值对象（Transport/Status） | `src/omichub/domain/mcp/value_objects.py` |
| Admin API 路由 | `src/omichub/api/v1/mcp.py` |
| 渐进式能力加载 | `src/omichub/application/services/studio_capabilities.py` |
| 独立 MCP Server | `mcp-server/main.py` + `mcp-server/config.yaml` |
| 数据库模型 | `src/omichub/infrastructure/database/models/` (mcp_servers, mcp_logs 表) |
| 前端 Store | `frontend/src/stores/mcp.ts` |

### 1.3 内置 Preset 工具清单

**omichub-platform**（11 个工具）：

```
platform_list_tasks, platform_get_task, platform_list_flows,
platform_sandbox_execute, platform_read_file,
list_workspace_files, search_workspace_files,
workspace_list_files, workspace_read_file, workspace_get_file_info,
find_session_uploads
```

**omichub-pipelines**（10 个工具）：

```
rna_seq_prepare, rna_seq_submit, rna_seq_status, rna_seq_results,
atac_seq_prepare, atac_seq_submit, atac_seq_status, atac_seq_results,
list_available_pipelines, check_workspace_data
```

**omichub-tools**（动态构建）：从 `tools_schema.yaml` + 启用了 `ai.enabled=True` 的 Flow 配置动态生成。

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
| omichub-tools preset | 部分支持 | 每次 `get_preset_by_name()` 动态构建，新 Flow 自动出现 |
| 外部 MCP Server | 支持 | `MCPClient` 每次调用新建 session，注册后立即可用 |
| Preset 工具定义变更 | 不支持 | 需重启（`ensure_presets()` 仅在启动时同步） |
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

# src/omichub/core/config.py (基础池)
sandbox_default_cpu: 2.0
sandbox_default_memory: "4g"
sandbox_exec_timeout: 300
sandbox_session_timeout: 1800
sandbox_network_isolated: true
```

### 2.4 网络隔离

**模式一：`none`（默认）**
- `network_mode="none"`，容器无任何网络接口
- Agent 通信仍通过 UDS（文件系统，非网络）

**模式二：`whitelist`（当前 studio.yaml 配置）**
- 每会话创建 Docker `internal` 桥接网络（无互联网网关）
- 仅两个容器接入：沙箱 + `omichub-studio-egress-proxy`
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
| qwen3.7-plus | qwen3.7-plus | 阿里云 MaaS |
| deepseek-v4-pro | deepseek-v4-pro | 火山方舟 |
| doubao-seed-2.0-pro | doubao-seed-2.0-pro | 火山方舟 |
| gpt-5.5 | gpt-5.5 | 代理端点 |

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

文件：`src/omichub/infrastructure/execution/langgraph_runtime.py`

---

## 4. Agent 自生成 MCP 可行性分析

### 4.1 现有基础设施覆盖度

| 所需能力 | 现有对应 | 复用度 |
|----------|----------|--------|
| LLM 代码生成 | `ProviderManager.chat_stream()` + LangGraph | 90% |
| 隔离运行环境 | `StudioSandboxManager` / `SandboxPool` | 95% |
| MCP 注册/挂载 | `MCPService` + Admin API + `MCPClient` | 80% |
| 网络安全隔离 | Egress Proxy + network_mode=none | 95% |
| 命令安全验证 | `validate_stdio_command()` | 70% |
| 用户级隔离 | Agent YAML `mcp_ids` + per-user 数据挂载 | 60% |

### 4.2 需要新建的组件

| 组件 | 说明 | 复杂度 |
|------|------|--------|
| AST 静态安全检查器 | 对生成代码做 import/call 级分析，白名单依赖 | 中 |
| 实验性 MCP 池 | DB 增加 `pool` 字段 + TTL 自动注销 | 低 |
| 生成→部署 Pipeline | 编排 LLM 生成 + 安全检查 + 沙箱启动 + 注册 | 中 |
| MCP 健康检查 | 对生成的 MCP 发 `tools/list` 验证可用性 | 低 |
| sandbox_agent MCP 端点 | 容器内启动 MCP Server 子进程并暴露 SSE | 中 |

### 4.3 最大障碍与解法

| 障碍 | 分析 | 解法 |
|------|------|------|
| MCP 进程模型 | 外部 MCP 是 stdio 长驻进程，生成代码需在沙箱内运行 | sandbox_agent 增加 `/mcp/start` 端点，容器内启 SSE Server |
| 热重载 | 注册后是否立即可用 | `MCPClient` 每次调用新建 session，注册即可用，无需热重载 |
| Prompt Injection | 生成的 MCP 可能返回恶意内容 | MCP 输出内容消毒 + 工具结果长度截断 |
| 依赖安装 | 生成代码可能需要白名单外的包 | 沙箱镜像预装白名单包 + 禁止运行时安装 |

### 4.4 有利条件

1. `MCPClient` 无连接池，每次调用新建 session → 新注册的 MCP 无需"热重载"即可使用
2. Studio 沙箱已有完整的容器生命周期管理（创建/健康检查/回收/TTL）
3. Egress Proxy 已实现域名白名单 → 生成代码的网络访问天然受限
4. `omichub-tools` preset 已是动态构建 → 有"运行时发现新工具"的先例
5. Agent YAML 声明式配置 → 新增 `agent-mcp-builder` 无需改代码

---

## 5. 实施方案

### 5.1 分阶段路径

```text
Phase 1 — MVP (约 2 天)
├── 新建 data/ai/mcp_builder.yaml (agent-mcp-builder)
├── studio_tools.py 增加 mcp_generate / mcp_validate 工具
├── 生成代码写入 Studio 沙箱 /workspace/mcp-servers/
└── 用 SandboxPool.stream_execute 验证代码可运行

Phase 2 — 隔离运行 (约 3 天)
├── sandbox_agent.py 增加 POST /mcp/start 端点
│   └── 容器内启动 MCP Server (SSE on 127.0.0.1:动态端口)
├── MCPService.register 增加 pool="experimental" + expires_at 字段
├── Celery beat 定时任务：清理过期实验 MCP
└── MCPClient 支持通过沙箱 UDS 代理连接容器内 SSE

Phase 3 — 安全加固 (约 2 天)
├── AST 静态分析器 (import 白名单 + 危险调用检测)
├── 生成代码结构验证 (必须包含 tools/list, tools/call)
├── MCP 输出内容消毒 (防 prompt injection)
└── 审计日志：记录谁生成了什么 MCP、何时过期
```

### 5.2 Phase 1 关键设计

#### Agent 配置 (`data/ai/mcp_builder.yaml`)

```yaml
agent_id: agent-mcp-builder
name: MCP 构建师
model: deepseek-v4-pro
prompt_file: prompts/mcp_builder.md
temperature: 0.2
features:
  engine: langgraph
tool_packs: [workspace, memory]
studio:
  enabled: true
  default_mode: studio
  runtime_profile: analysis-core
mcp_ids: []
```

#### 新增工具定义

```python
# mcp_generate: 根据自然语言需求生成 MCP Server 代码
{
    "name": "mcp_generate",
    "description": "根据用户需求生成符合 MCP 协议的 Server 代码",
    "parameters": {
        "requirement": "str - 自然语言需求描述",
        "runtime": "str - python | node (默认 python)",
        "tools_spec": "list[dict] - 期望的工具列表 [{name, description, params}]"
    }
}

# mcp_validate: 对生成的代码做安全检查和功能验证
{
    "name": "mcp_validate",
    "description": "验证 MCP Server 代码的安全性和可运行性",
    "parameters": {
        "code_path": "str - 代码文件路径 (相对于 /workspace)",
        "run_test": "bool - 是否实际运行测试 (默认 true)"
    }
}
```

### 5.3 Phase 2 关键设计

#### sandbox_agent 新增端点

```python
# deploy/studio/sandbox_agent.py 新增

@app.post("/mcp/start")
async def start_mcp_server(request: MCPStartRequest):
    """在沙箱容器内启动 MCP Server 子进程"""
    # 1. 验证代码路径在 /workspace 内
    # 2. 分配动态端口 (9100-9199)
    # 3. 启动子进程: python server.py --transport sse --port {port}
    # 4. 等待 /tools/list 健康检查通过
    # 5. 返回 {"port": port, "tools": [...]}

@app.post("/mcp/stop")
async def stop_mcp_server(request: MCPStopRequest):
    """停止指定的 MCP Server 子进程"""

@app.get("/mcp/list")
async def list_mcp_servers():
    """列出容器内运行中的 MCP Server"""
```

#### 数据库扩展

```sql
ALTER TABLE mcp_servers
  ADD COLUMN pool VARCHAR(20) DEFAULT 'production',   -- production | experimental
  ADD COLUMN expires_at TIMESTAMP NULL,               -- 实验 MCP 过期时间
  ADD COLUMN created_by UUID REFERENCES users(id),    -- 创建者
  ADD COLUMN generation_meta JSON NULL;               -- 生成元数据 (prompt, model, safety_report)
```

### 5.4 AST 静态安全检查器设计

```python
class StaticSafetyChecker:
    """基于 Python AST 的代码安全分析"""

    FORBIDDEN_IMPORTS = {
        'subprocess', 'ctypes', 'pickle', 'marshal',
        'importlib', 'socket', 'shutil', 'signal',
        'multiprocessing', 'threading'
    }

    FORBIDDEN_CALLS = {
        'eval', 'exec', 'compile', 'open',
        'os.system', 'os.popen', 'os.exec',
        '__import__'
    }

    ALLOWED_PACKAGES = {
        'mcp', 'pydantic', 'json', 're', 'datetime',
        'typing', 'collections', 'itertools', 'math',
        'hashlib', 'base64', 'uuid', 'string', 'pathlib',
        'httpx', 'requests'  # 受 egress proxy 白名单约束
    }

    def analyze(self, code: str) -> SafetyReport:
        """返回: passed, violations[], warnings[], dependencies[]"""
```

### 5.5 完整部署流水线

```text
用户需求 (自然语言)
    │
    ▼
┌─────────────────────────────────────┐
│ 阶段 1: 代码生成                      │
│   ProviderManager.chat_stream()      │
│   model=deepseek-v4-pro, temp=0.2    │
│   输出: 完整 MCP Server 代码          │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ 阶段 2: 静态安全检查                  │
│   AST 分析 → 白名单依赖              │
│   结构验证 → tools/list, tools/call  │
│   标记验证 → __exp_mcp_generated__   │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ 阶段 3: 沙箱部署                      │
│   写入 /workspace/mcp-servers/       │
│   sandbox_agent /mcp/start           │
│   容器内 SSE Server 启动             │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ 阶段 4: 健康检查                      │
│   GET /tools/list → 验证工具列表      │
│   调用每个 tool 的 dry-run            │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ 阶段 5: 注册挂载                      │
│   MCPService.register(               │
│     pool="experimental",             │
│     expires_at=now+TTL,              │
│     visibility={users: [requester]}  │
│   )                                  │
│   → MCPClient 立即可调用             │
└─────────────────────────────────────┘
```

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
| `src/omichub/core/config.py` | 平台级 MCP 开关与超时 |
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
