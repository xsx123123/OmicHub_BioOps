# CygnusX 架构调查报告：AI 日程管理与提醒系统接入前摸底

- **调查日期**：2026-08-23
- **调查对象**：CygnusX 当前工作区
- **调查目标**：为新增“AI 驱动的日程管理与提醒系统”确认现有的 AI 工具调用、数据持久化、实时推送、后台调度、通知、权限、API 和前端接入边界。
- **证据口径**：以当前工作区文件、配置、ORM 模型、路由和任务定义为准；调查时工作区存在未提交修改，因此结论描述的是当前工作树状态，不等同于最近一次 Git 提交。
- **总体结论**：平台已经具备实现日程提醒所需的大部分基础设施：AI Function Calling/MCP/Skill 工具链、异步 SQLAlchemy + PostgreSQL、Redis Pub/Sub、Celery Beat、通知表和前端 Pinia/Naive UI。当前缺少的是“用户级日程/提醒领域模型、到期任务扫描/投递幂等、通知渠道适配和 AI 日程工具”这一组业务闭环，不建议直接把管理员公告表改造成日程表。

## 架构总览

```text
Vue 3 + Pinia + Axios
        │
        ├── REST /api/v1/*
        ├── Chat SSE /api/v1/chat/stream
        └── WebSocket（AI、任务日志、工作流、终端、余额）
                │
FastAPI Web ─── API Router / Auth Middleware / Services
        │
        ├── AI Runtime（Legacy / Direct / LangGraph / Studio / Overdrive）
        │       ├── Tool Schema Loader
        │       ├── Agent tool-pack / MCP / Skill filtering
        │       ├── tool_call → executor → tool_result
        │       └── chat_messages.metadata_json / skill_invocations / traces
        │
        ├── Async SQLAlchemy → PostgreSQL / pgvector
        ├── Redis cache / Pub/Sub / Celery broker & result backend
        ├── Celery Worker + Celery Beat
        │       └── analysis / goals / notifications-adjacent cleanup / AgentTeams...
        └── MinIO（AgentTeams 产物与共享证据）
```

---

## 1. 项目整体结构

**现状摘要**：仓库是一个“FastAPI 后端 + Vue 3 前端 + 生信工具/流程 + AI/MCP 服务”的单体多模块工程。后端主代码位于 `src/cygnusx/`，前端位于 `frontend/`；MCP Server、独立工具、Flow 流程和部署文件分别位于 `mcp-server/`、`tool_configs/`、`pipelines/`、`deploy/`。

后端采用应用服务、领域模型、基础设施和 API 分层；工具模块又有自己的 `api.py/service.py/schema.py/tasks.py`。这适合增加一个独立的 `calendar`/`reminders` 领域模块，而不适合把日程逻辑散落在聊天服务或通知组件中。

**关键文件路径**：

- `src/cygnusx/main.py`：FastAPI 应用创建、生命周期、CORS 和 `/api/v1` 总前缀。
- `src/cygnusx/api/v1/router.py`：API v1 路由汇总。
- `src/cygnusx/`：后端主包。
- `frontend/src/`：Vue 前端源码。
- `mcp-server/`：独立 MCP Server 项目。
- `tool_configs/`：工具 Schema、工具展示配置和工具专用配置。
- `data/ai/`：Agent、Prompt、Provider、Skill、MCP/能力配置。
- `pipelines/`、`flows/`：生信分析流程与工作流描述。
- `deploy/docker/`、`deploy/studio/`、`deploy/agentteams/`：部署和运行时镜像配置。

**技术选型**：

- Web 后端：FastAPI、Uvicorn/ASGI。
- ORM/数据库：SQLAlchemy 2.x 异步 ORM、PostgreSQL；依赖中包含 `pgvector` 和 `langgraph-checkpoint-postgres`。
- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router、Naive UI。
- 异步任务：Celery、Redis broker/backend；部分任务通过 Redis Pub/Sub 推送。
- 对象存储：MinIO，主要用于 AgentTeams 证据/产物。
- 包管理：后端根 `pyproject.toml`；前端 `frontend/package.json`；MCP Server `mcp-server/pyproject.toml`。

**与日程管理功能的关联度**：**高**。新增功能需要同时落在后端领域、Celery 调度、通知投递和前端页面四层；现有分层可以直接承载，但应保持“日程业务”和“通用通知投递”解耦。

---

## 2. AI 助手架构（最高优先级）

### 2.1 Tool Schema / ToolBridge 注册机制

**现状摘要**：AI 工具的统一 Schema 来源是 `tool_configs/tools_schema.yaml`，由 `ToolsSchemaLoader` 读取、Pydantic 校验并转换为 OpenAI function schema，同时支持 mtime 热重载。Schema 不只描述参数，还包含 `invocation_mode`、service/method、shim、是否需要确认、能力要求、运行时镜像和 MAS 执行策略。

工具授权不是“Schema 中存在就全部可用”，而是由 Agent 的 `tool_packs` 和 MCP/Skill 绑定进行二次过滤。`AgentService` 根据 Agent 声明的 `builtin_tools`、`platform_tools`、`mcp_tools` 组装当前会话工具列表，并在运行时能力、用户权限和模式上继续过滤。

**关键文件路径**：

- `tool_configs/tools_schema.yaml`：AI 可调用工具的主 Schema。
- `tool_configs/tools_setting.yaml`：前端工具展示、启用状态、路由和配置目录元数据。
- `src/cygnusx/tools/schema_loader.py`：Schema 加载、校验、OpenAI function 转换、动态 Flow Tool。
- `src/cygnusx/application/services/agent_service.py:800-980`：Agent 工具包、MCP 工具和内置工具的组合与过滤。
- `src/cygnusx/domain/skill/`、`src/cygnusx/application/services/chat/skill_execution.py`：Skill 工具入口和渐进式加载。
- `src/cygnusx/api/v1/mcp.py`、`src/cygnusx/application/services/mcp_service.py`：MCP Server 管理、健康检查和工具发现/调用相关服务。
- `src/cygnusx/infrastructure/database/models/mcp.py`、`mcp_log.py`：MCP Server 与 MCP 日志模型。

**技术选型**：Pydantic + YAML Schema、OpenAI-compatible function calling、MCP、动态 Skill Loader、SQLAlchemy 日志/配置存储。

**与日程管理功能的关联度**：**高**。日程功能的 AI 能力应通过同一套 Schema/ToolPack 暴露，而不是在 Prompt 中要求模型“自行调用 API”。

### 2.2 当前 AI 工具清单

当前 `tool_configs/tools_schema.yaml` 可见的工具按功能大致分为：

- **检索/协作**：`toolbox-search`、`agent-handoff-transfer`、`agent-parallel-subagents`。
- **AgentTeams**：创建 Case、任务结果摘要、文件预览、产物获取、指标比较、阈值查询、Case facts 查询。
- **记忆**：保存、更新、忘记、搜索和更新 memory block。
- **生信分析**：KEGG、火山图、DEG、系统发育树、曼哈顿图、GSEA、共线性、FASTQ QC、JBrowse、BLAST 等。
- **平台入口工具**：绘图、表达矩阵 Explorer、序列操作、引物、格式转换、ID 转换、湿实验计算器、Venn/UpSet、终端等。

工具的执行模式包括：

- `backend_sync`：调用后端 Service 的指定方法。
- `backend_async`：提交 Celery/异步任务并返回任务信息。
- `backend_shim`：调用受控 shim 模块。
- `analysis_flow`：先做 Flow 参数预检/确认，再提交分析。
- `open_page`：只打开前端功能页，不执行后端分析。

### 2.3 Prompt 管理与加载

**现状摘要**：Prompt 有两条并行来源：外置 Prompt Registry 和 Agent/Assistant 运行时上下文。`data/ai/prompts/registry.yaml` 将逻辑 key 映射到 Markdown/YAML 文件；`PromptRegistry` 支持路径越界保护、变量白名单和 mtime 热重载。聊天服务再把 Agent system prompt、路由后缀、工具使用约束、记忆提示、Skill 提示拼接成最终 system prompt。

**关键文件路径**：

- `data/ai/prompts/registry.yaml`：Prompt key→文件映射。
- `data/ai/prompts/*.md`、`data/ai/prompts/chat/*.yaml`：系统提示词、领域提示词和聊天配置。
- `src/cygnusx/infrastructure/config/prompt_loader.py`：Prompt Registry 实现。
- `src/cygnusx/application/services/ai_service.py:188-218`：普通 AI 对话 Prompt、工具使用提示和 Skill 注入。
- `src/cygnusx/application/services/chat_service.py:3200-3420`：聊天 Runtime 的上下文、工具、路由、记忆和 handoff Prompt 组合。
- `data/ai/agent_ability.yaml`、`data/ai/general.yaml`、各领域 YAML：Agent 能力和默认配置。

**技术选型**：YAML Registry + Markdown Prompt + Pydantic/运行时字符串组装 + mtime 缓存。

**与日程管理功能的关联度**：**高**。日程工具的 Prompt 应只描述意图、参数和安全边界；真正的时间解析、时区、重复规则和权限校验必须放在 Schema/Service，不应依赖模型文本自律。

### 2.4 Function Calling 完整链路

**现状摘要**：链路是“请求进入→选择 Runtime→构建 system prompt 和工具列表→向 OpenAI-compatible Provider 发起流式请求→解析 `tool_calls`→按工具名路由到内置/MCP/Skill/平台执行器→返回 `tool_result`→将结果追加为工具消息并重新调用模型”。目前有 Legacy 手写 ReAct、Direct、LangGraph、Studio、Overdrive 等多条 Runtime，语义通过公共事件和适配器逐步统一。

**关键文件路径**：

- `src/cygnusx/application/services/chat/chat_router_service.py`：Runtime 选择。
- `src/cygnusx/application/services/chat/runtimes/direct_chat_runtime.py`：手写工具循环，默认有限轮次。
- `src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py`：LangGraph 适配器和工具执行回灌。
- `src/cygnusx/infrastructure/execution/langgraph_nodes.py`：LLM Node、Tool Exec Node、轮次路由。
- `src/cygnusx/application/services/chat_service.py`：Legacy/主聊天工具循环、工具结果持久化、handoff 和会话状态。
- `src/cygnusx/infrastructure/ai_provider/openai_compatible.py`：流式 Provider、tool call 分片聚合和网络重试。
- `src/cygnusx/application/services/chat/runtime_support.py:674-820`：Skill 工具执行入口、埋点和 Skill Invocation 落库。

**与日程管理功能的关联度**：**高**。推荐第一阶段只加入 4 个明确工具：`create_schedule`、`list_schedules`、`update_schedule`、`cancel_schedule`，第二阶段再加入 `snooze_reminder`、`complete_reminder` 和自然语言查询工具。

### 2.5 工具审计与日志

**现状摘要**：工具调用有多层记录：聊天消息的 `metadata_json` 保存 `tool_invocations`、timeline 和 UI payload；Skill 调用写入 `skill_invocations`；MCP Server 有 `mcp_logs`；AI 调用还有 `ai_call_metrics` 和 OpenTelemetry trace。当前不是所有平台工具都统一写入一个“工具调用表”，而是按执行通道分别记录。

**关键文件路径**：

- `src/cygnusx/infrastructure/database/models/chat.py:287-314`：`chat_messages` 与 JSONB 元数据。
- `src/cygnusx/application/services/chat_service.py:3825,4901-4925`：工具调用结果和消息元数据落库。
- `src/cygnusx/infrastructure/database/models/skill.py:84-100`：`skill_invocations`。
- `src/cygnusx/infrastructure/database/models/mcp_log.py`：`mcp_logs`。
- `src/cygnusx/infrastructure/database/models/ai_metric.py`：`ai_call_metrics`、`ai_metric_alerts`。
- `src/cygnusx/core/telemetry.py`、`src/cygnusx/application/services/execution_events.py`：Trace/Metric/执行事件。

**与日程管理功能的关联度**：**高**。日程修改必须记录操作者、Agent、自然语言原文、解析后的时间、时区、旧值/新值、幂等键和执行结果；建议新增领域审计事件，而不是只依赖聊天 JSONB。

---

## 3. 数据库与 ORM

**现状摘要**：数据库访问使用异步 SQLAlchemy `AsyncEngine`、`AsyncSession` 和 `async_sessionmaker`。Web 服务使用带容量参数的异步连接池；Celery/Beat 由于跨事件循环问题使用 `NullPool`。默认数据库配置为 PostgreSQL asyncpg，部署栈还提供 pgvector。

迁移使用 Alembic，迁移文件位于 `alembic/versions/`。核心业务表较多，已经覆盖用户、会话、消息、Agent、Memory、MCP、Skill、任务、报告、项目、文件、通知、目标执行和 AgentTeams 产物血缘等领域。

**关键文件路径**：

- `src/cygnusx/infrastructure/database/base.py`：Declarative Base、时间戳等基础模型能力。
- `src/cygnusx/infrastructure/database/session.py`：异步引擎、会话工厂和连接池指标。
- `src/cygnusx/infrastructure/database/models/`：ORM 模型。
- `alembic.ini`、`alembic/env.py`、`alembic/versions/`：迁移配置和迁移历史。
- `.env.example`：数据库、Redis、JWT、MinIO 和 Celery 环境变量模板。
- `deploy/docker/docker-compose.yml`：PostgreSQL/pgvector、Redis、MinIO 等服务。

**核心表（按日程功能相关性排序）**：

- 身份与权限：`users`、`workspaces`、`teams`、`team_members`、`api_keys`。
- AI 对话：`chat_sessions`、`chat_messages`、`chat_assistants`、`chat_handoff_events`、`chat_message_feedbacks`。
- AI/Agent：`agent_templates`、`user_agent_capabilities`、`agent_memories`、`memory_blocks`、`memory_facts`、`skills`、`skill_versions`、`skill_invocations`、`mcp_servers`、`mcp_logs`。
- 任务/目标：`tasks`、`agent_goals`、`agent_goal_work_units`、`agent_goal_events`。
- 通知/审计：`notifications`、`announcements`、`audit_logs`、`ai_call_metrics`、`ai_metric_alerts`。
- 文件/产物：`file_records`、`reports`、`report_files`、`case_artifact_versions`、`case_artifact_dependencies`。

**技术选型**：SQLAlchemy 2.x async ORM、PostgreSQL、JSONB、UUID、Alembic、pgvector。

**与日程管理功能的关联度**：**高**。事务、唯一约束、JSONB 和现有 `agent_goal_events` 模式都能复用；但日程必须拥有独立的规范化表和索引，不能只把 `due_at` 塞进 `notifications.payload`。

**现状风险**：`notifications.read_by` 采用 JSONB 用户 ID 列表，适合低并发公告已读状态，不适合作为日程提醒的投递记录。日程提醒应使用独立的 `reminder_deliveries`/`notification_deliveries` 表，支持唯一键和重试状态。

---

## 4. WebSocket / 实时通信

**现状摘要**：平台同时使用 WebSocket 和 SSE。WebSocket 主要用于双向 AI 对话、终端交互、沙盒执行、任务日志、Cookie 余额和工作流监控；SSE 主要用于聊天流、任务进度、AgentTeams 事件和 Goal 事件流。

连接一般通过 URL query 中的 JWT 完成端点内鉴权；Redis Pub/Sub 负责把后台任务或事件广播到 WebSocket。用户级频道和任务级频道并存，例如 workflow monitor 根据管理员身份订阅全局频道，普通用户订阅用户频道，任务日志订阅具体 task channel。

**关键文件路径**：

- `src/cygnusx/api/v1/ai.py:96-165`：AI 对话 WebSocket。
- `src/cygnusx/api/v1/tasks.py:126-164`：任务日志 WebSocket；`tasks.py:166-193`：任务进度 SSE。
- `src/cygnusx/api/v1/workflow_monitor.py:212-265`：全局/任务级工作流监控 WebSocket。
- `src/cygnusx/api/v1/cookies.py:80-108`：Cookie 余额 WebSocket。
- `src/cygnusx/api/v1/goals.py:128-160`：Goal 事件 SSE，带 cursor 和 heartbeat。
- `src/cygnusx/api/v1/chat.py:524` 附近：聊天 SSE。
- `src/cygnusx/infrastructure/cache/`：Redis Pub/Sub 实现。
- `frontend/src/composables/useAIWebSocket.ts`、`useWorkflowMonitorWebSocket.ts`、`useCookieWebSocket.ts`、`useSandboxWebSocket.ts`、`useTerminalWebSocket.ts`：前端连接封装。

**技术选型**：FastAPI WebSocket、`StreamingResponse`/SSE、Redis Pub/Sub、Vue WebSocket composables。

**与日程管理功能的关联度**：**高**。提醒到期时建议先写数据库，再发布 Redis 用户频道事件；前端已有连接管理能力，可增加统一 `useNotificationStream`，但不要让提醒可靠性依赖 WebSocket 在线状态。

**重要边界**：当前通知列表是 REST 拉取，不等于已有“实时通知投递系统”。日程提醒必须采用“持久化投递记录 + 在线实时推送 + 离线补偿查询”的三段式设计。

---

## 5. 定时任务与后台调度

**现状摘要**：平台明确使用 Celery Worker + Celery Beat，Broker/Backend 使用 Redis。Celery 应用集中注册分析、下载、沙盒、Studio、MAS、Overdrive、Memory、MCP Builder、AgentTeams、Goals、AI Metrics 和可观测性任务，并配置队列路由、软/硬超时、预取和 worker 子进程回收。

Celery Beat 当前有多类周期任务：存储清理、空间对账、Cookie 日终对账、沙盒/Studio 回收、MCP 实验实例过期、MAS outbox/event consume、AgentTeams case watch/事件消费/过期审批恢复、Goal lease recovery、AI 指标告警和可观测性归档。已有 Goal Runtime 使用“持久化 Goal + Celery continuation”机制，但它不是通用日历调度器。

**关键文件路径**：

- `src/cygnusx/infrastructure/celery_app/celery.py:17-88`：Celery App、队列和任务路由。
- `src/cygnusx/infrastructure/celery_app/celery.py:90-178`：Beat 周期任务。
- `src/cygnusx/infrastructure/celery_app/tasks/goals.py:18-69`：Goal 单步执行、延迟续跑和租约恢复。
- `src/cygnusx/application/services/goal_execution_engine.py`：Goal 执行引擎。
- `src/cygnusx/infrastructure/database/models/goal.py`：Goal、Work Unit、Event 持久化模型。
- `deploy/docker/docker-compose.yml:137-180`：Beat/Worker 服务定义。
- `deploy/docker/docker-compose.prod.yml:33-43`：生产 Beat/Flower 服务。
- `src/cygnusx/core/config.py`：Celery、Redis、Goal lease/continuation 等配置。

**技术选型**：Celery、Celery Beat、Redis、SQLAlchemy 异步数据库访问；不建议引入 APScheduler 作为第二套调度系统。

**与日程管理功能的关联度**：**最高**。日程提醒必须复用 Celery 体系，但不应为每个用户提醒创建无限量 Beat 条目。推荐一个高频扫描/抢占任务：扫描 `next_fire_at <= now` 的活动提醒，按数据库锁/租约领取，写 delivery 记录，再投递通知。

**调度现状的可复用点**：

- Goal 的 lease、version、event_sequence 和幂等键设计可借鉴。
- Celery 的 `countdown` 可用于短期延迟，但不能作为长期日程的唯一事实源。
- Beat 只保留固定扫描任务，日程规则和下一次触发时间存数据库。

**调度现状的缺口**：

- 没有发现专门的用户日历/重复规则模型。
- 没有发现 `reminder_deliveries` 之类的投递状态表。
- 没有发现邮件、浏览器 Push、Webhook 的统一发送适配器。
- Celery Beat 本身不能保证业务级 exactly-once，需要数据库唯一键和幂等处理。

---

## 6. 通知系统

**现状摘要**：平台已有站内通知系统，后端提供当前用户通知列表、管理员创建/编辑/删除、指定用户/全局可见、过期时间和标记已读 API。模型为 `notifications`，包含标题、正文、级别、类型、JSONB payload、创建者、全局/目标用户、read_by 和 expires_at。

前端已有 Pinia `useNotificationStore` 和 `NotificationDrawer.vue`，使用 REST 获取通知、标记已读和删除；Naive UI 提供消息/Toast 反馈。用户资料中存在 email/in_app/webhook 偏好字段，但当前调查未发现对应的完整渠道投递服务，因此这些偏好不能直接视为“提醒已发送能力”。

**关键文件路径**：

- `src/cygnusx/api/v1/notification.py`：通知 REST API。
- `src/cygnusx/application/services/notification_service.py`：通知应用服务。
- `src/cygnusx/infrastructure/database/repositories/notification_repository.py`：通知查询/写入/已读仓储。
- `src/cygnusx/infrastructure/database/models/notification.py`：`notifications` ORM。
- `alembic/versions/c72c373d1ee2_add_notification_table.py`：通知表迁移。
- `frontend/src/stores/notification.ts`：通知状态管理。
- `frontend/src/components/NotificationDrawer.vue`：通知抽屉和交互。
- `frontend/src/stores/notification.ts`、`frontend/src/api/admin/notifications.ts`：前端通知 API 调用与状态封装；普通用户通知请求目前直接写在 Store 中。
- `frontend/src/views/ProfileView.vue`：通知偏好 UI。

**技术选型**：FastAPI REST、SQLAlchemy/PostgreSQL JSONB、Vue/Pinia、Naive UI。

**与日程管理功能的关联度**：**最高**。可以复用通知展示组件和通知基础表，但提醒业务应新增“日程”和“投递记录”模型；通知表只作为已生成的站内通知结果，不能承载重复规则、时区、提醒提前量、重试和投递渠道状态。

**当前通知系统适合做什么**：站内公告、管理员通知、AgentTeams 邀请/状态通知、用户已读状态。

**当前通知系统不应直接承担什么**：长期周期规则、复杂 RRULE、每个渠道的发送重试、每次提醒的 exactly-once 约束、用户级静默窗口和工作日策略。

---

## 7. 用户认证与权限

**现状摘要**：平台使用 JWT Bearer Token 作为主要认证方式，同时支持 X-API-Key。`AuthMiddleware` 负责请求级认证，`CurrentUserId` 依赖负责为 API 注入当前用户 ID；JWT 会校验 access token 类型、用户状态和 token_version，API Key 支持 scopes。管理员敏感操作还可以要求 TOTP 二次验证。

工具调用上下文包含 `user_id`、`agent_id`、`session_id`、数据库会话等信息，Agent/MCP/文件服务还按用户和能力进行隔离。日程系统应让所有 schedule、reminder、delivery 查询都从当前认证上下文取 user/workspace，不允许模型参数直接指定任意 user_id。

**关键文件路径**：

- `src/cygnusx/api/deps.py:19-88`：OAuth2PasswordBearer、JWT/API Key 当前用户依赖。
- `src/cygnusx/middleware/auth.py`：请求认证中间件、公开路径和内部自鉴权路径。
- `src/cygnusx/core/security.py`：JWT 编解码、密码和安全辅助函数。
- `src/cygnusx/api/v1/auth.py`：登录、注册、刷新、2FA、API Key。
- `src/cygnusx/infrastructure/database/models/user.py`：`users`、`workspaces`。
- `src/cygnusx/application/schemas/tool_invocation.py`：工具调用上下文。
- `src/cygnusx/application/services/api_key_service.py`：API Key 验证与 scope。

**技术选型**：JWT HS256、OAuth2PasswordBearer、X-API-Key + scopes、TOTP 2FA、FastAPI Depends。

**与日程管理功能的关联度**：**最高**。日程是强用户数据，至少要设计 user_id、workspace_id、可选 team_id，并在 REST、AI Tool、Celery 扫描和通知投递四个入口都执行归属校验。

**权限建议**：

- 普通用户：管理自己的日程和提醒。
- Workspace/Team 共享日程：显式 ACL，不用“知道 ID 即可访问”。
- Agent：仅继承当前会话用户授权，创建/修改/取消前按工具级策略决定是否需要确认。
- 管理员：可运维查看投递失败，但不默认拥有读取所有用户日程正文的权限。

---

## 8. API 路由结构

**现状摘要**：所有常规后端 API 通过 `src/cygnusx/api/v1/router.py` 汇总，`src/cygnusx/main.py` 以 `/api/v1` 统一挂载。固定模块使用显式 `include_router`；生信工具包通过 `register_tool_routers` 自动发现带 `router` 的工具子包并挂载。

现有相关路由包括 `/chat`、`/ai`、`/notifications`、`/tasks`、`/goals`、`/agent-teams`、`/mcp`、`/prompts`、`/workflow-monitor` 等。日程 API 应作为独立版本化模块注册，避免把 CRUD 混入 `/notifications` 或 `/goals`。

**关键文件路径**：

- `src/cygnusx/api/v1/router.py:61-104`：固定路由注册。
- `src/cygnusx/main.py:334-435`：应用创建和 `/api/v1` 挂载。
- `src/cygnusx/tools/__init__.py:36-69`：工具子包自动发现/挂载。
- `src/cygnusx/api/v1/chat.py`：聊天、会话、SSE、助手和 Skill API。
- `src/cygnusx/api/v1/notification.py`：通知 API。
- `src/cygnusx/api/v1/goals.py`：Goal 生命周期和事件流。

**技术选型**：FastAPI `APIRouter`、依赖注入、Pydantic Request/Response DTO、REST + SSE/WebSocket。

**与日程管理功能的关联度**：**高**。

**推荐路由**：

```text
/api/v1/schedules
/api/v1/schedules/{schedule_id}
/api/v1/schedules/{schedule_id}/pause
/api/v1/schedules/{schedule_id}/resume
/api/v1/schedules/{schedule_id}/occurrences
/api/v1/schedules/{schedule_id}/deliveries
/api/v1/reminders/{reminder_id}/snooze
/api/v1/reminders/{reminder_id}/complete
/api/v1/notifications/stream       # 可选，统一用户实时通知流
```

推荐新增 `src/cygnusx/api/v1/schedules.py`，然后在 `router.py` 显式挂载：

```python
api_router.include_router(schedules.router, prefix="/schedules", tags=["Schedules"])
```

---

## 9. 前端架构

**现状摘要**：前端是 Vue 3 + TypeScript + Vite，使用 Pinia 管理状态、Vue Router 管理路由、Axios 封装 REST 请求，Naive UI 提供组件和全局反馈。页面和能力按领域拆分，已有 AI Chat、AgentTeams、Goals、Tasks、Notification、Workflow Monitor、Studio 等组件目录。

路由集中在 `frontend/src/router/index.ts`，API 集中在 `frontend/src/api/`，状态集中在 `frontend/src/stores/`。通知已有完整的 Drawer/Store/API 组合，日程可以沿用这一模式新增 `ScheduleView.vue`、`ScheduleCalendar.vue`、`ReminderList.vue` 和 `stores/schedule.ts`，不需要先改造整个前端架构。

**关键文件路径**：

- `frontend/package.json`：Vue/Pinia/Naive UI/Vue Router/Axios 等依赖。
- `frontend/src/main.ts`：Pinia、Router、Naive UI、全局样式注册。
- `frontend/src/router/index.ts`：前端路由。
- `frontend/src/api/client.ts`：Axios 基础客户端和认证刷新。
- `frontend/src/api/`：领域 API 封装。
- `frontend/src/stores/notification.ts`：通知状态管理示例。
- `frontend/src/components/NotificationDrawer.vue`：通知展示示例。
- `frontend/src/components/ai-chat/`：AI 工具调用、确认卡片、Goal/Task/Artifact 等交互组件。
- `frontend/src/components/agent-teams/`、`frontend/src/components/task/`、`frontend/src/components/workflow-monitor/`：实时任务/协作 UI。

**技术选型**：Vue 3、TypeScript、Vite、Pinia、Vue Router、Axios、Naive UI、date-fns、Vitest。

**与日程管理功能的关联度**：**高**。已有通知抽屉和 AI 工具调用卡片可复用；日程 UI 需要补充时区、重复规则预览、下一次触发时间、暂停/恢复、投递历史和失败重试状态。

**前端建议结构**：

```text
frontend/src/api/schedules.ts
frontend/src/stores/schedule.ts
frontend/src/views/SchedulesView.vue
frontend/src/components/schedule/ScheduleCalendar.vue
frontend/src/components/schedule/ScheduleEditor.vue
frontend/src/components/schedule/ReminderList.vue
frontend/src/components/schedule/DeliveryStatus.vue
frontend/src/composables/useNotificationStream.ts
```

---

## 10. 配置文件与环境变量

**现状摘要**：主配置由 Pydantic Settings 从 `.env` 加载，默认配置和派生值集中在 `src/cygnusx/core/config.py`。敏感配置包括数据库、Redis、Celery、JWT、MinIO、Provider API Key、CORS 和限流参数；非敏感平台配置则大量使用 `data/ai/`、`tool_configs/` 等 YAML 文件。

Prompt、Tool Schema、Tool 展示配置和 Agent 能力配置都有独立文件；运行时 Loader 普遍支持缓存或 mtime 热重载。部署通过 Docker Compose 注入 PostgreSQL、Redis、MinIO、Celery Beat/Worker、Flower 等服务。

**关键文件路径**：

- `src/cygnusx/core/config.py:1-16,45-70,240-282`：Settings、环境文件、数据库/队列/JWT/Prompt/Tool 路径。
- `.env.example`：环境变量模板。
- `data/ai/providers.yaml`：AI Provider 配置单一事实源。
- `data/ai/prompts/registry.yaml`：Prompt Registry。
- `data/ai/`：Agent、MAS、Skill、Prompt 和能力配置。
- `tool_configs/tools_schema.yaml`：AI Tool Schema。
- `tool_configs/tools_setting.yaml`：前端工具展示配置。
- `deploy/docker/docker-compose.yml`：开发/基础部署服务。
- `deploy/docker/docker-compose.prod.yml`：生产服务覆盖。
- `deploy/docker/docker-compose.worker.yml`：Worker/独立计算服务。

**技术选型**：Pydantic Settings、python-dotenv、YAML、Docker Compose、Redis/PostgreSQL/MinIO 环境注入。

**与日程管理功能的关联度**：**高**。日程功能至少需要新增默认时区、扫描间隔、每轮批量上限、租约时长、重试退避、渠道开关和静默窗口配置；敏感渠道密钥必须进入 `.env`/Secret，不应进入 `data/ai/*.yaml`。

**建议新增配置**：

```text
SCHEDULE_RUNTIME_ENABLED=true
SCHEDULE_SCAN_INTERVAL_SECONDS=30
SCHEDULE_SCAN_BATCH_SIZE=500
SCHEDULE_LEASE_SECONDS=120
SCHEDULE_MAX_DELIVERY_ATTEMPTS=5
SCHEDULE_DEFAULT_TIMEZONE=Asia/Shanghai
REMINDER_EMAIL_ENABLED=false
REMINDER_WEBHOOK_ENABLED=false
```

---

# 附录 A：关键文件清单（按优先级）

## P0：必须先读

1. `src/cygnusx/application/services/chat_service.py`
2. `src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py`
3. `src/cygnusx/application/services/chat/runtime_support.py`
4. `src/cygnusx/tools/schema_loader.py`
5. `tool_configs/tools_schema.yaml`
6. `src/cygnusx/application/services/agent_service.py`
7. `src/cygnusx/infrastructure/database/session.py`
8. `src/cygnusx/infrastructure/database/models/chat.py`
9. `src/cygnusx/infrastructure/celery_app/celery.py`
10. `src/cygnusx/api/v1/notification.py`
11. `src/cygnusx/infrastructure/database/models/notification.py`
12. `src/cygnusx/application/services/notification_service.py`

## P1：日程功能接入时需要联动

1. `src/cygnusx/api/v1/router.py`
2. `src/cygnusx/api/deps.py`
3. `src/cygnusx/infrastructure/database/models/user.py`
4. `src/cygnusx/infrastructure/database/models/goal.py`
5. `src/cygnusx/infrastructure/celery_app/tasks/goals.py`
6. `src/cygnusx/api/v1/goals.py`
7. `src/cygnusx/infrastructure/cache/goal_pubsub.py`
8. `frontend/src/api/client.ts`
9. `frontend/src/stores/notification.ts`
10. `frontend/src/components/NotificationDrawer.vue`
11. `frontend/src/router/index.ts`
12. `.env.example`

## P2：部署和运行时

1. `deploy/docker/docker-compose.yml`
2. `deploy/docker/docker-compose.prod.yml`
3. `deploy/docker/docker-compose.worker.yml`
4. `src/cygnusx/core/config.py`
5. `src/cygnusx/infrastructure/cache/`
6. `src/cygnusx/infrastructure/celery_app/tasks/`
7. `src/cygnusx/infrastructure/database/models/skill.py`
8. `src/cygnusx/infrastructure/database/models/mcp_log.py`
9. `src/cygnusx/infrastructure/database/models/ai_metric.py`
10. `src/cygnusx/infrastructure/config/prompt_loader.py`

---

# 附录 B：AI 日程提醒融合建议

## B.1 工具定义放置位置

建议拆成三层，不把业务逻辑写进 `tool_configs/tools_schema.yaml`：

1. **领域实现**：
   - `src/cygnusx/application/services/schedule_service.py`
   - `src/cygnusx/application/services/reminder_service.py`
   - `src/cygnusx/application/schemas/schedule.py`
   - `src/cygnusx/application/schemas/reminder.py`
2. **工具适配**：
   - `src/cygnusx/application/services/schedule_tool_service.py`
   - 通过 `ToolInvocationContext` 获取当前 user/session/agent/db。
3. **工具声明**：在 `tool_configs/tools_schema.yaml` 增加：
   - `schedule-create`
   - `schedule-list`
   - `schedule-update`
   - `schedule-cancel`
   - `reminder-snooze`
   - `reminder-complete`

Schema 中应明确 `input_schema`、`requires_confirm`、`annotations.readOnlyHint/destructiveHint`、`required_capabilities` 和 `llm_result_fields/ui_result_fields`。创建/修改/取消操作建议默认 `requires_confirm: true`，查询操作可读免确认。

## B.2 数据库表设计

建议新增独立模型文件：`src/cygnusx/infrastructure/database/models/schedule.py`，至少包含：

### `schedules`

- `id`、`user_id`、`workspace_id`、可选 `team_id`
- `title`、`description`、`source`（manual/ai/import）
- `timezone`
- `start_at`、`end_at` 或 `duration_seconds`
- `recurrence_rule`（建议 RFC 5545 RRULE 字符串）
- `next_fire_at`、`last_fired_at`
- `status`（active/paused/cancelled/completed）
- `reminder_offsets`（如提前 10 分钟、1 天；可规范化为子表）
- `metadata_json`
- `version`、`created_at`、`updated_at`

### `schedule_occurrences`

用于把重复规则展开成可追踪实例：

- `schedule_id`、`occurrence_key`
- `scheduled_at`、`status`
- `completed_at`、`skipped_at`
- 唯一约束：`(schedule_id, occurrence_key)`

### `reminder_deliveries`

用于可靠投递：

- `schedule_id`、`occurrence_id`、`user_id`
- `channel`（in_app/email/webhook/browser_push）
- `due_at`、`sent_at`
- `status`（pending/sending/sent/failed/suppressed）
- `attempt_count`、`next_retry_at`
- `provider_message_id`、`last_error`
- 幂等唯一键：`(occurrence_id, channel, reminder_offset)`

不要使用 `notifications.read_by` 代替 `reminder_deliveries`；前者是公告的已读列表，不具备投递状态和并发抢占能力。

## B.3 调度器技术选型

**推荐：复用 Celery + Celery Beat，新增固定扫描任务。**

```text
Celery Beat 每 30 秒
    → scan_due_schedules
    → DB 条件扫描 next_fire_at <= now
    → SELECT ... FOR UPDATE SKIP LOCKED / lease
    → 创建 reminder_deliveries 幂等记录
    → Celery 投递渠道任务
    → 更新 occurrence/schedule 的 next_fire_at
    → Redis Pub/Sub 推送在线用户
```

理由：

- 现有 Celery/Beat/Redis/Worker 已运行，减少第二套调度基础设施。
- 日程规则应存 DB；Beat 只扫描，不为每条用户日程动态注册 beat entry。
- Goal Runtime 已有租约恢复、版本号、事件序列和延迟 continuation，可借鉴但不直接复用 Goal 表。
- 短期一次性提醒可以使用 Celery `countdown/eta` 作为优化，但数据库仍是事实源，重启后由扫描器补偿。

## B.4 通知投递策略

建议先实现站内通知，再逐步扩展渠道：

1. `in_app`：生成 `notifications` 记录，并发布 Redis 用户频道事件。
2. `email`：独立 Celery 任务，失败按指数退避重试。
3. `webhook`：校验允许域名、签名、超时和重试上限。
4. `browser_push`：确认浏览器权限、设备订阅和撤销机制后再实现。

可靠性要求：

- 先写 `reminder_deliveries`，再执行外部投递。
- 发送任务必须使用 delivery idempotency key。
- WebSocket/Redis 断开不能导致提醒丢失；用户再次打开通知中心时必须可补拉。
- 用户删除/暂停日程时，未发送的 delivery 要进入 `suppressed`，不能继续发送。

## B.5 前端组件放置

建议新增：

```text
frontend/src/api/schedules.ts
frontend/src/stores/schedule.ts
frontend/src/views/SchedulesView.vue
frontend/src/components/schedule/ScheduleCalendar.vue
frontend/src/components/schedule/ScheduleEditor.vue
frontend/src/components/schedule/ReminderList.vue
frontend/src/components/schedule/DeliveryStatus.vue
frontend/src/composables/useNotificationStream.ts
```

复用：

- `frontend/src/stores/notification.ts`
- `frontend/src/components/NotificationDrawer.vue`
- `frontend/src/components/ai-chat/ToolCallEntry.vue`
- `frontend/src/components/ai-chat/ApprovalCard.vue`
- `frontend/src/components/ai-chat/AskUserCard.vue`
- `frontend/src/api/client.ts`
- `frontend/src/router/index.ts`

## B.6 推荐实施顺序

1. **数据库地基**：完成 `schedules`、`schedule_occurrences`、`reminder_deliveries`、Alembic 迁移和用户/Workspace 归属约束。
2. **REST CRUD**：实现列表、创建、更新、暂停、恢复、取消、完成和投递历史查询。
3. **扫描与投递**：实现 Celery Beat 扫描、数据库 lease、delivery 幂等、失败重试和站内通知。
4. **实时体验**：增加用户通知 Redis channel、SSE/WS 统一通知流和离线补偿。
5. **AI 工具**：接入 read-only 查询，再接入创建/修改/取消；写操作默认确认。
6. **前端日历**：先列表/时间线，再增加月/周日历、重复规则预览和投递状态。
7. **外部渠道**：最后接 Email/Webhook/Browser Push，并增加 provider 级审计和退避。

## B.7 关键风险清单

| 风险 | 当前证据 | 对策 |
|---|---|---|
| 把公告当日程 | `notifications` 只有 `expires_at` 和 `read_by`，没有 recurrence/delivery 状态 | 新建 schedule/occurrence/delivery 三类模型 |
| WebSocket 断线丢提醒 | 当前 WS 主要是在线 Pub/Sub 推送 | DB 持久化为事实源，连接只做加速通知 |
| Celery 重复执行 | Beat/Worker 是 at-least-once 语义 | delivery 唯一键、lease、状态机、重试上限 |
| AI 误解析时间 | Prompt/Tool 不足以保证时区和重复规则 | 服务层统一解析、校验、预览并对写操作确认 |
| 越权操作 | 工具参数可能被模型构造 | 从 `ToolInvocationContext` 注入 user/workspace，忽略模型传入 owner 字段 |
| 多时区错误 | 当前未发现日程专用时区模型 | 每条 schedule 固定 timezone，DB 时间统一 UTC，展示层本地化 |
| 取消后仍投递 | 异步任务可能已排队 | 投递前再次读取 schedule/delivery 状态，取消未发送记录 |
| 通知渠道不可观测 | 当前通知主要是站内 REST | delivery 记录 provider id、attempt、last_error 和最终状态 |

---

## 最终判断

CygnusX **不需要引入新的 AI Agent 框架或新的定时框架**来实现日程提醒。最稳妥的路径是：复用现有 Tool Schema/Agent Runtime、异步 SQLAlchemy/PostgreSQL、Celery Beat/Worker、Redis Pub/Sub、Notification UI 和认证上下文；新增独立的 Schedule 领域模型、可靠投递状态机、用户通知流和日程工具适配层。

其中最重要的架构原则是：

> **数据库记录是提醒事实源，Celery 负责到期扫描和投递，Redis/WebSocket/SSE 负责实时加速，AI 只负责通过受控工具表达和修改用户意图。**
