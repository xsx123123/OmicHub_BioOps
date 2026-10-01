# OmicHub 的 Session 管理与长期科研任务机制

> 2026-09-23 代码走查笔记。路径均相对仓库根目录。

## 1. 会话建模：`chat_sessions` 为纲的持久化模型

核心表在 `src/cygnusx/infrastructure/database/models/chat.py`：

- **`ChatSessionModel`** (`chat.py:32`, 表 `chat_sessions`)——对应 Cherry Studio 的 Topic 概念。关键字段：
  - `session_id`（业务 ID，unique）+ `user_id` / `project_id` / `assistant_id` / `agent_id` / `model_id`
  - `mode`: `chat`（普通对话）/ `studio`（工作台会话，绑定沙盒 `workspace_id` + `sandbox_meta`）
  - `message_count` / `total_tokens` / **`last_settled_message_id`**（记忆结算游标，见 §3）
  - `share_token_hash` / `share_expires_at`（会话分享）
  - 级联关系 `messages`（`chat.py:75`）——删会话连带删消息
- **`ChatMessageModel`** (`chat.py:338`, 表 `chat_messages`)——消息按 `session_id` + `created_at` 索引持久化，这是**对话历史的权威存储**。
- 周边事件表：`chat_message_events`（时间线事件）、`chat_handoff_events`（Agent 转交）、`collaboration_degradation_events`。
- MAS 协作室独立一套：`mas_rooms` / `mas_room_messages` / `mas_room_runs` / `mas_room_events`（`models/mas_room.py`）。

## 2. 对话如何跨请求维持上下文

**历史是"前端传 + DB 权威"双轨**：

- 前端每次聊天把完整 `messages` 数组随 SSE 请求传给后端（`api/v1/chat.py:635` 附近的流式端点），重开会话时通过 `GET /messages`（`api/v1/chat.py:876` → `session_service.get_messages`）从 DB 回放。
- 后端发送前对 `llm_messages` 做一系列处理（`chat_service.py:3206-3311`）：
  1. **微压缩** `compact_tool_history`（`studio_micro_compaction.py`）——压缩工具调用历史
  2. `sanitize_messages` 清洗
  3. **256K 窗口保护**（`chat/runtime_support.py:301` `_compress_context_if_needed`）：估算 token 超 200K 时，把早期消息交给当前模型生成结构化摘要（强制保留分析目标、文件引用、已完成步骤、产物、待办），只留最近 10 条原文；摘要失败降级为硬截断。**这是长对话能一直续下去的关键**。
- 每轮结束后把 assistant/user 消息落库（`chat_message_events`），`message_count` / `total_tokens` / `last_message_at` 回写 session。

Agent 上下文装配在 `request_preparation.py:32` `prepare_agent_request`：按 agent_id 组装系统词/MCP 工具/技能/记忆，带 TTL 缓存（`agent_context_builder.py:98`）。

## 3. 长期记忆：Celery 异步"结算"事实到 `memory_facts`

完整的三层流水线（`infrastructure/celery_app/tasks/memory.py`）：

1. **触发**：每轮对话结束，`chat_service.py:548` `_enqueue_memory_summary` / `:580` `_maybe_enqueue_memory_settle` 按阈值（`memory_settle_min_new_messages`）投递 Celery 低优先级任务（countdown=5s）。
2. **增量抽取** `settle_session_memory`（`memory.py:225`）：
   - 用 `last_settled_message_id` 游标只取**新消息区间**，`memory_settlements.range_key` 保证幂等
   - LLM 按严格 prompt 抽取"值得跨会话保留的事实"（持久偏好/项目事实/重要决定，≤200 字符，禁代词、禁密钥）
   - 写入 `memory_facts`（pgvector embedding，`fact_store.py:68` `PostgresFactStore`），并推进 session 游标
3. **召回**：`agent_memory_service.py:163` `search_memory`——pgvector 语义召回 + **两路合并**（共享分区 `agent_id=""` 的 profile/preference 优先 + 当前 Agent 分区，去重），供跨会话注入。

另有 `migrate_legacy_memories`（旧记忆迁 v2）和 `backfill_embeddings` 兜底任务。AgentTeams 合成会话被双保险排除，不进记忆通道。

## 4. 长期任务（科研 pipeline 级）：LangGraph checkpoint + 权威账本双轨

明确的架构决策（`infrastructure/execution/checkpointer.py:3` 引用 P0 文档）：**checkpoint 只作图执行恢复载体，业务状态表才是权威账本，禁止第二套状态存储**。

- **Checkpointer**：`postgres_checkpointer()`（`checkpointer.py:41`）——AsyncPostgresSaver 复用主 Postgres 库，`setup()` 幂等建 checkpoints 系列表；测试用 `InMemorySaver`。
- **Overdrive（长科研任务）**：`overdrive_runs` / `overdrive_events` / `overdrive_commands` / `overdrive_task_results` 表为权威账本（`models/overdrive.py`），编排图挂 checkpoint 恢复；每轮 turn 走 `chat_service.py:848` `_run_overdrive_turn`，产物落 `output/overdrive/{session_id}/{run_id}/`。
- **MAS 协作室**（`mas/mas_room_service.py`）：图挂 AsyncPostgresSaver，`thread_id = run_id`（`mas_graph.py:5`）：
  - `plan_review` 节点 interrupt 挂起，run 进入 `awaiting_review`（`:419`）
  - 人工决议落 `mas_room_events` 账本后 `Command(resume=decision)` 从 checkpoint 恢复（`:279` `_resume_run`）
  - `start_or_resume_run`（`:330`）实现**断点续跑**：有活跃 run 直接 resume，否则新起
- Studio 会话绑定沙盒工作区（`workspace_id`），产物跨会话留存。

## 5. 多运行时统一入口

`chat/runtimes/` 下有 `legacy` / `langgraph` / `overdrive` / `studio` / `direct_chat` 五个 Runtime，由 `delegating_runtime.py` 分发——注意：**副作用（工具落库/timeline）必须 legacy 和 langgraph 两边都改**，否则普通 chat 重开后丢卡片。

## 一句话总结

**短期靠前端传完整 messages + DB 权威消息表 + 256K 自动摘要压缩；中期靠 `memory_facts` 的 Celery 异步事实结算与 pgvector 召回；长期任务靠 LangGraph Postgres checkpoint 恢复 + `overdrive_runs`/`mas_room_events` 权威账本 + interrupt/resume 人工介入。**
