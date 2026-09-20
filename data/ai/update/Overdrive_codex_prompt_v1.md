# Codex 施工提示词 — Overdrive v1（Manager 真规划专项）

> 用法：把下面「提示词正文」整段粘贴给 Codex。

---

## 提示词正文

你是 CygnusX 仓库（/home/zj/zj_code_libarary/CygnusX）的施工工程师。本次任务：实施 **Overdrive 超频模式 v1 专项——Manager 真规划改造**，让 Manager LLM 真正按任务动态分工，权威领域契约从"整体替换"降级为"校验护栏"。

### 第一步：读文档（先读后动，禁止跳读）

1. **施工规格（权威）**：`data/ai/update/Overdrive_update_v1.md`——所有施工项、契约、验收标准以此为准。
2. **读懂现状代码再改**：
   - `src/cygnusx/application/services/chat_service.py:592-691`（`_default_overdrive_assignments`）
   - `src/cygnusx/application/services/chat_service.py:281-308`（`OVERDRIVE_MANAGER_PROMPT`）
   - `src/cygnusx/application/services/chat_service.py:3100-3202`（规划主流程，覆盖点在 3168-3183）
   - `src/cygnusx/application/services/domain_registry.py`（领域包求值器）
   - `src/cygnusx/domain/domains/schema.py` + `data/ai/domains/phylo.yaml`（权威规则定义）

规格文档与你的判断冲突时，以规格文档为准；发现规格有错误或遗漏，**先停下来在交付报告里说明，不要擅自改设计**。

### 施工顺序

严格按规格：**P0-1（配置开关）→ P0-3（schema 扩展，先做，P0-2 依赖它）→ P0-2（规划主流程重构）→ P0-4（话术诚实化）→ P1-1（遥测）→ P1-2（prompt 升级）→ P1-3（前端标记）**。

每完成一项：跑该项「验证」步骤 + 相关回归，通过后再做下一项。禁止一次性全做完再统一验证。

### ⚠️ 双执行路径警告（本任务最大的坑）

chat_service 存在 **LangGraph 与 legacy 双执行路径**。动手前必须先确认超频规划走的是哪条：

```bash
grep -rn 'authoritative_only\|OVERDRIVE_MANAGER_PROMPT\|_default_overdrive_assignments' src/cygnusx --include='*.py' | grep -v test
```

所有命中点都要检查：如果 LangGraph 路径也有等价逻辑，**两边都改**；如果只有一条生效，在交付报告中说明确认依据。漏改一条会导致普通 chat 重开后行为不一致。

### 本项目纪律（违反必返工，逐条遵守）

1. **无热重载**：改任何后端 Python 代码（chat_service / schema / config / prompt）→ `docker restart cygnusx-web`。`docker exec` 看到的是磁盘不是进程内存，改完不重启等于没改。
2. **compose 姿势**：live 栈 project 名是 `cygnusx`；需要重建容器时 `cd deploy/docker && docker compose --env-file ../../.env -p cygnusx up -d web`。改 `.env` 后 `docker restart` 无效（env 烘焙于容器创建时），必须 compose up 重建。
3. **领域包加载**：`DomainPackLoader` 有 `reload_if_changed`，但 schema/loader 代码本身变更仍须 restart web。
4. **前端**：改完跑 `vue-tsc -b` + `vite build`；报"找不到名字"幻影错误先删 `frontend/tsconfig*.tsbuildinfo` 再 build。naive-ui tooltip 的 #trigger slot 根元素禁止带 v-if。
5. **DB 时间戳即证据**：验证"真 LLM 规划"时，查 `chat_messages` 表用户消息与助手回复的 `created_at` 间隔——真 LLM 调用 ≥ 几百毫秒；间隔 <100ms 说明还在走模板路径，视为施工未完成。
6. **历史数据不动**：只保证新消息不再出现模板话术；不要清洗/修改 `chat_messages` 里的历史记录。

### 行为红线（本任务的核心诉求，逐条验收）

1. **speech 永不覆盖**：任何分支下，展示给用户的 speech 必须来自 LLM 原文或中性兜底话术；`chat_service.py:3180-3183` 和 `3199` 的两条领域特定模板必须删除，禁止换个位置复活。
2. **权威契约只做校验**：`authoritative: true` 规则不得再整体替换 LLM assignments（`override` 回滚模式除外）。
3. **兜底必须如实标注**：rule_merge / rule_override / rule_preflight 路径下，消息 metadata 必须写 `planning_mode`，且 speech 不得伪装成个性化规划。
4. **LLM 规划失败不能静默**：修复调用、rule_merge 兜底都要留审计/遥测记录。

### 每步验证的最低要求

- P0-3：`DomainPackLoader` 单测通过；非法字段报错不静默；旧包无新字段时默认值兼容。
- P0-2（核心验收）：
  1. 发"TnpD 对 20 个基因组建树"→ 回复不再是"已按系统发育领域契约固定执行链"模板句，计划含 homolog-search → phylogeny 锚点；
  2. 发"对 200 个基因组做同样分析"→ 计划出现分片/并行设计（锚点仍在、顺序不乱）；
  3. mock LLM 返回缺锚点计划 → 触发一次修复调用；修复仍缺 → rule_merge 兜底且审计记录 `planning_mode=rule_merge`；
  4. `OVERDRIVE_AUTHORITATIVE_MODE=override` 时行为与现状一致（回滚验证）；
  5. 以上每条都查 DB 确认 created_at 间隔 ≥ 几百毫秒（真 LLM 往返）。
- P1-3：三种 planning_mode 各构造一次，确认卡标记正确；vue-tsc + build 通过。
- 收尾：跑一次超频端到端（建计划 → 确认 → worker 执行），确认不影响现有执行链；普通 chat 路径无回归。

### 禁止事项

- 禁止 git commit（只改工作区，由用户审查后自行提交）。
- 禁止删除/修改 `data/ai/update/` 下任何既有文档；规格有错误在交付报告提出。
- 禁止做规格之外的"顺手优化"；发现的额外问题记入交付报告「建议后续项」。
- 禁止弱化权威校验来让测试通过（锚点缺失必须真的触发修复/兜底）。

### 交付报告格式（最后一轮输出）

按 P0-1…P1-3 逐项给：✅/⚠️/❌ + 改动文件清单 + 验证命令与输出摘要（含 DB 时间戳证据）+ 未通过项原因。附上双执行路径的排查结论。结尾给「建议后续项」列表。报告写入 `data/ai/update/Overdrive_update_v1_report.md` 并同步在聊天输出。
