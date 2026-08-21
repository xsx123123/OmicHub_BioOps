# OmicHub BioOps

可复现的组学分析多 Agent 交付基础设施 —— 华中农业大学园艺林学学院

让每一次组学交付都**可审计、可验证、可复用**：以多 Agent 协同（AgentTeams）为组织层，以版本锁定的 Flow Framework 为执行层，以 Skills 沉淀领域经验，交付物附带 Case / Artifact / Evidence / Manifest 溯源证据包。

> 📜 **Licensed under Apache-2.0 + Commons Clause — non-commercial use only.**
> See [LICENSE](./LICENSE) for details. Commercial use requires a separate agreement.

## 平台概览

OmicHub 提供从轻量探索到受控交付的四级入口，共享同一份用户工作区数据底座（下载入库、零搬运、`omic://` 逻辑引用，按用户与 Case 严格隔离）：

| 产品形态 | 定位 | 特点 |
|---|---|---|
| 生信工具箱 | 简单、重复、确定性计算（序列分析 / 可视化 / 表达分析等 17+ 工具） | 零 token 消耗，部分纯浏览器本地运算 |
| 星尘 AI 助手 | 轻量、探索性需求，对话式调用工具与知识库 | MCP + Skill + 轻量沙箱，内置高频组学快捷场景 |
| AI 工作台（OmicStudio） | 交互式深度分析，面向专业生信工作者 | 沙箱终端 + 代码编辑 + 人工审核，沙箱隔离、用完即毁 |
| 多 Agent 协作室 | 交付性、影响结论的分析（BioOps Case 本体） | 计划 → 审批 → 执行 → 质控 → 交付，全程受控可审计 |

核心原则：**不让 LLM 为确定性计算花 token，不让探索性分析污染交付链路** —— 越靠近探索越自由，越接近交付约束越强。

竞赛方案与产品叙事见 `docs/info/26.8.21/OmicHubBioOps_初赛_v1.pdf`。

## 技术栈与总体架构

- **后端**：FastAPI + SQLAlchemy 2.0 + PostgreSQL 14+（pgvector）+ Redis 7 + Celery / RocketMQ
- **前端**：Vue 3 + TypeScript + Vite + Naive UI + Pinia
- **流程引擎**：Snakemake 8+，Flow Framework 版本化 + Conda 环境锁定 + 容器执行
- **AI / 多 Agent**：统一 Agent 装配（`data/ai/*.yaml` 声明）、MCP 工具接入、AgentTeams Bridge/Gateway 协同层
- **部署**：Docker Compose 多栈编排（主栈 + 独立 Worker 计算栈 + AgentTeams 栈），支持单机、跨机器与（规划中）Slurm/Kubernetes

```text
Browser → Nginx → Web/API ──→ PostgreSQL / Redis
                     │
                     ├──→ Celery/RocketMQ Worker 栈 → Snakemake → /data/omichub（共享存储）
                     └──→ AgentTeams Bridge/Gateway → 专家 Worker 池（按角色令牌最小权限）
```

多 Agent 责任分离模型：**Manager 只编排不执行；领域执行者不判定质量；Quality Auditor 独立核验；Delivery Reporter 只交付已过质量门的产物**。详细设计见 `ARCHITECTURE_DESIN/`（索引：`ARCHITECTURE_DESIN/README.md`）。

## 快速开始

### 环境要求

- Python >= 3.11、Node.js >= 18、Docker >= 24.0、uv

### 本地开发

```bash
uv sync                          # 后端依赖
cd frontend && npm install       # 前端依赖
make docker-up                   # PostgreSQL + Redis 等基础设施
make migrate                     # 数据库迁移
make init-admin                  # 初始化管理员（或访问 /setup 网页注册）
make dev                         # 后端 :8000
make frontend-dev                # 前端 :5173（另一个终端）
```

访问 http://localhost:5173（前端）或 http://localhost:8000/docs（API 文档）。

### Docker 部署（推荐）

```bash
cp .env.example .env && chmod 600 .env   # 替换所有默认密码与密钥
make frontend-build
make docker-up-all                       # 主栈 + Worker 一键全启
```

访问 `http://<服务器地址>:8888`。首次无管理员时访问 `/setup` 创建首位管理员（创建后该入口永久关闭，后端强制校验）。

> ⚠️ **改前端后必须重启 nginx 才能生效**：nginx bind mount `frontend/dist`，`docker up -d` 不会重启已运行容器。
>
> 💡 dev compose 已把 `src/`、`data/`、`alembic/`、`flows/`、`tool_configs/` bind mount 进容器：
> - 改代码 / 前端 / 流程 YAML → `make docker-dev-refresh`（秒级热刷新，不重建镜像）
> - 改 `data/ai/*.yaml` 或提示词 → 刷新页面即生效（mtime 热重载）
> - **仅** `pyproject.toml` / `uv.lock` / Dockerfile 变更才用 `make docker-reload`（重建镜像并刷新 pgvector 主栈 + RocketMQ + AgentTeams + Worker）

## Make 命令速查

完整说明见 `docs/update_info/26.6/Makefile_命令说明.md`；以下为按用途分组的核心命令。

### 开发与测试

| 命令 | 说明 |
|---|---|
| `make dev` / `make dev-worker` / `make dev-beat` | 启动后端 / Celery Worker / Beat |
| `make dev-rocketmq-worker` | 启动 RocketMQ Worker |
| `make test` / `make test-bridge` / `make test-frontend` | 后端测试 / AgentTeams Bridge 测试工程 / 前端单测+类型检查 |
| `make test-all` / `make test-cov` | 全量测试 / 覆盖率报告 |
| `make lint` / `make format` / `make type-check` | ruff 检查 / 格式化 / mypy |

### 数据库迁移

| 命令 | 说明 |
|---|---|
| `make migrate` / `make migrate-new m="..."` / `make migrate-rollback` | 执行 / 新建 / 回滚迁移 |
| `make check-migrations` | 静态检查迁移链完整性（不连数据库；改迁移后必跑） |
| `make check-alembic-heads` / `make migrate-merge` | 检测 / 修复 Multiple Heads 多分支 |

### 部署与运行

| 命令 | 说明 |
|---|---|
| `make docker-up` | 启动主栈（web/db/redis/nginx/beat/flower） |
| `make docker-up-pgvector` | 主栈 + pgvector/PgBouncer/Exporter 验收叠加 |
| `make docker-up-worker` / `make docker-up-all` | 启动 Worker 栈 / 主栈 + Worker |
| `make docker-up-cross-web` / `make docker-up-cross-worker` | 跨机器控制面 / 计算节点 |
| `make docker-up-agentteams` | 构建并启动 AgentTeams Bridge、Gateway 与生产 Worker |
| `make docker-up-matrix-dev` | 本机开发用 Matrix(Synapse)+Element 栈 |
| `make docker-dev-refresh` | 日常热刷新：前端 build + 重启 web/beat/nginx + 迁移 |
| `make docker-reload` | 全量热重载：重建前端 + pgvector 主栈 + RocketMQ + AgentTeams + Worker |
| `make docker-logs` / `make docker-logs-worker` | 查看主栈 / Worker 日志 |
| `make docker-down` / `docker-down-all` / `docker-stop-all` | 停主栈 / 主栈+Worker / 全平台 |
| `make docker-fix-permissions` | 修复 `/data/omichub` 权限事故（登录 500 / PermissionError 时） |

### 镜像构建

| 命令 | 说明 |
|---|---|
| `make docker-build-enrichment` / `docker-build-deg` / `docker-build-synteny` | 富集 / DEG / 共线性 R 运行时镜像 |
| `make docker-build-sandboxes` | 全量重建 13 个沙盒/分析运行时镜像（含核对清单） |
| `make docker-build-worker` / `docker-build-all-images` | Worker 镜像 / 一键重建所有镜像 |
| `make runtime-images-build` | Studio 分析运行时三件套（core/plot/scrna） |

镜像 tag 规范：发布产物必须打 git SHA 短号 tag（`IMAGE_TAG`），禁止 `latest` 裸推，见 `deploy/docker/README.md`。

### 清理（按破坏性分级）

| 命令 | 容器 | 数据卷 | 镜像 | 用途 |
|---|---|---|---|---|
| `make docker-clean` | down | 保留 | 保留 | 停服务，数据不动 |
| `make docker-purge` | 删除 | 清空 | 删除 | ⚠️ 只清理不启动（宿主 `/data/omichub` 不受影响） |
| `make docker-start` | purge + 重建 | 清空 | 重建 | ⚠️ 彻底重建并启动 |
| `make clean` | — | — | — | 清理 Python 缓存 |

### 其他

`make init-admin` / `init-cookies`（初始化管理员 / 饼干定价）、`make knowledge-reindex`（重建知识库向量）、`make sync-knowledge`（同步通用/QC/Cloud 知识库到数据库）、`make pgvector-acceptance` / `polardb-verify`（pgvector / PolarDB 验收）、`make agentteams-worker-env`（从 Bridge 配置生成最小权限 Worker 令牌文件）。

## 部署拓扑（deploy/）

```
deploy/
├── docker/            主栈与 Worker 栈：docker-compose.yml / .worker / .prod / .pgvector /
│                      cross-web / cross-worker 覆盖、各 Dockerfile、nginx、rocketmq 配置
├── agentteams/        AgentTeams 栈：Bridge/Gateway/Worker compose、bridge.env|worker.env
│                      模板、matrix-dev 开发栈、check_setup.sh 与各项验证脚本、kubernetes/
├── runtime-images/    Studio 分析运行时三件套（core/plot/scrna Dockerfile + build.sh）
├── studio/            OmicStudio 沙箱镜像（base/bio）、出站白名单代理、sandbox_agent
├── sandbox/           旧版沙盒池镜像（omichub/sandbox-base）
├── mas/               MAS Apptainer Worker（systemd unit + env 模板）
└── logrotate/         宿主机日志轮转配置（omichub-logs）
```

### 单机 / 跨机 / 生产

- **单机**：一份 `.env` + `make docker-up-all`；数据库、Redis 等默认只监听 `127.0.0.1`。
- **跨机器**：控制面与每台 Worker 各自维护私有 `.env`（共享密钥相同，网络/挂载路径按节点配置），分别执行 `make docker-up-cross-web` 与 `make docker-up-cross-worker`。Worker 路径统一由 `data/worker_config.yaml` 定义（`shared_data_dir` / `pipeline_dir`），容器内统一映射为 `/data/omichub`；**Web、Worker、计算节点必须看到一致的绝对路径**。
- **生产**：`docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.prod.yml up -d`（4 uvicorn worker + 关闭 DB/Redis 宿主端口 + SSL）；Worker 栈用 `./scripts/worker-compose.sh --scale worker=N up -d` 水平扩展。生产 `APP_ENV=production` 时默认密钥会导致启动失败。
- **私有镜像仓库**：云部署建议在 CI 构建并按 git SHA 推送 `omichub-backend` / `omichub-worker` / `omichub-frontend` 及分析运行时镜像，节点只拉取不可变 digest；不要把 `.env`、密钥或数据目录打进镜像。
- **HPC / Kubernetes**：Slurm 接入（Worker 转为 `sbatch` 提交器 + Snakemake profile）与 K8s 高可用（无状态控制面 + 按队列拆分 Worker + RWX PVC）为规划路径，详见 `report/07_K8s大规模部署方案.md`、`report/09_管理节点与任务节点分离方案.md`。

### 开启 Multi-Agent 与 AgentTeams

1. 平台内 Multi-Agent：`.env` 设置 `UNIFIED_INTENT_ROUTER_ENABLED=true`、`MULTI_EXPERT_CONSULTATION_ENABLED=true`，验证配额与延迟后再开 `SUBAGENT_FANOUT_ENABLED=true`。
2. AgentTeams Bridge：复制 `deploy/agentteams/bridge.env.example` 与 `worker.env.example`，为 Manager、Approval、Workflow Operator 与 14 个专家身份设置不同随机令牌；执行 `deploy/agentteams/check_setup.sh deploy/agentteams/bridge.env` 预检。
3. 预检通过后置 `AGENTTEAMS_BRIDGE_ENABLED=true`、`AGENTTEAMS_CHAT_ENTRY_ENABLED=true` 并填入 Bridge URL 与角色令牌；`make docker-up-agentteams` 拉起栈。

> 不要在 `.env`、`bridge.env`、README 或日志中保存真实密钥与令牌；泄露后立即撤销轮换。

## 项目结构

```
src/omichub/          后端 Python 包（DDD 分层）
  api/v1/             FastAPI 路由（含 admin/）
  application/        应用层（services/ 用例编排 + schemas/ DTO）
  domain/             领域层（user/flow/task/file/ai/mcp/skill/cookie）
  infrastructure/     基础设施（ai_provider / database / celery_app / mcp / execution / ...）
  core/               配置、安全、日志、遥测
  middleware/         auth / rbac / cookie / rate_limit / trace_context
frontend/             Vue 3 前端（components / composables / stores / views）
deploy/               部署编排（见上节）
integrations/agentteams/  AgentTeams Bridge / Gateway / Worker 工程（独立测试工程）
flows/                Snakemake 流程 YAML 声明（rna_seq / atac_seq）
pipelines/            流程实现（RNAFlow / ATACFlow / scrna / EBIDownload / jbrowse2 / ...）
tool_configs/         生信工具箱配置（tools_schema.yaml / terminal / jbrowse / enrichments / deg / ...）
data/                 运行时配置（OmicHub.yaml / ai/*.yaml / worker_config.yaml）
alembic/              数据库迁移
docs/                 文档（knowledge/ 知识库源、info/ 竞赛与评审材料、modules/ 模块设计）
ARCHITECTURE_DESIN/   项目级架构与设计文档（索引见其 README.md）
report/               架构审查、安全审查、K8s/存储/调度方案报告
scripts/              运维脚本（worker-compose.sh、迁移检查、知识库同步等）
tests/                后端测试（unit / integration / e2e / performance）
```

## 核心扩展机制

### Flow（流程）扩展：YAML 声明式接入

新增分析流程通常只需在 `flows/` 添加 YAML，无需改后端代码：`meta`（全局唯一 id）+ `parameters`（动态表单）+ `execution`（Snakefile 路径与资源）+ `sample_sheet` + `pipeline_mapping`（参数 → 流程输入文件映射，由 `GenericFlowBuilder` 动态生成 config/samples/contrasts）。改后 `POST /api/v1/flows/reload` 热重载。参考 `flows/rna_seq.yaml`、`flows/atac_seq.yaml`。

### 工具箱 ↔ AI 助手联动

工具在 `tool_configs/tools_schema.yaml` 注册为 LLM function，经内置 MCP `omichub-tools` 由 `ToolBridgeService` 校验分发（`backend_shim` / `backend_sync` / `backend_async` / `open_page` 四种调用模式），返回双通道结果：`llm_payload`（≤3KB 摘要回灌 LLM）+ `ui_payload`（前端渲染 `plotly_figure` / `table_data` / `confirm_card` / 任务进度卡）。大文本参数用 `upload://file_id` 引用已上传文件。新增工具步骤与规范见 `tool_configs/tools_design.md`。

### Skill 工程体系

平台内置技能市场、多通道导入与版本回滚；Bridge/MAS 契约层（`integrations/agentteams/skills/contracts.yaml`）经 allowlist 映射到可执行 Skill，均定义调用条件与失败语义；`mcp-builder` Agent 可将规范与代码沉淀为新的复用资产（见 `ARCHITECTURE_DESIN/mcp_builder_agent.md`）。

### 数据下载与聚合

「数据下载」（`/downloads`）统一承载公共数据库（EBIDownload → EBI/NCBI FASTQ）与云存储直拉（OSS/TOS/OBS 官方 CLI），复用通用 Task 聚合与实时日志链路，产物自动入库「数据管理」。默认关闭，通过 `ENABLE_EBI_DOWNLOAD` / `ENABLE_CLOUD_STORAGE_DOWNLOAD` 及 `/data/omichub/bin/` 下对应二进制启用。

### 知识库

`docs/knowledge/`（`meta.yaml` 导航 + Markdown 正文）为源，直接读盘热更新，管理员可在线编辑（路径遍历防护 + 原子写）；运行时经 `make sync-knowledge` 同步数据库并向量化供 AI 检索。架构见 `ARCHITECTURE_DESIN/knowledge_db.md`。

### 云端沙盒终端

即用即毁隔离容器终端（xterm.js → FastAPI WS 代理 → 容器 ttyd）：根文件系统只读、`cap_drop ALL`、非 root、资源硬限制、仅挂载本人 workspace、退出自动销毁。参数集中在 `tool_configs/terminal/terminal_config.yaml`（热重载）。详见 `tool_configs/terminal/README.md`。

## 数据与日志

### 数据目录（`/data/omichub`，bind mount，`docker-purge` 不删）

```
/data/omichub/
├── omichub_data/        集中数据区：_pgdata(PG) / _redis / jbrowse / knowledge / welcome
├── users/<user_id>/     raw_data / workspace / temp（按用户隔离，注册时幂等创建）
├── uploads/  bin/  refdata/  .tmp/  .conda_envs/
└── logs/                app / celery/tasks / nginx / snakemake
```

备份迁移：停服后 `sudo rsync -aP /data/omichub/ <目标机>:/data/omichub/`（`_pgdata` 需 `-a` 保留属主）。

### 日志排查

日志统一收口 `/data/omichub/logs/`，应用/Celery 日志由 loguru 轮转（50MB/30天、20MB/7天），Nginx/Snakemake 由宿主机 logrotate 兜底（`deploy/logrotate/omichub-logs`），Docker stdout 限制 50m×3。常用：`tail -f logs/app/omichub.log`、按任务 `logs/celery/tasks/{task_id}.log`、JSON 日志用 `jq` 按 `trace_id` / `session_id` / `event` 过滤。详细策略见 `ARCHITECTURE_DESIN/LOG_ARCHITECTURE.md`。

### 可观测性（OpenTelemetry）

统一埋点产出 Trace / Log / Metrics 三信号：日志自动注入 `trace_id`/`span_id`/`request_id`/`session_id`；`/metrics` 暴露 Prometheus 指标；AI 调用指标持久化到 `ai_call_metrics` 驱动管理端「AI 指标仪表盘」与阈值告警（错误率/p95/日成本，`AI_ALERT_*` 配置）；管理端「会话日志排查」（`/admin/session-logs`）可按会话时间线聚合全部事件。未配置 OTLP 端点时自动降级，**本地与测试零配置可用，遥测异常绝不中断业务**。覆盖 `ai.chat` / `mcp.call_tool` / `skill.execute` / `agent.run` / `celery.task` / `toolbox.*` 等 span，属性不落密钥。

## 安全

24 项安全加固已落地（路径穿越防护、`/tracks/` 内网白名单、生产默认密钥启动失败、Redis 认证、AI key Fernet 加密、MCP stdio/SSE 的 RCE/SSRF 防护、登录限流、JWT `token_version` 吊销、沙盒网络隔离、聊天附件按用户隔离等），完整清单见 `docs/SECURITY_AUDIT.md` 与 `report/05_安全审查报告.md`。

首次部署 `.env` 必填强随机值：`JWT_SECRET_KEY`、`APP_SECRET_KEY`、`REDIS_PASSWORD`、`AI_PROVIDER_KEY_ENCRYPTION_KEY`（Fernet key，**设置后不可更改**）、`FLOWER_BASIC_AUTH`。生产检查项：prod override 关闭 DB/Redis 端口与 Flower、挂载 SSL、`/tracks/` 仅受信内网、沙盒网络隔离开启、`pip-audit` 无高危漏洞。

账号密码重置、数据库重置、聊天会话清理等运维操作见 `docs/update_info/26.6/Makefile_命令说明.md` 与 `scripts/` 下对应脚本。

## 文档索引

- **架构与设计**：`ARCHITECTURE_DESIN/README.md`（总索引）——Agent 执行框架、协作室（AgentTeams）架构、记忆系统、MCP 子系统、日志架构、Worker 镜像计划、平台愿景定义等
- **竞赛/评审材料**：`docs/info/26.8.21/`（BioOps 初赛方案 PDF、协作室 L4 审查报告与实施手册）
- **模块设计**：`docs/modules/`；**命令详表**：`docs/update_info/26.6/Makefile_命令说明.md`
- **部署细节**：`deploy/docker/README.md`、`deploy/agentteams/README.md`、`deploy/docker/POLARDB_POSTGRES.md`
- **审查与规划报告**：`report/`（架构梳理、安全审查、任务调度、K8s、存储迁移等）
