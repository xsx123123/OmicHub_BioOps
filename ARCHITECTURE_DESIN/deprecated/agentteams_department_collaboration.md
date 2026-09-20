# AgentTeams 生物信息协作部门架构提案（2026-08）

> **状态**：Phase 1 已落地；Phase 2 已实现变更决策、取消/重规划/并行支线与交接汇总骨架；Phase 3 已加入产物声明和写冲突串行化基础，容量治理仍在推进。  
> **目标**：把协作室从“Manager 单入口问答 + Worker 事件展示”演进为可控的部门协作空间：用户是甲方，Manager 是客户经理，领域 Agent 是部门负责人；一个 Agent 可以按任务并行派生多个 Worker，等同于该岗位下的多名执行员工。

> **合并说明 / 版本说明（2026-09-18 文档整合）**：本文档为当前稿，2026-08 评审稿（`agentteams_department_collaboration_architecture_2026-08.md`）已于 2026-09-18 文档整合时移除，历史见 git。  
> **时点说明**（自评审稿头注并入）：本提案的设计设想形成于 2026-08 时点，记录当时的设计设想；此后代码已持续演进，部分细节（行号、清单、状态）可能已过期，当前实现以代码及本目录中更新的基线文档（如 agentteams_room_architecture.md、database_architecture.md）为准。

---

## 1. 设计愿景

协作室应像一个专业生物信息分析部门的项目群，而不是一组互不透明的模型调用：

```text
甲方（用户）
  │  提需求、补信息、调整优先级、审批真实计算
  ▼
客户经理（Manager）
  │  澄清目标、组建团队、控制范围/预算/审批、整合对外交付
  ├───────────────┬────────────────┬────────────────┐
  ▼               ▼                ▼                ▼
单细胞部门       bulk RNA 部门     可视化部门       数据/代码部门
agent-scrna      agent-rnaseq      agent-viz         agent-code / agent-data
  │               │                │                │
  └── 多个并行 Worker（各自有工作项、工具上下文、产物和状态） ──┘
```

核心原则：

1. **人和岗位分离**：`agent-scrna` 是单细胞岗位/部门，不等于一个串行执行者；同一 Agent 可为互不冲突的子任务并行派生多个 Worker。
2. **对外单一责任人**：默认由 Manager 面向用户汇总、解释、发起审批；领域 Agent 可被用户点名并直接回复，但不能绕过审批和 Case 约束。
3. **群聊式沟通，工作流式执行**：房间消息是可追溯协作上下文；实际计算仍由 Case、工作项、审批和产物契约控制，不能把聊天文本当成无审计的直接命令。
4. **先停止/冻结，再理解变更**：用户对正在执行的领域 Agent 发言时，系统先令该 Agent 停止领取新工作并冻结受影响工作项；由 Agent 解释变更影响，再决定继续、重规划、拆分新支线或终止。
5. **真实计算必须人工审批**：`自主模式`只能影响沟通与低风险主动性，不能绕过真实计算、写入、费用、提交或质量闸门。

---

## 2. 术语与组织模型

| 概念 | 含义 | 例子 | 是否可并行 |
| --- | --- | --- | --- |
| 用户 / 甲方 | 提出需求、确认范围、批准真实计算的人 | 研究者、项目负责人 | 是，可在不同 Case 发言 |
| Manager | 客户经理 / 项目协调人 | `bioops-manager` | 协调多个领域部门 |
| 领域 Agent | 部门负责人，拥有领域提示词、Skill/MCP 权限与交接责任 | `agent-scrna` | 是，可派生多个 Worker |
| Worker | 一个有边界的具体执行员工 | `scrna-qc-01`、`scrna-deg-02` | 是，受依赖和资源限制 |
| Case | 一个面向甲方的正式项目容器 | “6 个小鼠样本 3v3 单细胞比较” | 是，Case 间隔离 |
| Work item | Case 内可追溯、可租约管理的执行单元 | 上游定量、QC、pseudobulk DEG | 是，按 DAG 依赖 |
| 房间消息 | 群聊式协作消息与审计证据 | `@单细胞助手 请改用 scVI` | 是，但必须落审计 |

### 2.1 “一个 Agent 可以是多个员工”

领域 Agent 不应被建模为唯一进程。建议采用二层编排：

```text
agent-scrna（领域负责人）
  ├─ worker:scrna-intake      输入/样本表/参考基因组核验
  ├─ worker:scrna-upstream    FASTQ → 计数矩阵
  ├─ worker:scrna-qc          质量控制与 doublet 评估
  ├─ worker:scrna-annotation  聚类、marker、细胞注释
  ├─ worker:scrna-comparison  比例差异 + pseudobulk DEG
  └─ worker:scrna-rare-cell   稀有细胞候选发现与验证
```

- Worker 由领域 Agent 按依赖、数据可用性、资源配额和风险派生；不是前端固定展示的“一个助手”。
- 同一领域内可并行的 Worker 必须使用不同 `work_item_id`、独立上下文、独立产物目录和独立工具调用追踪。
- Manager 只管理目标、优先级、跨部门冲突、审批和用户沟通；不应直接替代领域 Agent 做专业决策。

---

## 3. 当前架构与能力边界

### 3.1 当前消息与执行链路

```text
用户在协作室发送消息
  → POST /agent-teams/cases/{case_id}/messages（Case 模式）
    或 POST /agent-teams/rooms/{room_id}/messages（房间模式，未立项房间落房间级事件流，`api/v1/agentteams.py:1061`）
  → room.user_message 审计事件
  → Celery respond_to_room_message
  → AgentTeamsRoomResponseService
  → 默认 Manager 响应 / 受控执行意图识别
  → 路由决策、澄清卡、规划或房间回复
  → Bridge 事件流 / SSE
  → 前端消息流与 Worker 卡片投影
```

当前系统已经具备以下基础：

| 已有能力 | 说明 | 主要位置 |
| --- | --- | --- |
| 房间消息审计 | 用户消息以 `room.user_message` 记录，可经 SSE 历史重载 | `src/cygnusx/application/services/agentteams_service.py` |
| 房间消息历史恢复 | 切换 Case 时前端分页加载全部历史，再从最后事件启动 SSE | `frontend/src/views/AgentTeamsRoomView.vue` |
| 路由决策 | Router/规则根据原始需求选择 Flow 和 lead planner；高置信不要求用户选 Agent | `src/cygnusx/application/services/agentteams_route_decision.py` |
| Manager/领域流程交接 | 正式规划启动后停止 Manager 的重复泛化追问 | `src/cygnusx/application/services/agentteams_room_response_service.py` |
| Worker 进度投影 | work item、Skill、工具调用、产物可在房间内展示 | `frontend/src/utils/agentTeamsRoom.ts` |
| 运行中工作项取消 | Bridge 的 Manager 身份可取消非终态 work item，并级联跳过下游依赖 | `integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py` |
| 人工审批 | 真实计算必须经 Case 人工审批卡确认；旧自动确认标记只清理、不再放行 | `src/cygnusx/application/services/agentteams_service.py` |

### 3.2 当前缺口

> 注：下列多数缺口已由 Phase 1/Phase 2 落地解决（详见 §3.3），表中已标注；剩余缺口为后续阶段目标。

| 缺口 | 当前行为 | 目标行为 |
| --- | --- | --- |
| `@` 提及 | **已解决（Phase 1）**：`AgentTeamsMentionResolver` 统一解析 `@Manager`、领域 Agent、`@所有人` 与文件引用 | 可点名 Manager、领域 Agent、Worker 群组与文件（Worker 群组待 Phase 3） |
| 房间路由 | **已解决（Phase 1）**：依据 `target_agent_id`/`dispatch_mode` 定向投递；无提及才交给 Manager | 同左 |
| Agent 直接回复 | **已解决（Phase 1）**：被点名领域 Agent 可产生只读定向回复（`room.agent_message`），并经 `room.agent_handoff` 向 Manager 交接 | 同左 |
| 任务变更 | **已解决（Phase 2 决策链路）**：定向消息通过 `work_item.interruption_requested`/`room.change_assessment` 建立影响关系，四选一决策已接入真实编排；合作式取消与安全点快照仍待深化 | 先冻结受影响执行，再给出继续/重规划/拆分/终止决策 |
| 并行 Worker | 有 Worker 执行基础，但缺少“部门负责人→多员工”可视化与控制协议 | 每个领域 Agent 下可显示多个 Worker、依赖与占用状态 |
| `@所有人` | **已解决（Phase 1）**：解析为 `broadcast`，只交给 Manager 汇总和有序派发 | 同左 |

### 3.3 Phase 1 已落地能力

当前代码已先实现“可点名、可审计、可安全降级”的第一阶段闭环，但尚未实现 Phase 2 的真实中断与重规划：

| 能力 | 当前实现 | 边界 |
| --- | --- | --- |
| 服务端 Mention 解析 | `AgentTeamsMentionResolver` 统一解析 `@Manager`、`@mamager`、领域 Agent 与 `@所有人`，产出 `mentions/target_agent_id/dispatch_mode` | 当前目录来自运行时能力注册表；Case 参与者快照限制留到后续权限收敛阶段 |
| 消息审计与幂等 | `room.user_message` 保存提及路由、上下文引用和 `client_message_id`；重复客户端消息返回已有事件而不重复写入 | 幂等窗口受事件查询分页上限影响，生产环境应由 Bridge 提供按客户端 ID 的索引查询 |
| 前端点名菜单 | 协作室 `@` 菜单展示 Manager 与当前运行时领域 Agent，同时保留文件引用 | Worker 群组、权限过滤和提及 chip 的结构化回填仍需继续完善 |
| 定向只读回复 | 单个领域 Agent 被点名后，由目标 Agent 生成只读领域答复并写入 `room.agent_message` | 不执行真实计算、不修改计划、不绕过审批；多个 Agent 提及统一回 Manager 协调 |
| 运行中任务保护 | 被点名 Agent 有运行中工作项时写入 `work_item.interruption_requested`，生成只读 `room.change_assessment`，并提供四选一决策入口 | 当前仅 `cancel` 立即调用既有取消能力；resume/replan/branch 先审计记录，后续接入真实编排 |
| Manager 兼容入口 | 无 Agent 提及时、`@Manager`、`@所有人` 仍由 Manager 统一响应和协调；Worker 全部完成后产生 `room.agent_handoff` | Manager 自动消费交接已实现：`AgentTeamsCaseWatchService` 收到 `room.agent_handoff` 后自动触发 `respond_to_room_message` 生成汇总（`agentteams_case_watch_service.py:215-227`） |

Phase 2 当前新增：

- `POST /agent-teams/cases/{case_id}/change-decisions`：提交 `resume/replan/branch/cancel`。
- `cancel` 复用 Bridge 现有 Manager 工作项取消接口，并保留级联跳过语义。
- `replan` 直接把旧工作项经 Bridge Manager 取消接口置为终态 `cancelled`，并由 Bridge 级联跳过未启动的下游依赖（`agentteams_service.py:1729-1743` → `integrations/agentteams/bridge/cygnusx_agentteams_bridge/service.py:936-952`），同时补写 `work_item.interrupted` 审计事件保留原状态与可复用产物引用，再创建同一领域的新只读工作项；`branch` 创建独立并行验证支线。
- `resume`、`replan`、`branch` 均不会绕过人工审批启动真实计算；决策和新工作项都通过审计事件追踪。
- Work Item 支持 `declared_inputs/declared_outputs`；相同输入/输出存在写冲突时自动加入依赖，降级为串行执行。

对应实现文件：

- `src/cygnusx/application/services/agentteams_mention_resolver.py`
- `src/cygnusx/application/services/agentteams_service.py`
- `src/cygnusx/application/services/agentteams_room_response_service.py`
- `src/cygnusx/infrastructure/celery_app/tasks/agentteams.py`
- `frontend/src/components/ai-chat/KimiChatInput.vue`
- `frontend/src/components/ai-chat/MentionMenu.vue`
- `frontend/src/views/AgentTeamsRoomView.vue`

---

## 4. 目标群聊交互协议

### 4.1 提及对象

前端输入框的 `@` 菜单应分组显示，且只展示当前用户对当前 Case 可见的对象：

| 输入 | 目标 | 系统行为 |
| --- | --- | --- |
| `@Manager` / `@mamager` | `bioops-manager` | 处理范围、优先级、报价/审批、跨部门协调、最终汇总 |
| `@单细胞助手` / `@agent-scrna` | 当前 Case 的 `agent-scrna` | 定向投递给单细胞部门负责人 |
| `@可视化助手` | `agent-viz` | 定向投递给可视化部门负责人 |
| `@所有人` | `broadcast` | 仅生成 Manager 协调任务；Manager 决定需要通知的部门 |
| `@文件名` | 工作区文件 | 保留现有上下文引用语义，不等价于 Agent 提及 |

兼容规则：`@mamager` 作为 `@Manager` 的容错别名；展示始终使用用户配置的 Manager 名称。Agent 名称、别名与 `agent_id` 必须来自运行时能力目录，不能在前端或提示词中维护静态列表。

### 4.2 消息分类

每一条房间用户消息应先完成机械解析，再进入模型：

```json
{
  "content": "@单细胞助手 请把整合方法从 Harmony 改为 scVI，并说明影响",
  "mentions": [
    {"kind": "agent", "agent_id": "agent-scrna", "display_name": "单细胞助手"}
  ],
  "target_agent_id": "agent-scrna",
  "dispatch_mode": "direct",
  "context_refs": []
}
```

`dispatch_mode`（与 `agentteams_mention_resolver.py:144-152` 实际枚举一致）：

- `manager`：无 Agent 提及，或 `@Manager`；Manager 是唯一首答者。
- `direct`：单个领域 Agent 被点名；该领域 Agent 是唯一首答者，Manager 收到交接摘要但不抢答。
- `broadcast`：`@所有人`；Manager 先解释涉及哪些部门，再生成受控派发，不直接 fan-out 给所有 Agent。
- `multi_direct`：多个领域 Agent 同时被点名；下游统一转 Manager 协调。

多个领域 Agent 同时被点名时解析为 `multi_direct`，由 Manager 先生成串行或并行派发方案，避免多个 Agent 对同一问题各自输出矛盾答案。

### 4.3 领域 Agent 完成后的交接

领域 Agent 或其最后一个关键 Worker 完成后，必须产生结构化交接事件，而不是仅输出自然语言：

```json
{
  "event_type": "room.agent_handoff",
  "from_agent_id": "agent-scrna",
  "to_agent_id": "bioops-manager",
  "case_id": "...",
  "work_item_ids": ["scrna-comparison-01"],
  "summary": "完成细胞比例比较和 pseudobulk DEG；发现两个候选稀有亚群。",
  "risks": ["3v3 样本量下低效应差异需谨慎解释"],
  "artifact_refs": ["output/results/deg.csv", "output/figures/umap.png"],
  "recommended_next_action": "request_user_review"
}
```

房间中展示为 `@Manager 单细胞部门已完成交接`；Manager 在收到交接后再生成面向甲方的汇总、风险、审批请求或下一阶段建议。

---

## 5. “停止—理解—决定”的任务变更状态机

### 5.1 为什么不能直接取消

用户对正在运行的 Agent 说“改用 scVI”“不做稀有细胞了”“把重点改成免疫细胞”时，直接继续原任务会产生错误产物；直接取消整个 Case 又会丢掉可复用的上游结果。因此需要**冻结受影响范围**，再由领域 Agent 做影响分析。

### 5.2 建议状态

新增工作项状态/事件语义；保留 Bridge 当前 `cancelled` 的终态语义，不能把“等待用户决策”伪装成取消：

```text
running
  → interruption_requested   用户定向消息已收到，禁止领取新子任务
  → interrupted              当前工具调用安全停止点已到达，执行快照已保存
  → change_assessed          领域 Agent 已给出影响与建议
  ├─ resume_approved         继续原计划 / 保留已有结果
  ├─ replan_approved         冻结新计划，等待人工审批后重派发
  ├─ branch_created          新建独立 work item / 子 Case 并行处理
  └─ cancelled               用户明确终止，级联跳过下游
```

### 5.3 变更决策卡

当用户点名正在执行的领域 Agent，系统流程应为：

1. 写入 `room.user_message`（含 `target_agent_id` 与 mentions）。
2. 找出该 Agent 负责、且状态为 `claimed/running/in_progress/awaiting_approval/planning_running` 的工作项（`agentteams_interruption_coordinator.py:10`）。
3. 写入 `work_item.interruption_requested`，阻止新 Worker 领取该 Agent 的后续工作。
4. 对可中断工具请求取消；对不可安全中断的工具标记“将在当前原子步骤完成后停止”。
5. 领域 Agent 在只读上下文中读取用户消息、当前进度、已有产物和依赖图，输出 `room.change_assessment`。
6. 前端展示四选一决策卡：**继续原计划**、**按建议重规划**、**新建并行支线**、**终止该支线**。
7. 涉及真实计算、参数变更或新增资源消耗时，仍走 Case 人工审批；仅解释结果的消息不需要审批。

### 5.4 一致性要求

- 取消、冻结、恢复、重规划和审批必须有独立审计事件；前端只投影事件，不凭本地状态猜测执行结果。
- Worker 工具执行采用合作式取消：每个工具调用在安全点检查 `cancellation_token`；无法中断的外部流程必须如实说明“停止请求已排队”。
- `interrupted` 不是失败。已有产物保留，重规划时由 Agent 判断可复用性并写入证据。
- 一条用户定向消息只影响目标 Agent 的工作域；跨部门依赖由 Manager 决定是否扩大冻结范围。

---

## 6. 目标后端编排

```text
POST /cases/{case_id}/messages
  │
  ├─ MentionResolver（确定 agent / 文件 / broadcast / alias）
  ├─ CaseMessagePolicy（权限、Case 状态、审批与并发校验）
  ├─ Evidence: room.user_message {mentions, target_agent_id, dispatch_mode}
  │
  └─ Celery dispatch_room_message
       ├─ manager     → ManagerRoomResponseService
       ├─ direct      → DomainAgentRoomResponseService(target_agent_id)
       ├─ broadcast   → ManagerCoordinationService
       └─ clarification_reply → 原始 ask_user 的发起 Agent

DomainAgentRoomResponseService
  ├─ 目标 Agent 是否有运行中 work items？
  │    ├─ 否 → 直接做领域答复 / 提议新任务
  │    └─ 是 → InterruptionCoordinator → ChangeAssessment
  ├─ 需要真实计算？→ 冻结计划 → 人工审批
  └─ 完成 / 阶段完成 → room.agent_handoff → Manager
```

> **落地说明**：上图为目标设计形态，其中 `ManagerRoomResponseService`、`DomainAgentRoomResponseService`、`ManagerCoordinationService` 等服务名在代码中并不存在。当前实际落地为单一 `AgentTeamsRoomResponseService`（`agentteams_room_response_service.py`）+ Celery `respond_to_room_message` 任务统一处理 `manager/direct/broadcast/multi_direct` 各分发模式；`AgentTeamsMentionResolver` 与 `AgentTeamsInterruptionCoordinator` 已按原名落地。

### 6.1 新增服务建议

| 服务 | 职责 |
| --- | --- |
| `AgentTeamsMentionResolver` | 基于动态角色目录与 Case 参与者解析 `@`，输出标准 mentions |
| `AgentTeamsRoomDispatchService` | 把消息投递到 Manager、领域 Agent、广播协调或澄清回路 |
| `AgentTeamsInterruptionCoordinator` | 计算受影响 work item、冻结租约、请求合作式取消、保存快照 |
| `DomainAgentRoomResponseService` | 以被点名领域 Agent 身份理解消息，生成直接回复/变更评估/交接 |
| `AgentTeamsHandoffService` | 统一写 `room.agent_handoff`，避免不同 Agent 自由拼接交接文本 |

### 6.2 事件协议建议

| 事件 | 发起者 | 用途 |
| --- | --- | --- |
| `room.user_message` | 用户 | 增加 `mentions`、`target_agent_id`、`dispatch_mode` |
| `room.agent_message` | Manager 或领域 Agent | 可见自然语言回复，必须带 `agent_id` |
| `room.agent_handoff` | 领域 Agent | 向 Manager 结构化交接产物、风险和建议 |
| `work_item.interruption_requested` | 系统 / Manager | 停止领取新工作，发起安全中断 |
| `work_item.interrupted` | 系统 | 旧工作项被 `cancel/replan` 决策取消后的审计记录，含原状态（`previous_status`）与可复用产物引用（`reusable_artifacts`）；并非 Worker 到达安全停止点的快照 |
| `room.change_assessment` | 领域 Agent | 变更影响、推荐操作、是否需要审批 |
| `work_item.resume_decision` | 用户 / Manager | 继续、重规划、分支、终止的审计决定 |

所有事件需具备 `case_id`、`actor`、`recorded_at`、`correlation_id`、`causation_event_id`；所有前端卡片都必须可由历史事件完整重建。

---

## 7. 前端设计

### 7.1 `@` 菜单

将现有文件引用菜单扩展为分组目录：

```text
@ 提及
  项目成员
    🧭 Manager（客户经理）
    🧬 单细胞助手（当前负责：QC、注释）
    📈 可视化助手（空闲）
  群组
    👥 所有人（由 Manager 协调）
  工作区文件
    📄 samples.csv
    📁 input/
```

- Agent/群组提及与文件引用使用不同图标、不同 payload 和不同辅助说明。
- 非当前 Case 参与者默认不出现；可由 Manager 在规划后加入团队。
- 用户输入 `@mamager` 时，菜单纠正为可见标签 `@Manager`。
- 发送前在输入区保留可编辑的提及 chip；不要只做正则高亮。

### 7.2 消息表现

- 领域 Agent 的定向回复显示真实身份、部门和当前负责工作项。
- `@Manager` 交接消息显示为轻量系统/交接卡，不与用户普通消息混淆。
- 变更评估卡必须说明：受影响任务、已完成/可复用产物、预计影响、是否需审批、推荐动作。
- 不允许多个 Agent 同时流式刷屏；`@所有人` 先显示 Manager 的协调消息，随后按计划显示各部门更新。

---

## 8. 分阶段落地建议

### Phase 1：可见但不改变执行（低风险）

1. 前端 `@` 菜单展示 Manager 与 Case 参与 Agent。
2. `room.user_message` 增加 mentions、`target_agent_id`、`dispatch_mode` 审计字段。
3. `@领域 Agent` 可定向产生只读领域答复；无运行任务时不触发中断。
4. `room.agent_handoff` 前端投影和 Manager 汇总入口。

**验收**：`@单细胞助手` 只由 `agent-scrna` 回答；刷新/切换房间后提及与答复完整恢复。

### Phase 2：变更评估与冻结（中风险）

1. 新增 `interruption_requested`、`interrupted`、`change_assessment` 事件。
2. 把 Agent → work item 责任关系写入 Case/Bridge 元数据。
3. 对运行中 Worker 做合作式取消和安全点快照。
4. 前端变更决策卡与审批接入。

**验收**：用户 `@单细胞助手 改用 scVI` 时，上游已完成产物保留；下游受影响任务停止；系统只在确认后重规划并重跑。

### Phase 3：部门并行与容量治理（高风险）

1. Agent 下多 Worker 的并行池、配额和租约可视化。
2. 按资源、数据依赖、工具冲突自动生成 worker wave。
3. Manager 处理跨部门优先级冲突、预算和交付 SLA。
4. `@所有人` 广播由 Manager 转化为有序派发 DAG。

**验收**：同一单细胞 Case 可并行进行参考资料检索、样本表核验、marker 知识准备；不与同一输入文件的写入型上游流程产生竞争。

---

## 9. 风险与非目标

### 风险

- **并发冲突**：同一输入/输出路径被多个 Worker 写入，必须通过工作目录隔离、产物声明和资源锁避免。
- **上下文泄漏**：不同 Worker、不同 Case 的文件与消息必须按 `case_id/work_item_id` 隔离。
- **Agent 抢答**：广播或多提及不应直接 fan-out，Manager 必须有节流与编排权。
- **伪中断**：外部流程不支持即时取消时，UI 必须明确“将在安全点停止”，不能显示为已停止。
- **审批绕过**：任何重新执行、参数改变、额外计算资源或写入行为都要回到审批契约。

### 非目标

- 不把 Case 替换为纯即时聊天；Case、审批、Work item 和证据仍是权威执行状态。
- 不承诺每个领域 Agent 都可直接运行任意流程；仍受能力目录、Skill、MCP、资源和权限约束。
- 不让用户通过 `@Agent` 直接绕过 Manager 修改全局项目范围或审批结果。

---

## 10. 评审问题

在实施前建议确认以下产品决策：

1. 被点名的领域 Agent 是否允许直接向用户提问，还是必须由 Manager 转述？建议：允许领域问题直接提问，但范围/预算/审批仍由 Manager 负责。
2. `@所有人` 是否要真正展示多个答复？建议：默认只展示 Manager 协调结果；需要时显示有限的部门状态更新，不做无序群发。
3. “停止任务”默认采用暂停还是取消？建议：先采用**冻结 + 合作式中断**；只有用户明确终止才写 `cancelled`。
4. 一个 Agent 的并行 Worker 上限由谁决定？建议：能力目录声明上限，Manager 再结合项目配额和资源状态裁决。
5. 领域 Agent 的直接回复是否纳入最终报告？建议：纳入 Case 审计；最终对外交付仍由 Manager 汇总并附领域交接证据。

---

## 11. 结论

该方案可在不推翻当前 AgentTeams Case/Bridge/审批架构的前提下实现。现有系统已经有审计事件、房间消息、Worker 进度、工作项取消和人工审批等关键地基；主要新增内容是：**提及解析与定向投递、Agent—Work item 责任映射、可恢复的中断状态机，以及标准化领域交接事件**。

推荐先实施 Phase 1，先让协作室“像群聊一样可点名沟通”，再进入 Phase 2 的执行中断与重规划；这样可先验证用户的协作习惯和部门边界，避免过早把复杂中断机制投入生产。
