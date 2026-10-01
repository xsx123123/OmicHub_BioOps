# Snakemake Agent × OmicHub 集成与统一异步任务模型调查报告

调查日期：2026-09-23  
调查范围：本仓库当前工作树（只读检查）

## 0. 结论摘要

`Protocol/FlowFrame/FlowAgent` 是本仓库内的独立 TypeScript 应用，不是已经接入平台的外部服务。它具备 CLI 和 HTTP `/api/chat` 两种入口，调用 Vercel AI SDK，再通过受限工具执行 Snakemake；`submit_cluster` 当前实际上是在 Agent 进程所在机器启动本地后台 `snakemake`，不是平台任务提交或 HPC 提交。

平台已经有可复用的 Snakemake 执行链：`POST /api/v1/tasks` → `TaskService.submit` → `enqueue_task` → Celery `run_snakemake` → `LocalSnakemakeExecutor`。因此 MVP 不需要再造一条 Snakemake Celery 链，最小接入点是新增“外部计划/已确认计划提交”适配器，把 Agent 的 plan 转成平台已有 `TaskSubmitRequest` 或一个新的、只允许引用已注册 flow/rule 的计划 DTO。

当前统一程度有限：普通 `Task` 状态只有 `pending/queued/running/success/failed/cancelled`（`src/cygnusx/domain/task/value_objects.py:6-15`）；MAS 有独立的 `mas_runs`、`mas_nodes` 和 A2A Outbox（`src/cygnusx/infrastructure/database/models/mas.py:28-75,116-140`）；工具箱、下载、Studio、BLAST、富集等还各有自己的状态字段/事件通道。目标状态 `plan_pending/qc_gated/stale/archived` 在普通任务模型中不存在。建议新增 `Run` 外壳和事件投影，先包住 Snakemake，再逐步把普通 Task、Studio 和 MAS 映射进去，不要在 MVP 中直接重写现有任务表。

后台续跑目前最缺的是“完成事件 → 可寻址的 Agent 唤醒/续跑动作”。平台有 `session_id/project_id`（仅 MAS）和项目归档 `AGENTS.md`，但 FlowAgent 只有本地 `agent/run_ledger.jsonl`，没有 `run_id + project_slug` 绑定、回调订阅或续跑 API。MVP 可先提供轮询型只读 MCP；第二阶段再加通知表/Redis Stream consumer 和续跑 endpoint。

## 1. 代码边界与架构证据

### 1.1 两个“代码库”实际是一个仓库的两个模块

| 模块 | 关键证据 | 结论 |
|---|---|---|
| Snakemake Agent | `Protocol/FlowFrame/FlowAgent/package.json:1-24`；`README.md:1-8,82-95` | TypeScript/Node，`tsx` 运行，Vercel AI SDK 5、Zod；CLI + HTTP server；11 个工具；写入仅限 `composed/`、`agent/gap_log.yaml`、`agent/run_ledger.jsonl`。 |
| 平台 API/应用层 | `src/cygnusx/api/v1/tasks.py:43-123`；`src/cygnusx/application/services/task_service.py:53-146` | FastAPI → application service → domain/repository；任务提交后投递 Celery。 |
| 平台异步执行 | `src/cygnusx/infrastructure/celery_app/tasks/analysis.py:47-80,87-243` | Celery task 调本地 Snakemake executor，写 DB 任务状态和日志。 |
| MCP 外部桥 | `mcp-server/README.md:176-216`；`mcp-server/tools/tasks.py:9-171` | FastMCP 外部 server 通过 `X-API-Key` 调平台 REST；已暴露任务列表、详情、进度、日志、取消、DAG。 |
| Snakemake 事件插件 | `pipelines/tools/src/logger_plugin/snakemake_logger_plugin_rich_loguru/omichub_utils.py:32-147` | 已有 HTTP 推送插件和 `omichub.workflow_event.v1` payload；它是 logger sink，不是平台执行器 adapter。 |

### 1.2 三条流当前走向

```text
Agent 自然语言
  -> streamText + 工具查询 catalog/ports/rules
  -> dry_run + detailed_summary
  -> submit_cluster（当前本机 spawnDetached）
  -> agent/run_ledger.jsonl + 本地日志

平台用户/MCP
  -> POST /api/v1/tasks
  -> TaskService 生成 work_dir/config/monitor_config
  -> tasks 表 pending -> queued
  -> Celery run_snakemake
  -> tasks 表 running/success/failed + logs JSON
  -> Redis Pub/Sub task log + workflow monitor 缓存/WebSocket
  -> output 扫描写入 file_records

MAS
  -> mas_plans/mas_runs/mas_nodes
  -> mas_a2a_events Outbox
  -> Celery publish_outbox
  -> Redis Stream cygnusx:mas:events
  -> scheduler consumer
```

普通 `tasks` 事件使用 Redis Pub/Sub 和 workflow monitor 缓存（`src/cygnusx/application/services/workflow_monitor_service.py:138-172`），MAS 才有数据库 Outbox + Redis Stream（`src/cygnusx/infrastructure/mas/redis_streams.py:10-25`）。两者目前不是同一事件 schema 或同一消费组。

## 2. Snakemake Agent 现状

### 2.1 入口、规划和执行

- `src/agent.ts:7-24` 用 `streamText`、OpenAI-compatible provider、`stopWhen: stepCountIs(30)`；它是有状态于调用方消息数组的对话循环。
- `src/server.ts:29-79` 仅暴露 `GET /api/health` 和 `POST /api/chat`，没有提交平台任务的 API、回调 API 或 MCP server。
- `src/cli.ts:11-66` 支持单句和交互模式；会把响应消息追加回当前内存数组。
- `src/tools/registry.ts`、`src/tools/validate.ts`、`src/tools/writes.ts`（工具注册、manifest/端口/catalog 校验和受限写入）说明规划主要从已有 catalog、ports、rules、manifest 选择/组装；`write_composed` 才能生成 `composed/<date>_<request>/` 文件，且禁止覆盖。
- `src/tools/snakemake.ts:9-17` 的输入是 `task_id`、target 文件列表和相对 `workdir`，不是自然语言直接传给 Snakemake；`dry_run` 在 `:23-63`，`detailed_summary` 在 `:66-90`，`submit_cluster` 在 `:111-164`。
- `submit_cluster` 只检查本地台账中成功 dry-run 和 `FLOWAGENT_ALLOW_SUBMIT`，然后 `spawnDetached('snakemake', ['--cores', ..., '--rerun-incomplete', ...])`（`:119-159`）。返回的是本机 `pid` 和日志相对路径，没有平台 `task_id/run_id`、数据库登记、幂等键或结果归档。

因此 Agent 当前输出可以是“由现有 rule 组合得到的工作目录/targets + dry-run 摘要”，但它没有平台可直接消费的正式 `Plan` schema。完整 Snakefile/config 可以存在于 `composed/` 或目标流程仓库，但平台尚未验证或冻结这些文件。

### 2.2 台账和权限边界

`src/ledger.ts:4-15,17-25` 的 JSONL 字段只有 `ts/task_id/op/target/object/result/detail/confirmed`；`hasSuccessfulDryRun` 在 `:48-56` 按 task_id 或 target 集合查找成功 dry-run。没有 `project_slug`、平台 run id、事件序号、attempt、artifact 或恢复 token。

`src/config.ts:23-61` 显示：`FLOWAGENT_ALLOW_SUBMIT` 默认关闭；`safeJoin` 拒绝工作流根目录外路径；但 `runShell`/`spawnDetached` 仍是 Agent 进程直接执行系统命令的能力。README 所称“只读仓库”与 `submit_cluster`、`write_composed` 的受限写入应按工具边界理解，不能当成平台无 Shell 权限的证明。

### 2.3 插件事件现状

插件的 `OmicHubMonitorHandler`（`omichub_utils.py:32-77`）使用有界队列和后台线程；`:103-147` 构造事件：

```json
{
  "schema_version":"omichub.workflow_event.v1",
  "task_id":"...", "flow_id":"...", "user_id":"...", "project_name":"...",
  "timestamp":"...", "timestamp_ns":"...", "level":"info", "source":"snakemake",
  "message":"...",
  "snakemake":{"rule":"...","job_id":1,"event_type":"JobFinished",
    "shell_command":"...","progress_percent":42.0,"progress_details":"..."},
  "runtime":{"host":"...","pid":123,"user":"...","cwd":"...","command":"..."}
}
```

`:149-210` 通过 HTTP POST 发送，可选 Bearer token、HMAC 签名、AES-GCM 加密和重试；`:215-235` 队列满时丢弃事件并打印 warning。它从 logger 文本解析 `Rule`、`Jobid`、`JobFinished`、`ShellCommand`（`utils.py:94-131`），没有可靠的生命周期回调语义。

平台已有接收端：`POST /api/v1/workflow-monitor/events`（`src/cygnusx/api/v1/workflow_monitor.py:177-198`）和 Loki 兼容端点（`:200-210`）。`WorkflowMonitorService._apply_event` 会把 pending/queued 直接推到 running、更新进度和日志、写 Redis monitor pubsub（`workflow_monitor_service.py:102-172`）。这条链可以直接接插件，但会把“第一条 rule 日志”误当作 running，不能表达 `plan_pending`、`qc_gated`、`completed`、`stale`。

## 3. 平台任务和状态机普查

### 3.1 普通表单/流程 Snakemake 任务（可最低成本收编）

提交链路证据：`TaskService.submit` 先查 flow、生成工作目录和 config（`task_service.py:53-97`），创建任务（`:99-112`），调用 `enqueue_task(run_snakemake, ..., task_id=f"analysis-{task.id}-attempt-0", ...)`（`:114-123`），再推进 `pending -> queued`（`:125-126`）。任务表在 `task.py:14-44`，`idempotency_key` 有唯一索引（`:18-23,41`），但当前 `TaskSubmitRequest` 没有幂等键字段（`application/schemas/task.py:15-24`），提交服务也没有从请求设置它，故不能把数据库列视为已覆盖的防重链路。

状态定义和合法迁移在 `domain/task/value_objects.py:6-46`：

```text
pending -> queued -> running -> success
                         ├----> failed
                         └----> cancelled
pending/queued -> cancelled
```

Celery 执行器在 `analysis.py:108-112` 推进 running，成功在 `:156-158` 推进 success，失败在 `:200-210` 或异常分支 `:237-243` 推进 failed。成功后会生成报告并扫描 `output/` 注册 `file_records`（`:160-198`），但没有自动调用项目 `archive_run`。

### 3.2 普通异步执行路径

| 路径 | 现状状态/事件 | 统一化判断 |
|---|---|---|
| 分析 Snakemake | `TaskStatus`；Celery；task log Pub/Sub；workflow monitor | 最适合先接入 Run adapter。 |
| 数据下载 | 复用 `TaskStatus`，但在 `celery_app/tasks/download.py` 自己写大量状态/日志/进度；另有 `download_progress:*` Redis key | 可映射，需抽出通用 executor callbacks。 |
| Studio 长任务 | 复用 `TaskStatus`，但 `studio.py:506-618` 自定义 phase/progress；`:712-834` 有单独 stale queued/running 扫描 | 第二批迁移。 |
| 生信工具箱（DEG、富集、BLAST、树等） | 各自 service/schema/Redis 事件；例如 BLAST 有独立事件函数和 `build_status` | 需先统一事件 envelope，状态映射成本中等。 |
| AgentTeams/MAS | `mas_runs.status`、`mas_nodes.status`，节点 attempt/version/idempotency；A2A Outbox + Stream | 不是简单扩展 `tasks`；作为独立 adapter 投影到 Run。 |
| 质量门 | `AgentTeamsQualityGateService` 输出 `PASSED/WARNING/BLOCKED/MANUAL_REVIEW` 及 audit_event（`agentteams_quality_gate_service.py:17-75,77-144`） | 可投影为 `qc_gated` + gate decision，不能直接当 TaskStatus。 |
| 人工审批 | `MASApprovalModel.status=pending`（`models/mas.py:142-159`）及 MAS service/API | 只在 MAS 有持久化审批对象；普通 Task 没有计划确认状态。 |
| Agent/Overdrive/协同 | Overdrive 通过 run/event/tool_call 事件驱动，但与 `tasks`、MAS 的表和状态分开 | 最后迁移。 |

### 3.3 队列、背压、stale

队列不是单一 Celery：`src/cygnusx/infrastructure/task_queue/dispatcher.py:1-50` 通过配置在 ARQ/RocketMQ/Celery 之间分发；`arq_jobs.py:18-32` 用 Redis Pub/Sub 发布进度；`rocketmq.py:74-142` 负责发布与本地 Celery 兼容执行。现有证据没有按 project/user 的统一并发配额或公平调度。

分析任务有有限的 queued watchdog：`AgentTeamsStaleTaskService.scan` 查询 queued、未开始且更新时间超过阈值（`agentteams_stale_task_service.py:37-56`），最多自动重投一次，随后标记 failed（`:70-103,105-125`）。这不是目标 `stale -> failed` 的全局状态机，也不检测已 running 但无心跳的任务；workflow monitor 只在读取时统计 stale（`workflow_monitor_service.py:245-277`）。

### 3.4 Outbox/Redis Stream

MAS 的 `MASA2AEventModel` 有 `event_id/run_id/node_id/event_type/payload/dedupe_key/occurred_at/published_at/delivery_status`（`models/mas.py:116-140`）；`MASRepository.add_outbox_event` 写库（`mas_repository.py:150-173`），Celery `publish_outbox` 发布（`celery_app/tasks/mas.py:16-28`），`RedisStreamPublisher` 写固定 stream `cygnusx:mas:events`（`redis_streams.py:10-25`）。普通 `Task` 状态迁移没有对应 Outbox 表或事件重建逻辑；Redis 不可用时只能依赖任务表/日志，不能重放完整工作流事件。

## 4. Artifact、归档和续跑

### 4.1 产物登记/质量验证

MAS Artifact Registry 以 run/node 归属、路径、大小、SHA-256、visibility/state 存在 `MASArtifactModel`（`models/mas.py:78-113`）；`ArtifactService.validate` 实测文件大小和 SHA-256（`application/services/artifact_service.py:13-43`）。普通 Snakemake 成功后只把 `output/` 注册到 `file_records`（`celery_app/tasks/analysis.py:23-44,184-198`），没有在该处生成证据胶囊。

### 4.2 可复用的项目归档

`ProjectArchiveService.archive_run`（`application/services/project_archive_service.py:356-460`）已经提供目标目录校验、`README.md`、`environment.json`、`manifest.json`、项目级 `AGENTS.md`；README 明确同时保留 MD5 和 SHA-256（`:262-304,307-317`）。`AGENTS.md` 首次创建并按 `runs/<run_name>` 幂等追加（`:202-220,231-254,445-459`）。因此归档复用度高，缺口是：普通 `run_snakemake` 没调用它；归档输入没有统一的 artifact manifest 和 `rerun_command` 字段；任务模型也没有 `project_slug/run_id`。

### 4.3 续跑链路

- MAS `mas_runs` 有 `session_id`、`project_id`、`workspace_id`（`models/mas.py:32-49`），可以定位会话/项目，但没有通用 Agent 唤醒接口。
- FlowAgent 台账只有本地 `task_id` 和 target，不能跨机器凭平台 `run_id + project_slug` 找回现场（`FlowAgent/src/ledger.ts:6-19`）。
- 外部 MCP 目前只能轮询任务：`cygnusx_get_task_progress` 将 `success/failed/cancelled` 视为完成并建议稍后再次调用（`mcp-server/tools/tasks.py:68-96`）；没有 `list_runs/get_run_status/get_run_logs/verify_artifact` 的 Run 语义，也没有完成/失败通知。
- 平台已有 WebSocket 监控和 Redis Pub/Sub（`api/v1/workflow_monitor.py:212-265`），连接断开后没有可见的 durable cursor 或 Agent wakeup record。

## 5. 接口衔接清单

| 衔接点 | 提供方（文件:行） | 消费方 | 现状 | 估计 |
|---|---|---|---|---:|
| Agent 计划 → 平台计划 DTO | Agent `tools/snakemake.ts:9-17,66-90` | 新 `PlanAdapter` / `TaskService` | 需适配；当前只有 targets/summary | 3–5 人日 |
| dry-run 硬约束 | Agent `tools/snakemake.ts:23-63,111-130` | 平台 plan gate | 需新建平台持久化 gate；本地 ledger 不可作为平台证据 | 3–4 |
| 任务提交 | `TaskService.submit:53-146` | Agent/MCP | 可复用，但需接受 `run_id/project_slug` 和幂等键 | 2–3 |
| Celery Snakemake adapter | `celery_app/tasks/analysis.py:47-243` | 新 Run adapter | 可复用；补 heartbeat/event/归档调用 | 3–5 |
| 进度/日志事件 | 插件 `omichub_utils.py:103-210` | `/workflow-monitor/events` | 可直接 HTTP 对接；语义字段需扩展 | 2–4 |
| 任务级监控 | `WorkflowMonitorService:102-172` | 前端/MCP | 可复用；目前只落普通 tasks 和 Pub/Sub | 1–2 |
| Outbox durable event | MAS `mas_repository.py:150-183` | 普通 Run | 需新建通用 outbox 或扩展事件表 | 5–8 |
| Artifact 注册/校验 | `analysis.py:23-44`；`ArtifactService:13-43` | Run completion | 需适配普通 file_records 与 MAS registry | 3–5 |
| 项目归档 | `project_archive_service.py:356-460` | completion adapter | 高复用，需接到 analysis success/failure | 2–3 |
| Agent 恢复查询 | `mcp-server/tools/tasks.py:11-124` | FlowAgent | 需新增 Run 只读工具和 project/run 过滤 | 2–4 |
| 完成/失败唤醒 | 现有 Pub/Sub/WebSocket | Agent | 需新建 durable notification/outbox + consumer | 5–8 |
| 并发/背压 | 插件 bounded queue `omichub_utils.py:73-75,219-235` | 平台 scheduler | 插件只保护事件发送，未保护平台任务队列；需配额策略 | 4–6 |

## 6. 目标统一状态机差距矩阵

目标：`queued → plan_pending → running → qc_gated → completed → archived`，失败 `failed`，超时 `stale → failed`。

| 执行路径 | 状态机 | 事件 | 归档 | 续跑 | 背压 |
|---|---|---|---|---|---|
| Snakemake Task | 有 pending/queued/running/success/failed/cancelled；缺 plan_pending/qc_gated/archived/stale | native workflow event + Pub/Sub，非 durable | archive_run 可复用但未接 | 只有本地 ledger/轮询 | 无 project/user 全局配额 |
| Download | TaskStatus 基本可映射；下载 phase 分散 | Redis key + task log | 产物路径各自处理 | 无统一 wakeup | 下载器自身限速，非 Run 配额 |
| Studio | TaskStatus + 自定义 phase；有 watchdog | ARQ progress + task log | studio archive 可复用 | 依赖 session，未形成 Agent resume | 有 stale 扫描，非全局 |
| 工具箱/BLAST/DEG | 多套表和状态字符串 | 各自事件/Redis | 部分结果中心 | 轮询接口多，键不一致 | 未见统一配额 |
| MAS | run/node 独立状态，含审批/attempt/version | A2A Outbox + Stream durable | MAS Artifact + workspace | 有 session/project/workspace 绑定 | node max_attempts，缺用户配额 |
| 质量门/审批 | gate decision、approval pending 分开 | audit event/A2A | 依赖上游 | 不能直接唤醒 FlowAgent | 未统一 |

收编顺序：① Snakemake Task（已有 monitor、executor、archive 入口）；② Studio/Download（复用 TaskStatus）；③ 其他工具箱；④ MAS/AgentTeams（保留其 node 状态，新增 Run projection）；⑤ Overdrive/协同会话。

## 7. 推荐集成方案

### 7.1 MVP：Plan Adapter + Existing Task Executor

1. 新增平台 `SnakemakePlan` DTO：`schema_version`、`project_slug`、`flow_id/release_id`、`targets`、`config_ref`、`input_refs`、`expected_outputs`、`dry_run_digest`、`requested_by`。DTO 只接受已注册 flow/release 和 manifest 中的 rule/target；禁止 Agent 直接提交任意 Snakefile、shell 或数据库写操作。
2. 新增 `POST /api/v1/runs/snakemake/plan`：校验引用、保存 plan、状态置为 `plan_pending`，返回 `run_id` 和摘要。计划确认由平台用户/MCP 显式确认。
3. 新增 `POST /api/v1/runs/{run_id}/confirm`：确认后在同一事务生成普通 `TaskModel`（或调用 `TaskService`），写 `run_id/project_slug`，用 `run_id` 作为幂等键，投递现有 `run_snakemake`。
4. 修改 analysis adapter：开始/心跳/终态通过统一 `RunEvent` 写入普通 outbox；成功后调用 `FileRegistry`、`archive_run`，失败也归档错误摘要。现有 TaskStatus 继续作为执行细节，Run status 作为跨执行器外壳。
5. 插件把 `SNAKEMAKE_OMICHUB_TASK_ID` 设置为平台 task/run id，继续 POST `/workflow-monitor/events`；新增 `run_id/project_slug/status` 可选字段。平台 `_normalize_native_event` 保持向后兼容。
6. MCP 新增只读工具：

```text
cygnusx_list_runs(project_slug?: str, status?: str, limit?: int)
cygnusx_get_run_status(run_id: str) -> {run_id, project_slug, status, progress, current_rule, last_event_at}
cygnusx_get_run_logs(run_id: str, cursor?: str, limit?: int)
cygnusx_verify_artifact(run_id: str, artifact_id: str) -> {size, sha256, state}
cygnusx_confirm_run_plan(run_id: str, user_confirmed: bool)  # 写操作，必须确认
```

MCP 工具通过现有 `X-API-Key` 和用户 workspace 权限；`confirm_run_plan` 不是 Agent 自主确认，必须把用户确认原样传入。

### 7.2 统一事件草案

```json
{
  "schema_version": "cygnusx.run_event.v1",
  "event_id": "uuid",
  "run_id": "uuid",
  "task_id": "uuid-or-null",
  "project_slug": "project-a",
  "executor": "snakemake",
  "status": "running",
  "phase": "rule",
  "progress": 0.42,
  "rule": "fastqc",
  "job_id": 3,
  "occurred_at": "RFC3339",
  "sequence": 12,
  "attempt": 0,
  "payload": {},
  "dedupe_key": "run:sequence"
}
```

Outbox 必须以 `(run_id, sequence)` 或 `dedupe_key` 唯一；Redis Stream 只做投递，PostgreSQL 是证据源。事件消费者包括 monitor projection、notification/wakeup、artifact/archive worker；Redis 不可用时由 outbox publisher 重放。

### 7.3 计划格式边界

Agent 只提交：已注册 `flow_id/release_id`、manifest rule IDs、目标 artifact、参数白名单、输入 artifact refs、资源档位。平台根据 release 生成真实 Snakefile/config。若现阶段必须运行 Agent 生成的 composed 文件，应先把文件作为待审 artifact 存入隔离 workspace，由人工确认并 hash 锁定，再进入 `plan_pending`；不能让 Agent 直接写生产流程 YAML。

## 8. 风险、兜底和设计边界

| 风险 | 证据/原因 | 兜底 |
|---|---|---|
| Agent 绕过平台直接跑命令 | `submit_cluster` 调 `spawnDetached`（`snakemake.ts:139-143`） | 平台部署的 Agent 关闭 `FLOWAGENT_ALLOW_SUBMIT`；仅允许调用平台 submit MCP；网络/文件权限限制到 sandbox。 |
| 事件丢失 | 插件 bounded queue 满会丢事件（`omichub_utils.py:219-235`） | 终态和关键状态由平台 adapter 写 Outbox；插件事件只做细粒度日志，丢失时由 task/manifest 重建摘要。 |
| 事件顺序/重复 | HTTP retry + logger 文本解析 | event_id、sequence、dedupe_key；消费端幂等。 |
| 失败无人唤醒 | 现有 MCP 只轮询，WebSocket 非 durable | completion/failure notification 表 + Stream consumer；Agent 断线后按 cursor 补拉。 |
| stale 悬挂 | 当前 watchdog 只处理 queued，running stale 只统计 | Run heartbeat；超过 deadline 进入 stale，watchdog 负责终止/标记 failed，并发失败通知。 |
| 队列打满 | 尚无统一 project/user quota | admission control：项目并发数、用户并发数、最大 batch；超限返回 queued + retry_after，不让 Agent 批量同步重试。 |
| 产物越权/篡改 | 普通 pipeline 只注册 output；MAS 才强 SHA-256 validate | artifact register 前限制到 run workspace，归档时实测 MD5+SHA-256，结果查询只返回已验证 artifact。 |
| 计划生成违反“AI 只调度” | Agent 可写 composed | 只允许选择已发布 rule/release；任何新组合经过平台 plan gate + 人工确认，平台生成最终执行输入。 |

## 9. MVP 与后续排期

### MVP（约 10–15 人日）

- `SnakemakePlan`、plan/confirm API 和 `run_id/project_slug` 持久化。
- 复用 `TaskService`/Celery `run_snakemake`；不新增第二条执行链。
- 平台确认门验证 flow/release/target/config refs、dry-run digest 和幂等键。
- 统一 `RunEvent` 最小事件：queued、plan_pending、running、completed/failed；关键事件进 Outbox。
- 接入现有 `/workflow-monitor/events`，插件配置使用平台 task/run id。
- 接入现有 `FileRegistry` 和 `archive_run`，产出 README、environment、manifest、AGENTS.md。
- MCP 先提供 `list_runs/get_run_status/get_run_logs/verify_artifact`；Agent 暂时轮询，不做自动唤醒。

### MVP 后（约 15–25 人日）

- heartbeat/stale watchdog、终态通知和 cursor-based resume。
- `qc_gated` 与 `approval token`，把 `AgentTeamsQualityGateService` 的 audit event 映射到 Run。
- project/user quota、队列公平性和 admission control。
- Download/Studio 适配 Run adapter。
- MAS 通过 projection 接入统一 Run 查询，保留 node 状态和 A2A Outbox。

统一状态机应在 MVP 中以“Run 外壳 + 最小事件”落地；现有 `TaskStatus` 不必立即改名。这样可隔离旧消费者，避免一次性迁移任务表，同时让 Snakemake 成为后续执行器的参考 adapter。

## 10. 未验证项

- 本调查未连接运行中的 PostgreSQL、Redis、Celery worker 或真实集群，因此无法验证部署时实际 broker、beat 周期、队列名称、并发限制和 Outbox 重放成功率。
- `FlowAgent` 的规则/manifest/catalog 是目标流程仓库资产；本仓库 demo 可证明接口形态，但不能证明所有生产流程均已注册或可被平台安全引用。
- 插件存在 `omichub.workflow_event.v1` 接收协议，但没有在本仓库证据中看到把普通任务事件写入 PostgreSQL Outbox 的实现；需要部署级验收确认。
- 调查时 `TaskModel.idempotency_key` 有唯一索引，但普通任务提交 DTO/服务链没有设置它；本次实施补记已为提交 DTO/服务链增加幂等键，仍必须用集成测试验证真实防重范围，不能只依据列定义。

## 11. 2026-09-25 实施进展补记

已完成首个可独立验收的 MVP 切片：

- 新增 `platform_runs` ORM 模型及 Alembic 迁移 `alembic/versions/d9e0f1a2b3c4_add_platform_runs.py`。
- 新增 `SnakemakePlanSubmit` / `SnakemakePlanView`，计划提交强制 `cygnusx.snakemake_plan.v1`、项目 slug、flow/release、请求幂等键，且拒绝额外字段。
- 新增 `/api/v1/runs/snakemake/plan`、`/api/v1/runs`、`/api/v1/runs/{run_id}` 和 `/api/v1/runs/{run_id}/confirm`。
- 计划提交校验 flow 当前版本；相同用户 `request_key` 返回已有 Run；确认时使用 `run:{run_id}` 作为 Task 幂等键并复用现有 `TaskService`/Celery 链。
- 原调查报告中“当前不存在 Run API”的描述是调查时点快照；平台侧 dry-run digest 重算、并发确认集成测试及部署级 E2E 仍未完成。
- 后续首版已补充 RunEvent 持久化与 Redis Stream 重放任务、Snakemake 终态归档、MCP Run 查询/确认/产物查询，以及 FlowAgent `submit_plan`；真实 Redis/broker 和 E2E 仍未验证。
