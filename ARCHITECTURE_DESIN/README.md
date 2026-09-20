# 架构与设计文档索引

本目录集中存放 CygnusX 的项目级架构、设计规范和实施方案。修改相关功能前，请先阅读对应文档，确保实现与既有约束保持一致。

> **2026-09-18 文档整合说明**：本目录对内容重复的文档做了一次合并，共移除 10 个文件（合并去向见文末"合并记录"，历史内容可查 git）。各目标文档头部均有"合并说明"标注吸收来源。
>
> **2026-09-18 命名规范说明**：目录内文件统一按以下规则命名（更名对照见文末"命名规范记录"）：
> 1. 全小写 snake_case，不使用大写、连字符（`multi-agent` 类）与中文文件名；
> 2. 以领域前缀分组：`agent_` / `agentteams_` / `cygnusx_` / `mcp_` / `memory_` / `knowledge_` / `skill_` / `log_` / `database_` / `chat_` / `worker_` / `domain_` / `frontend`；
> 3. **活文档**（现行 as-built 基线、长期规范）不带日期，基线日期写在文档头部；
> 4. **快照 / 评审 / 提案 / 交接**等时点性文档以 `_YYYY-MM`（必要时 `_YYYY-MM-DD`）结尾，只增不改；
> 5. **不再演进方向**的文档移入 `deprecated/` 子目录原样保留，登记到文末"废弃归档"；
> 6. 新增文档请沿用本规则，并同步登记到本 README。
>
> **2026-09-20 新增说明**：新增 `agent_architecture.md`（单 Agent 技术架构备忘录，as-built）。与 `agent_execution_framework.md` 的分工：本文回答"Agent 这个对象由什么构成、接口长什么样、状态存在哪、依赖什么"，后者回答"一次执行怎么流转、怎么观测、怎么保护"。两者互补，不合并。


**文档类型口径**：
- **as-built**：记录仓库当前已落地架构，可信度最高；
- **规范**：约束"应该怎么改"，修改前必读；
- **提案/规划**：目标态设计，未（完全）实施，不得当作现状证据；
- **历史快照**：带"时点说明"的施工/评审/交接记录，部分引用已失效。

---

## 1. 平台总览与总体规范

### `cygnusx_architecture.md` — 平台架构总览（as-built 导航，2026-08-22）
全系统"一页地图"：Vue3 前端 → FastAPI → Application/Orchestration → AI/MCP、Celery/Worker、持久化 → Docker 沙箱/MinIO/Nginx 的总体分层；四条执行链路（Chat/Agent、Studio、AgentTeams、Pipeline/Worker）各自的请求路径；第 5 章 Agent 五形态（Legacy ReAct / LangGraph / Studio / Worker ReAct / AgentTeams）与 loop guard、`llm_payload`/`ui_payload` 双通道；第 6–10 章摘要 AgentTeams 四层拓扑、Studio 沙箱安全基线与 capability、MCP 三层体系、记忆/知识分层、Worker 边界与任务状态机；第 11–14 章前端、日志审计、部署发布、安全隔离模型；第 15 章区分"已具备主干能力"与"待验收项"；第 16–17 章为全目录文档索引。本文是导航与摘要，详细契约以各领域文档为准。

### `cygnusx_design.md` — 模块设计与接入规范（规范，2026-07-29）
"先设计后编码"的项目级基线：六条设计原则（分层清晰、契约优先、渐进接入、配置外置、默认安全、可验证）；目录级架构基线（`api/v1`/`application`/`domain`/`infrastructure`/`tools` 五层）与模块类型选择表；生信工具强制基线（`tools_setting.yaml` 注册、group 五分类透传、图形工具数据闭环、分组配色色板、PNG/SVG 导出 DPI）；新模块设计文档模板；后端（DTO/服务/领域/迁移/权限）与前端（Naive UI、`@/api/client`、Pinia 边界、主题响应式）规范；配置可运营性；实施流程、提交拆分、DoD 清单；附录 A"任务中心体验增强"设计实例。与 architecture.md 职责互补（规范 vs 描述），不合并。

### `cygnusx_platform_vision_2026-08.md` — L4 协作室目标态愿景（提案，2026-08-19）
描述设计目标而非现状：L1 工具箱 / L2 助手 / L3 工作台 / L4 协作室四层架构，协作室定义为"生物信息部门"；Manager 五项职责（接单/派单/验收/交付/例外处理）；专家层四段能力契约（capabilities / not_suitable_for / handoff_when / preferred_inputs）与 agent-data/qc/delivery 内部职能；甲方完整回路、共享地基（统一存储、分层记忆、单一能力目录、统一审计总线）；L4 判定"能且是正解"的四个必要条件及状态，附 token 成本风险提示。

---

## 2. Agent 执行架构

### `agent_architecture.md` — 单 Agent 技术架构备忘录（as-built，2026-09-20）
回答"一个 Agent 在 CygnusX 里到底怎么定义、怎么调用、怎么维持状态、怎么调工具、怎么跑起来、依赖什么、怎么和别的 Agent 协作"的实现细节层快照。Agent 是**数据驱动**（20 个 `data/ai/*.yaml` → `agent_templates` 表）而非基类继承；入口为 `POST /api/v1/chat/stream` SSE，出入参是 OpenAI 消息 dict 列表 → `AsyncIterator[ChatChunk>`；辨析两个同名 `AgentContext` 的职责边界；对话历史由**前端显式传入**、后端 per-request 无会话状态机，三层上下文裁剪；`AgentState` TypedDict 刻意不引入 LangChain 消息封装（reducer 用 `operator.add`）；checkpoint 仅编排图启用、单 Agent ReAct 图不用；工具调用的 OpenAI Function Calling 规范、tool_packs 请求级裁剪、MCP 三传输与 circuit breaker、双通道 `llm_payload`/`ui_payload`；轻量 Docker 沙箱（warm pool + Docker SDK exec）与 Studio 沙箱（一会话一容器 + Unix Socket）两种执行环境、MAS 执行准入策略、supervised 审批闸五步链路；全异步全流式与并发治理参数；依赖生态实测版本（langgraph 1.2.10 / langchain-core 仅间接依赖 / mcp 2.0.0 / 自研 httpx Provider，**无 Anthropic SDK、LlamaIndex、mem0**）；四种多 Agent 协同模式（Supervisor / Handoff / Map-Reduce / Group Chat）的落地位置。附关键实现位置索引（26 项）与 9 条改造约束。另记录一处配置漂移：`.env.example` 仍有 `MEM0_ENGINE_ENABLED=true` 但代码已无 mem0 引擎（实际为自研 Postgres FactStore + fastembed）。

### `agent_execution_framework.md` — 当前执行框架（as-built 主文档，2026-08-18；已吸收 observability 文档）
Agent 执行面的唯一现状快照：多入口、共享工具契约、分路径执行；`execution_path` 六路径登记表（chat_legacy / chat_langgraph / studio_chat_loop / agentteams_manager_consultation / agentteams_worker_react / agentteams_tool_execution，含 degraded 降级语义）；Legacy ReAct、LangGraph 节点（`llm_call_node`/`tool_exec_node`/双 route）、Worker 受限 ReAct（独立 child_session、五条禁止）三类闭环；AgentTeams 协助室意图四态判定与 Case 执行链；统一事件框架（七字段、生命周期事件 + 已并入的 `agent_tool_call`/`agent_tool_started`/`agent_tool_result` 三级工具事件链、`tool_call_id` 贯穿、Worker→房间证据投影表、前端事件→文案映射与"默认展开底层事件"）；运行保护（轮次治理、`StudioLoopGuard`、`duplicate_tool_call` 与无进展 Guard 语义）；消息/Case/Workspace 状态边界；修改扩展规则与验证清单。

### `agent_framework_baseline.md` — AI 助手基线与工具契约（as-built + 操作指南，2026-07-26/29；已吸收 extension_guide）
配置驱动 Tool Agent 的规范基线：`data/ai/` 配置 → `ensure_builtin_agents()` → 数据库运行时链，改 md 提示词必须经营理端 API 发布；七个内置 Agent 清单与请求执行链路；工具与提示词契约——工作区五工具白名单一致性约束、Skill 三层渐进披露、时效检索降级契约、记忆与 Handoff 契约（`allowed_targets`、`max_hops_per_session`）、ask_user 全执行器统一中断语义与数据缺失澄清、会话隔离（`.s{session_id}` 标记）；Router/双执行器/Studio 边界；MAS 启用五前置条件；修改扩展流程与"不要采用的方式"反模式清单（prompt 假装执行、shell 拼接、任意 subprocess、高权限工具全发）；发布验收清单与验证证据；P1–P4 能力状态历史与优化方案实施边界（附录）。

### `agent_architecture_review_2026-07.md` — 架构评审细读 + RAP 提案（历史快照/提案，2026-07-28）
前半为带 `path:line` 引用的评审细读：三层形态（Chat 专家、Studio 十工具与双通道、MAS 六步链路）、web_search 双触发与 knowledge_search 子串匹配现状、Prompt Registry 热重载、mermaid 时序图、四层治理机制（轮次治理与 `round_limit` 续轮、历史附件继承、256K 上下文压缩与 `context_compressed` 事件、会话文件治理）。后半为**未实施**的 RAP（检索增强计划生成）三层提案：提示词策略层、代码强制预检索注入、向量检索质量层，含实施顺序与验收清单。as-built 部分多数机制已被 `agent_architecture.md` / `agent_execution_framework.md` / `agent_framework_baseline.md` 三份承接，行号引用易腐化。

### `chat_execution_layers_2026-08.md` — Chat Runtime 分层与事件契约（施工快照，2026-08-23）
Chat Runtime 重构的实施记录：HTTP → ChatService/AgentRuntimeGateway → ChatRouterService → ChatRuntime → 编排层 → ChatEventService SSE 出口的分层边界；`request_preparation.prepare_agent_request()`、`AgentContextBuilder`、`DelegatingAgentRuntime`、`DirectChatRuntime`；事件契约与 `ChatEventService` 唯一状态机校验点、`StudioLoopGuard` 熔断降级 supervised；`chat_runtime_refactor_enabled` 灰度回退、`agent.runtime.legacy_entry` 退役依据、golden record + `DualRunComparator` 双跑门禁；当前边界（ChatService 未瘦身至 <1000 行）与 99 项回归验证。

---

## 3. 多智能体编排与记忆

### `mas_a2a_plan_2026-07.md` — MAS/A2A 实施方案（提案评审稿，2026-07-18，Phase 0–4 核心链路已落地）
把"单 Agent + MCP 工具闭环"升级为可审计多智能体系统的蓝图：MAS 控制面（Intent Router → Orchestrator → DAG Scheduler → HITL Gate + State/Artifact Registry + A2A Outbox）；数据模型 `MASRun/MASPlan/MASNode/MASArtifact/A2AEvent/MASApproval/MASRetry` 与 `mas_*` 迁移表、Run/Node 状态机（乐观锁）；A2A 事件协议（Redis Stream + Transactional Outbox、`dedupe_key` 幂等、`node.rework_requested` 修复指纹限环）；共享工作区 `/data/cygnusx/runs/<run_id>` 与内容寻址缓存、Context Packager；首批 MCP 工具与容器隔离约束；端到端场景、错误重试/HITL、Phase 0–5 实施、测试矩阵与灰度回滚。与根目录通用 `plan-ai.md` 不是同一文件。

### `multi_agent_fanout_2026-07.md` — 多 Agent 现状调查 + Sub-Agent Fan-out 设计（调查+设计，2026-07-29，Phase 1+2 已落地）
§1 三层协作机制现状（MAS DAG 固定管道执行、多专家会诊 `asyncio.gather` ≤3 LLM 无工具、Handoff 串行接力；父循环对 tool_calls 串行 await）；§2 A2A 定性：自研内部事件协议而非业界标准 A2A；§4 Sub-Agent Fan-out 设计：`parallel_subagents` 工具请求内并行迷你 ReAct 子循环、`ParallelSubAgentService`/`SubAgentRunner`、七条正确性约束（独占 AsyncSession、剥离递归工具、隔离子目录）、六个灰度开关、`subagents` SSE chunk；§8 as-built 实施偏差记录。与 mas_a2a_plan_2026-07.md 互补共存（分钟级编排 vs 秒级请求内并行）。

### `domain_prompt_sedimentation_2026-08.md` — 领域知识渐进沉淀设计（提案草案 v1，2026-08-06，未实施）
注意：主题是"提示词/领域资产沉淀"而非 agent 并行。四环闭环：感知层 `DomainMissEvent`（`domain_miss_events` 表、脱敏）→ 候选聚合（指纹聚类、`domain_candidates`、浮现阈值）→ 沉淀层（轻=知识库条目/中=skill/重=Domain Pack，LLM 起草+人审+回放测试）→ 生效层（`data/ai/domains/<domain>.yaml` 热重载、灰度、回滚）。依赖 Domain Pack 设计，V0–V3 分阶段，附四条反模式红线。

### `memory_architecture.md` — AI 记忆系统（as-built，2026-08-22）
自研 PostgreSQL + pgvector 薄层记忆（不依赖 mem0），v2 灰度：三层数据模型——归档 `agent_memories`、常驻 `memory_blocks`（profile/preferences/current_focus 块、乐观锁）、召回 `memory_facts`（HNSW cosine、`content_hash` 幂等、`superseded_by` 修正）；`AgentMemoryService`/`FactStore`、四个记忆工具、异步 `settle_session_memory`（游标增量+区间幂等）；Studio 文件型记忆（MEMORY.md 索引 + `.memory/*.md` + Git 检查点）；L4 AgentTeams 会诊接入与注入纪律；`memory_v2_enabled` 开关、OTel 观测指标、已落地/未收口清单与修改指南。

---

## 4. Studio 与沙箱

### `cygnusx_studio_handover_2026-07.md` — OmicStudio 实施进度与交接文档（历史快照，2026-07-17）
P0–P3 全阶段建设记录：sandbox-agent 端点协议（/exec NDJSON、文件 API、路径防护）、StudioSandboxManager 与三个已修复 bug、`studio.yaml`、10 个 Studio 内置工具（`sandbox_execute`/`workspace_*`/`datahub_import`/`artifact_register`/`update_plan` 等）、SSE 事件协议、Studio REST API 全表与前端清单；P1 per-user 只读挂载安全决策、Context Packager、报告版本树；P2/P3 diff 回滚、Celery 长任务、MCP/Skills 渐进披露、egress 代理、分享导出、Skill 提炼。已声明"勿按本文档再次执行"，现行沙箱基线见下一份。

### `cygnusx_sandbox_architecture_2026-08-22.md` — 沙箱强化架构（规范+进度，v1.1）
不替换 OmicStudio 编排前提下的容器隔离强化与 capability 路由：`code`/`browser`/`document` 三运行能力、Agent `features.studio.sandbox_capabilities` 授权源、`sandbox_meta` 持久化与 `studio.images` 镜像选择（含"未配置默认放行"实现偏差记录）；容器安全基线表（nano_cpus、pids_limit、cap_drop=ALL、no-new-privileges、uid 10001、只读根、tmpfs、network 白名单、10GiB 配额）；独立 browser-office 镜像；阶段 0–2 施工记录（`audit.py` 六类生命周期事件、配额兜底方案）与 gVisor/Kata 升级触发条件、验收状态。沙箱安全与 capability 的唯一规范来源。

### `research_loop_architecture_2026-09.md` — 科研闭环 as-built（WP0–WP4，2026-09-18）
会话工作区生命周期（休眠打包/平台侧归档/解包恢复/到期清理/管理页）、不可变执行历史（`chat_message_events` 事件表 + 双读重建 + 信封 payload_hash + 产物 sha256 对账）、声明式环境还原（micromamba 一次性还原 + 科研模式门控）、长任务 job 三契约（先落盘/终态不可重开/reconcile-only）、科研形态（cell 投影 / .ipynb 确定性导出 / research_mode 三开关）、PTC llm_query（system 锚定 + 同窗审计）、chat warm pool 硬化对齐 Studio 基线、LangGraph 审批闸（ADR-0002）。含新增配置/迁移/beat/API 速查表与已知限制（生产只读 rootfs 下 env restore 降级等）。施工依据 `docs/info/26.9.18/OmicHub科研闭环-实施手册.md`。

---

## 5. 专项子系统

### `mcp_architecture.md` — MCP 子系统（as-built + 已吸收 MCP 构建师 as-built）
MCP 三层体系（内置 Preset / 外部 Server / 管线专属）：`presets.py` 工具清单（cygnusx-platform 22 个、pipelines 10 个）、注册发现流程（`ensure_presets` → `mcp_servers` 表 → Agent YAML `mcp_ids`）、`MCPClient` 三层安全校验、`/api/v1/mcp/*` 端点与 `mcp_servers`/`mcp_logs` schema；双沙箱体系与 Egress 白名单；AI 模型接入（ProviderManager）。§4 为 Agent 自生成 MCP 提案的历史注记；§5 为已并入的 **MCP 构建师 `agent-mcp-builder` as-built**：六阶段生成流水线、`POST /api/v1/mcp-builder/builds` → `MCPBuilderService`、AST StaticSafetyChecker 12 条规则、sandbox_agent `/mcp/start|call|stop|list` STDIO 执行层、`mcp_builds`/`mcp_versions`/`mcp_visibility`/`mcp_reviews` 数据模型与状态机、15 条 Builder API、TTL/审核运维；§6–§10 独立 mcp-server、管线 MCP、约束红线。

### `database_architecture.md` — 数据库基础设施基线（as-built + 规范，2026-09-11）
`session.py` 按进程分流引擎（Web AsyncAdaptedQueuePool / Worker NullPool）、只读副本回退、连接池 OTel 指标；ORM 契约（`models/__init__.py` 全量注册 87 表、模型↔schema 对齐规则、pgvector 自实现 `vector.py`、relationship 懒加载纪律）；仓储两级分层（核心域 Protocol+实现、轻量域直连模型的升格判据）；迁移治理（Alembic 唯一事实来源、`check_migrations.py`/`check_schema_drift.py` 零漂移、外部表清单）；管理端 `/admin/database` 健康页；§11 参考基因组模块（SQLite/FTS5、CDS/UTR、GO Slim、JBrowse/BLAST）；新附录：Terminal 与参考基因组模块更新记录（自 LOG_ARCHITECTURE §9.2–9.6 迁入）。

### `log_architecture.md` — 统一日志架构（as-built + 更新规范）
统一日志根 `/data/cygnusx/logs/`（app/celery/nginx/snakemake/audit 五域）；`core/logging.py` loguru 四 sink 与 `CYGNUSX_LOG_*` 环境变量、trace_id 注入；`LoggedTask` 单任务日志、DB `tasks.logs` 截断；Nginx `cygnusx_json` 格式、Snakemake 落盘、审计 `audit_logs` 表 + JSON 备份；Docker 挂载矩阵、Loki/Promtail 预留、清理策略与容量治理、排障速查。与日志无关的 terminal/参考基因组记录已迁至 database_architecture.md 附录。

### `worker_images_plan.md` — Worker 轻量镜像计划（提案）
`Dockerfile.worker` 边界：python:3.11-slim + Celery + Snakemake + Micromamba，不打包流程/参考基因组/Conda 环境；运行时挂载约定（`/opt/cygnusx/pipelines:ro`、`.conda_envs` 按内容哈希复用）；六步实施（依赖盘点、compose 挂载、`SNAKEMAKE_CONDA_PREFIX`、PUID/PGID 与并发预热、构建验证）；验收标准、风险与 Rule 级容器化/Slurm/K8s 演进方向。

### `knowledge_architecture.md` — 知识库架构（as-built 快照，2026-07-31）
"一份数据两个消费方"（人类页面 + AI 检索）：`knowledge_bases`（show_in_lab/ai_searchable/is_enabled 三开关）、`kb_documents` 双指针版本、`doc_revisions`、`doc_editors`/`doc_audit_logs`/`kb_issues` 六表与迁移；`import_scseq_knowledge.py` 幂等导入 209 篇单细胞笔记；页面 `api/v1/docs.py` 过滤与编辑审核流；§6 `knowledge_search` 子串匹配现状（**已被 pgvector 向量检索取代**，见 memory/database 文档）；管理端 CRUD。

---

## 6. 前端

### `frontend.md` — 前端设计系统与实现规范（规范，36 章）
CygnusX 前端唯一权威规范：设计目标与非协商原则、技术边界；设计令牌（色彩/字体/间距/圆角/阴影）；页面结构与材质层级、设计质感基线（§33"被设计过"而非"被生成出来"）；组件实现契约与状态规范；动效与交互、响应式与可访问性、跨平台迁移；Hero 背景动画系统（§32 OmicBackgroundAnimation）；数据可视化规范（§13 图表配色/导出）；实时通信与 WebSocket、API 层与数据请求、状态管理（Pinia 边界）、文件操作；**AI 对话与流式界面（§18）**、终端与代码沙箱（§19）、AI 助手主入口设计与优化（§35–36）；知识库阅读页三要素冻结规范（§34）；代码组织与命名、性能预算、测试策略、安全规范、国际化、错误边界、路由与权限、通知、打印导出、长任务监控、叠层与定位选择器；实施流程与变更验收清单、可复用 Skill 入口、工具详情页对齐规范。

---

## 7. 其他

### `skill_architecture.md` — CygnusX Skill 体系全生命周期（as-built，2026-09-18）
由代码实勘得出的 Skill 子系统权威文档：两套 Skill 体系辨析（Kimi CLI Agent Skills vs 平台 Skill）；双层存储（`data/ai/skills/` 磁盘真相源 + skills/skill_versions/skill_invocations DB 三表索引）；SKILL.md 解析规范与 skill_store 读写；Agent `skill_ids` 声明式绑定与三层渐进披露发现；运行时工具路由、事件流与审计；五入口"预览→确认"导入管线、管理端创建、Studio 提炼、阿里云官方源同步（`ALIYUN_SKILLS_ENABLED` 默认关闭）；双轨版本管理；管理端 API 清单、数据表与迁移、前端组件；对旧文档的修正记录。

---

## 8. 废弃归档(deprecated/)

> **2026-09-18 归档说明**:AgentTeams 协作室(部门协作/超频/房间体系)这一方向不再继续演进,相关三份设计/架构文档移入 `deprecated/` 子目录原样保留,仅作历史参考,不再更新。**注意区分**:`agent_execution_framework.md` 中登记的 `agentteams_*` 执行路径与相关代码是平台现状的一部分,是否下线以代码与该文档为准;本目录仅废弃"设计文档"。

| 文件 | 内容简介 |
| --- | --- |
| `deprecated/agentteams_room_architecture.md` | 协作室历史基线(as-built,已归档,基线 2026-08-21,已吸收 room_plan、framework_research、manager_role):Web→Bridge/Matrix/MinIO→Gateway→Worker 四层拓扑;房间/Case 意图路由四态;多人模型 A1+ 平台代持与 `agentteams_room_members` 邀请状态机;全量过程记录(`AgentTeamsTurnRecorder`、MinIO turns + PG + OTel 三层);流程 HTML 报告;§15 模块清单、§16 演进史与遗留问题、§17 架构决策档案、附录 A Manager 双身份与红线 |
| `deprecated/agentteams_department_collaboration.md` | 部门协作架构当前稿(Phase 1/2/3 落地回写):用户—Manager—领域 Agent—并行 Worker 组织模型与五原则;`@` 点名群聊协议、任务冻结/变更决策状态机、dispatch_mode 与 `room.agent_handoff` 交接事件、产物声明与写冲突串行化 |
| `deprecated/agentteams_overdrive.md` | 超频模式(Overdrive)设计与实施全记录:`overdrive` 请求字段与 `mode_changed`/`room_speech` SSE 契约、第一期 B1–B5/F1–F5 详案、第二期 Matrix Gateway、第三期提前实现、风险清单与第 10 章审查修复记录 |

---

## 合并记录（2026-09-18）

| 已移除文件 | 合并去向 | 处理方式 |
| --- | --- | --- |
| `agent_execution_loop_observability_2026-08.md` | `agent_execution_framework.md` §4/§5.1/§6.1/§6.4/§6.5/§7.3/§10.1 | 独有内容并入 |
| `agent_architecture_and_extension_guide.md` | `agent_framework_baseline.md` §2.2/§8.4/§11/§12/§13 | 独有内容并入 |
| `agentteams_department_collaboration_architecture_2026-08.md` | `agentteams_department_collaboration.md` | 评审稿被当前稿完全覆盖，删除（历史查 git） |
| `agentteams_implementation_prompt.md`、`agentteams_review_fixes_prompt.md` | — | 纯转述提示词、零独有内容，删除 |
| `agentteams_review_fixes.md` | `agentteams_overdrive.md` 第 10 章 | 有效裁决并入 |
| `agentteams_room_framework_research_2026-08.md` | `agentteams_room_architecture.md` §2.1/§4.5/§15/§16 | 独有内容并入 |
| `agentteams_room_plan.md` | `agentteams_room_architecture.md` §17 | 决策档案并入，施工流水账归档 git |
| `manager_role_bioinfo_department_manager_2026-08.md` | `agentteams_room_architecture.md` 附录 A | 双身份辨析与红线并入 |
| `mcp_builder_agent.md` | `mcp_architecture.md` §5 | 两代文档合一，被取代的提案段压缩为历史注记 |

另：`log_architecture.md` §9.2–9.6（与日志无关的 terminal/参考基因组记录）迁至 `database_architecture.md` 附录。

## 命名规范记录（2026-09-18）

| 原文件名 | 新文件名 | 更名理由 |
| --- | --- | --- |
| `fontend.md` | `frontend.md` | 修正拼写错误 |
| `LOG_ARCHITECTURE.md` | `log_architecture.md` | 全小写 |
| `ARCHITECTURE_skill.md` | `skill_architecture.md` | 全小写 + 领域前缀统一 |
| `agent_current_execution_framework_2026-08.md` | `agent_execution_framework.md` | 活文档去日期（"current"由基线日期表达） |
| `agent_framework_final_baseline.md` | `agent_framework_baseline.md` | 活文档去"final" |
| `agentteams.md` | `agentteams_overdrive.md` | 实名化：本文只讲超频模式 |
| `agentteams_department_collaboration_architecture.md` | `agentteams_department_collaboration.md` | 去冗余 architecture 后缀 |
| `agentteams_room_current_architecture_2026-08-21.md` | `agentteams_room_architecture.md` | 活基线去日期与"current" |
| `cygnusx_sandbox_enhancement_architecture_2026-08-22.md` | `cygnusx_sandbox_architecture_2026-08-22.md` | 简化，保留快照日期 |
| `cygnusx_studio.md` | `cygnusx_studio_handover_2026-07.md` | 时点快照实名化并补日期 |
| `execution_layers.md` | `chat_execution_layers_2026-08.md` | 补领域前缀与快照日期 |
| `knowledge_db.md` | `knowledge_architecture.md` | 子系统命名统一为 *_architecture |
| `multi-agent.md` | `multi_agent_fanout_2026-07.md` | 去连字符；实名化（核心是 Fan-out 设计）并补日期 |
| `multi-agent-prompt.md` | `domain_prompt_sedimentation_2026-08.md` | 原名误导（内容与 agent 并行无关，实为领域沉淀设计） |
| `plan_ai.md` | `mas_a2a_plan_2026-07.md` | 与根目录通用 `plan-ai.md` 区分，实名化并补日期 |
| `平台愿景定义.md` | `cygnusx_platform_vision_2026-08.md` | 中文转英文 + 提案补日期 |

未更名（已符合规范）：`README.md`、`cygnusx_architecture.md`、`cygnusx_design.md`、`database_architecture.md`、`mcp_architecture.md`、`memory_architecture.md`、`agent_architecture_review_2026-07.md`、`worker_images_plan.md`。
`docs/` 目录下的历史日期文档仍引用旧文件名，作为当时的事实记录保留，不再回改。

## 相关文档（目录外）

- `docs/26.7.22/ai_assistant_single_entry_architecture.md`：AI 助手模块详细架构（统一入口「智能助手」、双引擎分流 LangGraph/手写循环、智能路由、MCP preset、Studio HITL、SSE 事件协议、前后端组件链）及优化待办清单与落地记录。
- 开发环境热刷新约定见根目录 `README.md`「Docker 部署」一节：日常改代码/YAML/前端用 `make docker-dev-refresh`（秒级，bind mount 免重建镜像），仅依赖（`uv.lock`/Dockerfile）变更才用 `make docker-reload`。
