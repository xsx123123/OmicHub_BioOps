# 超频模式升级方案：研究先行、计划确认、人格化异步 Agent 团队

> 更新日期：2026-08-10
>
> 文档性质：目标架构 + 状态机 + 数据契约 + 分阶段施工方案；本文不直接修改业务代码。
>
> 现状依据：`data/ai/README.md` §13–§16，以及当前的 `chat_service.py`、
> `parallel_subagent_service.py`、`overdrive_*` 服务、Agent YAML 与前端超频组件。
>
> 目标基线：在现有超频模式上演进，不另造一套用户入口。
>
> AgentTeams 的长期目标与施工依据统一见
> `data/ai/update/AgentTeams_VISION_FINAL.md` 与
> `data/ai/update/AgentTeams_CONVERGENCE_PLAN.md`（v1.1）。本文仅保留超频模式的历史设计背景，
> 不再作为 AgentTeams 的执行依据；执行者始终是平台 `data/ai/*.yaml` 定义的真实 Agent。

---

## 1. 最终目标

将现有超频模式统一为下面这一条可感知、可恢复、可审计的流程：

```text
用户发布任务
  → 主 Agent 判断任务方向并选择最合适的规划 Agent
  → 规划 Agent 并发研究：平台知识库 + 网络搜索 + 模型通用知识
  → 规划 Agent 创建 plan.md 并交回主 Agent
  → 主 Agent 审核计划，并通过弹窗请用户确认 / 修改 / 取消
  → 用户确认后，主 Agent 独立完成必须串行的前置工作
  → 主 Agent 按能力招募带定制人格的执行助手
  → 主 Agent 与助手真异步并行工作
  → 助手按完成顺序逐个回流，主 Agent 逐条点评、验收和纠偏
  → 主 Agent 根据结果动态发起后续波次
  → 质控、整合并统一交付产物与结论
```

这不是“先展示几张多人卡片，再在后台同步等待”的体验优化，而是超频运行时的目标语义。
以下五项属于硬约束：

1. **研究先于计划**：复杂任务不能直接生成分工；应先完成三路研究，再形成计划。
2. **计划先确认再执行**：计划阶段仅允许只读研究和写入 `plan.md`；用户确认前不得启动正式
   分析、代码执行、外部写操作或执行助手波次。
3. **主 Agent 先做串行前置**：文件核验、数据契约、Skill 加载、依赖安装审批等不能伪并行。
4. **真正异步**：助手运行时主 Agent 能继续执行自己的任务；单个助手完成即回流，不等全员。
5. **动态多波次**：后续波次由已完成结果和计划条件触发，不在首轮把所有角色机械地一次招满。

简单问答、闲聊、单一步骤且低风险的请求无需强制进入本流程；主 Agent 可以直接回答。只要任务
进入“正式执行 / 多 Agent 协作”路径，上述确认闸门就不可绕过。

### 1.1 单窗口心智模型（Kimi 式集群）

用户对多 Agent 协作的体感预期是：**在同一个聊天窗口里，像一群专家在群里协作把活干完**，
而不是跳到独立工单页或后台任务列表。因此本方案的前台形态固定为：

- **一个入口**：用户只在当前 AI 助手/工作台对话里发任务、看进展、做决策，不切页面。
- **一个 Manager**：当前会话绑定的主 Agent（通常是星尘 AI/`agent-general`）是唯一对用户负责的
  协调者，负责接单、选规划专家、出计划、确认、派活、点评、汇总。
- **一群真实专家在同一房间发言**：每个被招募的平台专家（`agent-rnaseq`/`agent-code`/
  `agent-qc` 等）以**自己的头像、名字、Persona 风格**在对话流里分条发言；发言不是批量汇总，
  而是谁先完成谁先出现（逐个回流），下面紧跟 Manager 的具体点评。
- **决策就地发生**：计划确认、高风险工具审批、向用户提问都以卡片形式插在同一条对话流里，
  用户就地操作，不另开审批页。
- **进度可感、断线可续**：招募花名册、泳道进度、阶段产物都投影在窗口里；刷新/断线后凭
  run 快照 + 事件游标重建同一房间的全部发言与状态。

实现上，单窗口不等于"阻塞式等整波完成再一起渲染"。真正的语义是：**每个专家是独立的后台 job，
完成一个就向房间投递一条带 `senderAgent` 的 `room_speech` 事件**，Manager 据该结果即时点评并
决定是否解锁下游任务（见 §4 阶段 G–I、§7.2）。同步 fan-out/批量汇总只是开发期兼容回退，
不构成"Kimi 式集群"的验收。

> 前台投影契约：所有发言/进度/决策复用既有 SSE 类型 `room_speech` / `overdrive_progress` /
> `ask_request(kind=plan_confirmation)` / `overdrive_approval_request` / `mode_changed`，
> 不新造前端不认识的事件类型（与 README §14.4 一致）。

---

## 2. 现状与目标差距

### 2.1 可复用的现有能力

- `_run_overdrive_turn()` 已能读取候选 Agent、按能力生成 assignments、计算依赖波次并输出
  `room_speech`、`overdrive_progress`、`ask_request` 和审批事件。
- `ParallelSubAgentService` 已具备受限子循环、并发、超时、重试、失败隔离以及
  `worker_started` / `worker_finished` 回调。
- `OverdriveManifest` 已能原子写入 manifest、任务状态、结果、摘要和进度日志，可作为持久化
  状态机的起点。
- 前端已有 Manager / worker 气泡、超频进度卡、`AskUserCard` 和高风险审批卡，可复用同一套
  群聊心智模型。
- 普通聊天运行时已有 `knowledge_search` 与 `web_search`；专业提示词已经定义“知识库优先、
  网络补充、模型知识只负责解释与串联”的证据纪律。
- Agent YAML 已有 `default_role`、`capability_scope`、输入/输出契约和颜色头像，适合扩展人格字段。

### 2.2 必须补齐的差距

| 编号 | 当前问题 | 目标状态 |
| --- | --- | --- |
| G1 | Manager 生成 assignments 后基本直接进入执行 | 先由规划 Agent 完成三路研究和 `plan.md` |
| G2 | 缺少对具体计划版本的确认闸门 | 主 Agent 展示计划弹窗；确认版本/hash 后才可执行 |
| G3 | 计划、运行 manifest 与用户确认没有强绑定 | manifest 记录 `plan_version`、`plan_hash`、确认人和时间 |
| G4 | 当前单次 SSE 请求承担整个编排生命周期 | 后台运行与 SSE 连接解耦，断线后可续传 |
| G5 | 波内虽并行，但父流程仍围绕整波 fan-out 等待 | 每个 worker 是独立后台任务，完成一个就投递一个事件 |
| G6 | 波内已有 worker_started/finished 事件流，但父流程仍逐波等待整波完成，且结果只统一汇总、无逐条验收 | 按实际完成顺序逐条回流（可复用现有事件队列机制），Manager 对每条即时点评 |
| G7 | Agent 只有平台注册身份，没有稳定人格协议 | 每种 Agent 有稳定的工作人格、表达风格和状态文案 |
| G8 | 后续交叉复核存在，但多波次仍偏静态 | Manager 可基于验收结果招募下一波或定向返工 |
| G9 | `plan.md`、结果文件、聊天消息缺少统一产物索引 | 计划、研究证据、任务产物、质控与最终交付均进入 manifest |

### 2.3 需要纠正的旧路线

不再把“阻塞式 fan-out + 人格化 UI，复刻 80% 观感”视为目标闭环，也不把真异步长期放在
“以后另行立项”。阻塞模式可以作为开发期间的兼容回退，但不能通过最终验收，也不能对用户
宣称已实现异步团队协作。

---

## 3. 角色模型：平台注册 Agent + 本轮人格实例

用户看到的“助手”仍然是平台已经配置的 Agent，不创建脱离权限体系的虚构执行者。人格层采用
两层结构：

1. **稳定角色人格（Agent Persona）**：跟随 `agent_id` 配置，定义工作习惯、判断偏好、表达风格
   和边界；跨会话保持一致。
2. **本轮助手实例（Assistant Instance）**：由稳定人格派生，包含本轮昵称、具体分工、波次、
   状态和临时上下文；同一 Agent 可在不同波次创建多个实例，但权限不变。

### 3.1 人格字段建议

在各 Agent YAML 的 `features.persona` 下增加：

```yaml
features:
  persona:
    archetype: "严谨的质量审计员"
    traits: [心细, 审慎, 坚持证据, 不放过边界条件]
    working_style: "逐项核对输入、阈值、日志和产物；先找反例，再给结论"
    communication_style: "简洁、明确、区分通过/警告/阻断，并给出证据"
    challenge_style: "发现证据不足时直接提出质疑，不为了团队和谐而默认通过"
    status_lines:
      queued: ["正在整理检查清单", "准备逐项核验"]
      running: ["正在核对证据链", "正在检查边界条件"]
      reviewing: ["正在复核结论"]
      succeeded: ["审计完成"]
```

人格字段只影响任务提示词、发言风格与 UI 展示，不得改变工具、权限、配额、审批规则或事实标准。
人格不等于表演：禁止用人格为错误结论辩护，也禁止给助手虚构学历、单位或真人经历。

### 3.2 各类 Agent 的默认人格方向

| Agent | 人格方向 | 典型行为 |
| --- | --- | --- |
| 主 Agent / Manager | 冷静、负责、善于协调 | 控制范围、解释决策、维护计划版本、处理冲突 |
| `agent-general` | 好奇、结构化、善于追问 | 梳理目标、连接跨领域信息、补全数据契约 |
| `agent-data` | 谨慎、有条理、重视可追溯性 | 核验文件、元数据、样本对应和输入完整性 |
| `agent-qc` | 心细严谨、怀疑精神强 | 主动找反例、验证阈值与证据，宁可阻断也不误放行 |
| `agent-delivery` | 条理清晰、耐心、结果导向 | 对齐清单、路径、版本、复现说明和风险披露 |
| `agent-code` | 务实、精确、偏好可复现 | 先读环境再编码，小步验证，完整保留日志 |
| `agent-viz` | 审美敏锐、克制、关注信息表达 | 优先可读性与统计诚实，不用装饰掩盖数据问题 |
| `agent-rnaseq` | 方法严谨、重视实验设计 | 先确认分组和批次，再讨论统计模型与生物学解释 |
| `agent-atacseq` | 系统、注重信号质量 | 紧盯 TSS、FRiP、片段周期性和峰集可比性 |
| `agent-scrna*` | 细致、对异质性敏感 | 区分技术噪声、批次、双细胞与真实生物差异 |
| `agent-mcp-builder` | 工程化、耐心、接口意识强 | 明确 schema、错误语义、兼容性和测试样例 |
| `shania` | 亲和、敏锐、鼓励式 | 保持温度，但不弱化事实、风险和执行边界 |

这些是默认值，后续允许管理员调整；主 Agent 只能为本轮增加 `persona_context`，不得覆盖稳定
人格的安全边界。例如，质控 Agent 可以被指定“重点检查批次效应”，但不能被要求“更宽松地通过”。

### 3.3 本轮助手实例契约

```json
{
  "assistant_instance_id": "asst:<run_id>:<wave_id>:<index>",
  "agent_id": "agent-qc",
  "display_name": "衡准",
  "persona_version": "agent-qc@1",
  "persona_context": "本轮重点审计批次效应与交付文件完整性",
  "task_id": "qc-final",
  "wave_id": "wave-2",
  "status": "recruited|queued|running|reviewing|succeeded|failed|awaiting_input",
  "task_summary": "独立复核分析证据与产物",
  "created_at": "...",
  "finished_at": null
}
```

昵称可由系统从受控名称池生成，或直接显示 Agent 名称；同一 run 内必须唯一并稳定，刷新页面后
不能变化。状态文案从 Persona 配置中确定性选择，避免每次刷新随机变化。

---

## 4. 完整工作流

### 阶段 A：任务接收、方向识别与规划 Agent 选择

主 Agent 首先判断：任务是否需要正式执行或多 Agent 协作。如果需要，则只选择完成计划所需的
最小规划集合：

- 单领域任务：选择最匹配的领域 Agent 作为 `lead_planner`；
- 跨领域任务：一个领域 Agent 担任 `lead_planner`，必要时增加最多两个只读规划顾问；
- 目标或数据模态不明确：先由 `agent-general` 完成 intake，使用 `ask_request` 补齐真正影响
  路线的信息；
- 不能为了显示“团队感”而固定套用通用、代码、可视化、质控四件套。

选择先看 `capability_scope`、输入/输出契约、工具可用性和任务方向，再附加人格；不得反过来因为
某个人格“看起来合适”而选择能力不匹配的 Agent。

### 阶段 B：三路研究与证据合并

规划 Agent 必须同时覆盖三类信息源：

1. **平台知识库**：调用 `knowledge_search`，优先查团队已经审核或沉淀的方法、SOP 与经验。
2. **网络搜索**：调用 `web_search`，补充最新论文、指南、软件版本和知识库未覆盖部分。
3. **模型通用知识**：不把它伪装成一个搜索工具；它仅用于生成候选框架、解释概念、发现还需
   检索的问题和综合前两路证据。凡无法由检索证据支持的内容，必须标为“通用知识/待验证推断”。

知识库检索与网络检索应由研究调度器并发发起；模型综合在两路结果返回后进行。若某一路不可用，
计划仍可生成，但必须在证据账本和“限制”中记录失败，不得伪造已搜索。

研究结果统一为 `EvidenceItem`：

```json
{
  "evidence_id": "ev-001",
  "source_type": "knowledge_base|web|model_knowledge",
  "title": "...",
  "locator": "kb://... 或 https://...；模型知识留空",
  "retrieved_at": "...",
  "freshness": "current|possibly_stale|not_applicable",
  "claim": "这条证据支持什么",
  "confidence": "high|medium|low",
  "used_in_plan_sections": ["4.2", "6"]
}
```

### 阶段 C：创建并交付 `plan.md`

`lead_planner` 根据三路研究创建 `plan.md`，然后发送 `plan_ready` 内部事件给主 Agent。建议路径：

```text
output/overdrive/<session_id>/<run_id>/plan.md
```

主 Agent 不直接照单执行，必须先完成一次管理审查：检查目标是否覆盖、依赖是否正确、串并行是否
合理、Agent 能力是否匹配、风险和验收标准是否清楚、证据是否可追溯。审查失败则退回规划 Agent
修订；审查通过后冻结版本。

`plan.md` 必须包含以下章节：

```markdown
# 执行计划

## 1. 用户目标与最终交付物
## 2. 已确认输入
## 3. 假设、限制与待确认事项
## 4. 研究与证据摘要
### 4.1 平台知识库
### 4.2 网络资料
### 4.3 模型通用知识与待验证推断
## 5. 主 Agent 串行前置工作
## 6. Agent 选择与理由
## 7. 执行 DAG 与波次
## 8. 每个任务的输入、输出、工具、超时与重试
## 9. 风险、审批点与停止条件
## 10. 质量门与验收标准
## 11. 交付目录
## 12. 计划版本与变更记录
```

计划不是泛泛的待办列表。每个执行任务至少需要 `task_id`、`agent_id`、`depends_on`、输入、输出、
完成判据、超时、重试和是否需要审批；波次由依赖关系计算，不由文本顺序猜测。

### 阶段 D：主 Agent 弹窗请求确认

主 Agent 通过现有 `ask_request` 事件发送 `kind: "plan_confirmation"`，前端用
`PlanConfirmationCard`（可复用 `AskUserCard` 容器）展示：

- 计划标题、摘要、预计波次数、预计参与 Agent；
- 串行前置工作、主要风险、审批点与最终交付物；
- `plan.md` 预览/打开入口；
- 三个动作：**确认并执行**、**提出修改**、**取消任务**。

确认事件必须携带：

```json
{
  "kind": "plan_confirmation",
  "run_id": "...",
  "plan_path": ".../plan.md",
  "plan_version": 1,
  "plan_hash": "sha256:...",
  "actions": ["approve", "revise", "cancel"]
}
```

- `approve`：记录确认人、时间、版本和 hash，进入串行前置阶段；
- `revise`：将用户意见交回规划 Agent，生成新版本，再次由主 Agent 审核并弹窗确认；
- `cancel`：终止 run，保留 `plan.md` 和研究记录，不启动任何执行任务。

`revise` 循环必须有上限（默认 3 轮，可在 `_overdrive_limits.yaml` 配置）。达到上限后主 Agent
明确告知用户当前分歧点，请用户选择确认当前版本或取消，禁止规划 Agent 与用户之间无限往返。

用户确认的是一个不可变快照。确认后若发生会改变目标、输入、成本/耗时等级、Agent 权限、关键参数、
质量门或交付物的实质变更，必须生成新版本并重新确认。仅重试、文案修正和不改变语义的调度优化可
记录到变更日志后继续。

### 阶段 E：主 Agent 独立完成串行前置工作

计划确认后，主 Agent 先独立完成无法安全并行的前置项，例如：

- 读取并核验用户上传文件、目录、格式、列名、样本分组和路径；
- 加载本任务必需的 `SKILL.md`、领域约束与工具说明；
- 固化数据契约、输出目录和共享上下文；
- 检查运行环境、配额和依赖；需要写操作或高风险工具时走现有审批卡；
- 创建共享 artifact 索引和每个下游任务的最小上下文包。

此阶段的输出是可验证的 `preflight_result`。只有所有硬前置通过，才可招募执行助手。失败时主 Agent
应说明具体阻塞，必要时向用户提问；不得让助手在缺少输入时各自猜测。

### 阶段 F：按能力招募人格化助手

主 Agent 从已确认计划的下一波 ready tasks 中招募助手，为每个实例绑定：Agent、稳定 Persona、
本轮昵称、任务、输入引用、输出契约、完成标准、超时与重试策略。

前端显示“助手招募”卡片：头像、昵称、平台角色、人格短句、具体任务和当前状态。招聘卡是运行状态
的投影，不是静态装饰；刷新后必须从 manifest 恢复。

默认并行上限由系统资源和模型配额控制，不以截图中的人数为固定目标。相互依赖或会写同一文件的
任务不得放在同一波；共享写目录时必须分配独占路径，最终由主 Agent 合并。

### 阶段 G：主 Agent 与助手真异步并行

招募后，每个助手作为独立后台 job 提交。提交接口立即返回 `assistant_instance_id` 和 `job_id`，
不能在当前聊天生成器中 `await asyncio.gather(...)` 直到整波完成。

与此同时，主 Agent 执行计划中标记为 `manager_tasks` 的工作，例如整理用户材料、维护证据账本、
准备整合框架或处理不依赖助手结果的部分。主 Agent 没有可做工作时可以进入等待状态，但等待是
显式状态，不是阻塞整个会话连接。

真异步必须满足：

- worker 生命周期不依赖一次 SSE 连接；
- 用户刷新或临时断线后任务继续，重连可按事件游标补发；
- 用户可继续查看进度；是否允许同一会话追加新指令由 run 状态机串行仲裁；
- pause / resume / terminate 会持久化，并由后台 worker 在安全点读取；
- 同一任务事件使用单调递增序号，保证消息落库与 UI 顺序可重建。

### 阶段 H：逐个回流与主 Agent 点评

助手完成后立即写入 artifact、更新 manifest，并发出 `assistant_result_ready`。事件按**完成顺序**
进入房间，而不是等整波结束后按 assignment 下标批量展示。

每个回流包含：

- “助手消息｜来自 {display_name}”；
- 任务结论和摘要；
- 产物路径、来源与执行日志；
- 自检结果、置信度、限制和未完成项；
- 状态：成功、失败、等待用户输入或等待审批。

主 Agent 对每条结果单独产生一条短点评，至少做以下判断：

1. 是否满足该任务完成判据；
2. 证据和产物是否真实可用；
3. 与已回流结果是否冲突；
4. 接受、要求原助手返工、招募复核助手，或暂停问用户。

点评不能只有“质量很高”之类礼貌性文案，应指出接受依据或具体缺口。点评结果写入 manifest 的
`manager_reviews[]`，成为后续波次的调度依据。

### 阶段 I：动态多波次编排

当一条结果通过点评后，状态机重新计算 ready tasks；不需要等同波其他任务全部完成，就可以启动
只依赖该结果且资源不冲突的下游任务。为了 UI 可理解性，仍用 `wave_id` 展示逻辑波次，但调度内核
采用事件驱动 DAG。

典型波次：

```text
研究规划波（确认前，只读）
  → 主 Agent 串行前置
  → 第一执行波：多个领域分析 / 资料整理并行
  → 第二波：代码实现、可视化或针对性补证
  → 第三波：独立质控与交叉复核
  → 第四波：交付报告与产物清单
```

后续波次可重用已有 Agent，也可招募新 Agent。任何新任务都必须能追溯到已确认 plan 的任务或
允许的非实质变更；超出计划范围则先修订计划并重新向用户确认。

### 阶段 J：统一交付

全部必需任务完成并通过质量门后，主 Agent 统一交付：

- 回答用户最初目标的综合结论，而不是简单拼接各助手消息；
- `plan.md` 最终版本及变更记录；
- 知识库/网络/模型知识的证据账本；
- 实际产物、脚本、日志、图表、质控结论和失败项；
- 每项产物的生成 Agent、版本、路径和复现说明；
- 假设、限制、未完成事项和建议下一步。

前端“全部文件”面板从 manifest 的 artifact index 渲染，支持预览和下载。只有通过质量门且路径
真实存在的文件才进入正式交付区；草稿和失败产物进入“过程文件”。

---

## 5. 运行状态机

建议将一次超频任务建模为持久化 `OverdriveRun`：

```text
RECEIVED
  → INTAKE_REQUIRED → RECEIVED
  → RESEARCHING
  → PLAN_DRAFTED
  → PLAN_REVIEWING
  → AWAITING_PLAN_CONFIRMATION
      ├─ revise → RESEARCHING / PLAN_DRAFTED
      ├─ cancel → CANCELLED
      └─ approve → SERIAL_PREFLIGHT
  → RECRUITING
  → RUNNING
      ↔ WAITING_FOR_RESULTS
      ↔ AWAITING_USER_INPUT
      ↔ AWAITING_APPROVAL
      ↔ PAUSED
      → REPLANNING（实质变更后回到 AWAITING_PLAN_CONFIRMATION）
  → QUALITY_REVIEW
      ├─ repair → RECRUITING / RUNNING
      └─ pass → DELIVERING
  → COMPLETED

任意运行态 → TERMINATING → TERMINATED
不可恢复错误 → FAILED
```

关键不变量：

- 没有 `approved_plan_hash`，不能进入 `SERIAL_PREFLIGHT` 之后的状态；
- `assistant_instance` 只能引用已确认计划中的 task，或已记录的非实质修订；
- `COMPLETED` 前所有 required tasks 必须成功或有用户明确豁免，质量门必须通过；
- `CANCELLED`、`TERMINATED`、`FAILED` 不得被最终文案包装为成功；
- 状态转换、用户确认、Manager 点评和工具审批均写入审计事件。

---

## 6. 核心数据与文件契约

### 6.1 目录建议

```text
output/overdrive/<session_id>/<run_id>/
├── plan.md
├── plan.v1.md
├── evidence.json
├── manifest.json
├── events.jsonl
├── control.json
├── preflight/
├── tasks/<task_id>/
│   ├── result.md
│   ├── summary.md
│   ├── progress.log
│   └── artifacts.json
├── reviews/
└── delivery/
```

`plan.md` 始终指向当前版本；每次确认过的版本另存 `plan.vN.md`，禁止原地覆盖已确认快照。
`plan_hash` 对 UTF-8 规范化（换行统一为 LF、去除末尾空白）后的文件字节计算 sha256，避免格式化
抖动导致确认意外失效。

### 6.2 manifest v2 必要字段

```json
{
  "version": 2,
  "run_id": "...",
  "session_id": "...",
  "status": "AWAITING_PLAN_CONFIRMATION",
  "root_request": "...",
  "lead_planner_agent_id": "agent-rnaseq",
  "research": {
    "knowledge_base": {"status": "succeeded", "evidence_ids": ["ev-001"]},
    "web": {"status": "succeeded", "evidence_ids": ["ev-002"]},
    "model_knowledge": {"status": "completed", "evidence_ids": ["ev-003"]}
  },
  "plan": {
    "path": ".../plan.md",
    "version": 1,
    "hash": "sha256:...",
    "status": "awaiting_confirmation",
    "approved_by": null,
    "approved_at": null
  },
  "manager_tasks": [],
  "tasks": [],
  "assistant_instances": [],
  "manager_reviews": [],
  "artifact_index": [],
  "event_cursor": 0
}
```

### 6.3 统一事件投影

继续复用现有前端认识的 SSE 类型，领域事件先持久化，再投影：

| 领域事件 | SSE 投影 | UI |
| --- | --- | --- |
| `research_started/completed` | `overdrive_progress` | 三路研究进度 |
| `plan_ready` | `room_speech` + `overdrive_progress` | 规划 Agent 交付计划 |
| `plan_confirmation_requested` | `ask_request(kind=plan_confirmation)` | 计划确认弹窗 |
| `assistant_recruited/started` | `overdrive_progress` | 招募花名册与泳道 |
| `assistant_result_ready` | `room_speech` | 单助手回流气泡 |
| `manager_review_ready` | `room_speech` | 主 Agent 点评 |
| `tool_approval_requested` | `overdrive_approval_request` | 高风险操作审批 |
| `run_completed/failed` | `overdrive_progress` + `room_speech` | 最终状态与交付 |

不要把计划确认和高风险工具审批混为一件事：前者确认“执行什么”，后者批准“某个具体危险动作”。

---

## 7. 后端改造建议

### 7.1 从巨型 turn 函数拆出职责

当前 `_run_overdrive_turn()` 同时承担 intake、规划、波次计算、worker 执行、消息持久化、审批和
总结。建议拆为：

- `OverdrivePlanningService`：选择规划 Agent、三路研究、生成/修订 `plan.md`；
- `OverdrivePlanValidator`：校验能力、DAG、输入输出契约、风险、质量门与路径；
- `OverdriveRunService`：创建 run、计划冻结、用户确认与状态转换；
- `OverdriveScheduler`：事件驱动计算 ready tasks、资源冲突和波次；
- `AssistantJobService`：提交/暂停/恢复/终止独立 worker job；
- `OverdriveEventStore`：持久化递增事件并支持 cursor 重放；
- `OverdriveRoomProjector`：把领域事件映射成现有 SSE chunk；
- `ManagerReviewService`：逐条验收回流结果并做返工/复核决策；
- `DeliveryAssembler`：统一产物索引、质量结果和最终报告。

`OverdriveManifest` 可升级为这些服务的文件投影，但并发写时不能继续依赖无锁的“整文件读改写”。
数据库或 Redis 中保存权威状态与事件序号，文件 manifest 作为可读快照；至少要使用 run 级锁和
原子 compare-and-set，避免多个 worker 覆盖状态。

### 7.2 真异步任务模型

推荐优先复用现有 Celery/Redis 基础设施承载长生命周期 worker；短任务也可进入同一 job 协议，
避免进程内 task 在 web 重启后丢失。每个 job 只负责一个 `task_id + attempt`：

```text
submit(task snapshot) → job_id
worker_started → append event
worker_progress → append event
worker_result persisted → assistant_result_ready
or worker_failed / awaiting_input / awaiting_approval
```

主 Agent 不需要一直占用一个 LLM 流。`assistant_result_ready` 到达后，由编排 worker 触发一次短的
Manager review turn，持久化点评，再决定下一任务。这样“逐个回流 + 点评”可跨断线、跨进程恢复。

点评必须有成本策略，不能每条结果都无差别消耗一次完整 LLM 调用：

- 规则快速通道：任务成功、完成判据全部命中、产物路径校验通过且无冲突时，可用模板化点评直接
  接受，并标注 `review_mode: rule`；
- LLM 点评：仅在失败、判据未命中、与其他结果冲突、产物可疑或计划要求交叉复核时触发；
- 每条点评的 token 与延迟预算写入 `_overdrive_limits.yaml`，超限降级为规则点评并在审计中记录。

### 7.3 规划阶段的三路并发

增加内部 `ResearchBundleService`，并发执行 `knowledge_search` 与 `web_search`，然后把结果和明确
标注的模型通用知识交给 `lead_planner`。这里的并发是研究 IO 并发，不允许把模型知识伪造成搜索
结果。必须保存原始检索结果的最小审计信息和失败状态。

研究阶段的每路超时、最大证据条数、总墙钟预算纳入 `_overdrive_limits.yaml` 统一管理；单路超时
不阻塞计划生成，按“降级并记录”处理，防止一路搜索挂起拖住整个确认弹窗。

### 7.4 Agent 选择与人格注入

- Agent catalog 在现有能力画像上增加 `persona_version` 与 persona 摘要；
- Manager 输出 `agent_id` 与选择理由，不直接自由生成权限；
- 后端根据 `agent_id` 解析稳定 Persona，再创建助手实例和昵称；
- 子任务提示词由“稳定 Agent 系统提示词 + Persona + 本轮任务契约 + 最小共享上下文”组成；
- Persona 只在服务端可信配置中读取，用户文本不得直接覆盖。

### 7.5 恢复、幂等与并发控制

- 所有 command 带 `run_id`、`command_id`，重复提交必须幂等；
- worker result 使用 `(run_id, task_id, attempt)` 唯一键；
- 事件使用 `(run_id, sequence)` 唯一键；
- 重连接口支持 `after_sequence`，前端补发遗漏事件；
- 终止只在安全点生效，已产生的产物保留但标为过程文件；
- 会话中新用户消息若属于当前 run 的确认/审批/补充则路由到该 run，否则由主 Agent提示先暂停、
  终止当前 run 或创建新 run，禁止两个 run 并发写同一工作目录。

---

## 8. 前端改造建议

1. **研究进度卡**：分别展示知识库、网络和模型综合状态；某一路失败时明确降级。
2. **规划 Agent 消息**：显示“计划已交给主 Agent 审核”，附 `plan.md` 路径和证据数量。
3. **`PlanConfirmationCard`**：计划摘要、风险、Agent、波次、交付物、预览入口，以及确认/修改/取消。
4. **人格化招募卡**：稳定昵称、头像、平台角色、人格短句、任务和真实状态。
5. **逐条消息回流**：按事件序列追加，不在 aggregated 时一次性补齐；回流消息下紧跟 Manager 点评。
6. **波次时间线**：区分规划、前置、执行、复核和交付波；允许后续动态增加。
7. **全部文件面板**：按正式交付、过程文件、失败产物分类，显示来源 Agent 和质控状态。
8. **重连恢复**：页面从 run snapshot + event cursor 重建，不能依赖内存中的当前消息对象。

状态文案应自然但克制，例如“衡准正在核对证据链”；不要使用与失败、审批或等待状态不符的随机
玩笑。人格体验来自稳定工作方式和表达，而不仅是名字与头像。

---

## 9. 分阶段施工顺序

每一阶段都服务于最终真异步闭环；不得把阶段性 UI 模拟标记为最终完成。

### P0：契约与迁移地基

- 定义 `OverdriveRun`、manifest v2、计划版本/hash、事件序号和 Assistant Instance schema；
- 为 Agent YAML 增加 `features.persona`，先覆盖 Manager、general、data、qc、code、viz、delivery；
- 为旧 manifest 提供只读兼容或 v1 → v2 迁移；
- **明确双引擎收敛路径**：当前部分 Agent（如 `agent-qc`）声明 `engine: langgraph`，P0 必须先
  决策——新的 `OverdriveRunService` 是作为唯一权威编排器包装两种引擎，还是仅替换 chat 循环。
  未决策前不得进入 P2，避免异步编排在两条路径上各写一份；
- **明确权威状态存储**：在数据库表（`overdrive_runs` / `overdrive_events`，走 alembic 迁移）与
  Redis 之间选定事件序号与 run 状态的权威来源，文件 manifest 只作可读快照。

### P1：研究 → `plan.md` → 用户确认闭环

- 实现规划 Agent 选择、三路研究、证据账本和计划校验；
- 写入版本化 `plan.md`；
- 实现 `ask_request(kind=plan_confirmation)` 与前端确认卡；
- 后端状态机硬性阻止未确认执行。

### P2：串行前置与持久化异步运行时

- 抽出 preflight；
- 将 worker 改为独立、可恢复 job；
- 实现事件存储、cursor 补发、pause/resume/terminate 与幂等。

### P3：人格化招募、逐条回流与 Manager 点评

- 创建 Assistant Instance 和花名册；
- worker 单个完成即落库并投影 `room_speech`；
- 事件触发 Manager review，支持接受、返工、复核和问用户。

### P4：动态多波次、质量门与统一交付

- 事件驱动 DAG 解锁下游任务；
- 接入独立 QC 和修复波；
- 构建 artifact index、全部文件面板和最终交付报告；
- 完成断线、重启、失败、取消与审批的端到端验证。

建议用新 feature flag 小流量启用，但同一个 run 不能在 v1/v2 编排器之间中途切换。兼容回退必须
在 UI 明示“同步兼容模式”，且不计入真异步验收。

---

## 10. 测试与验收标准

### 10.1 单元与契约测试

- 任务方向能选择最小且能力匹配的规划 Agent；
- 知识库和网络研究并发执行，失败时证据状态准确；
- 模型知识不会被标成 KB 或 Web 来源；
- `plan.md` 缺章节、DAG 循环、未知 Agent、缺输出契约时校验失败；
- plan hash 与文件内容一致，已确认版本不可覆盖；
- 未确认计划无法提交 worker；修改实质字段会使原确认失效；
- revise 达到上限后不再生成新版本，用户只能确认或取消；
- 规则快速通道点评不触发 LLM 调用，且产物校验失败时自动升级为 LLM 点评；
- Persona 注入不改变工具白名单和审批策略；
- task、command、result 和 event 均满足幂等与单调序号。

### 10.2 集成测试

- 用户任务 → 三路研究 → `plan.md` → 确认卡；确认前无执行工具调用；
- 点击“修改”后生成 v2，再次确认；点击“取消”后无 worker job；
- 确认后先完成 preflight，再出现招募卡；
- 两个助手运行时主 Agent 同时完成自己的 manager task；
- 快助手先回流并获得点评，不等待慢助手；
- 单条结果解锁下游任务，形成第二波；
- worker 触发 ask_user / 工具审批时只暂停受影响分支；
- web 服务重启和 SSE 断线后，任务不丢且消息按序恢复；
- 终止后不再招募新助手，已产物标为过程文件。

### 10.3 端到端用户验收场景

用一个“读取真实文件 + 多维研究 + 代码分析 + 可视化 + QC + 报告”的复合任务验证，页面顺序必须是：

```text
主 Agent 接单并说明规划角色
→ 三路研究进度
→ 规划 Agent 交付 plan.md
→ 主 Agent 计划确认弹窗
→ 用户确认
→ 主 Agent 串行前置与真实核验结果
→ 人格化助手招募
→ 主 Agent 与助手同时工作
→ 助手 A 回流 → 主 Agent 具体点评
→ 助手 B 回流 → 主 Agent 具体点评
→ 根据结果动态出现下一波
→ 独立质控
→ 统一交付 + 全部文件
```

另外必须验证：计划修改、计划取消、一路搜索失败、单 worker 失败重试、等待用户输入、高风险审批、
断线重连、web 进程重启、用户终止和部分成功。仅“看起来像多人聊天”不能通过验收。

### 10.4 完成定义（Definition of Done）

只有同时满足以下条件，才可宣布本轮超频升级完成：

- 复杂任务的已确认 `plan.md` 可在工作区看到，并可追溯三类信息源；
- 后端有不可绕过的计划确认状态闸门；
- 主 Agent 串行前置发生在执行助手招募之前；
- 助手 job 与 SSE 生命周期解耦，主 Agent 能与助手真实并行；
- 助手结果逐个回流且每条都有主 Agent 的验收点评；
- 后续波次由结果动态触发；
- 不同 Agent 展现稳定、定制但不越权的人格；
- 刷新、断线和服务重启后可恢复；
- 最终交付包含真实产物、证据、质控、失败与限制；
- 自动化测试和上述端到端场景全部通过。

### 10.5 部署服务器验收补充：基础设施、独立 QC 与 Broker 故障

本节是部署服务器上的可执行验收清单。所有停止服务、断网和配置禁用操作必须在
staging 或维护窗口执行，不得直接对生产 run 做破坏性测试。每个场景都要保存命令输出、
对应 `run_id`、事件游标和容器日志；没有证据只能标记为“未验收”。

#### A. PostgreSQL、Redis、Celery 与迁移

在仓库根目录执行，并确保当前 shell 已加载部署 `.env` 中的变量（如果使用独立 worker
栈，先按部署文档加载 `data/worker_config.yaml`）：

```bash
docker compose -f deploy/docker/docker-compose.yml ps db cache web beat
docker compose -f deploy/docker/docker-compose.yml exec db \
  pg_isready -U "${POSTGRES_USER:-cygnusx}" -d "${POSTGRES_DB:-cygnusx}"
docker compose -f deploy/docker/docker-compose.yml exec cache \
  redis-cli -a "${REDIS_PASSWORD}" ping
./scripts/worker-compose.sh ps
docker compose -f deploy/docker/docker-compose.worker.yml exec worker \
  celery -A cygnusx.infrastructure.celery_app.celery inspect ping
docker compose -f deploy/docker/docker-compose.worker.yml exec worker \
  celery -A cygnusx.infrastructure.celery_app.celery inspect registered \
  | grep -E 'overdrive\.(advance_run|replan_run|run_assistant_job|run_manager_review_job)'
docker compose -f deploy/docker/docker-compose.yml exec web alembic current
```

通过标准：db/cache 健康，`pg_isready` 返回 accepting connections，Redis 返回 `PONG`，
至少一个 Celery worker 返回 pong 并注册上述四个 Overdrive 任务，迁移当前版本为
`q1r2s3t4u5v6`（或包含该 revision 的 head）。随后用真实 API 创建一个最小 run，确认
`overdrive_runs`、`overdrive_events` 和 `overdrive_commands` 均有持久化记录；重启 web
容器后用 active-run/events 接口按游标恢复同一个 run。

#### B. 真实 QC Agent 与“不可用”分支

先验证默认部署确实加载 `agent-qc`，并在冻结的 `plan.vN.md`/`manifest.json` 中看到：

```text
task_id = independent-qc
agent_id = agent-qc
depends_on = 所有上游任务
```

使用真实文件任务跑到 QC，检查 `assistant_result_ready` 和 `manager_review_ready` 事件。
QC 结果末尾必须严格出现以下三种之一：

```text
质量结论：通过
质量结论：返工
质量结论：人工复核
```

只有“通过”可以进入 `DELIVERING/COMPLETED`；“返工”或“人工复核”必须阻断正式交付，
并留下 Manager review、返工或人工介入证据。

再在 staging 中临时禁用 `agent-qc` 或让其不可用，重新生成计划并记录实际产品策略：
当前实现会在计划摘要中明确“独立 QC 降级”，不会伪造 QC 任务。若产品要求 QC 是硬门，
该场景必须判定为失败并将策略改为“没有 `agent-qc` 时禁止冻结/执行计划”；不能把降级
场景误报为独立 QC 已验收。

#### C. Celery Broker 不可用时的自动重规划

在 staging 创建计划，点击“修改”使 run 进入 `REPLANNING`，确认数据库和事件中出现：

```text
plan_revision_requested
replanning_started（或等待调度的等价记录）
```

在重规划任务尚未消费时短暂停止 Redis 或隔离 worker，观察以下 SQL（只读）：

```sql
SELECT run_id, status, control, event_cursor, updated_at
FROM overdrive_runs
WHERE run_id = '<RUN_ID>';
```

通过标准是 Broker 恢复后，重规划任务能够被重新投递或由补偿任务接管，最终产生新的
`plan_confirmation_requested`（版本递增、hash 改变），且 `control.replan_lock` 被清理。
如果 run 在 Broker 恢复后仍永久停留 `REPLANNING`，或没有 `replanning_failed`/补偿记录，
则该场景未通过；保存以下证据后再修复调度可靠性：

```bash
docker compose -f deploy/docker/docker-compose.yml logs --since=10m cache
./scripts/worker-compose.sh logs --since=10m worker
docker compose -f deploy/docker/docker-compose.yml exec db \
  psql -U "${POSTGRES_USER:-cygnusx}" -d "${POSTGRES_DB:-cygnusx}" \
  -c "SELECT run_id,status,control,event_cursor,updated_at FROM overdrive_runs WHERE run_id='<RUN_ID>';"
```

该场景在补偿重试和明确失败收敛实现前，不得标记为“自动重规划已完成”。

为避免服务器验收退化成无法追溯的手工口头检查，仓库提供统一的证据采集器。它默认只读地检查
基础设施、任务注册、迁移、指定 run 的持久化事件和独立 QC；运行成功后会写入包含命令输出、退出码
和 run 元数据的 `acceptance.json`。示例：

```bash
python3 scripts/verify_overdrive_deployment.py --run-id '<RUN_ID>'
```

Broker 故障演练必须由已经处于 `REPLANNING` 的 staging run 发起。该模式会短暂停止共享 `cache`
服务，因而需要双重显式确认；无论演练结果如何，脚本都会在 `finally` 中尝试启动 Redis 并保存证据：

```bash
python3 scripts/verify_overdrive_deployment.py \
  --run-id '<QC_RUN_ID>' \
  --broker-run-id '<REPLANNING_RUN_ID>' \
  --environment staging \
  --exercise-broker-recovery \
  --confirm-broker-outage
```

若已另外执行 `agent-qc` 不可用演练，可将该 run 通过 `--qc-unavailable-run-id '<RUN_ID>'` 一并传入，
脚本会要求其计划摘要明确记录 `independent_qc.mode = degraded`，且不得存在伪造的 QC 任务。

如果重规划没有生成新的计划确认事件、没有清理 `replan_lock`，或收敛为 `replanning_failed`，脚本返回
非零状态并将该 run 标记为未通过；不得将“Redis 已重新启动”误判为自动重规划验收通过。

---

## 11. 需求追踪表

| 用户期望 | 本文落点 | 验收证据 |
| --- | --- | --- |
| 按任务方向选择合适 Agent | §4 阶段 A、§7.4 | Agent 选择契约测试 + run 中的选择理由 |
| 同时查知识库、网络和模型知识 | §4 阶段 B、§7.3 | `evidence.json` 三类记录与研究进度事件 |
| 创建 `plan.md` 并交给主 Agent | §4 阶段 C | 版本化文件 + `plan_ready` + Manager 审查记录 |
| 弹窗确认是否执行计划 | §4 阶段 D、§8 | `PlanConfirmationCard` + plan hash 确认记录 |
| 主 Agent 先完成串行前置 | §4 阶段 E | preflight artifact 早于任何执行 worker started |
| 招募助手 | §4 阶段 F | Assistant Instance 与可恢复花名册 |
| 真异步并行 | §4 阶段 G、§7.2 | 主/助手时间线重叠，断线后 job 继续 |
| 助手逐个回流 + 主 Agent 点评 | §4 阶段 H | 完成顺序事件 + `manager_reviews[]` |
| 多波次编排 | §4 阶段 I | 结果驱动的新 wave/task 事件 |
| 统一交付 | §4 阶段 J | delivery manifest 与全部文件面板 |
| 不同 Agent 定制人格 | §3 | Persona YAML、实例快照与前端发言 |

---

## 12. 实施约束

1. **权限边界不变**：人格和昵称不产生新权限；所有工具仍受 Agent 配置、sandbox、审批和配额约束。
2. **证据诚实**：只记录真实调用过的知识库/网络搜索；模型通用知识必须单独标记。
3. **一套前台**：继续使用超频房间的群聊、进度、询问和审批组件，不为每个后端创建独立入口。
4. **计划确认不可伪造**：Manager 自己不能替用户写 `approved_by`；确认必须来自真实用户事件。
5. **计划与审批分离**：确认计划不等于批准后续所有危险工具，高风险动作仍逐项审批。
6. **最小上下文**：助手只获取完成任务所需的上下文和 artifact 引用，避免整段会话无界复制。
7. **真实产物**：没有文件、日志或工具结果就不得声称已分析完成；失败和跳过必须进入最终报告。
8. **双路径收敛**：若 legacy/LangGraph 仍并存，计划确认与事件语义必须一致；最终应由统一运行服务
   承担状态，而不是在两条聊天循环中复制一套异步编排。
9. **配置化人格**：人格由 Agent YAML 管理并带版本，不能把所有角色的性格硬编码在前端。
10. **文档同步**：代码落地后更新 `data/ai/README.md` 的架构与进度，避免蓝图和实现状态混淆。
11. **执行者始终是平台真实 Agent**：无论是比赛期的 AgentTeams 编排还是本文的超频 v2，被调度的
    专家都必须是 `data/ai/*.yaml` 定义、经 `AgentService.assemble_context()` 装载的真实 Agent，
    携带其自身的提示词/Persona/工具/MCP/Skill/权限；不得在编排层另造一套只有名字没有能力的虚构角色。

### 12.1 与 AgentTeams（比赛阶段）的关系与迁移

- **比赛阶段**：按 `data/ai/AgentTeams_update.md`，以 AgentTeams Bridge/Case 状态机作为协同基点，
  通过补建 CygnusX consultation 端点让平台真实 Agent 作为 Worker 执行者，在单窗口内完成闭环。
  此阶段编排状态在外部 Bridge，执行能力在 CygnusX。
- **赛后收敛到本文**：编排/状态权威从外部 Bridge 迁回平台内置的超频 v2
  （`overdrive_run_service` DB 事件溯源 + Celery `run_assistant_job` 真异步 +
  `ParallelSubAgentService` 执行内核）。届时不再需要为每个专家常驻外部 Worker 容器，
  也不受 Gateway 只读策略限制——专家可在确认闸门内使用完整工具/沙箱能力。
- **迁移时保持不变的资产**：①"平台真实 Agent 即执行者"原则；②单窗口 `room_speech` 投影心智；
  ③研究先行→计划确认→串行前置→异步执行→逐条点评→质控交付的阶段语义；④只读研究 vs 审批后执行
  的边界。AgentTeams 阶段沉淀的角色映射表、`context_refs/evidence_refs` 传递约定可直接复用到
  v2 的任务契约。

本文档之后的代码优化应以 §10.4 的完成定义为终点；任何仅实现同步 fan-out、批量汇总或随机昵称
的方案都只是过渡态，不等同于本目标完成。
