# CygnusX「协作室」（AgentTeams Room）框架：最终架构（2026-08 升级后）

> 初稿调研：2026-08-20；**本文档已于 2026-08-21 重写为升级后的最终框架**，并于同日经
> L4 愿景符合度审查 + 审查修复（安全止血/工程地基/正确性加固）后回写状态口径。
> 升级依据：`docs/info/26.8.21/协作室架构升级方案-MinIO持久化与Case解耦及L4前置收尾.md`。
> **状态口径（四档制）**：本文所述全部改动当前处于**「代码就绪」**档（工作树内、单测/契约测试绿），
> 尚未分组提交、未经真实服务 e2e 验证、未上线——四档 = 代码就绪 → 已提交 → 已验证 → 已上线，
> 逐项状态见第八节与第十节。审查与修复证据：
> `docs/info/26.8.21/协作室L4愿景符合度审查报告-2026-08-21.md`、
> `docs/info/26.8.21/协作室L4审查修复与优化实施手册.md`。
> 数据来源：代码实读 + 设计/事故文档，非单一文档转述。

---

## 一、定位与愿景

协作室是平台分层愿景（L1–L4）中的 **L4 = 多智能体团队协作室**：用户扮演"甲方"提需求，Manager 接单、澄清、组队、审批、整合交付，模拟一个生物信息分析部门的项目群，而不是单轮模型调用。组织模型为：

- **用户 = 甲方**
- **Manager（bioops-manager）= 客户经理/项目协调人** —— 对外单一责任人，编排者而非执行者（`recruitable: false`、只做只读会诊）
- **领域 Agent（agent-rnaseq / atacseq / scrna / data / qc / delivery 等）= 部门负责人**
- **Worker = 岗位下的执行员工**（一个 Agent 可派生多个并行 Worker）

核心原则：人和岗位分离、群聊式沟通 + 工作流式执行、先冻结计划再理解变更、**真实计算必须人工审批**（不可旁路）。

**2026-08-21 升级后的核心形态变化**：

1. **房间是持久的轻量会话实体，Case 是"经用户确认执行"才创建的正式工单**（会话-工单解耦，见第四节）。
2. **Bridge 容器无状态化**：MinIO 是事实源，Redis 只是热缓存/分布式锁，本地 JSON 文件废除（见第五节）。
3. **L4 四个前置条件的代码全部就绪**：地基修复、L2→L4 升级规则、双注册表统一、统一审计总线（见第八节，状态按四档制标注）。

## 二、整体进程拓扑（三层 + 外部 Worker）

```
浏览器前端
   │ （只接触主后端，永远不接触 Bridge/Gateway 凭证）
   ▼
CygnusX 主后端 (FastAPI + Celery + Redis + PG + MinIO)
   │  httpx 代理 + 四身份令牌
   ▼
AgentTeams Bridge (integrations/agentteams/bridge/)   ← 独立部署、无状态 FastAPI 服务
   │  Case 状态机 + 审计事件流
   ├── 事实源：MinIO（bucket: agentteams，事件流 + 状态快照）
   └── 热缓存/分布式锁：Redis
   ▼
Matrix Gateway (integrations/agentteams/gateway/)     ← 独立部署，双职能：
   │     ① 会诊策略护栏（调用/成本限额）② Matrix 密钥隔离
   ▼
Matrix/Element（房间镜像，可选 iframe 嵌入）
外部 Worker（integrations/agentteams/worker/）轮询 claim 工作项，执行真实计算
```

关键架构特征：

- **房间实体化**：主库新增 `agentteams_rooms` 表（room_id/title/owner/case_id 可空/origin/origin_ref/时间戳），房间先于 Case 存在；纯聊天阶段事件落 Bridge **房间命名空间事件流**（`room-<room_id>` 命名空间记录，`record_kind="room_namespace"`），不进用户 Case 列表/配额/GC/指标。
- **协作室业务状态的事实源在 MinIO**：Case 状态快照与审计事件流全部对象化到 MinIO `agentteams` bucket；Bridge 容器重建后零状态损失。主库表只存游标（`agentteams_case_cursors`）、配置（`agentteams_bridge_settings`）与房间元数据（`agentteams_rooms`）。
- **Matrix 房间只是镜像**：Bridge 的 `AuditRoomMirror` 正向把 `room.*` 事件镜像进 Matrix；`agentteams_room_sync_service.py` 反向把 Element 侧发言回投，双向防回声（`via=matrix` 标记）。房间命名空间消息的 Matrix 回投改派 `respond_to_room_namespace_message` 任务。
- Bridge 是**完全独立的服务**（不 import CygnusX 任何代码），自带 16 态 Case 状态机（`queued→received→planning_running→…→delivery_ready→closed`）+ Work Item 状态机（租约 claim、重试预算、审批信封）。

## 三、后端核心模块清单

### API 层

- `src/cygnusx/api/v1/agentteams.py`（挂 `prefix="/agent-teams"`）：三类端点
  - 集成端点（`X-Integration-Token` 认证，供 Gateway 回调）：`GET /capabilities`、`POST /consultations/scientific-interpretation`
  - **房间端点（2026-08-21 新增，`CurrentUserId` 认证 + owner 归属校验）**：`POST /rooms`（建房即供给 Matrix 房间，**不建 Case**）、`GET /rooms` / `GET /rooms/{id}`、`POST /rooms/{id}/messages`、`POST /rooms/{id}/confirm-proposal`（立项确认/修改/取消）、`GET /rooms/{id}/events`（复合游标 `ns:<id>|case:<id>` 双流归并分页）、`GET /rooms/{id}/events/stream`（SSE）
  - 用户端点（Case 级，旧路径保留兼容）：Case CRUD、审批/修订/变更决策、`POST /cases/{id}/messages`、`GET /cases/{id}/events[ /stream]`、产物受控读取、`GET /cases/{id}/audit-chain`（**审计链统一查询入口，新增**）、`GET /role-labels`、`GET /status`
- `src/cygnusx/api/v1/chat.py`：新增 `POST /sessions/{session_id}/agentteams-upgrade`（L2→L4 升级决策 accept/dismiss）
- `src/cygnusx/api/v1/admin/agentteams_bridge.py`：管理员配置 Bridge 接入（URL + 四个身份令牌，加密落库）

### Application 服务层（`src/cygnusx/application/services/`）

| 文件 | 职责 |
|---|---|
| `agentteams_service.py`（`AgentTeamsService`） | Bridge 的 httpx 客户端适配器：Case 生命周期代理；四身份令牌管理；`provision_case_room` 建 Matrix 房间；`create_room_namespace()` 建房间命名空间记录；`bind_case_room()` 立项后绑定房间与 Case；`source_case_id` 透传（followup 关联上一 Case） |
| `agentteams_room_service.py`（**新增**） | 房间实体 CRUD（主库 `agentteams_rooms`）、归属校验、房间消息、复合游标事件聚合、有界 SSE、`confirm_proposal` 原子消费一次性 token；`build_room_proposal`/`persist_room_proposal` 立项卡构造 |
| `agentteams_room_response_service.py` | **房间消息响应回路核心**：Redis 互斥锁 + 幂等去重；意图分类（chat/clarify/execute/tool_execute）→ `respond_room()` 按房间绑定态分流（未立项走命名空间、已立项走 Case）；`_emit_case_proposal` 立项确认卡；终态后 EXECUTE 出 followup 卡（继续关联/新建工单）；correlation 字段（causation_event_id / answer_to_event_id）落事件 |
| `agent_consultation_service.py` | **会诊执行内核**：组装上下文 → 硬性门禁 → `ParallelSubAgentService.run`（LangGraph ReAct，`safe_only` 只读）→ 结构化信封 `ConsultationEnvelope`；`_BridgeEvidenceProjector` 投影工具调用证据 |
| `agentteams_capability_registry.py` | **单一权威能力目录**（2026-08-21 统一）：从 `data/ai/*.yaml` 派生运行时快照（60s TTL 单例缓存）；`snapshot()` 新增 `chat_router_catalog` / `flow_router_catalog` / `registered_agent_ids`，chat LLM 路由与房间关键词路由共用同一快照源 |
| `agentteams_upgrade_advisor.py`（**新增**） | L2→L4 升级触发器与编排：三条规则（显式请求必升 / Flow 步骤数≥3 / `requires_formal_delivery` 标记）+ 咨询否决词抑制；建议卡构造、上下文摘要（context_refs 协议路径 + 预检）；`AgentTeamsUpgradeService` accept/dismiss 编排；OTel counter `agentteams.upgrade.events` |
| `agentteams_audit_events.py`（**新增**） | 审计事件分级一处显式定义：`OPERATIONAL_EVENT_TYPES`（与 Bridge 同口径互注同步）、`RETAINED_HIGH_FREQUENCY_BUSINESS_TYPES` 白名单、`classify_event_type` / `extract_correlation` |
| `agentteams_audit_chain_service.py`（**新增**） | audit-chain 聚合：Case 流 + 绑定房间命名空间流合并去重、按 recorded_at 排序、`broken_links` 断链检测；用户态归属校验入口 + 运维态 manager 入口 |
| `agentteams_usage_service.py` | 会诊 token 用量写入合成系统会话，按 `ai_token_cookie_rate` 扣饼干（message_id 幂等） |
| `agentteams_case_watch_service.py` | beat 驱动：监视绑定 Case 的聊天会话，状态变化写系统通知；终态停止监视 |
| `agentteams_case_event_consumer_service.py` | 每绑定 Case 维护有界 Bridge SSE 消费，经 `CaseRoomProjector` + Redis pub/sub 推到聊天前端 |
| `agentteams_room_gateway_service.py` | Matrix Gateway 纯 HTTP 客户端（建房 / ensure_users / 发消息 / SSE sync） |
| `agentteams_room_sync_service.py` | Matrix→平台反向同步；`room-` 前缀 case_id 的回投改派房间命名空间响应任务 |
| `agentteams_intent_router.py` / `agentteams_route_decision.py` | 聊天意图→Flow 关键词路由（trigger_hints 来自 flows YAML）；**路由目标校验注册表成员资格**，未登记降级统一 fallback 并记审计日志 |
| `agentteams_mention_resolver.py` | 房间 @ 解析（manager / broadcast / 具体 agent），输出 `dispatch_mode` |
| `agentteams_quality_gate_service.py` | 确定性质量门禁：按 flow YAML `delivery.thresholds` 评估，先于 LLM 评审 |
| `agentteams_bridge_settings_service.py` | Bridge 配置 DB 持久化，令牌加密落库 |

### 异步任务层

`src/cygnusx/infrastructure/celery_app/tasks/agentteams.py`：

- `respond_to_room_message`（Case 房间）与 `respond_to_room_namespace_message`（**新增**，未立项房间）→ `AgentTeamsRoomResponseService.respond` / `respond_room`
- beat 周期任务：`watch_cases`、`consume_case_events`、`sync_case_rooms`、`requeue_stale_tasks`、`reconcile_approval_timeouts`、`cleanup_evidence`，全部用 Redis 分布式锁防多 worker 并发

### 独立部署组件（`integrations/agentteams/`）

- **`bridge/`**（独立 FastAPI 服务，不 import CygnusX 任何代码，**2026-08-21 起无状态化**）：
  - `app.py`：全部 REST 端点；`/healthz` 增加 `minio_enabled/minio_reachable/minio_last_write_latency_ms`
  - `service.py`（`BridgeService`）：Case 状态机、Work Item 租约、审批信封、质量门禁、交付 manifest；`create_case` 分流 `_create_room_namespace`（房间命名空间记录不排队、不转 planning、不进用户 Case 列表/配额/GC/指标）
  - `minio_store.py`（**新增**，MinIO 适配层）：事件流 append（读-改-写尾卷 + per-case asyncio 锁，超 50MB 按天分卷）、快照 envelope（version/case_id/saved_at/last_event_id/case）、启动恢复（读快照→校验 last_event_id→重放增量，任何失败拒绝启动）
  - `case_store.py`：MinIO 模式从 MinIO 恢复（fail fast）、`_persist` 逐 case 写快照（内嵌 last_event_id）后再更新 Redis 热缓存；本地 JSON 路径废除
  - `audit.py`（`AuditStore`）：写入顺序硬约束 **MinIO 落盘 → Redis 热缓存 → 内存索引 → `_notify`（mirror/SSE）**；`OPERATIONAL_EVENT_TYPES = {worker.inbox_polled, worker.heartbeat, room.typing}` 拦截为 Redis 指标计数；`metrics()` 暴露 operational 聚合计数
  - `migrate_to_minio.py`（**新增**）：一次性迁移 CLI（本地 JSON → MinIO → 逐 case 对账，不平非零退出）
  - `room_mirror.py`（`AuditRoomMirror`）：`room.*` 事件镜像进 Matrix（防回声、截断、瞬态事件跳过）
- **`gateway/`**（独立 FastAPI 服务，双职能）：会诊网关（策略校验、按 case 护栏 → 回呼主后端）+ Matrix 网关（密钥隔离）
- **`worker/`**：外部 Worker 轮询——claim → 只读项走会诊回呼；写操作项必须人工审批后由 `analysis-worker` 提交
- **`teams/bioops-delivery.yaml`**：纯描述性文档；运行时事实源是 `data/ai/*.yaml`
- **`skills/contracts.yaml`**：skill→Bridge 端点的稳定契约

## 四、会话-工单解耦（Case 按需创建，2026-08-21 落地）

**核心：房间是持久的轻量会话实体；Case 是房间内"经用户确认执行"才创建的正式工单对象。**

1. **房间实体化**：主库 `agentteams_rooms` 表（room_id/title/owner/case_id 可空/origin/origin_ref/created_at/updated_at，迁移 `t3u4v5w6x7y8` + `u4v5w6x7y8z9`）。Bridge 侧用**命名空间方案**承载房间级事件流：`room-<room_id>` 的 `record_kind="room_namespace"` 记录，完整复用 Case 的事件流/MinIO 持久化/恢复/SSE/镜像链路，靠 `record_kind` + `room-` 前缀双重过滤隔离于用户 Case。
2. **Case 创建时机后移**：
   - 意图 chat/clarify → 只对话（澄清问答全部发生在房间维度），不创建 Case；
   - 意图 execute → Manager 先落 `room.proposal_confirm` **立项确认卡**（payload：objective/flow_id/participants/estimated_stages/route_path/confidence/context_refs/options），用户确认（`POST /rooms/{id}/confirm-proposal`，owner 校验 + pending 状态原子消费、幂等、失败回滚 pending）后才创建 Case 并回写房间绑定（`room.case_bound` 事件带 `answer_to_event_id` 指回立项卡）。**confirm_token 口径（08-21 复审 B1 闭环）**：token 只存服务端（房间行 DB 字段 + 事实源事件内部），写入后全出口（Bridge/主后端分页、SSE、audit-chain、Matrix 镜像）一律脱敏；确认请求可不带 token（owner 身份即授权边界），带 token 则强制比对（API 级防重放 nonce）。
   - **participants[] 的来源口径（08-21 复审 B3 注明）**：立项卡的 participants/estimated_stages/route_path 来自 flow YAML 静态声明的关键词路由命中结果（`agentteams_route_decision.py` 只读观察），**Manager LLM 当前不做选专家决策**；Manager 真实组队属愿景深化项（手册阶段 3 已登记）。
3. **五步进度条按 Case 存在性渲染**（前端）：无 Case → 轻量会话头（房间标题 + "尚未立项"引导）；有 Case → 现有五段步骤条（`buildAgentTeamsStageView` 纯函数抽出）。
4. **终态后再发言**：Case closed/delivery_ready/cancelled 后房间可继续对话；新 execute 意图 → followup 立项卡（"基于上一 Case 的交付继续（source_case_id 关联引用）/ 新建工单 / 取消"）。
5. **兼容**：历史"发言即 Case"数据与旧路径（`POST /cases` 直建 + `/cases/{id}/messages`）保持可用、只读正常；前端投影层对 room 级与 case 级事件统一渲染（`projectCaseEvents` 同一入口，`applyProposalOutcomes` 消费确认卡）。
6. **四件事的保留**：审批/质控/契约/审计全部只在 Case 存在后激活——它们本来就是工单级语义，松绑不影响其完整性。

**立项确认卡事件契约**（`room.proposal_confirm`，房间命名空间事件流）：

```
payload = {agent_id, role, causation_event_id,
           proposal_kind: "new_case" | "followup",
           confirm_token,            # 一次性令牌：仅服务端留存与校验，所有读出口（分页/SSE/audit-chain/Matrix）一律脱敏为 null
           status: "pending",
           objective, flow_id, flow_label, lead_planner, route_path,
           participants[],           # 现状口径：flow YAML 静态声明 + 关键词路由命中，非 Manager LLM 组队决策
           estimated_stages[], confidence,
           origin_content, context_refs[], source_case_id,
           options,                  # new_case: confirm/modify/cancel；followup: continue/new/cancel
           created_at}
```

## 五、持久层：MinIO 化（2026-08-21 落地）

**原则：MinIO 是事实源，Redis 只是热缓存/分布式锁，本地 JSON 文件废除。**

- **对象布局**（bucket `agentteams`，`minio-init` 已加建）：
  - `cases/{case_id}/events/audit.jsonl` —— 事件流首卷；单对象超 50MB（`BRIDGE_MINIO_EVENT_OBJECT_MAX_BYTES`）按天滚卷 `audit-YYYYMMDD.jsonl`（同日多卷 `-N` 后缀）；读取按"首卷优先、分卷字典序"还原时间序
  - `cases/{case_id}/snapshot.json` —— 状态快照 envelope `{version, case_id, saved_at, last_event_id, case}`；每次状态迁移写一次（"状态迁移或每 200 事件"的超集）。**快照粒度口径（08-21 复审 B2 澄清）**：每个 snapshot.json 始终是**单 case 的完整 envelope**（非部分字段）；"增量写"指 `_persist` 每次只重写**本次变更 case** 的快照对象（替代原 O(N) 全量逐 case PUT 的写放大），恢复语义不变——逐 case 读最新快照 → 校验 last_event_id → 重放增量事件。
- **写入顺序硬约束**：MinIO 落盘成功 → Redis 热缓存（XADD/快照，失败仅告警）→ 内存索引 → `_notify`（room mirror / SSE 拉取源）。MinIO 写失败即操作失败，禁止"先缓存后补写"、禁止幽灵成功态。CaseStore 为 **persist-then-commit**：`_persist(changed=..., removed=...)` 先写快照成功才提交内存态，写失败抛错且内存不推进（23 处 mutating 调用点全部顺序反转）。
- **启动恢复**：读最新快照 → 校验 last_event_id 与事件流连续性（marker 非空则必须存在于事件流；marker=None 或落后于流尾是先快照后事件的合法瞬时态）→ 重放增量。任何读取/解析/校验失败 = 结构化告警 + 拒绝启动（fail fast）。
- **append 实现**：S3 无原生 append → 读-改-写尾卷 + per-case asyncio 锁；`record()` 返回前必须已落盘。
- **噪音治理**：operational 事件（`worker.inbox_polled / worker.heartbeat / room.typing`）不进 MinIO 事件流，只 `INCR <prefix>:metrics:events:{type}`（无 Redis 时进程内计数）；`metrics()` 暴露聚合计数供监控面板。
- **配置**：`BRIDGE_MINIO_ENDPOINT / ACCESS_KEY / SECRET_KEY / BUCKET(默认 agentteams) / SECURE(false)`；生产校验器强制 endpoint 非空；未配置时非生产回退旧模式并打 warning。compose 已接线（bridge 服务注入 `BRIDGE_MINIO_*`，endpoint `http://minio:9000`，凭证引用 `MINIO_ROOT_USER/PASSWORD`）。
- **迁移**：`python -m cygnusx_agentteams_bridge.migrate_to_minio` 一次性迁移既有本地 JSON → MinIO，逐 case 对账（事件数不平非零退出），旧文件保留人工归档。

## 六、消息流转全链路（升级后）

完全异步，HTTP 只负责落事件：

1. **未立项房间**：`POST /rooms/{id}/messages` → 落 `room.user_message`（房间命名空间流）→ Celery `respond_to_room_namespace_message` → `respond_room()`：
   - chat/clarify → Manager 对话 / 澄清卡（房间维度，无 Case）
   - execute → 路由 + `_emit_case_proposal` 立项确认卡
   - 用户确认 → `confirm_proposal` → `create_case`（Bridge）→ `bind_case_room` → 房间进入工单态
2. **已立项房间 / 旧 Case 路径**：`POST /cases/{id}/messages` → @ 解析、`client_message_id` 幂等 → 落 `room.user_message` → `respond_to_room_message` → 意图四态分派（execute → `room.route_decision` 决策卡 + `plan-01` 只读规划工作项；clarify → `room.ask_user`，最多 2 轮；tool_execute → 只读工具直跑；否则 Manager 会诊）
3. 会诊内核 `AgentConsultationService.run_consultation` → `ParallelSubAgentService.run`（safe_only）→ 增量落 `room.agent_stream`（打字机）→ 结论落 `room.agent_message`（带 causation_event_id）
4. **回推前端**：房间页走 `/rooms/{id}/events[ /stream]`（复合游标双流归并）；旧 Case 页走 `/cases/{id}/events/stream`；beat `consume_case_events` 经 Redis pub/sub 投影到聊天会话
5. **真实执行链路**：外部 Worker 轮询 claim → 只读项经 Gateway 护栏回呼会诊；写操作必须人工审批（`approval-authority` 签短时 scoped token）→ 提交平台既有 task

## 七、前端架构（升级后）

- 主页面 `frontend/src/views/AgentTeamsRoomView.vue`：**双模式**——房间模式（`selectedRoomId`，新默认：createRoom → postRoomMessage → 复合游标分页 + SSE）与旧 Case 详情模式（保留）；侧栏房间/Case 统一条目（boundCaseIds 去重）
- **五步进度条条件渲染**：`buildAgentTeamsStageView`（`utils/agentTeamsStatus.ts` 纯函数）——房间未绑 Case 返回 null，渲染轻量会话头；绑定后平滑切换进度条
- **立项确认卡组件** `components/agent-teams/RoomProposalCard.vue`：pending 时 new_case 渲染确认/修改/取消、followup 渲染继续/新建/取消；modify 回填 origin_content 到输入框；已消费渲染只读结果态
- **两级纯函数投影**（`utils/agentTeamsRoom.ts`）：`projectCaseEvents()` 统一投影 room 级与 case 级事件（新增 `room.proposal_confirm` / `room.case_bound` / `proposal_modify_requested` / `proposal_cancelled` 分支），`groupRoomMessages()` 聚合同前
- **同步三重保障**：fetch-based SSE（指数退避重连）+ 20s 可见性轮询兜底 + 发送乐观更新（event_id 对账）；复合游标只能由分页响应推进，SSE 重连重叠靠 event_id 去重
- 组件复用：房间页继续用 `roomMode` 复用 ai-chat 的 `KimiChatInput`/`MentionMenu`/`AskUserCard`/`McpToolCallCard`；房间专属组件新增 `RoomProposalCard.vue`

## 八、L4 四前置条件：收尾状态（2026-08-21，四档制）

> 四档口径：**代码就绪**（工作树内、单测绿）→ **已提交**（分组提交进主干）→ **已验证**（真实服务 e2e/生产物证）→ **已上线**（生产运行）。
> 08-21 审查结论：本节所有项均处于「代码就绪」档；「已验证」档要求的真实服务 e2e 载体（CI）已于同日建设，但端到端验收未执行。

| 前置条件 | 四档状态 | 落地内容 |
|---|---|---|
| 1. 地基修完 | 🟡 代码就绪（待提交验收） | 断点 A/F 等修复在工作树；CI 已建（`.github/workflows/ci.yml`，lint+单测+契约+Bridge+前端三 job）、/healthz SHA 接线已完成（Bridge ARG 注入 + 主后端 `/health` 补 version/git_sha/build_time）、E2E-7「hi 不建 Case」已加；**待执行**：218 条改动按《协作室工作树对账与分组提交计划-2026-08-21》分组提交 + 逐条人工验收 |
| 2. L2→L4 升级规则 | 🟡 代码就绪 | `agentteams_upgrade_advisor.py`：三规则（explicit_request 必升 / flow_steps_gte_3 / requires_formal_delivery）+ 咨询否决抑制；建议卡（assistant 消息 `content_type="agentteams_upgrade"` + SSE chunk）；accept → 建房（`origin=l2_upgrade`、`origin_ref=L2 session id`）→ 首条系统消息 `room.upgrade_context` 带结构化摘要（context_refs 预检）；dismiss 同会话不重复；OTel counter 统计进入率。已知偏差：Phase D 的"LLM 兜底"未实现、veto 命中不可审计（见第十节） |
| 3. 双注册表统一 | 🟡 代码就绪 | 单一权威目录 = `data/ai/*.yaml` → `AgentTeamsCapabilityRegistry` 快照；chat LLM 路由候选集/描述/flow 目录全部由快照注入（DB `list_agents` 与直读 YAML 的独立组装已删除）；房间关键词路由校验注册表成员资格，未登记降级统一 fallback + 审计日志；两路由共用 60s TTL 同一缓存；契约测试 `test_dual_registry_contract.py`（8 用例，含真实 YAML 对账，在 CI 默认路径） |
| 4. 统一审计总线 | 🟡 代码就绪 | 事件分级一处定义（business 进 MinIO 持久流 / operational 只进 Redis 指标计数；`room.agent_stream` 已瞬态化：不进 MinIO、不进 Matrix，仅 Redis/内存供 SSE 打字机）；统一查询入口 `GET /cases/{id}/audit-chain`（Case 流+房间流合并、broken_links 断链检测）+ CLI `scripts/fetch_case_audit_chain.py`；correlation 链补全（causation_event_id / answer_to_event_id / card_event_id 回路，含会诊异常事件）；audit-chain 对真实 Case 的实跑证据待「已验证」档补 |

## 九、配置与数据层

运行时事实源在 `data/ai/`：

- `agentteams_manager.yaml` + `prompts/agentteams_manager.md` —— Manager 独立人格
- `flows/*.yaml` —— 流程知识：`trigger_hints`（路由）、stages、`delivery.thresholds`（质量门禁）
- `agent_ability.yaml` —— 平台 agent 目录（含 `requires_formal_delivery` 标记，L2→L4 触发用）
- `mas/agent_capabilities.yaml` / `mas/tool_policies.yaml` —— MAS 能力登记与工具沙箱策略
- `AgentTeamsCapabilityRegistry` 从这些 YAML 派生运行时快照（60s 缓存），**chat 路由与房间路由的唯一能力来源**

存储分层：

| 层 | 内容 | 事实源 |
|---|---|---|
| MinIO（`agentteams` bucket） | Case/房间事件流、状态快照、证据文件 | ✅ 业务状态事实源 |
| Redis | 热缓存、分布式锁、会话游标、operational 指标计数、pub/sub | 易失，可重建 |
| 主库 PG | `agentteams_rooms`（房间元数据）、`agentteams_case_cursors`、`agentteams_bridge_settings`、`audit_logs`（HTTP 请求级） | 元数据事实源 |
| Matrix | 房间镜像 | 投影，可重建 |

## 十、演进历史与遗留问题

演进主线：**Overdrive 超频（08 初）→ 协作室 M1–M7（08-12~13）→ 部门协作 Phase 1–3 → 08-19 生产事故根因调查 → 08-20 Manager 人格分层 + 框架调研 → 08-21 MinIO 化 + Case 解耦 + L4 前置收尾 → 08-21 L4 符合度审查 + 安全/正确性加固 → 08-21 v3 复审八项修复 → 08-21 双线施工（地基真实栈 e2e 验收 + 七项 hotfix，本节）**。

08-21 双线施工（《协作室双线施工任务书-三件套实现与地基e2e验收.md》Track B）：11 条地基用例在真实栈（compose 全套 + MinIO + 5 个 agentteams worker）首轮验收 4 绿/1 半绿/3 红/1 阻断/2 未覆盖，产出 5 个地基 bug 档案；随后主干 hotfix 七项并逐项复验——BUG-01 建房 500（MissingGreenlet 懒加载）、BUG-02 立项卡不落库（celery 任务无 commit）、BUG-03 preflight 派单硬编码别名（`_canonical_work_item_target` 经 capability snapshot 解析 canonical identity，端到端目击 preflight-01 target=agent-data 被专业池认领）、E2E-2 limit 钳制、E2E-9 空页死循环；复验中新发现 BUG-04（规划校验自愈 3/3 全败停死 waiting_for_correction，修复：会诊信封补流程型 TaskSpec 完整骨架 + sample_sheet list 形态明示）与 BUG-05（工具错误信封缺顶层 error 致事件流摘要丢失真实原因 + task_id 描述澄清），均已修复并各带单测。修复后全链路重跑：规划 3 次尝试内通过 → planning.frozen → preflight completed → approval_pending。验收套件已固化为 `tests/e2e/agentteams/test_live_foundation_e2e.py`（AGENTTEAMS_LIVE_E2E=1 门控，真实栈 HTTP 驱动）。全部证据在 `evidence/e2e-2026-08-21/`。

08-21 审查修复后**已闭环**的原遗留项：#2 `room.agent_stream` 已瞬态化（不进 MinIO 持久流、不进 Matrix 镜像，仅 Redis/内存供 SSE 打字机）；#3 会诊异常事件已带 `causation_event_id`（`run_consultation` 调用链透传触发 event_id）；#6 CaseStore 已改 persist-then-commit（23 处调用点顺序反转，快照写失败内存态不推进，且 `_persist` 改增量写）；#8 幂等 receipt 已持久化 MinIO（`receipts/{key}.json`，恢复不依赖事件重放）。审查新发现的安全项同日修复：B1 审批旁路（approval-authority 不可铸 worker token、审批 token 绑定 plan_hash）、B2 evidence 身份白名单 + worker 因果锚点强制、B3 confirm_token 全出口脱敏（复审 B1 进一步闭环为"写入后即脱敏"，见第四节）+ owner 显式断言。

08-21 v3 复审（《协作室框架文档v3复审问题清单》）八项**已修复**：A1 房间立项 Case 接入与旧路径一致的项目物化链路（`_resolve_case_project`：立项卡 project 引用 → followup 继承源 Case 项目 → `get_or_create_project_by_name`，取名口径与前端 `buildCaseProjectName` 一致）；A2 复合游标归并截断到 limit + 游标按截断后保留集重算 + tie-break 统一 `(recorded_at, event_id)`（共享 `event_stream_sort_key`）；A3 @直答失败/超时（30s 可配，`agentteams_direct_timeout_seconds`）Manager 降级接管 + 可见降级消息 + `room.agent_timeout` 审计；B1 confirm_token 改"写入后全出口脱敏"（owner 可不带 token 确认，token 为可选 API nonce）；B2 快照口径澄清（见第五节）；B3 participants 来源注明（见第四节）；C1 Bridge `/v1/metrics` 增加房间事件量指标（`room_namespace_count`/`room_events__room-*`），GC/归档口径文档化（`docs/info/26.8.21/协作室房间事件GC与归档口径.md`）；C2 自建 agent 缺失注册表时 warning 日志（300s 节流）+ veto 命中写遥测（event=vetoed，含命中词/摘要/session id）+ "介绍"词表收窄 + 上线前盘点脚本 `scripts/check_custom_agents.py`。

当前遗留问题（按优先级）：

1. **分组提交验收未执行**（唯一阻断项）：218+ 条改动对账表与分组计划已产出（`docs/info/26.8.21/协作室工作树对账与分组提交计划-2026-08-21.md`），夹带项归属与 hunk 拆分待用户决策后提交；双线施工的七项 hotfix 也随工作树待提交。
2. **真实服务 e2e 已执行一轮并修复复验**（见上节双线施工）：剩余缺口为审批→执行→交付段（需真实审批触发计算任务）、E2E-4/6/11 的故障注入/前端渲染子项、live 套件进 CI 默认执行（需 CI compose 矩阵）；`waiting_for_correction` 无预算耗尽显式终态；BUG-05 的 live success 标记疑点待查。
3. L2→L4 的 Phase D"LLM 兜底"未实现（仅 trigger_hints 子串匹配，veto 可审计与词表收窄已修）。
4. 房间删除/归档端点未实现（GC 口径已定档未实施）；房间列表无最后消息预览字段。
5. @直答成功不落幂等标记（`direct_responded` 不在成功终态内，重试可能重复直答）——改动前即如此，待评估。
6. `correlation_id`（跨服务 trace）已定义提取口径，尚无写入点产生。
7. 超频 Manager 的 subagents 目录（`subagents_spawnable`）仍是独立组装点，未纳入注册表快照。
8. DB 自建 agent 上线前需执行 `scripts/check_custom_agents.py` 盘点生产影响面（缺失告警已加）。
9. Bridge 层无"manager 不可作 work item target"硬校验，依赖主后端自律（低风险）。
10. Worker 并行池：pool 模式每 identity 硬编码 `max_concurrent=1`，单 Agent 多 Worker 只能靠多副本；无 per-agent 并发上限。
11. 变更决策 resume/replan/branch 真实编排、Case 绑定项目 / 交付进"我的文件"（旧路径之外的深化）、provenance 三层标注、Manager LLM 真实组队仍未实现（属愿景深化/后续阶段，见《L4协作室与文件系统融合优化实施手册》与部门协作 Phase 2）。

## 十一、一句话总结

升级后的协作室是一套**"房间即轻量会话、Case 即确认工单、MinIO 即事实源"**的三进程架构——主后端做认证适配、房间实体与 LLM 会诊内核，无状态 Bridge 持有 Case 状态机并把状态与事件流全部对象化到 MinIO，Gateway 做策略护栏与 Matrix 密钥隔离；前端以 SSE + 两级纯函数投影把双流（房间级/Case 级）统一渲染成群聊。L4 四个前置条件的代码已全部就绪，经一轮独立审查、安全/正确性加固与真实栈地基 e2e 验收（七项 hotfix 已复验转绿）；但全部改动仍在工作树：**完成分组提交后，方可摘除"L4 候选/演示态"标签**。

---

## 附：主要参考文档

- `docs/info/26.8.21/协作室架构升级方案-MinIO持久化与Case解耦及L4前置收尾.md` —— 本次升级的方案蓝本
- `docs/info/26.8.21/协作室L4愿景符合度审查报告-2026-08-21.md` —— 升级后审查（清单 0–4，A–F 结论）
- `docs/info/26.8.21/协作室L4审查修复与优化实施手册.md` —— 审查修复手册（阶段 0–3）
- `docs/info/26.8.21/协作室工作树对账与分组提交计划-2026-08-21.md` —— 218 条改动对账与提交计划
- `docs/info/26.8.21/协作室框架文档v3复审问题清单.md` —— 第二轮复审八项问题（A/B/C 类，已全部修复）
- `docs/info/26.8.21/协作室双线施工任务书-三件套实现与地基e2e验收.md` —— 双线施工任务书（Track A 三件套待提交门禁，Track B 地基验收已执行）
- `evidence/e2e-2026-08-21/summary.md` —— 地基 e2e 验收 + 七项 hotfix 复验证据汇总（BUG-01~05 档案在 env/ 子目录）
- `docs/info/26.8.21/协作室房间事件GC与归档口径.md` —— 房间闲聊数据保留/归档口径（C1）
- `ARCHITECTURE_DESIN/agentteams_department_collaboration_architecture(_2026-08).md` —— 部门协作架构
- `ARCHITECTURE_DESIN/agentteams_room_plan.md` —— 协作室实施总账 M1–M7
- `ARCHITECTURE_DESIN/manager_role_bioinfo_department_manager_2026-08.md` —— Manager 定位评估
- `docs/info/26.8.19/L4愿景落地实施计划.md` —— L4 现状核查 + Phase A–F 路线（L2→L4 权威口径来源）
- `docs/info/26.8.19/协作室平台地基优化实施手册.md` —— 四阶段施工手册
- `docs/info/26.8.19/L4协作室与文件系统融合优化实施手册.md` —— Case 绑定项目 / MAS 交付入口 / context_refs 协议化
- `report/12_多智能体协作室根因调查报告_2026-08-19.md` —— 生产故障根因定案（断点 A–F）
- `docs/info/26.8.20/协作室Manager反复追问数据来源-代码调研报告_2026-08-20.md` —— 澄清卡症状调研
- `docs/info/26.8.20/Manager人格分层实施手册-通用助手与部门经理共存.md` —— 人格分层施工 spec
