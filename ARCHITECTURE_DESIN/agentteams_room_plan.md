# AgentTeams 团队协作室实施方案

> 日期：2026-08-12（2026-08-13 增补第 8 章：官方对齐路线与 Case 定位）
> 状态：M1~M6 已实施；M7 已评估（主体不做，决策见 M7 节）；剩余加固项见 8.3 M5 遗留清单
> 前提：超频模式（overdrive）保留不动，仅维持现状可用——用户计划后续对超频模式单独重构，本方案不为超频侧新增投入；与超频共用的组件（ParallelSubAgentService）只做向后兼容的增量改动。
> 本方案为 AgentTeams（Bridge Case 体系）新增独立聊天室入口，并让房间内的 agent 可调用平台已有的沙箱 / MCP / Skill。

## 1. 目标

1. 侧边栏新增「团队协作室」入口，页面内可发起 Case、实时观看多 agent 轮流发言（复用现有 room_speech 渲染观感）。
2. 房间内的 agent 执行过程可见：工具调用（沙箱 / MCP / Skill）逐步投影到房间事件流，而不是只见一头一尾。
3. 专业 agent（rnaseq/atacseq/scrna 等）在 Case 中可按 YAML 声明使用 `workspace_execution`（沙箱 + 9 个 workspace 工具），解除目前仅 agent-code/agent-viz 的硬编码限制。
4. 顺带修复治理缺陷：Case 状态自动收敛、Case GC、心跳面板别名聚合、Case 与会话关联展示。

## 2. 现状关键事实（已核实，实施时不必重查）

### 2.1 执行链路（沙箱/MCP/Skill 已天然在线）

```
worker 容器(空壳轮询) → bridge POST .../execute-readonly → gateway(白名单/限额)
  → 主后端 POST /api/v1/agent-teams/consultations/scientific-interpretation
  → AgentConsultationService.run_consultation
  → ParallelSubAgentService.run（超频同款子 agent 运行时）
      ├─ 沙箱：sandbox_execute 等 9 个 workspace 工具（execution_mode=workspace_execution 时）
      ├─ MCP：按 agent YAML 绑定的 mcp_servers 注入（_prepare_child_tools 保留 MCP 工具）
      └─ Skill：use_skill / read_skill_resource
```

- 会诊请求已携带 `case_id` + `work_item_id` + `execution_mode`（`src/omichub/api/v1/agentteams.py:97-119`）。
- `ParallelSubAgentService.run` 已支持 `on_event` 回调并发出 `worker_started / worker_tool_call / worker_finished / worker_heartbeat` 事件（`parallel_subagent_service.py:190,490,566,644`）——**会诊路径目前没有传 on_event**，这就是工具过程不可见的原因。
- Bridge 已有证据事件入口 `POST /v1/cases/{id}/evidence`（`bridge/.../app.py:549`），event_type 自由字符串（pattern `^[a-z0-9_.-]+$`），证据事件会进 audit 流，`GET /v1/cases/{id}/events/stream` SSE 可推到前端。
- 主后端 → bridge 的客户端 `AgentTeamsService`（`agentteams_service.py`）**尚无 evidence 方法**，需新增。
- 产物链路已通：会诊 artifacts 落盘 + MinIO 上传（`agent_consultation_service.py:270`），读取走 `GET /agent-teams/cases/{cid}/artifacts/{path}`（`api/v1/agentteams.py:377`）。

### 2.2 能力声明已在 YAML 里

- 多数 agent（rnaseq、scrna×3、cloud_ops、mcp_builder、data、general 等）已在 `data/ai/*.yaml` 声明 `features.agentteams.execution_modes: [readonly_consultation, workspace_execution]`。
- capability registry 已把 `execution_modes` 暴露进 `/capabilities` 快照的 `agent_capabilities`（`agentteams_capability_registry.py:80-106`）。
- 但 worker 端硬编码拦截：`integrations/agentteams/worker/production_runner.py:194-199` 只允许 `agent-code`/`agent-viz` 跑 workspace_execution——与 YAML 声明矛盾，是本方案要解除的核心限制。
- 安全边界保留：workspace_execution 的 workdir 禁锢在 `/data/omichub/output/agentteams/{case}/{work_item}`（`agent_consultation_service.py:121-124`），不可移除。

### 2.3 前端资产

- 房间发言渲染：`KimiMessageItem.vue` 只要消息挂 `senderAgent{name,avatar,color,role,round}` 即渲染 manager 气泡 / worker 折叠卡片。
- Case SSE 消费样板：`AgentTeamsCaseView.vue:startEventStream`（:311-355，cursor 续传 + 指数退避 + 轮询降级）。
- API 封装：`frontend/src/api/agentTeams.ts`（listCases/createCase/confirm/revise/reject/retry/getEvents 等齐全）。
- 侧边栏：`frontend/src/layouts/DefaultLayout.vue:230-258`（navItems，无 i18n，硬编码中文）；路由 `frontend/src/router/index.ts`。
- agent 显示元数据：registry 的 `role_labels()`（name/avatar/color/role，`agentteams_capability_registry.py:163-176`），但 `/capabilities` 是 integration token 鉴权，前端用户态拿不到，需新增用户态端点。

### 2.4 只读数据访问现状（"看到用户数据但仅读取"已是体系默认姿态）

- `readonly_consultation` 模式下子 agent 走 `safe_only=True` 只读工具白名单，本身就不能写。
- 已有 6 个用户态只读证据工具（`tool_configs/tools_schema.yaml:127+`，全部 `readOnlyHint: true` + `user_scoped: true`，`AgentTeamsDataToolService`）：
  - `task_result_summary`：读用户任务状态/参数快照/产物清单/QC metrics/失败摘录
  - `task_file_preview`：预览任务目录内文本产物头部（禁路径穿越/符号链接）
  - `workspace_file_preview`：按 requester_ref 隔离预览用户 workspace 文件
  - `artifact_fetch` / `task_compare_metrics` / `rule_threshold_lookup`
- 扩展读能力**不需要新代码**：在 agent YAML 绑定只读 MCP 工具包（builtin presets：omichub-tools / omichub-platform）即可，`parallel_subagent_service._prepare_child_tools` 会保留 MCP 工具。
- 即：房间 agent 默认"能看用户的任务、文件、产物、指标，但不能改"；要写只有 `workspace_execution` 模式且禁锢在 case 专属 workdir。

### 2.5 治理缺陷现状

- Case 不自动收敛：work item 更新只写 work_item 状态；`reconcile_case`（`bridge/.../service.py:259`）存在但只能手动/管理端触发。线上 2 个僵尸 received case 即此因。
- 无 GC：10 个 7/31-8/11 测试残留 case 永久留存的根因。
- 心跳面板误报：`_ROLE_ALIASES`（data-steward→agent-data 等 3 个，`agentteams_capability_registry.py:20-24`）在统计"缺心跳 worker"时未聚合；agent-router、shania 的 YAML 有 `internal_case_role` 但无 worker 部署。

## 3. 里程碑与改动清单

### M1：团队协作室 MVP（前端为主，后端 2 个小端点）

**目标**：侧边栏入口 + 房间页面，能发起 Case、实时看事件投影的多 agent 发言、做审批动作。

后端：

1. **新增用户态 role-labels 端点**：`src/omichub/api/v1/agentteams.py`
   - `GET /api/v1/agent-teams/role-labels`（用户 JWT），返回 `get_agentteams_capability_registry().snapshot()` 的 `role_labels` + `role_agent_map` 子集，供房间渲染发言人名/头像/颜色。
2. **Case 列表带会话关联**（可选，M1 简化版可跳过）：`list_cases` 响应补充 `session_id`——聊天侧绑定存在 `ChatSessionModel.sandbox_meta.agentteams_case_ids`（`agentteams_case_tool_service.py:296-327`），反向索引即可。M1 先按 requester_ref 全部列出。

前端：

3. **路由 + 导航**：
   - `frontend/src/router/index.ts`：新增 `{ path: 'agent-teams/room', name: 'agent-teams-room', component: () => import('@/views/AgentTeamsRoomView.vue'), meta: { title: '团队协作室', requiresAuth: true } }`。
   - `frontend/src/layouts/DefaultLayout.vue` navItems 在「AI 工作台」后加 `{ key: 'agent-teams-room', label: '团队协作室', to: '/agent-teams/room', icon: ... }`；如需前缀高亮在 `isActive`(:280-307) 加分支。
4. **事件→房间消息投影工具** `frontend/src/utils/agentTeamsRoom.ts`（新文件，纯函数，好测）：
   - 输入：case event `{event_id, recorded_at, case_id, actor, event_type, payload}` + role_labels。
   - 输出：`RoomMessage{ id, sender{name,avatar,color,role}, kind: 'speech'|'progress'|'action'|'system', content, round?, collapsed? }`。
   - 投影规则表：

     | event_type | 投影 |
     |---|---|
     | `case.created` / `planning.frozen` | manager 发言（计划摘要，payload 取 plan 描述） |
     | `work_item.assigned` | system 行「Manager 将任务分派给 {role_label}」 |
     | `work_item.claimed` / `work_item.running` | worker 卡片起始（streaming 态） |
     | `agent.tool_call`（M2 新增证据事件） | worker 卡片内 progress 行「正在调用 {tool}」 |
     | `agent.tool_result`（M2） | progress 行完成态（耗时/成败） |
     | `skill.finished` | worker 终态发言（payload.conclusion/summary） |
     | `skill.failed` / `skill.manual_review` | worker 发言（错误态样式） |
     | `quality.decision` / `quality.hard_gate` | agent-qc 发言 |
     | `case.cancelled` / `case.state_changed` | system 行 |
     | `omic_task.*` | 折叠 system 行（默认收起） |
     | 其他 | 丢弃（不进房间） |

5. **房间页面** `frontend/src/views/AgentTeamsRoomView.vue`（约 300-400 行）：
   - 左栏：Case 列表（`agentTeamsApi.listCases`，状态 badge，按 updated_at 倒序）+「发起团队任务」按钮。
   - 发起对话框：intent + project/flow 选择（复用 `AgentTeamsCaseView` 的表单件或 `AgentTeamsCaseCard` 逻辑）→ `POST /cases`。
   - 右栏：选中 Case → SSE 消费 `GET /api/v1/agent-teams/cases/{id}/events/stream?cursor=`，模式照抄 `AgentTeamsCaseView.vue:startEventStream`（cursor 续传、1s→30s 指数退避、断流转 20s 轮询 `getEvents`）；事件经 `agentTeamsRoom.ts` 投影成 RoomMessage 列表渲染。
   - 渲染：speech 消息直接用 `KimiMessageItem.vue`（构造带 `senderAgent` 的 ChatMessage）；progress 行用简化气泡；底部动作条按 case 状态渲染 确认/修计划/驳回/重试（调现有 agentTeamsApi，复用 `AgentTeamsCaseView` 的弹窗组件）。
   - M1 不做自由文字输入（Bridge 无用户发消息 API），输入框位留占位 disabled + tooltip「自由对话二期开放」。

**验收**：发起一个通用 Case → 房间左侧出现 → 右侧逐步出现 manager 计划、任务分派、worker 起止、qc、交付发言 → 审批动作可用。

### M2：工具调用投影（让房间"活起来"）

后端：

6. **`AgentTeamsService` 新增 `post_case_evidence`**：`src/omichub/application/services/agentteams_service.py`
   - `POST /v1/cases/{case_id}/evidence`（bridge app.py:549，用 manager 身份 token），body `{event_type, payload, actor}`。
7. **会诊路径接 on_event 投影**：`src/omichub/application/services/agent_consultation_service.py` `run_consultation`(:81)
   - 构造 `on_event` 回调传给 `ParallelSubAgentService.run`（:190 参数已存在）。
   - 映射：`worker_started` → evidence `agent.started`；`worker_tool_call` → `agent.tool_call`（payload: `{tool, args_summary(截断200字符), work_item_id, agent_id}`）；`worker_finished` → `agent.finished`（payload: `{status, tool_call_count, duration_ms}`）。
   - 工具执行成功后补 `agent.tool_result`（若 run 的事件流不区分结果，在 M2 内给 `ParallelSubAgentService` 的工具执行完成处（:763 附近）加发 `worker_tool_result` 事件，同样转发）。
   - 容错：evidence POST 失败仅 log warning，**不得影响会诊主流程**（fire-and-forget + try/except）。
   - 限流保护：同一 work item 的 tool_call 事件上限 200 条，超出计数合并为一条 `agent.tool_call_truncated`。

前端：

8. `agentTeamsRoom.ts` 投影表加入 `agent.tool_call / agent.tool_result / agent.started / agent.finished`（见 M1 表），房间视图在 worker 卡片内渲染进度行（样式参考超频 `assistant_tool_call` 的进度 label）。

**验收**：跑一个 workspace_execution work item，房间内实时看到「RNA-seq 助手 正在调用 sandbox_execute」「正在调用 pipeline_query」等进度，随后出现终态发言与产物。

### M3：能力放开 + 治理修复

9. **workspace_execution 白名单配置化**：
   - `integrations/agentteams/worker/production_runner.py:194-199`：删除 `agent-code/agent-viz` 硬编码，改为读 `/capabilities` 快照的 `agent_capabilities[identity].execution_modes`（`load_worker_profile` 已请求该端点，扩展取 execution_modes 一并校验）；YAML 未声明 `workspace_execution` 的 identity 才拒绝。
   - gateway `agent_policies`（`gateway/.../service.py:92-149`）：确认各 agent policy 的 capability 白名单包含 `workspace_execution`（配置文件同步改）。
   - 检查 bridge 侧 work item 创建时 `execution_mode` 的赋值点，确保与 registry 声明一致校验（不一致则降级 readonly 并记 `planning.validation_failed`）。
10. **Case 状态自动收敛**：`bridge/.../service.py`
    - 在 work item 状态更新为终态（completed/failed）的处理路径（app.py:298 → service 内 update 方法）末尾调用内部 `_auto_reconcile(case_id)`：复用 `reconcile_case`(:259) 的判定逻辑，全部 work item 终态且无进行中 omic_task 时推进 case 状态（保持现有状态机，不新增状态）。
    - 幂等：已终态 case 直接返回。
11. **Case GC**：`bridge/.../app.py` + `service.py`
    - 新增 `POST /v1/maintenance/case-gc`（manager 身份）：删除 `status ∈ {cancelled, failed, closed}` 且 `updated_at` 早于 N 天前的 case 及其 audit 事件；N 由 env `BRIDGE_CASE_GC_DAYS`（默认 7，0=禁用）。
    - 仅在 `BRIDGE_ENVIRONMENT != production` 默认启用启动时+每日定时执行；生产只提供手动端点。
12. **心跳面板别名聚合**：`src/omichub/application/services/agentteams_service.py` `admin_resource_snapshot`(:100)
    - 统计缺心跳 worker 前，先用 registry 的 `role_alias_map()` 把别名 identity 归并到 canonical role（data-steward→agent-data 等），消除误报。
13. **worker 部署缺口收口**（配置决策，二选一）：
    - 方案 a：给 `agent-router`、`shania` 补 professional-pool identity（`deploy/agentteams/docker-compose.agentteams.yml:137-157` 的 `AGENTTEAMS_WORKER_IDENTITIES` + token env）。
    - 方案 b（推荐）：这两个是路由/人设型 agent，不参与 Case 执行——从其 YAML 删除 `internal_case_role`，告警自然消失。
14. **（可选）Case-会话关联展示**：房间左栏按 session 分组显示 case（依赖 M1 第 2 条的反向索引）。
15. **只读数据工具盘点暴露**：房间「发起团队任务」对话框提示 agent 可读的数据范围（任务/文件/产物/指标），前端文案即可；若某 agent 需要更多读能力，在其 YAML 绑定只读 MCP 包，不改代码。

## 4. 配置与部署变更

- `deploy/agentteams/worker.env.example`：无新增 token；`production_runner` 改动纯代码。
- bridge env 新增：`BRIDGE_CASE_GC_DAYS=7`（compose `docker-compose.agentteams.yml` bridge 服务环境块补充）。
- 全栈重启验证：`make docker-reload`（步骤 9 会重建 agentteams worker 镜像，worker 代码改动必须走它生效）；只改主后端/前端时 `make docker-dev-refresh` 即可。

## 5. 测试计划

后端（pytest）：
- `tests/unit/test_agent_consultation_service.py`（或新建）：on_event 投影——mock `AgentTeamsService.post_case_evidence`，断言 tool_call/tool_result/started/finished 事件各按规则发出、evidence 失败不影响会诊结果、200 条截断生效。
- `tests/unit/test_agentteams_capability_registry.py`：execution_modes 校验逻辑。
- `integrations/agentteams/bridge/tests/`：auto-reconcile（全终态→状态推进、幂等）、case-gc（按天数过滤、audit 清理）、evidence 端点契约（已有 `test_bridge_contract.py` 可扩展）。

前端（vitest）：
- `frontend/src/utils/__tests__/agentTeamsRoom.spec.ts`：投影表全分支。
- 房间视图组件测试：mock SSE 事件序列 → 断言发言/进度/动作条渲染。

端到端冒烟（手动）：
1. `make docker-reload` 后起全栈。
2. 房间发起 RNA-seq 通用 Case → 观察 M1 全链路发言。
3. 确认计划 → 观察 worker 工具调用进度（M2）与产物下载。
4. 构造全终态 case 验证自动收敛；调 `POST /v1/maintenance/case-gc` 验证残留清理。

## 6. 风险与边界

- **安全边界不可后退**：readonly_consultation 的 `safe_only=True` 保留；workspace_execution 的 workdir 禁锢保留；evidence 投影失败不得阻断会诊。
- **投影事件量**：tool_call 高频，务必做 200 条截断 + args 摘要截断，避免 audit 流膨胀（Redis Stream 记得在 GC 中一并 trim）。
- **房间内不能自由对话**是 M1 已知限制；二期（Matrix 房间接线，`agentteams_room_gateway_service.py` 已写好待启用）再开。
- 超频模式与团队协作室共用 `ParallelSubAgentService`，M2 给它加 `worker_tool_result` 事件时注意不影响超频现有事件消费方（`chat_service.py` / `agentteams_case_watch_service.py`）——新增事件类型、不改既有事件语义即可。

## 7. 工作量估算

| 里程碑 | 内容 | 预估 |
|---|---|---|
| M1 | 房间入口+投影+页面（后端 2 小端点） | 1.5 天 |
| M2 | 工具调用投影（前后端） | 1 天 |
| M3 | 白名单配置化+自动收敛+GC+心跳聚合 | 1 天 |
| 合计 | | ~3.5 天 |

---

## 8. 与官方 AgentTeams 的对齐路线（2026-08-13 增补）

> 背景：对照阿里云官方 AgentTeams（help.aliyun.com/zh/agentteams/，开源实现 agentscope-ai/AgentTeams）做了完整兼容性排查。结论：平台自研的 Bridge Case 体系与官方是两套哲学——官方「Matrix 房间为协作底座 + 人进房间治理」，平台「Case 工单状态机 + 事件流投影」。本章记录对齐决策与新增里程碑。

### 8.1 为什么架构里有 Case（定位说明）

官方 AgentTeams **没有一等工单概念**：任务是 OSS 存储桶里的记录目录（meta.json/spec.md/result.md）+ Matrix 房间对话流，人工审批靠"人在房间里口头确认"，无结构化审批流。

平台的 Case 是在官方缺位处长出来的**治理载体**，承载官方模型无法表达的四件事：

1. **结构化人工审批**：approval token（HMAC 签名、短时、scoped）+ plan_hash 冻结 + 乐观锁修计划——比官方"房间里口头确认"可审计、可防伪造；
2. **质控门**：确定性硬门（mapping_rate/q30 等阈值）+ LLM 评审 + remediation 循环；
3. **计划即契约**：proposed_submission + preflight 输入快照哈希比对，执行不得偏离已批计划；
4. **审计与投影**：audit 事件流（Case/WorkItem/证据事件）既是治理记录，也是房间发言投影的数据源。

与官方概念的映射关系：

| 平台 | 官方对应 | 差异 |
|---|---|---|
| Case | OSS task 记录 + 房间对话流 | 平台多了状态机与审批治理 |
| WorkItem | Team Leader 在房间里派活 | 平台多了租约/重试/幂等 |
| bioops-manager | Team Leader（特殊 Worker） | 平台 manager 是桥内角色 |
| approval token 审批 | 房间内人口头确认 | 平台是结构化升级 |
| audit 事件流 | Matrix 房间历史即审计 | 平台另有独立事件存储 |

**决策（2026-08-13，用户确认）：审批/质控是平台独有价值，Case 体系保留不废弃**；不向官方"无工单"模型倒退。

### 8.2 不追全兼容的边界

- 不废弃 Case/审批/质控去对齐官方"无工单"模型；
- 不做官方托管版 OpenAPI（73 个管控面接口，RAM 签名）的协议级对接——若未来接官方托管实例，走"自研 runtime 被纳管"路径（官方明确支持纳管自研 Agent）；
- 官方 Worker 接入协议（LoongSuite Pilot + bootstrap token）未公开规范，不做协议仿真。

### 8.3 新增里程碑

**M4：房间 UI 重设计（进行中）**

现状问题（2026-08-13 截图 docs/26.8.13/image.png）：大面积留白浪费、每条 agent 发言挂着无意义的点赞/点踩/复制按钮、system 行过淡难以追踪流程、worker 折叠卡片信息密度低且重复、顶部缺少 Case 状态与进度总览、整体视觉与"团队协作室"叙事不符。

- 重设计 `AgentTeamsRoomView.vue`：顶部 Case 状态条（状态机进度：计划→审批→执行→质控→交付）；发言流按 role 分组着色、去掉无效动作按钮；worker 卡片内联展示工具调用进度（M2 投影数据）；system 行改为时间轴节点样式；左栏 Case 列表增加状态过滤与搜索；视觉对齐项目 `skills/omichub-frontend-design` 规范。

**M5：Matrix 进数据通路（第一~五刀已实施，剩余反向同步加固）**

目标：对齐官方"房间即协作空间"体验，用户可用 Element 旁观/介入，房间内可自由对话。

第一刀（2026-08-13 已实施）：建房接线 + audit→Matrix 事件镜像 + 用户发言 + 输入框启用。

- 建房：两条用户态创建路径（`POST /cases`、`/cases/confirm` 经 `AgentTeamsCaseToolService.run`）在 Case 创建成功后经 `AgentTeamsService.provision_case_room` 建房；失败仅 log warning，Case 照常返回（降级事件流模式）。房间标识以 `room.created` Case 级证据事件（`work_item_id="case"`，bridge 对 manager 放行、不要求同名 work item）持久化——bridge 审计流即 case_id → room_id 映射存储，未给 bridge 加 schema 字段。
- 镜像：接入点选 bridge 侧 audit append 钩子（`AuditStore.on_event` → `AuditRoomMirror`，fire-and-forget，失败仅 log），覆盖面为全部审计事件（主后端 consumer 路径只覆盖 chat 绑定且在线的 Case）。Gateway 只写本地审计不回写 Bridge，无循环镜像（`matrix.*` 事件类型显式跳过兜底）；重启后经 `AuditStore.all_events()` 重放 `room.created` 重建绑定。
- 用户发言：`POST /api/v1/agent-teams/cases/{id}/messages`（JWT，限长 4000，非归属 403）记 `room.user_message` 审计事件（payload.actor=requester）；有房间时由 bridge 镜像钩子以 `omichub-user` 身份发进 Matrix，Matrix 失败不影响事件记录。前端输入框启用（非终态可发），`room.user_message` 投影为"我"的气泡，`room.created` 投影为折叠 system 行。
- 开关：`agentteams_gateway_enabled` 默认关闭；未建房成功时 Matrix 部分完全不激活，`room.user_message` 审计始终记录。

第二刀（2026-08-13 已实施）：房间内自由对话的 Manager 响应回路。

- 触发：`POST /cases/{id}/messages` 落证据后 fire-and-forget 派发 Celery 任务 `respond_to_room_message`（analysis 队列；调度失败仅 log，不影响发言落盘）。
- 响应：`AgentTeamsRoomResponseService` 以 per-case Redis 互斥锁（`agentteams:room-response:lock:{case_id}`，TTL 180s）去重，锁占用即丢弃；终态 Case 跳过。Manager agent 选法：优先 `agent-general`（registry 无 manager 角色，agent-general 是平台指定的 recruitable + planner_eligible 通用 planner），缺失时回退任意 planner_eligible 可会诊 agent。经 `AgentConsultationService.run_consultation`（readonly_consultation）生成回复，question 组装含 Case intent/状态/最近 8 条事件摘要/最新用户发言。
- 回复落盘：`room.agent_message` Case 级证据事件（payload `{content, agent_id, role: bioops-manager}`）——SSE 投影（前端渲染为协作经理气泡）与 Matrix 镜像（room_mirror 以 bioops-manager 身份发送）自动生效。LLM 失败仅 log warning，不落失败事件、不影响用户发言。

第三刀（2026-08-13 已实施）：Manager"正在输入"指示 + Matrix→平台反向同步（双向房间）。

- Typing：响应任务拿锁且通过终态/manager 检查后落 `room.typing` `{typing:true}`，完成/失败 finally 落 `{typing:false}`；被锁丢弃的消息不发 typing 事件，天然不残留（前端另有 3 分钟新鲜度兜底，`room.agent_message` 到达即视为输入结束）。前端 `resolveManagerTyping` 从原始事件流推导，消息流底部渲染三点脉冲指示（语义令牌 + prefers-reduced-motion 回退）；`room.typing` 不进消息列表、不镜像进 Matrix。
- 反向同步：`AgentTeamsRoomSyncService`（主后端 Celery beat 任务 `sync_case_rooms`，全局互斥锁 + 有界 SSE，复用 `agentteams_case_event_stream_*` 节奏配置）。建房时 `record_room_binding` 把 `case→room|requester` 登记进 Redis hash；任务为每个绑定房间开 Gateway `/rooms/{id}/sync` SSE，sync cursor 持久化 Redis（`agentteams:room-sync:cursor:{case_id}`），终态 Case 自动移除绑定；断线由 beat 间隔自然重连。
- 防回声：Gateway matrix_client 给平台镜像消息打 `com.omichub.source=omichub` 标记，SSE 载荷 `origin != "external"` 一律不回投；回投事件 payload 带 `via="matrix"`，bridge room_mirror 据此跳过——双向均无循环。Element 侧发言回投为 `room.user_message`（payload.actor=Matrix sender，带 matrix_event_id）并同样触发 `respond_to_room_message`，与房间页发言语义一致。

第四刀（2026-08-13 已实施）：Element 嵌入 + AppService 批量供给用户 + 正式部署资产。

- Element 嵌入：Gateway 建房响应的 `element_room_url`（`GATEWAY_ELEMENT_BASE_URL` + `#/room/{room_id}` 深链）早已随 `room.created` 证据事件下发，本刀前端直接消费——`resolveElementRoomUrl`（仅接受 http/https，取最新一条）从事件流解析深链，房间页顶部出现"消息流 / Element 视图"切换；Element 视图以 sandbox iframe（`allow-scripts allow-same-origin allow-forms allow-popups allow-downloads` + `referrerpolicy="no-referrer"`）嵌入深链，并附"在新标签页打开"出口。未建房/Gateway 未配置 Element 地址时入口不出现（无 room.created 即无 URL）。前端不新增配置项，URL 单一来源是 Gateway 配置。
- 用户供给：映射规则 platform user → `omichub-user-<sanitized user_id>`（清洗为 Matrix localpart 安全字符，空则回退共享 `omichub-user`），主后端 `agentteams_service.matrix_identity_for_requester` 与 bridge `room_mirror` 各持一份同规则实现（跨进程无共享包）。Gateway 新增 `matrix_server_name` 配置与 `matrix_user_for_identity`（静态 map 优先，动态前缀兜底）+ 反向解析 `matrix_identity_by_user_dynamic`（sync 事件归源）；新增幂等端点 `POST /users/ensure`。建房路径：`provision_case_room` 先 best-effort 调 `ensure_users` 预热账号（失败不阻断，create_room 内部仍 ensure），再带 per-user 身份 invite 建房；bridge 镜像用户发言改以 per-user 身份发送，Element 侧可区分发言人。
- 部署资产：`deploy/agentteams/kubernetes/` 新增 `tuwunel.yaml`（Tuwunel 单副本 + Recreate + RWO PVC + AppService 注册文件 Secret 模板，users 正则覆盖 `omichub-user-*`）、`gateway.yaml`（Gateway Deployment/Service/PDB + ConfigMap/Secret 模板）、NetworkPolicy 补充（gateway/tuwunel 进出规则 + bridge→gateway 放行）与 README（与 matrix-dev 的分工、配置联动、镜像加速约定）；风格对齐 bridge-cluster.yaml 安全基线。matrix-dev 的 Synapse 仅保留开发用。

第五刀（2026-08-13 已实施）：房间页聊天式创建 Case + 通用 Case 自动确认。

- 聊天式创建：未选中 Case 时房间输入框常开（输入栏移出选中分支，placeholder 切换为创建引导），首条消息即意图——前端 `buildRoomCreateIntent`（trim + 空白收敛 + 对齐后端 256 上限）调 `POST /cases` 创建通用 Case，选中新房后把原文经 `POST /cases/{id}/messages` 发进房间，复用第二刀 Manager 响应链路。
- 上下文注入：后端 `AgentTeamsCaseCreateRequest` 校验器放开"通用 Case 必须显式关联上下文"（流程型必须关联项目的校验不变），端点对聊天式直发（无 flow_id 且无 project_id）缺省注入 `{"kind": "workspace", "id": current_user_id}` 只读引用——注入放后端是为了一处生效且不让前端伪造引用 id；显式携带 context_refs 的通用 Case 原样透传。
- 自动确认事实源：Redis 集合 `agentteams:auto_confirm_cases`（service 层常量 `AUTO_CONFIRM_CASES_KEY`）。Bridge Case 无 meta 字段且本刀不改 bridge schema，故标记放平台侧；创建成功后 best-effort `sadd`，Redis 异常仅 log warning，Case 降级为人工审批。
- 消费：Celery beat 任务 `auto_confirm_cases`（间隔复用 `agentteams_case_watch_interval_seconds`，全局互斥锁 + Lua 释放，与既有巡检任务同构）。取集合与 Bridge manager 身份 `GET /v1/cases?status=approval_pending` 的交集，逐个复用 `AgentTeamsService.approve_and_submit_task` 通用分支（approval-authority 先取 token 再 `general-plans/execute`，requester_ref 取 Case 自身值，审批 token 体系不变）；前置状态（queued~waiting_for_correction）保留标记等下一轮，已批准/终态/找不到的清理标记，单个失败 log 隔离不影响其他 Case。
- 治理边界：流程型 Case（真实计算）绝不自动确认——beat 内防御性跳过并清理标记，仍需人工"确认执行"；创建表单保留，顶部提示文案更新为"流程型真实计算仍需人工审批确认，通用任务在计划冻结后自动确认执行"。

剩余条目（后续刀）：

1. 反向同步加固：Redis 绑定丢失时从审计流 `room.created` 重建（当前仅建房时登记）；回投至少一次语义下的去重（matrix_event_id 幂等）；显式指数退避（当前依赖 beat 间隔）；
2. Element 内发言的终端用户登录：AppService 供给的 `omichub-user-*` 账号无密码，iframe 内目前只能以已有 Matrix 账号旁观/介入，面向平台用户的 SSO/token 下发未做；
3. 开关 `agentteams_gateway_enabled` 默认关闭，未配置时降级为现有事件流投影模式（第一刀已落实降级语义）。

**M6：Worker 凭证收敛（2026-08-13 已实施）**

对齐官方"网关持真实凭证、Worker 持可吊销 consumer token"模型：

1. Worker→Bridge 可吊销 per-worker token（已实施）：Bridge 新增 `WorkerTokenStore`（`worker_tokens.py`，Redis snapshot/本地 JSON 双模，与 CaseStore 同构，只存 SHA-256 哈希），端点 `POST /v1/worker-tokens`（manager 签发，identity + 可选 TTL/note，原始 token 仅返回一次）、`GET /v1/worker-tokens`（脱敏列表）、`DELETE /v1/worker-tokens/{id}`（吊销）。`security.require_identity` 扩展为静态 `BRIDGE_IDENTITIES` secret **或**有效未吊销 worker token 均可通过——存量静态部署不受影响，可逐 worker 迁移；吊销/过期立即 401；token 绑定 identity，header 身份与 token 不符即 403 防冒用。主后端代理端点 `GET/POST/DELETE /api/v1/admin/agentteams-bridge/worker-tokens`（签发/吊销需 TOTP），管理面板 `AgentTeamsBridgeTab.vue` 新增"Worker 令牌管理"卡片（签发对话框选 identity/TTL/备注、列表含状态与吊销按钮、签发后一次性展示+复制）。
2. MCP 上游凭证收敛（侦察结论：现状已收敛，无需代码改动）：MCP server 定义与凭证（command/url/env）存放于主后端数据库 `mcp_servers` 表，由 `agent_service` 在主后端进程内解析、`MCPClient.call_tool` 在主后端会诊进程内执行（`parallel_subagent_service._prepare_child_tools` 仅按 agent 绑定筛选工具名）。Worker 容器是空壳——只轮询 Bridge HTTP 接口（`X-Bridge-Identity`/`X-Bridge-Token`），compose 注入仅 `AGENTTEAMS_*` token，从不接触 MCP 定义或凭证。即官方模型中"网关持真实凭证"的角色由主后端进程承担，Worker 侧天然不持证。
3. 收紧 Bridge 容器凭证面（已实施）：`docker-compose.agentteams.yml` 与 `bridge.env.example` 移除 Bridge 从不消费的 `AGENTTEAMS_MINIO_*` 注入；主后端 MinIO 凭证走自身配置链（主 compose `minio-init` 建桶不受影响）；`deploy/agentteams/tests/test_minio_compose_contract.py` 改为断言 Bridge 环境不含 MinIO 凭证。

**M7：房间拓扑与通信策略（2026-08-13 评估完成：主体不做，部分做）**

> 结论：**不引入一等 Team 资源、不落地官方四类房拓扑、不实现 peerMentions/channelPolicy**；单团队与多团队场景均维持一 Case 一房。仅做两处低成本收口（事实源注释 + 预留路径记录）。

### M7.1 侦察事实（已核实，不必重查）

- `Case.team_id`（bridge `models.py:227`，默认 `bioops-delivery`）仅三处消费：存入 CaseRecord、Case 详情回显、管理快照按 team 计数。**不参与任何路由/建房/worker 过滤逻辑**。
- `integrations/agentteams/teams/bioops-delivery.yaml` 是静态描述文档，**无任何代码加载**；真正的角色事实源是 `data/ai/*.yaml` 的 `internal_case_role` + `features.agentteams`，经 capability registry 派生（role_agent_map / agent_capabilities / role_labels）。
- 平台无 TeamLeader/Manager 分离：bioops-manager 一肩挑（8.1 映射表）；registry 里没有 manager 角色，M5 的 manager 回复以 agent-general 兜底。
- 房间现状：一 Case 一房；worker 发言经 room_mirror 以 agent 身份镜像进同一房间；绑定靠 `room.created` 证据事件 + Redis hash 双写，反向同步按 case_id 逐房 SSE。
- 官方拓扑（agentscope-ai/AgentTeams）：Team CRD 驱动 Leader Room / Team Room / per-member Worker Room / Leader DM 四类房；`peerMentions` 控制 Worker 互 @，`channelPolicy` 控制跨 Team 通信。

### M7.2 立场与理由

**立场：部分做——拓扑与策略主体不做，仅做低成本收口。**

1. **角色坍缩使四类房退化为现有单房**：官方四类房的前提是 Manager/TeamLeader/TeamAdmin 三角分离（Manager 不进 Team Room、TeamAdmin 只与 TeamLeader 单聊）。平台 bioops-manager = Manager+TeamLeader 合体，用户 = TeamAdmin，M5 已让用户在 Case 房内与 manager 直接对话——Leader Room、Team Room、Leader DM 三类全部坍缩进现有 Case 房；Worker Room（Leader↔Worker 私聊派活）的平台等价物是 WorkItem 状态机 + 租约 + 审计事件，比 Matrix 私聊更可审计，且 worker 是主后端进程内的会诊执行体、不是房间自主聊天者，建 DM 房只有零信息增量的纯投影。
2. **通信策略没有可管的信道**：peerMentions 管 Worker 互 @、channelPolicy 管跨 Team 边界。平台是 manager 中心派发模型——worker 互不直接通信（派活走 work item，汇报走 evidence），且只有一个团队。对不存在的信道声明策略是投机抽象；真出现 worker 自主协作或多团队诉求时再补（届时先改编排模型，策略是后置的）。
3. **一等 Team 资源与现有事实源重复**：团队花名册已由 agent YAML + registry 表达并被 gateway/worker 实际消费；`Case.team_id` 已提供多团队出现时的 join key。新增 Team 表/CRD 只会制造第二份需手工对齐的事实——`teams/bioops-delivery.yaml` 无人加载、与 registry 各自演化，已是这种漂移的实证。

### M7.3 部分做的最小改动

1. **事实源收口（已实施）**：`integrations/agentteams/teams/bioops-delivery.yaml` 头部加注释声明"描述性文档，代码不加载；角色事实源为 `data/ai/*.yaml` + capability registry"，避免后来者把它当配置改。
2. **team 级共享房间的预留路径（不实施，仅记录触发条件与最小路径）**：若未来出现"同团队多 Case 并行、需要团队总览房"的真实诉求，复用现有模式、无需 bridge schema 改动：
   - 建房：`provision_case_room` 同款，`gateway.create_room(name=team_id)`，绑定以 `team_room.created` 锚点事件持久化，Redis hash 增 team→room 绑定；
   - 镜像：`room_mirror` 双路由（case 房 + 该 case `team_id` 对应 team 房），约 30 行；
   - 前端：房间页加 team 房 Tab，约 100 行；
   - 合计约 0.5 天。**触发条件：出现第二个团队或真实多 Case 同屏诉求，否则不做。**
3. **每 agent 独立 Matrix 身份**（官方拓扑对平台唯一有真实增量的部分：Element 侧发言人真实身份）已由 M5 第四刀的动态身份映射（`omichub-user-*` 前缀 + AppService 注册文件 users 正则）覆盖，不在 M7 重复立项。

### M7.4 明确拒绝项与决策理由（归档备查）

| 拒绝项 | 理由 |
|---|---|
| 一等 Team 资源（表/CRD/注册中心） | 与 agent YAML + registry 事实源重复；单团队无消费方 |
| Leader Room / Worker Room / Leader DM | 角色坍缩后无独立语义；派活语义已由 WorkItem 状态机承载 |
| peerMentions 等价物 | Worker 互不通信，无信道可管 |
| channelPolicy 等价物 | 单团队，无跨团队边界 |

> 重估触发器：① 接入第二个团队（多课题组/多交付线）；② worker 获得自主发起同行会诊能力（编排模型先于通信策略变更）；③ 外部通过官方纳管路径接入多 Team 托管实例。任一触发即重开本节。

### 8.4 排查发现的内部漂移清单（随 M4/M5 顺带修复）

| # | 问题 | 状态 |
|---|---|---|
| 1 | P0：`agent_consultation_service.py:215-217` 仍硬编码 workspace_execution 只允许 agent-code/agent-viz，M3 放开未走通最后一道闸 | 本次修复：改查 registry execution_modes |
| 2 | `mas_run_ids` 死字段（bridge models.py:259，无写入点） | 保留作 MAS 挂接预留，注释标注 |
| 3 | 前端 `agentTeams.ts:38` work item status 联合类型缺 claimed/running/awaiting_approval | 随 M4 修复 |
| 4 | `GET /v1/tasks/{id}/events`（bridge app.py:544）名不副实返回 task 详情 | 择机改为真事件列表或改名 |
| 5 | Bridge 容器被注入不消费的 MinIO 凭证 | M6 已收紧 |
| 6 | Gateway audit 只写本地 JSONL，无 Redis Stream 路径（与 bridge 不对称） | 随 M5/M6 评估 |
| 7 | Matrix 正式部署资产（Tuwunel/Higress Helm）缺失 | M5 第四刀已补齐（Tuwunel + Gateway 清单；Higress Ingress 未做） |
