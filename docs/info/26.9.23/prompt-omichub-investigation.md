# 调查提示词 · OmicHub（cygnusx）仓库：现状上下文管线与压缩嫁接点调查

> 使用方法：把 `<OMICHub_REPO_ROOT>` 替换为 OmicHub（cygnusx）仓库的绝对路径后，整段投喂给调查 Agent。

---

## 背景与目标

我是 OmicHub 平台的维护者，计划把 openai4s 的长对话上下文压缩框架（token 估算触发、超大输出外化、head/tail 保留 + 中段滚动摘要 + 结构化 handoff、归档持久化、双熔断）迁移进本平台。OmicHub 已有一套自己的上下文维持机制（256K 窗口保护压缩、memory_facts 异步结算、LangGraph checkpoint），但目前只掌握到入口行号，**现有管线的实际行为、多 runtime 覆盖情况、前后端一致性模型这些关键约束尚未确认**。

本次调查目标：彻底摸清现状，产出一份"嫁接点清单"——确定 openai4s 的压缩框架应该挂在 OmicHub 现有管线的哪个位置、替换哪段、避开哪些坑。

已知骨架信息（2026-09-23 代码走查，路径相对仓库根目录，供定位，不要重复调查）：

- `src/cygnusx/infrastructure/database/models/chat.py` —— `ChatSessionModel` (:32) / `ChatMessageModel` (:338)，`last_settled_message_id` 记忆结算游标
- `api/v1/chat.py:635` —— 流式端点（前端每次传完整 messages 数组）；`:876` —— `GET /messages` 重放
- `chat_service.py:3206-3311` —— 发送前处理管线（compact_tool_history → sanitize → 256K 压缩）；`:548` / `:580` —— 记忆结算触发；`:848` —— `_run_overdrive_turn`
- `chat/runtime_support.py:301` —— `_compress_context_if_needed`（256K 窗口保护）
- `chat/studio_micro_compaction.py` —— `compact_tool_history`
- `chat/request_preparation.py:32` —— `prepare_agent_request`；`agent_context_builder.py:98` —— TTL 缓存
- `infrastructure/celery_app/tasks/memory.py:225` —— `settle_session_memory` 增量事实结算
- `agent_memory_service.py:163` —— `search_memory` 两路合并召回
- `infrastructure/execution/checkpointer.py:41` —— Postgres checkpointer
- `chat/runtimes/` —— legacy / langgraph / overdrive / studio / direct_chat 五个 Runtime，注意副作用需 legacy 与 langgraph 同步修改
- 周边表：`chat_message_events` / `chat_handoff_events` / `collaboration_degradation_events` / `mas_rooms` / `mas_room_messages` / `mas_room_runs` / `mas_room_events` / `overdrive_runs` / `overdrive_events` / `overdrive_commands` / `overdrive_task_results` / `memory_facts` / `memory_settlements`

## 调查任务

### A. 现有压缩与上下文装配管线（把黑盒打开）

1. **`_compress_context_if_needed` 完整实现**（`chat/runtime_support.py:301`）：token 估算方法（用什么估算器？CJK 怎么处理？）；触发阈值的确切数值与来源（硬编码 200K？可配置？配置键名）；交给当前模型生成结构化摘要的 **prompt 全文**；强制保留的规则（"分析目标、文件引用、已完成步骤、产物、待办"具体如何实现）；只留最近 10 条原文的代码；摘要失败的降级硬截断具体行为；该函数是否区分 mode / runtime 走不同分支。
2. **`compact_tool_history` 微压缩**（`chat/studio_micro_compaction.py`）：触发条件、压缩策略、对哪些消息生效、与主压缩 `_compress_context_if_needed` 的先后关系与叠加效果。
3. **发送前处理管线全链路**（`chat_service.py:3206-3311`）：每一步的函数名、输入输出、执行顺序；`sanitize_messages` 的清洗规则清单。
4. **Agent 上下文装配**（`request_preparation.py:32` + `agent_context_builder.py:98`）：系统词 / MCP 工具 schema / 技能 / 记忆各自以什么格式、插在 `llm_messages` 的哪个位置；TTL 缓存的键与失效策略——压缩后这些"重建型上下文"在哪一步重新注入。

### B. 多 Runtime 覆盖情况（关键）

5. **五个 runtime 各自的上下文路径**：legacy / langgraph / overdrive / studio / direct_chat 是否都经过 `_compress_context_if_needed`？哪些有独立的消息装配逻辑？
6. **Overdrive 长科研任务**：`_run_overdrive_turn`（`chat_service.py:848`）的每一轮是否走压缩管线？长 run 几十轮后上下文如何维持？
7. **MAS 协作室**：`mas_room_service.py` 的图执行中，消息如何装配进 LLM 请求，有没有压缩；`plan_review` interrupt / resume 恢复后上下文如何重建。
8. **副作用覆盖确认**：现有压缩是否在任何地方落库或写时间线事件？结合已知警告"副作用必须 legacy 和 langgraph 两边都改"，确认压缩相关副作用的现状覆盖缺口。

### C. 消息一致性模型（与 openai4s 架构的最大差异点）

9. **重放语义**：`GET /messages`（`api/v1/chat.py:876` → `session_service.get_messages`）返回的是 DB 中的完整原文，还是压缩后的视图？压缩投影是否在任何环节持久化？
10. **前端双轨**：前端每次请求携带完整 messages 数组——压缩发生在服务端后，前端本地维护的 messages 与服务端 DB 的完整历史是否会产生一致性偏差（多端、刷新、重开场景）？share_token 分享会话的内容取自哪里、压缩后语义是什么？
11. **事件时间线扩展性**：`chat_message_events` 的表结构与事件类型枚举；如果要在时间线上记录 compaction 事件（压缩时机、节省 token 数、归档指针），现有事件机制能否直接扩展，需要改哪些地方。

### D. 记忆与长期机制交互

12. **Memory 注入点**：`search_memory`（`agent_memory_service.py:163`）的召回结果以什么格式、在哪一步注入 `llm_messages`（系统词内？消息数组？）；压缩投影会不会把已注入的记忆事实吃掉——请从代码路径上确认。
13. **记忆结算与压缩的互补点**：`settle_session_memory`（`memory.py:225`）的 `last_settled_message_id` 游标机制；如果引入 openai4s 式压缩，被压缩出窗口的内容是否仍能进入记忆结算通道（游标推进是否依赖消息在窗口内）。
14. **Checkpoint 与压缩的关系**：`postgres_checkpointer()` 的 checkpoint 里保存的消息快照内容；overdrive / MAS 的 interrupt-resume 恢复时，上下文是直接用 checkpoint 快照还是会重新走一遍压缩管线——两者结合会不会导致恢复的上下文与中断前不一致。

### E. 配置、估算与配额

15. **每模型上下文窗口来源**：`context_window` 或等价字段在哪个配置/模型表里；256K 是否硬编码；哪些模型有不同窗口。
16. **Usage 统计与校准**：`total_tokens` 如何统计；有没有把 provider 返回的真实 usage 回写用于校准估算（openai4s 有 ratio 自校准闭环，确认本平台现状）。
17. **相关阈值清单**：`memory_settle_min_new_messages` 等所有与长对话维持相关的配置键——名称 / 默认值 / 定义文件。

## 输出格式要求

- 中文输出，所有结论标注 `文件路径:行号` 证据；不确定的明确标"未确认"，不要臆测。
- 产出一张 **ASCII 现状管线流程图**：从"前端请求 → 服务端装配 → 压缩处理 → LLM 调用 → 落库/事件"的完整数据流，标注五个 runtime 的分叉点。
- 最后产出 **压缩嫁接点清单**：列出 3-5 个引入 openai4s 式压缩框架的候选挂载点（函数/层），每个给出：接入方式、需要同步修改的副作用点（对照 legacy/langgraph 双改警告）、主要风险。
- 单独一节列出**与 openai4s 架构冲突、迁移前必须做决策**的问题（如：压缩视图是否落库、重放语义、前端契约是否变更）。
