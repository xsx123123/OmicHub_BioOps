# CygnusX Dockerfile 职责

`deploy/docker/` 统一存放 CygnusX 主服务、计算 Worker 和工具运行时镜像的 Dockerfile。
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

## Studio/沙盒镜像映射与更新流程

镜像 tag 与配置的唯一登记表是 [`deploy/image-mapping.yaml`](../image-mapping.yaml)。当前映射如下：

| 用途 | 镜像 | Dockerfile | 主要配置来源 |
|---|---|---|---|
| 通用分析 | `cygnusx-analysis:core-v0.0.2dev` | `deploy/runtime-images/core.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml` |
| 绘图分析 | `cygnusx-analysis:plot-v0.0.2dev` | `deploy/runtime-images/plot.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml` |
| 单细胞分析 | `cygnusx-analysis:scrna-v0.0.3dev` | `deploy/runtime-images/scrna.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml`、`.env.example` |
| Studio base | `cygnusx-sandbox-base:v0.0.2dev` | `deploy/studio/base.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml` |
| Studio bio | `cygnusx-sandbox-bio:v0.0.2dev` | `deploy/studio/bio.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml` |
| 浏览器/办公 | `cygnusx-sandbox-browser-office:v0.0.2dev` | `deploy/studio/browser-office.Dockerfile` | `data/ai/runtime_images.yaml`、`data/ai/studio.yaml` |
| Copilot 执行沙盒 | `cygnusx-sandbox-copilot:v0.0.2dev` | `deploy/sandbox/Dockerfile` | `src/cygnusx/core/config.py` |
| 终端基础/子镜像 | `cygnusx-sandbox-terminal:*` | `tool_configs/terminal/docker/` | `tool_configs/terminal/terminal_images.yaml` |

Agent 的选择链是：`data/ai/<agent>.yaml` 中的 `studio.runtime_profile` ->
`data/ai/runtime_images.yaml` 的 `profiles.<profile>.image`。例如 `agent-scrna` 使用
`analysis-scrna`，`agent-viz` 使用 `analysis-plot`；不要直接在 Agent 文件中写另一个镜像 tag。

更新镜像时按以下顺序操作：

1. 先修改 `deploy/image-mapping.yaml` 中的最终镜像名和 tag。
2. 同步修改清单指出的 runtime/Studio/终端配置、`.env.example`、构建脚本和 Makefile 检查列表。
3. 运行 `make validate-image-mapping`；该命令同时检查 19 个启用 Agent 的 profile 映射。
4. 运行 `make docker-build-sandboxes` 构建并检查本地镜像；部署主机还应执行
   `python deploy/validate_image_mapping.py --check-local`。

如果只更新了 Dockerfile 或只更新了 `data/ai/*.yaml`，校验会失败并列出未同步的文件，
这样可以在运行时之前发现 `pull access denied`、错误 tag 或错误 Agent 镜像映射。

## 沙盒镜像 UID/GID 与挂载权限规范

所有会被 Studio、聊天沙盒或分析运行时挂载工作区的镜像，统一使用以下数值身份：

- UID：`10001`
- GID：`10001`
- 组名：`cygnusx-sandbox`

`deploy/runtime-images/`、`deploy/studio/` 和 `deploy/sandbox/` 的 Dockerfile 必须以这组
UID/GID 创建运行用户，并在镜像内将 `/workspace`、agent 缓存和运行脚本的属主设为
`10001:10001`。运行容器时同时指定 `user: 10001:10001`（Kubernetes 使用
`runAsUser: 10001`、`runAsGroup: 10001`）。运行时注册表中的 `runtime_uid`、
`runtime_gid` 和 `runtime_group` 必须与此规范一致。

镜像层的 `chown` 不能覆盖 bind mount 或 volume 的属主。编排器在启动容器前必须：

1. 预创建 `workspace/input`、`workspace/output`、`workspace/.logs` 等目录；
2. 将可写目录设置为 `10001:10001`，或设置为组 `cygnusx-sandbox` 且保证组可写（至少 `0770`）；
3. 将 `input` 按输入数据策略挂载为只读，将 `output` 挂载为可写；
4. 启动前以容器身份执行写入探针，失败时记录 mount source、owner、group、mode 并拒绝启动。

聊天沙盒的 bind mount 源目录还必须位于 Web 容器与 Docker daemon 共同可见的宿主路径，
默认使用 `${STORAGE_PATH}/.sandbox-pool`（配置项 `SANDBOX_POOL_HOST_DIR`）。不能让 Web
进程在自身私有 `/tmp` 下创建 source：Docker daemon 看不到该路径时会自动创建
`root:root 0755` 目录，最终容器内的 uid 10001 无法写入。

Docker bind mount 不能依赖镜像启动后的 `chown` 修复；Kubernetes volume 应配置
`fsGroup: 10001`，hostPath 或预置 PVC 仍需在节点侧完成同等授权。每次修改 UID/GID、
工作区挂载方式或运行用户，都必须重新构建相关镜像并执行真机权限验收：

```bash
docker inspect <container> --format '{{json .Mounts}}'
docker exec <container> sh -lc 'id; stat -c "%u:%g %a %n" /workspace /workspace/input /workspace/output'
docker exec <container> sh -lc 'touch /workspace/output/.permission-probe && rm /workspace/output/.permission-probe'
```

修改镜像用户、挂载路径或目录权限后，不能只重新 build 镜像：旧的 warm 容器仍可能保留
旧 bind mount。必须让沙盒池销毁并重建旧 warm 容器（或重启对应服务），再执行上面的
`inspect`、`stat` 和写入探针；否则镜像层的 `chown` 不会修复正在运行容器的挂载源。

构建速度方面，启用 BuildKit 后应保留 `/opt/conda/pkgs` 和 pip cache 的 cache mount，
不要在每个依赖层执行 `mamba clean --all` 或 `pip --no-cache-dir`。这些清理只会让下一次
构建重新下载大型 conda/Python 包；发布镜像体积由最终清理策略单独评估。

`PUID/PGID` 是主服务/Worker 写宿主数据目录时使用的身份，不得替代沙盒运行时的
`10001:10001`。若宿主用户不同，应通过目录属组或 ACL 授权，而不是让沙盒容器恢复为 root。

## 镜像 tag 与版本可观测规范

- **禁止 `latest` 裸推**：任何推送/发布的镜像必须打 git SHA 短号 tag，即 `make` 导出的
  `IMAGE_TAG`（默认 `git rev-parse --short HEAD`）。本地 `docker compose build` 的开发
  路径不受此约束，但不允许把未打 SHA tag 的镜像推送到任何 registry。
- 主栈后端镜像构建时经 `CYGNUSX_BUILD_SHA` / `CYGNUSX_BUILD_TIME` 构建参数注入版本信息
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
容器提供 Docker Socket。使用 `make docker-build-synteny` 构建 `cygnusx-synteny:v1`；Worker 负责运行
MCScanX 思路的区块识别并输出结构化 TSV/JSON，浏览器使用 Plotly `scattergl` 渲染 dot plot。

## PolarDB PostgreSQL / pgvector

`docker-compose.pgvector.yml` is an acceptance overlay that replaces the local PostgreSQL image with `pgvector/pgvector:pg14` and adds PgBouncer plus PostgreSQL Prometheus exporter. Production PolarDB uses managed writer/read-only endpoints rather than this local database container. Run `make docker-up-pgvector` to start it, or `make pgvector-acceptance` to run pgvector, backup/restore, and metrics checks. See `deploy/docker/POLARDB_POSTGRES.md` for cutover, read-replica, connection-pool, and monitoring validation.
