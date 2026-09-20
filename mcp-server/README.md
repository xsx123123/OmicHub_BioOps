# CygnusX / OmicHub 平台 MCP 能力总览与架构

> 本文汇总平台两套 MCP 接口的 **Prompts / Tools / Resources** 全量清单，并详述 MCP 架构。
> 扩展指南见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

平台的 AI 能力通过 **两套互补的 MCP 接口** 对外/对内提供：

| | 外部 MCP Server（本目录 `mcp-server/`） | 内部 MCP Preset（`src/cygnusx/infrastructure/mcp/`） |
|---|---|---|
| 消费者 | 第三方 AI 助手（QoderCN CLI、Claude Code 等，经 MCP 协议接入） | 平台内置 AI（Copilot / Studio / 协作室，经 LangGraph runtime） |
| 实现 | FastMCP（Python），stdio / SSE 传输 | builtin transport，进程内 handler 直调 application services |
| 数据来源 | 平台 REST API（`X-API-Key` 认证，httpx 客户端） | 直接 import 服务层，零网络开销 |
| Prompts | ✅ 5 个工作流引导 prompt | ❌ 无（仅 tools + 系统提示后缀） |
| Resources | ✅ 4 个只读资源 URI | ❌ 无 |
| Tools | ✅ 9 组共 40 个 | ✅ 平台 22 + 流水线 10 + 工具箱（动态） |

两套接口对重叠能力**同名对齐**（`list_workspace_files` / `search_workspace_files` / `rna_seq_*` / `atac_seq_*` / `check_workspace_data` / `list_available_pipelines`），保证内外双端同能力同名。

---

## 一、外部 MCP Server 能力清单

### 1.1 Tools（9 组 40 个）

返回格式统一为 `{"success": bool, "summary": str, "data": Any, "next_steps"?: list[str]}`；
破坏性操作均有 `user_confirmed: bool = False` 确认门——未确认时返回待确认摘要而不执行。

#### 📋 tasks — 任务管理（`tools/tasks.py`，6 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_list_tasks(status="")` | 列出用户分析任务，可按 pending/queued/running/success/failed/cancelled 过滤 | ✅ |
| `cygnusx_get_task(task_id)` | 任务详情：状态、进度、参数、时间、错误信息 | ✅ |
| `cygnusx_get_task_progress(task_id)` | 当前进度百分比和状态（轮询用） | ✅ |
| `cygnusx_get_task_logs(task_id, lines=50)` | 最近 N 条执行日志（clamp 到 `limits.max_log_lines`） | ✅ |
| `cygnusx_cancel_task(task_id, user_confirmed)` | 取消运行/排队中的任务 | ❌ 需确认 |
| `cygnusx_get_task_dag(task_id)` | Snakemake DAG 工作流图（DOT 文本） | ✅ |

#### 🧭 flows — 流程目录（`tools/flows.py`，3 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_list_flows(category="")` | 列出可用分析流程，可按 rna_seq/atac_seq/scrna 等类别过滤 | ✅ |
| `cygnusx_get_flow_detail(flow_id)` | 流程详情：描述、参数列表、样本表定义、执行配置 | ✅ |
| `cygnusx_get_flow_parameters(flow_id)` | 参数 JSON Schema（类型、默认值、约束） | ✅ |

#### 🚀 analysis — 分析提交（`tools/analysis.py`，2 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_submit_analysis(flow_id, name, parameters, sample_sheet, comparisons, user_confirmed)` | 提交分析任务；复杂流程建议改走 `*_prepare`/`*_submit` 预检通道 | ❌ 需确认 |
| `cygnusx_preview_analysis(flow_id, parameters, ...)` | 参数验证 dry-run | ✅ |

#### ⬇️ downloads — 数据下载（`tools/downloads.py`，3 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_submit_download(source, accession, download_method, ...)` | 提交下载，产物落 `raw_data`。三类来源：`sra`（SRA/GEO 登录号，aws/aspera/ftp 高速通道，支持 `dry_run` 试验）、`cloud_storage`（aliyun `oss://` / volc `tos://` / huawei `obs://`）、`direct_link`（HTTP/HTTPS/FTP 批量直链，禁内网地址） | ❌ 需确认 |
| `cygnusx_list_downloads()` | 列出下载任务（名称、状态、进度、产物目录） | ✅ |
| `cygnusx_get_download_progress(task_id)` | 逐 run 分阶段进度（下载/解压/压缩） | ✅ |

#### 📁 files — 文件浏览（`tools/files.py`，7 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `list_workspace_files(path="", pattern="")` | 列当前用户工作区目录（与内部 preset 同名） | ✅ |
| `search_workspace_files(query, limit=50)` | 递归按文件名模糊搜索（与内部 preset 同名） | ✅ |
| `cygnusx_list_files(directory="")` | 列出用户文件，可按目录过滤 | ✅ |
| `cygnusx_get_file_tree()` | 完整文件树（按来源分组 upload/download/pipeline） | ✅ |
| `cygnusx_list_directories()` | 列出所有目录 | ✅ |
| `cygnusx_get_task_outputs(task_id)` | 已完成任务的输出文件列表 | ✅ |
| `cygnusx_read_file_content(file_path, max_lines=50)` | 读文本文件前 N 行（clamp 到 `limits.max_file_preview_lines`） | ✅ |

#### 📄 reports — 报告（`tools/reports.py`，3 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_list_reports(flow_id="", keyword="")` | 列出报告，可按流程/关键词过滤 | ✅ |
| `cygnusx_get_report(report_id)` | 报告详情：标题、流程、文件列表、创建时间 | ✅ |
| `cygnusx_get_report_content(report_id)` | 报告 HTML 主文件内容 | ✅ |

#### 🧪 sandbox — 沙箱执行（`tools/sandbox.py`，4 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_sandbox_create(language="python")` | 创建/复用沙箱会话（mambaforge 环境，预装 scanpy/anndata/pandas/matplotlib 等） | ❌ |
| `cygnusx_sandbox_execute(code, session_id="", timeout=300)` | 执行代码（timeout clamp 到 `limits.sandbox_timeout`） | ❌ |
| `cygnusx_sandbox_list()` | 列出会话 | ✅ |
| `cygnusx_sandbox_destroy(session_id)` | 销毁会话 | ❌ |

#### 🏛️ platform — 平台信息（`tools/platform.py`，2 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `cygnusx_get_user_info()` | 当前用户信息与存储配额 | ✅ |
| `cygnusx_get_platform_status()` | 平台概览：任务统计、可用流程、存储 | ✅ |

#### 🔗 pipelines — 完整分析流水线（`tools/pipelines.py`，10 个，与内部 preset 同名对齐）

四段式 **prepare → submit → status → results**：

| 工具 | 说明 | 只读 |
|---|---|---|
| `rna_seq_prepare(raw_data_path, species, genome_version, sample_sheet, comparisons, library_type, project_name, extra_parameters)` | RNA-seq 参数与工作区数据预检，返回可提交的 `prepared_params` | ✅ |
| `rna_seq_submit(prepared_params)` | 提交经预检的 RNA-seq 任务 | ❌ |
| `rna_seq_status(task_id)` / `rna_seq_results(task_id, ...)` | 状态查询 / 结果摘要、差异基因统计与产物清单 | ✅ |
| `atac_seq_prepare(...)` / `atac_seq_submit(...)` / `atac_seq_status(...)` / `atac_seq_results(...)` | ATAC-seq 同构四段式 | 同上 |
| `list_available_pipelines()` | 列出当前可经 MCP 调用的完整流程 | ✅ |
| `check_workspace_data(analysis_type, data_path)` | 检查工作区数据完整性 | ✅ |

### 1.2 Resources（`resources/catalog.py`，4 个）

只读数据源，供 AI 助手直接订阅读取，错误以 `{"error": ...}` JSON 返回而非抛异常：

| URI | 说明 |
|---|---|
| `cygnusx://flows/catalog` | 所有可用分析流程的 JSON 目录 |
| `cygnusx://user/storage` | 用户存储配额 + 目录结构 |
| `cygnusx://tasks/{task_id}/outputs` | 指定任务的输出信息（status / work_dir / result_path） |
| `cygnusx://reports/{report_id}` | 报告元数据 |

### 1.3 Prompts（`prompts/workflows.py`，5 个）

预置工作流引导模板，注入后 AI 按步骤调用上述 tools：

| Prompt | 参数 | 引导内容 |
|---|---|---|
| `new_analysis` | `flow_id="rna_seq"` | 看流程详情 → 查文件 → 配参数 → preview 验证 → 确认提交 → 轮询进度 → 查结果，每步向用户确认 |
| `interpret_results` | `task_id` | 确认完成 → 取输出 → 读 DEG 表/QC 报告/计数矩阵 → 总结显著差异基因、上下调比例 → 建议富集方向 |
| `optimize_in_sandbox` | `task_id` | 先 `find` 探明实际结果文件（勿臆测路径）→ pandas 读取 → 调阈值/火山图/热图/GO-KEGG → 发表级图表 |
| `download_and_analyze` | `accession, flow_id="rna_seq"` | 提交下载 → 监控进度 → 查 `raw_data` → 配参分析 → 监控 → 解读 |
| `troubleshoot_task` | `task_id` | 查状态与错误 → 拉日志 → 分类归因（内存/参考基因组/样本表/conda）→ 修复建议与重提交 |

---

## 二、内部 MCP Preset 能力清单

声明于 `src/cygnusx/infrastructure/mcp/`，以 `PRESET_SERVERS`（`transport="builtin"` + `tools` + `handlers`）形式由 `mcp_service.ensure_presets()` 以 uuid5 确定性种子化入库。**只有 tools，没有 prompts/resources**；唯一"提示"形态是 `WORKSPACE_FILES_SYSTEM_PROMPT_SUFFIX`（外置 `data/ai/mcp/workspace_files_prompt.md`）注入系统提示。

### 2.1 `cygnusx-platform`（presets.py，22 个）

| 分组 | 工具 | 说明 | 副作用 |
|---|---|---|---|
| 文献 | `europe_pmc_search` | Europe PMC 检索 + 语义重排（不下载全文） | 只读 |
| 文献 | `arxiv_search` | arXiv 预印本检索 | 只读 |
| 任务 | `platform_list_tasks` / `platform_get_task` / `platform_list_flows` | 任务与流程查询 | 只读 |
| 账户 | `platform_get_user_info` | 账户、饼干（积分）余额、存储配额 | 只读 |
| 账户 | `platform_get_current_time` | 服务器时间/时区 | 只读 |
| Agent | `platform_list_agent_skills` | Agent 绑定的 Skill 列表 | 只读 |
| Agent | `ability_catalog_query` | 平台 Agent 能力目录查询（summary/detail 层） | 只读 |
| 协作室 | `room_state_query` | 当前协作室状态（标题/立项/待确认提案） | 只读 |
| 运维 | `platform_admin_health_check` | DB/Redis/存储/任务分布巡检 | 只读，需管理员 |
| 执行 | `platform_sandbox_execute` | 沙箱执行 Python/R/Bash（mambaforge） | 起沙箱会话 |
| 文件 | `list_workspace_files` / `search_workspace_files` / `workspace_read_file` / `workspace_get_file_info` / `workspace_list_files`(兼容) / `find_session_uploads` / `platform_read_file` | 工作区文件列举/搜索/按 file_id 读文本与 PDF 预览（≤5MB）/会话上传查询 | 只读 |
| 下载 | `platform_submit_download` | SRA/GEO、多云对象存储、直链三类下载；**要求先经 ask_user 确认**登录号与目录 | 写 |
| 下载 | `platform_list_downloads` / `platform_get_download_progress` | 下载任务与逐 run 进度 | 只读 |

### 2.2 `cygnusx-pipelines`（pipeline_preset.py，10 个）

与外部 `tools/pipelines.py` 完全同名对齐（见 §1.1 pipelines 表）；handler 要求携带 `ToolInvocationContext`（用户上下文），否则拒绝执行。prepare 返回 UI 预检卡。

### 2.3 `cygnusx-tools`（presets.py 动态构建）

生信工具箱，**清单非硬编码**：静态工具来自 `tools_schema.yaml`（KEGG 富集、火山图、系统发育树绘制等）+ 每个 `ai.enabled` 的 Flow 动态编译出 `<flow>_prepare` / status / summary 工具；全部经 `ToolBridgeService.execute()` 统一分发。

### 2.4 `conda-meta-mcp`（conda_meta_preset.py）

非 builtin，是 stdio 种子配置（conda-forge `cmm run`），供沙箱装包前查 conda 元数据：`package_search`、`import_mapping`/`pypi_to_conda`、`repoquery`（depends/whoneeds）、`file_path_search`，全只读。Studio 默认加载（`studio_capabilities.py`），镜像无 `cmm` 时优雅跳过。

---

## 三、MCP 架构详解

### 3.1 总体拓扑

```
┌────────────────────────┐      ┌─────────────────────────────┐
│  外部 AI 助手           │      │  平台内置 AI                 │
│  QoderCN CLI / Claude…  │      │  Copilot / Studio / 协作室   │
└──────────┬─────────────┘      └──────────────┬──────────────┘
           │ MCP (stdio / SSE)                  │ 进程内函数调用
           ▼                                    ▼
┌─────────────────────────┐    ┌──────────────────────────────────┐
│ mcp-server/ (FastMCP)    │    │ MCPClient (infrastructure/mcp/    │
│  main.py                 │    │  client.py, transport=builtin)    │
│  ├ tools/  ×40  (9 组)   │    │  ├ cygnusx-platform   ×22        │
│  ├ resources/ ×4         │    │  ├ cygnusx-pipelines  ×10        │
│  └ prompts/   ×5         │    │  ├ cygnusx-tools      (动态)      │
│           │              │    │  └ conda-meta-mcp     (stdio 子进程)│
│           ▼              │    └───────────────┬──────────────────┘
│  CygnusXAPIClient (httpx)│                    │ handler 直调
└───────────┬─────────────┘                    │
            │ REST + X-API-Key                 ▼
            ▼                     ┌───────────────────────────┐
┌──────────────────────────────────────────────────────────────┐
│  CygnusX 平台后端 (FastAPI, src/cygnusx/)                      │
│  api/v1 → application/services → domain                        │
│  TaskService · FlowService · DownloadService · FileService ·    │
│  ReportService · SandboxService · PipelineController ·          │
│  ToolBridgeService · MCPService                                 │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 外部 Server 分层（本目录）

| 层 | 文件 | 职责 |
|---|---|---|
| 入口 | `main.py` | 创建 `FastMCP(name, instructions)`，依次注册 tools/resources/prompts；解析 `--transport/--port`；启动前校验 API Key 与 SSE 绑定风险 |
| 配置 | `core/config.py` + `config.yaml` | 三级优先级：**环境变量 `CYGNUSX_*` > config.yaml > 代码默认值**；`tool_groups` 整组开关 |
| 声明 | `tools.yaml` | 声明式工具注册表（名称/描述/read_only/requires_confirm），供文档与校验；运行时注册由 `tools/__init__.py` 的 `_GROUP_REGISTRY` 驱动 |
| 工具 | `tools/<group>.py` | 每组导出 `register(mcp, api)`；`register_all_tools()` 按开关注入式 `importlib` 加载，禁用组不产生任何 MCP 暴露 |
| 资源 | `resources/catalog.py` | `@mcp.resource("cygnusx://…")` 只读 JSON 数据源 |
| 提示 | `prompts/workflows.py` | `@mcp.prompt()` 纯文本工作流模板（无 IO） |
| 客户端 | `client/api_client.py` | httpx 异步封装：`_request` 统一注入 `X-API-Key`、错误归一化为 `CygnusXAPIError`；按平台路由提供 ~30 个语义方法 |

**请求数据流**：AI 助手 → MCP `tools/call` → FastMCP 路由到工具函数 → `api.<method>()` → 平台 REST `/api/v1/*` → 服务层 → 结果裁剪（limits clamp）→ 统一 `{success, summary, data, next_steps}` 返回。

### 3.3 内部 Preset 执行机制

- **注册/种子化**：preset 以 `PRESET_SERVERS` 声明（name/description/transport/tools/handlers），`ensure_presets()` 用 uuid5 确定性 ID 写入数据库并同步工具注册表 → 平台的 MCPServer 实体可被 Agent 绑定并配置工具白名单。
- **handler 直调**：builtin 工具的 handler 进程内直接 import application services（TaskService/SandboxService/FlowService/DownloadService…），按需自开 DB session，零 HTTP/序列化开销。
- **MCPClient 路由**（`client.py`，601 行）：统一路由 builtin / stdio / sse / streamable_http 四种 transport。builtin 经 `get_preset_by_name()` 查 preset，用 `inspect.signature` 按 handler 声明注入 `user_id / tool_name / context`；外部 transport 走 Python MCP SDK，带**长活会话复用池**（按 server 缓存 ClientSession、per-server 锁串行、空闲 300s 回收、fingerprint 变更重建），并做 stdio 命令与 SSE URL 安全校验。
- **可靠性**（`reliability.py`）：进程内健康 registry + 熔断（连续 3 次失败 → degraded，冷却后半点试探）+ 重试退避（1/3/5s）+ 失败按 `fallback_servers` 回落到同名 builtin 工具或本地兜底计算。
- **文件引用解引用**（`workspace_file_refs.py`）：调用前递归解析参数中的 `file://{uuid}` 引用，在用户权限约束下替换为文本内容（≤5MB）；`file_id` 等标识符键保留原值。
- **LangGraph 衔接**（`application/services/chat/runtimes/langgraph_runtime.py`）：runtime 持有 `active_mcp_servers`（Agent 绑定的 MCPServer + 工具白名单）与 `mcp_client`；`_tool_executor` 按工具名匹配 server 后 `call_tool(server, tool, args, user_id, context=ToolInvocationContext)`。handoff / ask_user / knowledge_search / web_search / skills / chat-sandbox 先于 MCP 路由被特判；chat_sandbox 走审批闸。
- **AI 自生成 MCP Server**（`builder/`，与 preset 无关的独立框架）：safety（AST import 白名单 + 危险调用门禁）、versioning（SemVer）、generator（LLM 生成 FastMCP 代码）、doc_generator（构建报告）。

### 3.4 内外双端对齐

```
外部 tools/pipelines.py  ──同名──  内部 pipeline_preset.py  ──调用──  PipelineController
外部 tools/files.py      ──同名──  内部 cygnusx-platform 文件类工具  ──调用──  FileService
外部 tools/downloads.py  ──同名──  内部 platform_submit_download 等            DownloadService
外部 tools/sandbox.py    ──对应──  内部 platform_sandbox_execute               SandboxService
```

新增内部工具时须同步更新 `PLATFORM_PRESET_TOOLS` 与 `PLATFORM_HANDLERS`；新增外部工具按 ARCHITECTURE.md 的三步流程（模块 → `_GROUP_REGISTRY` → config.yaml + tools.yaml）。

### 3.5 设计约定

| 约定 | 说明 |
|---|---|
| 工具命名 | `cygnusx_<group>_<action>` 全小写下划线；与内部 preset 对齐的工具沿用内部命名 |
| 确认门 | 破坏性操作（提交/取消/删除/下载）必须有 `user_confirmed` 参数，未确认时返回待确认摘要 |
| 返回格式 | `{"success", "summary", "data", "next_steps"?}`，错误捕获为 `{"success": false, "summary": "…"}` |
| 输出上限 | 文件行数 / 日志条数 / 沙箱超时均 clamp 到 `limits.*`（默认 50 行 / 100 条 / 300 秒），防上下文爆炸 |
| 幂等只读 | 所有只读工具可安全重试；轮询类（progress/status）为轻量端点 |

### 3.6 安全模型

- **认证**：外部 server 所有请求经 `X-API-Key` 头访问平台 API，Key 由 `api_client.py` 统一注入；Key 经平台 `/api/v1/auth/api-keys` 创建（仅显示一次），建议用环境变量 `CYGNUSX_API_KEY` 传入，不落版本控制。
- **传输**：stdio（默认，本机 CLI）无网络面；SSE 模式**本身无鉴权**——绑定 `0.0.0.0` 时任何可达端口者可复用本服务的 API Key，仅限可信内网，公网前置带鉴权的反向代理或改绑 `127.0.0.1`（启动时自动告警）。
- **数据边界**：所有文件/任务/下载操作均隐式限定在 API Key 所属用户工作区内；直链下载禁内网地址；资源读取错误不泄露堆栈。
- **内部侧**：pipeline preset handler 强制 `ToolInvocationContext` 用户上下文；builder 框架 AST 白名单限制自生成代码可 import 的模块。

### 3.7 运行与部署

```bash
# 依赖: Python >= 3.11, fastmcp/httpx/pydantic/loguru（uv 管理）
cd mcp-server
uv sync

# stdio（默认，CLI 助手用）
uv run python main.py                     # 或 ./start.sh

# SSE（远程访问，注意 §3.6 风险）
uv run python main.py --transport sse --port 8900

# 独立流水线 server（仅 pipelines 组）
uv run python pipelines_main.py
```

AI 助手接入配置（QoderCN CLI / Claude Code 的 `mcpServers` 片段、SSE URL 形式、API Key 创建步骤）见 [mcp_config_example.jsonc](./mcp_config_example.jsonc)。

工具组开关：`config.yaml` 的 `tool_groups.<group>: false` 即可整组下线（如关闭 `sandbox` 或 `analysis` 收敛写操作面）。
