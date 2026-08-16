# OmicHub

私有化多组学分析平台 - 华中农业大学园艺林学学院

> 📜 **Licensed under Apache-2.0 + Commons Clause — non-commercial use only.**
> See [LICENSE](./LICENSE) for details. Commercial use requires a separate agreement.

## 技术栈

- **后端**: FastAPI + SQLAlchemy 2.0 + PostgreSQL 14+ + Redis 7+ + Celery
- **前端**: Vue 3 + TypeScript + Vite + Naive UI + Pinia
- **流程引擎**: Snakemake 8.0+
- **AI**: Cherry Studio SSE 架构 + Kimi/OpenAI API + MCP SDK
- **部署**: Docker Compose（主栈 + 独立 Worker 栈，逻辑解耦）

## 快速开始

### 环境要求

- Python >= 3.11
- Node.js >= 18
- Docker >= 24.0
- uv (Python 包管理器)

详细的 Makefile 命令说明见 [docs/Makefile_命令说明.md](docs/Makefile_命令说明.md)。

### 本地开发

```bash
# 1. 检查环境变量（.env 已存在，按需编辑）
#    编辑 .env，设置 JWT_SECRET_KEY、AL_API_KEY 等

# 2. 安装后端依赖
uv sync

# 3. 安装前端依赖
cd frontend && npm install

# 4. 启动 PostgreSQL + Redis（Docker）
make docker-up

# 5. 执行数据库迁移
make migrate

# 6. 初始化管理员账号
#    命令行：make init-admin
#    或浏览器访问 http://localhost:5173/setup 网页注册（见下方「首次使用与管理员注册」）
make init-admin

# 7. 初始化饼干定价策略（可选）
make init-cookies

# 8. 启动后端开发服务器
make dev

# 9. 启动前端开发服务器（另一个终端）
make frontend-dev
```

访问 http://localhost:5173（前端）或 http://localhost:8000/docs（API 文档）

### Docker 部署（推荐）

OmicHub 的 Web 控制面与 Celery Worker 计算面已拆分为**两个独立编排栈**，通过外部网络 `omichub_net` 共享 Redis，并经宿主目录 `/data/omichub` 共享任务数据：

- **主栈** `docker-compose.yml`：`web` / `db` / `redis` / `nginx` / `beat` / `flower`
- **Worker 栈** `docker-compose.worker.yml`：仅 `worker`，挂载流程 Workspace，并将动态 Conda 环境缓存写入共享盘

详细的单机、跨服务器和 AgentTeams 部署步骤见下方「**部署配置与 Make 命令**」。日常部署优先使用 `make docker-up-all`；跨服务器时使用 `make docker-up-cross-web` 和 `make docker-up-cross-worker`。

> ⚠️ **改前端后必须重启 nginx 才能生效**：nginx 通过 bind mount 挂载 `frontend/dist`，
> 但 `docker up -d` **不会重启已运行的容器**。Vite 构建会清空重建 dist（新 inode），
> 旧的 nginx 进程仍持有旧目录句柄，导致页面不更新。
> - 日常改代码/前端/YAML 用：`make docker-dev-refresh`（前端 build + 重启 web/beat/nginx + 跑迁移，秒级，不重建镜像）
> - 改动前端后用：`make docker-reload`（含 build + restart nginx）
> - 或手动：`cd frontend && npm run build && cd .. && docker restart omichub-nginx`
> - 浏览器端强制刷新：Ctrl+Shift+R（避免缓存旧 chunk）
>
> 💡 **dev compose 已把 `src/`、`data/`、`alembic/`、`flows/`、`tool_configs/`、`docs/` 全部 bind mount 进容器**，
> 所以日常改动不需要 `--build` 重建镜像：
> - 改 `src/` Python 代码 / 新增迁移 / 改前端 → `make docker-dev-refresh`
> - 改 `data/ai/*.yaml`（Agent 声明）或提示词 → 刷新页面即生效（每次调用幂等同步 + mtime 热重载），无需任何命令
> - **只有** `pyproject.toml` / `uv.lock` / Dockerfile 变更才需要 `make docker-reload`（依赖层缓存失效会全量重装，属一次性成本）

### 部署配置与 Make 命令

`.env` 是**声明式部署配置**：密码、服务发布端口、宿主机绑定地址、Docker 网络名和共享存储挂载路径都在这里设置。`make` 是**执行入口**：读取 `.env` 后创建网络、准备目录、构建镜像并启动相应 Compose 栈。

容器不需要固定 IP。容器内部始终通过 Compose 服务名（`web`、`db`、`cache`）通信；需要配置的是宿主机对外发布的私网地址和端口。

#### 自动化边界

`make` 可以完成 Docker 网络、运行目录、镜像构建、容器启动和健康检查；以下前置条件必须由部署人员或基础设施自动化先完成：

- 已安装 Docker、Docker Compose、GNU Make 和前端构建依赖。
- 已创建每台机器私有的 `.env`，并替换所有默认密码、令牌和密钥。
- 跨机器部署时，NAS/NFS/CephFS 等共享存储已挂载到每台机器的宿主机路径。
- 控制面与 Worker 的防火墙/VPN/DNS 已只放行必要的私网流量。
- 生产环境的 HTTPS 证书、备份和 Secret 管理已按组织规范配置。

#### 私有镜像仓库：推荐的云部署选项

是。对于云服务器、Kubernetes、多个计算节点或没有源码检出的交付环境，建议在 CI 或一台受控构建机上构建 OmicHub 自有镜像并推送到组织的私有镜像仓库（如 Harbor、阿里云 ACR、腾讯云 TCR、AWS ECR 或 GitHub Container Registry）。云端节点只需要拉取**已验证的不可变镜像**，无需安装 Node.js、uv、前端依赖或在部署时执行镜像构建；这会显著缩短扩容、回滚和跨地域部署时间。

这套方式适合推送 OmicHub 自己维护的镜像：后端控制面、通用 Worker、前端和各类分析运行时。`pgvector`、PgBouncer、Redis、PostgreSQL exporter 等第三方依赖仍可直接使用其固定上游 tag；若云环境不能稳定访问 Docker Hub，也可以先镜像同步到同一个私有仓库。

**构建并推送应用镜像**（在 CI / 构建机执行）：

```bash
# 使用 Git commit 作为不可变版本，不要只依赖 latest。
export REGISTRY=registry.example.com/omics
export VERSION="$(git rev-parse --short=12 HEAD)"

docker login "$REGISTRY"

docker build -f deploy/docker/Dockerfile \
  -t "$REGISTRY/omichub-backend:$VERSION" .
docker build -f deploy/docker/Dockerfile.worker \
  -t "$REGISTRY/omichub-worker:$VERSION" .
docker build -f deploy/docker/Dockerfile.frontend \
  -t "$REGISTRY/omichub-frontend:$VERSION" .

docker push "$REGISTRY/omichub-backend:$VERSION"
docker push "$REGISTRY/omichub-worker:$VERSION"
docker push "$REGISTRY/omichub-frontend:$VERSION"
```

分析运行时镜像（例如富集、差异分析、系统发育或 Studio runtime）也应以相同版本或兼容版本单独构建、扫描并推送。镜像构建完成后，先在预发布环境运行数据库迁移、`make pgvector-acceptance` 和业务冒烟测试，再将**同一个 digest**提升到生产环境。

**云端拉取部署原则**：生产 Compose / Kubernetes 清单应仅使用 `image: <registry>/<name>@sha256:<digest>`（或固定版本 tag），不要保留 `build:`、开发环境 bind mount 或 `make docker-reload`。部署节点通过 `docker login`、云厂商工作负载身份或 Kubernetes `imagePullSecrets` 获得拉取权限；Secret、`DATABASE_URL`、`READONLY_DATABASE_URL` 和 AI Provider 密钥继续由云端 Secret 管理服务注入，不写入镜像。

示意性 Compose 服务配置如下；`web`、`beat`、`flower` 可复用后端镜像，Worker 使用 Worker 镜像：

```yaml
services:
  web:
    image: registry.example.com/omics/omichub-backend@sha256:<immutable-digest>
    # 生产环境不设置 build:，不挂载 ../../src、../../alembic 等开发目录。
  worker:
    image: registry.example.com/omics/omichub-worker@sha256:<immutable-digest>
```

第三方依赖的私有镜像同步示例：

```bash
docker pull pgvector/pgvector:pg14
docker tag pgvector/pgvector:pg14 "$REGISTRY/third-party/pgvector:pg14"
docker push "$REGISTRY/third-party/pgvector:pg14"
```

镜像仓库只解决应用和依赖镜像分发；生产数据仍应使用 PolarDB PostgreSQL writer/read-only endpoint、托管备份/PITR、共享对象存储或共享文件系统。不要把数据库数据目录、`.env`、上传文件、运行日志或任何密钥打进镜像。

#### 1. 单机部署：一份 `.env` + 一条 Make 命令

适合开发、演示和小型课题组。Web、数据库、Redis 和 Worker 均在同一台机器运行。

```bash
# 首次复制模板并限制文件权限
cp .env.example .env
chmod 600 .env

# 编辑 .env：至少替换 JWT_SECRET_KEY、APP_SECRET_KEY、REDIS_PASSWORD、
# POSTGRES_PASSWORD、OMICHBUB_INIT_ADMIN_PASSWORD 和实际 AI Provider 密钥。
# 如数据盘不使用默认目录，修改：OMICHUB_DATA_ROOT=/mnt/omichub

# 构建前端并启动主栈 + Worker；Make 自动创建网络、运行目录和所需镜像。
make frontend-build
make docker-up-all
```

访问 `http://<服务器地址>:<OMICHUB_HTTP_PORT>`；模板默认端口为 `8888`。首次没有管理员时，访问 `http://<服务器地址>:8888/setup` 创建首位管理员，或执行 `make init-admin`。

单机常用命令：

| 命令 | 作用 |
|---|---|
| `make docker-up` | 启动主栈（Nginx、Web、PostgreSQL、Redis、Beat、Flower） |
| `make docker-up-worker` | 构建并启动通用与系统发育 Worker |
| `make docker-up-all` | 启动单机完整平台，优先使用 |
| `make docker-logs` / `make docker-logs-worker` | 查看控制面 / Worker 日志 |
| `make docker-down-all` | 停止主栈和 Worker，保留数据 |
| `make docker-reload` | 开发环境重建前端并刷新服务 |
| `make docker-fix-permissions` | 修复共享数据盘目录属主或权限错误 |

#### 2. 跨服务器部署：控制面与计算节点各自一份 `.env`

跨服务器不应共享同一个 `.env` 文件：所有节点需要使用相同的数据库、Redis、JWT、AI 和监控密钥，但控制面发布地址、Docker 网络名和 Worker 宿主机挂载路径属于**节点本地配置**。

**控制面服务器**运行 Nginx、Web、PostgreSQL、Redis、Beat 和 Flower。编辑控制面机器的 `.env`：

```dotenv
APP_ENV=production
APP_DEBUG=false
OMICHUB_CONTROL_HOST=10.0.0.10
OMICHUB_HTTP_BIND_HOST=0.0.0.0
OMICHUB_WEB_BIND_HOST=10.0.0.10
OMICHUB_POSTGRES_BIND_HOST=10.0.0.10
OMICHUB_REDIS_BIND_HOST=10.0.0.10
OMICHUB_DATA_ROOT=/mnt/omichub-control-data
```

然后在控制面机器执行：

```bash
make frontend-build
make docker-up-cross-web
```

**每台 Worker 计算服务器**挂载 NAS 后，编辑本机 `.env`。`WORKER_SHARED_DATA_DIR` 与控制面数据根可以不同，但都必须是同一共享存储在本机的挂载点；容器内会统一映射为 `/data/omichub`。

```dotenv
APP_ENV=production
APP_DEBUG=false
OMICHUB_CONTROL_HOST=10.0.0.10
OMICHUB_CONTROL_WEB_PORT=8000
OMICHUB_CONTROL_POSTGRES_PORT=5432
OMICHUB_CONTROL_REDIS_PORT=6379
WORKER_SHARED_DATA_DIR=/mnt/omichub-worker-data
WORKER_PIPELINE_DIR=/srv/omichub/pipelines
```

然后在每台 Worker 机器执行：

```bash
make docker-up-cross-worker
```

`make docker-up-cross-worker` 会使用 `deploy/docker/docker-compose.cross-worker.yml` 覆盖 Worker 的数据库、Redis、监控地址与本地网络，不会要求 Worker 加入控制面机器的 Docker 网络。关闭命令分别为 `make docker-down-cross-web` 与 `make docker-down-cross-worker`。

#### 3. 配置项速查

| `.env` 分类 | 核心变量 | 何时修改 |
|---|---|---|
| 数据根 | `OMICHUB_DATA_ROOT` | 控制面数据盘或 NAS 挂载点改变时 |
| 浏览器入口 | `OMICHUB_HTTP_BIND_HOST`、`OMICHUB_HTTP_PORT` | 更换 Nginx 监听地址或端口时 |
| 跨机 API | `OMICHUB_WEB_BIND_HOST`、`OMICHUB_WEB_PORT` | Worker 需要上报 workflow-monitor 时 |
| 跨机数据服务 | `OMICHUB_POSTGRES_*`、`OMICHUB_REDIS_*` | 控制面向 Worker 暴露私网端口时 |
| Worker 连接 | `OMICHUB_CONTROL_HOST`、`OMICHUB_CONTROL_*_PORT` | Worker 指向控制面私网 DNS/IP 时 |
| Worker 挂载 | `WORKER_SHARED_DATA_DIR`、`WORKER_PIPELINE_DIR` | 每台计算节点的 NAS/流程目录不同的时候 |
| Docker 网络 | `OMICHUB_NETWORK_NAME`、`OMICHUB_*_NETWORK_NAME` | 同机多套 OmicHub、已有网络命名冲突时 |
| AgentTeams | `AGENTTEAMS_*` | Bridge、聊天建单或角色令牌启用时 |

`.env.example` 保持安全默认值：单机时数据库、Redis、Flower 和 Web 内部 API 只监听 `127.0.0.1`；跨机器时才将它们绑定到控制面的私网 IP。不要将 PostgreSQL、Redis、Flower 或 Bridge 直接暴露到公网。

## 从单机扩展到 HPC 与 Kubernetes

OmicHub 的部署目标是以同一套应用代码支持三种规模：单机实验室、跨机器计算节点，以及高可用 Kubernetes 平台。核心原则是：**容器负责运行环境隔离；共享存储负责数据可见性；调度器负责把计算分配到合适的机器。**

### 当前能力与后续目标

| 能力 | 当前状态 | 实现入口 / 后续方式 |
|---|---|---|
| 单机控制面与计算 | 已支持 | `make docker-up-all`，Web 与 Worker 使用同一台机器的 `/data/omichub` |
| 独立 Worker 节点 | 已支持 | `deploy/docker/docker-compose.cross-web.yml` 与 `deploy/docker/docker-compose.cross-worker.yml`；Worker 通过内网访问控制面 |
| 多个 Celery Worker 水平扩展 | 已支持 | 每台计算机使用同一 Worker 镜像和队列配置，并挂载共享数据路径 |
| 分层 NAS / 对象存储 | 架构已定义，需按站点配置挂载与归档服务 | 用户数据、参考库、工作目录分别映射到 NAS；历史产物转对象存储 |
| Slurm 高性能计算 | 规划中，需接入执行器 | Worker 提交 `sbatch`；Snakemake 以 Slurm profile 在计算节点执行 |
| Kubernetes 高可用 | 规划中，需提供 Helm/Manifest 与执行器 | 控制面 Deployment + Worker Deployment/Job + RWX PVC + HPA |

> 不要把“Docker 容器”理解为自动实现跨机器存储：不同机器上的容器只有在挂载**同一份共享文件系统**、或通过对象存储 API 读写同一份数据时，才能安全地协同执行同一个分析任务。

### 统一逻辑目录与分层存储

应用内始终使用容器路径 `/data/omichub`，避免业务代码依赖某台宿主机的实际挂载点。运维侧通过 NFS、CephFS、Lustre、云 NAS 或对象存储网关，把不同的物理后端映射到此逻辑目录的不同子路径。

```text
/data/omichub/
├── users/                    # 用户上传、任务输入、活跃任务与近期结果（RW）
├── shared/
│   ├── references/            # 参考基因组、索引：高性能 NAS，计算节点只读（RO）
│   ├── blast_db/              # BLAST 数据库：高性能 NAS，计算节点只读（RO）
│   ├── annotations/           # 公共注释资源（RO）
│   └── bin/                   # 平台共享二进制（受控写入）
├── system/
│   ├── .conda_envs/           # Conda/Mamba 缓存：独立高速盘或 NAS（RW）
│   ├── .tmp/                  # 可清理的中间临时数据（RW）
│   └── archive/               # 等待迁移或归档的结果（RW）
└── logs/                      # 应用、Worker、Snakemake 日志（RW）
```

推荐的数据放置策略：

| 数据类别 | 推荐存储 | 访问权限 | 原因 |
|---|---|---|---|
| `shared/references`、`shared/blast_db` | 高性能 NAS / 并行文件系统 | Worker、Slurm 节点只读 | 比对和检索会产生高并发随机读取，避免重复复制参考库 |
| `users/*/inbox`、`users/*/tasks/*/work` | 支持 RWX 的 NAS | Web、Worker、Slurm 节点读写 | 上传、流程工作目录和产物必须被多个节点以相同路径访问 |
| `users/*/tasks/*/output` | NAS 温存储 | 读写 | 保留近期结果，支持在线预览与下载 |
| 历史原始数据、已完成结果 | OSS / S3 / COS 等对象存储 | API / 预签名 URL | 低成本长期保存；建议异步归档，不在运行中的流程中直接写冷存储 |
| PostgreSQL、Redis | 专用 SSD、托管数据库或高可用集群 | 仅控制面 | 不建议放在普通 NFS 共享目录 |

运行任务时，**Web、Celery Worker、Slurm 计算节点必须看到一致的绝对路径**，例如都能访问 `/data/omichub/users/<user_id>/tasks/<task_id>/work`。这是 Snakemake 输入、日志和输出可被不同节点接力处理的前提。

### 阶段一：单机与跨机器 Worker

单机模式适合开发、小型课题组或验证流程：

```text
Browser → Nginx → Web/API → Redis/Celery → Worker → Snakemake
                                            └──────→ /data/omichub
```

当分析计算需要迁移到独立机器时，控制面继续运行在管理节点；计算节点仅运行 Worker。仓库已提供跨机 Compose 覆盖文件：

```text
管理节点
  ├── nginx / web / db / redis / beat / flower
  ├── 内网暴露 PostgreSQL、Redis 与 workflow-monitor API
  └── 挂载共享存储到 /data/omichub

计算节点 A、B、...
  ├── worker / phylo-worker（可按队列部署不同镜像）
  ├── 通过内网连接管理节点 Redis、PostgreSQL 与监控 API
  └── 将同一共享存储挂载到 /data/omichub
```

部署要点：

1. 在每一台 Worker 机器挂载用户数据 NAS、参考库 NAS 和必要的日志目录；容器内保持 `/data/omichub` 的统一目录契约。
2. 在 Worker 机器的 `.env` 设置 `WORKER_SHARED_DATA_DIR` 和 `WORKER_PIPELINE_DIR`；若留空则回退读取 `data/worker_config.yaml`。
3. 管理节点和 Worker 节点都通过 `.env` 配置私网地址与端口；不再修改 Compose 文件中的示例 IP。
4. 数据库与 Redis 只对可信内网或 VPN 开放；不要直接暴露到公网。Worker 与控制面之间应使用防火墙、TLS/VPN 或 Kubernetes NetworkPolicy 限制访问。
5. 按队列拆分 Worker：`analysis` 用高 CPU/内存节点，`download` 用高网络吞吐节点，交互沙盒使用隔离能力更强的节点池。

跨机 Worker 示例：

```bash
# 管理节点：在 .env 写入控制面私网 IP、统一存储根目录与需要开放的端口。
# 容器无需固定 IP；容器内部继续通过 web、db、cache 等服务名通信。
# .env（管理节点）
OMICHUB_CONTROL_HOST=10.0.0.10
OMICHUB_WEB_BIND_HOST=10.0.0.10
OMICHUB_POSTGRES_BIND_HOST=10.0.0.10
OMICHUB_REDIS_BIND_HOST=10.0.0.10
OMICHUB_DATA_ROOT=/mnt/omichub-nas
```

```bash
make docker-up-cross-web
```

```bash
# 每台 Worker 计算节点：使用相同的密钥和 CONTROL_HOST，
# 但 WORKER_SHARED_DATA_DIR 与 WORKER_PIPELINE_DIR 使用该机器实际的挂载路径。
# .env（Worker 节点）
OMICHUB_CONTROL_HOST=10.0.0.10
WORKER_SHARED_DATA_DIR=/mnt/omichub-nas
WORKER_PIPELINE_DIR=/srv/omichub/pipelines
```

```bash
make docker-up-cross-worker
```

上述变量必须写入每台机器各自私有的 `.env`，不能只在终端临时赋值。完整端口、网络和 Worker 路径模板见 [`.env.example`](.env.example)。控制面与 Worker 的 `WORKER_SHARED_DATA_DIR` 可以是不同的宿主机路径，但它们在容器内必须都挂载到 `/data/omichub`；这样流程配置和任务记录才能使用一致路径。

### 阶段二：接入 Slurm 高性能集群

对于大规模 RNA-seq、ATAC-seq 或多用户并发分析，Celery Worker 应从“实际执行计算”转为“提交和跟踪作业”。实际 Snakemake rule 由 Slurm 分配给 HPC 计算节点：

```text
Web/API → Redis → Celery Worker（提交器） → sbatch / Slurm controller
                                             ↓
                               Slurm compute nodes / Snakemake
                                             ↓
                                   共享 NAS / 对象存储归档
```

建议实现方式：

1. **共享路径**：所有 Slurm 节点挂载与 Worker 一致的 `/data/omichub`；参考库单独挂载为只读高性能路径。
2. **流程可移植性**：为每个流程构建版本化 OCI 镜像，或提供 Apptainer/Singularity 镜像；不要依赖某台 Worker 本机的 Conda 环境。
3. **Snakemake profile**：为每个 Slurm 分区维护 profile，声明 `partition`、CPU、内存、运行时限、日志路径和重试策略；任务资源来自流程 YAML 的 `default_resources`，而不是由前端随意传入。
4. **执行器契约**：新增 `SlurmExecutor`，其职责是生成作业脚本、调用 `sbatch --parsable`、记录 Slurm job ID、通过 `sacct`/`squeue` 查询状态，并将失败原因和日志回写 OmicHub 任务状态。
5. **取消与清理**：OmicHub 任务取消时调用 `scancel <job_id>`；作业结束后保留结构化日志，按生命周期策略归档结果和清理工作目录。
6. **最小权限**：Worker 使用专用 Slurm 服务账号；不向应用容器挂载管理员 SSH 私钥。优先使用 Slurm REST API 或受限 `sudo`/命令白名单。

Slurm 接入完成前，当前平台仍是由本地 `LocalSnakemakeExecutor` 在 Worker 容器中运行流程；因此不能将“流程表单中的集群模式”视为已完成的 HPC 调度能力。

### 阶段三：Kubernetes 高可用平台

当需要高可用、弹性扩缩、多租户隔离或云上部署时，将 Docker Compose 的服务拆分为 Kubernetes 工作负载：

```text
Internet
   ↓
Ingress / LoadBalancer
   ↓
Web Deployment (N replicas) ──────── PostgreSQL HA / Managed RDS
   ↓                                   Redis HA / Managed Redis
Celery Worker Deployments
   ├── analysis workers ──┐
   ├── download workers ──┼── RWX PVC (NAS / CephFS)
   ├── sandbox workers ───┘
   └── Slurm submitter or Kubernetes Job executor

Per-task Job / workflow Pod → RWX PVC + Object Storage
```

推荐的 Kubernetes 资源划分：

| 组件 | 建议对象 | 高可用 / 隔离策略 |
|---|---|---|
| `web`、`nginx` | Deployment + Service + Ingress | 至少 2 副本、滚动更新、readiness/liveness probes、HPA |
| `beat` | 单副本 Deployment 或 Kubernetes CronJob | 避免重复调度；优先把独立周期任务改为 CronJob |
| `analysis`、`download` Worker | 按队列拆分 Deployment | 独立资源 requests/limits、nodeSelector、HPA/KEDA 按队列深度扩缩 |
| 单次重计算工作流 | Kubernetes Job 或 Snakemake Kubernetes executor | `ttlSecondsAfterFinished` 自动清理；每任务独立资源与服务账号 |
| PostgreSQL / Redis | 托管服务或专用 Operator/StatefulSet | 备份、故障转移、监控与连接池；不与无状态应用混部 |
| 用户/任务数据 | RWX PVC | NAS CSI、CephFS、Lustre CSI 等；挂载路径仍保持 `/data/omichub` |
| 长期归档 | 对象存储 | 预签名上传/下载、生命周期规则、跨区域备份（如需要） |

Kubernetes 上的关键实施要求：

- **无状态控制面**：Web 不保存本地会话和任务文件；会话、队列和任务元数据分别进入 Redis、PostgreSQL 与共享存储。
- **资源隔离**：每类 Worker 设置 CPU/内存 requests 与 limits；对 GPU、超大内存或高 I/O 任务使用 node taint/toleration 与专用节点池。
- **存储权限**：参考库 PVC 以只读方式挂载；用户数据按应用服务账号与访问范围控制；避免以 root 写入共享 NAS。
- **安全网络**：默认拒绝跨 namespace 通信，只放行 Web→DB/Redis、Worker→Redis/存储/Slurm、Ingress→Web 的必要路径。
- **可观测性**：收集 API 延迟、Celery 队列长度、任务状态、Slurm/Kubernetes Job 状态、NAS 容量与 I/O；以这些指标驱动告警和自动扩缩。
- **备份与演练**：定期执行 PostgreSQL PITR/恢复演练、对象存储版本控制、基础设施清单备份和跨节点故障演练。

### 推荐演进顺序

1. **先稳定单机**：完成备份、权限、日志、运行目录清理和流程镜像版本管理。
2. **再拆分 Worker**：使用已有 cross-machine Compose，把控制面与多个计算节点分离，并用共享 NAS 保证路径一致。
3. **再接 Slurm**：先从提交单个 Snakemake 驱动作业开始，再演进为每个 rule 独立调度；保留 Celery 作为任务状态与用户通知通道。
4. **最后迁移 Kubernetes**：先迁移无状态 Web 和 Worker，再迁移任务 Job；数据库、Redis 与共享存储优先使用成熟托管服务或经过验证的集群方案。

此顺序避免在流程、存储与权限契约尚未稳定时直接引入 Kubernetes 的复杂度，同时保证单机、HPC 和云原生环境共享同一份任务数据模型与运行目录规范。

### 开启 Multi-Agent 与 AgentTeams

完整环境变量模板见 [`.env.example`](.env.example)。复制后先以默认关闭状态启动；协作能力应按“轻量协作 → 并行增强 → 全流程闭环”的顺序灰度启用。

```bash
cp .env.example .env
chmod 600 .env
```

1. **平台内 Multi-Agent**：在 `.env` 设置 `UNIFIED_INTENT_ROUTER_ENABLED=true` 和 `MULTI_EXPERT_CONSULTATION_ENABLED=true`，重启 Web/Worker 后启用路由与只读专家会诊。确认模型调用配额、降级记录和延迟可接受后，再设置 `SUBAGENT_FANOUT_ENABLED=true` 开启并行子 Agent。
2. **AgentTeams Bridge**：先复制 `deploy/agentteams/bridge.env.example` 和 `deploy/agentteams/worker.env.example` 为私有配置，为 Manager、Approval、Workflow Operator 与 14 个专家身份设置不同的随机令牌；生产专家 Worker 使用可横向扩展的 capability 资源池，而不是每个角色独占一个服务。
3. **连接 OmicHub**：仅在 Bridge 的健康检查、令牌校验和最小权限网络策略都通过后，将 `.env` 中 `AGENTTEAMS_BRIDGE_ENABLED=true`、`AGENTTEAMS_CHAT_ENTRY_ENABLED=true`，并填入 Bridge URL 与服务端角色令牌。协作、计划确认、审批和产物预览均在 OmicHub 聊天窗口内完成，不再依赖 Element 外链入口。
4. **部署前检查**：执行 `deploy/agentteams/check_setup.sh deploy/agentteams/bridge.env`；生产环境还应运行文档规定的 Bridge 预检与健康检查。仅修改 OmicHub `.env` 不会启动 AgentTeams 的独立 Worker。

不要在 `.env`、`bridge.env`、README、Issue 或日志中保存真实云密钥、Bridge 身份令牌、数据库密码或管理员密码；生产部署应通过 Secret 管理服务注入，并在泄露后立即撤销和轮换。

### 首次使用与管理员注册

平台首次部署、数据库尚无管理员账号时，可直接用浏览器打开「初始化配置」页创建首位管理员：

```
http://<服务器IP>:8888/setup        # 例：http://192.168.5.102:8888/setup
```

- 该页面仅在**系统无任何 admin 用户**时可用（后端 `has_any_admin()` 强制校验）。
- 一旦首位管理员创建成功，`/setup` 即被永久关闭：
  - 浏览器再次访问 `/setup` 会自动重定向到登录页；
  - 即便绕过前端直接 `POST /api/v1/auth/setup`，后端也会返回 `409 系统已存在管理员账号，请通过登录页访问`，无法再创建第二个管理员。
- 因此 `/setup` 不存在被反复打开注册管理员的安全风险。

> 首位管理员创建后，其他账号需由管理员在「系统管理 → 用户管理」中创建（或在开放自助注册时通过登录页注册）。首次登录会自动弹出迎新引导，并收到一条指向「实验室知识库」的欢迎通知。

> 💡 一键拉起主栈 + Worker（含前端构建）：`make docker-up-all`。

### 用户默认存储目录

每个用户在创建成功后，系统会以用户 UUID 创建独立的存储根目录：

```text
/data/omichub/users/{user_id}/
├── raw_data/    # 用户上传的原始数据
├── workspace/   # 用户工作区及分析过程文件
└── temp/        # 用户临时文件
```

- `{user_id}` 必须对应数据库 `users.id`，不同用户之间的目录相互隔离。
- 用户注册或由管理员创建用户时，系统会幂等创建上述三个默认目录。
- 应用启动时会检查现有用户的默认目录，并自动补齐缺失的目录记录和物理目录。
- 用户删除成功后，系统会清理对应的 `/data/omichub/users/{user_id}` 存储根目录。
- 不属于数据库现有用户的 UUID 目录属于孤儿目录，应在确认无文件和数据库引用后再清理，不能直接按目录名批量删除。

### 生产环境部署

```bash
# 主栈：使用生产环境 override（4 uvicorn worker + 不暴露 DB 端口 + SSL）
docker compose -f deploy/docker/docker-compose.yml \
               -f deploy/docker/docker-compose.prod.yml up -d

# Worker 栈：独立启动（生产水平扩展用 --scale）
./scripts/worker-compose.sh --scale worker=2 up -d
```

> 注意：两栈必须通过同一外部网络 `omichub_net` 连通，且共享同一宿主 `/data/omichub`。首次需先执行 `docker network create omichub_net`（或 `make docker-network`）。

### Worker 路径配置与跨机迁移

Worker 的宿主机路径统一由 `data/worker_config.yaml` 定义：

```yaml
paths:
  shared_data_dir: /data/omichub
  pipeline_dir: /home/zj/pipeline
```

- `shared_data_dir` 必须是 Web 与 Worker 都可访问的共享存储；任务输入、结果、日志和 Snakemake Conda 缓存都位于其中。
- `pipeline_dir` 指向包含 `RNAFlow/` 和 `ATACFlow/` 的目录；可以设为当前仓库的 `pipelines` 绝对路径。
- Worker 镜像内置 Micromamba、Celery 与 Snakemake；不再挂载宿主机 Conda/Mamba。流程 Workspace 只读挂载到 `/opt/omichub/pipelines`，运行时环境缓存固定在共享盘 `/data/omichub/.conda_envs`。
- Flow 配置中的 Snakefile 应使用容器路径，例如 `/opt/omichub/pipelines/RNAFlow/Snakefile`；迁移机器时只改 YAML 中的宿主机路径。

请使用 `make docker-up-worker` 或 `./scripts/worker-compose.sh ...` 启动 Worker。启动脚本会先把 YAML 渲染为被 Git 忽略的 `data/.worker-config.env`，再交给 Docker Compose 插值；不要直接运行 `docker compose -f deploy/docker/docker-compose.worker.yml ...`。

Worker 默认镜像标签为 `omichub-worker:dev`，由 `docker-compose.worker.yml` 的 `image` 与 `build` 同时定义。可通过 `.env` 覆盖 `OMICHUB_WORKER_IMAGE` 使用指定的镜像仓库或发布标签：

```dotenv
OMICHUB_WORKER_IMAGE=registry.example.com/omichub-worker:2026.07.12-a1b2c3d
```

仅构建镜像时使用：

```bash
make docker-build-worker
```

### Worker 镜像：交互终端与运行用户

Worker 镜像除 Celery、Snakemake 和 Micromamba 外，还预装了 `btop`、`zsh`、Oh My Zsh 与 Oh My Posh，便于在计算节点直接检查运行环境。

镜像中的任务进程默认使用 `omichub` 用户（UID/GID `1000`）运行；该账户有可写的临时 HOME 目录 `/tmp/omichub-home`。这也保证 Snakemake 的 logger 插件能够解析当前用户名，不会因 `getpwuid(): uid not found: 1000` 中断。

```bash
# Dockerfile 或 Worker 入口脚本变更后重建镜像
make docker-build-worker

# 交互式进入 Worker；裸 `bash` 会被入口脚本自动切换为 zsh
docker run --rm -it omichub-worker:dev bash

# 进入已运行的 Worker
docker exec -it omichub-worker zsh

# 验证镜像内 Snakemake 与终端工具
snakemake --version
btop
```

> `bash -c '...'`、`bash -ic '...'` 等脚本形式不会被改写；仅交互式裸 `bash` 会切换到 Zsh。Compose 启动的 Celery Worker 命令不受影响。

部署前可校验配置语法：

```bash
python3 scripts/render_worker_config.py --check
```

生产环境注意事项：
- 设置 `APP_ENV=production`、`APP_DEBUG=false`
- 必须设置 `OMICHBUB_INIT_ADMIN_PASSWORD` 强密码
- `AI_CONFIG_ENCRYPTION_KEY` 必须为固定值（首次部署后不可更改，否则已加密的 API Key 无法解密）
- 配置 SSL 证书（挂载到 nginx）
- 不暴露数据库端口（prod.yml 已禁用）

## 配置说明

### YAML 配置总览

仓库中所有主要 YAML/YML 配置文件、加载入口、热重载方式和部署注意事项集中整理在 [`config_readme.me`](config_readme.me)。新增或修改配置前请先查阅该清单。

### AI Provider 配置

支持两种方式（可共存，方式 1 优先）：

**方式 1（推荐）：外置 YAML**

编辑 `data/ai/providers.yaml`，支持 `${ENV_VAR}` 插值引用 `.env` 中的密钥：

```yaml
providers:
  - name: aliyun
    provider_type: openai_compatible
    model: qwen3.7-max
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ${AL_API_KEY}
    is_default: true
```

**方式 2：环境变量兜底**

仅在数据库无 Provider 时生效，在 `.env` 中设置 `KIMI_API_KEY` / `OPENAI_API_KEY`。

### AI 助手架构

采用 Cherry Studio SSE 架构（`docs/OmicHub_CherryStudio_整合实施文档.md`）：

- **SSE 流式聊天**: `POST /api/v1/chat/stream` — 逐 token 推送，支持推理过程
- **三层数据模型**: `chat_sessions`（会话）→ `chat_messages`（消息）→ `chat_assistants`（助手）
- **Provider 管理**: `ProviderManager` 单例 + `OpenAICompatibleProvider`（httpx 直连 SSE）
- **助手系统**: 6 个内置助手（通用/RNA-seq/单细胞/代码/文献/可视化）+ 自定义助手
- **技能注入**: 管理员可配置技能（Skill），激活后自动注入到 system prompt

### 工具箱与 AI 助手联动框架

AI 助手不仅能对话，还能直接调用「生信工具箱」中的工具完成绘图、富集、序列分析等任务。工具在 `tool_configs/tools_schema.yaml` 中注册为 LLM 可调用的 function，通过内置 MCP `omichub-tools` 在进程内执行。

#### 完整调用链路

```text
用户消息 / 附件
    │
    ▼
Agent 调度中枢 (chat_service.py::stream_agent_chat)
    │ 1. 查 Agent → 组装模型 / 系统词 / MCP server / 工具列表
    │ 2. 送 LLM（流式）
    ▼
LLM 输出 tool_calls（OpenAI function call）
    │
    ▼
MCPClient.call_tool(server, tool_name, arguments)
    │  builtin transport → omichub-tools preset
    ▼
ToolBridgeService.execute(user_id, tool_name, arguments)
    │ 1. 参数校验 + upload://file_id 解析
    │ 2. 按 invocation_mode 分发执行
    ▼
具体工具实现（service / shim / async / open_page）
    │
    ▼
双通道结果
    ├─ llm_payload：精简摘要，回灌 LLM 用于下一轮对话
    └─ ui_payload：完整图/表/任务信息，透传给前端渲染
```

#### 关键文件

| 职责 | 文件 |
|------|------|
| 工具注册表 | `tool_configs/tools_schema.yaml` |
| Schema 加载 / OpenAI functions 转换 | `src/omichub/tools/schema_loader.py` |
| 工具执行桥（校验、分发、双通道打包） | `src/omichub/application/services/tool_bridge_service.py` |
| 内置 MCP 预设（omichub-tools） | `src/omichub/infrastructure/mcp/presets.py` |
| Agent 上下文组装 | `src/omichub/application/services/agent_service.py` |
| 流式聊天 + tool_call 闭环 | `src/omichub/application/services/chat_service.py` |
| SSE 流式接口 | `src/omichub/api/v1/chat.py` |
| 前端工具结果渲染（图表/表格/任务卡） | `frontend/src/components/ai-chat/KimiMessageItem.vue` |
| 前端 Agent 聊天 Store | `frontend/src/stores/agentHub.ts` |
| 前端 SSE 解析 | `frontend/src/composables/useAgentChatStream.ts` |

#### 双通道输出

工具返回经 `ToolBridgeService._package()` 统一为：

```python
{
    "success": True,
    "is_error": False,
    "llm_payload": {...},   # 给 LLM 看，建议 ≤3KB
    "ui_payload": {...},    # 给前端看
}
```

前端 `KimiMessageItem.vue` 识别的 `ui_payload` 字段：

| 字段 | 作用 |
|------|------|
| `plotly_figure` | 渲染交互式 Plotly 图表 |
| `table_data` / `tableData` | 渲染数据表格 |
| `confirm_card` | 显示二次确认卡片 |
| `route` | 显示「前往工具页」引导 |
| `task_id` + `progress_url` / `result_url` | 显示异步任务进度 |

#### 文件上传协议：`upload://file_id`

AI 助手上传的文件保存在 `users/<user_id>/workspace/chat-uploads/`。当工具参数需要大段文本（如 `data_text`、`gene_text`）时，LLM 可以传 `upload://file_id` 引用已上传文件，而不是把整表 CSV 塞进参数。

参数描述示例：

```yaml
data_text:
  type: string
  description: CSV/TSV 格式的差异表达表文本；也支持 upload://file_id 引用已上传文件
```

#### 新增一个 AI 助手可用工具的步骤

1. 在 `src/omichub/tools/` 下实现工具逻辑（service / shim），返回原始 dict。
2. 在 `tool_configs/tools_schema.yaml` 注册：name、description、input_schema、llm_result_fields、ui_result_fields。
3. 选择 `invocation_mode`：轻量出图用 `backend_shim`，复用 service 用 `backend_sync`，长任务用 `backend_async`，复杂交互用 `open_page`。
4. 确保 `ui_payload` 包含前端能识别的字段（如 `plotly_figure`）。
5. 调用 `POST /api/v1/flows/reload` 或重启 web 容器使 schema 生效。

详细架构规范见 `tool_configs/tools_design.md` 第十五章。

### 前端临时文件

```bash
# 清理前端构建缓存和产物
cd frontend
rm -rf node_modules dist .vite
npm install && npm run build

# 清理 npm 缓存（可选）
npm cache clean --force
```

### 后端 Python 缓存

```bash
# 清理 __pycache__、.pyc、缓存目录
make clean

# 或手动清理
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
```

### Docker 数据清理

按破坏性分级，四个命令职责清晰：

| 命令 | 容器 | 数据卷 | 镜像 | 前端 dist | 用途 |
|------|------|--------|------|-----------|------|
| `docker-clean` | down | 保留 | 保留 | 保留 | 停服务，数据不动 |
| `docker-dev-refresh` | restart web/beat/nginx | 保留 | 保留 | 重建 | 日常改代码/YAML/前端后热刷新（秒级） |
| `docker-reload` | restart | 保留 | 保留 | 重建 | 依赖（uv.lock/Dockerfile）变更后重建镜像刷新 |
| `docker-purge` | down + 强制删除 | 清空 | 删除 | 删除 | 只清理，不启动 |
| `docker-start` | purge + build + up | 清空 | 重建 | 重建 | 彻底重建，从头启动 |

```bash
# ① 轻度清理：仅删除两栈容器 + 网络（含孤儿容器），保留数据库/Redis 数据卷与镜像
make docker-clean

# ② 彻底清理（⚠️ 不可逆）：容器 + 数据卷 + 网络 + 本地镜像 + 前端构建产物，只清理不启动
make docker-purge

# ③ 彻底重建（⚠️ 不可逆）：在 purge 基础上重建镜像 + 构建前端 + 启动全部服务
make docker-start
```

> 注：任务数据存放于宿主 `/data/omichub`（bind mount，非数据卷），`make docker-purge` **不会**删除它。其中 `omichub_data/_pgdata` 是数据库目录、`omichub_data/_redis` 是缓存目录。需彻底清理任务数据请手动 `sudo rm -rf /data/omichub`。

`docker-start` 清理后会自动重建并启动，无需手动执行 `docker-up-all`。`docker-purge` 清理后需手动拉起：

```bash
make docker-up-all
docker exec omichub-web uv run alembic upgrade head
docker exec omichub-web uv run python scripts/init_admin.py   # 首次部署需要
docker exec omichub-web uv run python scripts/init_cookies.py # 可选
```

> ⚠️ `make docker-purge` 会清空 `pg_data` 数据卷，相当于删库。执行前确认无需保留的实验/任务数据，或先备份。

补充命令（手动场景）：

```bash
# 仅停止容器（等同 docker-clean 但不重建）
make docker-down

# 清理 Docker 构建缓存和悬挂镜像
docker builder prune -f
docker image prune -f

# 彻底清理所有 OmicHub 相关资源（含拉取镜像，⚠️ 不可恢复）
docker compose -f deploy/docker/docker-compose.yml down -v --rmi all
./scripts/worker-compose.sh down -v --rmi all
docker volume rm $(docker volume ls -q | grep omichub) 2>/dev/null
sudo rm -rf /data/omichub   # 任务数据（bind mount）
```

### 账号密码重置

如果只是忘记管理员密码，不需要删除数据库，直接重置即可：

```bash
# 进入 web 容器
docker exec -it omichub-web bash

# 重置 admin 密码为 admin123（开发环境）
python - <<'PY'
import asyncio
from omichub.core.security import hash_password
from omichub.infrastructure.database.session import get_session_factory
from omichub.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository

async def reset():
    factory = get_session_factory()
    async with factory() as session:
        repo = SqlAlchemyUserRepository(session)
        user = await repo.get_by_username("admin")
        if not user:
            print("未找到 admin 用户")
            return
        user.hashed_password = hash_password("admin123")
        await repo.save(user)
        print("admin 密码已重置为 admin123，请登录后立即修改")

asyncio.run(reset())
PY
```

重置后使用 `admin / admin123` 登录，并在 **系统设置 → 个人中心** 修改为强密码。

### 数据库重置

```bash
# 方式 1：回滚最后一个迁移再重新执行
docker exec omichub-web uv run alembic downgrade -1
docker exec omichub-web uv run alembic upgrade head

# 方式 2：重置到指定版本
docker exec omichub-web uv run alembic stamp <revision_id>
docker exec omichub-web uv run alembic upgrade head

# 方式 3：彻底重建（⚠️ 删除所有数据）
docker compose -f deploy/docker/docker-compose.yml down -v
docker volume create --name deploy_pg_data 2>/dev/null; true
make docker-up-all
docker exec omichub-web uv run alembic upgrade head
docker exec omichub-web uv run python scripts/init_admin.py
```

### AI 聊天会话清理

```bash
# 清空所有聊天会话和消息（保留助手配置）
docker exec omichub-db psql -U omichub -d omichub -c "
  DELETE FROM chat_messages;
  DELETE FROM chat_sessions;
  DELETE FROM ai_messages;
  DELETE FROM ai_conversations;
"

# 清空测试技能
docker exec omichub-db psql -U omichub -d omichub -c "
  DELETE FROM skills WHERE is_builtin = false;
"
```

## 项目结构

```
src/omichub/          后端 Python 包 (DDD 分层)
  api/                表示层 - FastAPI 路由
    v1/               API v1 路由
      admin/          管理员路由 (skills/assistants/cookies/users)
  application/        应用层 - 用例编排
    services/         应用服务 (ai_service/chat_service/skill_service/...)
    schemas/          Pydantic DTO
  domain/             领域层 - 七域 (user/flow/task/file/ai/mcp/skill)
  infrastructure/     基础设施层
    ai_provider/      LLM Provider (litellm/kimi/openai_compatible)
    database/         SQLAlchemy ORM + 仓储实现
  core/               核心配置 (config/security/exceptions/logging)
  middleware/         中间件 (auth/rbac/cookie/rate_limit)
frontend/             前端 Vue 3
  src/
    components/       组件 (ai-chat/ admin/ sandbox/ knowledge/ dashboard/)
    composables/      组合式函数 (useChatStream/useAIWebSocket/...)
    stores/           Pinia 状态 (chatSession/chatAssistant/ai/auth/...)
    views/            页面
deploy/docker/        Docker 部署配置
  docker-compose.yml  主栈开发环境 (web/db/redis/nginx/beat/flower)
  docker-compose.worker.yml  独立 Worker 计算栈
  docker-compose.prod.yml  生产环境 override
  nginx/nginx.conf   nginx 配置 (bind mount 挂载 frontend/dist)
flows/                Snakemake 流程 YAML (rna_seq/atac_seq)
tool_configs/           生信工具箱工具配置 (YAML 热重载)
  terminal/           云端沙盒终端 (Dockerfile + terminal_config.yaml)
  jbrowse/            JBrowse 2 基因组浏览器配置
  enrichments/        KEGG/GO 富集分析物种配置
data/                 AI Provider YAML 配置
docs/                 架构设计文档
  knowledge/         实验室知识库 (meta.yaml 导航 + *.md 正文)
```

## 镜像与容器

平台所有服务均以 Docker 容器运行，镜像分为**自研应用镜像**、**分析运行时镜像**、**AgentTeams AI 编排镜像**和**第三方基础设施镜像**四类。

### 自研应用镜像

| 镜像 | 构建文件 | 用途 | 典型大小 |
|------|---------|------|---------|
| `omichub-web` | `deploy/docker/Dockerfile` | FastAPI 后端控制面（Web / Beat / Flower 共用同一镜像） | ~3.9 GB |
| `omichub-worker` | `deploy/docker/Dockerfile.worker` | Celery 通用 Worker（内置 Docker CLI + Micromamba + Snakemake） | ~2.0 GB |
| `omichub-phylo-worker` | `deploy/docker/Dockerfile.phylo` | 系统发育分析 Worker（MAFFT / IQ-TREE / MrBayes / RAxML） | ~4.8 GB |
| `omichub-studio-egress-proxy` | `deploy/studio/proxy.Dockerfile` | OmicStudio 沙盒出站白名单代理 | ~130 MB |
| `omichub/sandbox-terminal` | `tool_configs/terminal/docker/Dockerfile` | 云端沙盒终端（samtools / bcftools / bedtools / fastqc 等） | ~950 MB |

### 分析运行时镜像

分层构建，上层继承下层，避免重复安装 R / Python 科学计算栈：

```
core (Python 3.12 + R 4.4 + DESeq2/edgeR/limma)           ~3.0 GB
  └── plot (+ matplotlib/seaborn/plotly + ggplot2/ggtree)  ~4.8 GB
        └── scrna (+ scanpy/Seurat/SingleCellExperiment)    ~6.2 GB
```

| 镜像 | 标签 | 构建文件 | 用途 |
|------|------|---------|------|
| `omichub-analysis` | `core-2026.07` | `deploy/runtime-images/core.Dockerfile` | 差异分析核心（DESeq2 / edgeR / limma） |
| `omichub-analysis` | `plot-2026.07` | `deploy/runtime-images/plot.Dockerfile` | 可视化层（ggplot2 / plotly / ggtree） |
| `omichub-analysis` | `scrna-2026.07` | `deploy/runtime-images/scrna.Dockerfile` | 单细胞层（scanpy / Seurat / SCE） |
| `omichub-r-deg` | `v1` | `deploy/docker/Dockerfile.deg` | DESeq2/edgeR 差异表达独立运行时 |
| `omichub-r-enrichment` | `v1` | `deploy/docker/Dockerfile.enrichment` | clusterProfiler GO/KEGG 富集分析运行时 |

### AgentTeams AI 编排镜像

| 镜像 | 构建文件 | 用途 | 典型大小 |
|------|---------|------|---------|
| `omichub-agentteams-bridge` | `integrations/agentteams/bridge/Dockerfile` | Bridge 侧车（任务分发 / 状态管理 / Gateway 代理） | ~181 MB |
| `omichub-agentteams-gateway` | `integrations/agentteams/gateway/Dockerfile` | Gateway（Agent 注册 / 令牌校验 / 审计） | ~180 MB |
| `omichub-agentteams-worker-*` | `integrations/agentteams/worker/Dockerfile` | Worker 池（professional-pool / analysis / quality / delivery） | ~125 MB |

### 第三方基础设施镜像

| 镜像 | 版本 | 用途 |
|------|------|------|
| `pgvector/pgvector` | `pg14` | PostgreSQL 14 + pgvector 向量扩展 |
| `redis` | `7-alpine` / `7.4-alpine` | 缓存 + Celery 消息队列 + AgentTeams 状态存储 |
| `nginx` | `alpine` | 反向代理 + 静态资源服务 |
| `edoburu/pgbouncer` | `v1.25.2-p0` | PostgreSQL 连接池 |
| `prometheuscommunity/postgres-exporter` | `v0.17.1` | PostgreSQL Prometheus 指标导出 |
| `minio/minio` | `latest` | S3 兼容对象存储（AgentTeams 证据归档） |
| `minio/mc` | `latest` | MinIO 初始化（一次性创建 Bucket） |
| `apache/rocketmq` | `5.3.2` | RocketMQ 消息队列（可选，profile 控制） |
| `ollama/ollama` | `latest` | 本地 Embedding 模型服务（可选，profile 控制） |

### 当前运行容器清单

以下为平台完整部署后的容器组成（单机模式，2026-08 实测）：

| 分类 | 容器名 | 镜像 | 说明 |
|------|--------|------|------|
| **控制面** | `omichub-web` | `omichub-web` | FastAPI 后端 |
| | `omichub-nginx` | `nginx:alpine` | 反向代理 |
| | `omichub-db` | `pgvector/pgvector:pg14` | PostgreSQL 数据库 |
| | `omichub-cache` | `redis:7-alpine` | Redis 缓存 |
| | `omichub-pgbouncer` | `edoburu/pgbouncer` | 数据库连接池 |
| | `omichub-beat` | `omichub-web` | Celery Beat 调度器 |
| | `omichub-flower` | `omichub-web` | Celery 监控面板 |
| | `omichub-postgres-exporter` | `postgres-exporter` | 数据库指标导出 |
| | `omichub-minio` | `minio/minio` | 对象存储 |
| | `omichub-studio-egress-proxy` | `omichub-studio-egress-proxy` | Studio 出站代理 |
| **Worker** | `omichub-worker` | `omichub-worker:dev` | Celery 通用 Worker |
| | `omichub-phylo-worker` | `omichub-phylo-worker:dev` | 系统发育 Worker |
| **AgentTeams** | `omichub-agentteams-bridge` | `omichub-agentteams-bridge` | AI Agent Bridge |
| | `omichub-agentteams-gateway` | `omichub-agentteams-gateway` | AI Agent Gateway |
| | `omichub-agentteams-state` | `redis:7.4-alpine` | AgentTeams 状态存储 |
| | `agentteams-worker-professional-pool-{1,2}` | `omichub-agentteams-worker-*` | 通用 Agent 池（2 副本） |
| | `agentteams-worker-analysis` | `omichub-agentteams-worker-*` | 分析 Worker |
| | `agentteams-worker-quality` | `omichub-agentteams-worker-*` | 质量审计 Worker |
| | `agentteams-worker-delivery` | `omichub-agentteams-worker-*` | 交付报告 Worker |
| **监控** | `prometheus` | `prom/prometheus` | 指标采集 |
| | `grafana` | `grafana/grafana` | 可视化看板 |
| | `loki` | `grafana/loki` | 日志聚合 |
| | `seq` | `datalust/seq` | 结构化日志 |

> 💡 单机完整部署约 **25 个容器**。`professional-pool` 默认 2 副本（可通过 `AGENTTEAMS_PROFESSIONAL_POOL_REPLICAS` 调整）；其余服务均为单实例。跨机器部署时 Worker 可按需水平扩展，控制面容器不变。

## 数据目录结构

平台运行时数据统一收口在宿主机 `/data/omichub`（由 `data/OmicHub.yaml` 的 `storage.data_root` 声明）。**数据库、缓存、参考基因组、知识库、欢迎词**五类核心数据已集中迁至 `omichub_data/` 子目录，让数据区更清爽；用户上传、任务产物等仍直接落在根下。

```
/data/omichub/                      # 数据根目录（storage.data_root）
├── omichub_data/                   # ★ 集中数据区
│   ├── _pgdata/                    # PostgreSQL 数据库（bind mount，uid 70 / 700）
│   ├── _redis/                     # Redis 持久化 dump.rdb（bind mount，uid 999）
│   ├── jbrowse/                    # JBrowse 2 参考基因组 + 预设轨道（ref/ tracks/）
│   ├── knowledge/                  # 实验室知识库运行时副本（镜像自 docs/knowledge/）
│   └── welcome/                    # 管理员登录欢迎词（welcome.yaml + 轮询游标）
├── users/<user_id>/                # 用户私有数据（上传 / 结果 / 富集产物）
├── uploads/                        # 分片上传中转
├── bin/                            # 外置二进制（EBIDownload 等）
├── refdata/                        # 公共数据集
└── .tmp/                           # 临时文件
```

### omichub_data 各子目录

| 子目录 | 作用 | 挂载 / 配置来源 | 备注 |
|--------|------|-----------------|------|
| `_pgdata/` | PostgreSQL 全部关系型数据（账号/任务/AI 会话） | `db` 服务 bind mount → `/var/lib/postgresql/data` | 属主 postgres(uid 70)，`rsync` 需 `-a` 保留属主；停库后再迁移 |
| `_redis/` | Redis 持久化 + Celery 队列 + 限流缓存 | `cache` 服务 bind mount → `/data` | 属主 redis(uid 999)；缓存类数据，丢失可重建 |
| `jbrowse/` | 参考基因组 FASTA(3.3G) + 基因注释(3.2G) | `tool_configs/jbrowse/jbrowse_config.yaml` 绝对路径 | 经 nginx `/tracks/` 流式读取；位于 `data_root` 下，换算自动兼容 |
| `knowledge/` | 知识库 `meta.yaml` + `*.md` + 配图 | 镜像自仓库 `docs/knowledge/` | 在线编辑读仓库源；此为数据区备份副本 |
| `welcome/` | 预生成欢迎词数组 + 轮询游标 | `config.py` 的 `welcome_yaml` / `welcome_state_yaml` | 启动时不足 20 条自动调 AI 补齐 |

### 为什么这些路径不用改容器挂载

`omichub_data` 仍是 `data_root`（`/data/omichub`）的子目录，因此：

- 容器内 `/data/omichub` 挂载、nginx `/tracks/` alias、`storage.data_root` 均**未改动**；
- `to_tracks_uri()` 把绝对路径换算为 `/tracks/omichub_data/jbrowse/...`，nginx 天然可读；
- 仅需同步修改 `docker-compose.yml` / `docker-compose.prod.yml` 的 `db`/`cache` bind mount、`config.py` 的 welcome 路径、`jbrowse_config.yaml` 的 fasta/轨道路径。

### 快速备份 / 迁移

```bash
# 停服后增量同步整个数据根（含 omichub_data）
docker compose -f deploy/docker/docker-compose.yml down
./scripts/worker-compose.sh down
sudo rsync -aP --info=progress2 /data/omichub/ <目标机>:/data/omichub/
```

## 日志排查

平台日志统一收口到宿主机 `/data/omichub/logs/`。应用日志、Celery 单任务日志、Nginx 日志、Snakemake stdout/stderr 均有明确的容量保护策略。

### 目录结构

```text
/data/omichub/logs/
├── app/                          # web / beat / worker 应用日志
│   ├── omichub.log
│   ├── omichub.json.log
│   └── error.log
├── celery/                       # Celery 单任务日志
│   └── tasks/{task_id}.log
├── nginx/
│   ├── access.log
│   └── error.log
└── snakemake/
    └── {project_name}/{timestamp}/
        ├── stdout.log
        └── stderr.log
```

### 首次初始化

新机器或清空数据后执行一次：

```bash
sudo mkdir -p /data/omichub/logs/{app,celery/tasks,nginx,snakemake}
sudo chown -R ${PUID:-1000}:${PGID:-1000} /data/omichub/logs
sudo chmod -R 755 /data/omichub/logs
```

如需启用宿主机 logrotate 兜底 Nginx/Snakemake 文件日志：

```bash
sudo cp deploy/logrotate/omichub-logs /etc/logrotate.d/omichub-logs
sudo logrotate -d /etc/logrotate.d/omichub-logs
```

### 常用排查命令

```bash
# 实时跟踪应用日志
tail -f /data/omichub/logs/app/omichub.log

# 只看 ERROR
tail -f /data/omichub/logs/app/error.log

# 按任务查 Celery 文件日志
tail -f /data/omichub/logs/celery/tasks/{task_id}.log

# 查看最近一次 Snakemake stdout/stderr
ls -lt /data/omichub/logs/snakemake/{project_name}/

# JSON 日志按服务过滤（需 jq）
jq 'select(.record.extra.service == "audit")' /data/omichub/logs/app/omichub.json.log

# Nginx 5xx 请求
jq 'select(.status >= 500)' /data/omichub/logs/nginx/access.log
```

### 容量保护

| 日志类型 | 策略 | 默认值 |
|------|------|------|
| 应用日志 | loguru rotation/retention/compression | `50 MB` / `30 days` / `zip` |
| Celery 单任务日志 | loguru rotation/retention/compression | `20 MB` / `7 days` / `zip` |
| Docker stdout/stderr | Docker `json-file` 限制 | `50m` × `3` |
| Nginx 文件日志 | 宿主机 logrotate | `100M` 或 daily，保留 14 轮 |
| Snakemake 文件日志 | 宿主机 logrotate + 定时清理 | `200M` 或 daily，建议 30 天清理 |
| DB 任务日志 | repository 截断 | 单条 8192 字符，单任务最近 1000 条 |

### 环境变量

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SERVICE_NAME` | 服务标识（web/beat/worker） | `app` |
| `OMICHUB_LOG_LEVEL` | stdout 日志级别 | `INFO`（开发环境 DEBUG） |
| `OMICHUB_LOG_DIR` | 应用日志根目录 | `/app/logs` |
| `OMICHUB_LOG_ROTATION` | 应用日志轮转阈值 | `50 MB` |
| `OMICHUB_LOG_RETENTION` | 应用日志保留期 | `30 days` |
| `OMICHUB_LOG_COMPRESSION` | 应用日志压缩格式 | `zip` |
| `OMICHUB_CELERY_LOG_DIR` | Celery 单任务日志目录 | `${OMICHUB_LOG_DIR}/celery/tasks` |
| `OMICHUB_CELERY_LOG_ROTATION` | Celery 单任务日志轮转阈值 | `20 MB` |
| `OMICHUB_CELERY_LOG_RETENTION` | Celery 单任务日志保留期 | `7 days` |
| `OMICHUB_CELERY_LOG_COMPRESSION` | Celery 单任务日志压缩格式 | `zip` |
| `TASK_LOG_MESSAGE_MAX_CHARS` | DB 单条任务日志 message 最大字符数 | `8192` |
| `TASK_LOG_MAX_ENTRIES` | DB 单任务最多保留日志条数 | `1000` |

详细架构说明见 `ARCHITECTURE_DESIN/LOG_ARCHITECTURE.md`。

## 可观测性（Trace / Log / Metrics）

平台后端基于 **OpenTelemetry** 在关键链路统一埋点，同时产出三类信号：

- **Trace（span）**：记录一次 AI 调用 / MCP 工具调用 / Agent 编排 / 工具箱任务的耗时、状态与父子关系。
- **Log（结构化日志）**：每条 JSON 日志自动注入 `trace_id` / `span_id` / `request_id`，会话作用域内还会注入 `session_id`，可与 Trace 互相关联、并按聊天会话聚合。
- **Metrics（指标）**：耗时直方图与计数计数器，经 Prometheus `/metrics` 端点暴露；AI 调用指标还会**应用内持久化**到 `ai_call_metrics` 表（缓冲 + 后台批量写库，不阻塞调用链），驱动管理端「AI 指标仪表盘」的按日趋势与阈值告警。

> 本轮仅做**后端埋点**；采集链路（OTel Collector / Promtail / Grafana 看板）由部署侧自行接通。未配置 OTLP 端点时，traces 自动降级（debug 打印到控制台、生产 noop），metrics 仍通过 `/metrics` 暴露，**本地与测试零配置可用，遥测异常绝不中断业务**。

### 初始化与接线

- 统一入口 `src/omichub/core/telemetry.py::setup_telemetry(service_name)`，在 web（`main.py` lifespan）与 worker（`celery_app/celery.py`）启动时各调用一次，幂等。
- `instrument_app(app)` 挂载 FastAPI / httpx 自动埋点（HTTP server span + 出站 LLM HTTP）；`mount_metrics(app)` 暴露 `/metrics`。
- `middleware/trace_context.py::TraceContextMiddleware` 读/生成 `X-Request-ID` 并写入 ContextVar，响应头回写；注册为最外层中间件。
- `core/logging.py` 通过 loguru `patcher` 从当前 OTel span + ContextVar 注入 `trace_id` / `span_id` / `request_id` / `session_id` 到每条日志的 `record.extra`。`session_id` 由会话入口（`chat_service.stream_chat` / `_stream_agent_chat_inner`，覆盖 AI 助手 / Agent / AI 工作台三条流）在解析出会话后写入 ContextVar。

### 埋点覆盖（span 名称）

| 链路 | span 名称 | 关键属性 | 指标 |
|------|-----------|----------|------|
| AI Stack A（ProviderManager） | `ai.chat` | provider / model / status / tokens | `ai.chat.duration`、`ai.tokens` |
| AI Stack B（LiteLLM / Copilot） | `ai.chat`、`ai.embedding` | provider=litellm / model / tokens | 同上（补齐 Copilot 此前缺失的 usage） |
| MCP（builtin/stdio/sse） | `mcp.call_tool` | server / transport / tool / status | `mcp.call.duration`、`mcp.call.count` |
| Studio 沙箱 MCP | `mcp.sandbox.call_tool` | server_id / tool / status | `mcp.sandbox.call.duration`、`mcp.sandbox.call.count` |
| 技能执行 | `skill.execute` | tool_name / skill_id / status | `skill.execute.count`、`skill.execute.duration` |
| Agent 编排（父 span） | `agent.run` | agent_id / model_id / status | `agent.run.duration` |
| Agent 工具分发 | `agent.tool_dispatch` | tool.name / tool.call_id | — |
| Celery 任务（worker 根 span） | `celery.task` | task.name / task.id / status | — |
| 工具箱状态迁移 | —（结构化日志） | flow_id / status / duration | `toolbox.task.count`、`toolbox.task.duration` |
| Snakemake 流程执行 | `toolbox.flow.run` | flow_id / task_id / returncode | — |
| Docker 计算容器 | `toolbox.runner` | runner(deg/enrichment) / returncode | — |
| HTTP server | 自动（FastAPIInstrumentor） | route / status_code | `http_server_duration` 等 |

所有埋点复用现有脱敏约束（`openai_compatible.py::_sanitize_log_message` / `core/sanitizer.py`），span 属性与日志**不落 api_key、令牌、明文密钥**。

### 配置环境变量

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `TELEMETRY_ENABLED` | 可观测性总开关；关闭后全部 noop | `true` |
| `OTEL_EXPORTER_ENDPOINT` | OTLP gRPC 导出端点（如 `http://otel-collector:4317`）；为空时 traces 不导出 | 空 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTel 标准变量，作为上一项的兜底 | 空 |
| `OTEL_SERVICE_NAME` | 服务名覆盖；为空时按入口（web/worker/beat）自动取值 | 空 |
| `METRICS_ENABLED` | 是否在 `/metrics` 暴露 Prometheus 指标 | `true` |
| `SPAN_STORE_ENABLED` | 是否将 span 持久化到应用内 JSONL，供管理端 Trace 瀑布图查询 | `true` |
| `AI_METRICS_ENABLED` | AI 调用指标是否应用内持久化（`ai_call_metrics` 表，仪表盘数据源） | `true` |
| `AI_ALERT_ENABLED` | 是否启用 AI 指标阈值告警（错误率 / p95 / 日成本） | `true` |
| `AI_ALERT_ERROR_RATE` | 错误率告警阈值（0-1） | `0.05` |
| `AI_ALERT_P95_LATENCY_MS` | p95 延迟告警阈值（毫秒） | `10000` |
| `AI_ALERT_COST_RATIO` | 日成本超过近 7 日均值的倍数阈值 | `1.5` |
| `AI_ALERT_COOLDOWN_MINUTES` | 错误率 / p95 延迟告警冷却（分钟；日成本按自然日去重） | `30` |
| `LOG_RETENTION_ENABLED` | 是否启用日志/span 归档留存清理 | `true` |
| `LOG_RETENTION_HOT_DAYS` | 热数据保留天数（在线快速排查窗口） | `7` |
| `LOG_RETENTION_COLD_DAYS` | 冷数据保留天数；超期轮转归档由定时任务删除 | `90` |

### 问题排查实战

**1. 确认埋点与指标已生效**

```bash
# /metrics 返回 Prometheus 指标（含 ai_tokens_total、http_server_duration 等）
curl -s http://localhost:8000/metrics | grep -E "ai_tokens_total|http_server_duration"
```

**2. 用 request_id 串起一次请求的全部日志**

响应头会带 `X-Request-ID`；拿到它后在 JSON 日志里过滤，即可看到该请求从入口到 AI/MCP/工具调用的完整日志链：

```bash
REQ_ID=<响应头里的 X-Request-ID>
jq -c 'select(.record.extra.request_id == "'$REQ_ID'")' \
  /data/omichub/logs/app/omichub.json.log
```

**3. 用 trace_id 关联同一条 Trace 的日志**

span 内产生的日志都带相同 `trace_id`；用它可把一次 Agent 运行里分散的 AI / MCP / 技能日志聚合起来：

```bash
# 找出所有带 trace 的日志，按 trace_id 分组计数
jq -r '.record.extra.trace_id // empty' \
  /data/omichub/logs/app/omichub.json.log | sort | uniq -c | sort -rn | head

# 锁定某个 trace_id 看全链路
jq -c 'select(.record.extra.trace_id == "<TRACE_ID>")' \
  /data/omichub/logs/app/omichub.json.log
```

**4. 按事件类型定位链路耗时 / 失败**

埋点结构化日志统一带 `event` 字段（`ai.chat` / `mcp.call_tool` / `skill.execute` / `agent.run` / `toolbox.*` / `celery.task`）：

```bash
# 看所有失败的 AI 调用（含 model / 耗时 / usage）
jq -c 'select(.record.extra.event == "ai.chat" and .record.extra.status == "error")' \
  /data/omichub/logs/app/omichub.json.log

# 看慢 MCP 工具调用（>2s）
jq -c 'select(.record.extra.event == "mcp.call_tool" and (.record.extra.duration_ms > 2000))' \
  /data/omichub/logs/app/omichub.json.log

# 看某个工具箱任务的流转与耗时
jq -c 'select(.record.extra.event == "toolbox.task.transition" and .record.extra.flow_id == "rna_seq")' \
  /data/omichub/logs/app/omichub.json.log
```

**5. 按会话（session）排查 AI 助手 / Agent / AI 工作台问题**

会话作用域内的所有日志都带相同 `session_id`，可把一个会话里分散的 AI / MCP / 技能 / Agent 编排日志整体聚合：

- **管理端可视化**：系统管理 → **会话日志排查**（`/admin/session-logs`）。左侧按 `session_id` / 标题 / 用户检索会话（来自 `chat_sessions` 表），点「查看日志」右侧以时间线展示该会话的全部可观测事件（按 `event` 分类着色、展开 `data` 字段与 `trace_id`）；勾选「包含轮转归档」可查较旧会话。
- **命令行**：

```bash
# 聚合某个会话的全部日志（按时间）
jq -c 'select(.record.extra.session_id == "<SESSION_ID>")' \
  /data/omichub/logs/app/omichub.json.log

# 只看该会话里的失败事件
jq -c 'select(.record.extra.session_id == "<SESSION_ID>" and .record.extra.status == "error")' \
  /data/omichub/logs/app/omichub.json.log
```

> 后端接口：`GET /api/v1/admin/session-logs/sessions`（会话列表）、`GET /api/v1/admin/session-logs/{session_id}/events`（事件时间线，`include_archives=true` 时扫描轮转归档）、`GET .../{session_id}/report`（单会话运行报告：token/成本/耗时/工具与技能统计/错误摘要）、`GET .../{session_id}/events/export?format=json|csv`（导出，SQL 原文始终脱敏）。均仅管理员可访问。

**6. AI 指标仪表盘与告警**

系统管理 → **AI 指标仪表盘**（`/admin/ai-metrics`）按日展示 AI 助手 / Agent / AI 工作台调用的 token 用量、成本（🥫，按 `AI_TOKEN_COOKIE_RATE` 折算）、错误率与延迟（平均 / p95），并支持按模型过滤。数据来自应用内 `ai_call_metrics` 表。

告警（C4）由 Celery 每 5 分钟评估一次，超阈值且过冷却期时写入 `ai_metric_alerts` 并通过平台**通知公告**推送给全体用户：

- 错误率 > `AI_ALERT_ERROR_RATE`（默认 5%，近 5 分钟窗口）
- p95 延迟 > `AI_ALERT_P95_LATENCY_MS`（默认 10000ms）
- 日成本 > 近 7 日均值 × `AI_ALERT_COST_RATIO`（默认 150%）

持续超阈值时，错误率和 p95 延迟沿用 `AI_ALERT_COOLDOWN_MINUTES`（默认 30 分钟）重试提醒；日成本因按自然日汇总，同一条规则每天最多推送一次，避免全天重复通知。

> 后端接口：`GET /api/v1/admin/ai-metrics/trend`、`/models`、`/alerts/status`、`/alerts/history`（均仅管理员）。开关与阈值见 `AI_METRICS_ENABLED` / `AI_ALERT_*` 配置。

**7. 本地调试查看完整 span（Console 导出）**

开发环境（`APP_DEBUG=true`）且未配置 OTLP 端点时，span 会打印到控制台。触发一次对话 / 工具调用后，在 `docker logs omichub-web` 中即可看到 `ai.chat` / `mcp.call_tool` / `toolbox.*` 等 span 及其属性。

**8. 接通后端采集（可选，部署侧）**

配置 `OTEL_EXPORTER_ENDPOINT` 指向 OTel Collector 即可上报 traces/metrics；日志侧用 Promtail 采集 `/data/omichub/logs/app/omichub.json.log`，凭 `trace_id` 字段在 Grafana 中实现 Log ↔ Trace 互跳。

## 常用命令

| 命令 | 说明 |
|------|------|
| `make dev` | 启动后端开发服务器 |
| `make frontend-dev` | 启动前端开发服务器 |
| `make test` | 运行测试 |
| `make lint` | 代码检查 (ruff) |
| `make format` | 代码格式化 |
| `make migrate` | 执行数据库迁移 |
| `make migrate-new m="名称"` | 创建新迁移 |
| `make docker-network` | 创建跨栈外部网络 omichub_net（幂等） |
| `make docker-fix-permissions` | 修复 `/data/omichub` 日志/用户目录权限事故 |
| `make docker-up` | 启动主栈 (web/db/redis/nginx/beat/flower) |
| `make docker-up-worker` | 启动独立 Worker 计算栈 |
| `make docker-up-all` | 启动主栈 + Worker（一键全启） |
| `make docker-down-all` | 停止主栈 + Worker |
| `make docker-logs-worker` | 查看 Worker 日志 |
| `make docker-reload` | 重新构建前端并刷新主栈 + Worker |
| `make docker-clean` | 清理两栈容器与网络（保留数据卷） |
| `make docker-purge` | [危险] 彻底清理：容器+数据卷+网络+本地镜像+前端产物 |
| `make docker-start` | [危险] 彻底重建：purge + 重建镜像 + 构建前端 + 启动全部服务 |
| `make init-admin` | 初始化管理员账号 |
| `make init-cookies` | 初始化饼干定价策略 |
| `make check-migrations` | 静态检查 Alembic 迁移链完整性 |
| `make check-alembic-heads` | 检查数据库是否存在 Alembic 多分支 (Multiple Heads) |
| `make clean` | 清理 Python 缓存文件 |

## 数据库迁移

### 创建新迁移

```bash
make migrate-new m="add xxx table"
```

### 迁移链健康检查

新增或修改迁移文件后，务必运行静态检查，确保 `down_revision` 等依赖关系正确：

```bash
make check-migrations
```

`make check-migrations` 会在**不连接数据库**的情况下解析所有迁移文件，检查：

- 每个迁移文件都能正确解析 `revision`、`down_revision`、`depends_on`。
- `down_revision` / `depends_on` 指向的父迁移真实存在。
- 迁移链只有一个 root，且拓扑连通（无孤岛）。
- 最终 `alembic heads` 唯一。

**建议在以下场景执行：**

- 新建或修改了 `alembic/versions/` 下的迁移文件。
- 合并分支后迁移文件有冲突。
- 拉取他人代码后，本地发现 `alembic/versions/` 有新增文件。
- 提交代码前或 CI 流水线中。

如果检查失败，说明迁移链本身有问题，**不要提交、不要部署**，先修好 `down_revision` 再推进。

### Docker 权限事故恢复

如果 `make docker-reload` 后登录页提示“系统内部错误”，并且 `docker logs omichub-web` 出现类似：

```text
PermissionError: [Errno 13] Permission denied: '/app/logs/omichub.log'
```

说明宿主机 `/data/omichub/logs/app` 等 bind mount 目录被 root 创建或属主漂移，而 `web/worker` 容器按非 root 的 `1000:1000` 运行，无法写日志。执行：

```bash
make docker-fix-permissions
docker restart omichub-web omichub-worker omichub-beat
```

`docker-up`、`docker-up-worker`、`docker-up-all`、`docker-start`、`docker-reload` 已经会自动执行轻量版运行目录准备，正常情况下不需要手动处理。

### 常见迁移错误

#### `down_revision` 指向错误父节点

例如迁移 `g3h4i5j6k7l8_add_model_name_to_agent_templates.py` 的作用是向 `agent_templates` 表添加字段，因此它的 `down_revision` 必须指向创建 `agent_templates` 表的迁移 `9a5b6c7d8e1f`。如果错指向 `c2d3e4f5a6b7`（目录表迁移），则空库从头升级时会因表不存在而报错：

```
sqlalchemy.exc.ProgrammingError: relation "agent_templates" does not exist
```

修复方式：修正迁移文件中的 `down_revision`。

#### Alembic Multiple Heads（多分支）

当多人并行创建迁移且未正确合并时，可能出现多个 head。可通过以下方式检查：

```bash
make check-alembic-heads
```

若发现多分支，执行：

```bash
make migrate-merge
```

## 代码更新后如何更新容器

根据改动类型选择对应的更新命令，避免不必要的镜像重建或数据清理：

| 改动类型 | 推荐命令 | 说明 |
|---|---|---|
| 只改前端代码（`frontend/src/`） | `make docker-reload` | 重新构建 `frontend/dist`，并重启 nginx / web |
| 只改后端 Python 源码（`src/`） | `docker restart omichub-web omichub-beat omichub-worker` | 容器挂载 `src:ro`，重启即可加载新代码，无需重建镜像 |
| 改了流程 YAML（`flows/*.yaml`） | `curl -X POST http://localhost:8000/api/v1/flows/reload` | 流程支持热重载，无需重启服务 |
| 改了数据库模型或新增迁移文件 | 先 `make check-migrations`，再 `make docker-reload` | web 容器入口会自动执行 `alembic upgrade head` |
| 改了依赖（`pyproject.toml` / `uv.lock`）或 Dockerfile | `make docker-start` | 必须重建镜像；这会清空数据卷，开发环境可用，生产环境需谨慎 |
| 想彻底从零重建 | `make docker-start` | 执行 `docker-purge + build --no-cache + 构建前端 + up` |

### 日常迭代推荐

前端 + 后端源码的日常改动，统一用：

```bash
make docker-reload
```

它等价于：

```bash
cd frontend && npm run build
docker compose -f deploy/docker/docker-compose.yml restart nginx
docker compose -f deploy/docker/docker-compose.yml restart web
docker compose -f deploy/docker/docker-compose.yml up -d
./scripts/worker-compose.sh up -d
```

> ⚠️ `make docker-reload` **不会重建镜像，也不会删除数据卷**。如果改了 `pyproject.toml`、Dockerfile 或需要彻底清空环境，请用 `make docker-start`。

### 彻底重建环境

如果需要**完全重建**（清空容器、数据卷、本地镜像，并重新构建镜像 + 前端 + 启动全部服务），使用：

```bash
make docker-start
```

`make docker-start` 等价于：

```bash
make docker-purge          # 清空容器、数据卷、网络、本地镜像、前端 dist
cd frontend && npm run build
docker compose -f deploy/docker/docker-compose.yml build --no-cache
./scripts/worker-compose.sh build --no-cache
make docker-up-all
```

典型场景：
- 修改了 `pyproject.toml` 新增/删除依赖（例如安装 `lunardate`）。
- 修改了 `deploy/docker/Dockerfile`。
- `make docker-reload` 后应用启动报 `ModuleNotFoundError` 等镜像内依赖缺失错误。
- 想从零开始清理开发环境。

> ⚠️ `make docker-start` 会清空 PostgreSQL 与 Redis 数据卷，开发环境可用；生产环境请谨慎，执行前务必备份。

## 流程（Flow）扩展机制

OmicHub 采用 **YAML 声明式 + 通用构建器** 的架构来接入不同的 Snakemake 分析流程。新增流程时，**通常只需要在 `flows/` 目录下添加 YAML 配置文件**，无需修改后端 Python 代码。

### 流程加载方式

1. 服务启动后，首次访问 `/api/v1/flows` 时会懒加载 `flows/` 目录下所有 `*.yaml` / `*.yml` 文件；
2. 文件由 `FlowDomainService` 用 Pydantic 模型校验结构、参数唯一性、条件渲染引用等；
3. 校验通过的流程会缓存在内存中，以 `meta.id` 为唯一键；
4. 新增或修改 YAML 后，调用 `POST /api/v1/flows/reload` 即可热重载，无需重启服务。

### 核心设计

后端 `TaskService` 不再针对每个流程写 `if-elif` 分支，而是统一调用 `GenericFlowBuilder`。该构建器读取 YAML 中的 `pipeline_mapping` 节点，动态完成：

- 生成主配置文件（`config.yaml` / `analysis.yaml` 等，由 `execution.config_file_name` 指定）；
- 生成样本表 `samples.csv`；
- 生成差异比较组表 `contrasts.csv`（可选）；
- 注入动态计算字段（工作目录、样本表路径、比较组路径）。

### 新增一个分析流程的步骤

以新增 `chip_seq` 为例：

1. **创建 YAML 文件** `flows/chip_seq.yaml`，至少包含：
   - `meta`：流程元信息（`id` 必须全局唯一且符合 `^[a-z][a-z0-9_]*$`）；
   - `parameters`：前端动态表单参数定义；
   - `execution`：Snakefile 路径、资源配置、主配置文件名；
   - `sample_sheet`：样本表校验规则；
   - `pipeline_mapping`：参数到底层流程输入文件的映射规则。

2. **编写 `pipeline_mapping`**：

   ```yaml
   pipeline_mapping:
     config_fields:           # 直接写入主配置文件的字段
       - project_name
       - Genome_Version
       - species
       - raw_data_path
       - peak_calling.macs2_qvalue   # 支持点号生成嵌套字典
     computed_fields:         # 由构建器动态注入的字段
       workflow: "__work_dir__"
       sample_csv: "__samples_csv__"
       paired_csv: "__contrasts_csv__"
     list_fields:             # 强制转为字符串列表的字段
       - raw_data_path
     sample_sheet:
       output_name: "samples.csv"
       columns:
         sample: sample
         sample_name: sample_name
         group: group
     comparisons:
       output_name: "contrasts.csv"
       columns:
         Control: Control
         Treat: Treat
   ```

3. **放置 Snakefile**：确保 `execution.snakefile` 指向的 Snakemake 文件存在，并能读取生成的配置文件；

4. **热重载**：

   ```bash
   curl -X POST http://localhost:8000/api/v1/flows/reload \
        -H "Authorization: Bearer <token>"
   ```

   或直接重启后端服务。

5. **前端使用**：访问 `/api/v1/flows/chip_seq/schema` 可获取参数 JSON Schema，前端据此渲染表单；提交任务时 `/api/v1/tasks/submit` 的 `flow_id` 填 `chip_seq` 即可。

### 已有流程配置参考

- `flows/rna_seq.yaml` — RNAFlow 流程，主配置文件 `config.yaml`
- `flows/atac_seq.yaml` — ATACFlow 流程，主配置文件 `analysis.yaml`

### 注意事项

- `meta.id` 一旦确定尽量不要修改，数据库中的任务记录会关联该 ID；
- `pipeline_mapping` 缺失的流程只会被展示和解析，**无法提交执行**；
- 若某字段需要嵌套结构（如 `peak_calling.use_pooled_peaks`），在 `config_fields` 中使用点号路径即可；
- 所有字段默认值、动态占位符、类型转换规则均可在 `pipeline_mapping` 中声明。

## 数据下载与聚合（公共数据库 + 云存储）

平台内置「数据下载」入口（`/downloads`），统一承载公共数据库下载与云对象存储直拉。所有下载都会创建通用 `Task` 聚合根（历史 `flow_id="ebi_download"`，语义已扩展为 Data Download），任务日志、状态、进度、任务详情页和文件入库都复用现有任务系统，不额外创建 `download_tasks` / `download_files` 表。

### 架构

```text
Vue 下载页 (/downloads)
  ├─ 公共数据库：accession + method
  └─ 云存储：provider + object_uri + recursive
        │ POST /api/v1/downloads
        ▼
DownloadService
  ├─ 校验来源参数与目标目录
  ├─ 创建 Task(flow_id="ebi_download")
  └─ 投递 Celery run_download(task_id)
        ▼
Celery 下载任务
  ├─ source=sra           → EBIDownload + Progress API + Redis download_progress:{task_id}
  └─ source=cloud_storage → ossutil/tosutil/obsutil + stdout/stderr 进度解析
        ▼
TaskRepository + Redis Pub/Sub
  ├─ 回写 Task.status / Task.progress / Task.logs
  └─ 任务详情页实时展示日志与总进度
        ▼
_register_downloaded_files
  └─ 扫描 work_dir，写入 FileRecord，文件自动出现在「数据管理」
```

这套实现采纳了 `docs/26.7.8/OmicHub_云存储下载前后端连接方案.md` 中“前端选择云商 → 后端调用二进制 → 捕获进度 → 前端展示”的核心思路；未采纳新增三张下载表和独立 WebSocket 的部分，因为当前系统已有 Task 聚合、任务日志 WebSocket、Redis 下载进度和文件入库链路。

### 公共数据库下载（EBIDownload）

调用 Rust 写的 [EBIDownload](pipelines/EBIDownload) 工具从 EBI/NCBI 下载测序数据（FASTQ）。下载完成的数据会自动出现在「数据管理」中，可直接作为分析流程输入。该功能默认关闭，启用步骤如下。

#### 1. 构建 Rust 二进制

```bash
cd pipelines/EBIDownload
CC=clang cargo build -p ebidownload-cli --release
# 产物：target/release/EBIDownload
```

#### 2. 装运行时依赖

Worker 需要 `sra-tools`（`prefetch` / `fasterq-dump`）。宿主机或 worker 镜像任选一种方式安装：

```bash
# 方式 A：在 worker 容器/镜像内安装
mamba install -n base -c bioconda sra-tools

# 方式 B：用 EBIDownload 自带命令拉取（写入 EBIDownload.yaml 指向的路径）
./EBIDownload deps install
```

#### 3. 配置二进制与 YAML 路径

```bash
mkdir -p /data/omichub/bin
cp pipelines/EBIDownload/target/release/EBIDownload /data/omichub/bin/EBIDownload
cp pipelines/EBIDownload/EBIDownload.yaml /data/omichub/bin/EBIDownload.yaml
```

```env
ENABLE_EBI_DOWNLOAD=true
EBI_DOWNLOAD_BINARY=/data/omichub/bin/EBIDownload
EBI_DOWNLOAD_YAML=/data/omichub/bin/EBIDownload.yaml
```

### 云存储直拉（OSS / TOS / OBS）

云存储直拉通过对象存储官方 CLI 在 worker 节点执行下载，当前支持：

| 前端选项 | URI 前缀 | 默认二进制 |
| --- | --- | --- |
| 阿里云 OSS | `oss://bucket/path` | `/data/omichub/bin/ossutil` |
| 火山引擎 TOS | `tos://bucket/path` | `/data/omichub/bin/tosutil` |
| 华为云 OBS | `obs://bucket/path` | `/data/omichub/bin/obsutil` |

启用前需要把对应 CLI 放到 `/data/omichub/bin/`，赋予执行权限，并按云商工具自身规范在 worker 环境中配置访问凭据。OmicHub 当前不保存云厂商 AK/SK，也不新增云存储凭据表。

```env
ENABLE_CLOUD_STORAGE_DOWNLOAD=true
CLOUD_OSSUTIL_BINARY=/data/omichub/bin/ossutil
CLOUD_TOSUTIL_BINARY=/data/omichub/bin/tosutil
CLOUD_OBSUTIL_BINARY=/data/omichub/bin/obsutil
```

### 端到端验证

1. 访问前端「数据下载」页面（`/downloads`）。
2. 公共数据库：输入 `PRJNA1251654` 或单个 `SRRxxxxxx` 后提交；云存储：选择云商并输入 `oss://` / `tos://` / `obs://` URI 后提交。
3. 页面会跳转到任务详情页，可见任务状态、实时日志与总进度。
4. 任务 `success` 后刷新「数据管理」（`/files`），即可看到 `raw_data/<任务目录>/` 下的下载文件。

> 说明：下载产物落在 `storage_path/users/<user_id>/raw_data/<target_directory>/<任务目录>/`。FASTQ/BAM 会按文件后缀识别类型，其余对象以 OTHER 入库。大体量数据请确认 `/data/omichub` 所在磁盘容量充足。

## 实验室知识库（Knowledge Base）

知识库页面（`/knowledge`）采用「树形目录 + 沉浸式 Markdown 阅读 + 管理员在线编辑」的专业文档系统，基于 [md-editor-v3](https://github.com/imzbf/md-editor-v3) 实现。

### 数据来源与自动加载

知识库文档以纯文件形式存储在 `docs/knowledge/` 目录：

- `docs/knowledge/meta.yaml` —— 导航配置（标题、文档列表、可选 `category` 分类）
- `docs/knowledge/*.md` —— Markdown 正文

服务每次读取文档时**直接读盘**，因此保存后无需重启即可生效（重启后自动加载最新内容，无 DB 持久化）。

```yaml
# docs/knowledge/meta.yaml 示例
title: "实验室知识库"
items:
  - id: "getting-started"
    title: "快速入门"
    file: "getting-started.md"
    category: "上手指南"      # 可选，前端按它聚合成树形目录
  - id: "rna-seq-tips"
    title: "RNA-seq 分析小贴士"
    file: "rna-seq-tips.md"
    category: "流程说明"
```

### 在线编辑（管理员）

- **阅读模式**：左侧树形目录（按 `category` 分组）+ 右侧 `MdPreview` 预览（80%）+ `MdCatalog` 大纲导航（20%，sticky）。
- **编辑模式**（仅管理员可见「编辑」按钮）：满宽 `MdEditor` 编辑器；点「保存」回写 `docs/knowledge/<file>.md` 落盘，下次加载即为新内容；点「取消」还原。
- 接口：`GET /api/v1/docs/knowledge`（目录）、`GET /api/v1/docs/knowledge/{doc_id}`（正文）、`PUT /api/v1/docs/knowledge/{doc_id}`（保存，需管理员）。

### 安全

- 保存接口带路径遍历防护：`resolve()` 后必须仍在 `docs/knowledge/` 目录内，且只能改已配置条目对应的文件，禁止凭空新建或越权写盘。
- 原子写：先写 `.tmp` 再 `replace`，避免写一半损坏文件。

> 新增文档：在 `meta.yaml` 的 `items` 加一条，并在 `docs/knowledge/` 放对应 `.md` 文件即可（可热更新，无需迁移）。

## 云端沙盒终端

生信工具箱中的即用即毁隔离容器终端。用户在浏览器中获得交互式 bash shell，容器挂载个人工作目录，退出即销毁。

### 架构

```
浏览器 xterm.js  ──WebSocket──>  FastAPI 双向代理  ──aiohttp WS──>  容器内 ttyd:7681 (bash)
                                      │
                              DockerManager (创建/销毁)
                                      │
                              /data/omichub/users/{uid}/workspace  ←bind mount→  /home/omichub/workspace
```

### 启用与配置

1. 构建镜像（`make docker-reload` 自动执行，或手动）：

   ```bash
   docker build -t omichub/sandbox-terminal:latest tool_configs/terminal/docker/
   ```

2. 确保隔离网络存在（`make docker-reload` 自动创建）：

   ```bash
   docker network create omichub-sandbox-net
   ```

3. 所有运行参数集中在 `tool_configs/terminal/terminal_config.yaml`，修改后**自动热重载**（无需重启）：

   | 关键参数 | 默认值 | 说明 |
   |---------|--------|------|
   | `enabled` | `true` | 功能开关 |
   | `image.name:tag` | `omichub/sandbox-terminal:latest` | 容器镜像 |
   | `default_resources.memory_mb` | `512` | 内存上限 |
   | `lifecycle.idle_timeout` | `1800` (30min) | 空闲超时 |
   | `lifecycle.max_sessions_per_user` | `2` | 单用户最大并发 |
   | `storage.workspace_base` | `/data/omichub/users` | 用户目录基路径 |

### 安全策略

- **根文件系统只读** (`read_only=True`)，仅 workspace 和 tmpfs 可写
- **cap_drop ALL** + **no-new-privileges**，容器内非 root (`user 1000:1000`)
- **内存/CPU/PID 硬限制**，防止单用户耗尽资源
- **目录隔离**：仅挂载 `/data/omichub/users/{uid}/workspace`，无法访问其他用户或系统路径
- **即用即毁**：`auto_remove=True`，容器退出后自动删除

### 预装工具

samtools, bcftools, bedtools, fastqc, seqkit, python3 (numpy/pandas/biopython/pysam), vim, htop, jq

详细架构与代码分布见 `tool_configs/terminal/README.md`。

## 安全加固清单

本章节汇总 `SECURITY_AUDIT.md` 中识别的风险及对应的修复措施。首次部署或升级后请按此清单核对。

### 修复概览

| 编号 | 风险 | 修复位置 | 关键配置/说明 |
|---|---|---|---|
| #1 | 路径穿越 → 任意文件读取 | `file_service.py` / `report_service.py` | `_resolve_abs()` / `_resolve_report_path()` 强制 `resolve().relative_to(storage_root)` 校验 |
| #2 | `/tracks/` 无鉴权暴露用户数据 | `nginx.conf` / `nginx.prod.conf` | 默认启用 RFC1918 内网 IP 白名单 |
| #3 | 生产环境默认 JWT 密钥 | `config.py` | `APP_ENV=production` 时若密钥仍为默认值则启动失败 |
| #4 | Redis 无密码 + 端口暴露 | `docker-compose.yml` / `docker-compose.prod.yml` / `config.py` | 开发环境 `--requirepass`；生产关闭 Redis 宿主端口 |
| #5 | AI Provider key / TOTP secret 明文落盘 | `config.py` | 生产环境强制 `AI_PROVIDER_KEY_ENCRYPTION_KEY` 非空 |
| #6 | MCP stdio/SSE 的 RCE/SSRF | `mcp/client.py` / `mcp_service.py` | SSE URL 禁止内网/IP；stdio 禁止绝对路径与 shell |
| #7 | nginx 缺失安全头 + 聊天上传无校验 | `nginx.conf` / `nginx.prod.conf` / `files.py` | 增加 `X-Frame-Options` 等；上传文件扩展名白名单 |
| #8 | Flower 监控无鉴权 | `docker-compose.yml` / `docker-compose.prod.yml` | 开发环境 `--basic_auth`；生产默认关闭 Flower |
| #9 | 云存储 URI 只校验 scheme | `schemas/download.py` | 按云商校验 endpoint 后缀，禁止 IP 地址 |
| #10 | cookie balance Redis 频道无命名空间 | `cookie_pubsub.py` | 频道名改为 `omichub:cookie_balance:{user_id}` |
| #11 | 登录端点仅全局限流 | `auth.py` / `login_rate_limit.py` | 同一 IP 5 分钟失败 5 次封禁 15 分钟 |
| #12 | 终端会话 ID 熵低 | `terminal_service.py` | 改用 `secrets.token_urlsafe(16)` |
| #13 | WebSocket 异常 detail 回传客户端 | `sandbox.py` | 仅返回通用错误，详细异常进日志 |
| #14 | AI key 可能进异常日志 | `openai_compatible.py` | 日志脱敏：Bearer token / api_key 替换为 `[REDACTED]` |
| #15 | WebSocket 未校验用户禁用状态 | `ai.py` / `terminal.py` / `sandbox.py` / `cookies.py` / `tasks.py` | accept 前查库确认 `status == active` |
| #16 | Chat 附件读取 SSRF | `chat_service.py` | 非本地上传时禁止访问内网/回环/metadata URL |
| #17 | MCP stdio command 路径遍历 / args 未校验 | `mcp/client.py` | 禁止 `..`、PATH 白名单、args 禁止 shell 元字符 |
| #18 | AI Tool Call 参数无 schema 校验 | `ai_tools.py` | `TaskSubmitRequest` / `QueryStatusArgs` Pydantic 校验 |
| #19 | 登录限流 XFF 首个 IP 可伪造 | `login_rate_limit.py` | 取 `X-Forwarded-For` 链中最后一个 IP |
| #20 | JWT 无吊销机制 | `security.py` / `deps.py` / `user model` | 引入 `token_version`；改密/角色/状态变更时递增 |
| #21 | 沙盒容器未做网络隔离 | `sandbox/pool.py` / `config.py` | 默认 `sandbox_network_isolated=true` 使用 `network_mode=none` |
| #22 | 聊天文件上传全局可访问 | `files.py` / `chat_service.py` | 目录按 `chat/{user_id}` 隔离；下载校验归属 |
| #23 | TOTP `required` 策略未生效 | `auth_service.py` | `totp_policy=required` 时未绑定 2FA 拒绝登录 |
| #24 | 依赖存在已知 CVE（ecdsa） | `pyproject.toml` / `security.py` | 用 `PyJWT` 替换 `python-jose[cryptography]`，移除 ecdsa 依赖 |

### 首次部署必填环境变量

以下变量在 `.env` 中必须设置为强随机值，生产环境若缺失或仍为默认值应用将**启动失败**。

```bash
# JWT / Cookie 签名密钥（任意长随机字符串，建议 ≥32 字节）
JWT_SECRET_KEY=your-random-secret-here
APP_SECRET_KEY=your-random-secret-here

# Redis 认证密码
REDIS_PASSWORD=your-redis-password-here

# AI Provider key / TOTP secret 加密密钥（Fernet 32 字节 URL-safe base64）
# 生成方式：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AI_PROVIDER_KEY_ENCRYPTION_KEY=your-fernet-key-here

# 开发环境 Flower 基本认证（用户名:密码）
FLOWER_BASIC_AUTH=admin:your-strong-password
```

> 💡 **开发环境默认值**：`Makefile` 已默认设置 `REDIS_PASSWORD=omichub`。如果你通过 `make docker-up` / `make docker-reload` 启动，无需在 `.env` 中额外配置 Redis 密码；如需自定义，在 `.env` 中设置 `REDIS_PASSWORD` 即可覆盖。

> ⚠️ `AI_PROVIDER_KEY_ENCRYPTION_KEY` 一旦设置并写入数据后**不可更改**，否则已加密的字段将无法解密。

### `/tracks/` 数据访问说明

`/tracks/` 用于 JBrowse 2 流式读取参考基因组、BAM/VCF 等大文件。默认配置仅允许 RFC1918 内网地址访问：

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`

**公网或多租户部署**不应仅依赖 IP 白名单，建议：

1. 通过 VPN/专线访问；或
2. 实现后端鉴权代理 + nginx `X-Accel-Redirect` 内部重定向。

### MCP 管理安全

MCP Server 注册/调用为**管理员功能**，已做以下限制：

- SSE URL 仅允许 `http`/`https`，禁止指向内网、回环、`169.254.169.254` 等地址。
- stdio command 禁止路径遍历、绝对路径，且必须从 `PATH` 中解析得到；禁止常见 shell 解释器（`sh`/`bash`/`zsh`/`cmd`/`powershell` 等）。
- stdio args 禁止 shell 元字符（`;|&<>()$` 等）与绝对路径/路径遍历。

建议同时启用管理员 2FA、使用强密码，避免管理员凭据泄露后被滥用。

### 生产环境部署检查项

- [ ] `APP_ENV=production`、`APP_DEBUG=false`
- [ ] `JWT_SECRET_KEY`、`APP_SECRET_KEY`、`REDIS_PASSWORD`、`AI_PROVIDER_KEY_ENCRYPTION_KEY` 已设置且非默认值
- [ ] `OMICHBUB_INIT_ADMIN_PASSWORD` 为强密码
- [ ] 数据库端口已在 `docker-compose.prod.yml` 中关闭
- [ ] Redis 端口已在 `docker-compose.prod.yml` 中关闭
- [ ] Flower 服务已在生产关闭（`replicas: 0`）
- [ ] SSL 证书已挂载到 nginx
- [ ] `/tracks/` 仅允许受信内网访问
- [ ] 沙盒容器已启用网络隔离（`SANDBOX_NETWORK_ISOLATED=true`，默认开启）
- [ ] 聊天附件按用户隔离，不存在跨用户访问
- [ ] 依赖漏洞扫描（`pip-audit`）无高危以上漏洞

## 文档

详细架构设计见 `docs/` 目录：

- `OmicHub_CherryStudio_整合实施文档.md` — AI 助手 Cherry Studio SSE 架构
- `OmicHub_完整系统架构设计文档_v3.md` — 整体架构设计
- `modules/` — 各模块详细设计

## 当前工作区变更摘要

> 自动生成于 `2026-07-09T21:40:00+08:00`，反映当前 Git 工作区状态。

| 类型 | 数量 |
|------|------|
| 修改 (Modified) | 145 |
| 删除 (Deleted) | 26 |
| 未跟踪 (Untracked) | 18 |
| 子模块修改 | 1 |

### 主要结构性变更

- **docs/ 清理**：删除 13 个 `* copy.md` 副本文件。
- **tools/ 重命名**：仓库根 `tools/` 目录整体迁移为 `tool_configs/`，避免与后端代码包 `src/omichub/tools/` 同名混淆。

### 修改的文件（按目录分组）

#### ARCHITECTURE_DESIN/LOG_ARCHITECTURE.md
- ARCHITECTURE_DESIN/LOG_ARCHITECTURE.md

#### Makefile
- Makefile

#### README.md
- README.md

#### data
- data/OmicHub.yaml
- data/ai/providers.yaml

#### deploy/docker
- deploy/docker/Dockerfile
- deploy/docker/docker-compose.worker.yml
- deploy/docker/docker-compose.yml

#### docs
- docs/26.7.6/KEGG_Docker_契约.md
- docs/knowledge/data-directory-guide.md

#### frontend/public
- frontend/public/genomes.yaml

#### frontend/src
- frontend/src/api/terminal.ts
- frontend/src/components/ai-chat/legacy/KimiLayout.vue
- frontend/src/components/ai-chat/legacy/KimiSidebar.vue
- frontend/src/components/task/TaskTable.vue
- frontend/src/components/terminal/ImageSelector.vue
- frontend/src/components/terminal/ResourceSettings.vue
- frontend/src/layouts/DefaultLayout.vue
- frontend/src/mock/referenceGenomes.ts
- frontend/src/router/index.ts
- frontend/src/stores/chat.ts
- frontend/src/stores/terminal.ts
- frontend/src/types/download.ts
- frontend/src/types/index.ts
- frontend/src/types/jbrowse.ts
- frontend/src/types/site-content.ts
- frontend/src/types/terminal.ts
- frontend/src/views/BioTools/TerminalView.vue
- frontend/src/views/BioTools/ToolsHubView.vue
- frontend/src/views/DownloadsView.vue
- frontend/src/views/FilesView.vue
- frontend/src/views/HomeView.vue
- frontend/src/views/ReferenceGenomeDetailView.vue
- frontend/src/views/ReferenceGenomesView.vue

#### report
- report/01_架构梳理.md
- report/04_可优化点与建议.md

#### src/omichub/api/v1/admin
- src/omichub/api/v1/admin/admin_cookies.py
- src/omichub/api/v1/admin/platform_config.py
- src/omichub/api/v1/admin/stats.py

#### src/omichub/api/v1
- src/omichub/api/v1/announcements.py
- src/omichub/api/v1/chat.py
- src/omichub/api/v1/docs.py
- src/omichub/api/v1/downloads.py
- src/omichub/api/v1/notification.py

#### src/omichub/application/schemas
- src/omichub/application/schemas/agent.py
- src/omichub/application/schemas/base.py
- src/omichub/application/schemas/chat.py
- src/omichub/application/schemas/file.py
- src/omichub/application/schemas/flow.py
- src/omichub/application/schemas/site_content.py
- src/omichub/application/schemas/site_settings.py
- src/omichub/application/schemas/skill.py
- src/omichub/application/schemas/storage.py
- src/omichub/application/schemas/task.py
- src/omichub/application/schemas/terminal.py
- src/omichub/application/schemas/user.py

#### src/omichub/application/services
- src/omichub/application/services/agent_service.py
- src/omichub/application/services/ai_provider_yaml_loader.py
- src/omichub/application/services/ai_service.py
- src/omichub/application/services/cookie_service.py
- src/omichub/application/services/download_service.py
- src/omichub/application/services/flow_service.py
- src/omichub/application/services/sandbox_service.py
- src/omichub/application/services/site_settings_service.py
- src/omichub/application/services/skill_service.py
- src/omichub/application/services/storage_service.py
- src/omichub/application/services/task_cookie_consumer.py
- src/omichub/application/services/task_service.py
- src/omichub/application/services/terminal_service.py

#### src/omichub/core
- src/omichub/core/config.py
- src/omichub/core/logging.py

#### src/omichub/domain/ai
- src/omichub/domain/ai/services.py

#### src/omichub/domain/cookie
- src/omichub/domain/cookie/repositories.py

#### src/omichub/domain/file
- src/omichub/domain/file/repositories.py

#### src/omichub/domain/flow
- src/omichub/domain/flow/condition.py
- src/omichub/domain/flow/entities.py
- src/omichub/domain/flow/services.py
- src/omichub/domain/flow/value_objects.py

#### src/omichub/domain/skill
- src/omichub/domain/skill/entities.py

#### src/omichub/domain/user
- src/omichub/domain/user/repositories.py

#### src/omichub/infrastructure/ai_provider
- src/omichub/infrastructure/ai_provider/base.py
- src/omichub/infrastructure/ai_provider/kimi.py
- src/omichub/infrastructure/ai_provider/litellm_provider.py

#### src/omichub/infrastructure/celery_app
- src/omichub/infrastructure/celery_app/celery.py
- src/omichub/infrastructure/celery_app/logging.py
- src/omichub/infrastructure/celery_app/tasks/download.py
- src/omichub/infrastructure/celery_app/tasks/storage.py

#### src/omichub/infrastructure/config
- src/omichub/infrastructure/config/agent_loader.py
- src/omichub/infrastructure/config/storage_config.py

#### src/omichub/infrastructure/database/models
- src/omichub/infrastructure/database/models/__init__.py
- src/omichub/infrastructure/database/models/agent.py
- src/omichub/infrastructure/database/models/ai.py
- src/omichub/infrastructure/database/models/ai_provider.py
- src/omichub/infrastructure/database/models/announcement.py
- src/omichub/infrastructure/database/models/audit_log.py
- src/omichub/infrastructure/database/models/chat.py
- src/omichub/infrastructure/database/models/cookie.py
- src/omichub/infrastructure/database/models/file.py
- src/omichub/infrastructure/database/models/mcp_log.py
- src/omichub/infrastructure/database/models/notification.py
- src/omichub/infrastructure/database/models/report.py
- src/omichub/infrastructure/database/models/sandbox.py
- src/omichub/infrastructure/database/models/site_settings.py
- src/omichub/infrastructure/database/models/skill.py
- src/omichub/infrastructure/database/models/terminal.py

#### src/omichub/infrastructure/database/repositories
- src/omichub/infrastructure/database/repositories/ai_provider_repository.py
- src/omichub/infrastructure/database/repositories/announcement_repository.py
- src/omichub/infrastructure/database/repositories/cookie_repository.py
- src/omichub/infrastructure/database/repositories/file_repository.py
- src/omichub/infrastructure/database/repositories/mcp_repository.py
- src/omichub/infrastructure/database/repositories/notification_repository.py
- src/omichub/infrastructure/database/repositories/report_repository.py
- src/omichub/infrastructure/database/repositories/sandbox_repository.py
- src/omichub/infrastructure/database/repositories/task_repository.py

#### src/omichub/infrastructure/database
- src/omichub/infrastructure/database/base.py

#### src/omichub/infrastructure/download
- src/omichub/infrastructure/download/progress_crypto.py
- src/omichub/infrastructure/download/progress_poller.py

#### src/omichub/infrastructure/execution
- src/omichub/infrastructure/execution/binary.py
- src/omichub/infrastructure/execution/generic_builder.py
- src/omichub/infrastructure/execution/remote.py

#### src/omichub/infrastructure/terminal
- src/omichub/infrastructure/terminal/docker_manager.py

#### src/omichub
- src/omichub/main.py

#### src/omichub/middleware
- src/omichub/middleware/auth.py
- src/omichub/middleware/rate_limit.py
- src/omichub/middleware/rbac.py

#### src/omichub/tools/enrichments
- src/omichub/tools/enrichments/api.py
- src/omichub/tools/enrichments/config.py
- src/omichub/tools/enrichments/service.py

#### src/omichub/tools/jbrowse
- src/omichub/tools/jbrowse/api.py
- src/omichub/tools/jbrowse/config.py
- src/omichub/tools/jbrowse/schema.py
- src/omichub/tools/jbrowse/service.py

#### src/omichub/tools/registry
- src/omichub/tools/registry/api.py
- src/omichub/tools/registry/config.py

#### src/omichub/tools/terminal
- src/omichub/tools/terminal/config.py

#### src/omichub/tools
- src/omichub/tools/__init__.py

#### tests/integration
- tests/integration/test_agent_service.py
- tests/integration/test_downloads.py
- tests/integration/test_flows.py
- tests/integration/test_tasks.py

#### tests/unit/core
- tests/unit/core/test_logging.py

#### tests/unit
- tests/unit/test_download_service.py
- tests/unit/test_site_content_service.py

#### todo.md
- todo.md

### 删除的文件

- docs/26.7.5/Agent_Management_Bug_Fix_Plan copy.md
- docs/OmicHub_AI界面功能优化计划 copy.md
- docs/OmicHub_AI聊天窗口Kimi风格改造方案 copy.md
- docs/OmicHub_CherryStudio_整合实施文档 copy.md
- docs/OmicHub_生产级优化建议文档 copy.md
- docs/OmicHub_美化优化文档 copy.md
- docs/docs/modules/12_cookie_backend copy.md
- docs/docs/modules/13_cookie_frontend copy.md
- docs/docs/modules/14_cookie_integration copy.md
- docs/modules/12_cookie_backend copy.md
- docs/modules/13_cookie_frontend copy.md
- docs/modules/14_cookie_integration copy.md
- tools/README.md
- tools/enrichments/README.md
- tools/enrichments/species_config.yaml
- tools/jbrowse/jbrowse_config.yaml
- tools/terminal/README.md
- tools/terminal/docker/Dockerfile
- tools/terminal/docker/bashrc
- tools/terminal/docker/zshrc
- tools/terminal/terminal_config.yaml
- tools/terminal/terminal_images.yaml
- tools/tools_design.md
- tools/tools_setting.yaml
- tools/volcano/volcano_test_data.csv
- tools/volcano/volcano_test_data.tsv

### 新增/未跟踪的目录或文件

- alembic/versions/r6s7t8u9v0w1_add_home_quick_entries_to_site_settings.py
- change.md
- deploy/logrotate/
- docs/26.7.8/
- docs/26.7.9/
- docs/Makefile_命令说明.md
- docs/offline_reference_database_build.md
- docs/plan/2026-07-09_reference_database_optimization_plan.md
- docs/plan/KEGG_GO离线数据库获取方案.md
- frontend/src/config/
- frontend/src/utils/primerForgeProcessor.ts
- frontend/src/views/AdminHomeQuickEntriesView.vue
- frontend/src/views/BioTools/PrimerForgeView.vue
- scripts/README.md
- scripts/omichubtools/
- scripts/pyproject.toml
- tests/unit/test_file_service.py
- tool_configs/
