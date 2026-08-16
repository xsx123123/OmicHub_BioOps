# OmicStudio（AI 分析工作台）实施进度与交接文档

> 更新时间：2026-07-17
> 设计依据：`docs/26.7.17/OmicHub_AI分析工作台_架构设计.md`（下称「架构文档」）
> 本文档面向接手开发者：完整记录已完成内容、关键设计决策、接口契约、验证状态与待办事项。

---

## 〇、总览

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P0 骨架（沙盒 + 工具 + 三栏工作台） | ✅ 完成并验证 | 端到端真机验证通过 |
| P1 平台联动 - 后端 | ✅ 完成并验证 | 5 个新工具 + Context Packager + 版本树 + plan 事件 |
| P1 平台联动 - 前端 | ✅ 完成并验证 | 文件引入、报告中心入口、保存新版本、待办面板、登记结果卡片 |
| P1 遗留小后端 | ✅ 完成并验证 | 用户侧「数据管理引入」REST 端点（见 §5.1） |
| P2 体验与规模化 | ✅ 完成并验证 | diff 回滚、预览、长任务、跨进程回收、预热、安全控制面、背压、网络隔离及 MCP/Skills 渐进式披露均完成 |
| P3 打磨 | ✅ 已完成 | 知识库联动、会话分享/导出、管理员「提炼为 Skill」、用量与存储配额统计均已接入 |

**与架构文档的三处关键偏离（均为有意决策）：**

1. **无 Docker Swarm**：仓库实际为 plain docker SDK（参考既有 `infrastructure/sandbox/pool.py`），沙盒容器按 `docker run` 管理，不是 Swarm service。
2. **前端是 naive-ui + CodeMirror 6**，不是文档假设的 Arco Design + Monaco。所有 UI 按 naive-ui 实现。
3. **聊天流式用 SSE（POST + fetch ReadableStream）**，不是 WebSocket。Studio 复用既有 `/chat/stream` SSE 通道扩展事件类型，未新增 WS。

---

## 一、P0 已完成内容（骨架）

### 1.1 沙盒镜像与 sandbox-agent

| 文件 | 说明 |
| --- | --- |
| `deploy/studio/sandbox_agent.py` | 容器内自包含 FastAPI 服务（仅依赖 fastapi/uvicorn/pydantic），非 root uid=10001，工作目录 `/workspace` |
| `deploy/studio/requirements-agent.txt` | agent 依赖清单 |
| `deploy/studio/base.Dockerfile` | `python:3.12-slim` + pandas/numpy/matplotlib/plotly/seaborn/scikit-learn/scipy/statsmodels/openpyxl/pyarrow + sandbox-agent |
| `deploy/studio/bio.Dockerfile` | FROM base + scanpy/anndata/pysam/bioinfokit + blast/samtools/bedtools/seqkit |
| `deploy/studio/build.sh` | 构建脚本（先 base 后 bio） |

**镜像已在本机构建**：`omichub-sandbox:base`、`omichub-sandbox:bio`（均已真机拉起验证）。

sandbox-agent 端点（容器内工作区 Unix Socket `/workspace/.agent.sock`，HTTP over UDS）：

- `GET /healthz`
- `POST /exec` `{language: python|r|bash, code, timeout?}` → NDJSON 流：`{"type":"stdout"|"stderr","data"}` + 终止 `{"type":"result","exit_code","duration_ms","artifacts":[{path,size,mtime}],"timed_out"?,"truncated_output_files"?}`。artifacts = `/workspace/output` 下新增/修改文件。单通道流内上限 10KB，溢出写 `/workspace/.logs/exec-<id>.{stdout,stderr}.log`；超时整进程组 SIGKILL。
- `GET /files/list?path=` → `{path, entries:[{name,type:file|dir,size,mtime}]}`
- `GET /files/read?path=&offset=0&limit=200` → `{content,total_lines,truncated}`（limit ≤ 2000）
- `POST /files/write` `{path, content}`；`POST /files/edit` `{path, old_string, new_string}` → `{path, diff, size, reverse_edit?}`（old_string 须唯一出现；reverse_edit 为可唯一命中的反向替换上下文）
- 路径防护：realpath 必须落 `/workspace`；**P1 起读路径放宽**（见 §2.4），写路径仍然严格。

### 1.2 StudioSandboxManager

`src/omichub/infrastructure/studio/manager.py`，模块级单例 `studio_sandbox_manager`，异常 `StudioSandboxUnavailableError`。

- `SandboxHandle(session_id, container_id, container_name, agent_url, agent_socket, image, workspace_dir)`（`agent_url` 为兼容字段，实际请求经工作区 UDS）
- `async ensure_running(session_id, image=None, user_id=None) -> SandboxHandle`：懒启动/复用；容器名 `studio-{session_id[:8]}`；agent 通过工作区 UDS 访问，不发布端口、不依赖沙盒网络；**`/healthz` 经 UDS 轮询就绪后才放行**；挂载见 §2.4。网络模式见 §5.3。
- `async exec(session_id, language, code, timeout_sec=None, image=None, user_id=None) -> AsyncIterator[dict]`（NDJSON 事件）
- `list_files / read_file / write_file / edit_file`（均可选 `user_id`）
- `async status(session_id)` → `running/stopped/absent/unavailable`（只读探测，不触发懒启动）
- `async stop(session_id)` / `async recycle_idle()`（Redis ZSET 跨 web/celery 记录 last_activity，空闲 30min）
- 每次代码执行与文件 API 请求持有独立 Redis 租约，避免长任务/并发请求被回收；Redis 不可用时降级进程内记录
- 会话创建后可后台预热专属容器（`session.prewarm_on_create`）；由于 per-user bind mount 在 plain Docker 中不可安全重绑，不复用跨用户通用 standby
- `workspace_dir(session_id) -> Path`（含 session_id 逃逸防护）；`static ensure_workspace_dirs(Path)`（预建 input/output/ref/.logs，chown 10001 → chmod 0777 兜底）

**已修复的三个真实 bug（P0 验证时发现）：**

1. `containers.run()` 返回的 attrs 是创建时快照，需 `container.reload()` 才拿得到 IP。
2. 容器进程就绪 ≠ agent 已监听，曾出现 ConnectError 竞态 → 加 `/healthz` 轮询（30s 超时）。
3. `tool_output` 事件原先不带 `tool_call_id`，并行同名工具输出会串卡 → 已补上（前后端均已适配）。

**网络安全契约（已落地）**：默认 `none` 使用 Docker `network_mode=none`，沙盒完全断网；`whitelist` 使用每会话 Docker `internal` 网络，仅连接沙盒与独立出站代理。代理按 `data/ai/studio.yaml` 热加载精确域名/子域名白名单，只允许 HTTP 80 与 HTTPS CONNECT 443，拒绝 IP 字面量、通配符、私网/保留地址，并在代理侧解析后固定公网 IP，防止 DNS rebinding。Manager 校验网络只挂载预期端点，失败关闭并清理临时网络。Redis 不可用时活跃态降级为进程内记录，多副本部署需确保 Redis 可用。

### 1.3 配置

- `data/ai/studio.yaml`：`studio.enabled`、`default_image: omichub-sandbox:bio`、`session.idle_ttl_minutes: 30`、`session.workspace_retention_days: 7`、`sandbox.cpu: 2 / memory: 4g / exec_timeout_seconds: 600`、`sandbox.network.mode: none|whitelist`、`sandbox.network.docker_network: omichub-studio-egress`（每会话网络前缀）、代理容器/别名/端口及 `allow` 域名列表、`mounts.workspace: "{storage_path}/studio"`（加载时解析为 `settings.storage_path` 下）、`session.prewarm_on_create`、`images.base/bio/full`、`tools.builtin`（10 个工具清单）。默认配置 `mode: none`，白名单模式需显式配置非空 `allow`。
- `src/omichub/core/config.py`：Worker 默认调用 `http://web:8000/api/v1/studio/internal`；控制 token 可由 `STUDIO_CONTROL_TOKEN` 显式提供，未提供时从 `APP_SECRET_KEY` 以 HMAC-SHA256 域隔离派生，不直接复用应用密钥。
- `src/omichub/infrastructure/config/studio_loader.py`：`StudioConfig` pydantic 模型 + mtime 热重载，`get_studio_config()` / `studio_config_manager`。
- `src/omichub/core/config.py` 新增 `studio_config_yaml: str = "data/ai/studio.yaml"`。
- 5 个智能体 yaml（`data/ai/{general,code,viz,rnaseq,shania}.yaml`）已追加 `studio: {enabled: true, image: ...}` 段（viz/general/code→base，rnaseq/傻妞→bio）。`agent_loader.py` 解析该段；`agent_service.ensure_builtin_agents` 写入 `features["studio"]`（**注意：既有同步逻辑对已有 agent 跳过，studio 段只对首次落库生效**；但 Studio 会话创建对未声明 agent 默认开放，显式 `enabled: false` 才拒绝）。

### 1.4 数据库迁移（均已应用到本地 dev DB）

| revision | 内容 |
| --- | --- |
| `u9v0w1x2y3z4` | `chat_sessions` 加 `mode`(String16, default 'chat', index)、`workspace_id`(String64)、`sandbox_meta`(JSONB) |
| `v0w1x2y3z4a5`（当前 head） | `reports` 加 `parent_id`(UUID FK→reports.id, SET NULL, index)、`version`(Integer, default 1) |

容器环境 entrypoint 会自动 `alembic upgrade head`（`RUN_MIGRATIONS=1`），部署新镜像后自动生效。

### 1.5 Studio 内置工具（10 个）

`src/omichub/application/services/studio_tools.py`：`STUDIO_TOOL_SCHEMAS` / `STUDIO_TOOL_NAMES` / `execute_studio_tool(name, args, session_id, image=None, on_output=None, *, user_id=None, db=None)` / `stream_studio_tool(..., tool_call_id="", *, user_id=None, db=None)`。

| 工具 | 阶段 | 说明 |
| --- | --- | --- |
| `sandbox_execute` | P0 | `{language, code, timeout?}`，stdout/stderr 边跑边推 `tool_output` 事件；llm_payload 尾部截断（stdout≤2000/stderr≤1000）+ artifacts |
| `workspace_write` | P0 | `{path, content}` |
| `workspace_edit` | P0 | `{path, old_string, new_string}`，ui_payload 含完整 unified diff |
| `workspace_read` | P0 | `{path, offset?, limit?}`，默认前 200 行 |
| `workspace_list` | P0 | `{path?}` |
| `datahub_import` | P1 | `{file_id, name?}` → 建 `/workspace/input/<name>` 软链（见 §2.4），校验文件归属与 active 状态 |
| `platform_result_import` | P1 | `{report_id}` → 把报告产物软链进既有会话 |
| `artifact_register` | P1 | `{path, title, type?, description?}` → 登记为结果报告（版本树，见 §2.3） |
| `update_plan` | P1 | `{steps:[{title, status: pending\|in_progress\|done}]}`，被 chat_service 拦截，发 `plan` 事件（见 §2.5） |
| `pipeline_query` | P1 | `{query?}` → 平台流程/工具目录摘要（≤6KB） |

工具结果双通道：`llm_payload`（进模型上下文，紧凑）/ `ui_payload`（进前端，含完整 diff/artifacts/stdout）。失败返回 `success: false` + 友好文案，不中断 LLM 闭环。每次工具调用持久化到 `ChatMessageModel.metadata_json["tool_invocations"]`（含 arguments/result/ui_payload，历史重载可渲染代码卡片）。

### 1.6 Agent Runner 集成

`chat_service.py` `stream_agent_chat`（全部 additive，非 studio 会话行为逐字节不变）：

- 会话 `mode == "studio"`（或新建时显式 `mode="studio"`）时：`tools.extend(STUDIO_TOOL_SCHEMAS)`、system_prompt 追加 `STUDIO_SYSTEM_PROMPT_SUFFIX`（中文，含沙盒环境、/workspace 布局、先落盘再执行、产物放 output/、update_plan 规则等）、镜像取 `sandbox_meta.image`。
- studio 工具优先路由到 `stream_studio_tool`，`mcp_server` 字段为 `"studio"`。
- `sandbox_meta.context_pack` 存在时，在其后再追加 `render_context_pack_hint()`（P1）。

### 1.7 SSE 事件协议（`/api/v1/chat/stream`，`data: {json}` 行）

既有类型：`text`（含 `is_reasoning`）、`tool_call`、`tool_result`、`error`、`done`。
Studio 新增：

```
{"type":"tool_output","content":"","tool":"sandbox_execute","tool_call_id":"call_x","stream":"stdout"|"stderr","data":"...增量"}
{"type":"plan","content":"","tool_call_id":"...","steps":[{"title":"加载数据","status":"in_progress"},...]}
```

`tool_call`/`tool_result` 形状：`{type, content:"", tool_call_id, tool_name, arguments, mcp_server:"studio", success, result, ui_payload}`。

`sandbox_execute` ui_payload：`{language, exit_code, duration_ms, stdout(≤20k), stderr, artifacts:[{path,size,mtime}]}`。

### 1.8 Studio REST API（`src/omichub/api/v1/studio.py`，前缀 `/api/v1/studio`）

全部校验会话归属 + `mode=="studio"`（不满足一律 404）。

| 端点 | 说明 | 阶段 |
| --- | --- | --- |
| `POST /sessions {agent_id, title?, model_id?}` → ChatSessionDTO | 创建 studio 会话（workspace_id=session_id，agent 的 studio.image 存 sandbox_meta） | P0 |
| `GET /sessions` → ChatSessionDTO[] | 当前用户 studio 会话 | P0 |
| `GET /sessions/{id}` → `{session, sandbox_status, workspace_id, files[], plan}` | plan 来自 sandbox_meta.plan（P1 加入） | P0+P1 |
| `GET /sessions/{id}/files?path=` | 工作区列目录（沙盒活着走 agent，否则宿主磁盘回退） | P0 |
| `GET /sessions/{id}/files/read?path=&offset=&limit=` | 读文件（同上回退策略） | P0 |
| `POST /sessions/{id}/files/edit {path, old_string, new_string}` | 精确编辑文件；workspace_edit 拒绝时交换为反向编辑并依赖唯一匹配守卫回滚 | P2 |
| `POST /sessions/{id}/run {code, language?, timeout?}` → SSE | **用户重跑代码卡片**：只发 `tool_output*` + 末尾 `tool_result`（无 `done` 事件，流结束即完成） | P0 |
| `GET /sessions/{id}/artifacts` → `{artifacts:[{path,size,mtime,download_url}]}` | 扫宿主磁盘 output/ | P0 |
| `GET /sessions/{id}/artifacts/download?path=` | FileResponse，confined 到 output/ | P0 |
| `POST /sessions/from-report {report_id, agent_id}` → ChatSessionDTO | Context Packager（见 §2.2） | P1 |
| `POST /sessions/{id}/artifacts/register {path, title, type?, description?}` → `{report_id, title, version, parent_id, file:{name,size,type}}` | 「保存为新版本」（见 §2.3） | P1 |

`ChatSessionDTO` 已加 `mode` 字段（P0 后补）。

### 1.9 前端（P0 完成）

| 文件 | 说明 |
| --- | --- |
| `frontend/src/views/StudioView.vue` | 三栏工作台：顶栏（返回/标题/Agent徽章/模型/沙盒状态灯🟡🟢⚪🔴/刷新/栏开关）；左栏（会话列表+文件树+数据管理引入）；中栏（KimiMessageList+KimiChatInput，复用 agentHub store）；右栏（产物+实时待办计划+沙盒状态块）。FilesView 式拖拽调宽。`/studio` 无参自动跳最近会话或空态引导 |
| `frontend/src/api/studio.ts` | `studioApi`（createSession/listSessions/getSession/listFiles/readFile/listArtifacts + blob 下载/预览：产物下载接口需 JWT，统一走 axios blob → ObjectURL） |
| `frontend/src/composables/useStudioRunStream.ts` | `/run` SSE 封装（onOutput/onResult/onError/onDone） |
| `frontend/src/components/studio/StudioCodeCard.vue` | 代码卡片：头部（文件名/语言/退出码徽章）、CodeMirror（默认只读，「编辑」解锁，「重跑」流式回灌输出，「复制」）、workspace_edit 用 diff2html 展示并支持接受/拒绝回滚、输出区（ANSI 剥离/自动滚动/折叠）、产物 chips |
| `frontend/src/components/studio/StudioFileTree.vue` | 懒加载目录树，refreshKey bump 保留展开态静默重载 |
| `frontend/src/components/studio/StudioArtifactsPanel.vue` | 产物列表：图片 blob 缩略图+NModal lightbox、CSV/TSV 表格预览、Markdown 渲染、下载、「插入对话引用」与版本登记 |
| `frontend/src/components/studio/context.ts` | `StudioContextKey` provide/inject + `isStudioCodeTool()` |
| `frontend/src/router/index.ts` | `{ path: 'studio/:sessionId?', name: 'studio', fullscreen: true }` |
| `frontend/src/layouts/DefaultLayout.vue` | 导航「AI 工作台」(`/studio`) |
| `AgentSandbox.vue` | 头部「工作台模式」按钮 → createSession → push `/studio/:id` |
| `AgentSidebar.vue` | studio 会话 📊 角标，点击直达工作台 |
| `useAgentChatStream.ts` | 回调新增 `onToolOutput(tool, stream, data, toolCallId?)` |
| `agentHub.ts` | tool_output 接线（优先 tool_call_id 精确匹配）、ui_payload stdout 回填、`loadSessionMessages` 从 `metadata_json.tool_invocations[]` 重建代码卡片、`studioSessionIds` 集合 |
| `KimiMessageItem.vue` | inject StudioContextKey；studio 代码工具渲染 StudioCodeCard，否则原气泡（/ai 视觉不变） |
| `ai-chat/types.ts` | `ToolCall` 加 `output?`、`language?` |

**前端有意未修的点**：`useAgentChatStream` 的 tool_call/tool_result 事件不透传 `mcp_server`（补透传会让 /ai 的 MCP 气泡多出标签，违反视觉不变约束）；studio 判定走 provide/inject + 工具名。

---

## 二、P1 已完成内容（后端平台联动）

### 2.1 安全决策：per-user 平台只读挂载（重要，与原始 brief 不同）

最初设计是宿主整个 `storage_path` 只读挂到容器 `/data/platform`。**已改为 `{storage_path}/users/{user_id}` → `/data/platform`（ro）**。原因：沙盒代码用户可编辑可重跑、模型输出可被提示注入，整存储挂载会让任一会话 `cat /data/platform/users/*/raw/*`，构成跨租户越权。per-user 挂载功能等价（数据管理文件在 `users/{uid}/raw`，报告文件在 `users/{uid}/results`）。

- 仅**新建容器**时挂载（`ensure_running(..., user_id=...)`）；旧的运行中容器没有该挂载，回收重建后获得。
- 软链目标形如 `/data/platform/raw/a.csv`、`/data/platform/results/task-1/de.csv`（相对于用户目录）。
- 真机验证：容器内经 `/workspace/input` 软链读平台文件 ✓；`/data/platform` 写入失败（ro）✓。

### 2.2 Context Packager（架构文档 §7.2）

`src/omichub/application/services/studio_context_service.py`：

- `create_session_from_report(user_id, report_id, agent_id, db)`：加载 report + report_files + 来源 task → 创建 studio 会话 → 报告文件逐一软链进 `{workspace}/input/` → `sandbox_meta.context_pack` 写入：
  ```yaml
  source: {pipeline, pipeline_name, run_id, params, report_id, report_title}
  files: [{path, role}]
  hint: ...
  ```
- `render_context_pack_hint(pack)`：渲染为中文系统上下文，chat_service 在 studio 后缀后追加。
- 哨兵值：`STUDIO_FLOW_ID="studio"` / `STUDIO_FLOW_NAME="OmicStudio"`。

### 2.3 artifact_register 与报告版本树

- `reports` 表已加 `parent_id`/`version`（迁移 `v0w1x2y3z4a5`）。`ReportResponse` 同步加字段（additive）。
- 登记流程：path 必须在 `output/` 下（严格守卫）→ **复制**产物到 `{storage_path}/users/{uid}/results/studio/{session_id}/`（workspace 7 天后会清理，复制是正解）→ 建 ReportModel（`flow_id="studio"`、`status="completed"`、parent_id 取自会话 context_pack.source.report_id → version = 父版本+1；父报告不存在/不属本人时退化 v1）+ ReportFileModel。
- `register_artifact_report()` 同时被 agent 工具与 REST 端点复用。

### 2.4 路径守卫放宽（读写分离）

`src/omichub/infrastructure/studio/paths.py`：

- 新增 `resolve_workspace_read_path(user_path, root, platform_host_root=None)`：**读路径**允许经符号链接逃逸到平台挂载——条件是「词法路径在 workspace 内（即逃逸完全经由 symlink）且 realpath 落在平台挂载根下」；直接写 `/data/platform/...` 绝对路径一律拒绝；host 侧翻译到 `platform_host_root` 并复查 realpath（防嵌套软链）。
- `resolve_workspace_path`（写守卫）**未动，仍然严格**。
- `deploy/studio/sandbox_agent.py` 已同步镜像同样的放宽逻辑（`/files/read`、`/files/list` 放宽，write/edit 严格）。

**镜像状态（2026-07-17）**：`omichub-sandbox:base/bio` 已重新构建，容器内 `/files/read` 读取 input 软链和 workspace_edit `reverse_edit` 反向上下文均已进入实际镜像。后续修改 `deploy/studio/sandbox_agent.py` 后仍需执行 `bash deploy/studio/build.sh`。

### 2.5 update_plan → plan 事件

- chat_service 在 studio 工具分支**拦截** `update_plan`（不打沙盒）：发 `ChatChunk(type="plan", metadata={tool_call_id, steps})`，持久化到 `sandbox_meta["plan"]`，同时正常写 tool_invocations（历史可重放）。
- `normalize_plan_steps()` 在 studio_tools 导出，做 steps 校验归一化。
- 系统提示已要求模型：开始时先 update_plan 给 3-8 步计划，每完成一步更新状态。
- `GET /studio/sessions/{id}` 响应含 `plan`。

### 2.6 其他新增

- `workspace.py`：`platform_user_rel()`（剥离 `users/{uid}/` 前缀，拒绝他人目录/`..`/绝对路径）、`link_platform_file()`（basename 消毒 + `name (2).ext` 去重）、`list_input_links()`；`disk_read_file/disk_list_files` 支持 `platform_host_root`。
- `pipeline_query` 数据源：`FlowService().list_flows()` + `schema_loader.list_tools()`。
- `data/ai/studio.yaml` tools.builtin 已同步 10 工具清单，并注释记录 per-user 挂载。

---

## 三、验证状态

| 项 | 结果 |
| --- | --- |
| Studio 相关回归 | **179 passed**（Studio 单测、sandbox-agent 路径测试及相邻集成测试；含渐进式能力、分享/导出、脚本提炼 Skill、知识库搜索、用量聚合、Agent 重同步及报告版本树） |
| ruff | 全部改动文件通过 |
| Python 编译 / API | `py_compile` 通过；Worker→Web 内部端点隐藏于 OpenAPI，并由独立控制 token 鉴权 |
| Alembic | head = `w1x2y3z4a5b6`，`scripts/check_migrations.py` 全绿 |
| 前端 `npm run type-check` / `npm run build` | 通过（含状态灯轮询、长任务卡片、产物预览与 diff2html 交互） |
| 真机 docker 冒烟 | base/bio 镜像与 per-user ro 挂载 ✓；internal Studio 网络连通与公网阻断 ✓；Worker→Web→真实 base 沙盒流式执行 ✓；30KB stdout 严格限制流内 ≤10KB、完整原始输出落 `.logs/`、容器清理 ✓ |

**未做的验证**：浏览器端真实联调（前端页面是静态核对 + 类型/构建验证）；P1 新工具未在真实 LLM 会话里跑过完整场景 A。

---

## 四、环境/运维坑（已踩过，务必知道）

1. **`make docker-reload` 只重建前端，不重建后端镜像**。后端新依赖（如 `pyproject.toml` 加了 `scikit-posthocs`）需要 `cd deploy/docker && docker compose build web`。当前 web 镜像是「补丁镜像」：`FROM docker-web` + 补装 scikit-posthocs（因为完整 build 卡在最后一步：GitHub clone `JZ_Tools` TLS 握手失败，构建环境访问 GitHub 的网络问题）。网络恢复后应重新完整 build。
2. **不要裸跑 `docker compose up`**：compose 里的 `${REDIS_PASSWORD}` 由 Makefile `export REDIS_PASSWORD=omichub` 提供；脱离 make 直接跑会得到空密码 → redis 崩 → web 被 depends_on 挡住。要么用 make，要么 `REDIS_PASSWORD=omichub docker compose up -d`。
3. 本地 dev DB：`.env` 里 `POSTGRES_HOST=db` 在宿主不可达，跑 alembic 用 `localhost:5432`（同凭据），如 `DATABASE_URL=... .venv/bin/python -m alembic upgrade head`（alembic/env.py 读 URL 的方式见该文件）。
4. 沙盒 workspace 在 `{storage_path}/studio/{session_id}`（本机 `/data/omichub/studio/`）；容器内 uid 10001 写出的文件宿主可能无权直接删，清理用 `docker run --rm -v /data/omichub/studio:/s alpine rm -rf /s/<sid>`。
5. 报告中心前端默认使用真实 API；设置 `VITE_USE_MOCK_REPORTS=true` 才渲染 mock 数据。

---

## 五、未完成工作清单

### 5.1 P1 遗留后端（小）

**用户侧「数据管理引入」REST 端点：✅ 已完成并验证**

- `POST /api/v1/studio/sessions/{session_id}/import`，body `{file_id: str, name?: str}`。
- 与 `datahub_import` 共用 `import_datahub_file()`：会话归属/mode、文件归属、active 状态、物理文件存在性和软链路径均复用同一守卫。
- 响应包含 `{sandbox_path, name, size, file_type, input_files}`；schema 位于 `application/schemas/studio.py`。
- `tests/unit/test_studio_platform_tools.py` 已覆盖 happy path、越权和非 Studio 会话；Studio 平台联动测试共 `19 passed`。

### 5.2 P1 前端：✅ 已完成并验证

1. **左栏「从数据管理引入」**：已接入 `FilePickerModal.vue`，支持多选；调用 import REST，刷新文件树，并将每个返回的 `sandbox_path` 追加到输入框。
2. **报告中心「在 AI 工作台中优化」**：已接入 `ReportCardMinimal.vue`；默认使用 `agent-viz` 创建 `/studio/sessions/from-report` 会话并跳转。真实 API 默认开启，设置 `VITE_USE_MOCK_REPORTS=true` 才使用 mock。
3. **产物面板「保存为新版本」**：每个产物支持标题弹窗、`artifacts/register` 登记、版本/版本树提示。
4. **待办计划面板**：`plan` SSE 事件实时更新；初始会话详情和历史 `update_plan` 工具调用均可恢复，状态显示 pending/in_progress/done。
5. **artifact_register 工具卡片**：成功结果显示「已登记为《title》vN」，存在 `parent_id` 时显示已挂接版本树。

**前端验证**：`npm run type-check` 与 `npm run build` 均通过。

### 5.3 P2（架构文档 §十/§十一，已完成）

- ✅ workspace_edit 结果 diff2html 渲染 + 「接受/拒绝」；拒绝通过 `POST /sessions/{id}/files/edit` 使用 sandbox-agent 生成的唯一反向上下文回滚。157 个 Studio/相邻回归测试、ruff、前端 build 和真实 base 容器删除文本→反向恢复冒烟均通过；base/bio 镜像已重建。
- ✅ `sandbox_execute` 显式 `timeout > 600s` 转 Celery：创建任务中心记录（`flow_id=studio_sandbox`），Worker 执行 Studio 沙盒并持久化 stdout/stderr、产物与结果；Redis 进度事件 + 带 JWT 的任务详情轮询驱动前端进度卡，完成后刷新工作区。`600s` 仍保持同步路径，超时时间上限收敛到 `3600s`。长任务生命周期测试、157 个 Studio/相邻回归测试、Celery 注册、ruff、前端 type-check/build 均通过。
- ✅ 沙盒状态灯每 10 秒刷新；容器被 Celery 回收后，下一次执行通过 `ensure_running` 透明重建；会话创建后后台预热专属容器。由于 plain Docker 的 per-user bind mount 不能安全重绑，采用会话级预热替代跨用户通用 standby。Redis ZSET 共享活跃时间，执行租约保护长任务与并发文件操作。
- ✅ Worker 不挂载 Docker socket：Celery 通过 Web 的隐藏内部 API 执行与回收沙盒，使用显式或由 `APP_SECRET_KEY` 域隔离派生的控制 token；JWT 中间件只对该前缀让出认证，端点自身做常量时间校验。Web/Worker 不进入沙盒网络；Web 通过 UDS 控制 agent，沙盒按 `none` 或每会话 `whitelist` 网络运行，真实 Docker 流式执行与代理网络冒烟通过。
- ✅ **MCP/Skills 渐进式披露**：Studio 初始上下文只注入当前 Agent 已绑定能力的名称、描述和可用性目录，不注入未加载 Skill prompt、MCP 工具 schema、命令或环境变量；模型通过 `studio_capabilities_list` / `studio_capability_load` 按需加载。加载状态与最近 100 条 list/load 审计写入 `sandbox_meta.capabilities`，会话详情 API 可读取；未绑定、停用、离线或工具名冲突的能力失败关闭。已加载 MCP 才能参与工具路由，现有会话禁止切换到其他 Agent 绕过边界；普通 chat 模式保持原有全量行为。
- ✅ 产物预览增强：图片 lightbox；CSV/TSV 前 50 行表格；Markdown 渲染。文本预览复用 `/files/read` 分页守卫，CSV/TSV 最多读取前 500 物理行解析，Markdown 最多读取前 2000 行，并显示截断提示。前端 `type-check` / `build` 通过。
- ✅ 输出背压与防爆：sandbox-agent 双通道队列上限 64、Web `tool_output` 队列上限 32，慢客户端会逐层反压；Web/前端每通道仅保留 20K 尾部。流内严格 ≤10KB，超出时 `.logs/` 保存完整原始输出，LLM 仅回 2K/1K 尾部与日志引用。30KB 真机冒烟通过。
- ✅ **默认网络隔离**：默认 `network_mode=none`，agent 通过工作区 UDS 访问；真实沙盒直连 `1.1.1.1` 与 `omichub-web:8000` 均验证阻断。
- ✅ **域名白名单出站**：独立非特权代理服务 `studio-egress-proxy` 使用独立 egress 网络；每会话创建 internal 网络，仅连接沙盒与代理。YAML 白名单支持热加载、精确域名/子域名匹配、仅 80/443，代理侧 DNS 固定公网 IP，私网/保留地址、通配符、IP 字面量及非法端口全部拒绝。真实 smoke 已验证允许域名 CONNECT 返回 200、未允许域名返回 403、直连上游及平台 Web 均阻断；停止会话后临时网络自动清理。
- ✅ `/files/read` 容器内读平台软链与 `reverse_edit` 已随 2026-07-17 镜像重建生效（后续 agent 代码变更仍需重建）

### 5.4 P3（已完成）

- ✅ **会话分享与导出**：Studio 会话可创建/轮换最长 30 天的高熵只读链接，数据库仅保存 SHA-256 token hash；支持状态查询、显式撤销、过期失效。公开快照只返回用户/AI 对话和 `output/` 产物元数据，公开下载严格限制在 `output/`，不暴露输入、平台挂载、能力状态或执行入口。新增打印优化 HTML，前端可直接「打印 / 保存为 PDF」，分享页也提供同样入口。
- ✅ **管理员提炼为 Skill**：管理员可从自己 Studio 会话的工作区脚本创建并启用全局 Skill；仅接受 `.py/.R/.r/.sh/.bash` UTF-8 文本，限制 256KB，严格阻断路径逃逸、空文件、疑似密钥/密码赋值，并要求显式确认已检查隐私信息。生成 prompt 包含名称、描述、使用说明、完整参考实现及会话/路径来源，持久化复用现有 SkillService 的唯一 ID 校验。前端仅管理员显示提炼入口。
- ✅ **知识库联动**：新增受权限约束的 `knowledge_search` 工具，仅检索已发布文档的标题、分类与当前版本内容，结果返回有界摘要和站内链接，不泄露待发布/私有文档或完整正文。
- ✅ **用量与配额统计**：新增 `GET /api/v1/stats/studio?days=7|30`，从 Studio 消息 usage、沙盒工具调用 metadata、`studio_sandbox` 长任务及用户存储配额聚合 token、执行次数/成功率/时长、产物数量、每日趋势与剩余空间；仪表板已接入 7/30 天切换。

### 5.5 已知小问题（任何阶段可顺手修）

- Redis 长时间不可用时会退化为进程内活跃态；多副本环境需确保 Redis 可用，否则跨进程回收准确性下降
- `test_docs_service.py` 5 个既有失败（非 Studio 范围）

---

## 六、快速上手（新窗口第一步）

```bash
cd /home/zj/zj_code_libarary/OmicHub
source .venv/bin/activate
# 后端起服务（开发）
uvicorn omichub.main:app --host 0.0.0.0 --port 8888 --reload
# 前端
cd frontend && npm run dev
# 跑测试
.venv/bin/python -m pytest tests/unit -q
```

P3 已完成。当前验收基线：架构文档 §8 场景 A 全流程可演示（报告中心点「优化」→ AI 复现火山图 → 改代码重跑 → 保存 v2 挂回版本树）；用量面板可在仪表板查看 Studio token、沙盒执行与存储配额。
