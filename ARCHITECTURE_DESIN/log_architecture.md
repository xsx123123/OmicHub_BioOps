# CygnusX 日志架构说明

> 本文档描述 CygnusX 平台统一日志架构。新增或修改日志相关功能时，请对照本架构保持目录、格式、挂载方式和容量保护策略一致。
>
> 迁移说明（2026-09-18）：原文 §9.2–§9.6（terminal 资源配置、参考基因组前端/路由/JBrowse 配置、cygnusxtools 参考库离线构建）与日志主题无关，已整段迁至 `database_architecture.md` 附录《Terminal 与参考基因组模块更新记录》；本文 §9 仅余 §9.1 日志容量治理，编号顺延保持不变。
>
> 关联文档：
> - `docs/update_info/26.7.7/omichub_log_unification_plan.md`（改造计划）
> - `README.md`「日志排查」章节（日常运维速查）

---

## 1. 设计目标

- **统一落盘**：应用、Nginx、Celery 任务、Snakemake、审计日志统一归集到宿主机 `/data/cygnusx/logs/`。
- **分级聚合**：可读文本、结构化 JSON、ERROR 独立日志并存，兼顾人工排障和机器采集。
- **容量受控**：loguru 文件日志内置轮转、保留期和压缩；Docker stdout 使用 `json-file` 大小限制；Nginx/Snakemake 通过宿主机 logrotate 兜底。
- **持久化**：通过 Docker bind mount 写入宿主机，容器重建不丢失。
- **实时流保留**：任务日志仍通过 Redis Pub/Sub → WebSocket 实时推送，并回写 DB；文本日志作为文件级备份。
- **Loki 就绪**：应用 JSON 日志与 Nginx JSON 访问日志可被 Promtail 采集，后续可平滑接入 Grafana Loki。

---

## 2. 目录结构

```text
/data/cygnusx/logs/                  # 宿主机统一日志根目录
├── app/                             # 应用服务日志（web / beat / worker）
│   ├── cygnusx.log                  # 可读文本主日志（loguru 轮转）
│   ├── cygnusx.json.log             # 结构化 JSON 日志（loguru serialize=True）
│   └── error.log                    # ERROR 级别以上单独抽离
├── celery/                          # Celery 单任务文本日志
│   └── tasks/
│       └── {task_id}.log            # loguru 单文件 sink，按任务 ID 查询
├── nginx/                           # Nginx 访问/错误日志
│   ├── access.log                   # JSON 结构化访问日志
│   └── error.log
├── snakemake/                       # 生物信息流程 stdout/stderr
│   └── {project_name}/
│       └── {timestamp}/
│           ├── stdout.log
│           └── stderr.log
└── audit/                           # 预留独立审计文本目录
    └── audit.log                    # 当前审计文本备份写入 app/cygnusx.json.log
```

---

## 3. 各服务写入方式

### 3.1 应用日志（web / beat / worker）

- **模块**：`src/cygnusx/core/logging.py`
- **入口**：
  - Web：`src/cygnusx/main.py` 的 lifespan 调用 `setup_logging()`。
  - Celery Worker / Beat：`src/cygnusx/infrastructure/celery_app/celery.py` 启动时调用 `setup_logging()`。
- **兼容标准库日志**：`InterceptHandler` 将仍使用 `logging.getLogger(...)` 的旧代码和第三方库日志转发到 loguru，避免日志分散。
- **环境变量**：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SERVICE_NAME` | `app` | 服务标识，如 `web` / `beat` / `worker` |
| `CYGNUSX_LOG_LEVEL` | `INFO`，开发环境未显式设置时为 `DEBUG` | 控制 stdout 日志级别 |
| `CYGNUSX_LOG_DIR` | `/app/logs` | 应用日志根目录，Docker 中挂载到 `/data/cygnusx/logs/app`；目录不可写时依次回退 `./logs` 和 `/tmp/cygnusx/logs`（`core/logging.py` `_resolve_log_dir`） |
| `CYGNUSX_LOG_ROTATION` | `50 MB` | 应用日志单文件轮转阈值 |
| `CYGNUSX_LOG_RETENTION` | `30 days` | 应用日志保留期 |
| `CYGNUSX_LOG_COMPRESSION` | `zip` | 轮转后压缩格式 |

- **Log↔Trace 关联**：`core/logging.py` 的 `_telemetry_patch` 向每条日志注入 `trace_id`、`span_id`（取自当前 OpenTelemetry span）、`request_id`、`session_id`（取自 trace_context 的 ContextVar）；遥测缺失时仅写入空值，不影响日志本身。

- **Sink**：
  1. `sys.stdout`：带颜色可读格式，便于开发和容器日志查看。
  2. `/app/logs/cygnusx.log`：文本主日志，默认 50 MB 轮转、30 天保留、zip 压缩。
  3. `/app/logs/cygnusx.json.log`：JSON 结构化日志，`serialize=True`。
  4. `/app/logs/error.log`：仅 ERROR 及以上，使用同样的轮转/保留/压缩策略。

### 3.2 Celery 单任务日志

- **模块**：`src/cygnusx/infrastructure/celery_app/logging.py`
- **机制**：`LoggedTask` 作为 Celery 全局 `task_cls`，每个任务自动创建独立文件 sink。
- **Docker 路径**：Worker 设置 `CYGNUSX_CELERY_LOG_DIR=/data/cygnusx/logs/celery/tasks`，因此宿主机可直接按任务 ID 查询。
- **默认本地路径**：未设置 `CYGNUSX_CELERY_LOG_DIR` 时使用 `${CYGNUSX_LOG_DIR:-/app/logs}/celery/tasks`。
- **容量保护**：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CYGNUSX_CELERY_LOG_ROTATION` | `20 MB` | 单任务日志文件轮转阈值 |
| `CYGNUSX_CELERY_LOG_RETENTION` | `7 days` | 单任务日志保留期 |
| `CYGNUSX_CELERY_LOG_COMPRESSION` | `zip` | 轮转后压缩格式 |

- **失败降级**：任务日志目录创建或 sink 添加失败时，只记录 warning，并继续执行任务，不阻断主流程。
- **实时链路**：现有 `publish_task_log` + DB 回写 + WebSocket 不变，文件日志只是额外备份。

### 3.3 数据库任务日志边界

任务详情页读取的是 `tasks.logs` JSON 字段。为避免长任务将数据库撑大，仓储层统一限制：

- **模块**：`src/cygnusx/infrastructure/database/repositories/task_repository.py`
- **策略**：
  - 单条 `message` 超过 `TASK_LOG_MESSAGE_MAX_CHARS` 时截断，并附加 `truncated=true`、`original_length`。
  - 单任务最多保留最近 `TASK_LOG_MAX_ENTRIES` 条日志。
- **配置项**：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TASK_LOG_MESSAGE_MAX_CHARS` | `8192` | DB 单条任务日志 message 最大字符数，`0` 表示不截断 |
| `TASK_LOG_MAX_ENTRIES` | `1000` | DB 单任务最多保留日志条数，`0` 表示不限制 |

大体量 stdout/stderr 应落文件，DB 只保留前端展示所需的摘要日志。

### 3.4 Nginx 日志

- **配置**：`deploy/docker/nginx/nginx.conf`（开发）、`deploy/docker/nginx/nginx.prod.conf`（生产）。
- **格式**：自定义 `cygnusx_json` log_format，字段包括 `timestamp`, `service`, `remote_addr`, `request_id`, `method`, `uri`, `status`, `bytes`, `request_time`, `upstream_time`, `referer`, `user_agent`。
- **落盘**：`access_log /var/log/nginx/access.log cygnusx_json;`
- **挂载**：宿主机 `/data/cygnusx/logs/nginx` 挂载到容器 `/var/log/nginx`。
- **容量保护**：Nginx 文件日志不受 loguru 控制，使用 `deploy/logrotate/cygnusx-logs` 在宿主机配置轮转。

安装示例：

```bash
sudo cp deploy/logrotate/cygnusx-logs /etc/logrotate.d/cygnusx-logs
sudo logrotate -d /etc/logrotate.d/cygnusx-logs
```

### 3.5 Snakemake 流程日志

- **模块**：`src/cygnusx/infrastructure/execution/local.py`
- **机制**：`LocalSnakemakeExecutor._execute` 在 subprocess 执行后，将 stdout/stderr 写入：

```text
/logs/snakemake/{project_name}/{timestamp}/
    stdout.log
    stderr.log
```

- **挂载**：Worker 将宿主机 `/data/cygnusx/logs/snakemake` 挂载到容器 `/logs`。
- **失败降级**：写文件失败返回 `None`，不影响任务主流程。
- **容量保护**：使用 `deploy/logrotate/cygnusx-logs` 对固定深度的 stdout/stderr 文件做压缩轮转；长期保留策略仍建议额外用 crontab 清理旧目录。

示例：

```bash
find /data/cygnusx/logs/snakemake -type f -mtime +30 -delete
find /data/cygnusx/logs/snakemake -type d -empty -delete
```

### 3.6 审计日志

- **数据库表**：`audit_logs`。
- **中间件**：`src/cygnusx/middleware/audit.py` 自动记录写操作（POST/PUT/PATCH/DELETE）。
- **文本备份**：DB 写入成功后，`logger.bind(service="audit").info({...})` 写入应用 JSON 日志。
- **查询示例**：

```bash
jq 'select(.record.extra.service == "audit")' /data/cygnusx/logs/app/cygnusx.json.log
```

> 注意：当前审计 payload 作为 loguru message 写入，服务标签在 `.record.extra.service`。后续如需按 `user_id`、`resource_type` 做高效日志查询，建议改为专用审计 JSON sink 或 Promtail pipeline 解析 message。

---

## 4. Docker 挂载与 stdout 限制

### 4.1 挂载矩阵

> 下表宿主机路径为默认值示意：主栈 `deploy/docker/docker-compose.yml` 中实际为 `${CYGNUSX_DATA_ROOT:-/data/cygnusx}`，独立 worker 栈 `deploy/docker/docker-compose.worker.yml` 中实际为 `${WORKER_SHARED_DATA_DIR}`（由 `scripts/worker-compose.sh` 从 `data/worker_config.yaml` 加载）。

| 服务 | 容器内路径 | 宿主机路径 | 用途 |
| --- | --- | --- | --- |
| web | `/app/logs` | `/data/cygnusx/logs/app` | 应用日志 |
| beat | `/app/logs` | `/data/cygnusx/logs/app` | 应用日志 |
| worker | `/app/logs` | `/data/cygnusx/logs/app` | Worker 应用日志 |
| worker | 整个共享盘挂载到 `${STORAGE_PATH:-/data/cygnusx}` | `/data/cygnusx`（共享盘根） | Celery 单任务日志（非独立 bind mount，由容器内 env `CYGNUSX_CELERY_LOG_DIR=${STORAGE_PATH:-/data/cygnusx}/logs/celery/tasks` 指向共享盘子目录间接实现） |
| worker | `/logs` | `/data/cygnusx/logs/snakemake` | Snakemake 流程日志 |
| nginx | `/var/log/nginx` | `/data/cygnusx/logs/nginx` | 访问/错误日志 |

### 4.2 Docker stdout 日志限制

`deploy/docker/docker-compose.yml` 与 `deploy/docker/docker-compose.worker.yml` 使用统一 logging 配置：

```yaml
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "3"
```

各服务通过 `logging: *default-logging` 继承该策略，限制 Docker 自身保存的 stdout/stderr 日志，避免文件日志已经轮转但 Docker daemon 日志继续膨胀。

---

## 5. Loki 接入预留

当前可采集入口：

- `app/cygnusx.json.log`：loguru JSON，每行包含 `.record.extra.service`。
- `nginx/access.log`：Nginx JSON，每行包含 `service="nginx"`。
- `audit`：当前在 `app/cygnusx.json.log` 中以 `service="audit"` 标记。

建议后续新增 `deploy/docker/docker-compose.monitoring.yml`：

- `loki`：日志存储与查询。
- `promtail`：只读挂载 `/data/cygnusx/logs`，按路径和 JSON 字段提取 label。

Grafana 查询示例：

```logql
{service="web"} |= "ERROR"
{service="audit"} |= "resource_type"
{service="nginx"} | json | status >= 500
```

---

## 6. 清理策略

| 日志类型 | 清理方式 | 默认策略 |
| --- | --- | --- |
| 应用主日志 / JSON / error | loguru | 50 MB 轮转，30 天保留，zip 压缩 |
| Celery 单任务日志 | loguru | 20 MB 轮转，7 天保留，zip 压缩 |
| Docker stdout/stderr | Docker json-file | 50 MB × 3 个文件 |
| Nginx access/error | 宿主机 logrotate | 100 MB 或 daily，保留 14 轮，压缩 |
| Snakemake stdout/stderr | 宿主机 logrotate + crontab | 200 MB 或 daily，保留 7 轮，建议 30 天清理旧文件 |
| DB 任务日志 | repository 截断 | 单条 8192 字符，单任务最近 1000 条 |

---

## 7. 排障速查表

| 现象 | 排查路径 |
| --- | --- |
| `/data/cygnusx/logs/app` 无应用日志 | 检查 `CYGNUSX_LOG_DIR=/app/logs`、目录权限、`/data/cygnusx/logs/app:/app/logs` 挂载；注意目录不可写时日志会依次回退到 `./logs` 和 `/tmp/cygnusx/logs`（见 stdout 中的实际落盘路径） |
| Worker/Beat 日志没有进入 `cygnusx.log` | 检查 `src/cygnusx/infrastructure/celery_app/celery.py` 是否调用 `setup_logging()`，以及 `SERVICE_NAME` 是否设置 |
| Celery 单任务文件不存在 | 检查 `task_cls=LoggedTask`、`CYGNUSX_CELERY_LOG_DIR`、`/data/cygnusx/logs/celery/tasks` 权限 |
| Docker daemon 日志过大 | 检查 compose 服务是否带 `logging: *default-logging` |
| Nginx 文件日志过大 | 安装并验证 `deploy/logrotate/cygnusx-logs` |
| Snakemake 日志目录为空 | 检查 worker 是否挂载 `/data/cygnusx/logs/snakemake:/logs`，以及 `work_dir` 是否非空 |
| 审计日志未进 JSON | 检查 `AuditMiddleware` 注册顺序和 `logger.bind(service="audit")`，查询字段使用 `.record.extra.service` |
| 任务详情日志缺少早期大量日志 | 检查 `TASK_LOG_MAX_ENTRIES`，DB 默认只保留最近 1000 条，文件日志仍可查完整任务输出 |

---

## 8. 更新约定

新增日志相关功能时，请遵循：

1. **统一目录**：持久化文件日志必须落到 `/data/cygnusx/logs/` 下对应子目录。
2. **容量上限**：新增文件日志必须明确 rotation、retention、compression 或 logrotate 策略。
3. **环境变量控制**：服务标识、日志级别、落盘目录和保留策略通过环境变量控制。
4. **JSON 优先**：供机器抓取的日志优先输出 JSON（loguru `serialize=True` 或 Nginx `escape=json`）。
5. **不影响主流程**：日志写入失败必须降级，不能导致请求或任务失败。
6. **同步更新文档**：新增目录、环境变量、sink、轮转策略时，同步更新 `log_architecture.md` 与 `README.md`「日志排查」章节。

---

## 9. 本次代码与架构更新记录

> 迁出说明（2026-09-18）：原 §9.2–§9.6（云端沙盒终端资源配置链路、参考基因组库升级为数据库模块、前端入口与路由兼容、JBrowse 配置模型兼容扩展、参考数据库离线构建边界）与日志主题无关，已整段迁至 `database_architecture.md` 附录《Terminal 与参考基因组模块更新记录》，原文内容以该附录为准；本章仅余 §9.1，编号顺延保持不变。

### 9.1 日志容量治理

- `src/cygnusx/core/logging.py`：统一 loguru stdout、文本日志、JSON 日志和 error 日志 sink，支持 `CYGNUSX_LOG_ROTATION`、`CYGNUSX_LOG_RETENTION`、`CYGNUSX_LOG_COMPRESSION` 控制轮转、保留与压缩。
- `src/cygnusx/infrastructure/celery_app/logging.py`：Celery 单任务日志迁移到 loguru sink，支持单任务文件轮转、保留、压缩，并在 sink 创建失败时降级为 warning，不阻断任务。
- `src/cygnusx/infrastructure/database/repositories/task_repository.py`：任务 DB 日志增加单条 message 截断和最大条数限制，避免长 stdout/stderr 撑大数据库字段。
- `deploy/docker/docker-compose.yml`、`deploy/docker/docker-compose.worker.yml`：统一 Docker `json-file` stdout/stderr 大小限制，并挂载 `/data/cygnusx/logs/*` 到对应容器路径。
- `deploy/logrotate/cygnusx-logs`：为 Nginx 与 Snakemake 文件日志提供宿主机轮转兜底。
