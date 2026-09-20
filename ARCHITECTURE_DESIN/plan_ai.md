# CygnusX 多智能体编排、共享工作区与 A2A 架构实施方案（评审稿）

> **状态：实施中（基础能力已落地，未完成生产验收）。**
>
> **实施分支：** `feat/ai-assistant-mas-a2a`（自 `main` 于 2026-07-18 创建）。
>
> **截至 2026-07-18 的实施进度：**
>
> - **Phase 0 已完成：** MAS 领域状态机、DAG/事件/Artifact 契约、工作区路径隔离、容器预检策略、ADR 与单元测试。
> - **Phase 1 核心链路已完成：** ORM、Alembic 迁移、Run/Artifact Registry、用户隔离 API、计划确认门、Artifact 完整性校验、仅投影元数据的 SSE 进度流，以及既有任务中心的 MAS Run 只读聚合投影。
> - **Phase 2 核心链路已完成：** PostgreSQL Outbox、Redis Stream Publisher/Consumer、计划批准后的节点解锁/派发、乐观锁、幂等消费、有限自动重试、Fake Worker、HITL 审批与断点恢复；修复补偿节点和真实 Worker 的生产恢复演练仍待完成。
> - **Phase 3 核心链路已完成：** Orchestrator 配置/Prompt、公共 Guardrails、服务端 Agent 能力校验、Chat/Studio 的结构化 `mas_plan` 预览适配，以及计划确认与实时进度卡；计划预览在用户确认前不会创建或执行 Run。
> - **Phase 4 受控执行已实现，待部署验收：** EBIDownload 清单、原生 Apptainer RNAFlow Worker、交付清单/QC 摘要、QC 覆盖审计、静态 PNG/PDF 火山图及容器预检均已实现；需要在具备 Apptainer、RNAFlow SIF、EBIDownload 凭据和测试 FASTQ 的环境中完成 E2E 验收。
>
> 所有 MAS API 仍受 `mas_enabled=false`（默认值）保护，因此不会改变现有单 Agent Chat/Studio 的默认路径。
>
> 本文将当前 CygnusX 的“单 Agent + MCP 工具调用闭环”逐步升级为可审计的多智能体系统（MAS）。目标是让用户在一个会话内发起跨数据下载、RNA-seq 流程和绘图等复合任务，由 Orchestrator 生成 DAG、各领域 Agent 在共享工作区内交付文件指针，并以 A2A 事件协议可靠协作。
>
> 本方案坚持增量演进：保留现有 Studio、MCP、Celery、Redis、任务中心和工作流监控；不在本阶段替换现有聊天链路，也不把大文件、完整日志或完整矩阵放进模型上下文。

---

## 1. 目标、边界与非目标

### 1.1 目标

1. 在一个统一对话窗口支持复合分析任务，例如：`S3 下载 → RNAFlow 定量/差异分析 → 火山图与报告`。
2. 用有向无环图（DAG）表达任务拆分、依赖、重试和人工审批点。
3. 在 Agent、Orchestrator 和任务 Worker 之间只传递**小型元数据与文件指针**，不传递原始 FASTQ、完整表达矩阵和长日志。
4. 用共享工作区保证下载程序、容器内流程、绘图脚本和用户可见产物读写的是同一份数据。
5. 将 RNAFlow、EBIDownload 及现有沙盒能力以受控 MCP 工具暴露给 Agent，而不是允许模型任意拼接宿主机命令。
6. 用可持久化、可重放的 A2A 事件协议实现 Agent 协作，并与现有任务中心/工作流监控统一展示。
7. 在失败时实现有限自愈、断点续跑和 Human-in-the-loop（HITL）审批。

### 1.2 非目标

1. 不在第一阶段引入新的消息中间件或替换 Redis/Celery；优先在既有 Redis 上实现 Stream/状态缓存，验证负载后再评估 NATS/Kafka。
2. 不允许任何 Agent 直接获得 Docker daemon、宿主机 shell 或无限制网络权限。
3. 不把 LLM 当作结果真实性判定器；关键生信质量结论必须来自结构化 QC 指标、规则校验和流程日志摘要。
4. 不要求一次性将所有现有工具改造成 MCP；先覆盖 EBIDownload、RNAFlow、数据探查和绘图四类关键能力。
5. 不更改当前单 Agent Studio 会话的默认行为；MAS 仅在任务分类器判定为“多步骤/长任务”且用户确认后启用。

---

## 2. 当前实现盘点与复用策略

### 2.1 已有基础

当前仓库已经具备本方案所需的大部分基础设施：

| 当前能力 | 现有位置 | 本方案中的定位 |
| --- | --- | --- |
| Agent 配置、模型/Prompt/MCP 组装 | `src/cygnusx/application/services/agent_service.py`、`data/ai/*.yaml` | 保留为 Agent 注册中心；新增“可执行角色/能力声明”。 |
| 单 Agent 流式 Tool-call 闭环 | `src/cygnusx/application/services/chat_service.py` | 保留为每个领域 Agent 的局部执行循环；MAS 在其外层增加 DAG 调度。 |
| MCP Server 注册表和客户端 | `src/cygnusx/infrastructure/database/models/mcp.py`、`src/cygnusx/infrastructure/mcp/` | 作为受控工具目录；扩展为管道/容器工具的统一入口。 |
| Studio 沙盒与长任务 | `src/cygnusx/application/services/studio_tools.py`、`src/cygnusx/infrastructure/celery_app/tasks/studio.py` | 复用用于代码探查、脚本与绘图；不作为重型流程的唯一执行器。 |
| Redis、Celery 和计算 Worker | `deploy/docker/docker-compose.worker.yml`、Celery 配置 | 复用为状态缓存、事件流和异步执行底座。 |
| 共享数据卷 | Worker 中的 `/data/cygnusx` 挂载 | 规范为 MAS 的唯一服务端工作区根；容器内映射到 `/workspace`。 |
| 工作流任务/事件监控 | `src/cygnusx/application/services/workflow_monitor_service.py`、`workflow_monitor_pubsub.py` | 复用前端可观测入口；新增 MAS Run/Node 的投影数据。 |
| RNAFlow/EBIDownload 仓库 | `pipelines/RNAFlow/`、`pipelines/EBIDownload/` | 首批 MCP 化的领域工具。 |

### 2.2 当前缺口

1. `stream_agent_chat` 是面向单个 Agent 的同步/流式工具调用循环，尚无跨 Agent 的 DAG 实体、依赖解析和恢复机制。
2. 已有任务/流程状态与 Studio 任务状态尚未形成统一的“父 Run → 子 Node → 产物”追踪模型。
3. 缺少可版本化的工作区产物清单（artifact manifest），因此下游难以稳定发现上游输出。
4. 缺少 A2A 消息信封、去重键、消息重放、失败转人工审批等协议。
5. Agent Prompt 当前更侧重专业问答/工具使用，尚未约束“只传指针、先校验产物、按状态机回报”。
6. 现有 MCP 注册模型可描述 server 和 tools，但缺少针对“容器镜像、输入/输出挂载、资源配额、幂等键、审批等级”的执行策略元数据。

### 2.3 核心设计决定

1. **控制面与数据面分离。** LLM、DAG、事件、状态和摘要属于控制面；FASTQ、BAM、矩阵、报告属于数据面。
2. **路径不是唯一真相。** 路径通过 Artifact Registry 注册为不可变版本，携带校验和、大小、格式、所有者、来源 Run/Node 与访问范围。
3. **Redis 负责快速协调，PostgreSQL 负责持久审计。** 任何“可恢复”的状态均最终落库；Redis 中断不能导致运行不可追溯。
4. **A2A 是事件协议而非 Agent 直接对话。** Agent 不相互塞 prompt；它们发布事件，Orchestrator 基于事件和 DAG 决定下游调度。
5. **容器执行经由受控执行器。** MCP Tool 只声明意图与参数，后端根据白名单镜像、挂载策略和资源限制生成容器任务；严禁向 Agent、Studio 沙盒或 RNAFlow 容器挂载 Docker socket。
6. **嵌套流程统一使用 Apptainer。** RNAFlow 中需要额外镜像的 Snakemake 规则通过专用计算节点上的 Apptainer 无特权运行；控制面 Docker 容器只提交受控任务，不能形成 Docker-in-Docker 权限链。
7. **公共原始数据采用内容寻址缓存。** 可复用 FASTQ 只在受控只读缓存中保存一份，Run 工作区通过经过校验的只读链接引用；缓存命中、并发下载和清理均由服务端管理。
6. **先采用单仓库模块化实现。** 首版不拆独立微服务；以 `src/cygnusx/domain/mas`、`application/services/mas_*`、Celery 任务和 API 路由组织，降低运维复杂度。

---

## 3. 目标架构

### 3.1 逻辑分层

```text
┌───────────────────────────────────────────────────────────────────┐
│  Web / Studio 统一会话                                              │
│  - 请求确认、计划卡片、进度、审批卡片、产物预览/下载                 │
└─────────────────────────────┬─────────────────────────────────────┘
                              │ REST + SSE/WebSocket
┌─────────────────────────────▼─────────────────────────────────────┐
│  MAS 控制面                                                         │
│  Intent Router → Orchestrator → DAG Scheduler → HITL Gate          │
│                   │                │                                │
│                   │                ├── State / Artifact Registry    │
│                   │                └── A2A Event Outbox             │
└───────────────────┼────────────────────────────────────────────────┘
                    │ 只传 task_id、artifact_id、受限路径、摘要
┌───────────────────▼────────────────────────────────────────────────┐
│  领域 Agent 执行面                                                   │
│  code_agent | rna_seq_agent | viz_agent | 后续 scRNA/ATAC Agent     │
│  - Agent 局部 Tool-call loop                                         │
│  - 输入预检、工具调用、结果校验、事件回报                             │
└───────────────────┬────────────────────────────────────────────────┘
                    │ MCP 调用（Schema + policy）
┌───────────────────▼────────────────────────────────────────────────┐
│  受控计算面                                                         │
│  MCP 工具 → Container Execution Gateway → Celery Workers            │
│  EBIDownload | RNAFlow | Studio Python/R | 图表渲染                   │
│  共享卷：host `/data/cygnusx/runs/<run_id>` ↔ container `/workspace` │
└───────────────────┬────────────────────────────────────────────────┘
                    │ 产物与日志落盘；事件/索引回传
┌───────────────────▼────────────────────────────────────────────────┐
│  基础设施                                                           │
│  PostgreSQL（审计/状态） | Redis（Stream/锁/缓存） | 共享存储         │
└───────────────────────────────────────────────────────────────────┘
```

### 3.2 执行路径

1. 用户在既有聊天/Studio 页面提交复合任务。
2. Intent Router 以轻量分类规则加 LLM 结构化输出，选择：继续单 Agent 对话、进入 MAS 计划预览，或要求补充元数据。
3. Orchestrator 仅产生受 schema 约束的 Plan Draft；服务端进行 DAG、路径模板、角色、工具能力和策略校验。
4. 用户确认计划后，创建 `MASRun`，复制经审计的计划版本，并创建 `MASNode`。
5. Scheduler 查找全部依赖满足的节点，将节点派发给目标 Agent Worker。
6. Agent 从 State/Artifact Registry 获取上游指针，调用 MCP 工具，校验输出并登记 Artifact。
7. Agent 写入 Outbox；事件发布器投递 Redis Stream，并更新节点状态。Scheduler 消费事件后解锁下游节点。
8. 所有终端节点完成后，Result Aggregator 生成用户可读摘要、产物链接和可追溯 manifest；若失败或需审批，则在原会话展示 HITL 卡片。

---

## 4. 共享工作区与状态管理

### 4.1 统一工作区契约

服务端真实根路径使用既有共享卷：

```text
/data/cygnusx/runs/<run_id>/
├── input/                 # 用户上传或数据管理软链接；默认只读
├── staging/               # 下载/解压的临时目录；可清理
├── workflow/              # RNAFlow 配置、样本表、Snakemake 元数据
├── results/               # 结构化分析结果
├── plots/                 # PDF/PNG/SVG/HTML 可视化产物
├── logs/                  # 原始运行日志，仅保存路径与摘要进入 LLM 上下文
├── manifests/             # artifact/run manifest 的 JSON 快照
└── scratch/               # 节点私有临时文件，节点结束后按策略回收
```

所有容器仅看到该 Run 的目录，统一挂载为：

```text
host: /data/cygnusx/runs/<run_id>
container: /workspace
```

规则：

1. 禁止模型生成 `/data/cygnusx`、`/etc`、用户 home 等宿主机路径；Prompt 中只暴露 `/workspace`。
2. API/执行器将容器路径映射回服务端路径，且必须使用 `Path.resolve()` 校验其仍位于 Run 根目录内。
3. `input/` 挂载为只读；工具写入 `staging/`、`workflow/`、`results/`、`plots/` 或节点专属 `scratch/`。
4. 不同用户/Run 绝不共享可写路径；跨 Run 仅可引用经过授权的只读 Artifact，禁止共享可写目录。
5. 产物保留、清理和归档由 Run 的数据生命周期策略决定，不由 Agent 自行删除。

### 4.2 公共原始数据缓存与去重

原始 FASTQ 不应复制到每一个 Run。新增由 `WorkspaceManager` 控制的内容寻址缓存，物理数据与 Run 工作区分离：

```text
/data/cygnusx/artifact-cache/raw/sha256/<digest>/
├── payload.fastq.gz
├── source.json            # URI、来源版本/ETag、下载时间、授权范围
├── checksum.json          # SHA-256、大小、验证工具与结果
└── cache_state.json       # writing | ready | quarantined | expired

/data/cygnusx/runs/<run_id>/input/raw_data/
└── sample_01_R1.fastq.gz -> 受控只读链接至 artifact-cache/raw/sha256/<digest>/payload.fastq.gz
```

强制规则：

1. 缓存键优先采用下载后验证的 `sha256`；下载前的候选键使用 `source URI + 对象版本/ETag + 预期大小`，不得把多段上传的 S3 ETag 当作内容校验和。
2. `writing` 状态由分布式锁保护；并发请求等待同一下载承诺或订阅其完成事件，避免缓存击穿后重复下载数百 GB 数据。
3. 对不存在、无权访问或格式非法的来源写入短 TTL 的负缓存和结构化错误码，并配合来源级速率限制，避免恶意/错误请求持续穿透到 S3/ENA。
4. 只有来源公开或授权范围、数据版本、完整性校验均匹配时才允许跨 Run 复用；私有、可变、失败校验或隔离中的数据不得进入共享缓存。
5. Run 内链接由服务端以受控相对路径创建并在容器中只读挂载；Agent 无权创建任意符号链接、修改缓存内容或解析缓存真实宿主路径。
6. Registry 为缓存 Artifact 维护 `reference_count`、租约、最后访问时间和保留策略。GC 仅清理引用数为零、无活跃租约且超过保留期的 `ready` 条目；可疑/校验失败文件先进入 `quarantined`，不向下游暴露。
7. 对不支持安全链接的远程/对象存储后端，使用只读 bind mount 或服务端复制，不以跨文件系统 symlink 作为回退。

### 4.3 Artifact Registry（状态字典的持久化实现）

新增 `mas_artifacts` 表，作为“全局状态字典”的持久真相源。Redis 只缓存热点索引。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `id` | UUID，A2A 与 API 中唯一传递的 Artifact ID。 |
| `run_id` / `node_id` | 产出所属 Run/Node。 |
| `logical_name` | 稳定语义名，例如 `raw_fastq_manifest`、`deg_results`、`volcano_plot_png`。 |
| `kind` | `file`、`directory`、`dataset_manifest`、`report`、`log`、`metric`。 |
| `workspace_path` | 服务端绝对路径；对 LLM/容器投影为 `/workspace/...`。 |
| `media_type` / `format` | MIME 与格式，如 `text/csv`、`application/pdf`、`fastq.gz`。 |
| `size_bytes` / `sha256` | 完整性与大文件治理依据。 |
| `schema_version` | CSV/JSON 等结构化文件的契约版本。 |
| `summary` | 限长结构化摘要，可进入模型上下文。 |
| `metadata` | 列名、行列数、样本数、QC 指标、产物尺寸等轻量信息。 |
| `visibility` | `private`、`run`、`project`、`shared`。 |
| `state` | `registered`、`validated`、`invalid`、`expired`。 |
| `created_at` / `expires_at` | 审计与清理。 |
| `storage_class` | `run_local`、`shared_cache`、`external_reference`，决定可复用与清理策略。 |
| `reference_count` / `lease_expires_at` | 防止共享缓存仍被运行中的 Run 使用时被回收。 |

逻辑键建议为：`run:<run_id>:artifact:<logical_name>`。同一逻辑名允许版本化，引用必须使用 `artifact_id`；只有计划草稿或人工输入阶段可以使用逻辑名解析最新版。

### 4.4 Context Budget 规则

对任何送入模型的上下文执行统一的 `Context Packager`：

| 内容 | 传递方式 |
| --- | --- |
| FASTQ/BAM/完整矩阵/大型图片 | 只传 `artifact_id`、格式、大小、受限路径；需要时通过工具抽样。 |
| 日志 | 只传末尾 N 行、错误分类、日志 Artifact 指针和固定上限摘要。 |
| CSV/TSV | 默认传表头、维度、前 5 行/随机抽样 5 行、缺失率和数值范围。 |
| RNAFlow 结果 | 传 `delivery_manifest.json` 解析后的摘要、QC 阈值状态、counts/DEG/report 的 Artifact 指针。 |
| 图像 | 传缩略图或图像理解结果摘要，不以 base64 全量注入。 |
| 历史消息 | 传会话摘要和当前 Run 状态，不无限堆叠原始对话。 |

默认限制建议：单个工具输出进入上下文不超过 10 KB；单次 Node 的结构化上下文包不超过 32 KB；超限内容自动落入 `logs/` 或 Artifact Registry，并返回 `artifact_id + 摘要 + tail`。

---

## 5. 数据模型与状态机

### 5.1 新增领域实体

| 实体 | 用途 |
| --- | --- |
| `MASRun` | 一次经用户确认的多 Agent 总运行；关联会话、用户、项目/工作区与计划快照。 |
| `MASPlan` | Orchestrator 生成且服务端验证后的 DAG JSON；计划版本不可变。 |
| `MASNode` | DAG 内的原子可调度节点；绑定目标 Agent、输入/输出契约、资源与重试策略。 |
| `MASArtifact` | 共享工作区中可追溯的文件/目录/指标。 |
| `A2AEvent` | 不可变事件信封；同时记录 Outbox 投递状态。 |
| `MASApproval` | 人工审批/补充信息/风险确认记录。 |
| `MASRetry`（可选） | 每次尝试的独立记录，便于保留完整诊断历史。 |

### 5.2 Run 状态机

```text
DRAFT → AWAITING_APPROVAL → QUEUED → RUNNING
                                   │       │
                                   │       ├→ PAUSED_FOR_INPUT
                                   │       ├→ CANCELLING → CANCELLED
                                   │       ├→ FAILED
                                   │       └→ SUCCEEDED_WITH_WARNINGS / SUCCEEDED
                                   └→ REJECTED
```

`PAUSED_FOR_INPUT` 只能通过用户明确操作恢复。任何执行型节点在 Run 不是 `RUNNING` 时不得启动。

### 5.3 Node 状态机

```text
PENDING → READY → DISPATCHED → RUNNING → VALIDATING → SUCCEEDED
                    │              │             │
                    │              │             └→ RETRY_WAIT → READY
                    │              ├→ WAITING_EXTERNAL
                    │              ├→ WAITING_APPROVAL
                    │              ├→ FAILED
                    │              └→ CANCELLED
                    └→ SKIPPED
```

关键规则：

1. 仅当所有 `depends_on` 节点为 `SUCCEEDED`（或显式允许的 `SKIPPED`）时，节点才可由 `PENDING` 进入 `READY`。
2. 所有状态转移必须带 `expected_version`（乐观锁）和事件记录，避免多个 Worker 重复调度同一节点。
3. `SUCCEEDED` 的前置条件是输出 Artifact 已登记并通过类型/文件存在性/校验规则；进程退出码为 0 不足以代表成功。
4. `FAILED` 与 `RETRY_WAIT` 的判定由错误分类和节点重试策略决定，不能由模型自由决定。
5. 用户取消时先停止尚未启动的节点，再向受控执行器发送终止请求；保留已产出的 Artifact 和日志供恢复使用。

### 5.4 最小数据库迁移

建议新增下列迁移，不修改既有 Chat/Task 表的语义：

1. `mas_runs`：`id`、`session_id`、`user_id`、`workspace_id`、`plan_id`、`status`、`context_summary`、`created_at`、`finished_at`、`version`。
2. `mas_plans`：`id`、`run_id`（草稿可为空）、`schema_version`、`plan_json`、`plan_hash`、`validated_at`、`created_by`。
3. `mas_nodes`：`id`、`run_id`、`node_key`、`agent_id`、`intent`、`depends_on`、`input_contract`、`output_contract`、`parameters`、`resources`、`status`、`attempt_count`、`max_attempts`、`idempotency_key`、`version`。
4. `mas_artifacts`：字段见 4.3，并对 `(run_id, logical_name, version)` 建唯一约束；共享缓存条目另以内容摘要和授权范围建立索引。
5. `mas_a2a_events`：`event_id`、`run_id`、`node_id`、`event_type`、`payload`、`dedupe_key`、`occurred_at`、`published_at`、`delivery_status`。
6. `mas_approvals`：`id`、`run_id`、`node_id`、`kind`、`prompt`、`options`、`response`、`status`、`expires_at`。
7. `mas_rework_guards`：`run_id`、`target_node_id`、`input_artifact_id`、`input_sha256`、`error_code`、`remediation_kind`、`fingerprint`、`attempt_count`、`status`，并对 `(run_id, target_node_id, fingerprint)` 建唯一约束。

现有任务中心通过 `flow_id = "mas"` 的只读投影展示 MAS Run；MAS 表仍是唯一真相源，不将复杂 DAG JSON 塞入现有 `TaskModel.parameters`。

---

## 6. A2A 事件协议

### 6.1 传输与可靠性

第一阶段采用 Redis Stream：

```text
Stream: cygnusx:mas:events
Consumer groups:
  - mas-scheduler
  - mas-monitor-projection
  - mas-notification
```

写入流程使用 **Transactional Outbox**：在同一 PostgreSQL 事务中完成 Node/Artifact 状态更新并写入 `mas_a2a_events`；独立 Publisher 将未发布事件写入 Redis Stream 后回填 `published_at`。这样即便 Redis 短暂不可用，也不会丢失状态变更。

投递语义为“至少一次”，消费者必须按 `event_id` 或 `dedupe_key` 幂等处理；禁止假设“恰好一次”。Redis Stream 超过保留期后仍可从 PostgreSQL 事件表重建投影。

### 6.2 统一事件信封

```json
{
  "schema_version": "1.0",
  "event_id": "evt_01J...",
  "event_type": "node.succeeded",
  "occurred_at": "2026-07-18T10:15:30Z",
  "trace_id": "trace_01J...",
  "run_id": "run_01J...",
  "node_id": "node_analysis",
  "sender": {
    "kind": "agent",
    "id": "agent-rnaseq",
    "attempt_count": 1
  },
  "recipient": {
    "kind": "orchestrator",
    "id": "mas-scheduler"
  },
  "status": "success",
  "intent": "run_rnaflow_standard_quantification",
  "context_pointers": {
    "counts_matrix": {
      "artifact_id": "art_01J...",
      "container_path": "/workspace/results/counts.csv"
    },
    "deg_results": {
      "artifact_id": "art_01J...",
      "container_path": "/workspace/results/deg_summary.csv"
    }
  },
  "summary": {
    "message": "RNAFlow 已完成；DEG 结果与 QC 摘要已登记。",
    "metrics": {
      "samples": 6,
      "median_mapping_rate": 0.89,
      "deg_count": 1240
    }
  },
  "dedupe_key": "run_01J...:node_analysis:attempt_1:node.succeeded:state_version_7",
  "causation_event_id": "evt_01J..."
}
```

事件负荷约束：

1. `context_pointers` 中只允许 `artifact_id`、容器内相对路径投影、格式与简短摘要；禁止内嵌大文本和 base64 数据。
2. `sender.id` 必须对应已注册 Agent 或系统组件；`recipient` 是路由意图，不代表直接 LLM 对话。
3. `summary.message` 限制为 1,000 字符；所有自由文本入库后仍需敏感信息脱敏。
4. 对每个 `event_type` 建立 Pydantic schema，接收端拒绝未知字段/不兼容版本。
5. 事件在 UI 上展示为可读卡片，但 UI 绝不能以文本解析来驱动调度。
6. 所有节点事件必须携带当前 `attempt_count`、`state_version` 和 `causation_event_id`；Scheduler 仅接受与数据库当前尝试号/版本一致的终态事件，迟到的旧尝试事件只审计、不改变状态。
7. `dedupe_key` 以 `run_id + node_id + attempt_count + event_type + state_version` 构造。消费者将已处理键持久化，而不是仅依赖 Redis 消费确认。

### 6.3 初始事件类型

| 事件类型 | 发送方 | 消费/作用 |
| --- | --- | --- |
| `run.created` | Orchestrator | 初始化监控投影。 |
| `plan.approved` | HITL 服务 | 解锁首批节点。 |
| `node.ready` / `node.dispatched` | Scheduler | 记录调度。 |
| `node.started` / `node.progressed` | Agent/Worker | 推送统一窗口与任务监控。 |
| `artifact.registered` / `artifact.validated` | Agent/Artifact 服务 | 更新状态字典。 |
| `node.succeeded` | Agent | 解锁依赖节点。 |
| `node.failed` / `node.retry_scheduled` | Agent/Worker | 触发重试或暂停。 |
| `node.input_required` | Agent | 创建用户输入/审批卡片。 |
| `node.rework_requested` | 下游 Agent，经 Scheduler | 受控的逆向修复请求。 |
| `run.completed` / `run.failed` | Result Aggregator | 生成最终会话响应。 |

### 6.4 下游格式问题的处理

可视化 Agent 发现 DEG 表缺少预期列时，不直接修改上游原文件，也不直接“喊话”。它提交 `node.rework_requested`：

```json
{
  "event_type": "node.rework_requested",
  "run_id": "run_01J...",
  "node_id": "node_visualize",
  "recipient": {"kind": "orchestrator", "id": "mas-scheduler"},
  "status": "needs_rework",
  "context_pointers": {
    "invalid_input": {"artifact_id": "art_deg_01J..."}
  },
  "summary": {
    "error_code": "DEG_SCHEMA_MISSING_REQUIRED_COLUMNS",
    "required_columns": ["log2FoldChange", "padj"],
    "observed_columns": ["gene_id", "p_value"]
  }
}
```

Scheduler 根据 Plan 的修复策略创建“格式标准化”补偿节点，或让原分析节点以新的 attempt 执行。修复前先计算 `rework_fingerprint = sha256(input_artifact_sha256 + error_code + remediation_kind + expected_schema_version)`；同一 Run、目标节点和指纹只允许一个活跃或已完成补偿节点。若同一错误输入再次触发请求，Scheduler 不再创建节点，直接返回既有诊断。`rework_requested` 与补偿节点均计入独立的 `max_rework_attempts`（默认 3 次）；达到上限或补偿产物的摘要/校验和未变化时，Run 必须进入 `PAUSED_FOR_INPUT`，禁止形成可视化→格式化→可视化的无限循环。

---

## 7. Orchestrator、领域 Agent 与 Prompt 改造

### 7.1 Orchestrator 的职责与限制

Orchestrator 只负责：意图拆解、计划草稿、Agent/工具能力匹配、依赖关系、输入输出契约、资源/审批建议和用户可读计划摘要。

Orchestrator 不负责：执行 shell、读取大文件、生成最终统计结论、跳过权限校验、直接写入数据库状态、绕过 MCP 启动容器。

其结构化输出应由服务端 Pydantic 模型限制，不建议将纯 JSON 自由文本直接交给 Scheduler。

```json
{
  "schema_version": "1.0",
  "summary": "下载 RNA-seq 数据，运行标准定量和 DEG，生成火山图。",
  "requires_confirmation": true,
  "nodes": [
    {
      "node_key": "download_raw_data",
      "agent_id": "agent-code",
      "intent": "download_sequencing_data",
      "depends_on": [],
      "input_contract": {
        "required_user_fields": ["s3_uri_or_manifest"]
      },
      "output_contract": {
        "artifacts": [
          {"logical_name": "fastq_manifest", "kind": "dataset_manifest", "format": "json"}
        ]
      },
      "tool_policy": {"allowed_tools": ["ebi_download.run"]},
      "resources": {"cpu": 4, "memory_gb": 8, "timeout_minutes": 180},
      "retry_policy": {"max_attempts": 3, "retryable_codes": ["NETWORK_TRANSIENT"]}
    },
    {
      "node_key": "rnaflow_quantification",
      "agent_id": "agent-rnaseq",
      "intent": "run_rnaflow_standard_quantification",
      "depends_on": ["download_raw_data"],
      "input_contract": {
        "artifacts": [{"from_node": "download_raw_data", "logical_name": "fastq_manifest"}],
        "required_user_fields": ["reference_genome", "sample_sheet", "contrasts"]
      },
      "output_contract": {
        "artifacts": [
          {"logical_name": "counts_matrix", "kind": "file", "format": "csv"},
          {"logical_name": "deg_results", "kind": "file", "format": "csv"},
          {"logical_name": "rnaflow_report", "kind": "report", "format": "html"}
        ],
        "quality_gate": {
          "policy": "block_downstream_on_review_required",
          "required_metrics": ["median_mapping_rate", "unique_mapping_rate", "sample_count"],
          "threshold_profile": "rna_seq_standard_v1",
          "on_hard_fail": "pause_for_user_confirmation"
        }
      },
      "tool_policy": {"allowed_tools": ["rnaflow.validate", "rnaflow.run"]},
      "resources": {"cpu": 24, "memory_gb": 96, "timeout_minutes": 1440}
    },
    {
      "node_key": "plot_deg_volcano",
      "agent_id": "agent-viz",
      "intent": "plot_deg_volcano",
      "depends_on": ["rnaflow_quantification"],
      "input_contract": {
        "artifacts": [{"from_node": "rnaflow_quantification", "logical_name": "deg_results"}]
      },
      "output_contract": {
        "artifacts": [
          {"logical_name": "volcano_plot_png", "kind": "file", "format": "png"},
          {"logical_name": "volcano_plot_pdf", "kind": "file", "format": "pdf"}
        ]
      },
      "tool_policy": {"allowed_tools": ["workspace.inspect", "plot.deg_volcano"]},
      "resources": {"cpu": 2, "memory_gb": 8, "timeout_minutes": 30}
    }
  ]
}
```

### 7.2 领域 Agent 的统一运行契约

`code_agent`、`rna_seq_agent` 和 `viz_agent` 均复用现有 `AgentService.assemble_context()` 和局部 tool-call loop，但追加以下系统约束：

1. 只接受 Scheduler 发出的已验证 Node；不得从用户自由文本自行创建跨 Agent 子任务。
2. 每次调用工具前先检查 `input_contract` 的 Artifact 状态、格式、可见性和路径存在性。
3. 通过 `workspace.inspect` 获取采样摘要，不得把完整文件内容拉进 Prompt。
4. 只能调用节点 `tool_policy.allowed_tools` 和自身 Agent 允许的 MCP/Studio 能力的交集。
5. 工具执行后必须调用 `artifact.register` 与 `artifact.validate`；RNA-seq Agent 还必须调用 `quality_gate.evaluate`，失败时按结构化错误码回报。
6. Agent 输出只包含：简短说明、已登记 Artifact 指针、指标摘要、质量门状态、下一步事件；不把原始日志回灌模型。
7. 对外部下载、覆盖已有数据、资源超过阈值、成本敏感操作，必须等待审批令牌。
8. `agent-rnaseq` 不得将“流程退出码为 0”解释为可视化许可；仅当质量门为 `PASS`，或存在用户签发的 `qc_override` 审批令牌时，才可发布解锁可视化节点的成功事件。

### 7.3 首批角色职责

| 角色 | 初始职责 | 禁止事项 |
| --- | --- | --- |
| `agent-orchestrator`（新增虚拟系统 Agent） | 计划和调度建议；不执行工具。 | 不运行脚本，不直接发布任务。 |
| `agent-code` | 数据清单解析、EBIDownload、完整性校验、格式转换。 | 不负责解释 RNA-seq 生物学结论。 |
| `agent-rnaseq` | RNAFlow 输入预检、配置生成、受控流程提交、QC/DEG 产物校验。 | 不直接操作 Docker/socket，不忽略失败 QC。 |
| `agent-viz` | 数据探查、DEG/WGCNA 等绘图、导出 PNG/PDF/HTML。 | 不更改上游原始矩阵；格式不符走补偿节点。 |

### 7.4 Prompt 与配置变更原则

1. 在 `data/ai/prompts/` 新增 `agents.orchestrator` 和 `mas.common_guardrails`，不要在现有 Prompt 中复制长篇公共规则。
2. 在 `data/ai/*.yaml` 为可参与 MAS 的 Agent 增加 `mas` 段，例如 `roles`、`intents`、`artifact_contracts`、`max_parallel_nodes`、`risk_tier`；保留现有 `studio` 段。
3. Agent 可调用工具由后端强制裁剪，Prompt 中的“允许工具”只用于引导，不作为授权来源。
4. 先在测试/管理员白名单用户启用该路由开关，避免所有普通聊天被误判为 MAS。

---

## 8. MCP 与容器执行网关

### 8.1 总体原则

现有 `MCPServerModel` 继续保存服务器基本注册信息。新增 `ToolExecutionPolicy`（可先放在 JSON 配置/工具 schema，稳定后再表结构化）补充执行安全策略：

| 策略项 | 示例 |
| --- | --- |
| `executor` | `celery_container`、`studio_sandbox`、`remote_api`。 |
| `image_allowlist` | `cygnusx-rnaflow:<immutable-tag>`、`cygnusx-analysis-plot:<immutable-tag>`。 |
| `command_template` | 服务端固定模板；模型不能提交任意 shell。 |
| `input_mounts` / `output_mounts` | 显式声明 `/workspace/input:ro`、`/workspace/results:rw`。 |
| `network_mode` | `none`、`restricted-egress`；仅下载工具允许受限外网。 |
| `resources` | CPU、内存、磁盘、超时、GPU、并行上限。 |
| `approval_policy` | 是否需要用户确认、项目权限或管理员授权。 |
| `idempotency` | 由 Run/Node/参数 hash 生成，避免重复执行。 |

### 8.2 首批 MCP 工具

#### A. `ebi_download.run`

- 输入：来源 URI/manifest、目标逻辑目录、并发数、校验策略。
- 后端：调用容器化 EBIDownload 或既有 Rust 工具；网络只允许目标对象存储/白名单域名。
- 输出：`fastq_manifest`、下载报告、校验和、失败文件列表 Artifact。
- 不允许：将存储凭证写入模型上下文、接受任意宿主路径、未确认的大批量下载。

#### B. `rnaflow.validate`

- 输入：`fastq_manifest` Artifact、样本表、对照表、参考基因组、模块开关。
- 后端：只做配置 schema、文件配对、样本一致性、磁盘/资源预检；不执行重型流程。
- 输出：`rnaflow_preflight` Artifact，包含可读摘要与机器可用错误码。

#### C. `rnaflow.run`

- 输入：已通过预检的配置 Artifact、运行资源、可选 resume 标记。
- 后端：在专用 RNAFlow 镜像中提交 Snakemake；将现有流程监控日志同步到 Run/Node 事件。
- 输出：解析 `delivery_manifest.json` 后登记 counts、DEG、QC、报告等 Artifact，不依赖模型猜测路径。
- 失败策略：根据 OOM、依赖、输入缺失、流程规则失败分类；仅对安全可重试的错误自动降并行或恢复执行。

#### D. `workspace.inspect` 与 `artifact.validate`

- 输入：Artifact ID、预期 schema、最大采样行数。
- 输出：文件存在性、格式、表头、行列数、缺失率、数值范围和限长预览。
- 这是所有下游 Agent 的必经前置工具。

#### E. `quality_gate.evaluate`

- 输入：`qc_summary`、`counts_matrix`、`deg_results` 等已验证 Artifact，以及版本化阈值配置（例如 `rna_seq_standard_v1`）。
- 后端：只读取结构化 QC 指标并输出 `PASS`、`WARNING`、`REVIEW_REQUIRED` 或 `FAIL`；阈值判断不得交给 LLM 自由解释。
- 强制策略：例如 `median_mapping_rate < 0.50`（生产阈值最终按物种/文库类型配置）必须为 `REVIEW_REQUIRED`；`0.30` 的中位比对率属于阻断级别，绝不自动解锁火山图节点。
- 输出：质量门决策、每项指标/阈值/证据 Artifact、推荐动作和可审计的 `quality_gate_version`。
- 覆盖：用户明确确认“仍要继续绘图”后，由审批服务签发一次性、仅作用于当前 Run/下游节点的 `qc_override`；事件中必须记录风险提示和确认人，图表/报告附带 QC 覆盖标记。

#### F. `plot.deg_volcano`

- 输入：经过校验的 DEG Artifact、阈值、颜色/标签策略、输出逻辑名。
- 后端：调用固定 R/Python 绘图入口，生成 300 dpi PNG 与 PDF，登记两个 Artifact。
- 输出：图路径指针、图像尺寸、被标注基因数量和绘图参数 JSON。

### 8.3 容器隔离要求

1. 使用不可变镜像 tag 或 digest；禁止在生产节点运行 `latest`。
2. 默认非 root 用户、只读根文件系统、`no-new-privileges`、capability drop、PID/内存/CPU 限制。
3. **禁止 Docker-in-Docker。** 不挂载 `/var/run/docker.sock`，不使用 `--privileged`，不允许任何 Agent/Studio/RNAFlow 容器调用宿主 Docker API。
4. **嵌套工作流统一走 Apptainer。** 在专用计算节点（裸机或受控 VM）部署 Apptainer；执行网关通过受限作业接口提交任务，Snakemake 规则使用 Apptainer/Singularity profile 和固定镜像来源。Apptainer 进程以非 root 身份运行，仅 bind 当前 Run 的 `/data/cygnusx/runs/<run_id>` 到 `/workspace`，不 bind 宿主根目录、Docker socket 或其他 Run。
5. 若 RNAFlow 本体由 Docker Worker 启动，Docker Worker 只负责控制/提交；实际需要嵌套镜像的规则必须路由到上述 Apptainer 计算节点，不在 Docker 容器内再启动 Docker 或伪装的特权 Apptainer。
6. `input` 只读、输出目录最小可写；不允许 host network、host PID、任意宿主路径挂载。
7. 下载工具独立网络策略；分析/绘图容器及 Apptainer 作业默认无网络，避免数据外泄和不可重现依赖下载。
8. 使用 Secret Manager 或 Worker 环境注入临时凭证；日志、事件、Prompt 和 Artifact 摘要必须脱敏。
9. 对文件扩展名、魔数、压缩包展开大小、路径穿越、符号链接目标实施校验；Run 内的缓存链接还须校验其真实路径属于批准的内容寻址缓存根。

---

## 9. 端到端场景：S3 RNA-seq → RNAFlow → Volcano Plot

### 9.1 用户请求与计划确认

用户：

> 帮我把 S3 上的那批转录组数据拉下来，走一遍标准定量流程，最后画处理组和对照组的差异表达火山图。

系统补充最小必要信息：S3 URI/manifest、物种/参考版本、样本分组表、对照关系、下载规模与预算确认。信息齐全后展示计划卡：

```text
1. 下载与校验原始 FASTQ（agent-code，预计网络与存储消耗）
2. RNAFlow 标准定量/差异分析（agent-rnaseq，预计 CPU/内存与耗时）
3. 生成 300 dpi 火山图（agent-viz）
```

用户点击“确认运行”后创建 `MASRun`。

### 9.2 节点一：下载与校验

1. Scheduler 将 `download_raw_data` 派发至 `agent-code`。
2. Agent 调用 `ebi_download.run`，目标为 `/workspace/staging/raw_data/`。
3. 工具生成并登记 `fastq_manifest`，每项包含受控相对路径、文件大小、校验和、样本候选名。
4. Agent 发布 `artifact.validated` 和 `node.succeeded`；不发送 FASTQ 内容。

### 9.3 节点二：RNAFlow

1. Scheduler 看到下载节点成功，解析其 `fastq_manifest` Artifact，解锁 `rnaflow_quantification`。
2. `agent-rnaseq` 先调用 `rnaflow.validate`，生成样本配对/参考版本/磁盘/配置预检摘要。
3. 若预检要求用户确认库类型或对照方向，Run 进入 `PAUSED_FOR_INPUT`；否则调用 `rnaflow.run`。
4. 容器中由 Snakemake 运行 RNAFlow；原始日志落 `/workspace/logs/`，只把进度、规则名、告警计数推到事件流。
5. 完成后由解析器读取 RNAFlow `delivery_manifest.json` 和约定目录，登记：`counts_matrix`、`deg_results`、`qc_summary`、`rnaflow_report`。
6. Agent 调用 `quality_gate.evaluate`：只有 DEG Artifact 通过列名/数值规则且质量门为 `PASS`，节点才能以可解锁下游的成功状态结束。
7. 当 `median_mapping_rate` 等阻断指标低于阈值（例如 30%）时，RNA-seq 节点写入所有可用 Artifact，但状态转为 `WAITING_APPROVAL`，Run 转为 `PAUSED_FOR_INPUT`；不得自动调度 `agent-viz`。
8. 用户明确接受风险后，审批服务写入 `qc_override` 审计记录并仅解锁当前 Run 的指定绘图节点；未确认则可修改参考基因组/样本表后从预检或分析节点恢复。

### 9.4 节点三：绘图与结果聚合

1. `agent-viz` 接收 `deg_results` 的 Artifact ID，先调用 `workspace.inspect`。
2. 若字段符合契约，调用 `plot.deg_volcano` 生成 `volcano_plot_png` 与 `volcano_plot_pdf`。
3. 若字段不符，发出 `node.rework_requested`；Scheduler 启动预定义的标准化补偿节点或暂停请求用户决定。
4. Result Aggregator 汇总各 Artifact 的短摘要和可访问链接，在原会话中回复：下载、流程、QC 状态、火山图、HTML 报告和可重跑 Run ID。

---

## 10. 容错、重试与人工介入

### 10.1 错误分类

| 错误类别 | 示例 | 默认动作 |
| --- | --- | --- |
| `NETWORK_TRANSIENT` | 下载超时、临时 5xx | 指数退避重试，最多 3 次。 |
| `RESOURCE_OOM` | RNAFlow/绘图内存不足 | 若策略允许，降低并发/提高已批准资源后重试；否则审批。 |
| `INPUT_MISSING` | FASTQ、样本表或对照表缺失 | 不重试，进入 `PAUSED_FOR_INPUT`。 |
| `INPUT_SCHEMA_INVALID` | DEG 表缺列、分隔符错误 | 调度补偿标准化节点；超过阈值后人工介入。 |
| `TOOL_POLICY_DENIED` | 非白名单镜像、越权路径 | 立即失败并记录安全事件，不自动重试。 |
| `PIPELINE_RULE_FAILED` | Snakemake 规则失败 | 根据可恢复错误码决定 resume 或人工介入。 |
| `QC_WARNING` | 非阻断指标偏离建议范围 | 节点可成功但 Run 标记 `SUCCEEDED_WITH_WARNINGS`，结果页醒目提示。 |
| `QC_REVIEW_REQUIRED` | `median_mapping_rate` 等阻断质量门未达标，例如 30% | 产物保留但节点进入 `WAITING_APPROVAL`、Run 进入 `PAUSED_FOR_INPUT`；未取得 `qc_override` 前禁止调度可视化/下游解释节点。 |
| `QC_FAIL` | 指标缺失、样本身份不一致、质量门无法可信评估 | 失败或要求补齐输入，不允许覆盖继续。 |

### 10.2 自动重试约束

1. `max_attempts` 默认最多 3 次，按 Node 类型独立配置。
2. 仅白名单错误码可自动重试；不得因为“模型觉得再试一次”就重跑昂贵流程。
3. 任何重试必须复用同一 `idempotency_key` 家族并显式递增 `attempt_count`，记录参数差异、原因、触发事件和输入 Artifact 校验和。
4. 对昂贵的下载/RNAFlow 节点，重试前必须检测部分输出能否 resume，防止重复下载和重复计算。
5. 多次失败后将简短错误诊断、日志 Artifact 指针、可选操作展示为 HITL 卡片。
6. 对 `node.rework_requested`，先查询 `mas_rework_guards` 的修复指纹；同一错误输入只能消耗一次修复预算。任何补偿节点必须继承并检查 `max_rework_attempts`，不得通过新建 node ID 绕过上限。

### 10.3 HITL 卡片

卡片必须由后端状态驱动，包含：

- 当前 Run/Node、失败类别、影响范围和已完成产物；
- 脱敏后的诊断摘要与完整日志下载/查看链接；
- 可选动作：`提供缺失文件`、`调整资源`、`修改对照表`、`取消`、`交由管理员`；
- 每个动作对应参数 schema 和审批审计记录；
- 用户操作后从原 Node 或补偿 Node 恢复，而不是重新创建整个 Run。

---

## 11. API、前端与可观测性

### 11.1 后端 API（建议）

| API | 作用 |
| --- | --- |
| `POST /api/v1/mas/plans:preview` | 从用户请求生成并验证 Plan Draft；不执行。 |
| `POST /api/v1/mas/runs` | 用户确认后创建 Run。 |
| `GET /api/v1/mas/runs/{run_id}` | 查询 Run、节点、摘要、审批和 Artifact。 |
| `POST /api/v1/mas/runs/{run_id}/approvals/{approval_id}` | 提交审批/补充信息。 |
| `POST /api/v1/mas/runs/{run_id}:cancel` | 请求取消。 |
| `POST /api/v1/mas/runs/{run_id}/nodes/{node_id}:retry` | 受权限与策略约束的人工重试。 |
| `GET /api/v1/mas/runs/{run_id}/events` | SSE 订阅 Run 事件；前端不直接消费 Redis。 |
| `GET /api/v1/mas/artifacts/{artifact_id}` | 基于鉴权返回元数据、预览或受控下载。 |

现有聊天接口保留：聊天响应中返回 `mas_plan_preview` 或 `mas_run_id` 事件，让统一窗口继续承载交互。

### 11.2 前端改造范围

1. 在现有 AI Chat/Studio 中新增“计划预览卡”：显示 DAG、依赖、预计资源、外部下载、风险与确认按钮。
2. 在 `TaskProgressCard` 或对应工作流视图中新增 MAS 节点状态、当前 Agent、重试次数和 Artifact 快捷入口。
3. 复用现有 Workflow Monitor 的事件展示，不单独建设第二套监控页面；以 `run_id` 聚合。
4. 增加 HITL 审批卡，支持表单型输入和恢复运行。
5. 在 Studio 文件树中按 Run 显示 `input/results/plots/logs`，但日志仅按权限和大小限制预览。
6. 增加 Artifact 预览：图片、CSV 摘要、HTML 报告安全 iframe/下载、JSON manifest；大文件只展示元数据。

### 11.3 指标、日志与追踪

每个 Run/Node/Artifact/Event 使用 `trace_id` 关联。至少采集：

- Run 成功率、平均耗时、等待审批时间、取消率；
- 各 Agent 的节点成功率、重试率、工具调用失败率；
- 队列等待、容器启动、RNAFlow 执行、产物验证耗时；
- 上下文打包字节数、工具输出截断次数、Artifact 大小分布；
- OOM、路径拒绝、策略拒绝、敏感信息脱敏命中等安全指标；
- 按用户/项目/工具的资源用量与可选成本归集。

所有日志均携带 `run_id`、`node_id`、`attempt`、`trace_id`，避免仅靠自然语言日志排障。

---

## 12. 分阶段实施计划

### Phase 0：契约与基础验证（先行设计，1 个迭代）

**目标：** 固化边界和 schema，不改变用户默认路径。

1. 建立 `src/cygnusx/domain/mas/`：Plan、Node、Artifact、Event、Approval 的 Pydantic/domain 模型与状态转移规则。
2. 定义 JSON Schema/Pydantic 校验：Plan、A2A 信封、各事件类型、Artifact 元数据、错误码。
3. 确定 `/data/cygnusx/runs/<run_id>` 工作区布局、容器 `/workspace` 映射、内容寻址缓存与路径安全工具。
4. 在工具 schema 中定义首批 MCP 执行策略，完成只读 preflight，不执行下载/流程；明确 Docker socket 禁用和 Apptainer 专用计算节点契约。
5. 编写架构决策记录（ADR）：Redis Stream、Transactional Outbox、Artifact 版本化/缓存生命周期、Apptainer 嵌套执行、QC 质量门与覆盖审计。

**验收：** 单元测试可拒绝循环 DAG、越界路径、超大事件、未授权工具和不合法 Artifact；可通过模拟事件驱动 Node 状态机，并验证 Docker socket/特权容器策略被拒绝、共享缓存链接不可写、重复修复请求不新增节点。

### Phase 1：持久化 Run 与 Artifact Registry（1–2 个迭代）

**目标：** 能创建、查询、取消单个 MAS Run，且产物可审计。

1. 新增数据库表和 Alembic 迁移；实现 Repository/Application Service。
2. 实现 `WorkspaceManager`：创建 Run 目录、路径映射、文件安全检查、生命周期标记、内容寻址缓存查询/租约/受控只读链接。
3. 实现 Artifact 注册、验证、摘要生成和权限校验；接入现有报告/数据管理链接但不复制大文件。
4. 增加 Run/Node/Artifact API 与基础 SSE 事件查询。
5. 将 MAS Run 映射到既有任务中心/工作流监控的只读投影。

**验收：** 通过 API 创建测试 Run、登记 CSV/PNG、查询元数据、拒绝跨用户访问，并可在任务中心看到聚合状态；同一校验和 FASTQ 被多个 Run 引用时只保留一份物理数据，活跃租约阻止 GC。

### Phase 2：A2A Outbox 与 DAG Scheduler（1–2 个迭代）

**目标：** 不依赖 LLM 即可用模拟 Agent 可靠跑通 DAG。

1. 实现 PostgreSQL Outbox、Redis Stream Publisher 和幂等 Consumer。
2. 实现 Scheduler：拓扑依赖解锁、乐观锁抢占、Celery 路由、重试计时和取消传播。
3. 实现错误分类、按修复指纹去重且有预算上限的补偿节点机制、HITL Approval 创建/恢复。
4. 使用 fake Agent Worker 依次产出 `fastq_manifest → deg_results → volcano_plot`，验证事件重放与 Worker 重启恢复。
5. 补齐 Run/Node 可观测性投影、SSE 与前端进度卡最小版本。

**验收：** 事件重复投递不重复执行；旧 attempt 的迟到事件不覆盖新 attempt；Redis 重启后可从 Outbox 恢复；同一错误 Artifact 不产生无限补偿；上游失败不解锁下游；审批后从断点恢复。

### Phase 3：Orchestrator 计划预览与 Agent 运行契约（1 个迭代）

**目标：** 将用户的复合请求安全转换为经确认的 DAG。

1. 新增 `agent-orchestrator` Prompt/配置及结构化 Plan 输出适配器。
2. 服务端加入 Agent 能力注册、计划校验、风险评估和用户确认门。
3. 在当前 Chat/Studio 页面加入 Plan Preview 与批准/取消交互。
4. 为 `code`、`rnaseq`、`viz` Prompt 注入 MAS 公共规则，并在后端缩减到节点许可的工具集合。
5. 为缺少 `sample_sheet`、`contrasts`、参考基因组等情况设计表单化追问，而不是将不完整信息交给执行器猜测。

**验收：** 给定标准用户请求可生成无环、能力匹配、可解释的计划；未经确认不创建 Celery 执行任务。

### Phase 4：首批受控 MCP 工具落地（2–3 个迭代）

**目标：** 真实跑通下载、RNAFlow 与绘图闭环。

1. MCP 化/适配 `ebi_download.run`，输出 manifest 与完整性报告。
2. MCP 化/适配 `rnaflow.validate`、`rnaflow.run`，解析 RNAFlow `delivery_manifest.json` 注册标准 Artifact，并通过专用 Apptainer 计算节点承载 Snakemake 的嵌套镜像规则。
3. 实现 `workspace.inspect`、`artifact.validate`、`quality_gate.evaluate` 和固定入口 `plot.deg_volcano`。
4. 为每个工具定义容器镜像、Apptainer 镜像来源、挂载、资源、网络和审批策略；接入 Celery Worker 队列。
5. 将 Snakemake/RNAFlow 的关键进度与 QC 摘要投影到 MAS 事件和现有 Workflow Monitor。

**验收：** 使用小型公开/测试 FASTQ 数据，在隔离环境完成“下载 → RNAFlow 标准模式 → DEG → PNG/PDF 火山图 → HTML 报告”；大文件不进入聊天上下文，Docker socket 不进入任何执行容器，低于质量门的运行无法自动生成火山图。

### Phase 5：生产强化与扩展（持续）

1. 完成配额/成本、并发公平调度、项目级访问控制和数据保留策略。
2. 支持 ATACFlow、scRNA-seq、WGCNA 等新的 Agent/工具，只需声明能力和 Artifact 契约。
3. 根据 Redis Stream 的积压、吞吐和跨机房需求评估 NATS JetStream/Kafka；迁移时保持 A2A schema 不变。
4. 增加计划/结果回放、Run 克隆、缓存命中和可复现环境指纹。
5. 建立质量基准集和红队用例，持续评估幻觉、越权工具调用和流程误调度。
6. 完成 Apptainer 镜像签名/来源校验、专用计算节点容量与调度隔离，确保嵌套工作流不会回退到 Docker socket 方案。

---

## 12.1 后续开发待办（2026-07-18）

> 以下项目尚未完成，建议按编号顺序继续开发。第 1、2 项需要真实 Worker 环境，不应在开发机通过伪造成功结果替代验收。

### 1. 真实执行环境 E2E 验收（最高优先级）

**前置条件：** Worker 节点已配置 Apptainer、RNAFlow SIF、EBIDownload 凭据/配置，以及可公开使用的小型 FASTQ 测试数据。

1. 提交并确认一个 MAS 计划，完整执行“下载 → RNAFlow → QC → 火山图 → Artifact 下载”链路。
2. 核验 Apptainer 挂载白名单、默认网络隔离、交付清单、Artifact 校验和和用户隔离。
3. 保存执行日志、Run ID、输入数据版本、镜像摘要和产物清单，作为可复现验收记录。

**验收：** 用户可从计划卡确认执行，在任务中心看到状态与节点进度，最终下载 FASTQ/分析结果、QC 摘要、PNG/PDF 火山图等登记产物；低于 QC 阈值时自动阻断火山图，显式覆盖须留下审计记录。

### 2. 真实 Worker 故障恢复演练（最高优先级）

1. 在节点运行期间终止 Celery Worker 或对应执行进程，再恢复 Worker 服务。
2. 验证 PostgreSQL Outbox、Redis Stream 消费位置、去重键、`attempt_count` 与乐观锁能够恢复调度。
3. 检查同一节点不会重复产生不可幂等副作用，未完成节点可继续执行，终态和 Artifact 元数据不丢失。

**验收：** 不以清空 Redis 队列作为恢复手段；恢复后无重复下载/重复分析、无丢失事件，Run 保持可审计状态转换记录。

### 3. 任务中心与工作流监控完善

1. 将 MAS Run 和节点状态接入 Workflow Monitor 大屏，展示队列、依赖、节点状态与失败原因。
2. 在任务中心增加跳转 MAS Run 详情、取消 MAS Run、查看/下载 Artifact 的明确入口。
3. 保持 MAS 表为唯一真相源；任务中心仅消费只读投影，不复用或污染旧 `TaskModel` 生命周期。

**验收：** 用户可从任务列表进入 MAS 详情、查看节点 DAG 与 Artifact，并只能操作自身 Run；取消与下载操作通过 MAS API 完成并保留审计记录。

### 4. 补偿与局部重跑策略

1. 定义可安全执行的补偿节点及其触发条件，限制同一错误指纹的补偿预算。
2. 支持人工确认后的局部重跑，复用未失效的上游 Artifact，避免整条流程重复执行。
3. 实现输入 Artifact 更新、失效或校验和变化后的下游失效传播和重新审批。

**验收：** 相同失败不会无限生成补偿节点；局部重跑不会错误复用失效输入；每次重跑、补偿和人工确认均可追溯。

### 5. Chat / Studio 计划体验打磨

1. 为普通 Chat 提供缺失输入的结构化追问，例如 accession、样本表、比较组、物种和关键参数。
2. 在计划卡展示依赖图、预估资源、风险/审批提示和缺失输入，明确区分“计划预览”和“已开始执行”。
3. 对不受支持的流程给出能力边界与下一步建议，避免模型伪造可执行节点、文件路径或样本信息。

**验收：** 用户补齐必要信息后才可生成可确认计划；计划卡的信息足以让用户理解执行范围、依赖、资源风险和待确认项。

### 6. 生产运维能力

1. 增加队列积压、节点失败率、节点执行时长、Apptainer 预检失败、Artifact 存储用量与清理状态等指标。
2. 为关键阈值配置告警和 Run/节点维度的排障链接，避免只依赖应用日志定位问题。
3. 补齐数据保留、归档/GC、容量阈值、异常清理和审计报表的运行手册。

**验收：** 运维人员可从指标定位积压、失败或存储风险；告警可关联到具体 Run/节点；清理策略不删除仍被引用或仍在租约期内的 Artifact。

---

## 13. 建议的文件改动清单（实施时）

> 下列是预计触达范围，评审通过前不修改。

### 新增

```text
src/cygnusx/domain/mas/
src/cygnusx/application/services/mas_orchestrator_service.py
src/cygnusx/application/services/mas_scheduler_service.py
src/cygnusx/application/services/artifact_service.py
src/cygnusx/application/services/workspace_service.py
src/cygnusx/application/services/a2a_event_service.py
src/cygnusx/application/schemas/mas.py
src/cygnusx/api/v1/mas.py
src/cygnusx/infrastructure/database/models/mas.py
src/cygnusx/infrastructure/database/repositories/mas_repository.py
src/cygnusx/infrastructure/celery_app/tasks/mas.py
src/cygnusx/infrastructure/mas/redis_streams.py
src/cygnusx/infrastructure/mas/outbox_publisher.py
src/cygnusx/infrastructure/execution/container_gateway.py
data/ai/orchestrator.yaml
data/ai/prompts/orchestrator.md
data/ai/prompts/mas/common_guardrails.md
alembic/versions/<revision>_add_mas_runs_artifacts_events.py
tests/unit/domain/mas/
tests/integration/test_mas_*.py
tests/e2e/test_mas_rnaflow_volcano.py
```

### 修改

```text
src/cygnusx/application/services/agent_service.py
src/cygnusx/application/services/chat_service.py
src/cygnusx/application/services/workflow_monitor_service.py
src/cygnusx/infrastructure/celery_app/celery.py
src/cygnusx/api/v1/router.py
src/cygnusx/core/config.py
src/cygnusx/tools/schema_loader.py
data/ai/code.yaml
data/ai/rnaseq.yaml
data/ai/viz.yaml
data/ai/prompts/registry.yaml
tool_configs/tools_schema.yaml
tool_configs/tools_setting.yaml
deploy/docker/Dockerfile.worker
deploy/docker/docker-compose.worker.yml
frontend/src/api/agent.ts
frontend/src/api/workflowMonitor.ts
frontend/src/components/ai-chat/TaskProgressCard.vue
frontend/src/components/agent-workspace/AgentSandbox.vue
frontend/src/stores/agentHub.ts
frontend/src/stores/workflowMonitor.ts
```

实施时需根据当前未提交改动逐项 rebase/合并，禁止覆盖用户已修改的 Studio、Chat、Docker 和 YAML 配置文件。

---

## 14. 测试与验收矩阵

### 14.1 单元测试

1. Plan：循环依赖、未知 Agent、未知工具、输入输出契约不匹配、超资源计划必须被拒绝。
2. Workspace：绝对路径/符号链接/`..` 绕过、跨 Run、跨用户访问必须被拒绝；缓存链接解析后必须仍位于批准的缓存根且只读。
3. Artifact：同名版本、校验和、格式探查、超大摘要截断、可见性授权、缓存租约/引用计数/GC 与负缓存 TTL。
4. 状态机：非法转换、并发抢占、取消传播、重试次数和乐观锁。
5. 事件：schema 兼容、去重、Outbox 重放、消费者幂等、超限负荷拒绝、旧 `attempt_count` 事件抑制、修复指纹限环。
6. 策略：Agent 能力与 Node 工具许可的交集、审批门、容器资源/网络策略、Docker socket/特权模式拒绝与 Apptainer bind 白名单。
7. QC：版本化阈值、`PASS/WARNING/REVIEW_REQUIRED/FAIL` 状态映射、30% mapping rate 阻断、`qc_override` 的最小范围与审计。

### 14.2 集成测试

1. PostgreSQL + Redis 下创建 Run、批准计划、事件驱动三节点 DAG 成功完成。
2. Worker 中途退出/Redis 临时不可用后，Outbox 能恢复并且下游只执行一次。
3. RNAFlow preflight 缺少 `contrasts.csv` 时产生 HITL 卡片并可补充后恢复。
4. 模拟 OOM 后执行降并行策略；超过限制后停止并保留诊断 Artifact。
5. Artifact 链接在未授权用户、跨项目用户、过期 Run 上均被拒绝；并发命中同一 FASTQ 时只触发一次实际下载。
6. `median_mapping_rate = 0.30` 时 RNAFlow 产物可查看但 `agent-viz` 不被派发；仅提交审计化 `qc_override` 后才可继续。
7. 同一 DEG Artifact 连续触发相同 `node.rework_requested` 时，仅创建一个补偿节点，达到预算后进入人工介入。

### 14.3 端到端验收

使用可公开、体量受控的 RNA-seq 测试数据：

1. 用户在一个会话中提交复合请求并看到 DAG 预览；未确认前没有实际下载/计算。
2. 确认后看到下载、RNAFlow、绘图节点依次推进，且均带 Agent、开始/结束、重试和 Artifact 链接。
3. 大型 FASTQ、完整 counts 和 Snakemake 全日志不出现在聊天上下文或 SSE 文本中。
4. 最终可下载/查看火山图 PNG、PDF 和 RNAFlow HTML 报告；所有文件可追溯到 Run/Node/镜像/参数。存在 QC 覆盖时，图表与报告必须明确显示覆盖标记。
5. 人为破坏 DEG 表头后，系统只发起有限补偿/重试，之后在同一会话显示明确的人工介入卡片。
6. RNAFlow 的嵌套规则通过 Apptainer 专用节点运行，任何执行容器中均不存在 `/var/run/docker.sock`、host PID、特权模式或跨 Run 挂载。

---

## 15. 上线、迁移与回滚

### 15.1 灰度顺序

1. 本地/CI：Fake Tool 与模拟 Artifact，先验证状态机和事件。
2. 测试环境：仅管理员/白名单用户、只允许测试数据和小配额。
3. 生产 Shadow Mode：Orchestrator 只生成计划并与人工计划对比，不执行。
4. 生产 Beta：开启 `code → rna_seq → viz` 固定模板，用户确认后执行；限制并发和数据规模。
5. 正式推广：按项目/角色逐步放开，并通过指标评估自动重试、成本和失败率。

### 15.2 Feature Flags

建议新增：

```text
MAS_ENABLED=false
MAS_PLAN_PREVIEW_ENABLED=false
MAS_REDIS_STREAMS_ENABLED=false
MAS_RNAFLOW_ENABLED=false
MAS_AUTO_RETRY_ENABLED=false
MAS_HITL_REQUIRED_FOR_EXTERNAL_DOWNLOAD=true
```

任何异常均可关闭 `MAS_ENABLED`；现有单 Agent Chat/Studio 流程保持可用。

### 15.3 回滚策略

1. 关闭入口 Feature Flag，停止创建新 Run；不删除现有数据。
2. Scheduler 停止派发，运行中的容器按策略完成或安全取消。
3. 所有 Run/Artifact/Event 数据保留，用户可下载已完成产物。
4. Redis Stream 有问题时，使用 PostgreSQL Outbox 重建投影；不以清空队列作为修复手段。
5. 数据库迁移遵循 expand/contract：先只新增表/索引，稳定后再考虑整合；首版不破坏现有表字段。

---

## 16. 评审决策点（实施前需确认）

1. **工作区根路径：** 是否确认服务端统一采用 `/data/cygnusx/runs/<run_id>`，容器统一投影为 `/workspace`？
2. **运行确认：** 是否确认外部下载、长时间 RNAFlow 和超过资源阈值的任务必须由用户点击计划卡后执行？
3. **消息底座：** 是否同意第一阶段使用现有 Redis + PostgreSQL Outbox，而不新增 NATS/Kafka？
4. **持久化边界：** 是否同意新增独立 `mas_*` 表，而不是复用/过载现有任务表的 JSON 参数字段？
5. **首批范围：** 是否只先覆盖 `agent-code`、`agent-rnaseq`、`agent-viz` 与 EBIDownload/RNAFlow/火山图？
6. **嵌套执行策略：** 是否确认禁止 Docker-in-Docker 与 `/var/run/docker.sock` 挂载，并为 RNAFlow 嵌套规则提供专用 Apptainer 计算节点？
7. **网络策略：** 是否确认所有分析/绘图容器及 Apptainer 作业默认无网络，只有下载工具使用白名单出口？
8. **质量门：** 是否确认阻断级 QC（例如中位比对率 30%）必须暂停并要求显式 `qc_override`，而不是自动流转到可视化？阈值配置的负责人是谁？
9. **缓存范围：** 哪些公共数据来源/授权范围允许进入内容寻址共享缓存？共享缓存的容量上限、保留期与归档策略是什么？
10. **重试策略：** 是否接受默认最多 3 次自动重试，且同一错误 Artifact 的格式化补偿也有独立 3 次预算；昂贵流程的资源升级/重新下载需额外审批？
11. **产物保留：** Run 的原始数据、中间文件、结果和日志分别保留多久；是否需接入对象存储归档？

---

## 17. 评审结论后的下一步

若上述决策点确认，建议按以下顺序开始实际开发：

1. 先提交 Phase 0–2：领域模型、迁移、工作区/Artifact Registry、Outbox、模拟 DAG 测试。
2. 审核事件与前端 Run 卡片后，再接入 Orchestrator Plan Preview。
3. 最后接入真实 EBIDownload、RNAFlow 和绘图 MCP，使用受控测试数据完成 E2E 验收。

这样可先验证最难的可靠性、可追溯性和安全边界，再让模型参与复杂任务拆解，避免“先接 LLM、后补治理”带来的不可控风险。
