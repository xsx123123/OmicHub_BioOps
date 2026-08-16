# 超频模式（Overdrive）审查修复清单

> **来源**：对 `ARCHITECTURE_DESIN/agentteams.md` 第一期实现的后端/前端双份审查报告（2026-08-04）。
> **结论回顾**：第一期本体可交付（契约点全落实、51 项后端测试全绿、前端 type-check/build 通过）。本文档是遗留问题修复清单，共 6 项，每项含：问题、证据位置、修复步骤、验证方法。
> **执行要求**：修代码时保持最小改动；禁止 git 任何写操作（commit/push/reset）；不引入新依赖；修完全部跑第 7 章验证。

---

## 修复项 1：契约文档回写 —— SSE 线格式拍平（改文档，不改代码）

**问题**：冻结契约（`ARCHITECTURE_DESIN/agentteams.md` §4.3）写的 `room_speech`/`mode_changed` 是 `metadata` 嵌套格式，但 SSE 序列化层（`src/omichub/api/v1/chat.py:100-102` 附近）对所有 chunk 执行 `data.update(chunk.metadata)` **拍平**——这是该序列化层的既有惯例（`collaboration_fanout` 等既有类型同构）。线上实际格式是拍平的，前后端自洽、功能正确。决定：**保留实现，修订文档**。

**修复步骤**（只改 `ARCHITECTURE_DESIN/agentteams.md`）：

1. 在 §4.3 开头加一段说明：

   > **线格式注意**：所有 chunk 经 SSE 序列化层（`api/v1/chat.py`）时会执行 `data.update(chunk.metadata)` 把 metadata 拍平到顶层——这是该层的既有惯例。因此线上实际格式为拍平结构，下文 JSON 示例中 `metadata` 内字段在线上位于顶层。前端按拍平格式读取。

2. §4.3 两个示例（`mode_changed`、`room_speech`）各补一个"线上实际格式"代码块：

   ```json
   // mode_changed 线上格式
   { "type": "mode_changed", "session_id": "...", "mode": "overdrive", "enabled": true }
   ```
   ```json
   // room_speech 线上格式
   { "type": "room_speech", "session_id": "...", "message_id": "msg-...",
     "sender": { "agent_id": "...", "name": "...", "avatar": "...", "color": "...", "role": "manager" },
     "content": "……", "round": 1 }
   ```

3. 在示例后补一句：已知扩展字段（契约外但已实现）：`mode_changed` 可带 `degraded: true`（Matrix 降级时）；`room_speech`/会话可带 `matrix_room_id`（第二期 Matrix 绑定时）。第三方对接应忽略未知字段。

**验证**：`grep -n "拍平" ARCHITECTURE_DESIN/agentteams.md` 有命中；文档 §4.3 与 `api/v1/chat.py` 序列化层行为一致。

---

## 修复项 2：工具 schema 与运行时对齐（fan-out 最少 1 个子任务）

**问题**：实现删除了 `src/omichub/application/services/parallel_subagent_service.py` 中"fan-out 至少 2 个子任务"的运行时校验（超频单 assignment 分派需要），但 LLM 面工具契约没同步：`tool_configs/tools_schema.yaml:73-77` 仍是 `minItems: 2`、描述仍写"2–5 个"。LLM 会被告知最少 2 个，后端实际接受 1 个。

**修复步骤**：

1. `tool_configs/tools_schema.yaml:73-77`（`parallel_subagents` 的 `tasks` 参数）：
   - `minItems: 2` → `minItems: 1`；
   - 描述中"2–5 个"改为"1–5 个"（先 `Read` 确认原文再改，保持其余措辞不变）。
2. 全局搜索同步点，逐一核对并修正过时表述：
   - `Grep "2–5" tool_configs/ src/omichub/ ARCHITECTURE_DESIN/ Protocol/`
   - `ARCHITECTURE_DESIN/multi-agent.md` 中 parallel_subagents 的"至少 2 个/2–5 个"描述 → "1–5 个"。
   - **注意区分**（不要误改）：
     - `chat_service.py` 的 `ROUTER_SYSTEM_PROMPT`（:161-181）与 `MULTI_AGENT_SYSTEM_PROMPT_SUFFIX`（:150-156）里"可拆成 2–5 个独立子任务才 fanout"是**何时拆**的语义建议，保持不变；
     - `chat_service.py:2367` 统一路由 fanout 的 `len(fanout_tasks) >= 2` 是路由自动分派的门槛，保持不变；
     - 要改的只是**工具 schema 的能力下限**（1 个也合法）。
3. 若有测试断言 minItems=2 或"至少两个子任务"报错文案，同步更新（`Grep -rn "minItems" tests/ tool_configs/` 与 `Grep -rn "至少.*子任务\|2 个子任务" tests/`）。

**验证**：`grep -n "minItems" tool_configs/tools_schema.yaml` 显示 1；`python -c "import yaml; yaml.safe_load(open('tool_configs/tools_schema.yaml'))"` 解析通过；相关单测全绿。

---

## 修复项 3：范围越界确认与加固（Matrix 第二期/管理面第三期提前量）

**背景**：实现提前完成了文档第二期（Matrix Gateway：`agentteams_room_gateway_service.py`、`chat_service.py:_run_overdrive_turn` 内 Matrix 建房/消息镜像、`api/v1/chat.py:168-248` room-events SSE、`integrations/agentteams/gateway/matrix_client.py` 等）和第三期（admin Bridge 向导、Case 事件推送、新建 Case 表单）。审查确认降级安全（gateway 默认 disabled，未配置时超频正常，Matrix 失败仅记日志）。**默认决策：接受提前量**，做以下加固；若产品决定拒绝，走末尾回退方案。

**加固步骤**：

1. **文档回写**：`ARCHITECTURE_DESIN/agentteams.md` 第 5 章末尾"明确不做（本期）"一节修订——把已实现的原第二期条目（Matrix 建房/消息镜像、room-events SSE、Case element_room_url 绑定）和第三期条目（Bridge 向导端点、Case 事件 SSE、新建 Case 表单）移到第 6/7 章对应位置并标注"已随第一期提前实现"；第 6.5 G5 条目标注完成状态。
2. **降级路径测试补强**（`tests/unit/test_overdrive_chat.py` 追加用例）：
   - gateway enabled=True 但不可达（mock httpx 抛 ConnectError）→ 超频轮正常完成，room_speech 序列完整，发出 `mode_changed{degraded:true}`；
   - gateway enabled=True、建房成功但 `post_message` 单条失败 → 仅记日志，不中断后续发言；
   - 会话无 `matrix_room_id` 时前端 room-events 404 → 后端返回结构与前端静默处理兼容（已有 `test_agentteams_room_gateway_service.py` 覆盖则跳过）。
3. **隔离检查**：确认 `_run_overdrive_turn` 内 Matrix 分支全部在 `if gateway_service.available:` 与 try/except 内（`chat_service.py:1578-1610`），`agentteams_gateway_enabled` 默认 False（`core/config.py:275`）——已确认则只需在代码注释中标注"第二期提前实现，默认关闭"。
4. **回退方案（仅当决策为拒绝时执行）**：`_run_overdrive_turn` 中删除 Matrix 建房/镜像分支（:1578-1610），保留 `agentteams_room_gateway_service.py` 与 room-events SSE（它们独立于聊天主路径，不影响），对应测试改为跳过。

**验证**：新增降级测试通过；`grep -n "提前实现" ARCHITECTURE_DESIN/agentteams.md` 有命中。

---

## 修复项 4：预置测试失败（HEAD 上即红，非本次改动引入）

**问题 A**：`tests/unit/test_agent_router.py` 2 个失败——`intent` 期望 `delivery_case` 实得 `case`（路由意图逻辑与测试漂移）。

**问题 B**：`tests/unit/test_agent_router_dispatch.py` 2 个失败——`data/ai/` 注册表新增 3 个 scrna agent，未同步进 router 候选表（router.md）。

**修复步骤**（先判对错，再改过期的一侧，禁止为通过而改）：

1. 问题 A：读 `test_agent_router.py` 失败用例与 `chat_service.py` 路由意图归一化逻辑（`_route_to_agent`/RouteInfo 归一化处，`Grep -n "delivery_case\|\"case\"" src/omichub/application/services/chat_service.py tests/unit/test_agent_router.py`）。判断 `case` 与 `delivery_case` 哪个是当前设计意图（查 `ARCHITECTURE_DESIN/multi-agent.md` 的意图枚举）。若设计已统一为 `case` → 更新测试期望；若 `delivery_case` 才是契约 → 修归一化逻辑。
2. 问题 B：`git diff HEAD -- data/ai/` 看新增的 3 个 scrna agent；对照 router 候选表来源（若候选由 `list_agents(active_only=True)` 动态生成，则测试里写死的候选清单/快照过期 → 更新测试数据；若存在 `router.md`/yaml 人工候选表 → 把新 agent 补进去）。改完跑 `pytest tests/unit/test_agent_router.py tests/unit/test_agent_router_dispatch.py -q` 全绿。
3. 在修复汇报中写明：每处是"代码对、测试过期"还是"测试对、代码漂移"，及依据。

**验证**：两个测试文件全绿；`pytest tests/unit -k router -q` 无回归。

---

## 修复项 5：前端低 severity 清理（4 小项）

**5a. 关键词触发路径诊断假阳性**

- 问题：发送时 overdrive=false、流中被关键词打开时，占位消息被 splice 移除，但 `onDone` 仍对脱离数组的 aiMsg 判空，触发 `reportChatDiagnostic('stream-empty')` 假阳性（`frontend/src/stores/agentHub.ts:1761-1776`）。
- 修法：`onDone`/`onError` 的普通分支加守卫——`if (session.overdrive || modeChangedToOverdrive)` 跳过空回复诊断与兜底。可直接复用函数内已算的 `effectiveOverdrive`（注意关键词路径下它初始为 false，需在 `onModeChanged` 时同步更新该闭包变量，或改为实时读 `session.overdrive`）。
- 验证：模拟"发送时关、流中开"路径（参考 `onModeChanged` splice 逻辑 `:1470-1473`），不再产生 stream-empty 诊断日志。

**5b. sendMessage options 补 overdrive 字段（对齐 F2 字面契约）**

- 问题：实现只有 session 路径（`agentHub.ts:1352`），没有 `options.overdrive ?? session.overdrive`（对照 multiAgent 的 `:1304/:1323` 写法）。
- 修法：`sendMessage` options 类型加 `overdrive?: boolean`；`:1352` 处改为 `const effectiveOverdrive = options.overdrive ?? session.overdrive ?? false`；若 options 显式传入则同时写回 `session.overdrive`（照 multiAgent `:1304`）。
- 验证：传 `options.overdrive=true` 且 session.overdrive=false 时请求体带 `overdrive:true`。

**5c. OverdriveToggle tooltip 文案对齐文档**

- 问题：`frontend/src/components/agent-workspace/OverdriveToggle.vue:34-36` 文案与设计文档 F1 指定文案不一致。
- 修法：改为文档原文——未开："开启后，复杂任务由 Manager 发现全部专家并分工协作，各专家在对话中依次发言"；已开："超频模式已开启：团队房间接管对话，直接布置任务即可"。
- 验证：目视/diff 确认。

**5d. 超频时最后一条消息误判 streaming 样式**

- 问题：`KimiMessageList.vue:64-70` 把最后一条 assistant 且 isTyping 的消息视为 streaming；超频轮最后一条 room_speech 命中该条件（内容无影响，仅样式）。
- 修法（二选一，推荐前者）：`onRoomSpeech` push 的消息显式 `status:'done'` 且不参与 typing 判定；或在 `KimiMessageList.vue` 的 streaming 判定条件中排除 `message.senderAgent` 存在的消息。
- 验证：超频轮结束后最后一条发言不显示打字光标/流式样式。

---

## 修复项 6：工作区变更集拆分（提交前整理，不执行 commit）

**问题**：工作区混了两个独立 feature 的改动（超频/AgentTeams vs 参考基因组），提交时应拆成两个变更集。

**修复步骤**：产出一份 `git add` 分组清单（写进修复汇报，**不执行任何 git 命令**）：

- **变更集 A：超频模式 + AgentTeams**
  - `src/omichub/application/schemas/chat.py`、`api/v1/chat.py`、`application/services/chat_service.py`、`application/services/parallel_subagent_service.py`、`application/services/agentteams_room_gateway_service.py`、`application/services/agentteams_service.py`、`application/services/agentteams_case_tool_service.py`、`api/v1/agentteams.py`、`api/v1/admin/agentteams_bridge.py`、`application/schemas/agentteams_bridge.py`、`core/config.py`（仅 gateway 相关 hunk，见下）、`integrations/agentteams/`、`deploy/agentteams/`、`frontend/src/stores/agentHub.ts`、`composables/useAgentChatStream.ts`、`components/agent-workspace/OverdriveToggle.vue`、`AgentSandbox.vue`、`views/StudioView.vue`、`components/ai-chat/types.ts`、`KimiMessageItem.vue`、`views/AgentTeamsCaseView.vue`、`components/task/AgentTeamsCasesPanel.vue`、`components/admin/AgentTeamsBridgeTab.vue`、`api/admin/agentTeamsBridge.ts`、`tests/unit/test_overdrive_chat.py`、`test_agentteams_*`、`tool_configs/tools_schema.yaml`、`ARCHITECTURE_DESIN/agentteams.md`、`multi-agent.md`
- **变更集 B：参考基因组模块**
  - `src/omichub/reference_genomes/`、`api/v1/router.py`（该文件两个 feature 都碰，需 `git add -p` 拆 hunk）、`core/config.py`（同上，`reference_genomes_yaml` 的 hunk 归 B）、`refdata/reference_genomes.yaml`、`frontend/src/api/referenceGenomes.ts`、`types/referenceGenomes.ts`、`views/ReferenceGenomesView.vue`、`tests/unit/reference_genomes/`、`test_reference_genomes_sequence.py`、`scripts/reference_genomes_smoke.py`
- **需人工裁决的混杂文件**：`api/v1/router.py`、`core/config.py`、`views/ProfileView.vue`（个人页 UI 重做，与两个 feature 均无关，建议单独第三个变更集）、`docs/knowledge/getting-started.md`、`.gitignore`、`.env.example`（逐文件确认归属）。
- 子模块变动（`pipelines/*`、`Protocol/FlowFrame` 显示 `m`）与两个 feature 无关，不要纳入。

---

## 7. 全部修复后的验证（必跑）

```bash
# 后端（用项目 .venv）
.venv/bin/python -m pytest tests/unit/test_overdrive_chat.py tests/unit/test_agentteams_room_gateway_service.py \
  tests/unit/test_agentteams_matrix_case_binding.py tests/unit/test_agentteams_bridge_admin.py \
  tests/unit/test_agentteams_service.py tests/unit/test_parallel_subagent_service.py \
  tests/unit/test_agent_router.py tests/unit/test_agent_router_dispatch.py -q
# 前端
cd frontend && npm run type-check && npm run build
# 文档
grep -n "拍平" ARCHITECTURE_DESIN/agentteams.md && grep -n "minItems" tool_configs/tools_schema.yaml
```

全部通过后汇报：每项修复的改动文件+位置、修复项 4 的对错判断依据、变更集分组清单（修复项 6）、验证输出摘要。
