# Overdrive 超频模式优化框架 v1（Manager 真规划专项：让 AI 按任务动态分工）

> 文档性质：施工规格，供 Codex 直接施工。  
> 编写日期：2026-08-11。  
> 问题动机：用户发起"TnpD 序列对 20 个基因组建树"任务，收到的回复"已按系统发育领域契约固定执行链：……"是 `chat_service.py` 里的硬编码模板——**用户感知到超频模式不是真 AI 在规划**，要求"让 AI 真正根据不同任务进行 multi-agent 分析"。  
> 与 AgentTeams 文档族的关系：本文针对的是 CygnusX 侧超频（overdrive）Manager 规划层，不涉及 Bridge/Gateway/Worker 契约。

---

## 0. 根因分析（2026-08-11 实证）

### 0.1 证据

| # | 证据 | 出处 |
|---|---|---|
| E1 | 回复文案逐字硬编码，命中权威契约即覆盖 LLM 输出 | `src/cygnusx/application/services/chat_service.py:3178-3183` |
| E2 | DB 时间戳：用户消息 12:22:21.560 → 助手回复 12:22:21.569，**间隔 9.7ms**，物理上不可能是 LLM 往返 | `chat_messages` 表，session `1147829a-…` |
| E3 | 同一模板 1 小时内在 3 个会话重复出现 5 次，全部秒回 | `chat_messages` LIKE '%固定执行链%' |
| E4 | 权威规则定义在领域包 YAML，`phylo.yaml` 有 2 条 `authoritative: true` 规则 | `data/ai/domains/phylo.yaml:93-111` |

### 0.2 当前规划流程（问题所在）

```
用户消息 → 超频规划（chat_service.py:3123-3199）
  ├─ preflight/followup 分支：直接返回模板问题/话术（不调 LLM）
  └─ else 分支：调用 Manager LLM（ask_manager，max_tokens=900）
        ↓ LLM 返回 speech + assignments
     【覆盖点】chat_service.py:3169-3183：
        authoritative_assignments = _default_overdrive_assignments(..., authoritative_only=True)
        if authoritative_assignments:        ← 命中 phylo.yaml 权威规则
            assignments = authoritative_assignments   ← LLM 分工整体丢弃
            speech = "已按系统发育领域契约固定执行链：……"  ← LLM 话术整体丢弃
```

### 0.3 根因分级

| # | 根因 | 后果 |
|---|---|---|
| M1 | **权威契约是"替换"而非"约束"**：命中后 LLM 的 assignments/speech 全部作废 | 同领域任何任务都得到同一条固定链 + 同一句模板话术；LLM 白调用（浪费 token） |
| M2 | **模板话术伪装成 AI 回复**：固定文本以 manager 人格发出，无来源标注 | 用户无法分辨"AI 规划"与"规则兜底"，信任受损 |
| M3 | **权威规则粒度过粗**：`task_type: phylogeny_construction` 一个槽位命中即锁死整条链 | "20 个基因组"与"200 个基因组"、"蛋白序列"与"核酸序列"得到完全相同的计划，无法按任务调整（分片、并行、增删环节） |
| M4 | **preflight/followup 分支完全跳过 LLM**（E2 的 9ms 即此路径） | 部分会话连 Manager LLM 都没调用就给出了"规划结论"话术 |
| M5 | **无规划来源遥测**：LLM 规划率、规则覆盖率、修复率均无记录 | 无法评估"AI 真规划"的占比 |

### 0.4 设计原则（施工全程遵守）

1. **LLM 是规划者，规则是校验者**：领域契约定义"必须包含什么环节、什么顺序"（安全护栏），但任务拆分、agent 选择、并行度、话术由 Manager LLM 按具体任务生成。
2. **权威契约降级为"必需阶段锚点"**：`authoritative: true` 的规则不再提供完整计划，而是提供"该领域计划必须覆盖的阶段契约"（task_id 锚点 + 输入输出契约 + 依赖顺序）。
3. **话术永不覆盖**：speech 一律来自 LLM；LLM 不可用时的兜底话术必须中性且如实标注（如"已按领域标准流程生成计划（规则辅助）"），禁止伪装成个性化规划。
4. **可回滚**：引入配置开关，保留旧的 override 行为作为 fallback 模式。

---

## 1. P0 — 规划层改造（约束式权威契约）

### P0-1 规划模式配置开关

**施工**：`src/cygnusx/core/config.py` 新增（裸名无前缀）：

```python
overdrive_authoritative_mode: str = "constraint"   # constraint | override | off
overdrive_plan_repair_enabled: bool = True          # LLM 计划违规时给一次修复机会
```

- `constraint`：新模式（本文 P0-2）——LLM 规划 + 规则校验；
- `override`：旧行为（整体替换），用于快速回滚；
- `off`：完全不用权威规则（调试用）。

`.env.example` 同步。改完 `docker restart cygnusx-web`。

### P0-2 核心改造：authoritative 从"替换"改为"校验+补缺"

**施工**：`chat_service.py:3168-3183` 重构。新模式流程：

```
LLM 返回 assignments（经 _normalize_overdrive_assignments 归一化）
  ↓
authoritative_rules = 命中的 authoritative 规则集（不再生成完整 assignments，
                      而是提取"必需阶段锚点"列表：task_id / depends_on / 输入输出契约）
  ↓
validate_llm_plan(assignments, authoritative_rules) → violations[]
  校验项：
  a) 覆盖性：每条权威规则的 task_id 锚点必须在 LLM 计划中有对应任务
     （task_id 相同，或其 produces_outputs 覆盖规则的 produces_outputs）
  b) 顺序性：锚点间的 depends_on 方向不得颠倒（homolog-search 必须在 phylogeny 上游）
  c) 能力边界：锚点任务的 agent 必须在 rule.agent_match 允许的专家范围内
  d) 契约完整性：锚点任务的 accepts_inputs/produces_outputs 不得缺失
  ↓
无违规 → 采用 LLM 计划（保留 LLM 对任务的增删、分片、并行设计）
有违规且 overdrive_plan_repair_enabled → 携带 violations 发起一次修复调用
  （prompt 见附录 7.1；修复后仍违规 → 进入下一条）
修复失败/未启用 → rule_merge 兜底：
  以权威链为骨架，保留 LLM 计划中不冲突的额外任务，合并后输出
  ↓
记录审计：planning_mode ∈ {llm, llm_repaired, rule_merge, rule_override}
```

**speech 处理**：
- 所有模式（含兜底）下 speech 一律使用 LLM 原文；
- LLM 不可用/未调用（preflight 分支）时，兜底话术为中性文本：`"已为你生成执行计划，请确认任务分工与顺序。"`，**删除** `chat_service.py:3180-3183` 和 `3199` 的两条领域特定模板；
- 助手消息 metadata 增加 `planning_mode` 字段（写入 `metadata_json`），前端可用于展示"AI 规划/规则辅助"标记。

**验证**：
1. 发"TnpD 对 20 个基因组建树"→ 回复不再是固定模板句；计划含 tnpd-homolog-search → tnpd-phylogeny 锚点且由 LLM 组织语言；
2. 发"对 200 个基因组做同样分析"→ LLM 应给出分片/并行设计（锚点仍在）；
3. mock LLM 返回缺锚点的计划 → 触发修复调用；修复仍缺 → rule_merge 兜底且审计记录 `planning_mode=rule_merge`；
4. `OVERDRIVE_AUTHORITATIVE_MODE=override` 时行为与现状一致（回滚验证）。

### P0-3 领域包 schema 扩展：authoritative 规则声明"锚点"语义

**施工**：
1. `src/cygnusx/domain/domains/schema.py` 的 `AssignmentRule` 增加字段：
   ```yaml
   authoritative: true
   required: true            # 该阶段锚点必须出现在最终计划中
   allow_split: true         # 允许 LLM 把该阶段拆成多个并行子任务（分片）
   allow_reorder: false      # 是否允许与其他锚点交换顺序
   ```
2. `data/ai/domains/phylo.yaml` 两条 authoritative 规则补 `required: true`；homolog-search 补 `allow_split: true`（按基因组分片），phylogeny-build 补 `allow_split: false`。
3. `data/ai/domains/omics.yaml` 自查是否有 authoritative 规则，同法处理。
4. `DomainPackLoader` 校验新字段类型；旧包无新字段时按 `required=true / allow_split=false / allow_reorder=false` 默认（与权威语义兼容）。

**验证**：pack loader 单测；schema 非法字段报错不静默。

### P0-4 preflight 分支的话术诚实化

**施工**：`chat_service.py:3125` 的默认 speech（"为了把计划做得可执行……"）保留（它确实是规则话术且语义如实）；检查 preflight/followup 分支所有固定话术，凡给用户"已完成规划"错觉的改为如实描述当前状态（"需要先确认几个关键信息"）。同时确保这些分支的消息 metadata 标 `planning_mode: "rule_preflight"`。

**验证**：E2 场景（9ms 秒回）重放，话术无"已按…固定执行链"类伪规划表述。

---

## 2. P1 — 规划质量与可观测

### P1-1 规划遥测

**施工**：新增轻量记录（Redis 计数器即可，参照 `agentteams_consultation_telemetry_service.py` 模式）：
- `overdrive_planning_total{mode}` 按 planning_mode 计数；
- `overdrive_plan_repair_total{outcome}` 修复成功/失败；
- `overdrive_llm_speech_overridden_total`（新模式下应恒为 0，作为回归哨兵）。

管理端展示可并入 AgentTeams 遥测面板（见 `AgentTeams_update_v2.1.md` §2.3），本期先保证数据可查询。

**验证**：跑 10 次规划后能看到 mode 分布；constraint 模式下 `llm_speech_overridden` 恒 0。

### P1-2 Manager prompt 升级

**施工**：`OVERDRIVE_MANAGER_PROMPT`（`chat_service.py:281-308`）补充：
1. 注入权威锚点清单（新增 `{authoritative_anchors}` 占位）："以下阶段为本领域必需环节，你必须将它们纳入计划（可拆分、可并行化、可补充中间环节），并保持其依赖顺序与输入输出契约：…"；
2. 明确"你可以为大规模输入设计分片并行（同一专家承担多个 shard 任务）"；
3. 明确"speech 必须反映你实际生成的计划，禁止泛泛而谈"。

**验证**：200 基因组场景 LLM 输出 shard 设计；speech 与 assignments 内容一致。

### P1-3 计划确认卡显示规划来源

**施工**：前端 `PlanConfirmationCard.vue` 读取消息 metadata 的 `planning_mode`：
- `llm` → 显示"AI 规划"标记；
- `llm_repaired` → "AI 规划（已自动校正）"；
- `rule_merge` / `rule_override` / `rule_preflight` → "领域标准流程辅助"。

**验证**：三种模式各构造一次，卡片标记正确；`vue-tsc -b` + `vite build` 通过（幻影错误删 tsbuildinfo）。

---

## 3. P2 — 后续可选（本期不做，仅记录）

1. 多领域混合任务的锚点冲突仲裁（phylo + omics 同时命中时的优先级）；
2. Manager 规划失败率纳入告警；
3. 用户编辑计划后反哺领域包规则（人工校正 → 规则建议）。

---

## 4. 验收标准

⬜ **真规划**：同一领域三个不同规模/输入的任务得到三份结构不同但锚点齐全的计划（LLM 生成，非模板）。  
⬜ **真话术**：speech 与计划内容一致，全库 grep 不再出现"已按系统发育领域契约固定执行链"作为 assistant 消息新发（历史数据不动）。  
⬜ **护栏有效**：mock LLM 缺锚点 → 修复或 rule_merge，最终计划必含必需阶段且顺序正确。  
⬜ **可回滚**：`override` 模式行为与现状逐字节一致。  
⬜ **可观测**：planning_mode 分布可查；speech 覆盖计数恒 0。  
⬜ **不回归**：普通 chat（非超频）路径不受影响；`docker restart cygnusx-web` 后超频端到端跑通一次建树 Case。

---

## 5. 施工纪律

- 改 `chat_service.py` / schema / prompt → `docker restart cygnusx-web`（uvicorn 无 reload）；本项目无热重载，`docker exec` 看的是磁盘不是内存。
- 注意 chat_service 有 **LangGraph 与 legacy 双执行路径**：超频规划入口若两条路径都有，必须两边都改或确认只有一条生效（grep `authoritative_only` 与 `OVERDRIVE_MANAGER_PROMPT` 的全部调用点）。
- 前端构建：`vue-tsc -b` + `vite build`；报"找不到名字"幻影错误先删 `frontend/tsconfig*.tsbuildinfo`。
- 禁止 git commit（用户自行审查提交）；发现规格错误在交付报告中提出，不擅自改设计。

---

## 6. 附录

### 6.1 修复调用 prompt 模板（P0-2 用）

```
你刚才的执行计划缺少本领域的必需环节或违反了依赖约束：
{violations 逐条列出：缺失锚点 task_id / 顺序颠倒 / agent 越界 / 契约缺失}

必需环节契约（必须全部覆盖，保持依赖方向）：
{authoritative_anchors：task_id、depends_on、accepts_inputs、produces_outputs、允许的专家}

请输出修正后的完整计划（同样的 JSON 格式），保留你原计划中的合理设计（分片、并行、额外环节），只修复违规点。
```

### 6.2 审计/metadata 字段

```json
{
  "planning_mode": "llm | llm_repaired | rule_merge | rule_override | rule_preflight",
  "authoritative_anchors": ["tnpd-homolog-search", "tnpd-phylogeny"],
  "plan_violations": [],
  "repair_attempted": false
}
```

### 6.3 涉及文件清单

| 文件 | 改动 |
|---|---|
| `src/cygnusx/application/services/chat_service.py` | P0-2 重构 3168-3199；删模板话术；metadata 写 planning_mode；P0-4 |
| `src/cygnusx/domain/domains/schema.py` | AssignmentRule 新增 required/allow_split/allow_reorder |
| `src/cygnusx/infrastructure/config/domain_pack_loader.py` | 新字段校验与默认值 |
| `data/ai/domains/phylo.yaml`（+自查 omics.yaml） | 补锚点语义字段 |
| `src/cygnusx/core/config.py` / `.env.example` | overdrive_authoritative_mode 等开关 |
| `frontend/src/components/ai-chat/PlanConfirmationCard.vue` | 规划来源标记 |
