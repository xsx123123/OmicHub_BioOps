# AgentTeams 超频模式（Overdrive）实施方案

> **文档读者**：执行本方案的 AI 工程师或开发者。
> **文档目标**：从当前代码状态出发，分阶段实现"超频模式"——用户在星尘 AI 聊天中点一个按钮（或直接用自然语言说"进入超频模式"）后，聊天界面被"团队房间"接管：Manager 自动发现当前所有可用 Agent，按用户布置的任务进行分工协作，各 Agent 的发言以独立消息（带各自头像/名字/颜色）流回现有聊天窗口；最终形态与官方 AgentTeams 的 Matrix 房间互通。
> **使用方式**：第 1~3 章是背景与设计共识（必读）；第 4 章是前后端冻结接口契约（任何实现不得偏离）；第 5 章是第一期逐步实施详案（可直接照做）；第 6 章是第二期 Matrix Gateway 详案；第 7~9 章是可选项、风险清单与执行 Checklist；第 10 章是 2026-08-04 审查与修复记录（史料的整合并入，勿再执行）。

> **合并说明（2026-09-18 文档整合）**：原 `agentteams_review_fixes.md`（2026-08-04 超频模式第一期审查修复清单）中仍有效的独有裁决已整体并入本文件第 10 章「审查与修复记录（2026-08-04）」，原文件已删除，历史见 git（修 1 与修 3 的文档回写部分已落在正文第 1/4/6/7 章，不重复）。
> **修订记录（2026-09-18）**：两个纯转述执行提示词文件 `agentteams_implementation_prompt.md`（转述本文第 4/5 章）与 `agentteams_review_fixes_prompt.md`（转述原审查修复清单）已移除——两者零独有内容、原已标注"勿再执行"，内容可查 git 历史。

---

## 1. 需求与愿景

### 1.1 用户体验目标

1. 星尘 AI 聊天页（`AgentSandbox`）和工作台页（`StudioView`）顶栏出现一个 **"超频模式"开关**（与现有 Multi-agent 开关并列）。
2. 用户也可以不发开关，直接在对话里说"进入超频模式"/"开启超频"，后端自动把本会话切入超频模式，前端开关同步点亮；说"退出超频模式"则恢复。
3. 超频模式下，用户每发一条消息：
   - **Manager**（以当前会话 agent = 星尘 AI 的人格出现）先发言：复述理解、给出分工计划；
   - Manager 从**当前所有可用 Agent**（发现机制见 2.4）中挑选 0~5 个，把子任务并行分派出去；
   - 每个被分派的 Agent 以自己的身份（名字/头像/颜色）在聊天里各发一条独立消息汇报结果；
   - Manager 最后发一条汇总消息给出统一结论。
4. 所有发言落库，刷新页面后历史完整可回放。
5. 最终形态（第二期）：上述"房间"是一个真实 Matrix 房间，用户也可以用 Element 客户端旁观/介入，与官方 AgentTeams 体验一致。

### 1.2 明确不做（第一期边界）

> **修订（2026-08-04）**：原定"第一期不碰 Matrix"的边界已在实施中突破——第二期的 Matrix 建房/消息镜像、room-events SSE 与第三期的管理面条目已随第一期**以默认关闭方式提前实现**（逐条状态见第 6、7 章标注）。以下为仍成立的边界。

- ~~第一期不碰 Matrix/Element/Bridge~~（已提前实现，默认 `agentteams_gateway_enabled=false`；未配置时自动降级为内置编排语义，"房间"对未配置用户仍是 CygnusX 内置编排）。
- 与现有 multi_agent 开关相互独立：multi_agent 控制 `parallel_subagents`/`create_agentteams_case` 工具挂载，超频控制"Manager 编排 + 多 Agent 发言"的会话形态。两者可同时开。
- 子 Agent 发言不做 token 级流式（`parallel_subagents` 是结果粒度），后续可增强。
- 不做常驻 Worker、不做房间成员管理——超频是"每轮消息一次编排"（Worker 自主驻留房间仍属第二期未完成项，见 6.3）。


---

## 2. 现状盘点（实施前必读，含精确位置）

### 2.1 前端聊天管线

- **Store**：`frontend/src/stores/agentHub.ts`（约 1835 行，Pinia `useAgentHubStore`）。
  - `AgentSession` 接口（:80-95）：已有 `mode: 'chat'|'studio'`、`multi_agent?: boolean`。新增 `overdrive?: boolean` 是同构扩展。
  - `sendMessage()`（:1195-1659）：push 用户消息（:1237-1253）→ push assistant 占位消息 `msg-ai-{ts}`、`status:'streaming'`（:1256-1272）→ 组上下文 → 调 `streamChat(...)`（:1318-1638），约 20 个回调把 SSE 事件写回占位消息。
  - 会话加载回填 `multi_agent` 在 :551 附近；新会话默认值在 :870 附近；`multiAgent` 写入会话在 :1226、传给 `streamChat` 在 :1333。
  - **关键先例**：`startAgentTeamsCaseEvents()`（:197-237）是独立于 LLM 流的第二条 SSE（`GET /api/v1/chat/sessions/{id}/agentteams-events`），手动 reader 解析 `data:` 行并把事件 push 为 `role:'system'` 消息（`applyAgentTeamsCaseEvent`，:169-190）。
- **流式 composable**：`frontend/src/composables/useAgentChatStream.ts`（657 行）。
  - `streamChat()`（:317-417）：POST `/api/v1/chat/stream`，body 在 :334-351 组装（含 `multi_agent`）。
  - `normalizeAgentStreamEvent`（:256-310）：解析 SSE 事件，**目前只提取 `type/content/reasoning/session_id/message_id`，没有 sender 字段**。
  - `handleStreamEvent`（:423-635）：chunk 类型 switch，现有类型：`text/content/message/delta/reasoning`、`tool_call`、`tool_result`、`tool_output`、`web_search`、`web_search_results`、`skill`、`plan`、`approval_request`、`approval_resolved`、`ask_request`、`route`、`handoff`、`consultation`、`collaboration_route`、`agentteams_case`、`round_limit`、`context_compressed`、`error`、`done`。
  - 现有 agent 身份表达先例：`route` 事件（:96-103，含 `agent_id/name/avatar/color/reason`）→ 消息的 `routedAgent` 徽标。
- **消息渲染**：`frontend/src/components/ai-chat/KimiMessageItem.vue`（1730 行）。
  - 头像逻辑（:658-676）：`agentAvatar==='🤖'` 或空 → Lottie 动画；否则 `agentColor` 底色 + emoji。
  - 名字（:323-326）：`aiIdentityName = message.modelName || props.agentName`。
  - `routedAgent` 徽标（:677-685）是"一条消息由哪个 agent 回答"的现有表达。
  - `frontend/src/components/ai-chat/types.ts`（:60-102）`ChatMessage` 接口——新增 `senderAgent` 字段的位置。
  - `KimiMessageList.vue:64-70` 的 `streamingMessageId` 只认最后一条 assistant 消息——所以**超频模式下每条 agent 发言必须是独立消息**，不能共用占位。
- **顶栏挂载点**：
  - 星尘聊天页：`frontend/src/components/agent-workspace/AgentSandbox.vue` 的 `sandbox-header`（:334-383），`header-right` 首项是 `MultiAgentToggle`（:348），flex + gap 10px（:511 样式）。
  - 工作台页：`frontend/src/views/StudioView.vue` 的 `studio-topbar`（:812-906），`bar-right`（:828）首项 `MultiAgentToggle`（:829，compact），绑定 computed `multiAgentEnabled`（:374-378）。
  - `MultiAgentToggle.vue`（77 行）是仿写模板：`NIcon + NSwitch + NTooltip`，`v-model:boolean + disabled + compact`。
- **关键词触发先例**：`KimiChatInput.vue:534` 发送前调 `matchWorkbenchIntent(content)`（`frontend/src/config/aiIntents.ts`）做纯前端意图切换；`/` 快捷命令（`SlashCommandMenu.vue:53-70`）只是插入文本，后端无解析。**本方案关键词判定放后端**（权威、可落库）。**修订（2026-09-11）**：该先例已不存在——`KimiChatInput.vue` 不再调用 `matchWorkbenchIntent`，`frontend/src/config/aiIntents.ts` 已删除。

### 2.2 后端 chat_service

- 文件：`src/cygnusx/application/services/chat_service.py`（约 4285 行）。
- **multi_agent 三段式写法（照抄对象）**：
  - 生效判定（:1644-1649）：请求参数优先，否则读会话 `sandbox_meta["multi_agent"]`，并写回 `session_mcp_meta`；
  - 建会话写入（:1714）；
  - 会话 DTO 读出（:4217）。
- **路由 catalog 构造**（:1344-1384）：`AgentService.list_agents(active_only=True)`（`agent_service.py:242-250`，查 `agent_templates` 表，过滤 `is_active`，按 `is_default desc, created_at` 排序）→ 排除 `features.router == true` → catalog 含 `agent_id/name/description/category`，JSON 序列化进 prompt。
- **JSON 容错解析先例**：`_extract_route_json`（:184 起）——逐个尝试所有 `{...}` 片段，取最后一个可解析且含关键字段的对象。
- **直接调并行分派的先例**（:2362-2396，统一路由 fanout，不依赖 function tools）：
  ```python
  tool_context = ToolInvocationContext(user_id=..., agent_id=..., session_id=..., db=self._db)
  from cygnusx.application.services.parallel_subagent_tool_service import ParallelSubAgentToolService
  fanout_result = await ParallelSubAgentToolService().run_parallel_subagents(
      context_summary=user_content, tasks=[...], context=tool_context)
  ```
  返回 `{success, llm_payload, ui_payload}`；自带防递归/剥控制工具/隔离 session（C1–C7 约束，见 `parallel_subagent_service.py:39` 与 `ARCHITECTURE_DESIN/multi_agent_fanout_2026-07.md`）。
- **ChatChunk 产出先例**：`yield ChatChunk(type="collaboration_fanout", metadata={...})`（:2387-2394）。
- **sandbox_meta 标准写法**（JSONB 必须整体重新赋值，否则不变更检测）：
  ```python
  meta = dict(session.sandbox_meta or {})
  meta["overdrive"] = True
  session.sandbox_meta = meta
  session.updated_at = datetime.now(UTC)
  await context.db.flush()
  ```
  现有键：`image`、`mcp_mode`、`extra_mcp_servers`、`multi_agent`、`context_pack`、`permissions`、`capabilities`、`plan`、`agentteams_case_confirmation`、`agentteams_case_status`。
- **消息落库**：`ChatMessageModel`（`src/cygnusx/infrastructure/database/models/chat.py`），会话 `ChatSessionModel.sandbox_meta` 在同文件（:19 附近）。ai_message 的持久化与 metadata 写法在 stream 主流程中（参考 :3179-3186 agentteams_case 卡片落 metadata 的先例）。

### 2.3 AgentTeams Bridge 现状与 Matrix 数据面缺口（第二期背景）

> **修订（2026-09-11）**：本节快照为实施前基线，现状已漂移——Bridge `app.py` 已增至 837 行，并新增 `/v1/rooms/{id}/archive|unarchive` 端点（`app.py:443,454`）及 `client.py`、`room_mirror.py` 模块；静态身份由 9 个增至 11 个（`config.py:38-42`，新增 `agent-rnaseq`、`analysis-worker`）；Case 模型的 `element_room_url` 字段已移除，改用 `record_kind: case|room_namespace` 区分记录类型（`models.py:247`）；前端 `AgentTeamsChatDrawer.vue` 已不存在，由 `views/AgentTeamsRoomView.vue` 取代；`AgentTeamsService.chat_room()` 已移除，建房改走 `gateway.create_room`（`agentteams_service.py:1466`）。

- Bridge 是**纯 HTTP 代理**（`integrations/agentteams/bridge/cygnusx_agentteams_bridge/app.py`，405 行单文件），端点只有 Case/WorkItem/Preflight/Approval/Task/Evidence/Health，**没有任何 rooms/messages/sync 端点，没有 Matrix 客户端**。
- Case 模型有 `element_room_url` 纯文本字段（`models.py:170`）——只存 URL 供前端 iframe，Bridge 不创建/不读写房间。
- 身份体系：9 个静态身份（`bioops-manager`、`data-steward`、`approval-authority`、`workflow-operator`、`quality-auditor`、`delivery-reporter`、`agent-code`、`agent-viz`、`agent-scrna`），`X-Bridge-Identity` + `X-Bridge-Token` 头认证，**≠ Matrix 账号**。
- Worker（`integrations/agentteams/worker/worker_runner.py:65-112`）是轮询 Bridge 收件箱（`GET /v1/work-items/assigned`）的 HTTP 客户端，**不在任何 Matrix 房间里**。
- CygnusX 侧 `AgentTeamsService.chat_room()`（`agentteams_service.py:99-129`）只返回 Element URL；前端 `AgentTeamsChatDrawer.vue:88-94` 是**纯 iframe 嵌入，无 postMessage 桥**。
- 本地开发 homeserver 是 Synapse（`deploy/agentteams/matrix-dev/docker-compose.yml`，127.0.0.1:8008）；官方生产用 Tuwunel。设计文档 `docs/26.8.1/agent_Case.md`（**失效引用：文件已不存在**）8.3 节已把 Matrix Gateway 标注为"规划中"。
- **结论**：第二期的 Matrix 数据面（服务账号、房间读写、sync→SSE、身份映射）全部需要新建，工作量集中在 Gateway 组件本身，第一期的前端渲染与契约可以直接复用。

### 2.4 Agent 注册与发现

- 存储：表 `agent_templates`（`src/cygnusx/infrastructure/database/models/agent.py:18`），字段含 `agent_id/name/description/avatar/color/category/model_id/model_engine/system_prompt/mcp_ids/skill_ids/features(JSONB)/is_builtin/is_active/is_default`。
- 种子：`data/ai/*.yaml`，`AgentService.ensure_builtin_agents()`（`agent_service.py:84` 起）同步落库。
- **星尘 AI = `agent-router`**（`data/ai/router.yaml`）：name "智能助手"、description "统一入口：自动识别你的需求并转接对应专家"、`features.router: true`。"星尘 AI"只是品牌名（`data/CygnusX.yaml:64`）。
- **"现阶段所有可用 agent"的权威定义**：`list_agents(active_only=True)` 排除 `features.router == true`——与路由器候选清单完全一致，无用户级权限概念。
- 前端 agent 列表：`agentHub.ts fetchAgents()`（:441）→ `GET /agents`。

---

## 3. 总体架构与分期路线

```
第一期（本方案主线，1~2 天）
  用户 ──► 星尘 AI 聊天 UI（+超频开关/关键词）
        ──► POST /api/v1/chat/stream {overdrive: true}
        ──► chat_service 超频编排（Manager LLM 分工 → parallel_subagents 并行 → 逐条 room_speech 事件）
        ──► 前端逐条渲染多 Agent 发言

第二期（Matrix Gateway，独立大工程）
  会话 ↔ 真实 Matrix 房间双向绑定；Manager/Worker 作为 Matrix 用户在房间发言；
  CygnusX 聊天 UI 与房间双向同步；Element 客户端可旁观/介入

第三期（可选，管理面）
  对齐官方 AgentTeams Dashboard：Worker/Team 资源管理面板、Bridge 接入向导、Case 状态实时推送
```

---

## 4. 接口契约（冻结，前后端共同遵守）

### 4.1 请求

`POST /api/v1/chat/stream` 请求体新增可选字段：

```json
{ "overdrive": true }
```

- `overdrive: bool | null`，缺省/null = 不覆盖，读会话 `sandbox_meta["overdrive"]`。
- 与现有 `multi_agent` 字段互不影响。

### 4.2 会话 DTO

会话列表/详情的 DTO 新增 `overdrive: bool`（从 `sandbox_meta["overdrive"]` 读出），前端加载会话时回填开关状态。

### 4.3 新增 SSE chunk 类型

沿用现有 `ChatChunk(type=..., metadata={...})` 形态：

**线格式注意**：所有 chunk 经 SSE 序列化层（`api/v1/chat.py`）时会执行
`data.update(chunk.metadata)`，把 metadata **拍平**到顶层——这是该层的既有惯例。
因此线上实际格式为拍平结构，下文 JSON 示例中 `metadata` 内字段在线上位于顶层。
前端按拍平格式读取。

**`mode_changed`** —— 会话模式被切换（关键词触发或开关）时发出：

```json
{ "type": "mode_changed",
  "session_id": "...",
  "metadata": { "mode": "overdrive", "enabled": true } }
```

线上实际格式：

```json
// mode_changed 线上格式
{ "type": "mode_changed", "session_id": "...", "mode": "overdrive", "enabled": true }
```

**`room_speech`** —— 房间里一个 agent 的一次发言（Manager 与 Worker 通用）：

```json
{ "type": "room_speech",
  "session_id": "...",
  "message_id": "msg-...",
  "metadata": {
    "sender": { "agent_id": "agent-rnaseq", "name": "RNA-seq 专家",
                "avatar": "🧬", "color": "#4f8ef7", "role": "manager" },
    "content": "……发言全文……",
    "round": 1
  } }
```

线上实际格式：

```json
// room_speech 线上格式
{ "type": "room_speech", "session_id": "...", "message_id": "msg-...",
  "sender": { "agent_id": "...", "name": "...", "avatar": "...", "color": "...", "role": "manager" },
  "content": "……", "round": 1 }
```

- `sender.role`：`"manager" | "worker"`。
- 一轮超频回复的事件序列：`room_speech(manager 分工)` → `room_speech(worker)` × N → `room_speech(manager 汇总)` → `done`。
- 每条 `room_speech` 同时落库为一条 `ChatMessageModel`（assistant），`metadata.senderAgent = sender`，保证刷新可回放。
- 已知扩展字段（契约外但已实现）：`mode_changed` 可带 `degraded: true`（Matrix 降级时）；`room_speech`/会话可带 `matrix_room_id`（第二期 Matrix 绑定时）。第三方对接应忽略未知字段。

### 4.4 消息持久化元数据

`ChatMessageModel.metadata` 新增键 `senderAgent`（结构与 4.3 的 `sender` 一致，去掉 `role` 也可保留）。前端历史消息渲染时从 metadata 还原 `senderAgent`。

---

## 5. 第一期实施详案（内置超频编排）

### 5.1 后端步骤

**步骤 B1 — schema 与透传**

1. `src/cygnusx/application/schemas/chat.py`：
   - `ChatStreamRequest`（:50 附近）加 `overdrive: bool | None = None`；
   - 会话 DTO（:111 附近）加 `overdrive: bool = False`。
2. `src/cygnusx/api/v1/chat.py`（:80 附近）：把 `overdrive` 透传进 `chat_service.stream_agent_chat(...)`。
3. `chat_service.py`：
   - 在 :1644-1649 同款位置计算：
     ```python
     effective_overdrive = (
         bool(overdrive) if overdrive is not None
         else bool(session_mcp_meta.get("overdrive", False))
     )
     session_mcp_meta["overdrive"] = effective_overdrive
     ```
   - :1714 建会话处写入 `sandbox_meta["overdrive"]`（默认 False）。
   - :4217 会话 DTO 读出：`overdrive=bool((s.sandbox_meta or {}).get("overdrive", False))`。
   - 凡修改 `session.sandbox_meta` 处都用 2.2 的标准写法（整体重新赋值 + flush）。

**步骤 B2 — 关键词触发**

在 `stream_agent_chat` 主流程开始处（用户文本已确定、effective_overdrive 已计算之后）插入：

```python
_OVERDRIVE_ON_HINTS = ("超频模式", "超频", "overdrive")
_OVERDRIVE_OFF_HINTS = ("退出超频", "关闭超频", "取消超频", "overdrive off")

# 伪代码：
text = user_content.lower()
if not effective_overdrive and any(h in user_content for h in _OVERDRIVE_ON_HINTS) \
        and not any(h in user_content for h in _OVERDRIVE_OFF_HINTS):
    effective_overdrive = True
    # 写回 sandbox_meta（标准写法）
    yield ChatChunk(type="mode_changed",
                    metadata={"mode": "overdrive", "enabled": True})
elif effective_overdrive and any(h in user_content for h in _OVERDRIVE_OFF_HINTS):
    effective_overdrive = False
    # 写回 sandbox_meta
    yield ChatChunk(type="mode_changed",
                    metadata={"mode": "overdrive", "enabled": False})
    # 退出当轮走普通对话流程，不进入编排
```

注意：判定用原始用户文本（大小写不敏感处理 "overdrive"），"退出/关闭"优先于"开启"判定，避免"别进超频模式"误触发。

**步骤 B3 — Manager 编排路径**

新增模块级 prompt 与新方法（放在 `ROUTER_SYSTEM_PROMPT` 附近，:181 之后）：

```python
OVERDRIVE_MANAGER_PROMPT = """你是团队房间的 Manager（人格：{manager_name}）。用户消息已进入超频模式。

候选专家（JSON 数组）：
{catalog}

规则：
1. 直接输出一行 JSON：{{"speech": "...", "assignments": [{{"agent_id": "...", "task": "..."}}]}}。
2. speech 用简体中文，先复述你对任务的理解，再说明分工（无分工则说明由你直接处理）。
3. assignments 0–5 个；仅当任务可拆为相互独立的专业子任务时才拆分，agent_id 必须来自候选清单。
4. 简单问答、闲聊、单领域问题 → assignments 为空数组。
5. 禁止输出思考过程，第一个字符必须是 {{。

用户消息：{user_content}"""
```

新增 `_run_overdrive_turn(...)`（async generator，挂在 `effective_overdrive` 为真的分支）：

1. **发现 agent**：复用 :1344-1384 的 catalog 构造（`list_agents(active_only=True)`、排除 `features.router`），**字段扩展补 `avatar`/`color`**（表里有这两列，DTO 若没有则直接在查询后取模型字段）。
2. **Manager 分工**：用当前会话 agent 的 model_config 调 LLM（复用路由器调 LLM 的方式，:1384 附近），prompt 如上；用 `_extract_route_json` 容错解析；解析失败 → assignments 视为空，speech 用 LLM 原始输出兜底。
3. yield Manager 第一条 `room_speech`（sender = 会话当前 agent 的 id/name/avatar/color，`role:"manager"`），并落库。
4. **并行分工**：`assignments` ≥1 时，按 :2355-2378 先例构造 `ToolInvocationContext` 并调
   `ParallelSubAgentToolService().run_parallel_subagents(context_summary=user_content, tasks=assignments, context=tool_context)`。
5. 从 `fanout_result["llm_payload"]` 取各子任务结果，**每个子 agent 一条 `room_speech`**（sender 从 catalog 查对应 agent 的 name/avatar/color，`role:"worker"`），逐条 yield + 落库。失败的子任务也要发一条说明（content 含错误摘要）。
6. **Manager 汇总**：把各 worker 结果拼进 second-pass prompt（"基于以上专家结果给出统一、可核验的结论，不要重复执行"），再调一次 LLM，yield 收尾 `room_speech`（manager）+ 落库。assignments 为空时跳过 4-6，只保留第 3 步的一条（或直接走普通对话路径——二选一，推荐：空分工时 Manager 直接正常回答，仍作为一条 room_speech，保持房间语义一致）。
7. 主流程分叉位置：在路由/工具循环之前，`if effective_overdrive:` 走 `_run_overdrive_turn` 并 `return`，**不再进入普通工具循环**（避免双重回答）。

**步骤 B4 — SSE 序列化与 DTO**

- 确认 `room_speech`/`mode_changed` 两个新 type 能穿过 chat stream 的事件序列化层（api/v1/chat.py 的 SSE 包装）——现有 `collaboration_fanout` 等自定义 type 已能穿透，同构即可。
- 落库消息 metadata 写 `senderAgent`。

**步骤 B5 — 后端测试**（`tests/unit/`）

- overdrive 参数优先级：请求 True/False/None × meta True/False。
- 关键词：开启、退出、"别进超频模式"不触发、已开启时说"超频模式"不重复发 mode_changed。
- Manager 输出解析：标准 JSON、带思考前缀的 JSON、纯文本兜底、assignments 超 5 截断、agent_id 不在 catalog 时过滤。
- 编排事件序列：0/2/5 个 assignments 时 room_speech 数量与顺序、worker 失败时错误发言、每条均落库且 metadata.senderAgent 正确。
- mock 掉 LLM 调用与 `ParallelSubAgentToolService.run_parallel_subagents`。

### 5.2 前端步骤

**步骤 F1 — OverdriveToggle.vue**

- 新建 `frontend/src/components/agent-workspace/OverdriveToggle.vue`，整体仿写 `MultiAgentToggle.vue`（77 行模板）：`v-model:boolean + disabled + compact`，图标换成闪电/火箭类（`@vicons/ionicons5` 的 `FlashOutline` 或 `RocketOutline`），label "超频模式"。
- tooltip 文案：未开——"开启后，复杂任务由 Manager 发现全部专家并分工协作，各专家在对话中依次发言"；已开——"超频模式已开启：团队房间接管对话，直接布置任务即可"。
- 挂载：`AgentSandbox.vue:348` 的 `MultiAgentToggle` 前/后；`StudioView.vue:829` 旁（compact）。绑定 computed（照 `StudioView.vue:374-378` 的 multiAgentEnabled 模式）读写 `session.overdrive`，流式中 `:disabled="store.isStreaming"`。

**步骤 F2 — agentHub.ts**

- `AgentSession`（:80-95）加 `overdrive?: boolean`；新会话默认 false（:870 附近）；会话加载回填（:551 附近，`s.overdrive` 来自 DTO）。
- `sendMessage()`：
  - options 加 `overdrive`，:1226 同款写入 `session.overdrive`；
  - :1333 传参加 `overdrive: options.overdrive ?? session.overdrive ?? false`；
  - **占位消息分叉**（:1256-1272）：`if (session.overdrive)` 不 push 单条 assistant 占位，改为维护 `streamingMessageId = null`，等 `room_speech` 事件逐条 push；
- 新回调（接 useAgentChatStream 的新事件）：
  - `onRoomSpeech(event)`：push `{ id: event.message_id ?? 'msg-speech-'+ts, role:'assistant', content: event.metadata.content, senderAgent: event.metadata.sender, status:'done', ts: Date.now() }` 到 `session.messages`（必须操作响应式代理，:1269 注释有强调）；
  - `onModeChanged(event)`：`session.overdrive = event.metadata.enabled`，并可 push 一条 `role:'system'` 提示（"已进入/已退出超频模式"，照 :169-190 的 system 消息先例）。
- 历史消息加载：从后端消息 metadata 还原 `senderAgent`（找现有的 messages 加载/映射处，把 `metadata.senderAgent` 透到 `ChatMessage.senderAgent`）。

**步骤 F3 — useAgentChatStream.ts**

- body 组装（:334-351）加 `overdrive: options.overdrive ?? false`；`streamChat` options 类型同步加字段。
- `normalizeAgentStreamEvent`（:256-310）：放行 `room_speech`/`mode_changed` 的 `metadata` 与 `message_id`（现有只提取少数字段，需要扩展透传 metadata）。
- `handleStreamEvent`（:423-635）新增两个 case，调用 F2 的回调。

**步骤 F4 — 消息模型与渲染**

- `types.ts`（:60-102）`ChatMessage` 加：
  ```ts
  senderAgent?: { id: string; name: string; avatar?: string; color?: string }
  ```
- `KimiMessageItem.vue`：
  - 名字（:323-326）：`aiIdentityName = message.senderAgent?.name || message.modelName || props.agentName`；
  - 头像（:658-676）：最前面加分支——`message.senderAgent` 存在时用其 `avatar`/`color` 渲染 `avatar-fallback` div（`avatar` 为空或 🤖 时才落回 Lottie）。
- 不需要动 `KimiMessageList.vue`（每条发言是独立消息，天然绕开 :64-70 的 streamingMessageId 限制）。

**步骤 F5 — 前端验证**

- `npm run typecheck`（或项目对应的 tsc/vue-tsc 脚本）与 `npm run build` 通过。
- 手动冒烟（需后端一起）：开开关 → 发"帮我同时看看 QC 结果和差异表达" → 依次出现 Manager 分工、两位专家各自发言（头像/名字不同）、Manager 汇总 → 刷新页面历史完整 → 说"退出超频模式"→ mode_changed 到达、开关熄灭、下一条消息恢复普通回答。

### 5.3 第一期验收标准

1. 开关与关键词两条触发路径均生效，状态会话级持久化（刷新/重进会话仍保持）。
2. 一轮超频回复 = Manager 分工 → worker 依次发言 → Manager 汇总，事件顺序与落库一致。
3. 每条发言有独立头像/名字/颜色；简单问题（assignments=0）不出现无意义拆分。
4. multi_agent 开关与超频开关互不影响；超频轮不进入普通工具循环。
5. 后端单测全绿；前端 typecheck/build 通过。

---

## 6. 第二期实施详案（Matrix Gateway，真房间接管）

> **提前实现状态**：第二期核心能力已按“默认关闭”方式提前实现；仅当 Gateway 配置完整且
> `agentteams_gateway_enabled=true` 时启用，Gateway 不可达时自动降级为第一期内置编排。

> 前置：第一期已完成。本章把"内置编排"升级为"真实 Matrix 房间"，与官方 AgentTeams 体验对齐。设计依据：`docs/26.8.1/agent_Case.md`（8.3 节 Matrix Gateway 规划）（**失效引用：文件已不存在**）。

### 6.1 组件与部署 ✅ 已随第一期提前实现

> 实现为**自研 HTTP/AppService 客户端**（`integrations/agentteams/gateway/cygnusx_agent_gateway/matrix_client.py`），未引入 matrix-nio；配置见 `config.py`，部署见 `deploy/agentteams/docker-compose.agentteams.yml` 的 gateway 容器与 `gateway.env.example`，冒烟脚本 `deploy/agentteams/matrix_gateway_smoke.py`。

- 新建 **Matrix Gateway** 组件（建议放 `integrations/agentteams/gateway/`，该目录已存在占位）：一个轻量 Python 服务（FastAPI），内嵌 `matrix-nio` client，持有 homeserver 服务账号（bot 或 Application Service）。
- 配置项：homeserver URL（dev=Synapse `http://127.0.0.1:8008`，prod=Tuwunel）、服务账号 token、与 Bridge 的身份映射表。
- 部署：加入 `deploy/agentteams/docker-compose.agentteams.yml`，与 Bridge 同网络；K8s 走官方 Helm 思路（Tuwunel + Gateway 两个 Deployment）。
- CygnusX 侧不直接依赖 matrix-nio，只通过 Gateway 的 HTTP API 访问房间（职责边界与 Bridge 一致：CygnusX 永不持有 Matrix 凭证）。

### 6.2 Gateway HTTP API（新建 4 类端点）✅ 已随第一期提前实现

> Gateway `app.py` 已提供 rooms 四类端点（建房/发消息/读历史/sync），CygnusX 侧经 `agentteams_room_gateway_service.py` 代理调用。

| 方法+路径 | 说明 |
|---|---|
| `POST /rooms` | 创建房间（name=`cygnusx-session-{session_id}`），邀请 Manager/Worker 身份对应的 Matrix 用户，返回 `room_id` |
| `POST /rooms/{room_id}/messages` | 以指定身份（user/manager/system）发消息进房间 |
| `GET /rooms/{room_id}/messages?since=` | 游标读房间消息历史（照 Bridge `/v1/cases/{id}/events` 的游标轮询范式） |
| `GET /rooms/{room_id}/sync` | 长轮询 homeserver `/sync` 按 room_id 过滤，转 SSE 推给 CygnusX |

### 6.3 身份映射 ⚠️ 部分提前实现

> 已实现：Gateway 以 AppService 方式供给/代理 Matrix 身份（`matrix_client.py`），子 agent 结果由 **CygnusX 代发**进房间（即下文"过渡"方案）。
> 未实现：**Worker 自主驻留房间**（监听 `m.mentions` 自主发言）——目前 Worker 仍是轮询 Bridge 的 HTTP 客户端，这是第二期剩余的最大一块工作。

- 建一张映射表（Gateway 配置或 DB）：Bridge 身份 ↔ Matrix 用户（如 `bioops-manager` ↔ `@bioops-manager:localhost`）。
- Gateway 用 Application Service 可为各身份**无密码批量供给 Matrix 用户**（官方 v1.2.0-beta 的 Matrix AppService 同款做法）。
- Worker agent 要能在房间发言，需把现有轮询 Worker（`worker_runner.py`）升级或替换为"驻房间的 agent 进程"：监听房间 `m.mentions` → 调各自能力 → 回房间发言。**这是第二期最大的一块工作量**，可先用"CygnusX 代发"过渡：子 agent 结果由 CygnusX 经 Gateway 以该 agent 的 Matrix 身份代发进房间（房间里有真实消息记录，Element 旁观可见），后续再让 Worker 自主驻留。

### 6.4 数据模型与绑定 ✅ 已随第一期提前实现（过渡方案）

> `matrix_room_id` 按过渡方案存 `sandbox_meta`（**未做** alembic 列迁移）；Case 创建透传 `element_room_url` 已实现（`agentteams_case_tool_service.py`、`agentteams_service.py`）。

- `ChatSessionModel` 新增 `matrix_room_id` 列（alembic 迁移；或先放 `sandbox_meta["matrix_room_id"]` 过渡）。
- 开启超频且 Gateway 可用时：无 room_id → `POST /rooms` 创建并绑定；有则复用。
- Case 的 `element_room_url` 字段改为可解析出 room_id，Case 房间与会话房间统一。

### 6.5 CygnusX 与前端改造 ✅ 已随第一期提前实现

> 每条 speech 经 Gateway 镜像进 Matrix 房间（`chat_service.py:_run_overdrive_turn` 的 Matrix 分支，默认关闭、降级安全）。**修订（2026-09-11）**：原回流通道 `GET /api/v1/chat/sessions/{id}/room-events`（SSE）与前端 `startRoomEvents`（agentHub.ts）**均已移除**（`tests/unit/test_overdrive_chat.py:1870` 显式断言该路由不存在）；房间回流现由 `agentteams_room_sync_service.py` / `case_room_projector.py` 承担，实时事件走 `api/v1/agentteams.py:1147` 的 `GET /api/v1/agent-teams/rooms/{room_id}/events/stream`。

- 后端：`_run_overdrive_turn` 的每条 speech 增加"经 Gateway 写进 Matrix 房间"一步；新增房间消息回流通道——`GET /api/v1/chat/sessions/{id}/room-events`（SSE，内部桥接 Gateway `/sync`），把房间里**非 CygnusX 来源**的消息（如 Element 里用户的发言、Worker 自主发言）push 进会话消息流。前端照搬 `startAgentTeamsCaseEvents`（agentHub.ts:197-237）的 reader 模式。**修订（2026-09-11）**：该 room-events 设计未按此落地，实际回流通道见上方修订注记。
- 前端：传输层仍走 `/api/v1/chat/stream`；`AgentTeamsChatDrawer` 保留为"在 Element 中打开"的旁观入口（iframe 不动）。
- 降级：Gateway 未配置/不可达时，超频自动回落第一期内置编排，并在 mode_changed metadata 里带 `degraded: true`。

### 6.6 第二期验收标准 ⬜ 未验收（端到端 Element 联调未做）

1. 开启超频自动建房并绑定会话；会话内每条发言在 Element 客户端实时可见。
2. Element 里用户发言能回流为 CygnusX 会话消息（双向同步）。
3. Gateway 宕机时自动降级为内置编排，不报错阻断对话。
4. CygnusX 进程与数据库中不出现任何 Matrix 凭证。

---

## 7. 第三期（可选，管理面优雅化）

> **提前实现状态**：第三期的 Bridge 接入向导、Case 创建入口与 Case 事件实时化已提前实现；
> Worker 生命周期仍由独立部署管理，管理面只展示心跳并提供已有的安全重协调操作。

1. **Bridge 接入向导** ✅ 已随第一期提前实现：管理后台 AgentTeams Bridge Tab 增加"一键检测 + 分步引导"，token 自动生成/校验（对齐官方 `curl | bash` 体验）。实现：`api/v1/admin/agentteams_bridge.py`（含一次性 token 生成端点）+ `frontend/src/components/admin/AgentTeamsBridgeTab.vue`。
2. **资源管理面板** ✅ 已随第一期提前实现：Worker/Team/Case 列表与生命周期操作（对齐官方 Dashboard）。实现：`agentteams_service.admin_resource_snapshot` + Bridge Tab 资源面板；Worker 生命周期仍由独立部署管理，面板只展示心跳并提供安全重协调。
3. **新建 Case 表单页** ✅ 已随第一期提前实现：后端 `POST /api/v1/agent-teams/cases` 已存在且不要求 multi_agent 开关。实现：`frontend/src/components/task/AgentTeamsCasesPanel.vue` 新建 Case 表单。
4. **Case 状态实时化** ✅ 已随第一期提前实现：20s 轮询 + 60s watch → SSE 直推。实现：`agentteams_service.stream_case_events` + `api/v1/agentteams.py` Case 事件 SSE + Bridge `events/stream`。

---

## 8. 风险与注意事项（执行时务必检查）

1. **JSONB 变更检测**：`sandbox_meta` 必须整体重新赋值再 flush（2.2 标准写法），直接 `session.sandbox_meta["x"] = y` 不会落库。
2. **占位消息分叉**：超频模式绝不能沿用"单条 assistant 占位 + 流式填充"，否则多 agent 发言会互相覆盖；必须逐条独立 push（F2）。
3. **防双重回答**：超频轮在普通工具循环之前 return，不要让同一条消息既走编排又走普通 LLM 回答。
4. **防递归**：`run_parallel_subagents` 自带 C1–C7 约束；不要在 Manager prompt 里暴露 `parallel_subagents`/`create_agentteams_case` 等控制工具给子 agent。
5. **assignments 健壮性**：LLM 可能返回 catalog 外的 agent_id、超 5 个、重复项——全部要过滤/截断/去重。
6. **关键词误判**：退出类短语优先判定；"超频"子串可能出现在正常语境（如"CPU 超频"），第一期可接受误判（用户再说退出即可），不要为此引入复杂意图分类。
7. **模型差异**：编排路径不依赖 function tools（直接调服务），所以与 multi_agent 开关不同，模型不支持 tools 也能用；但 Manager 需要能稳定输出单行 JSON，prompt 里已强调"第一个字符必须是 {"。
8. **凭证边界**：第二期 CygnusX 侧永不存 Matrix token；全部经 Gateway 代理。
9. **消息条数**：一轮最多 1+5+1=7 条 room_speech，前端不要假设固定条数；`done` 事件仍是回合结束标志。

---

## 9. 执行 Checklist

### 第一期

- [x] B1 schema/DTO/透传/sandbox_meta 三段式（schemas/chat.py、api/v1/chat.py、chat_service.py）
- [x] B2 关键词触发 + mode_changed 事件
- [x] B3 OVERDRIVE_MANAGER_PROMPT + `_run_overdrive_turn`（发现→分工→worker 发言→汇总，逐条落库）
- [x] B4 SSE 序列化穿透 + metadata.senderAgent 落库
- [x] B5 后端单测
- [x] F1 OverdriveToggle.vue + 两处挂载
- [x] F2 agentHub.ts（session 字段/传参/占位分叉/onRoomSpeech/onModeChanged/历史还原）
- [x] F3 useAgentChatStream.ts（body 字段/metadata 透传/两个新 case）
- [x] F4 types.ts + KimiMessageItem.vue senderAgent 渲染
- [ ] F5 typecheck/build 已通过；**手动冒烟（5.2 冒烟脚本）未做**
- [ ] 第一期验收 5.3：1–5 条由测试/构建覆盖，**端到端手动验收未做**

### 第二期

- [x] G1 Matrix Gateway 服务骨架 + 配置 + 部署（6.1）—— 已随第一期提前实现（自研 AppService 客户端）
- [x] G2 四类端点（6.2）—— 已随第一期提前实现
- [~] G3 身份映射 + AppService 用户供给（6.3）—— AppService 供给与 CygnusX 代发已实现；**Worker 自主驻留房间未做**
- [x] G4 matrix_room_id 迁移与绑定（6.4）—— 已按 sandbox_meta 过渡方案实现；alembic 列迁移未做
- [~] G5 CygnusX 桥接 + 降级（6.5）—— 桥接镜像与降级已实现（默认关闭，降级有测试覆盖）；**修订（2026-09-11）**：原 room-events SSE（`/api/v1/chat/sessions/{id}/room-events`）已移除，房间回流改由 `agentteams_room_sync_service.py` / `case_room_projector.py` + `/api/v1/agent-teams/rooms/{room_id}/events/stream` 承担
- [ ] G6 第二期验收（6.6）—— 端到端 Element 联调未做

### 第三期（可选）

- [x] Bridge 接入向导 / 资源管理面板 / 新建 Case 表单 / Case 状态实时化（第 7 章）—— 均已随第一期提前实现

---

## 10. 审查与修复记录（2026-08-04）

> **来源与整合说明**：本章为 2026-09-18 文档整合时并入的史料，原文是 `agentteams_review_fixes.md`——对第一期实现的后端/前端双份审查报告（2026-08-04）形成的修复清单，共 6 项修复（每项含问题、证据位置、修复步骤、验证方法），已全部执行完毕。**结论回顾**：第一期本体可交付（契约点全落实、51 项后端测试全绿、前端 type-check/build 通过）。原文头注的时点说明仍然成立：文中所述修复已执行或已演进，部分引用（路径、行号、测试文件）为 2026-08-04 时点位置、可能已失效；**请勿按本章再次执行，当前实现以代码为准**。
> 修 1（§4.3 SSE 线格式拍平的契约回写）与修 3 的文档回写部分（§1.2 修订注、第 6/7 章"已随第一期提前实现"标注）已落在本文正文，此处不重复；本章保留仍有效的独有裁决与执行口径。执行要求（当时口径）：修代码保持最小改动；禁止 git 任何写操作（commit/push/reset）；不引入新依赖。

### 10.1 修 2：parallel_subagents 工具 schema 与运行时对齐（fan-out 最少 1 个子任务）

- 背景：实现删除了 `parallel_subagent_service.py` 中"fan-out 至少 2 个子任务"的运行时校验（超频单 assignment 分派需要），LLM 面工具契约需同步：`tool_configs/tools_schema.yaml` 的 `parallel_subagents` `tasks` 参数 `minItems: 2` → `minItems: 1`，描述中"2–5 个"改为"1–5 个"；`ARCHITECTURE_DESIN/multi_agent_fanout_2026-07.md` 中 parallel_subagents 的"至少 2 个/2–5 个"能力下限描述同步改为"1–5 个"。
- **不得误改的区分口径**（要改的只是工具 schema 的能力下限——1 个也合法）：
  - `chat_service.py` 的 `ROUTER_SYSTEM_PROMPT` 与 `MULTI_AGENT_SYSTEM_PROMPT_SUFFIX` 里"可拆成 2–5 个独立子任务才 fanout"是**何时拆**的语义建议，保持不变；
  - 统一路由 fanout 的 `len(fanout_tasks) >= 2` 是路由自动分派的门槛，保持不变。
- 断言 minItems=2 或"至少两个子任务"报错文案的测试需同步更新（`grep -rn "minItems" tests/ tool_configs/`、`grep -rn "至少.*子任务\|2 个子任务" tests/`）。
- 验证口径：`grep -n "minItems" tool_configs/tools_schema.yaml` 显示 1；`python -c "import yaml; yaml.safe_load(open('tool_configs/tools_schema.yaml'))"` 解析通过；相关单测全绿。

### 10.2 修 3："接受二/三期提前量"决策与加固

- **决策**：实现提前完成了原第二期（Matrix Gateway：`agentteams_room_gateway_service.py`、`_run_overdrive_turn` 内 Matrix 建房/消息镜像、当时的 room-events SSE、Gateway `matrix_client.py`）和原第三期（admin Bridge 向导、Case 事件推送、新建 Case 表单）。审查确认降级安全（gateway 默认 disabled，未配置时超频正常，Matrix 失败仅记日志）。**默认决策：接受提前量**，做以下加固；若产品决定拒绝，走末尾回退方案。
- **三个降级测试用例**（`tests/unit/test_overdrive_chat.py` 追加）：
  1. gateway enabled=True 但不可达（mock httpx 抛 ConnectError）→ 超频轮正常完成，room_speech 序列完整，发出 `mode_changed{degraded:true}`；
  2. gateway enabled=True、建房成功但 `post_message` 单条失败 → 仅记日志，不中断后续发言；
  3. 会话无 `matrix_room_id` 时前端 room-events 404 → 后端返回结构与前端静默处理兼容。（**注**：room-events SSE 通道已于 2026-09-11 移除，见 6.5 修订注记，该场景现由房间回流新通道的对应测试承担，以代码为准。）
- **隔离检查**：确认 `_run_overdrive_turn` 内 Matrix 分支全部在 `if gateway_service.available:` 与 try/except 内，`agentteams_gateway_enabled` 默认 False（`core/config.py`）——已确认则只需在代码注释中标注"第二期提前实现，默认关闭"。
- **回退方案（仅当决策为拒绝时执行）**：`_run_overdrive_turn` 中删除 Matrix 建房/镜像分支，保留 `agentteams_room_gateway_service.py` 与 room-events SSE（它们独立于聊天主路径，不影响），对应测试改为跳过。
- 验证口径：新增降级测试通过；`grep -n "提前实现" ARCHITECTURE_DESIN/agentteams_overdrive.md` 有命中。

### 10.3 修 4：预置红测试（HEAD 上即红，非本次改动引入）与"先判对错再改"原则

- **问题 A**：`tests/unit/test_agent_router.py` 2 个失败——路由 `intent` 期望 `delivery_case` 实得 `case`（路由意图逻辑与测试漂移）。
- **问题 B**：`tests/unit/test_agent_router_dispatch.py` 2 个失败——`data/ai/` 注册表新增 3 个 scrna agent，未同步进 router 候选表。
- **裁决原则：先判对错，再改过期的一侧，禁止为通过而改**：
  - 问题 A：读失败用例与 `chat_service.py` 路由意图归一化逻辑（`_route_to_agent`/RouteInfo 归一化处），判断 `case` 与 `delivery_case` 哪个是当前设计意图（依据 `ARCHITECTURE_DESIN/multi_agent_fanout_2026-07.md` 的意图枚举）。设计已统一为 `case` → 更新测试期望；`delivery_case` 才是契约 → 修归一化逻辑。
  - 问题 B：`git diff HEAD -- data/ai/` 看新增的 3 个 scrna agent；对照 router 候选表来源——候选若由 `list_agents(active_only=True)` 动态生成，则测试里写死的候选清单/快照过期 → 更新测试数据；若存在 `router.md`/yaml 人工候选表 → 把新 agent 补进去。
  - 修复汇报中必须写明：每处是"代码对、测试过期"还是"测试对、代码漂移"，及依据。
- 验证口径：两个测试文件全绿；`pytest tests/unit -k router -q` 无回归。

### 10.4 修 5：前端低严重度清理（四小项）

- **5a 关键词触发路径诊断假阳性**：发送时 overdrive=false、流中被关键词打开时，占位消息被 splice 移除，但 `onDone` 仍对脱离数组的 aiMsg 判空，触发 `reportChatDiagnostic('stream-empty')` 假阳性（`agentHub.ts`）。修法：`onDone`/`onError` 的普通分支加守卫——`if (session.overdrive || modeChangedToOverdrive)` 跳过空回复诊断与兜底；注意关键词路径下闭包变量 `effectiveOverdrive` 初始为 false，需在 `onModeChanged` 时同步更新该闭包变量，或改为实时读 `session.overdrive`。验证：模拟"发送时关、流中开"路径，不再产生 stream-empty 诊断日志。
- **5b sendMessage options 补 overdrive 字段（对齐 F2 字面契约）**：`sendMessage` options 类型加 `overdrive?: boolean`；计算处改为 `const effectiveOverdrive = options.overdrive ?? session.overdrive ?? false`；options 显式传入时同步写回 `session.overdrive`（照 multiAgent 的写法）。验证：传 `options.overdrive=true` 且 session.overdrive=false 时请求体带 `overdrive:true`。
- **5c OverdriveToggle tooltip 文案对齐 F1 文档原文**：未开——"开启后，复杂任务由 Manager 发现全部专家并分工协作，各专家在对话中依次发言"；已开——"超频模式已开启：团队房间接管对话，直接布置任务即可"。
- **5d 超频时最后一条消息误判 streaming 样式**：`KimiMessageList.vue` 把最后一条 assistant 且 isTyping 的消息视为 streaming，超频轮最后一条 room_speech 命中该条件（内容无影响，仅样式）。修法（二选一，推荐前者）：`onRoomSpeech` push 的消息显式 `status:'done'` 且不参与 typing 判定；或在 `KimiMessageList.vue` 的 streaming 判定条件中排除 `message.senderAgent` 存在的消息。验证：超频轮结束后最后一条发言不显示打字光标/流式样式。

### 10.5 修 6：工作区变更集拆分原则

- 工作区混了两个独立 feature 的改动（超频/AgentTeams vs 参考基因组），提交时应拆成两个变更集；**只产出 `git add` 分组清单写进汇报，不执行任何 git 命令**。
- **变更集 A：超频模式 + AgentTeams**：`src/cygnusx/application/schemas/chat.py`、`api/v1/chat.py`、`application/services/chat_service.py`、`application/services/parallel_subagent_service.py`、`application/services/agentteams_room_gateway_service.py`、`application/services/agentteams_service.py`、`application/services/agentteams_case_tool_service.py`、`api/v1/agentteams.py`、`api/v1/admin/agentteams_bridge.py`、`application/schemas/agentteams_bridge.py`、`core/config.py`（仅 gateway 相关 hunk）、`integrations/agentteams/`、`deploy/agentteams/`、`frontend/src/stores/agentHub.ts`、`composables/useAgentChatStream.ts`、`components/agent-workspace/OverdriveToggle.vue`、`AgentSandbox.vue`、`views/StudioView.vue`、`components/ai-chat/types.ts`、`KimiMessageItem.vue`、`views/AgentTeamsCaseView.vue`、`components/task/AgentTeamsCasesPanel.vue`、`components/admin/AgentTeamsBridgeTab.vue`、`api/admin/agentTeamsBridge.ts`、`tests/unit/test_overdrive_chat.py`、`test_agentteams_*`、`tool_configs/tools_schema.yaml`、`ARCHITECTURE_DESIN/agentteams_overdrive.md`、`multi_agent_fanout_2026-07.md`
- **变更集 B：参考基因组模块**：`src/cygnusx/reference_genomes/`、`api/v1/router.py`（该文件两个 feature 都碰，需 `git add -p` 拆 hunk）、`core/config.py`（同上，`reference_genomes_yaml` 的 hunk 归 B）、`refdata/reference_genomes.yaml`、`frontend/src/api/referenceGenomes.ts`、`types/referenceGenomes.ts`、`views/ReferenceGenomesView.vue`、`tests/unit/reference_genomes/`、`test_reference_genomes_sequence.py`、`scripts/reference_genomes_smoke.py`
- **需人工裁决的混杂文件**：`api/v1/router.py`、`core/config.py`、`views/ProfileView.vue`（个人页 UI 重做，与两个 feature 均无关，建议单独第三个变更集）、`docs/knowledge/getting-started.md`、`.gitignore`、`.env.example`（逐文件确认归属）。
- 子模块变动（`pipelines/*`、`Protocol/FlowFrame` 显示 `m`）与两个 feature 无关，不要纳入。

### 10.6 总验证命令（全部修复后必跑，2026-08-04 时点口径）

```bash
# 后端（用项目 .venv）
.venv/bin/python -m pytest tests/unit/test_overdrive_chat.py tests/unit/test_agentteams_room_gateway_service.py \
  tests/unit/test_agentteams_matrix_case_binding.py tests/unit/test_agentteams_bridge_admin.py \
  tests/unit/test_agentteams_service.py tests/unit/test_parallel_subagent_service.py \
  tests/unit/test_agent_router.py tests/unit/test_agent_router_dispatch.py -q
# 前端
cd frontend && npm run type-check && npm run build
# 文档
grep -n "拍平" ARCHITECTURE_DESIN/agentteams_overdrive.md && grep -n "minItems" tool_configs/tools_schema.yaml
```

全部通过后汇报：每项修复的改动文件+位置、修 4 的对错判断依据、变更集分组清单（修 6）、验证输出摘要。
