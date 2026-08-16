# Docker 部署

OmicHub 将控制面与计算面拆分部署：主栈承载 Web、数据库、缓存和入口服务；Worker 栈独立承载
分析任务。日常部署优先使用 Makefile，不要绕过项目封装直接拼接 Compose 命令。

## 部署前准备

1. 复制 `.env.example` 为私有 `.env`，限制其读取权限。
2. 设置 `JWT_SECRET_KEY`、`APP_SECRET_KEY`、`REDIS_PASSWORD`、`POSTGRES_PASSWORD`、
   `AI_PROVIDER_KEY_ENCRYPTION_KEY`、`OMICHBUB_INIT_ADMIN_PASSWORD` 和实际 AI Provider 密钥。
3. 按需设置 `OMICHUB_DATA_ROOT`；默认运行数据目录为 `/data/omichub`。
4. 安装 Docker Compose、Node.js 和项目要求的运行环境。

请始终从仓库根目录运行 `make` 命令。主应用会通过 Compose 的 `env_file` 读取根 `.env`，而 Makefile
也会读取其中的关键运行变量以保持 Redis、数据目录和网络配置一致。

## 推荐启动方式

```bash
# 构建前端、准备网络与运行目录，并启动主栈和 Worker 栈
make docker-up-all

# 等待 Web 健康检查
make wait-web

# 执行数据库迁移并初始化管理员
make migrate
make init-admin

# 可选：初始化默认饼干定价策略
make init-cookies
```

`make docker-up` 只启动主栈；`make docker-up-worker` 只启动 Worker 栈。首次部署或同时更新两者时，
使用 `make docker-up-all` 更不容易遗漏依赖。Web 容器会挂载 `docs/` 和只读 `wiki/`，因此这两处的
Markdown 都能由 `make sync-knowledge` 载入运行中知识库。

## 更新、重载与回滚

| 场景 | 推荐命令 |
| --- | --- |
| 日常代码或 YAML 更新 | `make docker-dev-refresh` |
| 重新构建前端并刷新完整开发栈 | `make docker-reload` |
| 查看主栈 / Worker 日志 | `make docker-logs` / `make docker-logs-worker` |
| 停止全部服务，保留数据 | `make docker-down-all` |
| 清理容器与网络，保留数据卷和镜像 | `make docker-clean` |
| 不可逆地清除 Docker 资源 | `make docker-purge` |

数据库迁移、镜像重建和回滚的完整决策表见 [代码更新与回滚](update-rollback)。

## Worker、跨机与生产环境

- Worker 通过 `data/worker_config.yaml` 管理共享数据目录和流程目录；请使用
  `make docker-up-worker` 或 `./scripts/worker-compose.sh` 渲染并启动，不要手工跳过配置渲染。
- 单机扩展、跨机器 Worker、Slurm 和 Kubernetes 的演进路线见根目录 `README.md` 的“从单机扩展到
  HPC 与 Kubernetes”。
- 生产环境应使用 `deploy/docker/docker-compose.prod.yml` 覆盖、私网数据库/Redis、固定镜像 digest、
  SSL、备份和部署前健康检查。
- AgentTeams、RocketMQ、pgvector/PgBouncer 等可选组件按对应开关和部署文档启用，不应默认暴露到
  公网。

## 常见验证

```bash
make check-migrations
make check-alembic-heads
make sync-knowledge
```

Worker 镜像、交互式终端和排障命令见 [问题排查](../operations/troubleshooting)。
