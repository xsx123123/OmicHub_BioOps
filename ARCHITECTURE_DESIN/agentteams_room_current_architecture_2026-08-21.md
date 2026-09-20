# 协作室（AgentTeams）最终架构 · 2026-08-22

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
  "child_session_id": "agentteams:{case_id}:child:{run_id}",
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
| `GET` | `/users/lookup?q=` | 任意已登录用户；用户名/昵称前缀精确搜索，仅返回 `id/nickname/avatar`，有速率限制 |
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
  （`overdrive_control.py:704`，注入各 Agent 的 `capability_scope`/`default_role`/
  `accepts_inputs`/`produces_outputs`）自由生成阶段拆分与分派。
- **校验**：`overdrive_run_service.py:93-133` 的结构校验与领域无关、始终生效（task_id 唯一、
  agent_id 真实存在、depends_on 合法、契约字段齐全）；但锚点校验
  `apply_authoritative_plan`（`overdrive_plan_constraint_service.py:199`）在无权威规则时
  直接放行，**没有任何能力匹配检查**——派错 Agent 会静默通过。
- **执行与汇总**：与领域模式共用 parallel_subagents 拓扑波次分派与 DeliveryAssembler
  汇总，不依赖领域配置。

### 14.2 本期施工：通用阶段骨架提示词

在 `OVERDRIVE_MANAGER_PROMPT`（`chat_service.py:410-445`）增加"未命中领域包时"的规划规则，
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
