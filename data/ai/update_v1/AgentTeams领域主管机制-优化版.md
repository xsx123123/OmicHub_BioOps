# AgentTeams 领域主管机制（Domain Manager）：单细胞三兄弟协调范式的泛化

> 版本：1.1
> 日期：2026-08-11
> 性质：对 `AgentTeams愿景目标文档-优化版.md`（v1.1）的增补章节，作为后续施工与代码改动的权威依据
> 配套关系：
> - 增补 `AgentTeams愿景目标文档-优化版.md` §4.2（Manager 定义）与 §5.2（群聊阶段）
> - 增补 `AgentTeams收敛实施计划-优化版.md` §4.1（角色映射单一来源）与 Phase 2/3
> - 当本文与上述两份文档冲突时，**在本文涉及范围内以本文为准**
>
> 本文替代以下口头/讨论形态的约定，成为唯一权威：
> - 任何"单细胞场景让 scrna 当 Manager"的非正式约定
> - 任何"领域 Agent 当 Manager"未明确边界的讨论
>
> v1.1 修订要点：
> 1. 明确三个硬边界（不接工单 / 不自判归口 / QC 独立），任一缺失即视为越权
> 2. 把"单细胞主管"泛化为可复用的 **领域主管（Domain Manager）** 范式，避免成为单细胞特例补丁
> 3. 规定分阶段落地路径：**先 lead planner 模式（零改动）→ 再 `can_act_as_domain_manager_for` 资源切换**
> 4. 规定 registry / Bridge / Projector 三处一致性改造点
> 5. 规定契约测试与验收门槛

---

## 实施状态（2026-08-11）

**当前结论：本文定义的是核心收敛完成后的独立增量机制，本轮交付未将 Domain Manager 模式标记为已上线。** 当前平台页面测试应先覆盖收敛计划与愿景文档中的通用 Manager 闭环；只有在决定开启本机制后，才按本文分阶段实施并逐项验收。

- 已具备的前置条件：角色 registry、Bridge/Gateway/Projector 的基础编排链路、独立 QC、审批与审计闭环已随核心收敛交付落地。
- 尚未作为本轮验收结论：`can_act_as_domain_manager_for` 声明、Domain Manager 指派/屏蔽、自派工单拒绝事件，以及 Phase 2/3 的页面与契约验收。
- 后续启用时必须从 §4.1 的 lead planner 模式开始，完成 §6.1 验收后再逐步放量；不得跳过独立 QC、router 指派或回退开关。

---

## 1. 背景：为什么需要领域主管

### 1.1 问题

单细胞在 OmicHub 被合理地切成三个专家：

| 专家 | 阶段 | 主要产物 |
| --- | --- | --- |
| `agent-scrna-upstream` | FASTQ / Cell Ranger / 上游 QC | 10x 矩阵 / h5ad |
| `agent-scrna-integration` | 整合 / 聚类 / 批次校正 | integrated object |
| `agent-scrna-advanced` | 注释 / 轨迹 / 通讯 | annotated object、marker、轨迹图 |

跨三者的状态流转（上游 → 整合 → 高级）目前只能靠 Work Item 的 `depends_on` DAG 串行表达。若让 `agent-general` 当 Manager，每次同域协调都要 "general 听不懂再问 scrna" 的往返，增加无效跳数与口径漂移。

### 1.2 设计目标

允许领域专家在自己**本域**的复合任务里担任 Manager，统一调度同域兄弟专家；同时用三个硬边界 + 一个可复用的 registry 标记，把这种"升任"限制在可控范围内，避免成为"专家越权主导全 Case"的口子。

---

## 2. 三个硬边界（任一缺失即越权）

### 边界 1：Manager 不接工单

`scrna`（或任何领域专家）被指派为 Manager 时，在本 Case 内**临时关闭自己的 `recruitable`**：不再作为可招募专家落 Work Item。否则会出现 "既调度三兄弟又自己接单" 的双重身份混乱，编排与执行不分。

- 落地：Bridge 在该 Case 内，从 `role_agent_map` 中**屏蔽 Manager 所在 `agent_id` 对应条目**。
- 该屏蔽仅对本 Case 生效，不影响其它 Case 中该 Agent 继续作为可招募专家。
- 屏蔽必须在 `created` / `planning_pending` 转换时写入审计，事件名 `manager_appointed`，actor=Manager，payload 含被屏蔽 `agent_id`。

### 边界 2：领域归口判断不能交给领域 Agent 自己

是否进入"单细胞 multi-agent Case"这个**入口决策**由 `agent-router` / `agent-general` 做顶层路由，而不是让 `scrna` 自判。否则领域 Agent 一旦被选为 Manager 就有动机把所有任务都拉成自己域的群聊（"手里有锤子看什么都像钉子"）。

- 落地：触发条件仍按 VISION §5.1 + 建单幂等键（`session_id + 意图哈希`）；Manager slot 由 router / general **显式指派**，领域 Agent 不自行升任。
- 入口路由必须落审计，含命中的触发条件代号与 Manager slot 选择理由。
- 若 router 判断不构成多专家 Case（简单问答、单步低风险），即使领域 Agent 声明了 `can_act_as_domain_manager_for`，也不得启用领域主管模式。

### 边界 3：QC 仍然独立

`agent-scrna` 当 Manager 时，质控仍走 `agent-qc`，**不能因为"自己懂单细胞"就跳过三态门**。

- 落地：lead planner 在 plan 中**显式声明**是否需要 `quality_running`；声明需要时由 `agent-qc` 给出 PASSED / WARNING / BLOCKED 三态结论。
- Manager 不得在执行中临时插入未声明的质控环节，也不得以"领域内自评"替代 `agent-qc`（沿用 VISION §5.2）。
- 若 Manager 越权尝试跳过 QC，Bridge 应拒绝该转换并落审计事件 `qc_bypass_attempted`。

---

## 3. "领域主管"泛化机制（不是单细胞特例补丁）

### 3.1 为什么泛化

为单细胞打补丁（例如 `acts_as_manager_when_lead_single_cell` 这种领域硬编码字符串）是坏味道：下次 RNA-seq 扩成 "上游比对 + 下游统计" 两个专家、ATAC-seq 扩成 "footprinting 专项" 时又要加一个补丁。用**可复用的 registry 标记**表达，单细胞只是第一个实例。

### 3.2 registry 标记定义

`data/ai/*.yaml` 的 `features.agentteams` 块新增可选字段 `can_act_as_domain_manager_for`：

```yaml
# scrna.yaml
features:
  internal_case_role: agent-scrna
  agentteams:
    category: expert
    recruitable: true
    planner_eligible: true
    execution_modes: [readonly_consultation, workspace_execution]
    max_parallel_work_items: 2
    case_mode_excluded_tool_packs: [subagents]
    handoff_in_case_mode: false
    work_item_timeout_sec: 3600
    can_act_as_domain_manager_for: [single-cell]   # 新增：可担任 Manager 的域标签
```

### 3.3 语义

- `can_act_as_domain_manager_for` 是**能力声明**，不是**自动启用**：声明了不代表每次单细胞 Case 都用它当 Manager，仅代表 router 可在域标签命中时**优先**考虑。
- 同一域标签可被多个 Agent 声明（未来若有两个单细胞主管竞争，router 按其 `capability_scope` 与任务方向择优；当前单细胞域唯一声明者是 `scrna`，无歧义）。
- 未声明该字段的 Agent 不得担任 Domain Manager（但可继续担任 lead planner 或可招募专家）。
- 该字段由 `AgentTeamsCapabilityRegistry` 自动聚合，Bridge / Gateway / Projector 三处共用，不得在任一处再写硬编码。

### 3.4 Bridge 派单时的启用规则

Case 建单并完成入口路由后：

1. router / general 产出 `domain_tag`（如 `single-cell`、`bulk-rnaseq`、`bulk-atacseq`），落审计。
2. 若 Case `domain_tag` 命中某 Agent 的 `can_act_as_domain_manager_for`，Manager slot 优先使用该 Agent；选择理由落审计（命中域 + 候选 Agent 列表 + 最终选择）。
3. Manager slot 指派后，Bridge 对本 Case 的 `role_agent_map` 屏蔽 Manager 所在 `agent_id`（边界 1）。
4. 若无 Agent 声明该域主管，回退到默认 Manager（`agent-general`）。
5. 与幂等键（`session_id + 意图哈希`）协同：同一会话同一意图不重复建单；已建单后即便 router 重新判域，也不变更 Manager slot（避免中途换帅）。

### 3.5 同域 lead planner 与 Domain Manager 的关系

启用 Domain Manager 模式时，lead planner **默认由 Domain Manager 自己担任**（它最懂本域三兄弟如何编排）。若 Case 涉及跨域（如单细胞 + 可视化 + QC），Domain Manager 只在自己域内当 lead planner，跨域协作仍由 Manager 间 handoff 或回退到 `agent-general`。

---

## 4. 分阶段落地路径

### 4.1 Phase 1：lead planner 模式（零改动、立即可用）

**目标**：不引入 Domain Manager 机制，先用现有 §4.2 机制让 `scrna` 当 lead planner 而不是 Manager，验证同域协调体感。

- Manager 仍由 `agent-general` 担任：接单、点评、汇总、不参与同域调度。
- lead planner 选 `scrna`，由 `scrna` 写计划，把三兄弟的 `depends_on` DAG 一并排进 `plan_hash`。
- 用户确认计划后由 Bridge 按 `plan_hash` 派工单，`scrna` 作为 lead planner 已完成使命，后续以可招募专家身份视情况承接高级分析工单（仍受 §4.2 约束）。

**改动量**：零（VISION v1.1 §4.2 现成机制）；仅 router 在选 lead planner 时优先匹配 `capability_scope` 含单细胞的 Agent。

**风险**：低；若失败回退到 general 当 lead planner。

**验收**：跑通一个单细胞复合 Case，`scrna` 出的 plan 把上游→整合→高级 `depends_on` 排清楚，general Manager 点评通过；异常路径（上游失败、整合超上限）也按 §6.3 触发重试 / 升级。

### 4.2 Phase 2/3：Domain Manager 模式（增量上线）

**前置条件**：Phase 1 在生产跑稳至少 2 周，确认单细胞复合 Case 的体感显著优于 general 管线。

**改造点（对齐收敛实施计划 §4.1 / Phase 2）**：

| 改动 | 位置 | 要点 |
| --- | --- | --- |
| Agent YAML 声明 | `data/ai/scrna.yaml` 优先；未来可扩 `rnaseq.yaml` / `atacseq.yaml` / `cloud_ops.yaml` | 加 `features.agentteams.can_act_as_domain_manager_for: [<domain_tag>]` |
| registry 聚合 | `src/omichub/application/services/agentteams_capability_registry.py` | 暴露 `domain_manager_map() -> dict[domain_tag, agent_id]`；加载时校验：声明 `can_act_as_domain_manager_for` 的 Agent 必须同时满足 `recruitable=true && planner_eligible=true`，否则报错 |
| Bridge 消费 | `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py` | Case 建单后：① router 产出 `domain_tag`；② 命中 `domain_manager_map` 则指派 Domain Manager 并落审计事件 `manager_appointed`；③ 从本 Case 的 `role_agent_map` 屏蔽 Manager 所在 `agent_id`；④ 删除旧的硬编码 `data-steward` 等本地映射（§4.1 要求） |
| Gateway 消费 | `integrations/agentteams/gateway/service.py` | `agent_policies` 从 registry 加载；对被屏蔽 `agent_id` 的工单派发请求直接拒绝，返回 `manager_self_dispatch_forbidden` |
| Projector 消费 | `src/omichub/application/services/case_room_projector.py` | Domain Manager 的 `room_speech` 用领域主管头像与 status_lines；与普通 Manager（general）头像区隔 |
| 入口路由 | `agent-router` / `agent-general` 提示词与 `chat_service.py` | 出 `domain_tag`；命中触发条件且 tag 命中 domain_manager_map 才启用；否则默认 general Manager |

**风险与回退**：

- registry 加特性开关 `domain_manager_enabled`（默认 True 逐步放量，异常切回 general Manager，零数据迁移）。
- Bridge 在 Manager slot 已指派后对 `domain_tag` 变更只落审计不切人，避免中途换帅。
- 越权检测：Bridge/Wateway 拒绝 Manager 自派工单 → event `manager_self_dispatch_forbidden` → 告警。

### 4.3 不 vat 走的路径（明确排除）

- 不允许领域 Agent 自行升任 Manager（必须 router 指派，边界 2）。
- 不允许 Domain Manager 在执行中插入未声明 QC（边界 3）。
- 不允许同域所有兄弟专家都声明 `can_act_as_domain_manager_for` 同一 tag 形成歧义；registry 加载时歧义即报错。
- 不允许 Domain Manager 在跨域 Case 中扩张自己的调度权到其它域；跨域仍走 general Manager 或 handoff。

---

## 5. 三处一致性（沿用 VISION §4.4 / 收敛计划 §4.1）

Registry 是单一来源，三处消费必须一致：

1. **Bridge `service.py`**：解析 target → agent_id，屏蔽 Manager 所在 agent_id，校验 plan_hash，落审计。
2. **Gateway `service.py`**：`agent_policies` 从 registry 加载 capability 与 tool 白名单，拒绝屏蔽 agent_id 的自派工单。
3. **`CaseRoomProjector`**：审计事件 actor 投影为头像/名字；Domain Manager 用领域主管头像，与普通 Manager 区隔。

在 `tests/unit/test_agentteams_capability_registry.py` 增加：

- `domain_manager_map()` 返回当前所有声明 `can_act_as_domain_manager_for` 的 Agent。
- 声明该字段的 Agent 必须同时 `recruitable=true && planner_eligible=true`。
- 同一 `domain_tag` 被多个 Agent 声明时加载报错（除非显式标注优先级，本版本不实现优先级）。
- Bridge 屏蔽一致性：Domain Manager 指派后，`role_agent_map` 中该 agent_id 被屏蔽，且 Gateway 拒绝其自派工单。

在 `tests/contract/` 增加：

- Domain Manager 指派审计事件 schema：`manager_appointed`、`manager_self_dispatch_forbidden`、`qc_bypass_attempted`。
- Projector 输出：Domain Manager 的 `room_speech` avatar/name 字段与普通 Manager 不同。

---

## 6. 验收清单

### 6.1 Phase 1（lead planner 模式）

- [ ] 单细胞复合 Case 中 `scrna` 作为 lead planner 出 plan，三兄弟 `depends_on` 正确排进 `plan_hash`。
- [ ] Manager 仍为 `agent-general`，点评 / 汇总正常。
- [ ] 异常路径（上游失败、整合重试、高级超上限）按 VISION §6.3 触发。
- [ ] 简单单细胞问答不触发 multi-agent Case（边界 2 兜底）。

### 6.2 Phase 2/3（Domain Manager 模式）

- [ ] `scrna.yaml` 声明 `can_act_as_domain_manager_for: [single-cell]`。
- [ ] `registry.domain_manager_map()` 返回正确，三处消费一致。
- [ ] 单细胞复合 Case 由 `scrna` 担任 Domain Manager，`role_agent_map` 在本 Case 内屏蔽 `agent-scrna`（边界 1）。
- [ ] 入口路由由 router 显式指派 Manager slot，`scrna` 不自判升任（边界 2）。
- [ ] QC 由 `agent-qc` 独立完成，三态结论不受 Manager 干预（边界 3）。
- [ ] 越权尝试：Domain Manager 自派工单被 Gateway 拒绝并落审计 `manager_self_dispatch_forbidden`。
- [ ] 越权尝试：Manager 跳过声明 QC 被拒绝并落审计 `qc_bypass_attempted`。
- [ ] 回退开关 `domain_manager_enabled=false` 时全部回退到 `agent-general` 当 Manager，零数据迁移。
- [ ] 契约测试全绿，回归测试全绿。

---

## 7. 附：术语

| 术语 | 定义 |
| --- | --- |
| Domain Manager | 领域主管；在某域复合 Case 中担任 Manager 的领域专家；本版本首个实例为单细胞的 `agent-scrna` |
| domain_tag | Case 的领域标签，由 router 产出，用于命中 `can_act_as_domain_manager_for` |
| 三兄弟 | 单细胞域拆分的三个专家：`agent-scrna-upstream` / `agent-scrna-integration` / `agent-scrna-advanced` |
| lead planner 模式 | 不启用 Domain Manager，领域专家仅当 lead planner 排 DAG，Manager 仍为 general |
| `manager_appointed` | 审计事件：Domain Manager 被指派时落审计，含 domain_tag、Manager agent_id、被屏蔽 agent_id |
| `manager_self_dispatch_forbidden` | 审计事件：Domain Manager 尝试自派工单被 Gateway 拒绝 |
| `qc_bypass_attempted` | 审计事件：Manager 尝试跳过声明 QC 被 Bridge 拒绝 |
