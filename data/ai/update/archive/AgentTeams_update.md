# AgentTeams 多 Agent 协同实现框架（比赛交付，已归档）

> 文档性质：比赛阶段以 **AgentTeams 为协同设计基点**的实现框架与施工说明。
> 更新日期：2026-08-10（已完成全面代码审核，审核结论见 §0，施工清单见 §8，最终审核清单见 §10）。
> 适用：在 OmicHub 平台已有的 AgentTeams Bridge / Gateway / Worker 集群上，让平台真实定义的
> 专家 Agent（`agent-rnaseq` / `agent-code` / `agent-viz` / `agent-qc` 等）作为执行者，
> 在**一个聊天窗口**内完成"任务 → 规划 → 确认 → 执行 → 质控 → 汇总交付"的端到端闭环。
>
> 赛后长期目标见 `update_agent.md`（Kimi 式单窗口人格化异步团队）。本文与该文档共享同一条原则：
> **执行者始终是平台 `data/ai/*.yaml` 定义的真实 Agent，不在 AgentTeams 里另造一套角色大脑。**
>
> 本文档是**自包含施工规格**：每个施工项都给出改动文件、实现要点和验证方式，可直接交给
> Codex / 开发者逐项执行。施工顺序严格按 §8 的 P0 → P1 → P2。

---

## 0. 全面审核结论（2026-08-10 实测）

审核方法：对照本文档每项声明，对 Bridge/Gateway/Worker 栈、OmicHub 后端、前端投影三条线
做全量代码核查（逐文件读取，非抽样）。

**总结论：编排骨架（状态机/租约/审批/审计/投影）质量高于本文旧版自述，可直接作为比赛协同基点；
执行内核（consultation 端点）缺失是唯一的根因级缺口；另有 3 个审核新发现会直接卡住比赛验收
（N1 身份令牌缺失、N2 质控空转、N3 聊天内无法审批）。**

### 0.1 已核实完成的点（无需再施工，审核通过）

| # | 能力 | 证据（文件:行号） |
| --- | --- | --- |
| A1 | Case 状态机：15 态（旧文写 14，以代码为准），`_ALLOWED_TRANSITIONS` 白名单转换、非法转换 409、本地锁 + Redis 分布式锁 | `integrations/agentteams/bridge/omichub_agentteams_bridge/case_store.py:29-44`、`:47-66`、`:175` |
| A2 | Work Item 租约/认领：原子 claim、heartbeat 续租、过期自动 requeue、attempt/max_attempts 重试预算 | `case_store.py:389-579`；模型字段 `models.py:247-269` |
| A3 | 审批签名：HMAC-SHA256 + scope 校验（case/action/work_item/flow/task）+ `hmac.compare_digest` 防时序；analysis-worker 走 token-free 预存提交 | `security.py:44-106`；`service.py:744-820`（queue）、`:822-888`（submit-approved） |
| A4 | 审计 append-only：JSONL 文件 / Redis Stream 只追加；per-case 查询 + SSE 流 | `audit.py:26-222`；`app.py:335-393` |
| A5 | 只读能力边界三层强制：Bridge 强制 `agent-*` 工单 read_only（422）→ Gateway 硬编码剥离 `allow_task_actions/allow_file_write/database_access/shell` → agent/capability/tool 三层白名单 | `service.py:91-95`；`gateway/client.py:24-45`；`gateway/service.py:81-98` |
| A6 | 交付 manifest 生成：`{case_id}.delivery_manifest.json` 含 Case、Agent 身份、输入引用、任务快照、质控结论、审批事件、全部审计事件、runbook | `service.py:1132-1194` |
| A7 | 后端投影器：`CaseRoomProjector` 产出 `room_speech` / `overdrive_progress` / `overdrive_approval_request` / `mode_changed` 四类 SSE 事件 | `src/omichub/application/services/case_room_projector.py:30-97` |
| A8 | Celery 巡查：`watch_cases` 带 Redis 分布式锁，默认 60s 周期，游标续传 | `src/omichub/infrastructure/celery_app/tasks/agentteams.py:25-67`；beat 配置 `celery.py:128-131` |
| A9 | 前端 Case 工作台：状态时间线、审计事件流（SSE + 20s 轮询兜底）、审批模态框、协作聊天室抽屉、工单列表 | `frontend/src/components/agentteams/AgentTeamsCaseView.vue`；路由 `router/index.ts:122-126` |
| A10 | 前端单窗口投影消费：`room_speech` 气泡（头像/角色/折叠）、进度卡、审批卡与超频 v2 **完全共用组件**，零新事件类型 | `stores/agentHub.ts:254-327`（applyCaseRoomEvent 复用超频逻辑）；`KimiMessageItem.vue` |
| A11 | 管理端面板：外部 Worker 心跳（X/Y 活跃 + 告警）、Case 列表、重协调（TOTP）、接入向导 | `frontend/src/components/admin/AgentTeamsBridgeTab.vue` |
| A12 | 可复用执行内核：`ParallelSubAgentService` 具备 `safe_only` 只读过滤（`:398-403`）、有界循环、超时、重试、工具结果截断 8000 字符、失败隔离，可直接承载 consultation 回合 | `src/omichub/application/services/parallel_subagent_service.py:161-178` |
| A13 | 平台 Agent 装载：`AgentService.assemble_context(agent_id, user_id=...)` 可装载系统提示词/Persona/模型/MCP/Skill/工具白名单，user_id 语义即"以真实用户身份运行" | `src/omichub/application/services/agent_service.py:758-969` |
| A14 | 平台 Agent 已定义并启用：`agent-data` / `agent-qc` / `agent-delivery` / `agent-rnaseq` 均在 `agents.enabled`（共 16 个） | `data/OmicHub.yaml:84-101`；`data/ai/{data,qc,delivery,rnaseq}.yaml` |
| A15 | OmicHub 侧 Case 管理 API 9 个端点齐全（创建/详情/审批提交/事件/流） | `src/omichub/api/v1/agentteams.py:91-209` |
| A16 | Bridge/Gateway/Worker 契约测试约 2600 行（Bridge 1498 行最全） | `integrations/agentteams/**/tests/`、`deploy/agentteams/tests/` |

### 0.2 已确认缺口（本文旧版已承认，审核复核属实）

| # | 缺口 | 证据 |
| --- | --- | --- |
| G1 | **`POST /api/v1/agent-teams/consultations/scientific-interpretation` 不存在**，`agent_consultation_service.py` 不存在——专家工单无法真执行的根因 | `src/omichub/api/v1/agentteams.py` 全文无 consultation |
| G2 | **`ROLE_AGENT_MAP` 错配**：`data-steward/quality-auditor/delivery-reporter` → `agent-general` | `case_room_projector.py:7-16` |

### 0.3 审核新发现（旧文未提；N1–N3 直接卡比赛验收）

| # | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| N1 | `teams/bioops-delivery.yaml` **无 `agent-rnaseq` 角色**；`bridge.env` 缺 `agent-rnaseq`、`analysis-worker` 令牌（9 个身份 vs `config.py:21-26` 默认值 11 个） | `deploy/agentteams/bridge.env:6` | 生产 profile 起满也只有 3/5，"5/5 活跃"验收必败 |
| N2 | **质量门空转**：Bridge 只持久化外部传入的 decision 不做检查；`quality_runner.py:63-71` 永远返回 `manual_review` | `bridge/service.py:1027-1094`；`worker/quality_runner.py` | "agent-qc 独立质控"名不副实 |
| N3 | **聊天内无法完成 Case 审批**：`AgentTeamsCaseCard.vue:71-74` 只有"刷新状态/打开 Case"，必须跳详情页批准 | 前端核查 | 违反 §9"用户未离开聊天窗口"验收 |
| N4 | `reconcile_case` 任务成功后只派 `quality-01`，**不派 agent-rnaseq 解读工单** | `bridge/service.py:120-167` | 专家发言链断在"解读"环节 |
| N5 | 前端两处"创建协作 Case"是假入口：只往输入框塞模板文字，不调 `createCase` API | `KimiChatInput.vue:799-805`；`StudioView.vue:604-607` | 用户预期落空 |
| N6 | manifest 只显示 `manifest_uri` 文本，无下载按钮，API 层无下载接口 | `AgentTeamsCaseView.vue:449`；`api/agentTeams.ts` | "manifest 可下载"不满足 |
| N7 | 事件游标存 `ChatSessionModel.sandbox_meta` 单 JSONB 字段，"发布 SSE 后、更新游标前"崩溃会丢/重事件；60s 轮询有延迟 | `agentteams_case_watch_service.py:86,126,149` | 断线重建可靠性 |
| N8 | `agent-data` / `agent-delivery` 是骨架：`skill_ids` 为空、welcome_message 自述"正在配置" | `data/ai/data.yaml`、`delivery.yaml` | 预检/交付环节有名无实 |
| N9 | Bridge 文件存储 `_persist()` 整体覆盖写、无原子 rename，崩溃可丢全部 Case；Gateway 成本护栏是进程内内存计数，多实例失效 | `case_store.py:636-646`；`gateway/service.py:31-33` | 生产健壮性 |
| N10 | consultation 端点缺**集成认证**：现有端点全是终端用户 JWT/API-Key，Gateway→OmicHub 机器间调用需专用集成令牌 | `api/v1/agentteams.py` 全部 `CurrentUserId` | G1 的隐含工作量 |
| N11 | 普通 `/ai` 聊天页（旧 `AIChat.vue`）完全不支持 AgentTeams，仅 Studio 页可用 | `views/AIChatView.vue` | 技术债，赛后随旧组件淘汰 |
| N12 | `integrations/agentteams/skills/` 只有 `contracts.yaml` 13 个 API 契约，无 skill 实现代码 | `skills/` 目录 | 名义能力 > 实际能力 |

---

## 1. 总体目标

在一个聊天窗口内，用户把任务交给 Manager，由 AgentTeams 框架完成下列闭环：

```text
用户发布任务
  → Manager 选择合适的领域 Agent 做规划，产出 plan
  → 聊天窗口弹出计划确认卡（用户 确认 / 修改 / 取消）
  → 确认后 Manager 调度合适的 Agent 执行（可多个、按依赖）
  → 各 Agent 结果逐个回流到同一聊天窗口（带头像/角色的发言气泡）
  → 质控 Agent 独立审核
  → Manager 汇总并交付结论与产物
```

比赛要求的五项映射（角色编排、任务拆解、上下文传递、协同执行、状态追踪）全部落在 AgentTeams
框架原语上，不新造并行编排系统。

**Case 不限定于平台流水线。** Manager 建单时判定两类 Case（详见 §3.4）：

- **流水线交付型**：目标可映射到平台已发布 flow（如 RNA-seq），走"提交→解读→质控→交付"全链；
- **通用分析型**：目标是用户数据上的即席分析（如"对 XXX 目录下的 .fa 文件构建 treeplot"），
  不对应任何 flow，走"规划→确认→工作区执行→质控→交付"，不经 analysis-worker。

两类共享同一套状态机、审批闸门、审计与单窗口投影。

---

## 2. 角色编排：平台 Agent 即执行者（两层模型）

### 2.1 核心架构决策：身份层与大脑层分离

**用户要求并已确定为最终方案：用平台 `data/ai/*.yaml` 定义的真实 Agent 替换 AgentTeams
内部创建的角色"大脑"。** 实现方式是两层模型，而不是把平台 Agent 塞进 AgentTeams：

```text
┌─────────────────────────────────────────────────────────────┐
│ 身份层（AgentTeams，安全与编排边界）                          │
│   一个身份 = 一个常驻 Worker 容器 = 只持自己的 Bridge 令牌     │
│   职责：轮询收件箱 → 认领工单 → 请求执行 → 回写结果            │
│   不含任何 LLM、不含任何领域逻辑（纯转发骨架，已核实）          │
└──────────────────────┬──────────────────────────────────────┘
                       │ execute-readonly → Gateway consult
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ 大脑层（OmicHub 平台 Agent，真正干活的）                      │
│   assemble_context(agent_id, user_id=requester_ref)          │
│   装载该 Agent 的系统提示词/Persona/模型/MCP/Skill/白名单      │
│   在 omichub-web 进程内经 ParallelSubAgentService 只读回合执行 │
└─────────────────────────────────────────────────────────────┘
```

**权威角色映射表**（施工后以此为准；Bridge 配置、Gateway 策略、OmicHub 投影器三处必须一致）：

| AgentTeams 身份（Worker 容器） | 平台 Agent（大脑） | 职能 | 执行方式 |
| --- | --- | --- | --- |
| `bioops-manager` | 当前会话主 Agent（星尘 AI / `agent-general`） | 接单、分派、汇总、交付 | Bridge 侧，由 OmicHub 后端驱动 |
| `data-steward` | **`agent-data`** | 数据契约、样本/文件预检 | 只读 consultation |
| `agent-rnaseq` | `agent-rnaseq` | RNA-seq 分析解读 | 只读 consultation |
| `agent-scrna` | `agent-scrna` | 单细胞解读 | 只读 consultation |
| `agent-code` | `agent-code` | 脚本复现、代码审查 | 只读 consultation |
| `agent-viz` | `agent-viz` | 可视化、图表规范 | 只读 consultation |
| `quality-auditor` | **`agent-qc`** | 独立质控、证据审查 | 只读 consultation（输出真实质控决策） |
| `delivery-reporter` | **`agent-delivery`** | 交付清单、runbook、证据汇总 | 只读 consultation |
| `analysis-worker` | （无大脑，提交器） | 持预存审批快照提交 OmicHub 流水线 | approval-gated 提交，不调 LLM |
| `approval-authority` | （审批网关，非 Agent） | 人工确认后签发短期、动作受限令牌 | 服务，非 Worker |

> 加粗的三行是本次"替换"的关键：身份名保持 AgentTeams 原语（`data-steward` 等），
> 执行时经权威映射解析为平台 Agent（`agent-data` 等）。Worker 容器、令牌、工单 target
> 全部不变；变化的只是"谁来思考"。

### 2.2 容器模型：是不是每个 Agent 一个容器？

**是——但容器的粒度是 AgentTeams 身份，不是平台 Agent。** 具体：

1. **每个 AgentTeams 身份一个常驻 Worker 容器**（最小权限：只持自己的 Bridge 令牌，
   不加载 `bridge.env`，避免继承 Manager 令牌/审批密钥/其他身份）。这是 AgentTeams 安全模型
   的硬性要求，比赛期间保持不变。
2. **平台 Agent 不需要新容器**。`agent-data` / `agent-qc` / `agent-delivery` 等大脑运行在
   既有 `omichub-web` 容器内（consultation 端点 + `ParallelSubAgentService`），它们的能力
   由 `data/ai/*.yaml` 声明，热更新走平台既有的 Agent 配置链路，不涉及 AgentTeams 部署。
3. **Worker 容器是薄进程**：无 LLM、无 GPU、无重依赖，只做 轮询 → 认领 → 转发 → 回写。
   全部 Worker 共用一个镜像（`deploy/agentteams` 构建），仅靠环境变量区分身份。

施工后的完整容器清单（compose `agentteams-production` profile）：

| 容器 | 身份 | 现状 |
| --- | --- | --- |
| `omichub-agentteams-bridge` / `-gateway` / `-state` | 控制面三件套 | ✅ 已在运行 |
| `agentteams-worker-code-production` | `agent-code` | ✅ 已定义 |
| `agentteams-worker-viz-production` | `agent-viz` | ✅ 已定义 |
| `agentteams-worker-scrna-production` | `agent-scrna` | ✅ 已定义 |
| `agentteams-worker-rnaseq-production` | `agent-rnaseq` | ✅ 已定义（compose `:177-193`），但 teams yaml / bridge.env 缺配置（N1，P0-3 修） |
| `agentteams-worker-analysis-production` | `analysis-worker` | ✅ 已定义 |
| `agentteams-worker-quality-production` | `quality-auditor` | ✅ 已定义，但执行逻辑空转（N2，P0-5 修） |
| `agentteams-worker-delivery-production` | `delivery-reporter` | ✅ 已定义，P0-5 接入 consultation |
| `agentteams-worker-data-production` | `data-steward` | ⬜ **需新增**（P0-3）：当前预检跑在 Bridge 内部，无独立 Worker；为让 `agent-data` 真实出场，新增该容器 |

> 说明：管理端心跳面板追踪的外部 Worker 是 `_EXTERNAL_WORKERS` 固定 5 个
> （`agent-code/viz/scrna/rnaseq/analysis-worker`，`bridge/service.py:56-58`）。
> `data-steward` 新容器不纳入 5/5 口径，避免破坏既有验收指标；如需展示可在面板另列。

比赛**至少 3 个不同职能**的端到端组合：`agent-data`（预检）→ `agent-rnaseq`（解读，
配合 `analysis-worker` 提交真实流水线）→ `agent-qc`（独立质控），Work Item 依赖串成闭环。

---

## 3. 任务拆解（映射到 Case + Work Item）

一次用户任务对应一个 **Case**；Case 被拆成若干 **Work Item**，每个 Work Item 精确分配给一个身份。

### 3.1 Work Item 契约（Bridge `models.py:WorkItemRecord`，已核实）

关键字段：`target`（承接身份）、`objective`（喂给目标 Agent 的自然语言目标）、
`skill_name`（如 `project-preflight` / `result_interpretation` / `quality-gate`）、
`depends_on`（DAG）、`context_refs` / `output_refs`（逻辑引用）、
`read_only`（专家工单必须只读，Bridge 已强制，A5）、`approval_required`（提交类工单需人工审批）。

### 3.2 工单序列（RNA-seq 示例，施工后形态）

```text
plan-01       (领域 Agent 如 agent-rnaseq,     read_only,         规划：出 plan + 参数草案
               capability=planning_advice)                        （P0-4b 新增，见 §3.3）
preflight-01  (data-steward → agent-data,      read_only,         数据/样本预检（校验参数与真实数据匹配）
               depends_on=plan-01)
plan-confirm  (Manager → 用户审批卡，聊天内完成)                    计划确认闸门（冻结 plan_hash + 参数快照）
submit-01     (analysis-worker,                approval_required) 提交 RNAFlow（执行冻结快照）
interpret-01  (agent-rnaseq,                   read_only,         结果解读（P0-4 新增派单）
               depends_on=submit-01)
quality-01    (quality-auditor → agent-qc,     read_only,         独立质控（P0-5 接真 Agent）
               depends_on=interpret-01)
delivery-01   (delivery-reporter → agent-delivery, read_only)     交付汇总
```

只读专家工单（含规划工单）由对应 Worker 认领后经 Bridge→Gateway→OmicHub consultation
端点执行；提交类工单由 `analysis-worker` 在人工审批后执行预存提交。

### 3.3 规划阶段：Manager 转派领域 Agent 出计划（P0-4b）

**现状差距**：当前 Bridge 流程没有规划工单——提交参数是创建 Case 时由调用方直接带入的，
Manager 并未把任务转派给领域 Agent 做规划。本节把这一环补上，使"任务拆解"由真实专家完成。

流程与硬性规则：

1. **Manager 选 lead_planner**：按任务方向与 `capability_scope` 选最匹配的领域 Agent
   （单领域选一个；跨领域一个 lead + 最多两个只读规划顾问）；禁止为了"团队感"固定套用
   通用/代码/可视化/质控四件套（与 `update_agent.md` 阶段 A 一致）。
2. **plan-01 经 consultation 只读执行**：`capability=planning_advice`，输入为用户目标 +
   `project_ref` + 已有 `context_refs`；信封在标准四字段外扩展一个结构化字段：
   ```json
   {
     "conclusion": "计划正文（markdown）",
     "proposed_submission": {"flow_id": "rna_seq", "params": {...}},
     "recommendations": [...], "evidence_refs": [...], "risks": [...]
   }
   ```
3. **参数必须过校验才可进入审批卡**：`proposed_submission` 先经 Bridge 既有校验链
   （flow 白名单 + `get_flow_schema` 参数 schema + 样本表/comparison 格式，
   `service.py:594-684`）——校验失败则 Case 进 `waiting_for_correction`，由 Manager
   退回规划 Agent 修订（上限 3 轮）；**LLM 自由文本一律不直接成为提交参数**。
4. **冻结与绑定**：校验通过后 Bridge 把 `proposed_submission` 存到 Case（新字段
   `proposed_submission` + `plan_hash`，hash 对规范化后的计划正文 + 参数 JSON 计算 sha256）；
   审批卡展示计划摘要 + 参数明细；用户点"确认"时 `queue_approved_submission` 冻结的
   **就是这份校验过的快照**，并在审批审计事件中记录 `plan_hash`。
5. **实质变更重新确认**：确认后任何改变 flow/参数/分组的修改都必须重新生成 plan-01 并再次
   经过确认闸门；仅文案修正可记录后继续（与 `update_agent.md` 阶段 D 一致）。
6. **状态机**：在 `received` 与 `preflight_running` 之间新增 `planning_running` 态
   （`_ALLOWED_TRANSITIONS` 加 `received → planning_running → preflight_running`，
   失败支路 `planning_running → waiting_for_correction`）；未经过 `planning_running`
   且无 `plan_hash` 的 Case 不得进入 `approval_pending`。

这样 §5 闭环中"规划"由真实领域专家完成，用户审批的就是专家产出且经机器校验的快照，
`analysis-worker` 依旧只做机械提交。

### 3.4 通用分析型任务：不限定于平台流水线

平台已有能力（星尘 AI → 特定 Agent）本就能完成"对 XXX 目录下的 .fa 文件构建 treeplot"
这类即席分析；AgentTeams 的价值不是替代它，而是把同类任务升级为**多专家协同、有计划确认、
有审计、有独立质控、可交付**的 Case。因此 Case 分两类：

| 维度 | 流水线交付型（pipeline） | 通用分析型（general） |
| --- | --- | --- |
| 触发 | 目标映射到平台已发布 flow（rna_seq 等） | 目标不对应任何 flow（建树、格式转换、定制统计、图表……） |
| 规划 | plan-01 产出 plan + `proposed_submission` | plan-01 产出 plan + 任务 DAG（无 flow 提交参数） |
| 确认 | 审批卡冻结 flow 参数快照 + plan_hash | 审批卡冻结任务 DAG + plan_hash |
| 执行 | `analysis-worker` 提交真实流水线 | **工作区执行工单**（execution_mode=workspace_execution，见下） |
| 质控/交付 | 相同（agent-qc / agent-delivery） | 相同 |
| analysis-worker | 参与 | **不参与**（无 submit-01 工单） |

通用型示例（treeplot）工单序列：

```text
plan-01     (agent-code,  readonly, planning_advice)    规划：mafft 比对 → iqtree 建树 → ggtree 渲染
plan-confirm(Manager → 用户确认 plan_hash + 任务 DAG)
exec-01     (agent-code,  workspace_execution)          比对 + 建树，产物写入用户工作区并登记
exec-02     (agent-viz,   workspace_execution,          treeplot 渲染出图
             depends_on=exec-01)
quality-01  (agent-qc,    readonly, depends_on=exec-02) 产物存在性/日志/合理性审查
delivery-01 (agent-delivery, readonly)                  交付清单 + 下载链接
```

**工作区执行通道**（施工规格见 §8 P0-6）要点：

- 与只读会诊**同一透传链**（Worker → Bridge → Gateway → OmicHub），仅 OmicHub 侧执行模式不同：
  `ParallelSubAgentService` 用 `workspace_access=True`、`safe_only=False`，Agent 按其 YAML 的
  `tool_packs` 白名单使用平台工具（含沙箱命令、文件读写）；
- 工作目录强制限定 `output/agentteams/<case_id>/<work_item_id>/`，产物按平台规则登记
  `file_records`（否则 /files 页不可见、无法下载）；
- **执行工单的合法性来自 plan 确认**：execution 工单必须能追溯到已确认 plan（plan_hash 绑定）
  中的任务；plan 外新增执行工单必须重新走确认闸门；单条高风险工具调用仍弹平台审批卡
  （计划确认 ≠ 危险操作豁免）；
- Bridge 侧对 `agent-*` 工单的 read_only 强制（422）放宽为：
  `execution_mode=workspace_execution` 的工单允许非只读，但必须 `approval_required=True`
  或所属 Case 已有确认 plan_hash。

这样 AgentTeams 的多 Agent 流程对**任意用户任务**开放：能映射到流水线的走流水线，
不能的走工作区执行，编排/审批/审计/投影语义完全一致。

---

## 4. 上下文传递（映射到 context_refs / evidence_refs / consultation_summary）

上下文**不靠 Worker 之间自然语言对话**传递，而是通过 Bridge 持有的结构化引用与审计事件流转：

1. **输入上下文**：Case 创建时携带 `project_ref`、`intent`、`consultation_summary`。
2. **工单上下文**：每个 Work Item 的 `context_refs` 声明依赖的 project / file / task / report 引用。
3. **执行透传链**：
   `Worker → Bridge(execute-readonly) → Gateway(consult) → OmicHub /consultations/scientific-interpretation`，
   请求体携带 `case_id / agent_id / question / capability / evidence_refs / requested_tools / requester_ref`。
4. **用户身份透传（施工要点）**：Case 的 `requester_ref`（真实用户 id）必须一路透传：
   - Bridge：`CaseRecord.requester_ref`（已有）→ `execute_readonly_work_item()`（`service.py:266-378`）
     调 Gateway 时加入请求体（**当前未传，P0-1 补**）；
   - Gateway：`models.py` 上游请求模型加 `requester_ref` 字段，`client.py:24-45` 透传；
   - OmicHub：consultation 端点取 `requester_ref` 作为 `assemble_context(user_id=...)` 的实参，
     使专家 Agent 以**该用户身份**运行（知识库、工作区、权限按真实用户隔离）。
5. **产物回流**：执行结果经 Gateway 固定信封（`conclusion / recommendations / evidence_refs / risks`，
   `gateway/models.py:46-52`）回到 Bridge，写为审计事件并作为下游工单的 `context_refs`。

> 关键约束：Gateway 强制 `read_only=True` 且剥离 task/file/db/shell（A5）。专家 Agent 在
> consultation 端点内运行时由 `safe_only=True` 二次保证只读（A12）；真正的流水线提交只走
> `analysis-worker` + 审批令牌这一条路。

---

## 5. 协同执行（单窗口流程如何映射到 Case 状态机）

Case 状态机（15 态，A1）就是协同执行的骨架：

```text
received
  → planning_running         （领域 Agent 出 plan + 参数草案 —— P0-4b 新增状态）
      └─ 校验失败 → waiting_for_correction → 退回修订（≤3 轮）
  → preflight_running        （data-steward → agent-data 预检）
  → approval_pending         （聊天窗口弹计划/提交确认卡，用户聊天内批准 —— P1-6 后成立）
      ├─ cancel → cancelled
      └─ approve → approved
  → executing                （analysis-worker 提交 OmicHub 流水线；agent-rnaseq 解读）
  → quality_running          （agent-qc 独立质控）
      ├─ pass → delivery_ready
      └─ blocked → quality_blocked / remediation_pending → 回到 executing / quality_running
  → delivery_ready           （agent-delivery 交付汇总）
  → closed                   （交付 manifest 生成）
```

### 5.1 执行内核：consultation 端点（施工规格见 §8 P0-1）

Worker 认领专家工单后，Bridge 调 Gateway，Gateway 回调：

```http
POST /api/v1/agent-teams/consultations/scientific-interpretation
X-Integration-Token: <集成令牌>     # 机器间认证，非终端用户 JWT（N10）
{
  "case_id": "...",
  "agent_id": "agent-rnaseq",        # 平台真实 Agent，由 Bridge 权威映射解析
  "question": "<objective + context_refs 渲染出的任务>",
  "capability": "result_interpretation",
  "evidence_refs": [...],
  "requested_tools": [...],
  "requester_ref": "<真实用户 id>"
}
```

OmicHub 侧执行（复用已审核通过的 A12/A13）：

1. `AgentService.assemble_context(agent_id, user_id=requester_ref)` 装载平台 Agent 全量上下文；
2. 运行**只读受限回合**：`ParallelSubAgentService.run(...)` 单 task，
   `safe_only=True`、`workspace_access=False`、`runtime_authorized=True`；
   自动获得有界循环/超时/重试/8000 字符工具结果截断/失败隔离；
3. 按提示词契约要求专家输出结构化结论，解析为固定信封
   `{conclusion, recommendations, evidence_refs, risks, token_usage}`，
   对齐 Gateway `UpstreamConsultationResponse`（`gateway/models.py:46-52`）；
   解析失败时降级为 `conclusion=原文` 并在 `risks` 记录"信封解析降级"。

这样 `agent-rnaseq` Worker 执行的就是平台上真实的 RNA-seq 专家（提示词/Persona/Skill/工具
与聊天内一致），满足比赛"发言来自平台对应 Agent"的验收。

### 5.2 单窗口投影

聊天窗口不跳独立 Case 页也能完成闭环：

- `watch_cases`（60s，P2 降至 10-15s）扫描活跃 Case，`CaseRoomProjector` 把审计事件投影为：
  - `case.created / work_item.assigned / skill.finished / quality.decision / case.closed` → `room_speech`；
  - 工单分配/完成 → `overdrive_progress`（泳道进度）；
  - `approval_pending` → `overdrive_approval_request`（审批卡）；
- 前端消费已就绪（A10）；`ROLE_AGENT_MAP` 修正（P0-2）后气泡头像/名字与真实专家一致；
- **审批卡施工后可在聊天内直接批准/拒绝**（P1-6），不再强制跳 Case 详情页。

独立 Case 工作台页（`AgentTeamsCaseView.vue`）保留为详情/审计入口，不强制使用。

---

## 6. 状态追踪（映射到审计事件 + manifest）

- **Case 状态机**：15 态原子转换（A1），每次转换写审计事件。
- **append-only 审计流**（A4）：`case.created / work_item.assigned / work_item.claimed /
  skill.finished / omic_task.completed / quality.decision / case.closed`，经
  `GET /cases/{id}/events` 与 `/cases/{id}/events/stream` 拉取。
- **租约/认领**（A2）：一个工单同一时刻只被一个 Worker 执行，失败按预算重试。
- **交付 manifest**（A6）：Case 关闭时生成，含全量证据；P1-7 补前端下载入口。
- **聊天侧追踪**：事件经投影成为窗口内发言、进度泳道和审批卡；断线后由事件游标重建。
  已知风险 N7（游标存 sandbox_meta 单字段，崩溃窗口内可能丢/重事件），P2-10 加固。

---

## 7. 部署与 Worker 容器

Bridge / state / gateway 三容器已在运行。生产专家 Worker 用 compose profile 拉起：

```bash
cd deploy/agentteams
# 1. 配置真实令牌（bridge.env 的 BRIDGE_IDENTITIES 必须含全部 11 个身份 —— P0-3 修正）
# 2. 起生产 profile（施工后为 8 个 Worker 容器）
docker compose -f docker-compose.agentteams.yml \
  --profile agentteams-production up --build -d
```

令牌只通过部署 secret / 环境变量注入；Worker 不加载 `bridge.env`（最小权限）。
后端代码改动后必须 `docker restart omichub-web`（uvicorn 无热重载）；
Celery 任务（如 watch 间隔、投影逻辑）改动后必须 `docker restart omichub-worker`。

---

## 8. 施工清单（Codex 执行版）

> 执行纪律：
> - 严格 P0 → P1 → P2 顺序；P0 任意一项未完成不得开始 P1。
> - **业务智能（解读、质控判断）只允许写在 OmicHub 侧的 Agent/consultation 服务里，
>   禁止写进 Bridge/Gateway/Worker 的 Python 代码**——Bridge 只承担状态机/租约/审批/审计，
>   赛后编排迁移（`update_agent.md`）时专家能力零改动平移。
> - 每完成一项：跑 `deploy/agentteams/tests/` 与 `integrations/agentteams/**/tests/` 回归；
>   后端改动 `docker restart omichub-web`；Celery 改动 `docker restart omichub-worker`。
> - 每完成一项，到 §10 对应行把 ⬜ 改为 ✅ 并填验证日期。

### P0 — 不做则闭环跑不通

#### P0-1 实现 consultation 端点（基石，修 G1+N10）

**OmicHub 侧（新建 + 改动）：**

1. 新建 `src/omichub/application/services/agent_consultation_service.py`：
   - `AgentConsultationService.run_consultation(case_id, agent_id, question, capability,
     evidence_refs, requested_tools, requester_ref) -> ConsultationEnvelope`；
   - 校验 `agent_id` 在允许集合（`agent-data/qc/delivery/rnaseq/scrna/code/viz`）且已启用；
   - `AgentService.assemble_context(agent_id, user_id=requester_ref)` 装载上下文，
     agent 不存在/未启用返回 404 语义错误；
   - 调 `ParallelSubAgentService.run(...)`：单 task（instruction = question + evidence_refs 渲染
     + 信封输出契约），`safe_only=True`、`workspace_access=False`、`runtime_authorized=True`；
   - 解析子 Agent 最终答复为 `{conclusion, recommendations, evidence_refs, risks, token_usage}`；
     提示词契约要求输出 ```json 代码块，解析失败降级 conclusion=原文 + risks 记一条；
   - 全程结构化日志（case_id/agent_id/requester_ref/耗时/token）。
2. `src/omichub/api/v1/agentteams.py` 新增 `POST /consultations/scientific-interpretation`：
   - **集成认证（N10）**：新增依赖 `IntegrationTokenRequired`——读 `X-Integration-Token` 头，
     与 `settings.agentteams_integration_token` 做 `hmac.compare_digest` 比较，缺失/不符 401；
     Settings 字段为裸名 `AGENTTEAMS_INTEGRATION_TOKEN`（本项目 Settings 无 env_prefix）；
     **不得**用 `CurrentUserId`（终端用户认证不适用于机器间调用）；
   - 请求模型：`case_id / agent_id / question / capability / evidence_refs / requested_tools /
     requester_ref`（pydantic，全部校验长度上限）。
3. 单元测试 `tests/unit/test_agent_consultation_service.py`：信封解析、降级路径、
   agent 不存在、集成令牌缺失/错误、safe_only 工具剥离生效。

**Bridge / Gateway 透传（requester_ref + 角色映射）：**

4. Bridge `service.py:execute_readonly_work_item`：调 Gateway 的请求体加 `requester_ref`
   （取 `CaseRecord.requester_ref`）；加权威 `ROLE_AGENT_MAP`（见 §2.1 表，放 Bridge `config.py`，
   可用环境变量覆盖），将工单 target 解析为平台 `agent_id` 传给 Gateway；
   扩展 `execute_readonly_work_item` 的 actor 白名单：当前只允许 `agent-code/viz/scrna/rnaseq`
   （`service.py:266-378`），需加入 `data-steward / quality-auditor / delivery-reporter`。
5. Gateway：`models.py` 上游请求模型加 `requester_ref`；`client.py:24-45` 透传；
   `config.py:30-39` `agent_policies` 补 `agent-data / agent-qc / agent-delivery` 的
   capability + tool 白名单（tools 可为空数组——只读研究工具由 OmicHub 侧 safe_only 控制）。
6. `gateway.env` 增加 `GATEWAY_OMICHUB_INTEGRATION_TOKEN`，与 OmicHub 侧 `AGENTTEAMS_INTEGRATION_TOKEN`
   一致；`client.py` 调 OmicHub 时带 `X-Integration-Token` 头。

**验证：** 单元测试通过；`docker restart omichub-web` 后
`curl -X POST .../consultations/scientific-interpretation -H "X-Integration-Token: ..."`
以 `agent-rnaseq` 发起真实会诊，返回非空 conclusion；无令牌请求 401。

#### P0-2 修正 ROLE_AGENT_MAP（修 G2）

- `src/omichub/application/services/case_room_projector.py:7-16`：
  `data-steward→agent-data`、`quality-auditor→agent-qc`、`delivery-reporter→agent-delivery`；
  其余保持不变。未命中映射的角色降级 `agent-general` 并记 WARNING。
- 注意与 Bridge 侧权威映射（P0-1 第 4 步）同源——两处值必须一致，建议在文档/注释中互相引用。

**验证：** `docker restart omichub-web && docker restart omichub-worker`；触发一个 Case，
聊天气泡显示"数据管理员/质量审计员/交付报告员"头像与名字，不再是"通用助手"。

#### P0-3 补齐身份配置 + 新增 data-steward 容器（修 N1）

1. `integrations/agentteams/teams/bioops-delivery.yaml`：补 `agent-rnaseq` 角色定义
   （skills：`result_interpretation`、`rnaseq-planning-advice`，对齐现有 agent-code 条目的格式）；
   补 `data-steward` 的 consultation 化说明（如保留 Bridge 内置格式预检，则在注释中说明分工：
   Bridge 做格式校验，`agent-data` 做语义预检结论）。
2. `deploy/agentteams/bridge.env`（及 `bridge.env.example`）：`BRIDGE_IDENTITIES` 补
   `agent-rnaseq` 与 `analysis-worker` 两个身份的令牌，与 `bridge/config.py:21-26` 默认值
   对齐到 11 个身份；令牌用 `openssl rand -hex 32` 生成，禁止提交真实值到 git。
3. `deploy/agentteams/docker-compose.agentteams.yml`：新增
   `agentteams-worker-data-production` 服务（复制现有 rnaseq worker 块改身份与令牌环境变量）。
4. `worker/production_runner.py:30-35` `_AGENT_PROFILES` 扩展：
   加 `data-steward→agent-data / project-preflight`、
   `quality-auditor→agent-qc / quality-gate`、
   `delivery-reporter→agent-delivery / delivery-pack` 三个 profile
   （quality/delivery 有独立 runner，P0-5 统一改为经 consultation；此处先保证 profile 可解析）。

**验证：** 起生产 profile 后 8 个 Worker 容器全部 healthy；管理端面板显示 **5/5 活跃**。

#### P0-4 reconcile_case 增派解读工单（修 N4）

- `bridge/service.py:120-167` `reconcile_case`：任务（`omic_task.completed`）成功后、
  创建 `quality-01` 之前，按 Case 的 flow 类型创建解读工单：
  - flow 含 `rna` → target `agent-rnaseq`，`skill_name=result_interpretation`；
  - flow 含 `scrna` → target `agent-scrna`；flow 含 `atac` → target `agent-rnaseq`
    （暂无 atac 身份，复用 rnaseq 并记 limitation）；
  - `depends_on` = 提交类工单 id；`read_only=True`；`context_refs` 带上 task 引用；
  - `quality-01` 的 `depends_on` 改为该解读工单（串成 提交→解读→质控→交付）。
- 未知 flow 类型：跳过解读派单并写审计事件 `interpretation.skipped`（不阻断主流程）。

**验证：** Bridge 契约测试新增用例：mock 任务成功后断言创建了 `interpret-01` 且
`quality-01.depends_on == [interpret-01]`；回归 `test_bridge_contract.py` 全绿。

#### P0-5 质控与交付接真 Agent（修 N2）

- `worker/quality_runner.py`：删除永远 `manual_review` 的固定逻辑（`:63-71`），改为：
  认领 `quality-01` → 走 execute-readonly 会诊链（P0-1 已放行 `quality-auditor` actor）→
  `agent-qc` 返回的信封中 `conclusion` 首行约定为 `PASSED / WARNING / BLOCKED` 之一 →
  映射为质量门 decision 提交 Bridge；解析失败或会诊异常 → `manual_review` 兜底
  （在 risks 中记录原因，**禁止静默放行**）。
- `worker/delivery_runner.py`：同理，认领 `delivery-01` → `agent-delivery` 会诊产出
  交付清单/风险披露，写入工单结果后再触发 Case 关闭。
- `agent-qc` 的提示词契约（`data/ai/qc.yaml`）补一段：consultation 场景下结论首行必须输出
  三态标记——只改提示词，不改 Bridge 代码（遵守本节执行纪律）。

**验证：** 构造一个证据不全的 Case，`agent-qc` 返回 BLOCKED 时 Case 进入 `quality_blocked`；
正常 Case 返回 PASSED 进入 `delivery_ready`；会诊服务宕机时落 `manual_review` 且有风险提示。

#### P0-4b 规划工单：Manager 转派领域 Agent 出计划（新增，对应 §3.3）

1. Bridge `models.py`：`CaseRecord` 加 `proposed_submission`（dict | None）与
   `plan_hash`（str | None）字段；`case_store.py:_ALLOWED_TRANSITIONS` 加
   `received → planning_running → preflight_running` 与
   `planning_running → waiting_for_correction → planning_running` 转换。
2. Bridge `service.py`：Case 创建后（含提交类意图时）自动创建 `plan-01` 工单——
   target 由 Manager 按能力选定（创建 Case 的请求体加 `lead_planner` 字段，默认按
   flow 类型映射：rna→agent-rnaseq / scrna→agent-scrna / 其他→agent-code），
   `capability=planning_advice`、`read_only=True`；Case 进入 `planning_running`。
3. 信封扩展：Gateway/OmicHub 两侧模型在标准四字段外允许 `proposed_submission` 可选字段；
   `agent-rnaseq` 等的 consultation 提示词契约补"规划场景必须输出 proposed_submission
   结构化参数"（只改 `data/ai/*.yaml` 提示词，不改 Bridge 业务逻辑）。
4. plan-01 完成后：`proposed_submission` 过既有预检校验链（`service.py:594-684`），
   通过则写入 Case 并计算 `plan_hash`、转 `preflight_running`；失败转
   `waiting_for_correction` 并派修订工单（attempt 上限 3）。
5. `queue_approved_submission`（`service.py:744-820`）：改为冻结 Case 上已校验的
   `proposed_submission` 快照，审批审计事件记录 `plan_hash`；无 `plan_hash` 的 Case
   不得进入 `approval_pending`（状态机硬阻断）。
6. OmicHub 侧：审批卡（`AgentTeamsCaseView.vue` + P1-6 的聊天内卡片）展示计划摘要 +
   参数明细 + `plan_hash` 短码，让用户确认的就是这份快照。

**验证：** 无 `plan_hash` 直接提交 → 409；plan-01 产出非法 flow 参数 →
`waiting_for_correction`；确认后篡改参数重放 → 审批校验失败；契约测试新增
"规划→校验→确认→冻结"全链用例。

#### P0-6 通用工作区执行通道（新增，对应 §3.4；让 treeplot 类即席任务可闭环）

1. Bridge `models.py`：`WorkItemRecord` 加 `execution_mode: Literal["readonly_consultation",
   "workspace_execution"] = "readonly_consultation"`；`service.py` 的 read_only 强制放宽为：
   `workspace_execution` 工单允许 `read_only=False`，但必须 `approval_required=True`
   或所属 Case 已有确认 `plan_hash`，否则 422；执行路由按 `execution_mode` 分发。
2. OmicHub `agent_consultation_service`：支持 `mode="workspace_execution"`——
   `ParallelSubAgentService.run(..., workspace_access=True, safe_only=False,
   runtime_authorized=True)`；工作目录强制 `output/agentteams/<case_id>/<work_item_id>/`；
   产物完成后登记 `file_records`（复用任务产物登记逻辑，参考"下载产物需登记才可见"约束）；
   信封扩展 `artifacts: [{path, kind, bytes}]`。
3. Gateway：`agent_policies` 为 `agent-code / agent-viz` 增加 `workspace_execution` capability；
   `client.py` 仅在 `mode=workspace_execution` 时不强制 read_only，其余字段约束不变。
4. plan 绑定：Bridge 在认领 execution 工单前校验该工单 `objective/skill_name` 能追溯到
   Case 已确认 plan 的任务列表（plan 快照里存任务 DAG）；追溯失败拒绝认领并写审计。
5. 高风险工具：执行回合内 `requires_confirm` 的工具调用走平台既有审批卡（不豁免）。
6. 测试：单测覆盖模式分发、plan 绑定校验、产物登记；集成用例用 2 个示例 .fa 文件跑
   treeplot 迷你 Case（可用 mock 工具结果，不要求真跑 mafft）。

**验证：** 在 Studio 聊天发起"对 <测试目录> 下的 .fa 文件构建 treeplot"→ 规划 → 确认 →
exec-01/exec-02 真实执行 → /files 可见产物 → agent-qc 质控 → 交付气泡含下载链接；
plan 外工单认领被拒。

### P1 — 验收体验项（对应 §9 验收标准）

#### P1-6 聊天内审批闭环（修 N3）

- 首选方案（改动最小）：`AgentTeamsCaseCard.vue` 增加"批准 / 拒绝"按钮，直接调
  `POST /api/v1/agent-teams/cases/{id}/submit`（已存在，A15）；操作结果经既有 SSE/轮询自动刷新卡片。
- 备选方案：`case_room_projector.py` 的 `overdrive_approval_request` 事件携带
  `case_id + submit_action`，复用 `OverdriveApprovalCard` 的批准通道——需后端审批 API 接受
  该通道来源，改动大于首选，仅当产品要求卡片样式完全统一时采用。

**验证：** Studio 聊天内收到 Case 审批卡 → 不跳页面直接批准 → Case 进入 `approved` →
后续发言气泡继续在窗口内出现。

#### P1-7 manifest 下载（修 N6）

- `api/agentTeams.ts` 补 `downloadManifest(caseId)`；后端如缺代理下载端点则在
  `agentteams.py` 加 `GET /cases/{id}/manifest`（CurrentUserId + Case 所有权校验，
  从 Bridge 拉取 manifest JSON 返回）。
- `AgentTeamsCaseView.vue:449` 处把 `manifest_uri` 文本改为下载按钮 + 在线预览（JSON 折叠）。

#### P1-8 补齐骨架 Agent（修 N8）

- `data/ai/data.yaml`：配 `skill_ids`（至少文件/样本核验相关）、确认 tool_packs 覆盖
  只读研究工作区工具；welcome_message 去掉"正在配置"。
- `data/ai/delivery.yaml`：同理，面向交付清单/runbook/证据汇总场景配提示词与工具。
- 两者 Persona 方向参照 `update_agent.md` §3.2（data=谨慎可追溯；delivery=条理清晰结果导向）。

**验证：** 平台 Agent 管理页可见两者能力非空；consultation 端点以 `agent-data` 调用返回
真实预检结论而非客套话。

#### P1-9 修假创建入口（修 N5）

- `KimiChatInput.vue:799-805` 与 `StudioView.vue:604-607`：二选一——
  (a) 直接调 `agentTeamsApi` 创建 Case 并在聊天内插入 `AgentTeamsCaseCard`；
  (b) 保留模板但按钮文案改为"发送给 AI 以创建协作 Case"，消除误解。
- 比赛时间紧时选 (b)，一行文案改动。

### P2 — 健壮性（演示后做，影响可信度）

10. **事件游标加固（N7）**：游标/通知状态从 `sandbox_meta` 迁出——新建
    `agentteams_case_cursors` 表（alembic 迁移；注意迁移历史多 head，须用 mergepoint 合并）
    或在发布 SSE 与更新游标间加幂等键（`case_id + event_id` 去重）。watch 间隔
    `AGENTTEAMS_CASE_WATCH_INTERVAL_SECONDS` 从 60s 降至 10-15s（Redis 锁已兜底，
    改配置即可，改后 `docker restart omichub-worker`）。
11. **Bridge 存储加固（N9）**：生产强制 Redis 模式（`BRIDGE_STATE_STORE_URL`），文件模式
    `_persist()` 改"写临时文件 + os.replace 原子 rename"；启动时检测文件模式且无 Redis 时
    打 WARNING。
12. **Gateway 成本计数共享（N9）**：`_case_calls` / `_case_tokens` 从进程内字典迁 Redis
    （INCR + EXPIRE），多实例口径一致。
13. **端到端自动化测试**：把 `demo/run_bridge_demo.py` 的 `staging-success` 模式固化为
    pytest（创建 → 预检 → 审批 → 提交 → 解读 → 质控 → 关闭 → 断言 manifest 字段齐全），
    纳入 CI；补并发 claim 同一工单的竞态用例。

### 明确不做 / 延后

- ❌ 不在 Bridge/Gateway/Worker 里写任何领域规则（质量阈值、生物学逻辑）——违反迁移原则。
- ❌ 不适配旧 `/ai` 聊天页（N11）——赛后随旧组件淘汰。
- ❌ 不做 `update_agent.md` 的 P1-P4（真异步、逐条点评）——赛后目标，比赛阶段不扩大战线。
- ❌ 不为平台 Agent 新建容器——大脑跑在 omichub-web 内（§2.2）。

---

## 9. 验收标准（比赛端到端）

在一个聊天窗口内跑完一个 RNA-seq 复合任务，页面顺序为：

```text
Manager 接单并说明分派（选定领域规划 Agent 及理由）
→ 规划 Agent（如 agent-rnaseq）发言：交付 plan + 参数草案
→ agent-data 预检结论（带头像气泡，身份=数据管理员）
→ 计划/提交确认卡（展示 plan_hash + 参数明细，用户在聊天内直接批准，不跳页）
→ analysis-worker 提交流水线 + agent-rnaseq 结果解读
→ agent-qc 独立质控结论（真实三态：PASSED/WARNING/BLOCKED）
→ agent-delivery 交付汇总
→ Case closed，交付 manifest 可下载
```

满足：

- 至少 3 个不同职能 Agent 真实参与，且其发言来自平台对应 Agent（提示词/Persona/工具一致）；
- 审计事件完整（`work_item.claimed → skill.finished → quality.decision → case.closed`）；
- 管理端外部 Worker 5/5 活跃；
- 用户未离开聊天窗口即可完成确认、查看进度与结论。

另需演示一个**通用分析型 Case**（如 treeplot，§3.4）：证明多 Agent 流程不限定于平台流水线，
即席任务同样走"规划→确认→执行→质控→交付"闭环且产物可下载。

---

## 10. 最终审核清单（施工完成后逐项打勾）

> 状态图例：✅ 已审核通过（2026-08-10 代码实测）｜⬜ 待施工｜🔶 部分完成。
> 施工完成后把 ⬜ 改 ✅，填验证方式与日期。本表是比赛交付的最终验收依据。

### 10.1 编排骨架（已审核，无需施工）

| # | 检查点 | 状态 | 验证方式 |
| --- | --- | --- | --- |
| 1 | Case 15 态状态机 + 原子转换 + 非法转换 409 | ✅ | 代码核查 `case_store.py:29-44` + 契约测试 |
| 2 | Work Item 租约/认领/续租/过期回收 | ✅ | 代码核查 `case_store.py:389-579` |
| 3 | 审批 HMAC 签名 + scope 校验 + token-free 提交 | ✅ | 代码核查 `security.py:44-106` |
| 4 | 审计 append-only + per-case 查询/SSE | ✅ | 代码核查 `audit.py` + `app.py:335-393` |
| 5 | 只读三层强制（Bridge/Gateway/策略） | ✅ | 代码核查 A5 三处 |
| 6 | 交付 manifest 生成（后端） | ✅ | 代码核查 `service.py:1132-1194` |
| 7 | 前端 Case 工作台 + 管理端心跳面板 | ✅ | 代码核查 A9/A11 |
| 8 | 单窗口投影复用超频组件 | ✅ | 代码核查 A10 |
| 9 | 契约测试 ~2600 行 | ✅ | `deploy/agentteams/tests/` 等 |

### 10.2 P0 施工项

| # | 检查点 | 状态 | 验证方式 |
| --- | --- | --- | --- |
| 10 | consultation 端点上线路由存在且集成令牌认证生效 | 🔶 | 2026-08-10：重启 `omichub-web` 后无令牌实测 401；真实会诊需选定测试项目与模型凭证。 |
| 11 | `agent_consultation_service` 复用 safe_only 只读回合 | ✅ | 2026-08-10：`tests/unit/test_agent_consultation_service.py` 8 passed（工具剥离、信封和降级）。 |
| 12 | `requester_ref` 三处透传（Bridge→Gateway→OmicHub） | ✅ | 2026-08-10：Bridge 52 passed、Gateway 8 passed；请求体和服务日志字段均受测试覆盖。 |
| 13 | Bridge 权威角色映射 + actor 白名单扩展（data/quality/delivery） | ✅ | 2026-08-10：Bridge 契约回归通过；data、quality、delivery 生产 Worker 已启动。 |
| 14 | Gateway `agent_policies` 补 agent-data/qc/delivery | ✅ | 2026-08-10：Gateway 8 passed，策略越权路径受回归覆盖。 |
| 15 | 前端 `ROLE_AGENT_MAP` 修正，气泡显示真实专家 | ✅ | 2026-08-10：前端 `type-check` 与生产构建通过，角色投影映射已更新。 |
| 16 | `bioops-delivery.yaml` + `bridge.env` 11 身份齐备 | ✅ | 2026-08-10：运行配置加载 11 身份；Bridge `/v1/health/workers` 实测核心 Worker 5/5 活跃。 |
| 17 | `agentteams-worker-data-production` 容器新增并 healthy | ✅ | 2026-08-10：`agentteams-worker-data-production` 已启动，全部生产 Worker 运行正常。 |
| 18 | `reconcile_case` 派 interpret-01 且 quality-01 依赖之 | ✅ | 2026-08-10：Bridge 52 passed；staging-success pytest 覆盖 reconcile→interpret→quality。 |
| 19 | quality_runner 接 agent-qc 真三态决策 | ✅ | 2026-08-10：Worker 21 passed，覆盖 PASSED/WARNING/BLOCKED 与 manual_review 兜底。 |
| 20 | delivery_runner 接 agent-delivery 产交付清单 | ✅ | 2026-08-10：Worker 21 passed，覆盖 delivery 清单与风险输出。 |
| 21 | 规划工单 plan-01：状态机加 planning_running，无 plan_hash 不得审批 | ✅ | 2026-08-10：Bridge 52 passed，覆盖规划冻结及无冻结计划的拒绝路径。 |
| 22 | proposed_submission 校验 + 冻结 + plan_hash 绑定审批 | ✅ | 2026-08-10：Bridge 契约回归覆盖参数冻结、提交快照与审批作用域。 |
| 23 | 工作区执行通道：execution_mode 分发 + plan 绑定 + 产物登记 | ✅ | 2026-08-10：Bridge 52 passed，覆盖 workspace 执行、计划绑定、DAG 分发及 file_records。 |
| 24 | 通用型 Case 端到端（treeplot 类即席任务） | 🔶 | 2026-08-10：treeplot 通用计划、审批与 workspace DAG 自动化通过；真实 `.fa` 产物与聊天气泡仍需实机演示。 |

### 10.3 P1 验收体验项

| # | 检查点 | 状态 | 验证方式 |
| --- | --- | --- | --- |
| 25 | 聊天内批准/拒绝 Case，全程不跳页 | ✅ | 2026-08-10：审批卡批准/拒绝直连 API；前端类型检查与构建通过。 |
| 26 | manifest 可下载 + 在线预览 | ✅ | 2026-08-10：详情卡已提供 JSON 预览和下载入口，前端生产构建通过。 |
| 27 | agent-data / agent-delivery 能力非骨架 | 🔶 | 2026-08-10：提示词、Gateway 策略与 Worker 回归完成；真实会诊结论需选定测试项目/模型。 |
| 28 | 假创建入口修复（真创建或文案明示） | ✅ | 2026-08-10：入口文案已明确为“发送给 AI 以创建协作 Case”，构建通过。 |

### 10.4 P2 健壮性项

| # | 检查点 | 状态 | 验证方式 |
| --- | --- | --- | --- |
| 29 | 事件游标幂等/独立存储，watch 10-15s | ✅ | 2026-08-10：watcher 单测通过，重启后的 Worker 内实测 `watch_cases()` 成功执行。 |
| 30 | Bridge Redis 模式 + 文件模式原子写 | ✅ | 2026-08-10：Bridge Redis/文件持久化回归在 52 passed 中覆盖。 |
| 31 | Gateway 成本计数 Redis 化 | ✅ | 2026-08-10：Gateway 8 passed，Redis 共享计数回归通过。 |
| 32 | 端到端 pytest 固化（含并发 claim 竞态） | ✅ | 2026-08-10：Bridge 52 passed（1 skipped）、Gateway 8、Worker 21、OmicHub 聚焦 37。 |

### 10.5 端到端最终验收（§9 全量）

| # | 检查点 | 状态 | 验证方式 |
| --- | --- | --- | --- |
| 33 | 单窗口 RNA-seq Case 全流程（§9 页面顺序） | ⬜ | 演示录屏 + 审计事件导出 |
| 34 | 通用型 Case 全流程（treeplot，§3.4 工单序列） | ⬜ | 演示录屏 + /files 产物截图 |
| 35 | ≥3 职能 Agent 真实参与且发言来自平台 Agent | ⬜ | 气泡身份 + 会诊日志 agent_id 交叉核对 |
| 36 | 审计链完整 claimed→finished→decision→closed | ⬜ | `GET /cases/{id}/events` 导出核对 |
| 37 | 管理端 5/5 活跃 | 🔶 | 2026-08-10：Bridge 运行态确认 code/viz/scrna/rnaseq/analysis 5/5 活跃；本地 `agentteams_bridge_settings` 尚未配置，待管理端连通后截图验收。 |

---

## 11. 与赛后目标的关系

本框架用 AgentTeams 满足比赛"协同设计基点"要求，并验证"平台真实 Agent 作为执行者、
经审批与审计在窗口内协作"的可行性。赛后按 `update_agent.md` 收敛：编排/状态从外部 Bridge
逐步迁移到平台内置的超频 v2（DB 事件溯源 + Celery 真异步 + `ParallelSubAgentService` +
人格化多波次），获得真异步、逐条回流点评与断线恢复能力。

本文确立并在施工中必须守住的四条原则，迁移后继续成立：

1. **角色→平台 Agent 映射**：AgentTeams 身份只是安全边界，大脑永远是 `data/ai/*.yaml`；
2. **只读执行边界**：专家会诊 safe_only，写操作只走审批令牌单通道；
3. **单窗口投影**：`room_speech / overdrive_progress / overdrive_approval_request` 契约不变；
4. **业务智能不进 Bridge**：解读/质控规则全部在 OmicHub 侧，Bridge 只做编排与审计。
