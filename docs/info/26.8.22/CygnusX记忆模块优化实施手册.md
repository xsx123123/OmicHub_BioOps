# CygnusX 记忆模块优化实施手册

> 版本：v1.0 ｜ 日期：2026-08-21
> 范围：v2 共享分区召回断裂修复（M1）+ L4 协作室记忆接入（M2/M3）+ settle 泄漏面封堵（M0）+ 总验收（M4）
> 档案来源：《协作室L4记忆接入现状-调研核对与适配实施计划》（调研与核对的完整证据链在档案里，本手册只留结论与施工内容）
> 施工原则：每阶段独立可验；验收权在用户手里，不接受编码 Agent 自报通过。

---

## Part 0 根因摘要（调研已证实，证据位置见档案）

1. **settle 机制敞门**：通用 settle 两个投递点（`chat_service.py:2021-2043` 删除会话 / `:2045-2066` 消息阈值）不排除 AgentTeams 合成会话（`session_id=agentteams:<case_id>`、`status=system`、`mode=agentteams`、`agent_id=NULL`，见 `agentteams_usage_service.py:38-128`）；settle 抽取提示允许项目事实（`tasks/memory.py:42-63`）——Case 事实进长期记忆的通道在机制上存在。
2. **v2 共享召回断裂（全局 bug）**：工具层设计意图是 profile/preference 跨 Agent 共享（保存传 `agent_id=None`，`agent_memory_tool_service.py:20-32`），v2 写入归一为 `agent_id=""`（`agent_memory_service.py:63-76`），但召回侧（`search_memory :159-174`、`build_prompt_context_v2 :411-440`）按当前 agent 精确匹配——共享层永远查不到。影响所有非默认 agent，不止 L4。
3. **L4 零接入**：房间链路无任何 `build_prompt_context*` 注入（四分支均无）；L4 无记忆写入纪律装配（`MEMORY_V2_WRITE_DISCIPLINE` 只在 ChatService 路径）。

---

## Part 1 语义基线与红线（全程不可动摇）

- **Case 事实源永远是事件流 + 血缘**；长期记忆只承载"关于人的软偏好"。Case 临时事实（样本/分组/路径/中间决策）永不进 `memory_facts`。
- scope 语义定型：`profile`/`preference` = 跨 Agent 共享层（分区 `""`）；`project`/`summary`/`memory_block` = 当前 Agent 分区（隔离）。
- 红线：愿景前提不动；v2 off 回滚路径不动；旧 `agent_memories` 链路不动；不改 classify_execution_intent 与完成门；敏感信息拦截保持统一入口。

---

## Part 2 阶段 M0：settle 泄漏面封堵（P1，纯加法，可立即施工）

**spec**：入口双点排除 + 任务体双保险 + 审计留痕。

**提示词（paste-ready）**：

```
只改以下三处，纯加法，不动任何现有 settle 行为：
1. src/cygnusx/application/services/chat_service.py 的两处投递点——_enqueue_memory_summary（:2021-2043）与 _maybe_enqueue_memory_settle（:2045-2066）：增加排除，会话 mode=="agentteams" 或 status=="system" 或 session_id.startswith("agentteams:") 任一命中即不投递 settle。
2. src/cygnusx/infrastructure/celery_app/tasks/memory.py 的 settle_session_memory（:223-251）任务体开头加同样校验，命中即幂等返回并落一条 operational 级审计事件（防御未来新投递点绕过入口）。
3. 单测：三种排除标记各一条 + 任务体直接调用双保险一条 + 普通会话 settle 行为不变回归一条；v2 off 路径回归。
红线：不改游标/幂等逻辑；不改现有会话 settle 行为。改完逐条给自测证据。
```

**人工验收**：编码 Agent 跑单测全绿；用户抽查——构造一个 `mode=agentteams` 会话触发删除/阈值路径，确认无 settle 任务入队（审计或日志可见跳过）。

---

## Part 3 阶段 M1：v2 共享分区召回修复（P1，全局 bug）

**spec**：召回侧两路合并（共享层 + 当前 agent 分区），写入侧不动。

**提示词（paste-ready）**：

```
修复 v2 共享分区召回断裂。证据链：profile/preference 保存工具传 agent_id=None（agent_memory_tool_service.py:20-32），v2 写入归一 agent_id=""（agent_memory_service.py:63-76），但 search_memory（:159-174）与 build_prompt_context_v2（:411-440）按当前 agent 精确召回，共享层永远查不到。
1. search_memory 与 build_prompt_context_v2 的 facts 召回改为两路合并：共享分区 agent_id="" + 当前 agent 分区；profile/preference scope 结果优先；排序沿用 similarity × 时间衰减不变；同一事实两路命中时去重。
2. memory_blocks 读取同样纳入共享层（profile/preferences 块）。
3. 写入侧不动（None→"" 保持）；旧 agent_memories 链路不动。
4. 单测：agent A 写偏好 → agent B 召回可见；agent 分区事实（project/summary）不被其他 agent 召回；两路命中去重；v2 off 回归。
改完逐条给自测证据。
```

**人工验收**：编码 Agent 单测全绿。用户在 v2 灰度环境观察召回命中率变化（并入记忆监控面板）。

---

## Part 4 阶段 M2：L4 读取面接入（依赖 M1）

**spec**：房间侧装配注入共享层 + Manager 分区记忆；专家不接。

**提示词（paste-ready）**：

```
L4 房间读取面接入（前置：M1 已合入）：
1. agentteams_room_response_service.py 的 _build_question 装配时调用 AgentMemoryService.build_prompt_context_v2，只注入共享层（profile/preference）+ agentteams-manager 分区；沿用 3200 字节预算与 <user_memory> 不可信包装。
2. 覆盖 Manager 主回路与 tool_execute 分支；@专家直答与会诊子 Agent 不注入（purpose-shaped 裁剪，专家按四段契约干活）。
3. 挂房间侧装配，不改 AgentService.assemble_context 通用面，避免污染其他 consultation 调用方。
4. v2 off 时行为与现状完全一致（不注入）。
5. 单测：注入含共享偏好、不含其他 agent 分区事实、预算截断生效、<user_memory> 包装存在、专家分支无注入。
红线：不改完成门/审批/分类器。改完逐条给自测证据。
```

**人工验收**：用户手测（并入 E2E-18）——L2 告诉助手一条持久偏好（如"结果图都用英文标注"），进协作室提需求，Manager 回复/拆解体现该偏好；不体现则查 M1 合并召回与 M2 注入点。

---

## Part 5 阶段 M3：L4 写入纪律（prompt 层，可与 M2 并行）

**spec**：L4 版三条纪律进会诊 system prompt，解释 why 风格。

**提示词（paste-ready）**：

```
给 L4 会诊 system prompt 增加记忆写入纪律（装配点：agent_consultation_service.py 的 _build_instruction :470-531 或房间侧等价位置；不照搬 chat_service.py:1284-1289 的 ChatService 版，写 L4 版）。三条，用「解释为什么」的风格：
1. 只记录甲方明确陈述的持久偏好与纠错——一次性任务细节、临时上下文、未经确认的推测不进长期记忆，因为它们只对当前 Case 有意义；
2. Case 事实（样本/分组/文件路径/中间决策）禁止写入长期记忆——要查历史用血缘与 case_facts_query，因为记忆会漂移、血缘与事件流不会；
3. 写入前先 cygnusx_search_memory 查重，避免同一事实多版本漂移。
单测：装配产物包含三条纪律；v2 off 时不追加。红线：敏感信息拦截保持统一入口，不动。
```

**人工验收**：编码 Agent 导出 L4 会诊 system prompt 截图/落盘，三条纪律在；用户无需额外操作。

---

## Part 6 阶段 M4：总验收（E2E-18 + 观测）

**提示词（paste-ready）**：

```
真实平台栈执行 E2E-18，逐条给证据（事件流/DB 查询结果/审计记录），不接受自报通过：
1. 房间交互若干轮（含接单、澄清、交付）后查 memory_facts：无样本/分组/路径/中间决策类新增事实；
2. L2 存一条偏好 → L4 房间 Manager 回复体现该偏好（M1+M2 贯通证据）；
3. 构造删除 AgentTeams 合成会话路径：不触发 settle（审计可见跳过）；
4. Manager/专家实际可见记忆工具清单取证（消化调研存疑项：safe_only 过滤后的运行时工具面）。
同时把记忆敏感拦截次数、注入字节超限率接入既有记忆监控面板（memory_architecture.md §10 指标清单）。
```

**总验收 checklist（操作 → 期望现象 → 不通过处理）**：

| # | 验收项 | 操作（谁执行） | 期望现象 | 不通过处理 |
|---|---|---|---|---|
| V1 | settle 封堵 | 编码 Agent：单测+E2E-18③ | 三种标记不投递；任务体直接调用幂等返回 | 查排除条件覆盖 |
| V2 | 跨层召回贯通 | 用户手测：L2 存偏好→L4 提问 | Manager 回复体现偏好 | 查 M1/M2，降级单测定位 |
| V3 | Case 事实零泄漏 | 编码 Agent：E2E-18① | memory_facts 零 Case 事实新增 | **升 P0**，查 settle 之外的写入路径 |
| V4 | 注入预算与包装 | 编码 Agent：单测 | ≤3200 字节、`<user_memory>` 包装在 | 查 M2 装配 |
| V5 | 专家零记忆注入 | 编码 Agent：E2E @专家/会诊 | 专家 prompt 无 `<user_memory>` | 查分支条件 |
| V6 | 纪律上屏 | 编码 Agent：导出会诊 prompt | L4 版三条纪律在 | 查 M3 装配点 |
| V7 | 回滚路径 | 编码 Agent：v2 off 全量回归 | 旧链路零变化 | 回退越界改动 |

---

## Part 7 施工顺序与依赖

```text
M0（settle 封堵，纯加法）────── 可立即施工，与一切并行
M1（共享召回修复）──────────── 可立即施工，与 M0 并行
M2（L4 读取面）←── 依赖 M1
M3（L4 写入纪律）───────────── 与 M2 并行
M4（E2E-18 总验收）←── 依赖 M0–M3 全部合入 + staging 环境
```

- 提交纪律：M0/M1 一个 commit 组（记忆系统全局），M2/M3 一个 commit 组（L4 接入），各带 SHA 记录进四档对账。
- 灰度纪律：M1 属 v2 灰度范围，合并进 `memory_architecture.md` §11 灰度观察项；出现异常关 `memory_v2_enabled` 即回旧路径。
- 与既有路线图的对应：M0/M1 = 路线图第 2 批 2.5；M2/M3 = 第 3 批 3.3；M4 的 V2 与能力咨询修复的 E2E-17 可同批 staging 手测。

---

## 附：档案指针

- 调研证据链、核对结论、风险登记册全文：《协作室L4记忆接入现状-调研核对与适配实施计划》（Part 1–5）
- 记忆系统现状架构：`memory_architecture.md`（2026-08-18）
- 排期总账：《协作室后续优化路线图-2026-08-21》
