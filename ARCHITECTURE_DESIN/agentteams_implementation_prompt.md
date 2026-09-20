# 超频模式（Overdrive）实施提示词

> 用法：把下面「提示词正文」整段复制给执行 AI（ChatGPT/Codex 等），并保证它能在仓库根目录 `/home/zj/zj_code_libarary/CygnusX` 下读写文件、运行命令。

---

## 提示词正文

你是资深全栈工程师，在 CygnusX 仓库（Vue3 + TS + naive-ui 前端 `frontend/`，Python FastAPI 后端 `src/cygnusx/`）中实现"超频模式（Overdrive）"第一期：**内置超频编排**。

### 第一步（必做）：读设计文档

先完整阅读 `ARCHITECTURE_DESIN/agentteams.md`。它是本任务的唯一权威设计文档，包含：现状盘点（精确到行号）、冻结接口契约（第 4 章）、第一期逐步实施详案（第 5 章 B1–B5 / F1–F5）、风险清单（第 8 章）。**只允许实现第一期（第 5 章），严禁提前做第二期 Matrix Gateway 的任何内容**（不接 Matrix、不动 `integrations/agentteams/bridge/`）。

### 任务目标（一句话）

星尘 AI 聊天新增会话级"超频模式"：顶栏开关或用户说"进入超频模式"触发；开启后每轮消息由 Manager（当前会话 agent 人格）先发言并分工 → 从全部 active 非 router agent 中选 0–5 个并行分派 → 各专家以独立消息（各自头像/名字/颜色）发言 → Manager 汇总；全部落库可回放。

### 冻结接口契约（不得偏离）

- 请求：`POST /api/v1/chat/stream` body 新增 `overdrive: bool | null`（null = 读会话 `sandbox_meta["overdrive"]`）。
- 会话 DTO 新增 `overdrive: bool`。
- 新增 SSE chunk：
  - `mode_changed`：`metadata: {mode: "overdrive", enabled: bool}`
  - `room_speech`：`metadata: {sender: {agent_id, name, avatar, color, role: "manager"|"worker"}, content: string, round: int}`，顶层带 `message_id`。
- 一轮事件序列：`room_speech(manager 分工)` → `room_speech(worker)`×N → `room_speech(manager 汇总)` → `done`。
- 每条 room_speech 落库为独立 assistant 消息，`metadata.senderAgent` 保存 sender。

### 关键实现约束（违反即返工）

1. **照抄现有模式**，不发明新风格：
   - `multi_agent` 三段式：`chat_service.py` :1644-1649（生效判定）/ :1714（建会话写入）/ :4217（DTO 读出）；
   - catalog 构造：:1344-1384（`list_agents(active_only=True)` 排除 `features.router`，**补 avatar/color 字段**）；
   - JSON 容错解析：`_extract_route_json`（:184）；
   - 直接调并行分派：:2355-2378（`ToolInvocationContext` + `ParallelSubAgentToolService().run_parallel_subagents`，不依赖 function tools）；
   - sandbox_meta 写入：**整体重新赋值 + flush**（直接改键不会落库）。
2. 编排入口在普通工具循环**之前**，`effective_overdrive` 为真时走完 `_run_overdrive_turn` 直接 return，**禁止双重回答**。
3. Manager prompt 用文档 5.1-B3 的 `OVERDRIVE_MANAGER_PROMPT`；assignments 过滤 catalog 外 agent_id、去重、截断到 5 个；解析失败兜底为"空分工 + 原始文本"。
4. 关键词：开启（"超频模式"/"超频"/"overdrive"）与退出（"退出超频"/"关闭超频"/"取消超频"），**退出类优先判定**；切换时写 meta 并 yield `mode_changed`。
5. 前端：
   - `OverdriveToggle.vue` 整体仿写 `MultiAgentToggle.vue`（77 行模板），挂 `AgentSandbox.vue:348` 旁 + `StudioView.vue:829` 旁（compact），流式中禁用；
   - `agentHub.ts sendMessage()` 超频会话**不 push 单条 assistant 占位消息**（:1256-1272 分叉），改为 `onRoomSpeech` 逐条 push 独立 assistant 消息（操作响应式代理）；`onModeChanged` 更新 `session.overdrive` 并 push system 提示；
   - `useAgentChatStream.ts`：body 加 `overdrive`、`normalizeAgentStreamEvent` 透传 metadata/message_id、`handleStreamEvent` 加两个 case；
   - `types.ts` 的 `ChatMessage` 加 `senderAgent?: {id; name; avatar?; color?}`；`KimiMessageItem.vue` 头像（:658-676）与名字（:323-326）优先用 `message.senderAgent`；
   - 历史消息加载时从后端 metadata 还原 `senderAgent`。
6. **最小改动**：不重构、不顺手清理、不改无关文件；每条 worker 发言允许非流式（结果粒度）。
7. 降级与健壮性：子任务失败也要发一条含错误摘要的 worker room_speech；空分工时 Manager 直接正常回答（仍是一条 room_speech）。

### 测试与验证（全部通过才算完成）

- 后端：在 `tests/unit/` 新增测试（mock LLM 与 `run_parallel_subagents`）：参数优先级、关键词开/关/防误触、Manager 输出解析四种形态、0/2/5 个 assignments 的事件序列与落库、worker 失败分支。运行 `pytest tests/unit -k overdrive`（或你放置测试的对应路径）全绿，且不破坏既有测试（跑一遍相关 chat 测试）。
- 前端：查看 `frontend/package.json`，跑 typecheck（vue-tsc/tsc）与 `npm run build` 通过。
- 最后输出：改动文件清单 + 每条契约的实现位置（文件:行号）+ 测试结果摘要。

### 禁止事项

- 禁止改 `integrations/agentteams/`、`deploy/`、alembic 迁移（第一期不需要任何迁移）。
- 禁止引入新依赖。
- 禁止在 Manager/子 agent 路径暴露 `parallel_subagents`、`create_agentteams_case` 等控制工具（防递归，parallel_subagent_service 有 C1–C7 约束，保持不动）。
- 禁止 git commit/push 等任何 git 写操作。

开始吧。完成后按"测试与验证"要求的格式汇报。
