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

## PolarDB PostgreSQL / pgvector

`docker-compose.pgvector.yml` is an acceptance overlay that replaces the local PostgreSQL image with `pgvector/pgvector:pg14` and adds PgBouncer plus PostgreSQL Prometheus exporter. Production PolarDB uses managed writer/read-only endpoints rather than this local database container. Run `make docker-up-pgvector` to start it, or `make pgvector-acceptance` to run pgvector, backup/restore, and metrics checks. See `deploy/docker/POLARDB_POSTGRES.md` for cutover, read-replica, connection-pool, and monitoring validation.
