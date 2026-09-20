# 协作室（AgentTeams）最终架构 · 2026-08-21

> **合并说明（2026-09-18）**：本文是协作室的现行基线，已并入以下三份文档的独有内容并删除原件：
>
> 1. `agentteams_room_framework_research_2026-08.md`（2026-08-21 框架研究快照）→
>    §2.1（Bridge MinIO 持久化工程口径）、§4.5（立项确认卡事件契约）、§15（模块清单）、
>    §16（演进史与遗留问题，与 §13 互补）；其中与本文重复的拓扑 / 会话-工单解耦 / Matrix
>    镜像描述已丢弃，以本文为准。
> 2. `agentteams_room_plan.md`（实施总账 M1–M7，2026-08-12 初稿 / 08-13 增补）→
>    §17（架构决策档案）；M1–M3 施工流水账已被 2026-08-21 升级覆盖，不搬，
>    历史施工明细见 git。
> 3. `manager_role_bioinfo_department_manager_2026-08.md`（2026-08-20 评审稿）→
>    附录 A（Manager 双身份与命名红线）；其组织模型复述与本文 §1 重复，丢弃。
>
> **日期口径（合并时修正，2026-09-18 更名后仍有效）**：本文是现行活基线，文件名已去日期
>（`agentteams_room_architecture.md`，原 `agentteams_room_current_architecture_2026-08-21.md`）；
> 基线日期以标题 **2026-08-21** 为准，正文所记录的
> as-built 实现断面为 **2026-08-22**（见下"状态口径"），§14 为 **2026-08-27** 增补。
> 原正文标题误写"· 2026-08-22"与文件名不一致，现予以澄清。

> **文档定位**：协作室的最终目标架构与施工验收依据。它以 2026-08-21 已建底座为
> as-built 基线，并吸收 `docs/info/26.8.22/agentteams/协作室两项需求施工任务书_2026-08-22 copy.md`
> 的已定稿决策：**Case LLM 过程全量记录**、**邀请平台用户加入房间**与**流程 HTML
> 报告导出**。
>
> **状态口径（2026-08-22）**：本文同时记录当前工作树的 as-built 实现：已落地
> `agentteams_turn_records`、`agentteams_room_members`、邀请/成员/turns API、
> `agentteams_ctx_var`、MinIO `cases/{case_id}/turns/...` 全文记录、Bridge→Gateway→
> 平台的 `trace_id` 透传、Redis 审计流的近似 `MAXLEN`，以及受控的
> `reports/flow-*.html` 产物与血缘登记。仍待第 12 节的真实双账号环境验收；在该验收前，
> 不将 Matrix 联通性或生产存储可用性表述为已验证。
>
> **权威来源**：两项需求施工任务书优先；既有基础能力以当前代码、部署栈与
> 2026-08-21 的已建基线为准。本文取代旧版“单主房间、无过程记录”的架构口径。

---

## 1. 目标、边界与不变量

协作室是面向平台用户的多人协作入口：用户在房间讨论、澄清和立项；Case 进入 Bridge
状态机后由 Manager、Gateway 和 Worker 集群协同完成；全过程既要让协作者看见可信的结果，
也要让 owner 在事后能够审计、定位并回看每一次 LLM 调用；平台级审计读取须另设只读管理端点。

本次架构达成三项能力：

1. **全量过程记录**：对每次 AgentTeams LLM 调用持久化完整输入、输出、思考、工具调用、
   模型参数、用量、耗时及链路身份，并可按 Case/工作项/轮次回看。
2. **受控多人房间**：owner 可邀请平台用户；受邀用户明确接受后成为 member，在不改变
   Bridge 单 `requester_ref` 模型的前提下参与房间和浏览 Case 的允许内容。
3. **离线流程报告**：从已落库的 turns、审计事件和产物血缘生成单文件 HTML，按导出者角色
   在服务端裁剪敏感正文，并把报告作为新的可追溯产物版本登记。

以下不变量不得因本次施工被破坏：

- Bridge 仍是 Case 状态机、派单、认领和事件卷的权威；过程记录独立于事件卷，不以
  `room.agent_stream` 替代过程存档。
- 正式执行仍须经过 `room.proposal_confirm` 与 owner 的立项确认；member 不得删除房间、
  邀请/移除成员或消费立项确认。
- prompt 与 reasoning 的正文不得写入 OTel span、普通日志或 Redis stream；span 只保存
  可审计引用。
- 过程记录失败绝不阻断模型调用、Worker 交付或 Bridge 状态机；失败必须可观测。
- 访问控制必须由服务端执行；前端仅展示后端已裁剪的字段，不能作为权限边界。
- 本期不改变 Bridge 的 `requester_ref`/Case 模型，不以 `@用户名` 作为邀请命令，也不承诺
  “同一快照重新执行”或研究级严格复现。

## 2. 最终总体拓扑

```text
浏览器（owner / accepted member）
   │ JWT
   ▼
Vue3: RoomView ──────── CaseView（时间线 + 步骤详情 + 流程报告导出）
   │ /api/v1/agent-teams/*                  │ /users/lookup
   ▼                                         ▼
┌──────────────────────────── cygnusx-web ─────────────────────────────┐
│ 房间服务 / 成员与邀请 / 通知 / 意图路由 / Case 服务 / 会诊              │
│ 过程记录器 / turns 查询与脱敏 / 流程报告 / 血缘、QC、自省 / OTel ContextVar │
│ PostgreSQL: rooms、members、turn-record 索引、血缘、判决、通知          │
└───────────────┬─────────────────────┬───────────────────┬────────────┘
                │ X-Integration-Token │ Matrix mirror     │ async best-effort
                ▼                     ▼                   ▼
┌──────────────────────┐   ┌──────────────────────┐  ┌──────────────────┐
│ Bridge（Case 状态机） │   │ Matrix（多人房间镜像）│  │ MinIO evidence   │
│ events / dispatch     │──▶│ owner/member identities│  │ Case 产物+turns+reports │
└──────────┬───────────┘   └──────────────────────┘  └──────────────────┘
           │ consult / workspace execution                        ▲
           ▼                                                      │
┌──────────────────────┐                                          │
│ Gateway（执行仲裁）    │ ──▶ 平台 Agent 运行时                    │
└──────────┬───────────┘     `parallel_subagent_service`           │
           ▲                                                        │
┌──────────┴───────────────────────────────────────────────────────┴──┐
│ Worker 集群：analysis / quality / delivery / code / viz / scrna /    │
│ professional-pool / phylo；inbox → claim → heartbeat → report         │
└───────────────────────────────────────────────────────────────────────┘

Redis：Bridge 共享状态与热流；不得承载过程记录正文，也必须对审计 stream 设置 MAXLEN。
```

现有运行组件继续使用 `deploy/agentteams/docker-compose.agentteams.yml` 所定义的 Gateway、
Bridge、state、Worker、`cygnusx-web`、PostgreSQL、MinIO、Redis 和开发态 Matrix。无需引入
Langfuse 等外部观测产品；本架构复用平台已有 ContextVar、OTel、MinIO 和 PostgreSQL 能力。

### 2.1 Bridge 持久层：MinIO 事实源口径（并入自 2026-08 框架研究 §五）

原则：**MinIO 是事实源，Redis 只是热缓存/分布式锁，本地 JSON 文件已废除**。Bridge 业务状态
使用 `agentteams` bucket（`minio-init` 建桶）；本文 §5.3 的过程记录使用另一受控桶
`agentteams-evidence`，两桶前缀与读取通道互相独立。

- **事件卷对象布局**：`cases/{case_id}/events/audit.jsonl` 为事件流首卷；单对象超 **50MB**
  （`BRIDGE_MINIO_EVENT_OBJECT_MAX_BYTES`）按天滚卷为 `audit-YYYYMMDD.jsonl`（同日多卷加
  `-N` 后缀）；读取按"首卷优先、分卷字典序"还原时间序。
- **快照 envelope**：`cases/{case_id}/snapshot.json`，结构
  `{version, case_id, saved_at, last_event_id, case}`；每次状态迁移写一次（"状态迁移或每
  200 事件"口径的超集）。每个 snapshot.json 始终是**单 case 的完整 envelope**（非部分字段，
  08-21 复审 B2 澄清）；"增量写"指 `_persist` 每次只重写**本次变更 case** 的快照对象（替代
  原 O(N) 全量逐 case PUT 的写放大），恢复语义不变——逐 case 读最新快照 → 校验
  last_event_id → 重放增量事件。
- **写入顺序硬约束**：MinIO 落盘成功 → Redis 热缓存（XADD/快照，失败仅告警）→ 内存索引 →
  `_notify`（room mirror / SSE 拉取源）。MinIO 写失败即操作失败，禁止"先缓存后补写"、禁止
  幽灵成功态。
- **persist-then-commit**：CaseStore 的 `_persist(changed=..., removed=...)` 先写快照成功
  才提交内存态；写失败抛错且内存不推进（23 处 mutating 调用点全部顺序反转）。`audit.py`
  （`AuditStore`）与 `case_store.py` 共同执行该约束；MinIO 模式下 `case_store.py` 从 MinIO
  恢复（fail fast），本地 JSON 路径废除。
- **启动恢复 fail-fast**：读最新快照 → 校验 last_event_id 与事件流连续性（marker 非空则必须
  存在于事件流；marker=None 或落后于流尾是"先快照后事件"的合法瞬时态）→ 重放增量。任何
  读取/解析/校验失败 = 结构化告警 + **拒绝启动**。
- **append 实现**：S3 无原生 append → 读-改-写尾卷 + per-case asyncio 锁；`record()` 返回前
  必须已落盘。
- **operational 事件降噪**：operational 事件
  （`worker.inbox_polled / worker.heartbeat / room.typing`）不进 MinIO 事件流，只
  `INCR <prefix>:metrics:events:{type}`（无 Redis 时进程内计数）；`metrics()` 暴露聚合计数
  供监控面板；Bridge 侧 `OPERATIONAL_EVENT_TYPES` 与主后端
  `agentteams_audit_events.py` 同口径互注同步（见 §15.2）。Redis 审计 stream 的 XADD
  近似 `MAXLEN` 止血项见 §8 第 4 条。
- **配置**：`BRIDGE_MINIO_ENDPOINT / ACCESS_KEY / SECRET_KEY / BUCKET（默认 agentteams）/
  SECURE(false)`；生产校验器强制 endpoint 非空；未配置时非生产回退旧模式并打 warning。
  compose 已接线（bridge 服务注入 `BRIDGE_MINIO_*`，endpoint `http://minio:9000`，凭证引用
  `MINIO_ROOT_USER/PASSWORD`）。
- **迁移 CLI**：`python -m cygnusx_agentteams_bridge.migrate_to_minio` 一次性迁移既有本地
  JSON → MinIO，逐 case 对账（事件数不平非零退出），旧文件保留人工归档。

## 3. 房间与 Case 的职责划分

### 3.1 房间层

- 每个房间保留 `agentteams_rooms.owner_id` 作为唯一 owner/管理员事实源；未立项房间的
  审计流仍使用 `room-<room_id>` 伪 Case 命名空间，与正式 Case 共用事件总线但不计入
  Case 运营指标。
- 意图路由仍是 `EXECUTE / TOOL_EXECUTE / CLARIFY / CHAT` 四态。无命中时必须澄清或
  LLM 会诊，禁止静默降级到通用助手。
- 执行类需求生成立项确认卡；仅 owner 可确认、修改或取消，并由此创建和绑定正式 Case。
- 房间消息继续镜像到 Matrix。平台事件/SSE 仍是业务 UI 的实时来源，Matrix 是协作镜像，
  不替代平台服务端授权。

### 3.2 Case 执行层

- Bridge 保持 Case、Work Item、派单、认领、心跳、重试、归档及 MinIO 事件卷的权威状态机。
- Worker 的只读会诊和工作区执行经 Gateway 仲裁，交付继续遵守 `source_refs`、产物血缘与
  QC 质量门约束。
- 三条 LLM 路径——房间响应、平台会诊、Worker 代跑——都在
  `parallel_subagent_service._child_loop` 的 `provider_manager.chat_stream` 汇合；这是唯一的
  过程记录主埋点。`llm_call_node` 仅属于 AI 聊天/Studio，禁止改作 AgentTeams 埋点。

## 4. 多人协作模型：A1+ 平台代持

### 4.1 身份决策

本期采用 **A1+（平台代持 + 全程真实身份标注）**：

- Bridge 请求仍使用房间 owner 的 `requester_ref`。这避免修改 Bridge、Gateway、Worker 三个
  进程的 Case 所有者模型和事件反向同步语义。
- 平台在进入 Bridge 前执行房间成员授权；accepted member 可读取/发言，所有 owner-only
  操作仍在平台层硬拒绝。
- member 发起的房间消息、会诊或 Case 动作，在平台事件 `actor` 与过程记录
  `actor_user_id` 中写真实平台用户；`requester_ref` 仍记录 Bridge owner 身份。审计因此同时
  保留“谁实际触发”和“Bridge 以谁的身份执行”。
- 平台 admin 当前没有协作室隐式越权；审计读取若有需求，须以独立的服务端管理端点设计，
  不得把 admin 身份透传为 Bridge requester。
- Bridge 原生多成员/多 requester（路线 B）是后续独立项目，不能混入本期。

### 4.2 成员状态机与数据模型

新增 `agentteams_room_members`，owner **不**写入该表，owner 语义始终来自
`agentteams_rooms.owner_id`。

| 字段 | 语义 |
|---|---|
| `room_id`, `user_id` | 房间与被邀请平台用户；联合唯一约束 `(room_id, user_id)` |
| `role` | 本期接受后为 `member`；保留 `owner/member` 枚举兼容成员模型模板，但 owner 不落行 |
| `invited_by` | 发起邀请的 owner 用户 ID |
| `status` | `pending`、`accepted`、`declined`；拒绝是保留的服务端终态，不授予成员访问权限 |
| `created_at`, `responded_at` | 邀请与最终响应时间；拒绝记录可供 owner 审计、展示与再次邀请 |

状态转换：

```text
不存在 ── owner invite ──▶ pending ── invitee accept ──▶ accepted
                                │                              │
                                ├── invitee decline ──▶ declined ── owner re-invite ──▶ pending
                                └── owner revoke ────▶ 不存在    │
accepted ── member leave / owner remove ────────────────────────▶ 不存在
```

重复邀请同一用户必须幂等返回既有 `pending` 记录；再次邀请 `declined` 用户会重置该行至
`pending` 并创建新的定向通知；撤销仅适用于 `pending`。数据库约束、事务与服务层判断共同保证
一个用户不能在同房间获得重复成员态。

### 4.3 授权矩阵

| 操作/资源 | owner | accepted member | 平台 admin（当前实现） |
|---|:---:|:---:|:---:|
| 查看房间、历史消息、关联 Case 与证据卡 | ✅ | ✅ | ❌（无隐式越权） |
| 发送房间消息、触发会诊 | ✅ | ✅ | ❌ |
| 创建邀请、撤销邀请、移除成员 | ✅ | ❌ | ❌ |
| 离开房间 | owner 不适用 | ✅ | 不适用 |
| 删除房间、消费立项确认 | ✅ | ❌ | ❌ |
| turns 摘要、工具原文、LLM 输出全文 | ✅ | ✅ | ❌ |
| prompt 全文、reasoning 全文 | ✅ | ❌（默认） | ❌ |

`AgentTeamsRoomService.get_room()` 与 `list_rooms()` 的通行条件为“owner 或 accepted member”；
当前没有 admin 的隐式协作室越权。若后续需要审计读取，必须新增由服务端 `AdminRequired` 保护的
只读端点，不能复用用户态房间写接口。
列表必须返回 `role=mine|invited`，供界面分组。所有 Case/turns 查询都先通过
`_get_case_for_requester` 或等效 Case 归属检查，再叠加房间成员权限；不得把只知道 Case ID
视作授权。

### 4.4 Matrix 与级联清理

accept 在事务内形成 accepted 成员态后，为该用户派生 Matrix identity 并执行 Gateway 的
ensure/invite/join 原语；成功后通知邀请人。成员主动退出、owner 移除成员和删房都必须执行
Matrix 离房清理。删房遍历 owner 与所有 accepted member，不能沿用只清理 owner 的旧逻辑。

### 4.5 立项确认卡事件契约（并入自 2026-08 框架研究 §四）

执行类需求在房间内生成 `room.proposal_confirm` 事件（房间命名空间事件流），其 payload 全
契约如下：

```text
payload = {agent_id, role, causation_event_id,
           proposal_kind: "new_case" | "followup",
           confirm_token,            # 一次性令牌：仅服务端留存与校验，所有读出口一律脱敏为 null
           status: "pending",
           objective, flow_id, flow_label, lead_planner, route_path,
           participants[],           # 现状口径：flow YAML 静态声明 + 关键词路由命中，非 Manager LLM 组队决策
           estimated_stages[], confidence,
           origin_content, context_refs[], source_case_id,
           options,                  # new_case: confirm/modify/cancel；followup: continue/new/cancel
           created_at}
```

- **confirm_token 口径（08-21 复审 B1 闭环）**：token 只存服务端（房间行 DB 字段 + 事实源
  事件内部）；写入后全出口（Bridge/主后端分页、SSE、audit-chain、Matrix 镜像）一律脱敏。
  确认请求可不带 token（owner 身份即授权边界），带 token 则强制比对（API 级防重放 nonce）。
  `confirm_proposal` 对 pending 状态做原子消费：幂等、失败回滚 pending；owner 校验在平台层
  执行（member 不得消费，见 §4.3 授权矩阵）。
- **participants 来源口径（08-21 复审 B3 注明）**：立项卡的
  participants/estimated_stages/route_path 来自 flow YAML 静态声明的关键词路由命中结果
  （`agentteams_route_decision.py` 只读观察），**Manager LLM 当前不做选专家决策**；Manager
  真实组队属愿景深化项。
- 用户确认后创建 Case 并回写房间绑定，`room.case_bound` 事件带 `answer_to_event_id` 指回
  立项卡。终态后（closed/delivery_ready/cancelled）房间可继续对话，新 execute 意图产出
  followup 立项卡（"基于上一 Case 的交付继续（`source_case_id` 关联引用）/ 新建工单 /
  取消"）。

## 5. 过程记录子系统

### 5.1 捕获与上下文传播

新增 `agentteams_ctx_var`，值为：

```json
{
  "case_id": "...",
  "work_item_id": "...",
  "round_number": 1,
  "agent_id": "...",
  "actor_user_id": "..."
}
```

会诊入口在 `agent_consultation_service.run_consultation` 设置 Case、工作项、Agent 与真实
触发用户；`_child_loop` 在每轮开始更新 `round_number`。其生命周期、reset 和异常安全模式与
既有 `session_id_var`、`request_id_var` 一致，不能让并发会诊之间串值。

在 `_child_loop` 的每次 `provider_manager.chat_stream` 调用前后，
`AgentTeamsTurnRecorder` 完成一次独立记录：调用前冻结 messages 全文和实际模型参数；流消费
结束后收集输出、reasoning、工具调用、usage、结束原因、状态、异常和耗时。这样单一埋点覆盖
房间响应、会诊和 Worker 代跑，无需污染 provider 层签名。

### 5.2 单条记录契约

每次模型调用生成一个不可变 JSON 对象：

```json
{
  "record_id": "uuid4",
  "recorded_at": "ISO8601",
  "case_id": "...",
  "work_item_id": "...",
  "agent_id": "...",
  "round_number": 3,
  "call_seq": 1,
  "child_session_id": "agentteams:{case_id}:child:{run_id}:{index}",
  "requester_ref": "bridge-owner-user-id",
  "actor_user_id": "actual-platform-user-id",
  "trace_id": "...",
  "span_id": "...",
  "provider": "...",
  "model": "...",
  "sampling": {"temperature": 0.7, "max_tokens": null, "deep_thinking": true},
  "messages": [{"role": "system", "content": "全文"}],
  "output_text": "输出全文",
  "reasoning_text": "思考全文或 null",
  "tool_calls": [{"name": "...", "arguments": "原始 JSON"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "duration_ms": 0,
  "finish_reason": "...",
  "status": "ok|error",
  "error": null
}
```

`call_seq` 在同一 `case_id/work_item_id/round_number` 内递增；错误调用也写入 `status=error`
及错误摘要，只要在调用前已获得上下文。记录对象只追加、不覆盖、不经事件流拼接，保证“每次
调用一个对象”且没有追加竞争。

### 5.3 持久化、索引与读取

| 层 | 存储内容 | 读取用途 |
|---|---|---|
| MinIO `agentteams-evidence` | 完整不可变 JSON | 详情按需读取、审计和未来重放输入 |
| PostgreSQL `agentteams_turn_records` | `record_id`、Case/Work Item/round、actor、model、tokens、duration、status、`s3_uri`、时间等摘要索引 | 分页列表、筛选、按轮聚合 |
| OTel span | `agentteams.turn_record_uri` 与模型/用量属性 | Trace → 具体记录跳转；禁止正文 |

MinIO key 固定为：

```text
cases/{case_id}/turns/{work_item_id}/{round_number:04d}/call-{call_seq:02d}-{record_id}.json
```

过程记录写入以异步、非阻塞 best-effort 执行；写对象、写索引或设置 span 引用失败时只记录
结构化错误、指标和告警，**不得**影响 `chat_stream`、SSE、Worker 或 Bridge 主链。DB 列表查询
绝不扫描对象存储；详情先经授权，再按索引的 `s3_uri` 定位对象。记录器与查询服务需要为
“对象成功但索引失败”或“索引成功但对象失败”提供可观测诊断，不能向用户伪造完整记录。

`environment_snapshot` 同步补充本次实际使用的 `provider`、`model`、`temperature` 与
`deep_thinking`，使产物版本事实与过程记录可交叉核验。

### 5.4 可见性裁剪

`GET turns` 与详情接口在服务端根据第 4.3 节角色矩阵裁剪：member 不返回
`messages` 与 `reasoning_text` 键；不是返回截断文本或依赖 CSS 隐藏。owner 可查看完整
对象；成员可查看记录摘要、工具原文与 `output_text`。前端遇到缺失字段显示“无权查看”，不做
自行授权判断。

## 6. API 与通知契约

所有接口位于既有 JWT 用户 API 下，除非明确标注 Bridge 内部接口；请求体和分页 schema 应
在 `api/v1/agentteams.py` 的 Pydantic 模型中显式定义。

| 方法 | 路径 | 授权与语义 |
|---|---|---|
| `POST` | `/rooms/{room_id}/invitations` | owner；`{user_id}`，幂等创建/返回 pending，并创建定向通知 |
| `GET` | `/invitations/pending` | 当前用户；列出本人待处理邀请 |
| `POST` | `/invitations/{id}/accept` | 仅 invitee；accepted → best-effort Matrix join → 通知 owner |
| `POST` | `/invitations/{id}/decline` | 仅 invitee；写入 declined 终态，不加入 Matrix |
| `DELETE` | `/rooms/{room_id}/invitations/{user_id}` | owner；撤销 pending |
| `POST` | `/rooms/{room_id}/leave` | accepted member；移除成员态并离开 Matrix |
| `DELETE` | `/rooms/{room_id}/members/{user_id}` | owner；移除 accepted member 并离开 Matrix |
| `GET` | `/users/lookup?q=` | 任意已登录用户；用户名/昵称前缀精确搜索，仅返回 `id/nickname/avatar`；端点无专用限流，仅由全局每 IP 滑动窗口限流中间件兜底（`middleware/rate_limit.py:76`，默认 100 次/60 秒） |
| `GET` | `/cases/{case_id}/turns` | owner/accepted member；DB 索引分页，可按 `work_item_id`、`round_number` 过滤 |
| `GET` | `/cases/{case_id}/turns/{record_id}` | owner/accepted member；读取完整对象后按角色脱敏 |
| `POST` | `/cases/{case_id}/reports/flow` | owner/accepted member；服务端读取已有 turns/events/血缘，按角色裁剪后生成并登记 HTML 产物 |
| `GET` | `/cases/{case_id}/artifacts/{path}` | owner/accepted member；复用受控下载通道读取报告等 Case 产物 |

邀请通知使用现有 `NotificationModel`：`type=agentteams_room_invite`，payload 至少包含
`room_id`、`invitation_id`、邀请人昵称；受邀人响应后，服务端在同一 payload 写入
`decision=accepted|declined` 与 `responded_at`。优先复用平台已有全局 SSE/WebSocket 通道；
若当前没有可复用通道，本期允许通知抽屉以最多 60 秒轮询获得邀请，不新建专用推送基础设施。

## 7. 前端最终交互

### 7.1 房间成员管理

`AgentTeamsRoomView.vue` 的房间头部在 owner 视角展示“+ 邀请”：弹窗通过
`/users/lookup` 搜索用户，显示 owner、accepted 成员和 pending 邀请。owner 可撤销
待处理邀请或移除成员；member 仅能对自己执行“退出”。房间列表根据 `mine/invited` 标记展示
“我创建的/邀请我的”分组或角标。

`NotificationDrawer.vue` 对 `agentteams_room_invite` 呈现“接受/拒绝”操作；处理结果写回通知
payload 并刷新列表，因此换浏览器后仍显示“已接受/已拒绝”且按钮禁用。owner 的成员管理面板显示
`declined`，并可重新邀请。

### 7.2 Case 步骤详情

`AgentTeamsCaseView.vue` 在协作时间线后增加“步骤详情”：列表按 Work Item → round 分组，
行展示轮次、模型、tokens、耗时和状态；展开某条后按 role 段落展示 messages、等宽块展示
reasoning、完整输出和工具调用原文。成员收到的详情缺少 prompt/reasoning 时展示“无权查看”。
刷新或重新登录后，页面从 turns API 回看内容，不依赖易失的在线 stream。

既有房间 SSE、虚拟列表和事件游标行为必须保持，邀请 UI 不得引入单消费者假设。

### 7.3 Case 流程 HTML 报告

`AgentTeamsCaseView.vue` 在“Agent 过程记录”卡片提供“导出流程报告”。`POST
/cases/{case_id}/reports/flow` 先按房间角色授权；房间 Case 由 owner 的 Bridge 身份读取 Case
与事件，避免 A1+ 的单 `requester_ref` 阻断 accepted member 的合法导出。服务端从 DB 索引读取
turns 顺序、从 MinIO 读取每条全文、从 Bridge 读取时间线、从 `case_artifact_versions` 读取血缘，
再渲染为零外部 CSS/JS 依赖的单文件 HTML。

报告中 LLM 步骤使用 `TRN-{round:04d}-{call_seq:02d}-{record_id前8位}`，时间线使用
`EVT-{event_id前8位}`，产物使用 `ART-{artifact_version_id前8位}`；每项同时保留完整 ID，短码旁
有离线可用的复制按钮。报告额外渲染应用名/版本、服务名、生成者、时间及 turns/events 计数的环境
快照。member 报告在渲染前移除 `messages` 与 `reasoning_text`，以“已按权限裁剪”原位标注，不能依赖
前端隐藏。报告写到 `cases/{case_id}/reports/flow-{timestamp}-{nonce}.html`，随后写
`report.flow_exported` 事件、登记 `case_artifact_versions`，并作为下游产物以 `derived_from` 边
关联已有产物。

血缘行的 `checksum_sha256` 是下载文件字节的权威 SHA-256；HTML 页脚显示的
`content_checksum_sha256` 是对报告输入快照的规范化摘要，避免静态文件自引用哈希无法验证的悖论。
前端经现有受控产物下载通道取 Blob 后下载，始终携带用户 JWT，不暴露 MinIO 直链。

## 8. 链路追踪、止血项与运维

本架构同时落实以下低风险止血项：

1. 会诊 API 入口和房间响应进入 `run_consultation` 前设置
   `session_id_var = "agentteams:{case_id}"`，使管理端 Trace 可按 Case 聚合。
2. Bridge 将 `work_item.trace_id` 加入 `consult_payload`，Gateway 原样透传；平台处理 consult
   时优先将该值写入 `request_id_var`，并兼容既有 `x-request-id`。
3. `room.agent_message` 的直答和主路径统一使用 `_ROOM_REPLY_CONTENT_MAX_CHARS`，消除
   8,000/10,000 字符截断差异。
4. Bridge Redis 审计 stream 的 XADD 使用可配置的近似 `MAXLEN`（保守默认值）；MinIO 业务事件
   卷仍是优先持久层，Redis 仅承担热状态/热流。

span 允许保留 `gen_ai.request.model`、`gen_ai.usage.*`（或兼容的既有 `ai.*`）及
`agentteams.turn_record_uri`；绝不写 messages、reasoning、工具参数或输出正文。告警至少覆盖
过程记录写失败、索引/对象不一致、turns 读取失败、邀请 Matrix 入/离房失败和 Redis 裁剪异常。

## 9. 安全、隐私与保留策略

- JWT 负责用户到平台；Worker token 负责 Worker inbox/claim/heartbeat；
  `X-Integration-Token` 仅限 Bridge 与平台的内部自省/服务调用。三类令牌不得互用。
- 最小目录搜索不复用 admin 用户列表，不返回邮箱、权限、账号状态等额外个人信息，并限流。
- 全量 prompt、reasoning 和工具原文视为敏感审计数据：仅放 MinIO 受控对象、经服务端授权
  读取；不得出现在普通日志、错误消息、span 属性或无鉴权的预签名链接中。
- turns 对象与产物证据共用 `agentteams-evidence` bucket，但有独立 Case/turns 前缀和 DB 索引；
  删除/归档策略须在未来按 Case 生命周期统一制定，不能被 Redis TTL 或房间事件归档误删除。
- 房间归档继续表示“业务写入只读 + 事件卷冷存”，不是删除；过程记录独立于房间事件卷，归档
  和 Bridge 重启均不能破坏已完成 Case 的 turns 回看。

## 10. 数据迁移、发布与回退

发布顺序固定为：

1. 先部署止血项与数据库迁移：`agentteams_turn_records`、`agentteams_room_members` 及必要索引；
   在 staging 实跑 Alembic upgrade。
2. 部署后端：ContextVar、记录器、异步写入、turns API、成员/邀请/API 搜索/通知/Matrix 级联，
   保持旧 owner-only 数据可用。
3. 部署前端邀请、步骤详情和流程报告下载；未迁移完成或 turns API 不可用时前端应为空态/错误态，不能猜测权限。
4. 以两个真实账号与真实多轮 Case 完成第 12 节 e2e 后，才开放给更大范围用户。

回退优先关闭前端入口和新增路由流量；已写 turns 对象为 append-only 审计证据，不回删。记录器
写入异常时可停用异步写任务而不影响 Case 主链；不得为回退而修改 Bridge 的 requester 模型或
删除已接受成员的房间审计事实。

## 11. 关键文件地图

| 责任 | 主要位置 |
|---|---|
| 房间授权、成员与事件流 | `src/cygnusx/application/services/agentteams_room_service.py` |
| 房间响应与会诊发起 | `src/cygnusx/application/services/agentteams_room_response_service.py` |
| 会诊与产物环境快照 | `src/cygnusx/application/services/agent_consultation_service.py` |
| LLM 汇合点与轮次 | `src/cygnusx/application/services/parallel_subagent_service.py` |
| 过程记录器（新增） | `src/cygnusx/application/services/agentteams_turn_recorder.py` |
| 流程报告渲染与登记 | `src/cygnusx/application/services/agentteams_flow_report_service.py` |
| ContextVar 与 span 导出 | `src/cygnusx/core/span_store.py`（或同级新增上下文模块） |
| MinIO 读写先例 | `src/cygnusx/infrastructure/storage/minio_store.py` |
| 房间/turns/邀请/流程报告 API | `src/cygnusx/api/v1/agentteams.py` |
| 最小用户目录 API | `src/cygnusx/api/v1/users.py` |
| 房间与过程记录模型 | `src/cygnusx/infrastructure/database/models/chat.py` |
| 通知 | `src/cygnusx/infrastructure/database/models/notification.py`、`src/cygnusx/api/v1/notification.py` |
| Bridge trace 与 requester | `integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py` |
| Gateway 透传与 Matrix 原语 | `integrations/agentteams/gateway/cygnusx_agent_gateway/` |
| 房间、Case 与通知 UI | `frontend/src/views/AgentTeamsRoomView.vue`、`frontend/src/views/AgentTeamsCaseView.vue`、`frontend/src/components/NotificationDrawer.vue` |
| 数据库迁移 | `alembic/versions/*agentteams*` |

## 12. 交付验收门（用户手测优先）

单元测试只证明局部行为，不能替代下列真实端到端验收。每项都需要保存可复查证据。

| 顺序 | 场景 | 必须证明的结果 |
|---|---|---|
| 1 | 邀请接受 | owner 在 UI 邀请账号 B；B 收到通知并从 UI 接受；B 的房间列表出现 `role=invited`，Matrix 身份已入房 |
| 2 | 拒绝、移除与删房 | B 拒绝后为 `declined`、不见房间；owner 可见拒绝记录并再次邀请；owner 移除 B 后 B 访问为 403 且 Matrix 已离房；删房使 owner 与所有 accepted member 离房 |
| 3 | 多轮过程记录 | 运行至少两轮、含工具调用的真实会诊；每次调用均有符合 key 规范的 MinIO 对象，DB 行数等于调用数，messages/输出/reasoning 与在线流一致 |
| 4 | 记录容错与追踪 | 断开 MinIO 后模型调用仍完成；管理端按 `agentteams:{case_id}` 找到完整 span，并能从 span 的 `agentteams.turn_record_uri` 定位记录 |
| 5 | owner 历史回看 | 刷新/重登后，owner 能从 turns 列表逐轮展开 prompt、reasoning、输出和工具调用 |
| 6 | 成员真实归因 | B 发言并触发多轮 Case；房间 SSE 的 `actor` 是 B，turns 的 `actor_user_id` 是 B，`requester_ref` 仍为 owner |
| 7 | 字段与操作授权 | B 能读摘要、工具原文与输出，但详情没有 messages/reasoning；B 删除房间和消费立项确认均被拒绝 |
| 8 | 回归 | 既有房间 SSE、虚拟列表、事件游标、Bridge 事件重放及独立 turns 回看均正常；Bridge 重启不丢 turns |
| 9 | 流程报告 | owner 导出并离线打开 HTML；随机 3 个 TRN 短码可反查 turns/MinIO，事件/产物都有完整 ID 和复制按钮；member 导出不含 prompt/reasoning 且有裁剪标注；环境快照可见；血缘中存在报告 `ART` 行，其 `checksum_sha256` 与下载文件字节哈希一致 |
| 10 | 可选真实栈自动验收 | 在可用 JWT、Bridge、PostgreSQL 和 MinIO 环境执行 `AGENTTEAMS_LIVE_E2E=1 CYGNUSX_E2E_BASE_URL=http://localhost:8000 CYGNUSX_E2E_TOKEN=<JWT> uv run pytest tests/e2e/agentteams/test_live_foundation_e2e.py -k e2e10 -v`；用例创建 Case、生成报告、经 JWT 下载并检查 HTML，随后取消 Case |

## 13. 已知边界与后续路线

- `room.agent_stream` 的持久流写放大与镜像刷屏问题不在本次改造范围；过程记录不能借此掩盖。
- Bridge CaseStore 的内存先改后持久化窗口、跨服务 `correlation_id` 写入点和会诊异常事件的
  `causation_event_id` 仍是既有工程债。§8.2 的 `trace_id` 透传已经落地；此处挂账的是独立的
  审计链 `correlation_id` 写入点，当前仍为空白。
- “重跑此轮”可在本架构稳定后利用保存的 prompt、模型和 sampling 单独立项；严格可复现实验
  需要额外冻结数据快照、工具版本和运行环境，本期不承诺。
- 路线 B 的 Bridge 原生成员列表、多人 requester 和反向同步需独立设计与迁移；不得在 A1+
  施工中隐式混入。

## 14. 通用流程路径（提示词层 + 通用能力校验）与领域包沉淀路线 · 2026-08-27

> **背景**：以 tnpd 单基因系统发育树方案评审为契机确认的设计口径——"经理出方案 →
> 各阶段分派给专门 Agent → 汇总交付"不依赖预先编写的领域包也能运转，但未命中
> `data/ai/domains/*.yaml` 时缺少能力匹配与阶段完整性的硬约束。本期决策：**先用提示词层
> 实现通用路径并补齐通用能力匹配软校验，后续按使用频率将跑通的流程沉淀为领域包**。
> 领域锚点模式（如 `domains/phylo.yaml` 的 `assignments.rules` + `validate_plan` 强制校验）
> 仍是已定义领域的最高质量路径，本节不改变其优先级。
>
> **施工状态（2026-08-27）**：§14.2 提示词骨架与能力匹配软校验均已落地（实现位置见
> §14.2 末），单测覆盖于 `tests/unit/test_overdrive_plan_constraint_service.py`；
> 剩余后续项见 §14.4。

### 14.1 现状基线（as-built）

未命中任何领域包时，框架已具备完整的自由规划管线，缺的是质量保障而非功能：

- **规划**：`select_lead_planner`（`overdrive_planning_service.py:858`）在领域评分全 0 时
  兜底到 `agent-general`；Manager LLM 依据 `build_overdrive_agent_catalog`
  （`overdrive_control.py:702`，注入各 Agent 的 `capability_scope`/`default_role`/
  `accepts_inputs`/`produces_outputs`）自由生成阶段拆分与分派。
- **校验**：`overdrive_run_service.py:93-133` 的结构校验与领域无关、始终生效（task_id 唯一、
  agent_id 真实存在、depends_on 合法、契约字段齐全）；但锚点校验
  `apply_authoritative_plan`（`overdrive_plan_constraint_service.py:297`）在无权威规则时
  直接放行，**没有任何能力匹配检查**——派错 Agent 会静默通过。
- **执行与汇总**：与领域模式共用 parallel_subagents 拓扑波次分派与 DeliveryAssembler
  汇总，不依赖领域配置。

### 14.2 本期施工：通用阶段骨架提示词

在 `OVERDRIVE_MANAGER_PROMPT`（`chat_service.py:440-476`）增加"未命中领域包时"的规划规则，
作为 `{authoritative_anchors}` 为"无。"时的补充约束：

1. **通用四阶段骨架**：计划默认按 输入核验 → 核心分析/实现 → 可视化/解读 → 汇总交付
   组织；任务可合并但不可缺省"输入核验"与"汇总交付"，缺省时必须在 speech 中说明理由。
2. **能力匹配选派**：每个 assignment 的 `agent_id` 必须依据 catalog 中候选专家的
   `capability_scope` 与 `default_role` 选择，并在任务描述中写明选派理由；禁止仅按名称
   字面猜测分工。
3. **交接契约**：每个任务必须写明 `accepts_inputs`/`produces_outputs`，下游任务的
   inputs 必须能由上游 outputs 满足。
4. **领域优先**：命中领域锚点时锚点规则优先，通用骨架仅约束锚点未覆盖的剩余阶段。

提示词是软约束，不替代校验。实现位置：

- 提示词：`OVERDRIVE_MANAGER_PROMPT` 新增规则 6.1（通用四阶段骨架）并强化规则 9
  （选派须在 task 描述注明能力依据），`chat_service.py`。
- 通用能力校验：`validate_capability_match` 与 `_apply_generic_capability_check`
  （`overdrive_plan_constraint_service.py`）——无领域锚点时按通用能力组
  （可视化/绘图、代码/脚本执行）核对任务文本与 Agent 身份
  （agent_id/name/category/capability_scope/capability_tags），错配且目录中另有 Agent
  覆盖时请求 Manager 修复一次；修复未果不阻断通用流程，违规项随 `plan_violations`
  保留供观测。`build_repair_prompt` 按有无锚点切换修复提示词文案，两个修复调用点
  （`overdrive_control.py` 的 `repair_overdrive_plan` 与 `chat_service.py` 的
  plan_builder）统一改用它。
- 开关：`overdrive_capability_check_enabled`（默认开，`config.py`），关闭即回退纯
  LLM 自由规划。

### 14.3 领域包沉淀路线

通用路径兜底长尾需求；同类流程**复现 2–3 次以上**即沉淀为 `data/ai/domains/<domain>.yaml`，
享受锚点硬约束。建包规范：

- **粗粒度锚点**：每域 3–6 条 authoritative 锚点，描述"必须有什么阶段、谁来干
  （`agent_match`）、交接什么产物"；阶段内部细节留给执行 Agent 与其 `skill_ids` 挂载的
  领域知识（如 `skills/bio_skills/`），不把框架变成僵化流水线。
- **分支决策前置**：方案分叉（如定根策略、是否修剪）用 `intake.questions` 与 `slots` 在
  规划前问清，不写成多套互斥锚点。
- **marker 去重**：新增 `domain_markers` 前先与既有包比对，避免多包重叠命中导致路由歧义；
  `question_filters` 随 marker 同步维护。
- **契约对齐能力**：`produces_outputs`/`accepts_inputs` 对照目标 Agent 的
  `capability_scope` 与已挂载 skill 编写，不承诺执行侧没有的产物。
- **热加载**：`DomainPackLoader.reload_if_changed`（`domain_pack_loader.py:34`）按文件签名
  自动重载，新增/修改领域包无需重启；单包校验失败不影响其他包。

首个沉淀案例：tnpd 系统发育树流程，将 `domains/phylo.yaml` 现有 `phylogeny-build` 粗锚点
拆分为 输入校验（agent-code）→ 比对与修剪（agent-code）→ 建树与定根（agent-code）→
树可视化（agent-viz）→ 报告交付（agent-delivery）的锚点链，并在
`prompt_injections.manager_notes` 补充分派口径。

### 14.4 后续路线（不在本期）

- **能力组扩充**：通用能力表当前只含可视化与代码两组边界清晰的能力；数据核验、
  交付报告等组误报率偏高，待真实运行样本积累后再评估是否加入。领域级选派约束不
  进通用表，一律沉淀到领域包。
- **catch-all 兜底领域包**：给 `DomainRegistry.match_domains`（`domain_registry.py:48`）
  增加"无命中时兜底 pack"语义，使通用四阶段骨架也享受锚点硬约束。
- **领域包半自动生成**：利用既有热重载，由新领域请求触发领域包草稿生成，把"支持任意
  领域"转化为"领域包快速注册"。

### 14.5 验收要点

| 场景 | 必须证明的结果 |
|---|---|
| 通用路径规划 | 构造不命中任何领域包的执行类请求；计划包含输入核验与汇总交付阶段，每个 assignment 的 agent 与 catalog 能力声明一致，契约字段齐全 |
| 领域优先不回归 | phylo 等已定义领域的锚点校验、修复、合并行为与施工前一致；通用骨架不改变锚点覆盖阶段的分派 |
| 沉淀闭环 | tnpd 流程经扩充后的 phylo.yaml 执行：锚点链各阶段由 `agent_match` 指定 Agent 承接，交付物含 Newick + 树图 + 方法学报告 |

## 15. 模块清单（并入自 2026-08 框架研究 §三）

> 与 §11 关键文件地图互补：§11 按本期改造责任列主要位置，本节按 2026-08-21 框架研究快照
> 列出全量模块职责。本节为快照时点信息，行号与部分细节以当前代码为准；本文 §5–§7 所述
> turn recorder / flow report / 成员邀请能力是 08-22 断面在其上叠加的演进。

### 15.1 API 层端点分类

- `src/cygnusx/api/v1/agentteams.py`（挂 `prefix="/agent-teams"`）：三类端点
  - **集成端点**（`X-Integration-Token` 认证，供 Gateway 回调）：`GET /capabilities`、
    `POST /consultations/scientific-interpretation`
  - **房间端点**（2026-08-21 新增，`CurrentUserId` 认证 + owner 归属校验）：
    `POST /rooms`（建房即供给 Matrix 房间，**不建 Case**）、`GET /rooms` /
    `GET /rooms/{id}`、`POST /rooms/{id}/messages`、`POST /rooms/{id}/confirm-proposal`
    （立项确认/修改/取消）、`GET /rooms/{id}/events`（复合游标
    `ns:<id>|case:<id>` 双流归并分页）、`GET /rooms/{id}/events/stream`（SSE）。
    邀请/成员/turns/流程报告端点为其后续扩展，契约见 §6。
  - **用户端点**（Case 级，旧路径保留兼容）：Case CRUD、审批/修订/变更决策、
    `POST /cases/{id}/messages`、`GET /cases/{id}/events[ /stream]`、产物受控读取、
    `GET /cases/{id}/audit-chain`（审计链统一查询入口）、`GET /role-labels`、`GET /status`
- `src/cygnusx/api/v1/chat.py`：`POST /sessions/{session_id}/agentteams-upgrade`
  （L2→L4 升级决策 accept/dismiss）
- `src/cygnusx/api/v1/admin/agentteams_bridge.py`：管理员配置 Bridge 接入（URL + 四个身份
  令牌，加密落库）

### 15.2 Application 服务层（`src/cygnusx/application/services/`）

| 文件 | 职责 |
|---|---|
| `agentteams_service.py`（`AgentTeamsService`） | Bridge 的 httpx 客户端适配器：Case 生命周期代理；四身份令牌管理；`provision_case_room` 建 Matrix 房间；`create_room_namespace()` 建房间命名空间记录；`bind_case_room()` 立项后绑定房间与 Case；`source_case_id` 透传（followup 关联上一 Case） |
| `agentteams_room_service.py` | 房间实体 CRUD（主库 `agentteams_rooms`）、归属校验、房间消息、复合游标事件聚合、有界 SSE、`confirm_proposal` 原子消费一次性 token；`build_room_proposal`/`persist_room_proposal` 立项卡构造。08-22 断面叠加成员/邀请 CRUD 与通行条件"owner 或 accepted member"（§4.2/§4.3） |
| `agentteams_room_response_service.py` | **房间消息响应回路核心**：Redis 互斥锁 + 幂等去重；意图分类（chat/clarify/execute/tool_execute）→ `respond_room()` 按房间绑定态分流（未立项走命名空间、已立项走 Case）；`_emit_case_proposal` 立项确认卡；终态后 EXECUTE 出 followup 卡（继续关联/新建工单）；correlation 字段（causation_event_id / answer_to_event_id）落事件 |
| `agent_consultation_service.py` | **会诊执行内核**：组装上下文 → 硬性门禁 → `ParallelSubAgentService.run`（LangGraph ReAct，`safe_only` 只读）→ 结构化信封 `ConsultationEnvelope`；`_BridgeEvidenceProjector` 投影工具调用证据 |
| `agentteams_capability_registry.py` | **单一权威能力目录**（2026-08-21 统一）：从 `data/ai/*.yaml` 派生运行时快照（60s TTL 单例缓存）；`snapshot()` 含 `chat_router_catalog` / `flow_router_catalog` / `registered_agent_ids`，chat LLM 路由与房间关键词路由共用同一快照源 |
| `agentteams_upgrade_advisor.py` | L2→L4 升级触发器与编排：三条规则（显式请求必升 / Flow 步骤数≥3 / `requires_formal_delivery` 标记）+ 咨询否决词抑制；建议卡构造、上下文摘要（context_refs 协议路径 + 预检）；`AgentTeamsUpgradeService` accept/dismiss 编排；OTel counter `agentteams.upgrade.events` |
| `agentteams_audit_events.py` | 审计事件分级一处显式定义：`OPERATIONAL_EVENT_TYPES`（与 Bridge 同口径互注同步）、`RETAINED_HIGH_FREQUENCY_BUSINESS_TYPES` 白名单、`classify_event_type` / `extract_correlation` |
| `agentteams_audit_chain_service.py` | audit-chain 聚合：Case 流 + 绑定房间命名空间流合并去重、按 recorded_at 排序、`broken_links` 断链检测；用户态归属校验入口 + 运维态 manager 入口 |
| `agentteams_usage_service.py` | 会诊 token 用量写入合成系统会话，按 `ai_token_cookie_rate` 扣饼干（message_id 幂等） |
| `agentteams_case_watch_service.py` | beat 驱动：监视绑定 Case 的聊天会话，状态变化写系统通知；终态停止监视 |
| `agentteams_case_event_consumer_service.py` | 每绑定 Case 维护有界 Bridge SSE 消费，经 `CaseRoomProjector` + Redis pub/sub 推到聊天前端 |
| `agentteams_room_gateway_service.py` | Matrix Gateway 纯 HTTP 客户端（建房 / ensure_users / 发消息 / SSE sync） |
| `agentteams_room_sync_service.py` | Matrix→平台反向同步；`room-` 前缀 case_id 的回投改派房间命名空间响应任务 |
| `agentteams_intent_router.py` / `agentteams_route_decision.py` | 聊天意图→Flow 关键词路由（trigger_hints 来自 flows YAML）；**路由目标校验注册表成员资格**，未登记降级统一 fallback 并记审计日志 |
| `agentteams_mention_resolver.py` | 房间 @ 解析（manager / broadcast / 具体 agent），输出 `dispatch_mode` |
| `agentteams_quality_gate_service.py` | 确定性质量门禁：按 flow YAML `delivery.thresholds` 评估，先于 LLM 评审 |
| `agentteams_bridge_settings_service.py` | Bridge 配置 DB 持久化，令牌加密落库 |

### 15.3 异步任务层（`src/cygnusx/infrastructure/celery_app/tasks/agentteams.py`）

- `respond_to_room_message`（Case 房间）与 `respond_to_room_namespace_message`（未立项
  房间）→ `AgentTeamsRoomResponseService.respond` / `respond_room`
- beat 周期任务：`watch_cases`、`consume_case_events`、`sync_case_rooms`、
  `requeue_stale_tasks`、`reconcile_approval_timeouts`、`cleanup_evidence`，全部用 Redis
  分布式锁防多 worker 并发

### 15.4 独立部署组件（`integrations/agentteams/`）

- **`bridge/`**（独立 FastAPI 服务，不 import CygnusX 任何代码，2026-08-21 起无状态化；
  持久化口径见 §2.1）：
  - `app.py`：全部 REST 端点；`/healthz` 含
    `minio_enabled/minio_reachable/minio_last_write_latency_ms`
  - `service.py`（`BridgeService`）：**16 态 Case 状态机**
    （`queued→received→planning_running→…→delivery_ready→closed`）+ Work Item 状态机
    （租约 claim、重试预算、审批信封）；质量门禁、交付 manifest；`create_case` 分流
    `_create_room_namespace`（房间命名空间记录不排队、不转 planning、不进用户 Case
    列表/配额/GC/指标，靠 `record_kind="room_namespace"` + `room-` 前缀双重过滤隔离）
  - `minio_store.py`：MinIO 适配层——事件流 append（读-改-写尾卷 + per-case asyncio 锁，
    超 50MB 按天分卷）、快照 envelope、启动恢复（见 §2.1）
  - `case_store.py`：MinIO 模式从 MinIO 恢复（fail fast）、`_persist` 逐 case 写快照
    （内嵌 last_event_id）后再更新 Redis 热缓存；本地 JSON 路径废除
  - `audit.py`（`AuditStore`）：写入顺序硬约束 **MinIO 落盘 → Redis 热缓存 → 内存索引 →
    `_notify`（mirror/SSE）**；`OPERATIONAL_EVENT_TYPES` 拦截为 Redis 指标计数；
    `metrics()` 暴露 operational 聚合计数
  - `migrate_to_minio.py`：一次性迁移 CLI（本地 JSON → MinIO → 逐 case 对账，不平非零退出）
  - `room_mirror.py`（`AuditRoomMirror`）：`room.*` 事件镜像进 Matrix（防回声、截断、
    瞬态事件跳过）
- **`gateway/`**（独立 FastAPI 服务，双职能）：会诊网关（策略校验、按 case 护栏 → 回呼
  主后端）+ Matrix 网关（密钥隔离）
- **`worker/`**：外部 Worker 轮询——claim → 只读项走会诊回呼；写操作项必须人工审批后由
  `analysis-worker` 提交
- **`teams/bioops-delivery.yaml`**：纯描述性文档；运行时事实源是 `data/ai/*.yaml`（见 §17.3
  M7 收口）
- **`skills/contracts.yaml`**：skill→Bridge 端点的稳定契约

配置与数据层（`data/ai/` 运行时事实源与存储分层表）与本文 §9 一致，不再重复；
`agentteams_manager.yaml` + `prompts/agentteams_manager.md` 为 Manager 独立人格配置
（见附录 A 注）。

## 16. 演进史与遗留问题（并入自 2026-08 框架研究 §十）

> 与 §13 互补保留：§13 是现行架构口径下仍挂账的边界，本节保留 2026-08 全月的演进主线、
> 修复档案与当时的遗留清单作为背景。原框架研究 §八 以四档制（代码就绪 → 已提交 → 已验证
> → 已上线）标注 L4 四前置条件，当时全部处于"代码就绪"档；该口径已被本文开头的
> 08-22 状态口径（工作树已落地实现、待 §12 真实双账号验收）所取代。

演进主线：**Overdrive 超频（08 初）→ 协作室 M1–M7（08-12~13）→ 部门协作 Phase 1–3 →
08-19 生产事故根因调查 → 08-20 Manager 人格分层 + 框架调研 → 08-21 MinIO 化 + Case 解耦 +
L4 前置收尾 → 08-21 L4 符合度审查 + 安全/正确性加固 → 08-21 v3 复审八项修复 → 08-21 双线
施工（地基真实栈 e2e 验收 + 七项 hotfix，见下）**。

**08-21 双线施工**（《协作室双线施工任务书-三件套实现与地基e2e验收.md》Track B）：11 条
地基用例在真实栈（compose 全套 + MinIO + 5 个 agentteams worker）首轮验收 4 绿/1 半绿/
3 红/1 阻断/2 未覆盖，产出 5 个地基 bug 档案；随后主干 hotfix 七项并逐项复验——
**BUG-01** 建房 500（MissingGreenlet 懒加载）、**BUG-02** 立项卡不落库（celery 任务无
commit）、**BUG-03** preflight 派单硬编码别名（`_canonical_work_item_target` 经 capability
snapshot 解析 canonical identity，端到端目击 preflight-01 target=agent-data 被专业池认领）、
**E2E-2** limit 钳制、**E2E-9** 空页死循环；复验中新发现 **BUG-04**（规划校验自愈 3/3 全败
停死 `waiting_for_correction`，修复：会诊信封补流程型 TaskSpec 完整骨架 + sample_sheet
list 形态明示）与 **BUG-05**（工具错误信封缺顶层 error 致事件流摘要丢失真实原因 + task_id
描述澄清），均已修复并各带单测。修复后全链路重跑：规划 3 次尝试内通过 →
planning.frozen → preflight completed → approval_pending。验收套件已固化为
`tests/e2e/agentteams/test_live_foundation_e2e.py`（`AGENTTEAMS_LIVE_E2E=1` 门控，真实栈
HTTP 驱动；对应本文 §12 第 10 项）。全部证据在 `evidence/e2e-2026-08-21/`。

**08-21 审查修复后已闭环的原遗留项**：#2 `room.agent_stream` 已瞬态化（不进 MinIO 持久流、
不进 Matrix 镜像，仅 Redis/内存供 SSE 打字机；其持久流写放大问题另见 §13 首条）；#3 会诊
异常事件已带 `causation_event_id`（`run_consultation` 调用链透传触发 event_id）；#6 CaseStore
已改 persist-then-commit（23 处调用点顺序反转，快照写失败内存态不推进，且 `_persist` 改
增量写；§13 所列"内存先改后持久化窗口"为对该机制剩余窗口的现行口径）；#8 幂等 receipt 已
持久化 MinIO（`receipts/{key}.json`，恢复不依赖事件重放）。审查新发现的安全项同日修复：
B1 审批旁路（approval-authority 不可铸 worker token、审批 token 绑定 plan_hash）、
B2 evidence 身份白名单 + worker 因果锚点强制、B3 confirm_token 全出口脱敏（复审 B1 进一步
闭环为"写入后即脱敏"，见 §4.5）+ owner 显式断言。

**08-21 v3 复审八项修复**（《协作室框架文档v3复审问题清单》）：
- A1 房间立项 Case 接入与旧路径一致的项目物化链路（`_resolve_case_project`：立项卡 project
  引用 → followup 继承源 Case 项目 → `get_or_create_project_by_name`，取名口径与前端
  `buildCaseProjectName` 一致）；
- A2 复合游标归并截断到 limit + 游标按截断后保留集重算 + tie-break 统一
  `(recorded_at, event_id)`（共享 `event_stream_sort_key`）；
- A3 @直答失败/超时（30s 可配，`agentteams_direct_timeout_seconds`）Manager 降级接管 +
  可见降级消息 + `room.agent_timeout` 审计；
- B1 confirm_token 改"写入后全出口脱敏"（owner 可不带 token 确认，token 为可选 API
  nonce，见 §4.5）；
- B2 快照口径澄清（见 §2.1）；
- B3 participants 来源注明（见 §4.5）；
- C1 Bridge `/v1/metrics` 增加房间事件量指标（`room_namespace_count` /
  `room_events__room-*`），GC/归档口径文档化
  （`docs/info/26.8.21/协作室房间事件GC与归档口径.md`）；
- C2 自建 agent 缺失注册表时 warning 日志（300s 节流）+ veto 命中写遥测（event=vetoed，
  含命中词/摘要/session id）+ "介绍"词表收窄 + 上线前盘点脚本
  `scripts/check_custom_agents.py`。

**08-21 时点遗留问题清单**（按当时优先级；多数已被本文 §12/§13 或后续施工接续，保留备查）：

1. **分组提交验收未执行**（当时唯一阻断项）：218+ 条改动对账表与分组计划已产出
   （`docs/info/26.8.21/协作室工作树对账与分组提交计划-2026-08-21.md`），夹带项归属与
   hunk 拆分待用户决策后提交；双线施工的七项 hotfix 也随工作树待提交。
2. 真实服务 e2e 已执行一轮并修复复验（见上双线施工）：剩余缺口为审批→执行→交付段（需
   真实审批触发计算任务）、E2E-4/6/11 的故障注入/前端渲染子项、live 套件进 CI 默认执行
   （需 CI compose 矩阵）；`waiting_for_correction` 无预算耗尽显式终态；BUG-05 的 live
   success 标记疑点待查。
3. L2→L4 的 Phase D"LLM 兜底"未实现（仅 trigger_hints 子串匹配，veto 可审计与词表收窄
   已修）。
4. 房间删除/归档端点未实现（GC 口径已定档未实施）；房间列表无最后消息预览字段。
5. @直答成功不落幂等标记（`direct_responded` 不在成功终态内，重试可能重复直答）——改动前
   即如此，待评估。
6. `correlation_id`（跨服务 trace）已定义提取口径，尚无写入点产生（现行口径见 §13 第二条：
   §8 的 `trace_id` 透传已落地，独立审计链 `correlation_id` 写入点仍空白）。
7. 超频 Manager 的 subagents 目录（`subagents_spawnable`）仍是独立组装点，未纳入注册表
   快照。
8. DB 自建 agent 上线前需执行 `scripts/check_custom_agents.py` 盘点生产影响面（缺失告警
   已加）。
9. Bridge 层无"manager 不可作 work item target"硬校验，依赖主后端自律（低风险）。
10. Worker 并行池：pool 模式每 identity 硬编码 `max_concurrent=1`，单 Agent 多 Worker
    只能靠多副本；无 per-agent 并发上限。
11. 变更决策 resume/replan/branch 真实编排、Case 绑定项目 / 交付进"我的文件"（旧路径之外
    的深化）、provenance 三层标注、Manager LLM 真实组队仍未实现（属愿景深化/后续阶段，见
    《L4协作室与文件系统融合优化实施手册》与部门协作 Phase 2）。

## 17. 架构决策档案（并入自 room_plan 2026-08-12，08-13 增补）

> `agentteams_room_plan.md`（协作室实施总账）的 M1–M3 施工流水账已被 2026-08-21 升级与
> 本文 §2–§7 覆盖，不再搬运（**历史施工明细见 git**）。本节保留其中仍是现行决策依据、
> 未被本文其他章节覆盖的档案：Case 定位、官方兼容边界、M5/M6/M7 as-built 决策与内部
> 漂移清单、治理教训。

### 17.1 为什么保留 Case（官方无工单，平台治理四件事 + 映射表）

对照阿里云官方 AgentTeams（help.aliyun.com/zh/agentteams/，开源实现
agentscope-ai/AgentTeams）的完整兼容性排查结论：平台自研的 Bridge Case 体系与官方是两套
哲学——官方「Matrix 房间为协作底座 + 人进房间治理」，平台「Case 工单状态机 + 事件流投影」。

官方 AgentTeams **没有一等工单概念**：任务是 OSS 存储桶里的记录目录
（meta.json/spec.md/result.md）+ Matrix 房间对话流，人工审批靠"人在房间里口头确认"，无
结构化审批流。平台的 Case 是在官方缺位处长出来的**治理载体**，承载官方模型无法表达的四件事：

1. **结构化人工审批**：approval token（HMAC 签名、短时、scoped）+ plan_hash 冻结 +
   乐观锁修计划——比官方"房间里口头确认"可审计、可防伪造；
2. **质控门**：确定性硬门（mapping_rate/q30 等阈值）+ LLM 评审 + remediation 循环；
3. **计划即契约**：proposed_submission + preflight 输入快照哈希比对，执行不得偏离已批计划；
4. **审计与投影**：audit 事件流（Case/WorkItem/证据事件）既是治理记录，也是房间发言投影
   的数据源。

与官方概念的映射关系：

| 平台 | 官方对应 | 差异 |
|---|---|---|
| Case | OSS task 记录 + 房间对话流 | 平台多了状态机与审批治理 |
| WorkItem | Team Leader 在房间里派活 | 平台多了租约/重试/幂等 |
| bioops-manager | Team Leader（特殊 Worker） | 平台 manager 是桥内角色 |
| approval token 审批 | 房间内人口头确认 | 平台是结构化升级 |
| audit 事件流 | Matrix 房间历史即审计 | 平台另有独立事件存储 |

**决策（2026-08-13，用户确认）：审批/质控是平台独有价值，Case 体系保留不废弃**；不向官方
"无工单"模型倒退。这与本文 §1 不变量（立项确认、质控门、审计投影不可被破坏）同源。

### 17.2 官方兼容边界（不追全兼容）

- 不废弃 Case/审批/质控去对齐官方"无工单"模型；
- **不做官方托管版 OpenAPI（73 个管控面接口，RAM 签名）的协议级对接**——若未来接官方托管
  实例，走"自研 runtime 被纳管"路径（官方明确支持纳管自研 Agent）；
- 官方 Worker 接入协议（**LoongSuite Pilot** + bootstrap token）未公开规范，不做协议仿真。

### 17.3 M5/M6/M7 as-built 决策要点

**M5：Matrix 进数据通路（五刀，2026-08-13 全部实施）——与现行架构仍相关的 as-built 口径：**

- 第一刀（建房/镜像/用户发言）：建房走 `AgentTeamsService.provision_case_room`，失败仅
  log warning、Case 照常返回（降级事件流模式）；房间标识以 `room.created` Case 级证据事件
  持久化（`work_item_id="case"`），**bridge 审计流即 case_id → room_id 映射存储，未给
  bridge 加 schema 字段**；镜像接入点选 bridge 侧 `AuditStore.on_event → AuditRoomMirror`
  （fire-and-forget），Gateway 只写本地审计不回写 Bridge，无循环镜像（`matrix.*` 事件类型
  显式跳过兜底）；用户发言 `POST /cases/{id}/messages`（JWT、限长 4000、非归属 403）记
  `room.user_message`；开关 `agentteams_gateway_enabled` 默认关闭。
- 第二刀（Manager 响应回路）：发言后 fire-and-forget 派发 Celery
  `respond_to_room_message`；per-case Redis 互斥锁（TTL 180s）去重、锁占用即丢弃；当时
  Manager 人格优先取 `agent-general`（`_PREFERRED_MANAGER_AGENT_ID` 硬编码的由来，现状见
  附录 A）；回复落 `room.agent_message`（payload 带 `role: bioops-manager`）。
- 第三刀（typing + 反向同步）：`room.typing` 瞬时事件（现已 operational 化，见 §2.1/§16
  闭环项 #2）；反向同步 `AgentTeamsRoomSyncService`（beat `sync_case_rooms` + Redis 绑定
  hash + sync cursor 持久化），防回声靠 Gateway 打
  `com.cygnusx.source=cygnusx` 标记 + 回投事件 `via="matrix"` 跳过——双向无循环。
- 第四刀（Element 嵌入 + 用户供给）：前端消费 `element_room_url` 深链以 sandbox iframe
  嵌入；平台用户 → `cygnusx-user-<sanitized user_id>` 动态 Matrix 身份映射（主后端与
  bridge 各持一份同规则实现），Gateway `POST /users/ensure` 幂等供给；正式部署资产
  `deploy/agentteams/kubernetes/`（Tuwunel + Gateway 清单 + NetworkPolicy）。
- 第五刀（聊天式创建 + 通用 Case 自动确认）：首条消息即意图创建通用 Case；后端对聊天式
  直发缺省注入 workspace context_ref（放后端防止前端伪造引用 id）；通用 Case 经 Redis
  集合 `agentteams:auto_confirm_cases` + beat `auto_confirm_cases` 自动走审批链路（复用
  `approve_and_submit_task`，approval token 体系不变）；**流程型 Case（真实计算）绝不自动
  确认**——该边界即本文 §1 不变量"正式执行须经过立项确认"的前身与保留项。
- 剩余条目（未做）：反向同步加固（Redis 绑定丢失从 `room.created` 重建、matrix_event_id
  幂等去重、显式指数退避）；Element 内平台用户 SSO/token 下发（AppService 供给的账号
  无密码）。

**M6：Worker 凭证收敛（2026-08-13 实施）——与现行 §9 令牌三分口径相关的 as-built 要点：**

1. Worker→Bridge 可吊销 per-worker token：Bridge 新增 `WorkerTokenStore`
   （`worker_tokens.py`，Redis snapshot/本地 JSON 双模，与 CaseStore 同构，**只存 SHA-256
   哈希**）；端点 `POST/GET/DELETE /v1/worker-tokens`（manager 签发，identity + 可选
   TTL/note，原始 token 仅返回一次；吊销）；`security.require_identity` 扩展为静态
   `BRIDGE_IDENTITIES` secret **或**有效未吊销 worker token 均可通过——存量静态部署不受
   影响，可逐 worker 迁移；吊销/过期立即 401；**token 绑定 identity，header 身份与 token
   不符即 403 防冒用**。主后端代理端点
   `GET/POST/DELETE /api/v1/admin/agentteams-bridge/worker-tokens`（签发/吊销需 TOTP），
   管理面板 `AgentTeamsBridgeTab.vue` 有"Worker 令牌管理"卡片。
2. MCP 上游凭证收敛结论：MCP server 定义与凭证存放于主后端数据库 `mcp_servers` 表、在主
   后端进程内解析执行；Worker 容器是空壳、从不接触 MCP 定义或凭证——官方模型"网关持真实
   凭证"的角色由主后端进程承担，Worker 侧天然不持证。
3. 收紧 Bridge 容器凭证面：移除 Bridge 从不消费的 `AGENTTEAMS_MINIO_*` 注入，并有契约测试
   断言 Bridge 环境不含该组凭证（注意与 §2.1 的 `BRIDGE_MINIO_*` 是不同前缀：08-13 移除的
   是 Bridge 不消费的旧 MinIO 变量，08-21 MinIO 化后注入的是 Bridge 真正消费的
   `BRIDGE_MINIO_*`）。

**M7：房间拓扑与通信策略（2026-08-13 评估完成：主体不做，部分做）——拒绝表 + 最小收口 +
重估触发条件：**

侦察事实：`Case.team_id`（bridge `models.py`，默认 `bioops-delivery`）仅存取与按 team 计数
三处消费，**不参与任何路由/建房/worker 过滤逻辑**；`teams/bioops-delivery.yaml` 无任何代码
加载，角色事实源是 `data/ai/*.yaml` 的 `internal_case_role` + `features.agentteams` 经
capability registry 派生；平台无 TeamLeader/Manager 分离（bioops-manager 一肩挑、用户 =
TeamAdmin）；官方拓扑为 Team CRD 驱动 Leader Room / Team Room / per-member Worker Room /
Leader DM 四类房 + `peerMentions`/`channelPolicy`。

| 拒绝项 | 理由 |
|---|---|
| 一等 Team 资源（表/CRD/注册中心） | 与 agent YAML + registry 事实源重复；单团队无消费方；新增只会制造第二份需手工对齐的事实（`teams/bioops-delivery.yaml` 无人加载、与 registry 各自演化即是漂移实证） |
| Leader Room / Worker Room / Leader DM | 角色坍缩后无独立语义：Manager+TeamLeader 合体、用户已在 Case 房与 manager 直接对话，三类房全部坍缩进现有 Case 房；Worker Room 的平台等价物是 WorkItem 状态机 + 租约 + 审计事件（比 Matrix 私聊更可审计），worker 是主后端进程内的会诊执行体、非房间自主聊天者，建 DM 房只有零信息增量的纯投影 |
| peerMentions 等价物 | 平台是 manager 中心派发模型——worker 互不直接通信（派活走 work item，汇报走 evidence），对不存在的信道声明策略是投机抽象 |
| channelPolicy 等价物 | 单团队，无跨团队边界 |

最小收口（已实施）：`teams/bioops-delivery.yaml` 头部注释声明"描述性文档，代码不加载；
角色事实源为 `data/ai/*.yaml` + capability registry"。team 级共享房间预留路径（不实施，仅
记录）：出现"同团队多 Case 并行、需要团队总览房"诉求时，复用 `provision_case_room` 模式 +
`team_room.created` 锚点事件 + Redis team→room 绑定 + room_mirror 双路由（约 30 行）+
前端 Tab（约 100 行），合计约 0.5 天，无需 bridge schema 改动。每 agent 独立 Matrix 身份
已由 M5 第四刀覆盖，不重复立项。

**重估触发条件（任一触发即重开本节）：① 接入第二个团队（多课题组/多交付线）；② worker
获得自主发起同行会诊能力（编排模型先于通信策略变更）；③ 外部通过官方纳管路径接入多 Team
托管实例。**

### 17.4 内部漂移清单（room_plan §8.4，7 条，随当时 M4/M5 顺带修复）

| # | 问题 | 当时状态 |
|---|---|---|
| 1 | P0：`agent_consultation_service.py:215-217` 仍硬编码 workspace_execution 只允许 agent-code/agent-viz，M3 放开未走通最后一道闸 | 修复：改查 registry execution_modes |
| 2 | `mas_run_ids` 死字段（bridge models.py，无写入点） | 保留作 MAS 挂接预留，注释标注 |
| 3 | 前端 `agentTeams.ts` work item status 联合类型缺 claimed/running/awaiting_approval | 随 M4 修复 |
| 4 | `GET /v1/tasks/{id}/events`（bridge app.py）名不副实返回 task 详情 | 择机改为真事件列表或改名 |
| 5 | Bridge 容器被注入不消费的 MinIO 凭证 | M6 已收紧 |
| 6 | Gateway audit 只写本地 JSONL，无 Redis Stream 路径（与 bridge 不对称） | 随 M5/M6 评估 |
| 7 | Matrix 正式部署资产（Tuwunel/Higress Helm）缺失 | M5 第四刀已补齐（Tuwunel + Gateway 清单；Higress Ingress 未做） |

### 17.5 治理教训（压缩自 room_plan §2 现状事实）

- **Case 不自动收敛**：work item 更新只写自身状态，`reconcile_case` 存在但只能手动/管理端
  触发 → 线上出现僵尸 received case。
- **无 GC**：测试残留 case 永久留存（房间/Case 事件 GC 口径见 §16 遗留 #4 与
  `docs/info/26.8.21/协作室房间事件GC与归档口径.md`）。
- **心跳面板别名误报**：`_ROLE_ALIASES`（data-steward→agent-data 等）在统计"缺心跳
  worker"时未聚合；另见 §16 BUG-03（派单硬编码别名同类根因）与遗留 #10。
- **production_runner 硬编码矛盾**：worker 端只允许 `agent-code/agent-viz` 跑
  workspace_execution，与多数 agent YAML 已声明 `execution_modes` 矛盾——配置声明与代码
  白名单双轨必然漂移（修复路径见 §17.4 #1）。
- **默认安全姿态**：房间 agent 默认"能读用户的任务、文件、产物、指标，但不能改"
  （`safe_only=True` 只读白名单 + 6 个 `user_scoped` 只读证据工具，扩展读能力只需在 agent
  YAML 绑定只读 MCP 包、不改代码）；要写只有 workspace_execution 且 workdir 禁锢在
  `/data/cygnusx/output/agentteams/{case}/{work_item}`——该禁锢不可移除。

## 附录 A. Manager 双身份与命名红线（并入自 manager_role 评审 2026-08-20）

> `manager_role_bioinfo_department_manager_2026-08.md` 的 §1 组织模型复述（用户=甲方、
> Manager=客户经理/项目协调人、领域 Agent=部门负责人、Worker=执行员工）与本文 §1 及部门
> 协作架构文档重复，丢弃。**其 §4 建议的人格层改动已落地：`data/ai/agentteams_manager.yaml`
> + `prompts/agentteams_manager.md` 已存在（2026-08-21 框架研究 §九可证），Manager 已有独立
> 人格配置，不再以 agent-general 的 persona 作为唯一来源。** 本节保留其双身份辨析、模式
> 隔离事实与红线。

### A.1 两层身份辨析

- **安全/审计身份 `bioops-manager`（非 LLM agent）**：`teams/bioops-delivery.yaml` 声明
  （描述性文档）；Bridge `config.py` token 配置、`app.py` 多处
  `require_role(identity, "bioops-manager")` 权限控制；`room_mirror.py` 将 Manager 回复以
  `bioops-manager` 身份镜像到 Matrix。**结论：此身份不改名**——它散落在 token 配置与权限
  校验中，改名无收益、改动面大。
- **LLM 人格（Manager 回复的历史实际生成者 = `agent-general`）**：
  `agentteams_room_response_service.py` `_PREFERRED_MANAGER_AGENT_ID = "agent-general"`
  硬编码 + 回退逻辑；房间话术硬编码于同文件 `_build_question()`；名称偏好链路：前端
  `agentTeamsPreferences.ts`（默认 `'Manager'`）→ 后端注入 prompt「称呼自己为
  {manager_name}」→ 前端 `managerLabel` 展示；2026-08-20 已将前端角色后缀
  ` · 管家` 改为 ` · 生物信息部门经理`（展示层）。

改动分层与影响面（评审时判定，供后续改设参照）：

| 层级 | 改动内容 | 对通用助手影响 |
|---|---|---|
| 展示层（已完成） | 角色后缀「管家」→「生物信息部门经理」 | 无 |
| 称呼层 | 默认 `managerName`、后端兜底名 | 无 |
| 话术层 | Manager 房间 prompt（"扮演 Manager"段，`room_response_service`） | 无（仅协作室） |
| 人格层（已落地） | Manager 独立 agent YAML（`agentteams_manager.yaml`）+ 可配置选择 | 无（与 agent-general 解耦） |
| ⚠️ 禁区 | 直接改 `general.yaml` 的 name/persona/prompt_file 或 `prompts/general.md` | **三个模式一起变，禁止** |

### A.2 三模式完全分离与唯一共享点

| 模式 | 前端入口 | 后端 API | 服务链路 |
|---|---|---|---|
| AI 助手 | `/ai` → AIChatView | `/api/v1/chat` | ChatService → agent 运行时 |
| AI 工作台 | `/studio/:sessionId?` → StudioView | `/api/v1/studio` | Studio 会话 + 沙盒执行 |
| AgentTeams 协作室 | `/agent-teams/room` | `/api/v1/agent-teams` | AgentTeamsService + Bridge + room_response_service |

三种模式入口、API 前缀、服务类**完全分离**；Manager 相关逻辑只在协作室链路内被调用。
**唯一共享点**（评审时）：Manager 回复复用 `agent-general` 的 system prompt + persona
（经 `agent_consultation_service` → `agent_service._append_persona_prompt`）；
`data/ai/general.yaml`（`name: 通用助手`）同时承载三重身份——AI 助手/AI 工作台里的通用
助手、协作室 Manager 的 LLM 人格（历史）、可招募专家（`recruitable: true`）。人格层独立
配置落地后，第一、二重身份已解耦，但 general.yaml 仍是通用助手 + 可招募专家的双重事实源。

### A.3 红线

1. **`data/ai/general.yaml` 与 `data/ai/prompts/general.md` 是多模式共享配置源，任何针对
   Manager 的个性化都不得落在这两个文件上**（改了会让三个模式一起变）。
2. 深化 Manager 人设：改 `room_response_service` 话术层，或使用独立
   `agentteams_manager.yaml` 人格层（已落地），不要动 `general.yaml`。
3. `bioops-manager` 安全/审计身份保持不变，不因展示层改名而更名。
