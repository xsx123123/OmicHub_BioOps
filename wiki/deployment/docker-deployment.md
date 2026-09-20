# Docker 部署

CygnusX 将控制面与计算面拆分部署：主栈承载 Web、数据库、缓存和入口服务；Worker 栈独立承载
分析任务。日常部署优先使用 Makefile，不要绕过项目封装直接拼接 Compose 命令。

## 部署前准备

1. 复制 `.env.example` 为私有 `.env`，限制其读取权限。
2. 设置 `JWT_SECRET_KEY`、`APP_SECRET_KEY`、`REDIS_PASSWORD`、`POSTGRES_PASSWORD`、
   `AI_PROVIDER_KEY_ENCRYPTION_KEY`、`OMICHBUB_INIT_ADMIN_PASSWORD` 和实际 AI Provider 密钥。
3. 按需设置 `CYGNUSX_DATA_ROOT`；默认运行数据目录为 `/data/cygnusx`。
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

- Worker 通过 `data/worker_config.yaml` 管理共享数据目录和流程目录（`shared_data_dir` /
  `pipeline_dir`），容器内统一映射为 `/data/cygnusx`；请使用
  `make docker-up-worker` 或 `./scripts/worker-compose.sh` 渲染并启动，不要手工跳过配置渲染。
  **Web、Worker、计算节点必须看到一致的绝对路径**。
- **跨机器**：控制面与每台 Worker 各自维护私有 `.env`（共享密钥相同，网络/挂载路径按节点配置），
  分别执行 `make docker-up-cross-web` 与 `make docker-up-cross-worker`。
- **生产**：`docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.prod.yml up -d`
  （4 uvicorn worker + 关闭 DB/Redis 宿主端口 + SSL）；Worker 栈用
  `./scripts/worker-compose.sh --scale worker=N up -d` 水平扩展。生产 `APP_ENV=production` 时默认密钥
  会导致启动失败。
- **私有镜像仓库**：云部署建议在 CI 构建并按 git SHA 推送 `cygnusx-backend` / `cygnusx-worker` /
  `cygnusx-frontend` 及分析运行时镜像，节点只拉取不可变 digest；不要把 `.env`、密钥或数据目录打进镜像。
- **HPC / Kubernetes**：Slurm 接入（Worker 转为 `sbatch` 提交器 + Snakemake profile）与 K8s 高可用
  （无状态控制面 + 按队列拆分 Worker + RWX PVC）为规划路径，详见根目录
  `report/07_K8s大规模部署方案.md`、`report/09_管理节点与任务节点分离方案.md`。
- AgentTeams、RocketMQ、pgvector/PgBouncer 等可选组件按对应开关和部署文档启用，不应默认暴露到
  公网；AgentTeams 开启步骤见 [开启 Multi-Agent 与 AgentTeams](agentteams-enablement)。

## 常见验证

```bash
make check-migrations
make check-alembic-heads
make sync-knowledge
```

Worker 镜像、交互式终端和排障命令见 [问题排查](../operations/troubleshooting)。
