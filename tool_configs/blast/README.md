# BLAST 工具配置

本目录是 OmicHub BLAST 模块的配置与运维入口。运行代码位于
`src/omichub/tools/blast/`，管理端和检索端分别位于
`frontend/src/views/AdminBlastDatabasesView.vue` 与
`frontend/src/views/BioTools/BlastSearchView.vue`。

## 文件说明

| 文件 | 作用 |
|------|------|
| `blast_config.yaml` | 输入限制、执行方式、线程、超时、队列、program 映射和默认参数 |
| `blast_db.yaml` | BLAST 数据库声明清单；由 PostgreSQL 元数据自动同步 |
| `ARCHITECTURE.md` | 数据模型、任务链路、缓存、SSE、版本管理、API、部署和排障 |
| `README.md` | 快速使用与常用配置 |

## 当前能力

- 支持 `blastn`、`blastp`、`blastx`、`tblastn`、`tblastx` 自动推断。
- 查询任务和建库任务分别进入 `blast_search`、`blast_db_build` 队列。
- 结果以结构化 JSON、NCBI XML（outfmt 5）和标准 Text（outfmt 0）下载。
- 任务状态通过 Redis Pub/Sub + SSE 实时推送，断流时前端自动回退轮询。
- 相同数据库版本、序列和参数的查询缓存 24 小时。
- 支持任务历史搜索、结果排序、分页和大结果虚拟滚动。
- 支持数据库分片上传、版本族自动切换和管理员回滚。
- 用户任务接口按所有者隔离；排队任务取消后即使 worker 重启也不会执行。

## 快速开始

### 1. 创建数据库

1. 管理员进入 **BLAST 数据库管理**。
2. 填写名称、`db_key`、`db_type`、版本和 `version_group`。
3. 上传 `.fasta`、`.fa`、`.fna` 或 `.faa` 文件。
4. 等待 `makeblastdb` 任务变为 `ready`。

前端对小文件使用 multipart 直传；文件大于 32 MB 时自动调用分片接口。
后端分片大小由 `database_upload_chunk_size_mb` 控制，当前为 16 MB；单个数据库
文件上限由 `max_database_file_size_mb` 控制，当前为 10 GB。

同一 `version_group` 中，新版本构建成功后自动成为 `is_active: true`，旧版本自动
停用。管理员可点击“激活此版本”回滚；普通用户只能看到 `ready + public + active`
的版本。

### 2. 执行查询

1. 进入 **生物信息工具箱 → BLAST 检索**。
2. 选择当前激活的数据库。
3. 粘贴 FASTA 或纯序列，设置 E-value、最大命中数等参数。
4. 提交后可留在结果页查看 SSE 进度，也可在任务历史页继续跟踪。
5. 完成后可下载 JSON、XML、Text 三种格式。

重复提交仅标题不同、但数据库版本、序列和参数完全相同的请求时，标题不会参与
缓存键计算，接口会直接返回 `completed` 和“命中缓存”。

### 3. 常用 API

```text
GET    /api/v1/blast/databases
POST   /api/v1/blast/submit
GET    /api/v1/blast/tasks
GET    /api/v1/blast/tasks/{task_id}
GET    /api/v1/blast/tasks/{task_id}/events
POST   /api/v1/blast/tasks/{task_id}/cancel
GET    /api/v1/blast/results/{task_id}
GET    /api/v1/blast/download/{task_id}/{json|xml|text}
```

管理员接口：

```text
GET    /api/v1/blast/admin/databases
POST   /api/v1/blast/admin/databases
POST   /api/v1/blast/admin/database-uploads
PUT    /api/v1/blast/admin/database-uploads/{upload_id}/chunks/{chunk_index}
POST   /api/v1/blast/admin/database-uploads/{upload_id}/complete
GET    /api/v1/blast/admin/databases/{db_id}/build-status
POST   /api/v1/blast/admin/databases/{db_id}/rebuild
POST   /api/v1/blast/admin/databases/{db_id}/activate
DELETE /api/v1/blast/admin/databases/{db_id}
POST   /api/v1/blast/admin/databases/sync-from-yaml
GET    /api/v1/blast/admin/tasks
POST   /api/v1/blast/admin/cleanup/old?days=7
POST   /api/v1/blast/admin/cleanup/all?confirm=true
GET    /api/v1/blast/admin/storage-stats
```

所有接口均要求 Bearer JWT；管理员接口还要求管理员角色。

### 3. 数据保留与下载

- BLAST 任务结果文件默认保留 **7 天**，到期后自动清理；页面顶部有持久提示。
- 完成后可点击 **JSON / XML / Text** 按钮下载对应格式。
- 如果下载按钮提示失败，请确认前端 `dist` 已重新构建（`npm run build`），旧版本会
  因下载 URL 双 `/api/v1` 前缀导致 404。

## `blast_db.yaml`

`blast_db.yaml` 是数据库声明清单，与 `blast_databases` 表同步。通过页面/API
创建、构建、激活、删除数据库后，文件会自动重写。不要在同步过程中并行手工编辑。

示例：

```yaml
databases:
  - db_key: "rice_pan_genome_v2"
    name: "水稻泛基因组 v2"
    db_type: "nucl"
    path: "/data/omichub/blast/db/rice_pan_genome_v2/rice_pan_genome_v2"
    description: "水稻泛基因组核酸序列库"
    source_species: "Oryza sativa"
    source_version: "v2.1"
    version_group: "rice_pan_genome"
    is_active: true
    is_public: true
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `db_key` | 是 | 唯一目录标识，仅允许小写字母、数字和下划线 |
| `name` | 是 | 页面显示名称 |
| `db_type` | 是 | `nucl` 或 `prot` |
| `path` | 是 | BLAST 索引前缀路径，不含 `.nin/.pin` 等后缀 |
| `description` | 否 | 数据库说明 |
| `source_species` | 否 | 来源物种 |
| `source_version` | 否 | 数据版本 |
| `version_group` | 否 | 版本族；为空时使用 `db_key` |
| `is_active` | 否 | 是否为版本族当前版本 |
| `is_public` | 否 | 是否公开，默认 `true` |

手工新增后执行：

```bash
curl -X POST http://localhost:8888/api/v1/blast/admin/databases/sync-from-yaml \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

同步规则：

- 已存在的 `db_key` 跳过，不覆盖数据库记录。
- 索引存在时导入为 `ready`。
- 索引不存在时导入为 `pending` 并触发 `makeblastdb`。
- 同一版本族只能有一个激活版本；普通列表只返回激活版本。

## `blast_config.yaml`

常用配置：

```yaml
input_limits:
  max_query_sequence_length: 50000
  max_target_seqs: 100
  max_database_file_size_mb: 10240
  database_upload_chunk_size_mb: 16

execution:
  use_docker: false
  num_threads: 10
  search_timeout: 3000
  build_timeout: 3600
  search_queue: "blast_search"
  build_queue: "blast_db_build"

defaults:
  evalue: 1.0e-5
  max_target_seqs: 10
  result_format: "json"
```

配置加载器按文件 mtime 热重载。新增 YAML 字段前必须先在
`src/omichub/tools/blast/config.py` 中声明；未知字段会被忽略。

## 部署要点

- Worker 镜像必须安装 `ncbi-blast+`，包括 `makeblastdb`、查询程序和
  `blast_formatter`。当前 `deploy/docker/Dockerfile.worker` 已通过
  `apt-get install ncbi-blast+` 安装；容器重建后不会丢失。
- 若改用 Docker 模式（`use_docker: true`），worker 容器需要挂载 Docker socket，且
  镜像中仍需 `ncbi-blast+` 用于本地回退或 `blast_formatter`。
- `deploy/docker/docker-compose.worker.yml` 的 `command` 已包含
  `-Q analysis,blast_search,blast_db_build`，确保 worker 消费 BLAST 专属队列。
- Web 与 worker 必须共享 `/data/omichub`，否则缓存命中任务无法复用结果文件。
- Redis 同时承载 Celery broker/backend、结果缓存和任务事件 Pub/Sub。
- `tool_configs/blast` 需要对 web 与 worker 可读；自动同步 YAML 的进程需要写权限。
- 运行 `alembic upgrade head`，当前 BLAST 迁移 head 为数据库版本字段迁移之后的 head。
- 大文件直传需要 nginx 放宽 body size；分片接口的单块默认只有 16 MB。
- 50 用户瞬时并发会超过通用 nginx `10r/s, burst=20` 限流。部署时应为
  `/api/v1/blast/` 配置独立限流区；建议 `50r/s, burst=100`，并将限流响应设为 429。

开发环境更新 worker 代码后执行：

```bash
./scripts/worker-compose.sh build worker
./scripts/worker-compose.sh up -d worker
```

## 已验证行为（2026-07-15）

- 真实 TRA10 查询完成，SSE 返回终态。
- JSON、XML、标准 Text 三种下载均返回 200；下载 URL 不再出现双 `/api/v1` 前缀。
- 同序列不同标题可在约 0.1 秒内直接命中缓存。
- 非任务所有者访问返回 404。
- worker 离线时取消排队任务，worker 重启后仍保持 `cancelled`，且不生成结果目录。
- 分片上传、版本自动激活、版本回滚和硬删除清理通过真实 API 验证。
- 管理页存储统计正常显示，不再因 `path.stat()` coroutine 异常返回 500。
- 10 个不同查询并发提交后全部进入 `completed`，平均提交响应约 366 ms。
- 50 个瞬时请求在应用层之前被现有通用 nginx 限流拦截；需完成上面的 BLAST
  专用限流配置后重新验收“零失败、平均响应低于 3 秒”。

## 相关文件

- `src/omichub/tools/blast/`
- `tests/unit/tools/test_blast_core.py`
- `tests/integration/test_blast_api.py`
- `tests/performance/locust_blast.py`
- `docs/26.7.15/omichub_blast_upgrade_plan.md`
