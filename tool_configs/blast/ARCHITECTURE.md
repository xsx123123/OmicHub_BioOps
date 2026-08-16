# OmicHub BLAST 模块架构说明

> 实现目录：`src/omichub/tools/blast/`；配置目录：`tool_configs/blast/`；API 前缀：`/api/v1/blast`。

## 1. 目标与边界

BLAST 模块负责本地序列检索、数据库构建、结果持久化和任务管理。Web 进程只做
校验、元数据和文件协调；CPU 密集型 `blast*`/`makeblastdb` 命令由 Celery worker
执行。

核心能力：

- 核酸/蛋白序列类型识别和 program 自动推断。
- 查询、建库分队列执行。
- JSON/XML/Text 多格式结果。
- Redis 结果缓存和 SSE 状态事件。
- 数据库分片上传、版本族自动切换和回滚。
- 用户所有权隔离、管理员 RBAC、持久取消语义。

## 2. 代码结构

```text
src/omichub/tools/blast/
├── __init__.py
├── api.py          # FastAPI 用户端和管理端路由
├── cache.py        # SHA-256 结果缓存键与 Redis 读写
├── config.py       # blast_config.yaml 模型和 mtime 热重载
├── core.py         # 命令构造、执行、ASN.1 转换、XML 解析、建库
├── events.py       # Redis Pub/Sub 状态事件
├── schema.py       # API DTO 和参数约束
├── service.py      # 权限范围、上传、版本、任务和下载业务逻辑
├── tasks.py        # Celery 查询与建库任务
└── yaml_sync.py    # blast_db.yaml 双向同步
```

相关入口：

```text
src/omichub/infrastructure/database/models/blast.py
src/omichub/infrastructure/celery_app/celery.py
frontend/src/api/blast.ts
frontend/src/views/BioTools/BlastSearchView.vue
frontend/src/views/BioTools/BlastTaskHistoryView.vue
frontend/src/views/AdminBlastDatabasesView.vue
```

## 3. 外置配置

### 3.1 `blast_config.yaml`

配置模型只接受 `config.py` 已声明字段，未知字段会被忽略。

| 区域 | 字段 | 说明 |
|------|------|------|
| `input_limits` | `max_query_file_size_mb` | 查询文件上限 |
| `input_limits` | `max_query_sequence_length` | 单次查询序列字符上限 |
| `input_limits` | `max_target_seqs` | API 允许的最大命中数 |
| `input_limits` | `max_database_file_size_mb` | 数据库 FASTA 总大小上限 |
| `input_limits` | `database_upload_chunk_size_mb` | 分片大小及单片上限 |
| `execution` | `use_docker` | 本地 BLAST+ 或 `docker run` |
| `execution` | `num_threads` | 单个查询使用线程数 |
| `execution` | `search_timeout` | 查询命令超时秒数 |
| `execution` | `build_timeout` | `makeblastdb` 超时秒数 |
| `execution` | `search_queue` | 查询队列说明值 |
| `execution` | `build_queue` | 建库队列说明值 |
| `program_map` | - | 查询类型/数据库类型到 program 的映射 |
| `defaults` | - | 前端方法接口返回的默认参数 |

当前 Celery task 装饰器固定使用 `blast_search` 和 `blast_db_build`；修改 YAML 中的
队列名之前，需要同步修改 task 路由和 worker 消费队列。

### 3.2 `blast_db.yaml`

这是可读、可声明的数据库镜像，不替代 PostgreSQL。页面/API 的元数据写入数据库后，
服务会重新生成该文件；手工条目可通过 `sync-from-yaml` 导入。

`version_group` 表示同一逻辑数据库的版本族，`is_active` 表示当前版本。对用户公开的
数据库必须同时满足：

```text
build_status == ready
is_public == true
is_active == true
```

## 4. 数据模型

### 4.1 `blast_databases`

| 字段 | 含义 |
|------|------|
| `id` | UUID 主键 |
| `name` | 显示名称 |
| `db_key` | 唯一文件目录标识 |
| `db_type` | `nucl` / `prot` |
| `source_species` | 来源物种 |
| `source_version` | 来源版本 |
| `version_group` | 版本族 |
| `is_active` | 当前激活版本 |
| `file_path` | BLAST 索引前缀 |
| `file_size_mb` | FASTA 大小 |
| `sequence_count` | 序列数 |
| `build_status` | `pending/building/ready/failed/deprecated` |
| `is_public` | 是否公开 |
| `created_by` | 创建管理员 |
| `build_log` | 建库日志或错误 |

### 4.2 `blast_tasks`

| 字段 | 含义 |
|------|------|
| `task_id` | Celery task id，同时作为公开任务标识 |
| `user_id` | 任务所有者 |
| `db_id` | 目标数据库版本 |
| `program` | 实际 BLAST program |
| `query_title/query_sequence` | 标题与规范化 FASTA |
| 参数字段 | E-value、命中数、word/gap 参数 |
| `status/progress` | 生命周期与进度 |
| `result_path` | XML 文件绝对路径；Text 位于同目录 |
| 摘要字段 | 命中数、top identity、top E-value |
| 时间字段 | submitted/started/completed |

用户任务、结果、下载、SSE 和取消接口均以 `user_id` 限定查询。管理员任务监控通过
独立管理接口访问，普通任务接口不会因为用户是管理员而绕过所有权检查。

## 5. 存储布局

```text
/data/omichub/blast/
├── db/{db_key}/
│   ├── {db_key}.fasta
│   └── {db_key}.n* / .p*       # makeblastdb 原子替换后的索引
├── uploads/{user_id}/{task_id}/query.fasta
├── database_uploads/{user_id}/{upload_id}/
│   ├── manifest.json
│   └── chunk-000000 ...        # complete 后清理
└── results/{user_id}/{task_id}/
    ├── query.fasta
    ├── result.asn              # BLAST outfmt 11 archive
    ├── result.xml              # blast_formatter outfmt 5
    ├── result.txt              # blast_formatter outfmt 0
    └── result.json             # 下载时按需生成
```

Web 与 worker 必须挂载同一个 `/data/omichub`。Redis 缓存只保存结果路径和摘要，不
保存大型结果内容，因此共享存储不可缺失。

## 6. 查询链路

```text
POST /submit
  │
  ├─ JWT 用户解析与数据库可见性检查
  ├─ FASTA 规范化、长度限制、序列类型检测
  ├─ program 推断与参数兼容性校验
  ├─ 计算缓存键并检查 Redis
  │    └─ 命中：创建 completed 任务，复用已有 result_path
  └─ 未命中：创建 queued 任务并以 task_id 投递 blast_search
         │
         ├─ worker 再检查任务是否已 cancelled
         ├─ 状态 running，发布 Redis 事件
         ├─ BLAST 单次执行，输出 result.asn (outfmt 11)
         ├─ blast_formatter 生成 XML (5) 与 Text (0)
         ├─ XML 解析为 hits 和摘要
         ├─ 完成前 refresh，避免覆盖并发取消状态
         ├─ 写数据库与 24h Redis 缓存
         └─ 发布 completed/failed/cancelled 事件
```

### 6.1 缓存键

Redis key：

```text
blast:result:{sha256}
```

SHA-256 输入包括：

- 数据库 UUID 与版本标识（`source_version + updated_at`）。
- program。
- 去除 FASTA 标题和所有空白、统一大写后的序列。
- E-value、最大命中数、word size、gap open、gap extend。

查询标题、用户 ID 和结果展示格式不参与缓存键。缓存 TTL 当前固定为 24 小时。
Redis 不可用或结果文件已清理时静默降级为正常执行。

### 6.2 SSE 事件

事件通道：

```text
blast:task:{task_id}:events
```

事件载荷包含 `task_id/status/progress/message/error_message/timestamp`。API 使用
`GET /tasks/{task_id}/events` 输出 `text/event-stream`；先发送数据库快照，再订阅
Redis。终态立即关闭流，空闲 15 秒发送 keep-alive。前端通过 `fetch` 流式读取以携带
Bearer Header，连接失败时回退状态轮询。

## 7. 数据库构建、分片与版本

### 7.1 分片上传

```text
POST /admin/database-uploads
  -> upload_id, chunk_size_bytes, total_chunks
PUT  /admin/database-uploads/{upload_id}/chunks/{index}
POST /admin/database-uploads/{upload_id}/complete
```

约束：

- `upload_id` 必须是 32 位小写十六进制，防止路径穿越。
- chunk index 必须位于声明范围内。
- 单片不得超过配置大小。
- 合并后的字节数必须严格等于初始化声明的 `total_size`。
- complete 无论成功或失败都会清理临时上传目录。

### 7.2 原子建库

FASTA 先写入数据库目录。`makeblastdb` 在临时前缀上构建成功后再替换正式索引，避免
失败构建破坏现有版本。建库状态按 `pending -> building -> ready/failed` 更新。

### 7.3 版本切换

- 创建时未提供 `version_group`，默认使用 `db_key`。
- 新版本只有在 `makeblastdb` 成功后才激活。
- 激活新版本时，同版本族其他记录全部设为 `is_active=false`。
- `POST /admin/databases/{db_id}/activate` 可回滚到任意 `ready` 版本。
- 软删除当前版本时，自动激活同版本族最新的其他 `ready` 版本。
- 有关联查询任务的数据库禁止硬删除。

## 8. API 概览

### 8.1 用户接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/databases` | 当前用户可见的激活数据库 |
| GET | `/methods` | program 映射和默认参数 |
| POST | `/submit` | 提交或命中缓存 |
| GET | `/tasks` | 分页历史，支持 `status/search` |
| GET | `/tasks/{task_id}` | 状态与参数 |
| GET | `/tasks/{task_id}/events` | SSE 状态流 |
| POST | `/tasks/{task_id}/cancel` | 取消 queued/running |
| GET | `/results/{task_id}` | 结构化命中结果 |
| GET | `/download/{task_id}/{format}` | `json/xml/text` 下载 |

### 8.2 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/databases` | 全部版本与状态 |
| POST | `/admin/databases` | multipart 直接上传 |
| POST | `/admin/database-uploads` | 初始化分片上传 |
| PUT | `/admin/database-uploads/{upload_id}/chunks/{index}` | 上传分片 |
| POST | `/admin/database-uploads/{upload_id}/complete` | 合并并创建数据库 |
| GET | `/admin/databases/{db_id}/build-status` | 构建状态 |
| POST | `/admin/databases/{db_id}/rebuild` | 重建索引 |
| POST | `/admin/databases/{db_id}/activate` | 激活/回滚版本 |
| DELETE | `/admin/databases/{db_id}` | 软删除或硬删除 |
| POST | `/admin/databases/sync-from-yaml` | 导入 YAML 条目 |
| GET | `/admin/tasks` | 全平台任务监控 |
| POST | `/admin/cleanup/old?days=7` | 清理 N 天前结果文件 |
| POST | `/admin/cleanup/all?confirm=true` | 清理所有结果文件 |
| GET | `/admin/storage-stats` | 任务数、清理数、存储占用 |

## 9. 数据清理与保留策略

BLAST 任务结果文件默认保留 7 天，7 天后自动清理会删除结果 XML/TXT/JSON 和上传的
查询序列，但保留数据库记录（状态变为 `cleaned`），便于审计和复跑。清理通过以下方式
触发：

- 管理员在 **BLAST 存储管理** 页面点击“清理 7 天前数据”或“清理所有数据”。
- 调用 `POST /api/v1/blast/admin/cleanup/old?days=7`。
- 调用 `POST /api/v1/blast/admin/cleanup/all?confirm=true`（危险操作，需显式确认）。

`GET /api/v1/blast/admin/storage-stats` 返回任务总数、已完成数、已清理数和结果目录
磁盘占用（MB），用于管理员评估存储压力。该接口使用同步 `os.walk` 在线程池中遍历结
果目录，避免在事件循环中直接调用大量 `path.stat()`。

## 10. Celery 与 Redis

队列：

```text
analysis
blast_search
blast_db_build
```

当前独立 worker 同时消费三个队列。查询 task id 与数据库 `task_id` 相同，因此取消接口
可以准确 revoke 对应 Celery 消息。worker 启动时仍以数据库状态为最终依据，解决 worker
离线期间 revoke 广播无法持久化的问题。

Redis 用途：

```text
DB 1  Celery broker（按部署环境 URL 为准）
DB 2  Celery result backend（按部署环境 URL 为准）
应用 Redis client  BLAST result cache + Pub/Sub events
```

启用 Redis 密码后，所有 URL 和应用 client 必须使用同一密码。修改环境变量需要重新创建
容器，而非仅 `docker restart`。

## 11. 前端行为

- 搜索页：数据库选择、参数、提交、SSE、轮询降级、结果排序和分页；页面顶部显示 7 天
  数据保留提示。
- 结果表：限制高度并启用虚拟滚动，避免大量 hits 一次性撑开 DOM。
- 下载：JSON/XML/Text 三按钮；下载地址使用相对路径，避免与 `apiClient.baseURL` 叠加
  产生 `/api/v1/api/v1/blast/download/...` 404。
- 历史页：按状态和任务标题/ID 搜索，可恢复查看结果。
- 管理页：直接/分片上传、构建状态、版本族、当前版本、激活回滚、删除、存储统计与清
  理操作。
- 序列分析侧栏可识别当前文本并跳转到 BLAST 页面。

## 12. 部署检查

- [ ] Alembic 已升级到包含 `blast_databases`、`blast_tasks`、`version_group`、
      `is_active` 的 head。
- [ ] Worker 中 `blastn`、`blastp`、`blast_formatter`、`makeblastdb` 可执行。
      生产环境推荐在 `Dockerfile.worker` 中安装 `ncbi-blast+`（当前已安装），或启用
      `use_docker: true` 并挂载 Docker socket。
- [ ] Worker 监听 `blast_search`、`blast_db_build`；`docker-compose.worker.yml`
      的 `command` 已包含 `-Q analysis,blast_search,blast_db_build`。
- [ ] Web、worker 共享 `/data/omichub`。
- [ ] Redis 认证正确，缓存和 Pub/Sub 可访问。
- [ ] `tool_configs/blast` 对同步进程可写。
- [ ] nginx 允许数据库上传体积，并为 BLAST API 配置满足目标并发的独立限流。
- [ ] 前端已构建并部署最新 `dist`。

### 12.1 推荐 nginx 限流

通用 API 的 `10r/s, burst=20` 无法承载 50 个瞬时 BLAST 提交。推荐：

```nginx
limit_req_zone $binary_remote_addr zone=blast_api_limit:10m rate=50r/s;
limit_req_status 429;

location ^~ /api/v1/blast/ {
    limit_req zone=blast_api_limit burst=100 nodelay;
    proxy_pass http://omichub_backend;
    proxy_read_timeout 86400;
}
```

数据库大文件直传的更长前缀 location 仍需保留 `client_max_body_size 10g` 和
`proxy_request_buffering off`。

## 13. 验证与测试

```bash
uv run pytest -q tests/unit/tools/test_blast_core.py
uv run pytest -q tests/integration/test_blast_api.py
uv run ruff check src/omichub/tools/blast tests/unit/tools/test_blast_core.py
cd frontend && npm run type-check && npm run build
```

性能脚本：

```bash
OMICHUB_ACCESS_TOKEN=<token> \
OMICHUB_BLAST_DB_ID=<db-uuid> \
uvx locust -f tests/performance/locust_blast.py \
  --host http://localhost:8888 \
  --headless --users 50 --spawn-rate 5 --run-time 10m
```

2026-07-15 实机验收已证明：真实查询、SSE 终态、三格式下载、缓存、所有权隔离、
持久取消、分片上传、版本切换与回滚、10 个并发真实查询均正常。50 瞬时请求当前被
通用 nginx 限流返回 503；完成 12.1 配置并 reload 后需重跑最终性能门禁。

## 14. 故障排查

| 现象 | 原因与处理 |
|------|------------|
| 点击 XML/JSON/Text 提示“下载失败” | `getBlastDownloadUrl()` 曾返回带 `/api/v1` 前缀的绝对路径，与 `apiClient.baseURL` 叠加成 `/api/v1/api/v1/blast/download/...`；已修复为相对路径 `/blast/download/{taskId}/{format}` |
| BLAST 存储管理提示“系统内部错误” | `storage-stats` 在线程池外调用 `path.stat()` 偶发 coroutine 异常；已改为 `os.walk` 单线程遍历 |
| Text 下载 404 | 旧实现错误地把 XML 作为 `blast_formatter -archive` 输入；新任务应先生成 `result.asn`，再转换 XML/Text |
| 同序列不同标题不命中缓存 | 缓存键必须去除 FASTA header；确认 web 与 worker 都已更新并重启 |
| 取消任务在 worker 重启后又执行 | worker 必须在执行前检查数据库 `cancelled` 状态 |
| 50 并发出现 503 且无 upstream time | nginx `limit_req` 拦截；应用未收到请求，配置 BLAST 独立限流 |
| 任务一直 queued | worker 未消费 `blast_search`；检查 `active_queues` |
| 建库一直 pending | worker 未消费 `blast_db_build` 或 `makeblastdb` 缺失 |
| `Authentication required` | Redis URL 缺少密码，重新创建容器 |
| 数据库构建失败后旧索引损坏 | 应检查是否使用临时前缀构建后原子替换 |
| 缓存命中但下载文件不存在 | Web/worker 未共享存储，或结果已被清理；缓存读取会删除失效 key 并降级执行 |
| 普通用户看不到版本 | 记录必须同时为 `ready/public/active` |
| YAML 不更新 | `tool_configs/blast` 挂载只读或同步异常 |

## 15. 近期修复记录

### 2026-07-15

- **下载 URL 双前缀修复**：`frontend/src/api/blast.ts` 的 `getBlastDownloadUrl()` 现在
  返回相对路径 `/blast/download/{taskId}/{format}`，与 `apiClient.baseURL = /api/v1` 组
  合成正确的 `/api/v1/blast/download/{taskId}/{format}`。
- **管理页存储统计修复**：`service.get_storage_stats()` 改用 `os.walk` 在线程池中一次
  性计算目录大小，避免 `'coroutine' object has no attribute 'st_size'` 导致的 500。
- **7 天保留提示前置**：`BlastSearchView` 将数据保留告警从结果区移到页面工具栏下方，
  用户在提交前即可看到。
- **路径注释修正**：`blast_config.yaml` 中的结果路径注释已更新为包含 `{user_id}`。
- **测试补充**：新增 `test_get_storage_stats_calculates_size_and_counts` 与
  `test_get_storage_stats_returns_zero_when_directory_missing` 覆盖存储统计的两种场景。

## 16. 相关文件

- `docs/26.7.15/omichub_blast_upgrade_plan.md`
- `docs/26.7.15/omichub_blast_fix_v1.3.md`
- `docs/26.7.15/omichub_blast_fix_v1.4.md`
- `docs/26.7.15/omichub_blast_fix_v1.5.md`
- `tests/unit/tools/test_blast_core.py`
- `tests/integration/test_blast_api.py`
- `tests/performance/locust_blast.py`
- `frontend/src/types/blast.ts`
