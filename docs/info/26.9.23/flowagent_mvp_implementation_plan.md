# FlowAgent 接入 × 统一 Run 模型：MVP 实施计划（含验收标准）

> 依据：《Snakemake Agent × OmicHub 集成与统一异步任务模型调查报告》（2026-09-23）第 5–9 节。
> 原则：不新增第二条执行链；Run 做外壳，不改写现有 TaskStatus；PostgreSQL 是证据源，Redis 只做投递；异步的是等待，不是管控。

> **文档状态（2026-09-25）**：S1 首版 Run 计划 API、S2 的 Task 幂等键、S3 的 RunEvent PostgreSQL Outbox/Redis Stream 发布、S4 的 Snakemake 终态归档、S5 的 Run 事件查询、S6 的 MCP Run 工具和 FlowAgent `submit_plan` 已落地首版。平台侧 dry-run digest 重算、并发确认集成测试、真实 Redis/broker、E2E 及失败恢复仍需 staging 验证。下方验收标准仍是完成判据。

## 0. MVP 边界

**做**：Snakemake Plan DTO 与确认门 → 复用现有 Celery `run_snakemake` 执行 → 最小 RunEvent（queued/plan_pending/running/completed/failed）进 Outbox → 插件事件接入现有 workflow-monitor → 成功/失败自动归档（证据胶囊）→ MCP 只读工具 → FlowAgent 以平台提交替换本机 `submit_cluster`。

**不做（MVP 后）**：自动唤醒/通知（Agent 先轮询）、`qc_gated` 与 approval token 全量映射、project/user 配额与 admission control、Download/Studio/MAS 的 Run 收编、heartbeat/stale watchdog。

## 1. 目标架构（MVP 态）

```text
FlowAgent（TS）                        平台（Python/FastAPI + Celery）
─────────────                        ─────────────────────────────
自然语言 → dry_run → 组装 plan   │   POST /api/v1/runs/snakemake/plan
  │                                   │  校验 flow/release/targets/config_refs
  │  submit_plan（MCP 或 HTTP）       │  平台自跑 dry-run 验证 digest
  └──────────────────────────────────▶│  → plan_pending，返回 run_id
                                      │  人工确认（平台 UI 或 MCP confirm）
                                      │  POST /runs/{run_id}/confirm
                                      │  → 生成 TaskModel（run_id 作幂等键）
                                      │  → Celery run_snakemake（现有链）
插件事件 ──HTTP──▶ /workflow-monitor/events（带 run_id）
                                      │  RunEvent → Outbox 表 → Redis Stream
                                      │  成功/失败 → FileRegistry + archive_run
                                      │    → projects/{slug}/runs/{名}-{ts}/
MCP 只读：list_runs / get_run_status / get_run_logs / verify_artifact
```

## 2. 平台侧实施步骤

### S0. 准备（0.5 人日）

- 新建分支 `feat/run-shell-mvp`；所有新接口挂 feature flag `RUN_SHELL_ENABLED`（默认关），回滚 = 关开关。
- **验收**：flag 关闭时新接口 404，现有任务提交链路回归通过。

### S1. SnakemakePlan DTO + plan/confirm API（3 人日）

**改动**：

| 文件 | 动作 |
|---|---|
| `src/cygnusx/application/schemas/run_plan.py` | 新增 `SnakemakePlanSubmit` / `SnakemakePlanView` DTO |
| `src/cygnusx/api/v1/runs.py` | 新增 `POST /api/v1/runs/snakemake/plan`、`POST /api/v1/runs/{run_id}/confirm`、`GET /api/v1/runs/{run_id}` |
| `src/cygnusx/infrastructure/database/models/run.py` | 新增 `RunModel`：run_id(uuid pk)、project_slug、flow_id、release_id、plan_json、dry_run_digest、status、task_id(可空)、requested_by、created/confirmed_at |

**Plan DTO（草案）**——只接受已注册资产，禁止任意 Snakefile/shell：

```json
{
  "schema_version": "cygnusx.snakemake_plan.v1",
  "project_slug": "project-a",
  "flow_id": "rna_seq",
  "release_id": "2.3.0",
  "targets": ["de_results/diffexpr.tsv"],
  "config_ref": "flowrelease://rna_seq/2.3.0/default",
  "input_refs": ["filerecord://123", "filerecord://124"],
  "expected_outputs": ["*.tsv", "*.pdf"],
  "dry_run_digest": "sha256:...",
  "requested_by": "agent:flowagent"
}
```

**验收标准**：

1. `curl -X POST localhost:8000/api/v1/runs/snakemake/plan -d @plan.json` → 返回 `run_id`，DB 中 status=`plan_pending`。
2. 未注册 flow_id / release_id、manifest 外的 rule target、 Snakefile/shell 字段 → 422 并给出具体拒绝原因。
3. `GET /api/v1/runs/{run_id}` 返回 plan 摘要与状态。
4. 单元测试：DTO 校验矩阵（合法/每种非法引用各一例）。

### S2. 计划确认门 + 平台侧 dry-run 验证 + 幂等（2–3 人日）

**改动**：

| 文件 | 动作 |
|---|---|
| `src/cygnusx/application/services/run_plan_service.py`（新） | 引用校验（flow/release/target 必须在已注册 manifest 内）；**平台侧重跑 dry-run 生成 digest 并与提交值比对**（不信任 Agent 自报值） |
| `src/cygnusx/application/services/task_service.py` | `confirm` 事务：创建 `TaskModel`，`idempotency_key = run_id`，写 `run_id/project_slug` 到任务行 |
| `src/cygnusx/application/schemas/task.py` | `TaskSubmitRequest` 链路支持幂等键透传（补上"有列不设值"的 latent gap） |

**验收标准**：

1. 同一 `run_id` 重复 confirm → 不产生第二个 Celery 任务（DB 唯一索引生效 + 接口返回首次的 task_id）。
2. dry_run_digest 不匹配 → 409，计划不得进入 confirm。
3. 集成测试：confirm 后 `run_snakemake` 被投递且任务行携带 run_id（用 `CELERY_TASK_ALWAYS_EAGER` 或 staging worker 验证）。

### S3. RunEvent + 通用 Outbox（3–4 人日）

**改动**：

| 文件 | 动作 |
|---|---|
| `src/cygnusx/infrastructure/database/models/run_event.py`（新） | `RunEventModel`：event_id、run_id、task_id、project_slug、executor、status、phase、progress、rule、job_id、occurred_at、sequence、attempt、payload、dedupe_key；`(run_id, sequence)` 唯一 |
| `src/cygnusx/application/services/run_event_service.py`（新） | `emit()` 写库（同事务）；`publish_outbox` Celery beat 任务照搬 MAS `publish_outbox` 模式发布到 `cygnusx:run:events` |
| `src/cygnusx/infrastructure/celery_app/tasks/analysis.py` | 在 running/success/failed 推进点调用 `emit()`；成功/失败均调用归档（见 S4）；加最小 heartbeat（每 N 分钟发 running 事件） |

**事件 schema**：采用调查报告 §7.2 的 `cygnusx.run_event.v1`。

**验收标准**：

1. 跑一次真实 flow：`SELECT status, count(*) FROM run_events WHERE run_id=? GROUP BY status` 覆盖 queued/plan_pending/running/completed。
2. Redis 停掉 → 事件仍落 PostgreSQL；恢复后 `publish_outbox` 重放，Stream 消费者收到完整序列（验证报告未验证项 #1/#3）。
3. 消费端幂等：同一 `(run_id, sequence)` 重放不产生重复投影。

### S4. 归档与证据胶囊接线（2 人日）

**改动**：

| 文件 | 动作 |
|---|---|
| `src/cygnusx/infrastructure/celery_app/tasks/analysis.py` | 终态调用 `ProjectArchiveService.archive_run`（`project_archive_service.py:356-460`，直接复用） |
| `src/cygnusx/application/services/project_archive_service.py` | manifest 增加 `rerun_command` 字段；归档输入接受统一 artifact manifest |

**验收标准**：

1. 任务成功后 `projects/{slug}/runs/{任务名}-{时间戳}/` 存在 README.md、environment.json、manifest.json，MD5+SHA-256 齐全，项目级 AGENTS.md 追加该 run 条目（幂等，重跑不产生重复条目）。
2. 任务失败同样归档：含错误摘要与已产出部分产物的指纹。
3. 按 README 中 rerun_command 在干净环境重跑，产物 MD5 与 manifest 一致。

### S5. 插件事件接入 workflow-monitor（1–2 人日）

**改动**：

| 文件 | 动作 |
|---|---|
| `pipelines/tools/.../omichub_utils.py` | 环境变量 `SNAKEMAKE_OMICHUB_TASK_ID` 改传平台 run_id；payload 增加可选 `run_id/project_slug/status` 字段（保持 `omichub.workflow_event.v1` 向后兼容） |
| `src/cygnusx/application/services/workflow_monitor_service.py` | `_normalize_native_event` 识别新字段；修复"第一条 rule 日志即 running"的误判——有 run_id 的事件以 RunEvent 状态为准 |

**验收标准**：

1. 插件事件出现在监控中心且关联正确 run_id；rule 级进度可见。
2. 旧格式事件（无 run_id）回归通过。
3. 插件 bounded queue 打满丢事件时，Run 终态事件仍完整（终态由平台 adapter 发，不依赖插件）。

### S6. MCP 只读工具（2 人日）

**改动**：`mcp-server/tools/runs.py`（新增，照搬 `tasks.py` 的 X-API-Key 模式）：

```text
cygnusx_list_runs(project_slug?, status?, limit=50)
cygnusx_get_run_status(run_id) -> {run_id, project_slug, status, progress, current_rule, last_event_at, task_id}
cygnusx_get_run_logs(run_id, cursor?, limit=200)
cygnusx_verify_artifact(run_id, artifact_id) -> {size, sha256, state}
cygnusx_confirm_run_plan(run_id, user_confirmed: bool)  # 写操作：仅透传真实用户确认
```

**验收标准**：

1. 四个只读工具返回结构符合签名；越权 project_slug 返回 403。
2. `confirm_run_plan` 无真实用户确认令牌时拒绝；Agent 无法自我确认（测试：API key 直接调用被拒）。
3. 工具清单注册进 MCP server 并在客户端可发现。

## 3. FlowAgent 接入专章

### 3.1 接入方式：只走平台通道，关闭本机执行

FlowAgent 保留规划能力（catalog/ports/rules 查询、dry_run、detailed_summary），**执行一律改走平台**。部署配置：

- `FLOWAGENT_ALLOW_SUBMIT` 移除或恒为 false（本机 `spawnDetached` 路径下线）。
- 新增 `FLOWAGENT_PLATFORM_URL`、`FLOWAGENT_API_KEY`、`FLOWAGENT_PROJECT_SLUG`（`src/config.ts`）。
- FlowAgent 到平台走 MCP（推荐，与 Skill 调度同一权限面）或直连 REST；**不允许** FlowAgent 持有平台数据库/Shell 权限。

### 3.2 改动清单

| 文件 | 动作 |
|---|---|
| `FlowAgent/src/tools/platform.ts`（新） | 新增 `submit_plan` 工具：输入为 flow/release/targets/input_refs/expected_outputs；内部先复用现有 `dry_run` 产出 digest，组装 `SnakemakePlan`，调平台 plan API，返回 run_id 与状态页摘要 |
| `FlowAgent/src/tools/snakemake.ts` | `submit_cluster` 标记 deprecated（保留 dry_run / detailed_summary）；`hasSuccessfulDryRun` 校验逻辑被 `submit_plan` 复用 |
| `FlowAgent/src/ledger.ts` | JSONL schema 扩展：`platform_run_id`、`project_slug`、`plan_digest`、`platform_task_id`；新增 `hasSubmittedPlan(run_id)` 查询 |
| `FlowAgent/src/server.ts` / `cli.ts` | 响应中 surfaced run_id；提交后提示"任务已入平台队列，run_id=…"，并支持 `check_run <run_id>`（封装 MCP `get_run_status`） |
| `FlowAgent/README.md` | 更新边界声明：执行仅经平台，本机不再直接跑 Snakemake |

### 3.3 交互时序

```text
用户自然语言
  → Agent 查 catalog/rules，dry_run 通过
  → submit_plan → 平台 plan_pending → 返回 run_id
  → 人工确认（平台 UI；MCP confirm 透传用户操作）
  → Agent 轮询 get_run_status（MVP 不做自动唤醒）
  → completed 后：get_run_logs + verify_artifact → 基于产物继续对话式解读
  → 失败：拿 run_id 查失败原因，向用户呈现，可修正后重新 plan（新 run_id）
```

### 3.4 FlowAgent 验收标准

1. 自然语言"对 project-a 的 RNA-seq 数据做差异分析"→ 产出 plan → 平台出现 plan_pending run，FlowAgent 正确返回 run_id。
2. 平台部署形态下，`FLOWAGENT_ALLOW_SUBMIT=false` 时 `submit_cluster` 不可用；`runShell`/`spawnDetached` 在代码路径上不可达（测试断言）。
3. 台账 JSONL 含 run_id + project_slug + plan_digest，进程重启后可凭台账继续查询。
4. 平台任务完成后，FlowAgent 能通过 `check_run` 拿到 completed 状态与产物清单，`verify_artifact` 返回 SUCCESS。

## 4. 端到端验收场景（staging 部署后执行）

| # | 场景 | 通过标准 |
|---|---|---|
| E2E-1 | 主链路：plan → confirm → 执行 → 归档 → MCP 查询 | run 全状态事件序列完整；归档目录含 README/environment/manifest/AGENTS.md 条目；MD5 核验通过 |
| E2E-2 | 幂等：同一 run_id 重复 confirm / Agent 重试提交 | 仅一个任务执行；第二次返回首次 task_id |
| E2E-3 | 韧性：执行中停 Redis 再恢复 | 事件零丢失，Outbox 重放后消费者序列完整 |
| E2E-4 | 失败路径：注入失败 rule | status=failed，失败归档含错误摘要，Agent 轮询可见 |
| E2E-5 | 治理：Agent 尝试提交未注册 flow / 自报伪造 digest / 自我 confirm | 全部拒绝且留审计记录 |
| E2E-6 | 回归：现有表单提交流程任务不受影响的（RUN_SHELL_ENABLED 开/关两种状态） | 原有任务链路全部通过 |

## 5. 部署级验证清单（对应报告"未验证项"）

- [ ] 实际 broker 类型与 `task_queue/dispatcher.py` 分发配置确认（ARQ/RocketMQ/Celery 哪条在用）
- [ ] Outbox 重放成功率压测（kill Redis 期间持续 emit）
- [ ] 幂等键真实防重范围（集成测试覆盖，不只信列定义）
- [ ] FlowAgent 生产流程是否全部已注册为平台 flow/release（catalog ↔ 平台 manifest 对账）

## 6. 排期（单人全栈，已按 1.5–2 倍系数调整）

| 周 | 内容 | 产出 |
|---|---|---|
| W1 | S0 + S1 + S2 | plan/confirm API 可测，确认门与幂等生效 |
| W2 | S3 + S4 | 事件落库可重放，归档接线完成 |
| W3 | S5 + S6 + FlowAgent 3.1–3.2 | 插件联调 + MCP 工具 + FlowAgent submit_plan |
| W4 | E2E-1~6 + 部署级验证清单 + 文档 | staging 验收报告，FlowAgent README 更新 |

回滚预案：任何一步出问题，`RUN_SHELL_ENABLED=false` 即回到现状；FlowAgent 侧保留 `submit_cluster` 代码但配置关闭，可随时切回（仅限开发机）。

## 7. 风险登记（MVP 期）

| 风险 | 监控点 | 兜底 |
|---|---|---|
| 平台 dry-run 验证耗时长 | plan 接口延迟 | digest 比对可配置为抽样 + 高风险必验 |
| 单人排期溢出 | 每周里程碑 | 砍 S5 插件粒度（只保任务级事件），S6 减为 2 个工具 |
| 旧消费者受 RunEvent 影响 | E2E-6 回归 | RunEvent 与旧 Pub/Sub 双写并行，观察期后切流 |
