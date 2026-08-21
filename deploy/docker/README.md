# OmicHub Dockerfile 职责

`deploy/docker/` 统一存放 OmicHub 主服务、计算 Worker 和工具运行时镜像的 Dockerfile。
工具目录只保存运行配置、脚本、示例和数据契约；Dockerfile 不应放回 `tool_configs/`。

| Dockerfile | 镜像职责 | 构建上下文 | 主要入口 |
|---|---|---|---|
| `Dockerfile` | FastAPI Web、Celery Beat、Flower 共用的后端应用镜像 | 仓库根目录 | `docker compose -f deploy/docker/docker-compose.yml build` |
| `Dockerfile.frontend` | 构建 Vue 前端并由 Nginx 托管静态文件 | 仓库根目录 | 生产前端镜像构建 |
| `Dockerfile.worker` | 通用 Celery 计算 Worker，包含 Snakemake、Micromamba 和 Docker CLI；入口脚本降权时保留 Docker Socket GID | 仓库根目录 | `make docker-build-worker` |
| `Dockerfile.phylo` | 系统发育树专用 Worker，提供独立 Conda/生物信息学环境 | 仓库根目录 | `make docker-build-worker` |
| `Dockerfile.enrichment` | GO / KEGG 富集 R 运行时，提供 `clusterProfiler`、`enrichplot` | `tool_configs/enrichments` | `make docker-build-enrichment` |
| `Dockerfile.deg` | DEG 差异表达分析 R 运行时，提供 `DESeq2`、`edgeR`（含 1v1 无重复的固定 BCV 模式），脚本契约见 `tool_configs/deg/README.md` | `tool_configs/deg` | `make docker-build-deg` |

## 命名和构建约定

- 通用后端保留 `Dockerfile`；其他镜像统一命名为 `Dockerfile.<purpose>`。
- Dockerfile 位于 `deploy/docker/`，但可通过 `docker build -f` 使用工具目录作为构建上下文。
- 每个 Dockerfile 文件头必须说明用途、构建上下文和推荐 Make 入口。
- 面向开发者和部署脚本的稳定入口必须是 Make target，不在文档中依赖容易失效的裸 `docker build` 路径。
- 高计算量工具镜像必须在对应 Worker 启动前完成构建；`make docker-up-worker` 和 `make docker-start` 应自动满足该依赖。

## 镜像 tag 与版本可观测规范

- **禁止 `latest` 裸推**：任何推送/发布的镜像必须打 git SHA 短号 tag，即 `make` 导出的
  `IMAGE_TAG`（默认 `git rev-parse --short HEAD`）。本地 `docker compose build` 的开发
  路径不受此约束，但不允许把未打 SHA tag 的镜像推送到任何 registry。
- 主栈后端镜像构建时经 `OMICHUB_BUILD_SHA` / `OMICHUB_BUILD_TIME` 构建参数注入版本信息
  （`Dockerfile` ARG → `APP_GIT_SHA` / `APP_BUILD_TIME` ENV），`/health` 返回
  `version` / `git_sha` / `build_time`；AgentTeams Bridge 镜像经 `BRIDGE_BUILD_SHA` /
  `BRIDGE_BUILD_TIME` 注入，`/healthz` 返回 `build_sha` / `build_time`。
- 上述变量由 Makefile 部署 target（`docker-up*` / `docker-reload` / `docker-start` 等）
  自动导出；绕过 Make 手工 `docker compose build` 时需自行 `export`，否则健康端点显示
  `unknown`。部署后核对：`/health(z)` 返回的 SHA 必须与发布 commit 一致。

## RocketMQ Worker 故障处置

- `rocketmq-worker` 使用有限的 `on-failure:5` 重启策略；连续启动失败会停在退出状态，而不是无限 crash loop。
- 告警应监控该容器退出、重启次数达到 5 次及消费积压；排查时先查看 `docker compose logs rocketmq-worker` 中的 nameserver 地址、Python 客户端加载和订阅 topic。
- 确认 `ROCKETMQ_NAMESRV_ADDR` 可达且镜像包含 `rocketmq-client-python==2.0.0` 后，再人工重启该服务；未恢复前将 `TASK_QUEUE_BACKEND` 保持为 `celery`，避免新任务继续投递到不可用的 RocketMQ。

## 基因组共线性运行时

`Dockerfile.synteny` 用于基因组共线性 Worker，构建上下文为 `tool_configs/synteny/`，不向 Web
容器提供 Docker Socket。使用 `make docker-build-synteny` 构建 `omichub-synteny:v1`；Worker 负责运行
MCScanX 思路的区块识别并输出结构化 TSV/JSON，浏览器使用 Plotly `scattergl` 渲染 dot plot。

## PolarDB PostgreSQL / pgvector

`docker-compose.pgvector.yml` is an acceptance overlay that replaces the local PostgreSQL image with `pgvector/pgvector:pg14` and adds PgBouncer plus PostgreSQL Prometheus exporter. Production PolarDB uses managed writer/read-only endpoints rather than this local database container. Run `make docker-up-pgvector` to start it, or `make pgvector-acceptance` to run pgvector, backup/restore, and metrics checks. See `deploy/docker/POLARDB_POSTGRES.md` for cutover, read-replica, connection-pool, and monitoring validation.
