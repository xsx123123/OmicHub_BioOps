# 分析中心 Celery + Snakemake 跨服务器部署实施方案

**编写日期**：2026 年 7 月 11 日  
**适用范围**：OmicHub Web 服务与分析计算 Worker 部署在不同服务器的场景  
**目标**：将耗时的 RNAFlow、ATACFlow 等 Snakemake 流程稳定地调度到计算服务器执行，同时让 Web 端持续获取任务状态、日志与流程进度。

## 一、结论：Snakemake 是否由 Celery 启动？

**是。当前实现中，Snakemake 由 Celery Worker 进程启动。**

调用关系如下：

```text
浏览器分析中心
  │ POST /api/v1/tasks
  ▼
Web API（TaskService）
  │ 1. 创建任务记录与工作目录
  │ 2. 生成流程输入配置
  │ 3. run_snakemake.apply_async(..., queue="analysis")
  ▼
Redis Broker（DB 1）
  ▼
Celery Worker（计算服务器，消费 analysis 队列）
  │ run_snakemake()
  ▼
LocalSnakemakeExecutor
  │ asyncio.create_subprocess_exec("snakemake", ...)
  ▼
Snakemake CLI → RNAFlow / ATACFlow 规则与 Conda 工具环境
```

对应实现位置：

- 任务提交与 Celery 投递：`src/omichub/application/services/task_service.py`
- Celery 任务入口：`src/omichub/infrastructure/celery_app/tasks/analysis.py`
- Snakemake 子进程执行：`src/omichub/infrastructure/execution/local.py`
- Celery 队列路由：`src/omichub/infrastructure/celery_app/celery.py`

因此，Worker 必须部署在能访问以下资源的计算服务器上：流程代码、参考基因组、用户上传数据、任务工作目录，以及 Snakemake/Conda 与流程依赖工具。

## 二、推荐双服务器架构

### 2.1 服务器角色

| 服务器 | 建议职责 | 必需组件 |
| --- | --- | --- |
| Web/控制服务器（例如 `10.0.0.10`） | 用户访问、API、鉴权、任务创建、数据库、队列、实时推送 | Nginx、Web、PostgreSQL、Redis、Celery Beat、可选 Flower |
| Worker/计算服务器（例如 `10.0.0.20`） | 消费分析任务并执行 Snakemake | Celery Worker、Snakemake、Conda/Mamba、RNAFlow/ATACFlow、分析软件环境 |
| 共享存储（NFS/并行文件系统） | 上传数据、任务工作目录、结果、日志 | 两端同一路径挂载，例如 `/data/omichub` |

### 2.2 通信拓扑

```text
                         用户浏览器
                             │ HTTPS / WSS :443
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ Web/控制服务器 10.0.0.10                                          │
│  Nginx → Web API                                                   │
│     │       │                                                      │
│     │       ├── PostgreSQL :5432（任务、用户、日志、报告元数据）   │
│     │       └── Redis :6379（Celery broker/result、Pub/Sub）      │
│     │                                                              │
│     └── /api/v1/workflow-monitor（接收 Worker 的流程事件）        │
└──────────────┬───────────────────────▲───────────────────────────┘
               │ Redis :6379           │ HTTP(S) :8000 /monitor
               │ PostgreSQL :5432      │ token + HMAC 签名
               ▼                        │
┌──────────────────────────────────────────────────────────────────┐
│ Worker/计算服务器 10.0.0.20                                       │
│  Celery Worker (-Q analysis)                                      │
│       │                                                           │
│       ├── 读取任务与更新状态 → PostgreSQL                          │
│       ├── 发布任务文本日志 → Redis Pub/Sub                        │
│       ├── 启动 Snakemake 子进程                                   │
│       └── Snakemake logger 事件 → Web Monitor API                 │
│                                                                    │
│  /data/omichub（共享挂载）                                        │
│  /home/zj/pipeline（流程代码，只读）                              │
│  /reference/...（参考基因组，只读）                               │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 各通信链路的用途

| 源端 → 目标端 | 协议/端口 | 用途 | 是否必须 |
| --- | --- | --- | --- |
| 浏览器 → Nginx | HTTPS/WSS `443`（或临时 `8888`） | UI、API、WebSocket | 必须 |
| Web → PostgreSQL | Docker 内部 `5432` | 持久化业务数据 | 必须 |
| Web → Redis | Docker 内部 `6379` | 发布 Celery 任务、实时日志 Pub/Sub | 必须 |
| Worker → Redis | TCP `6379` | 消费 `analysis` 队列、写 Celery 结果、发布日志 | 必须 |
| Worker → PostgreSQL | TCP `5432` | 读取任务、写状态/错误/报告记录 | 当前实现必须 |
| Worker → Web Monitor API | HTTP(S) `8000` / 经 Nginx `443` | 回传 Snakemake 规则级进度与事件 | 启用流程监控时必须 |
| Web 与 Worker → 共享存储 | NFS/并行文件系统 | 相同路径访问输入、配置、结果和日志 | 必须 |
| 运维终端 → Flower | HTTPS `443` 反代或内网 `5555` | 队列与 Worker 观测 | 可选 |

> 不要将 PostgreSQL、Redis、`8000` 或 `5555` 直接暴露到公网。跨服务器通信应使用专用内网、VPN 或安全组规则限制为 Worker 网段。

## 三、当前仓库已有部署文件

仓库已提供跨机 Compose 覆盖文件：

| 文件 | 使用位置 | 作用 |
| --- | --- | --- |
| `deploy/docker/docker-compose.cross-web.yml` | Web/控制服务器 | 将 `db`、`cache`、`web` 的端口绑定到 Web 内网 IP，供 Worker 访问。 |
| `deploy/docker/docker-compose.cross-worker.yml` | Worker/计算服务器 | 将 Worker 的 PostgreSQL、Redis 与监控 API 地址改为 Web 服务器 IP。 |
| `deploy/docker/docker-compose.worker.yml` | Worker/计算服务器 | 定义 Worker 镜像、流程目录、Conda/Mamba、共享任务目录与 `analysis` 队列消费命令。 |

这些文件中的 `10.0.0.10` 是示例地址，部署前必须替换为实际 Web 服务器的**内网地址或内部 DNS 名称**。

## 四、部署前的关键约束

### 4.1 共享文件系统是硬性条件

Web 创建任务时会写入任务目录和流程配置；Worker 执行时通过同一个 `work_dir` 读取它们。因此两端必须挂载到**同一份存储且路径完全一致**。

推荐统一为：

```text
/data/omichub/
├── users/<user_id>/uploads/...
├── users/<user_id>/results/<flow_id>/<task_id>/...
├── logs/celery/tasks/...
├── logs/snakemake/...
└── .conda_envs/...
```

实施建议：

- 优先使用 NFSv4、CephFS、Lustre 或已有并行文件系统；不要依赖两台机器各自本地磁盘的同名目录。
- 两台机器的挂载点统一为 `/data/omichub`，并用同一运行 UID/GID 保证读写权限。
- 工作流代码可使用 Git/镜像同步，也可只读挂载；参考基因组建议在计算节点本地高速盘或共享高性能存储，且配置路径必须与流程 YAML 匹配。
- 不建议把大型原始 FASTQ 先复制到 Web 本地磁盘再由 Worker 访问；上传目标应直接进入共享存储或对象存储挂载。

### 4.2 Worker 必须具备完整计算运行时

`docker-compose.worker.yml` 当前采取“容器调用宿主机已安装 Conda/Mamba 环境”的模式。Worker 服务器需准备：

1. Docker 与 Docker Compose v2。
2. `/home/zj/miniconda3`，包含可运行的 Snakemake 环境。
3. `/home/zj/.local/share/mamba`，包含 RNAFlow/ATACFlow 所需工具环境，或改为统一由 `--use-conda` 在 `/data/omichub/.conda_envs` 创建。
4. `/home/zj/pipeline`，包含 RNAFlow、ATACFlow 及其规则文件；容器按只读方式挂载。
5. 每个流程 YAML 指向实际可访问的原始数据、工作目录、结果目录和参考基因组路径。

生产上更稳妥的演进方向是：将 Snakemake 与所有必需工具环境做成版本化分析镜像，或使用 Conda lock 文件固化环境；不要只依赖某台 Worker 手工维护的环境状态。

### 4.3 Web 与 Worker 必须使用一致的应用版本和密钥

至少应保持以下配置一致：

- `SECRET_KEY`、数据库连接信息与 Redis 密码。
- `WORKFLOW_MONITOR_INGEST_TOKEN`（或 `OMICHUB_WORKFLOW_MONITOR_TOKEN`）。
- Workflow Monitor 相关开关与签名配置。
- 数据库 schema：先在 Web 服务器运行迁移，再启动 Worker。
- `flow` 配置、流程路径约定、共享存储根路径。

Worker 不需要对公网开放服务端口；它只需主动连向 Web/控制服务器和共享存储。

## 五、实施步骤

以下示例假设 Web 服务器为 `10.0.0.10`，Worker 服务器为 `10.0.0.20`。请替换为实际地址。

### 步骤 1：准备内网与防火墙

仅允许 Worker `10.0.0.20` 访问 Web `10.0.0.10` 的：

```text
TCP 5432   PostgreSQL
TCP 6379   Redis
TCP 8000   Workflow Monitor API（推荐后续改经 HTTPS 443 反向代理）
TCP 2049   NFS（若使用 NFS，按实际 NFS 配置开放）
```

浏览器仅访问 Web 的 `443`（或上线前临时 `8888`）。禁止向公网开放 `5432`、`6379`、`8000` 和 `5555`。

### 步骤 2：准备共享存储

在两端挂载同一共享目录，并验证路径与权限：

```bash
sudo mkdir -p /data/omichub
# 按实际 NFS 服务端、导出路径和运维规范挂载；示例：
sudo mount -t nfs4 <nfs-server>:/omichub /data/omichub

id
touch /data/omichub/.write-test && rm /data/omichub/.write-test
```

容器使用 `PUID`/`PGID` 运行；两端应使用相同的数值并确保它对共享目录有读写权限。

### 步骤 3：部署 Web/控制服务器

1. 将生产 `.env` 放在仓库根目录，设置强随机密码和令牌，至少包括：

```dotenv
POSTGRES_USER=omichub
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=omichub
REDIS_PASSWORD=<strong-password>
SECRET_KEY=<strong-random-secret>
WORKFLOW_MONITOR_INGEST_TOKEN=<long-random-token>
OMICHUB_WORKFLOW_MONITOR_TOKEN=<same-long-random-token>
PUID=<shared-uid>
PGID=<shared-gid>
```

2. 将 `deploy/docker/docker-compose.cross-web.yml` 中的 `10.0.0.10` 改成 Web 内网 IP；建议同步把 Worker 访问的 `8000` 改为仅反向代理的 HTTPS 内部域名。
3. 创建主栈所需外部 Docker 网络（单机主栈内部使用）：

```bash
docker network create omichub_net
```

4. 构建并启动 Web 主栈：

```bash
docker compose \
  -f deploy/docker/docker-compose.yml \
  -f deploy/docker/docker-compose.cross-web.yml \
  up -d --build
```

5. 通过 Web 容器迁移数据库（当前入口脚本支持 `RUN_MIGRATIONS=1` 的自动迁移；生产应确保只由一个 Web 实例执行迁移）。

### 步骤 4：准备 Worker/计算服务器

1. 将同一版本的 OmicHub 代码及 `.env` 放到 Worker；不要让 Worker 与 Web 使用不同提交版本。
2. 挂载共享 `/data/omichub`，并准备流程与参考资源：

```text
/home/zj/pipeline/RNAFlow
/home/zj/pipeline/ATACFlow
/home/zj/miniconda3
/home/zj/.local/share/mamba
/reference/... 或流程配置中定义的参考目录
```

3. 修改 `deploy/docker/docker-compose.cross-worker.yml`：

```dotenv
POSTGRES_HOST=10.0.0.10
REDIS_HOST=10.0.0.10
CELERY_BROKER_URL=redis://:<REDIS_PASSWORD>@10.0.0.10:6379/1
CELERY_RESULT_BACKEND=redis://:<REDIS_PASSWORD>@10.0.0.10:6379/2
WORKFLOW_MONITOR_INTERNAL_URL=http://10.0.0.10:8000/api/v1/workflow-monitor
```

实际文件中这些变量已存在；需要替换示例 IP。密码不要直接写入 Compose 文件，继续从 `.env` 注入。

4. 构建并启动只消费分析队列的 Worker：

```bash
docker compose \
  -f deploy/docker/docker-compose.worker.yml \
  -f deploy/docker/docker-compose.cross-worker.yml \
  up -d --build
```

Worker 的启动命令必须保留 `-Q analysis`；否则任务可能被投递到 `analysis` 队列但没有消费者。

### 步骤 5：上线验证顺序

按以下顺序执行，避免直接提交全量 RNA/ATAC 分析：

1. Web：`docker compose ps`，确认 `web`、`db`、`cache` 健康。
2. Worker：`docker compose ps`，确认 `worker` 健康；查看 `docker compose logs -f worker` 是否已连接 Redis。
3. 从 Web 容器或管理终端确认 Celery ping 能找到 Worker。
4. 在 Worker 容器中确认：`snakemake --version`、参考目录、流程目录与共享目录可访问。
5. 提交一个只含小型 FASTQ 的 `only_qc: true` 任务。
6. 确认任务状态由 `QUEUED → RUNNING → SUCCESS/FAILED` 正确变化。
7. 确认 Web 任务日志、流程监控页面、`/data/omichub/logs/snakemake/` 与结果目录均有预期输出。
8. QC 验证通过后，再进行 RNAFlow/ATACFlow 的完整 DAG 预演和生产任务。

## 六、状态、日志与监控如何跨机回传

### 6.1 任务状态

Worker 的 `run_snakemake` 任务直接连接共享 PostgreSQL：

```text
QUEUED → RUNNING → SUCCESS / FAILED
```

Web 从同一个数据库读取任务详情，因此不需要额外的状态同步服务。

### 6.2 文本日志

Celery Worker 会将关键日志写入数据库，并通过 Redis Pub/Sub 发布到 `task_logs:<task_id>`。Web 端可通过其 API/WebSocket 将日志展示给浏览器。

这条链路依赖 Worker 能访问 Redis `6379`，不要求 Web 主动访问 Worker。

### 6.3 Snakemake 规则级进度

`LocalSnakemakeExecutor` 在启用流程监控时向 Snakemake CLI 注入 logger 插件参数。插件把规则运行事件发送到：

```text
${WORKFLOW_MONITOR_INTERNAL_URL}/events
```

当前跨机覆盖文件将其设为：

```text
http://10.0.0.10:8000/api/v1/workflow-monitor
```

Web 的 `/api/v1/workflow-monitor/events` 接口会校验监控令牌，并在提供签名头时验证 HMAC 时间戳、nonce 与签名。生产建议：

- 通过内网 HTTPS 域名暴露 Monitor API，而不是跨机明文 HTTP。
- 使用长随机 Token，并定期轮换。
- 在防火墙上限制该接口只接受 Worker 网段。
- 保持 Worker 与 Web 的时钟同步（NTP/chrony），避免 HMAC 时间戳校验失败。

## 七、安全与可靠性建议

| 类别 | 建议 |
| --- | --- |
| 网络隔离 | Web 与 Worker 使用内网/VPN；数据库、Redis 和监控 API 只允许 Worker 网段访问。 |
| Redis | 必须设置强密码；生产建议启用 TLS 或把 Redis 放在私有网络内。 |
| PostgreSQL | 使用强密码、限制 `pg_hba.conf` 来源地址；生产可为 Worker 使用独立最小权限账户。 |
| 传输安全 | 浏览器侧使用 HTTPS/WSS；Worker→Monitor API 优先 HTTPS；敏感内部流量采用 VPN、mTLS 或服务网格按需加固。 |
| 容器权限 | Worker 使用非 root 的 `PUID:PGID`；流程代码与参考库只读挂载；仅任务/日志/Conda 缓存目录可写。 |
| 任务隔离 | 不将用户输入直接拼接为 shell 命令；限制 `cores`、内存、并发和单任务运行时长。 |
| 可靠性 | Celery 已设置长任务超时与 `worker_prefetch_multiplier=1`；建议增加失败告警、磁盘阈值告警和数据库/Redis 备份。 |
| 版本一致性 | Web/Worker 使用同一镜像 tag 或同一 Git commit；流程 YAML、参考库版本和 Conda 环境均应可追溯。 |

## 八、当前方案的限制与后续演进

### 当前可用方案

现有代码适合“单一控制面 + 多台计算 Worker”模式：所有 Worker 连接同一 PostgreSQL 和 Redis，消费同一 `analysis` 队列，并通过共享文件系统访问任务目录。

### 建议后续改进

1. **按计算能力拆队列**：例如 `analysis.cpu`、`analysis.highmem`、`analysis.gpu`，让不同 Worker 以 `-Q` 消费匹配队列；当前代码已有 `analysis.local`/`analysis.remote` 队列常量，但默认路由仍使用 `analysis`。
2. **避免 Worker 直连数据库**：未来可改为 Worker 调用受鉴权的内部 Task API 写状态，缩小数据库暴露面；这是架构演进，不是当前跨机部署的必要条件。
3. **引入 TLS/内部域名**：Redis/PostgreSQL/Monitor API 使用内部 DNS + TLS 或 WireGuard/Tailscale/VPN，替换裸 IP 与明文 HTTP。
4. **容器化分析依赖**：将流程依赖固化为版本化镜像或 Conda lock，减少宿主机挂载 Conda 环境的可变性。
5. **引入资源调度器**：当任务量或资源需求增长时，将 Snakemake 配置为提交 Slurm/PBS/Kubernetes，而 Celery 仅负责任务控制与状态聚合。

## 九、上线检查清单

- [ ] Web 与 Worker 的 OmicHub 镜像/代码版本一致。
- [ ] 数据库迁移已在 Web 端完成。
- [ ] Worker 可以访问 Web 的 `5432`、`6379`、`8000/443`。
- [ ] Redis 密码、数据库密码、`SECRET_KEY`、监控 Token 已使用生产强随机值。
- [ ] 两端 `/data/omichub` 是同一共享存储且挂载路径一致。
- [ ] Worker 可以读取流程代码、参考库、输入 FASTQ 和任务配置。
- [ ] Worker 可以写任务结果、Celery 日志、Snakemake 日志和 Conda 缓存。
- [ ] Worker 按 `-Q analysis` 启动并已通过 Celery ping 验证。
- [ ] 流程监控 URL 指向 Web 的真实内网 HTTPS/HTTP 地址，Token/HMAC 校验通过。
- [ ] 已用 `only_qc: true` 小样本完成端到端验收，再开放全流程任务。

