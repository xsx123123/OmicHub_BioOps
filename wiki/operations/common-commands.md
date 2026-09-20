# 常用命令

以 `make help` 的实际输出为准；下表列出当前最常用的安全入口。

## 开发与质量

| 目的 | 命令 |
| --- | --- |
| 启动后端开发服务器 | `make dev` |
| 启动前端开发服务器 | `make frontend-dev` |
| 启动 Celery / RocketMQ Worker | `make dev-worker` / `make dev-rocketmq-worker` |
| 运行测试 | `make test` |
| 代码检查 / 格式化 / 类型检查 | `make lint` / `make format` / `make type-check` |
| 安装或构建前端 | `make frontend-install` / `make frontend-build` |

## 数据库与知识库

| 目的 | 命令 |
| --- | --- |
| 执行迁移 | `make migrate` |
| 创建 / 回滚 / 合并迁移 | `make migrate-new m="描述"` / `make migrate-rollback` / `make migrate-merge` |
| 检查迁移链 | `make check-migrations`、`make check-alembic-heads` |
| 初始化管理员 / 饼干策略 | `make init-admin` / `make init-cookies` |
| 同步 Markdown 知识库 | `make sync-knowledge` |
| 重建知识库分块与向量 | `make knowledge-reindex` |

## Docker 生命周期

| 目的 | 命令 |
| --- | --- |
| 启动主栈 / Worker 栈 / 全部 | `make docker-up` / `make docker-up-worker` / `make docker-up-all` |
| 停止主栈 / Worker 栈 / 全部 | `make docker-down` / `make docker-down-worker` / `make docker-down-all` |
| 查看主栈 / Worker 日志 | `make docker-logs` / `make docker-logs-worker` |
| 日常代码刷新 / 完整开发重载 | `make docker-dev-refresh` / `make docker-reload` |
| 修复运行目录权限 | `make docker-fix-permissions` |
| 清理容器网络 / 危险清理全部 Docker 资源 | `make docker-clean` / `make docker-purge` |

`docker-purge` 和 `docker-start` 会删除或重建 Docker 资源；执行前确认数据卷、镜像和构建缓存的影响。

## 可选运行组件

| 目的 | 命令 |
| --- | --- |
| 启动 RocketMQ 与对应 Worker | `make docker-up-rocketmq`、`make docker-up-rocketmq-worker` |
| 启动 pgvector 验收叠加并检查 | `make docker-up-pgvector`、`make pgvector-acceptance` |
| 启动跨机器控制面 / Worker | `make docker-up-cross-web`、`make docker-up-cross-worker` |
| 启动 AgentTeams / 本机 Matrix 开发栈 | `make docker-up-agentteams`、`make docker-up-matrix-dev` |
| 构建运行时和 Worker 镜像 | `make runtime-images-build`、`make docker-build-worker` |

## 镜像构建

| 目的 | 命令 |
| --- | --- |
| 富集 / DEG / 共线性 R 运行时镜像 | `make docker-build-enrichment` / `docker-build-deg` / `docker-build-synteny` |
| 全量重建沙盒与分析运行时镜像（含核对清单） | `make docker-build-sandboxes` |
| Studio 分析运行时三件套（core/plot/scrna） | `make runtime-images-build` |
| 一键重建所有镜像 | `make docker-build-all-images` |

镜像 tag 规范：发布产物必须打 git SHA 短号 tag（`IMAGE_TAG`），禁止 `latest` 裸推，见
`deploy/docker/README.md`。
