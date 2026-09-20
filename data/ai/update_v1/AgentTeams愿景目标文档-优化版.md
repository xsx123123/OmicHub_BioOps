# AgentTeams 最终目标：用户参与的单窗口多专家群聊（优化版）

> 版本：1.1（审核优化版，基于 v1.0 修订）
> 日期：2026-08-11
> 性质：产品架构最终目标与验收标准
> 配套施工计划：`AgentTeams_CONVERGENCE_PLAN.md`（v1.1）
>
> 本文替代以下过时/重叠文档成为 AgentTeams 的唯一权威目标描述：
> - `data/ai/update/AgentTeams_update.md`（v1 比赛交付版）
> - `data/ai/update/AgentTeams_update_v2.md`
> - `data/ai/update/AgentTeams_update_v2.1.md`
> - `data/ai/update/AgentTeams_update_v2.2_report.md`
> - `data/ai/update/AgentTeams_codex_prompt*.md`
> - `data/ai/update/update_agent.md` 中关于 AgentTeams 的章节
>
> 旧文档全部移入 `data/ai/update/archive/` 归档，不再作为执行依据。
>
> v1.1 修订要点：统一 Agent 计数口径；补齐 15 态状态机清单与失败语义；明确三类审批的适用边界；
> 补充计划版本/修改规则、非功能需求（时延、可观测、并发配额）、动态网页报告预览的安全约束；
> 修正 `target` 命名示例漂移；验收标准增加异常路径。

---

## 当前交付状态（2026-08-11）

**当前结论：本文定义的核心产品闭环已完成实现并完成自动化与本机部署验证，现进入平台页面试运行验收。** 用户可继续在平台页面测试；新增问题应回写为缺陷、补充自动化覆盖，并按本文的产品边界修复。

### 已实现

- 用户在当前聊天窗口内完成 Case 创建、计划确认/修改/取消、审批、追问、执行进度、失败重试、终止、刷新恢复和结果回流；不再依赖 Matrix/Element 外链群聊。
- AgentTeams 只负责编排，平台专家通过 Bridge/Gateway 和 Worker 资源池执行；14 个可招募专家的运行身份已在本机部署中完成心跳验证。
- 角色映射、审批令牌、审计事件、报告沙箱预览、配额/并发控制、游标双写迁移和延迟校验工具均已落地，并有对应受影响模块的自动化回归。

### 尚待真实运行验收

- 需在真实浏览器中为事件可见和审批受理各采集至少 20 条样本，确认 §9.1 与 §10.2 的 P95 门槛；当前不得据此宣称性能验收完成。
- Case 事件游标当前保持 `dual_write`。只有 watcher 连续 3 个自然日记录零 mismatch 后，才可依据部署文档切换到 `new_only`；迁移期间保留 `legacy_only` 回退能力。
- 领域主管（Domain Manager）为独立的后续增量机制，是否启用及其验收以 `AgentTeams领域主管机制-优化版.md` 为准，不因本轮核心收敛交付而自动视为上线。

---

## 1. 一句话定位

**AgentTeams 是 CygnusX 里“用户参与的单窗口多专家群聊”背后的编排框架。**

用户只在当前 AI 助手 / Studio 聊天窗口里发任务、看进展、做决策；多个平台真实 Agent 以各自头像和人格在同一窗口里轮流发言、协作把任务做完；AgentTeams 负责这些专家之间的状态机、工作项派发、审批、审计和跨角色上下文传递。

---

## 2. 最终用户体感

用户发起一个复杂请求后，聊天窗口里依次出现：

1. **Manager 接单**：主 Agent 说明“我将协调几位专家一起完成”，并说明**为什么**需要开启群聊（触发理由对用户可见）。
2. **规划专家发言**：领域 Agent 输出计划摘要（如 RNA-seq 分析师给出分析方案）。
3. **计划确认卡**：用户在窗口内确认 / 修改 / 取消；**修改会生成新的计划版本并重新确认**（见 §8.3）。
4. **专家陆续入群**：数据管理员、领域分析师、代码助手、可视化助手、质控员等以各自头像出现，显示“正在处理”。
5. **逐个回流**：谁先完成，谁先在群里发言，附上结果摘要和产物。
6. **Manager 点评**：每条专家结果回流后，系统自动触发 Manager 验收点评（一个隐式的 manager review Work Item），决定接受、返工或触发下游。
7. **用户被@**：需要决策时（高风险审批、信息不足），群里弹出询问卡片，用户就地回答。
8. **最终交付**：主 Agent 汇总结论、产物清单、质控结论和限制；`agent-delivery` 可生成 Plotly 等动态可视化网页报告，在聊天内以**沙箱化 iframe** 直接预览（见 §8.4 安全约束）。

整个过程中用户**不跳转到独立 Case 页、不打开 Element 外链、不离开当前聊天窗口**。

异常路径同样被覆盖：专家失败自动重试并告知用户、长时间无响应给出超时提示、用户可随时在窗口内终止整个 Case（见 §6.3、§10.1）。

---

## 3. 架构总览

```text
┌─────────────────────────────────────────────────────────────────┐
│  前台：AI 助手 / Studio 单窗口聊天                                │
│  复用组件：room_speech / overdrive_progress / AskUserCard        │
│         / OverdriveApprovalCard / 产物下载面板                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ SSE / HTTP
┌────────────────────────────▼────────────────────────────────────┐
│  编排框架：AgentTeams Bridge + Gateway + Worker 集群              │
│  - Case 状态机（15 态，见 §6.1）                                  │
│  - Work Item 租约 / 认领 / 重试（至多 3 次，指数退避）            │
│  - 审批与 HMAC 签名                                               │
│  - append-only 审计事件                                           │
│  - 角色 → 平台 Agent 映射（单一来源 registry）                    │
│  - MinIO/S3 case 级共享存储                                       │
└────────────────────────────┬────────────────────────────────────┘
                             │ execute-readonly / workspace_execution
┌────────────────────────────▼────────────────────────────────────┐
│  执行大脑：CygnusX 平台真实 Agent（data/ai/*.yaml 定义）           │
│  - consultation 端点调用 ParallelSubAgentService                 │
│  - 携带该 Agent 自己的提示词 / Persona / Skill / MCP / 工具白名单   │
│  - 以 requester_ref 对应的真实用户身份运行                        │
└─────────────────────────────────────────────────────────────────┘
```

### 3.1 关键边界

- **AgentTeams 不运行 LLM，只编排工单。** 所有“思考”都发生在 CygnusX 平台 Agent 的 consultation 回合里。
- **AgentTeams 不替代平台 Agent 权限体系。** 每个专家能调用什么工具，仍由 `data/ai/*.yaml` 和 Tool Pack 决定。
- **AgentTeams 不新建虚构角色。** 用户看到的每个头像都对应平台上一个真实、已启用的 Agent。
- **用户是群聊成员。** 计划确认、高风险审批、澄清提问都发生在同一条对话流里。
- **所有跨服务日志与指标必须携带 `case_id` / `work_item_id`**，保证一次群聊可全链路追踪（见 §9.3）。

---

## 4. 角色与可用 Agent 清单

### 4.1 计数口径（v1.1 新增，解决 v1.0 中“16 个 Agent”口径不一的问题）

平台共定义 **16 个 Agent**，在 AgentTeams 中分三类：

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 可招募专家 | 14 | 承接 Work Item、在群里发言交付结果 |
| 轻量陪伴 | 1（`shania`） | 可入群轻量发言，**不承接 Work Item、不进入重任务编排** |
| 入口路由 | 1（`agent-router`，星尘 AI） | 仅做入口路由，不作为群聊专家发言 |

因此验收口径统一为：**全部 14 个可招募专家均可在群聊中被招募**（v1.0 中“16 个 Agent 都可被招募”与 shania 的备注自相矛盾，已修正）。

### 4.2 Manager

Manager 由当前会话主 Agent 担任（通常为 `agent-router` 路由后的 `agent-general`，或用户直接对话的领域 Agent）。Manager 是**编排者**：接单、说明触发理由、选规划专家、审核计划、协调专家、点评结果、汇总交付。Manager 不通过 Work Item 执行；`agent-general` 同时保留“通用助手”专家身份，可被招募承接需求澄清类工单。

### 4.3 可招募专家（14 个）

| 角色 | 平台 Agent（角色 ID 与 Agent ID 同名） | 职责 |
| --- | --- | --- |
| 数据管理员 | `agent-data` | 文件/样本/元数据预检、输入完整性审查 |
| RNA-seq 分析师 | `agent-rnaseq` | RNA-seq 规划、解读、结果解释 |
| ATAC-seq 分析师 | `agent-atacseq` | ATAC-seq 规划与解读 |
| 单细胞分析师 | `agent-scrna` | 单细胞完整分析 |
| 单细胞上游专家 | `agent-scrna-upstream` | FASTQ / Cell Ranger / 上游 QC |
| 单细胞整合专家 | `agent-scrna-integration` | 整合、聚类、批次校正 |
| 单细胞高级专家 | `agent-scrna-advanced` | 注释、轨迹、通讯 |
| 代码助手 | `agent-code` | 脚本实现、代码审查、复现 |
| 可视化助手 | `agent-viz` | 图表、出版级绘图 |
| 质量审计员 | `agent-qc` | 独立质控、证据审查、三态结论 |
| 交付报告员 | `agent-delivery` | 交付清单、runbook、证据汇总 |
| 云运维工程师 | `agent-cloud-ops` | 平台健康、资源、故障分诊（管理员场景） |
| 通用助手 | `agent-general` | 需求澄清、跨领域协调 |
| MCP 构建师 | `agent-mcp-builder` | MCP 构建相关任务 |

### 4.4 角色映射单一来源

**声明层单一来源是各 Agent YAML**：每个 Agent 在自己的 YAML 中通过 `features.internal_case_role`、`features.agentteams`（执行模式、Case 模式工具包排除、并行上限等）和 `capability_scope` / `capability_tags` / `accepts_inputs` / `produces_outputs` 声明自己的角色与能力；`AgentTeamsCapabilityRegistry` 由这些 YAML **自动聚合生成**，是声明层的物化视图，不允许手工登记第二份映射。模板参照 `data/ai/atacseq.yaml`。

生成的 registry 有三处消费，必须一致：

1. Bridge `service.py` 在创建 Work Item 时解析 target。
2. Gateway `agent_policies` 校验 capability 与 tool 白名单。
3. `CaseRoomProjector` 把审计事件 actor 投影为前端头像/名字。

禁止在 Bridge/Gateway/Worker 里再写一份硬编码映射。

---

## 5. 单窗口群聊流程

### 5.1 触发条件

当用户请求满足以下任一条件时，Manager 决定开启 AgentTeams 群聊：

- 涉及多个领域（如 RNA-seq + 可视化 + QC）
- 需要多步骤执行和独立质控
- 需要用户多次决策
- 明确需要“专家团队协作”

简单问答、单步低风险任务仍由单个 Agent 直接回答，不走群聊。

**自动建单的治理（v1.1 新增）**：Manager 自动创建 Case 时必须满足——
1. 在群里显式说明触发理由（命中了哪条触发条件）；
2. 创建动作携带幂等键（`session_id + 意图哈希`），同一会话同一意图不会重复建单；
3. 用户在计划确认前可一键取消，取消不留任何运行中工单；
4. 所有自动触发决策落审计日志，用于后续评估触发准确率、避免过度编排。

### 5.2 群聊阶段

```text
Manager 接单（说明触发理由）
  → 选择 lead planner（真实领域 Agent）
  → planning_running：lead planner 出 plan.md + 参数草案
  → 校验失败 → 退回修订（≤5 轮；超过上限升级给用户决策，见 §6.3）
  → 计划确认卡（用户在同窗口确认 / 修改 / 取消）
  → preflight_running：数据管理员等做串行前置
  → executing：多专家并行 Work Item，结果逐个回流到群聊
  → 每条结果回流 → Manager 自动验收点评（接受 / 返工 / 触发下游）
  → quality_running（可选）：仅当 lead planner 在已确认计划中声明需要时，由 agent-qc 独立质控
  → delivery_ready：agent-delivery 汇总交付，支持 Plotly 等动态可视化网页报告
  → closed：Case 关闭，交付清单可下载
```

每个阶段转换都写审计事件，并投影为 `room_speech` 或 `overdrive_progress`。

**QC 触发决策权（v1.1 明确）**：是否进入 `quality_running` 由 lead planner 在计划中显式声明，用户在计划确认时一并确认；不允许在执行中临时插入未声明的质控环节。

### 5.3 消息类型

| 场景 | SSE 类型 | UI 形态 |
| --- | --- | --- |
| 专家发言 / 结果回流 | `room_speech` | 带头像、名字的气泡 |
| 专家正在处理 | `overdrive_progress` | 泳道进度条 / 招募卡 |
| 需要用户决策（含计划确认） | `ask_request` | 弹窗卡片 |
| 高风险操作审批 | `overdrive_approval_request` | 审批卡片 |
| 模式切换 | `mode_changed` | 进入/退出群聊态 |
| 产物就绪 | `overdrive_progress` + artifacts | 文件下载入口 |

所有类型都是前端已识别的既有事件，**不新造事件类型**；允许在既有事件的 payload 中扩展字段（如专家头像、角色名），扩展字段须写入契约测试固定下来。

### 5.4 三类“审批/确认”的适用边界（v1.1 新增，避免机制混用）

| 机制 | SSE / API | 适用场景 | 超时策略 |
| --- | --- | --- | --- |
| 计划确认卡 | `ask_request(kind=plan_confirmation)` | 计划确认 / 修改 / 取消；澄清提问 | 默认 24h 未响应则暂停 Case 并提醒 |
| 高风险操作审批 | `overdrive_approval_request` + HMAC 签名 | 写操作、删除、外部调用等高风险动作 | 未批准前工单阻塞；拒绝则工单失败并回流原因 |
| Case 提交审批 | `POST /cases/{id}/submit`（卡片内按钮） | 用户在建单后正式提交启动 | 无，用户主动动作 |

---

## 6. Case 状态机与失败语义

### 6.1 15 态清单（v1.1 补齐；实现侧以 `case_store.py` 为准，若不一致以代码为准并回写本节）

| # | 状态 | 含义 |
| --- | --- | --- |
| 1 | `created` | 建单未提交 |
| 2 | `planning_pending` | 规划工单已创建待认领 |
| 3 | `planning_running` | lead planner 规划中 |
| 4 | `planning_revision` | 计划校验失败退回修订（计数 ≤5） |
| 5 | `plan_confirmation_pending` | 等待用户确认计划 |
| 6 | `preflight_pending` | 前置工单待认领 |
| 7 | `preflight_running` | 串行前置执行中 |
| 8 | `executing` | 专家并行执行中 |
| 9 | `quality_pending` | 质控工单待认领（可选路径） |
| 10 | `quality_running` | agent-qc 独立质控中 |
| 11 | `delivery_running` | delivery 汇总中 |
| 12 | `delivery_ready` | 交付就绪待查收 |
| 13 | `closed` | 正常关闭 |
| 14 | `failed` | 失败终态（含修订超上限、审批拒绝、重试耗尽） |
| 15 | `cancelled` | 用户主动终止 |

### 6.2 关键转换约束

- 未经过 planning 且无已确认 `plan_hash`，不得进入 `preflight_pending` / `executing`。
- `workspace_execution` 工单必须绑定已确认的 `plan_hash`；计划被修改后旧 hash 立即失效。
- 用户取消可从任意非终态进入 `cancelled`：运行中工单收到取消信号，已产出产物保留并标记 `cancelled_at`。

### 6.3 失败与超时语义（v1.1 新增）

- **Work Item 重试**：失败自动重试至多 3 次，指数退避（如 30s/2min/8min）；第 3 次失败后 Case 转 `failed` 或按依赖关系仅阻塞下游，由 Manager 在群里说明并给出“重试 / 跳过 / 终止”选项。
- **修订上限**：规划修订超过 5 轮，升级给用户：继续修订 / 更换 lead planner / 取消。
- **专家超时**：consultation 调用设可配置超时（默认 10 分钟）；超时按失败处理进入重试。
- **审批/确认超时**：见 §5.4；超时 Case 暂停（保持当前状态 + `paused_reason`），用户回来后可继续。
- **断线恢复**：Worker 宕机时租约到期自动回收工单重新派发；前端刷新后凭事件游标重建群聊。

---

## 7. 与旧路径的关系

### 7.1 保留并作为唯一前台

- **超频模式（overdrive room）前端组件**：`room_speech`、`overdrive_progress`、`AskUserCard`、`OverdriveApprovalCard` 全部复用。
- **AgentTeams Bridge/Gateway/Worker**：作为编排框架完整保留。
- **consultation 端点 + ParallelSubAgentService**：作为专家执行内核保留。

### 7.2 移除或降级

| 旧路径 | 处理方式 | 原因 |
| --- | --- | --- |
| MAS 编排（orchestrator + DAG） | **移除启用逻辑**，保留代码但默认关闭、不再作为产品入口 | 与单窗口群聊形态冲突；默认关闭已证明不可见 |
| 对话内 fan-out (`parallel_subagents`) 在 AgentTeams 场景下 | **收敛其使用范围**：常规 AI 助手页面继续保留；AgentTeams 群聊内不走 fan-out，改由 Bridge Work Item 编排 | 避免两条 multi-agent 路径竞争；保留常规页面轻量并行能力 |
| AgentTeams Matrix/Element 外链群聊 | **移除 Element iframe 抽屉/外链入口** | 体验割裂，不是产品内原生群聊 |
| 独立 Case 详情页作为主入口 | **保留但仅作为审计详情入口**，不强制跳转 | 复杂任务必须在聊天内闭环 |
| 旧版 v1/v2/v2.1/v2.2 施工文档 | **移入 archive/** | 版本爆炸、互相引用错误 |

### 7.3 历史数据

已存在的 AgentTeams Case 记录和审计事件继续保留，但前端不再展示 Element 外链入口，只展示投影后的 room_speech 时间线。

---

## 8. 数据契约

### 8.1 Case 与 Work Item

沿用现有 `CaseRecord` / `WorkItemRecord` 模型：

- `case_id`：一次用户任务对应一个 Case。
- `work_item_id`：一个专家任务对应一个 Work Item。
- `target`：AgentTeams 角色 ID。**命名规范（v1.1 统一）**：角色 ID 与平台 Agent ID 同名（如 `agent-rnaseq`、`agent-data`）；历史数据中的旧身份名（如 `data-steward`）作为 registry 中的别名保留映射，新数据一律使用同名规范。
- `agent_id`：由角色映射解析出的平台 Agent ID。
- `execution_mode`：`readonly_consultation` 或 `workspace_execution`。
- `depends_on`：DAG 依赖。
- `context_refs` / `evidence_refs`：结构化上下文引用。
- `plan_hash`：已确认计划的 sha256，未确认不得进入执行。

### 8.2 产物与共享存储

- case 级共享前缀：`s3://agentteams-evidence/{case_id}/`，访问权限按 Case 创建者身份隔离。
- 专家产物写入该前缀，下游通过 `artifact_fetch` 拉取。
- 同时登记 `file_records`（`source="agentteams"`），保证 `/files` 页面可见。
- 大文件走 S3，小预览走 `workspace_file_preview`（20KB）。
- **输入文件只读保护**：用户真实数据目录以只读 bind mount（`mode: "ro"`）挂载到沙箱 `/data/platform`；沙箱内 `input/`、`ref/` 仅放指向只读挂载的引用。注意：不得依赖“软链 + 可写目录”实现只读——软链本身可被删除替换，只读保证必须来自挂载层，防止专家误删或覆盖原始数据。

### 8.3 计划版本与修改规则（v1.1 新增）

- 计划以 `proposed_submission` + `plan_hash` 表示；用户确认后冻结。
- 用户选择“修改”时生成**新计划版本**（`plan_version` 递增），重新走确认；旧 `plan_hash` 立即失效，已派发但未开始的工单重绑新 hash，已开始的工单不受影响并在群里公示。
- 计划确认卡展示：`plan_version`、`plan_hash` 前 8 位、摘要、关键参数。

### 8.4 动态网页报告预览的安全约束（v1.1 新增）

- Plotly 等动态 HTML 报告在聊天内预览时必须使用 **sandboxed iframe**（禁止 `allow-same-origin` 与 `allow-scripts` 同时开放之外的权限，按需最小化），并附加严格 CSP。
- 预览内容只允许加载 Case 产物前缀内的静态资源，不允许携带用户会话凭证发起请求。

### 8.5 群聊消息持久化

- Bridge 审计事件是权威来源。
- `CaseRoomProjector` 把审计事件投影为 SSE chunk。
- 前端按 `event_id` / `idempotency_key` 去重，保证刷新后可重建。
- 事件游标从 `sandbox_meta` 迁移到独立 `agentteams_case_cursors` 表（迁移采用双写过渡，见施工计划 Phase 2）。

---

## 9. 非功能需求（v1.1 新增章节）

### 9.1 时延预算

- 审计事件产生 → 前端可见：**P95 ≤ 3s**。状态变化应优先走事件驱动推送；watch 轮询（10–15s）仅作为非事件驱动来源的兜底，不得成为主链路。
- 用户点击审批/确认 → 后端受理：P95 ≤ 1s。

### 9.2 并发与配额

- 单 Case 并行 Work Item 上限默认 8（可配置）。
- 单用户同时活跃 Case 上限默认 3；超出排队并在群里提示。
- Worker 按 capability 认领工单形成资源池，避免为每个角色固定独占一个 Worker 服务（部署形态见施工计划 §4.2 说明）。

### 9.3 可观测性

- 指标：Case 端到端时长、各状态停留时长、Work Item 失败/重试率、审批等待时长、自动建单触发次数与用户取消率（用于评估触发准确率）。
- 日志：全链路携带 `case_id` / `work_item_id` / `event_id`。
- 告警：Case 卡在非终态超过阈值（默认 2h）告警。

### 9.4 安全

- 审批 HMAC 签名密钥按环境隔离，定期轮换。
- 身份令牌（bridge/worker）不落入仓库，走密钥管理；`bridge.env.example` 只放占位符。
- 共享存储按 Case 前缀做访问控制，跨用户不可见。

---

## 10. 验收标准

### 10.1 功能验收

**主路径**：在一个聊天窗口内跑完一个复合任务（例如 RNA-seq + QC + 可视化）：

1. Manager 接单并说明将协调哪些专家、触发理由是什么。
2. 规划专家（如 `agent-rnaseq`）在群里发言交付计划。
3. 用户在窗口内确认计划，不跳转页面。
4. 至少 3 个不同职能专家真实参与并发言。
5. 专家结果按完成顺序逐个回流，附带产物。
6. Manager 对每条结果自动做验收点评。
7. 计划中声明需要质控时，`agent-qc` 给出真实三态结论（PASSED / WARNING / BLOCKED）；未声明时不得出现质控环节。
8. `agent-delivery` 汇总交付，产物可下载；动态网页报告在沙箱化 iframe 内预览。
9. 遇到高风险操作时，窗口内弹出审批卡（机制符合 §5.4 边界）。
10. 刷新页面后，同一 Case 的发言、进度、状态可重建。

**异常路径（v1.1 新增，必测）**：

11. 计划“修改”：生成新版本、旧 hash 失效、群里有版本提示。
12. 专家失败：自动重试可见，重试耗尽后用户可选重试 / 跳过 / 终止。
13. 用户中途取消：任意阶段可取消，运行中工单被回收，产物保留可查。
14. 断线恢复：Worker 重启后工单被重新认领，前端刷新后群聊完整重建。
15. 计划修订超 5 轮：正确升级给用户决策。

### 10.2 非功能验收

- 全部 14 个可招募专家均可被招募（口径见 §4.1）。
- 角色映射单一来源，无硬编码漂移（契约测试覆盖三处一致性）。
- Bridge/Gateway/Worker 仍可通过原有契约测试。
- 简单问答不走 AgentTeams，避免过度编排；自动建单决策有审计记录。
- 时延、并发、可观测性达到 §9 要求。
- 不再依赖 MAS / Element 外链；AgentTeams 场景下不再独立使用 fan-out。

### 10.3 完成定义（Definition of Done）

只有当以下全部满足时，才宣布 AgentTeams 收敛完成：

- [ ] 旧版文档已归档，本文件成为唯一权威目标。
- [ ] MAS 编排默认关闭且不再进入主入口。
- [ ] AgentTeams 场景下 fan-out 已收敛；常规 AI 助手页面的 fan-out 能力保留。
- [ ] Element 外链入口已移除。
- [ ] 独立 Case 详情页不再作为强制入口。
- [ ] 角色映射表统一并三处一致。
- [ ] 全部 14 个可招募专家可在群聊中被招募。
- [ ] 计划确认（含修改生成新版本）、审批、ask_user 全部在聊天窗口内闭环。
- [ ] 端到端主路径 + §10.1 异常路径全部通过。
- [ ] §9 非功能指标达标并有看板。
- [ ] 回归测试全绿。

---

## 11. 附

### 11.1 旧文档归档清单

以下文件移入 `data/ai/update/archive/`，不再作为执行依据：

- `AgentTeams_update.md`
- `AgentTeams_update_v2.md`
- `AgentTeams_update_v2.1.md`
- `AgentTeams_update_v2.2_report.md`
- `AgentTeams_codex_prompt.md`
- `AgentTeams_codex_prompt_v2.1.md`
- `AgentTeams_codex_prompt_v2.2.md`
- `update_agent.md` 中关于 AgentTeams 的章节（保留该文件本身，但删除其 §12.1 及 AgentTeams 相关段落，统一引用本文）

### 11.2 术语表（v1.1 新增）

| 术语 | 定义 |
| --- | --- |
| Case | 一次用户复合任务的编排实例，对应一个群聊 |
| Work Item | 派给单个专家的最小工单，有租约、可重试 |
| Manager | 当前会话主 Agent，负责编排与点评，不承接 Work Item |
| lead planner | 负责出计划的领域专家，由 Manager 按任务方向选择 |
| room_speech | 群聊气泡 SSE 事件，承载专家发言 |
| plan_hash | 已确认计划内容的 sha256，执行型工单的准入凭证 |
| 三态结论 | agent-qc 的 PASSED / WARNING / BLOCKED 质控结论 |
