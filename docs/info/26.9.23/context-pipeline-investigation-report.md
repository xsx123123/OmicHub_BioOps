# OmicHub 上下文管线现状调查报告与 openai4s 压缩框架嫁接点清单

> 调查日期:2026-09-23。对应调查任务:`docs/info/26.9.23/prompt-omichub-investigation.md`。
> 所有结论标注 `文件路径:行号` 证据;未确认处已明确标注,无臆测。

---

## A. 现有压缩与上下文装配管线

### A1. `_compress_context_if_needed` 完整实现
`src/cygnusx/application/services/chat/runtime_support.py:301-364`

| 项 | 结论 | 证据 |
|---|---|---|
| token 估算 | `_estimate_messages_tokens`:`sum(len(text)//2 + 4)`,中英混合按 **2 字符≈1 token** 的静态口径。**无 CJK 特判、无自校准** | runtime_support.py:296-299 |
| 触发阈值 | **类常量硬编码 200_000** tokens(`_CONTEXT_COMPRESS_THRESHOLD_TOKENS = 200_000`,注释称"256K 窗口预留输出/系统词/工具定义空间"),不可配置;另需 `len(messages) > keep+2`(12 条) | runtime_support.py:284-287,313 |
| 摘要 prompt | 原文:*"请将以下对话历史压缩为一份结构化摘要,必须保留:用户的分析目标与需求、关键数据文件引用（file_id / 文件名 / 路径）、已完成的分析步骤与结论、生成的产物（图表/文件）、以及未完成的待办事项。"*,system: *"你是对话压缩器,只输出摘要本身,不超过 1500 字。"*,`max_tokens=2048` | runtime_support.py:332-341 |
| 强制保留实现 | **仅靠 prompt 措辞**,无结构化抽取/校验 | runtime_support.py:333-336 |
| 压缩输入 | 早期消息仅取 `_message_text(m)[:2000]`(每条截 2000 字符)拼 digest | runtime_support.py:316-321 |
| 保留原文 | `old, recent = messages[:-keep], messages[-keep:]`,`keep=_CONTEXT_KEEP_RECENT_MESSAGES=10` | runtime_support.py:287,316 |
| 摘要载体 | 压缩结果 = **一条 role=system 的摘要消息 + 最近 10 条原文**(`[早期对话已压缩为摘要,后续请基于摘要与最近对话继续]`) | runtime_support.py:350-355 |
| 失败降级 | 摘要调用异常 → `logger.warning` 后**硬截断:保留首条 user 消息 + 最近 10 条** | runtime_support.py:346-347,361-364 |
| 摘要模型 | 复用**当前请求的 model_config**(经 `provider_manager.chat_stream`) | runtime_support.py:324-327 |
| mode/runtime 分支 | **不区分**——单一实现,所有调用方同一行为 | runtime_support.py:301-364 |

### A2. `compact_tool_history` 微压缩
`src/cygnusx/application/services/studio_micro_compaction.py:21-52`

- 触发:`threshold_chars`(**YAML 可配,默认 4000**,范围 500–100K,`StudioMicroCompactionConfig`)`src/cygnusx/infrastructure/config/studio_loader.py:183-186`。
- 策略:**非 LLM 的确定性压缩**——只压历史 assistant 消息 `metadata.tool_invocations` 里结果 JSON 超过 threshold 的项:>100 行保留首尾各 50 行,否则保留首尾各 threshold/2 字符;跳过 `ask_user`、用户消息、最后一条消息;有 path 时附"完整内容见工作区文件 {path}"。studio_micro_compaction.py:9-52。
- 顺序:**先微压缩、后 sanitize、再(多模态注入/技能/文件上下文)、最后主压缩**(见 A3),两者叠加。

### A3. 发送前处理管线全链路
`chat_service.py:3205-3321`(在 `_stream_agent_chat_inner` 内,`chat_service.py:2582` 起):

1. `compact_tool_history(messages, history_threshold)` — 工具输出微压缩(`chat_service.py:3206-3207`)
2. `sanitize_messages(...)` — 敏感词脱敏,规则:`settings.sensitive_keywords`(env `SENSITIVE_KEYWORDS` 逗号分隔),大小写不敏感联合正则,**不可逆替换为 [REDACTED]**,只处理 str content(`src/cygnusx/core/sanitizer.py:39-53`)(`chat_service.py:3208-3217`)
3. `@` 技能上下文注入到 `llm_messages[-1]`(每技能 prompt 截 12000 字符,`chat_service.py:3218-3246`)
4. star_command 模式/权限规则注入(`chat_service.py:3247-3270`)
5. Studio:`_link_session_files_to_workspace` 幂等软链附件(`chat_service.py:3282-3285`)
6. `_build_multimodal_messages` 附件多模态注入(`chat_service.py:3287-3291`;runtime_support.py:366-439)
7. `_collect_session_file_context` 历史文件引用注入 → `_append_context_to_last_user_message`(**仅改送 LLM 视图,不落库**,runtime_support.py:254-280)(`chat_service.py:3293-3306`)
8. `_compress_context_if_needed`(**256K 主压缩**,`chat_service.py:3310`)→ 压缩时 yield `context_compressed` ChatChunk(`chat_service.py:3313-3321`)

### A4. Agent 上下文装配
`request_preparation.py:32-100` + `agent_context_builder.py:98-159` + `agent_service.assemble_context`(`agent_service.py:802-1031`)

- 系统词:Agent system_prompt + Persona + 技能 L1 索引(name+description,约 100 tokens/技能)+ cygnusx-tools hint + 各后缀(记忆/交接/ask_user 等)拼接,`agent_service.py:996-1020`;记忆工具后缀在 chat_service.py:3464-3476 二次追加。
- MCP 工具 schema:OpenAI function 格式进 `tools` 数组(**不是**系统词/消息),白名单过滤 + 预设兜底,`agent_service.py:847-977`。
- 技能:L1 索引进系统词,L2 `use_skill` 按需加载,L3 `skill_resource`(`agent_service.py:998-1004`)。
- 记忆:**无主动注入**——记忆以 `cygnusx_search_memory` 工具形式由模型检索(见 D1)。
- TTL 缓存:`AgentContextBuilder._cache`(类级 dict),键 `(agent_id, user_id, mode, sha256(user_message))`,TTL `agent_context_cache_ttl_seconds=60`(`core/config.py:41`;agent_context_builder.py:108-158)。缓存的是**装配件**(系统词/工具),与消息历史无关;压缩后无需重注入装配件,下一轮 `assemble()` 自然重新装配。

## B. 多 Runtime 覆盖情况

### B1. 五个 runtime 的上下文路径(ASCII 图见文末)

关键事实:**`_compress_context_if_needed` 全仓只有一处调用**(`chat_service.py:3310`),位于 `_stream_agent_chat_inner` 的 step 4.2,在 runtime 分流点(`chat_service.py:4064-4133`)**之前**。因此:

| Runtime | 经主压缩? | 说明 |
|---|---|---|
| legacy(手写循环) | ✅ | 走 `_stream_agent_chat_inner` 全管线(仅 `features.engine=="legacy"` 或逃生舱 `chat_force_legacy_runtime` 时,`chat_service.py:4097-4133`) |
| langgraph(普通聊天默认) | ✅ | 同上,`llm_messages` 压缩后传入 `LangGraphChatRuntime._stream_agent_chat_langgraph`(`chat_service.py:4107-4112`;langgraph_runtime.py:277-288) |
| studio | ✅ | Studio 会话继续走同管线到 studio 循环(`chat_service.py:4131` 起) |
| overdrive | ❌ **旁路** | `_run_overdrive_turn` 在 step 3 之后、step 4 管线之前分流(`chat_service.py:2937-2946`),**完全不过压缩**;长 run 靠任务级结构维持:上游摘要 `build_upstream_context`(每任务摘要 1500 字/上游总 8000 字,`overdrive_runtime.py:19-21,308-333`)+ 结果落 `overdrive_task_results` 表(`models/overdrive.py:104-128`)+ manifest 读回。几十轮主链上下文靠 intake/followup 状态机(`chat_service.py:910-948`),规划 prompt 单次组装不滚压 |
| direct_chat(星尘 AI 助手) | ❌ 旁路 | `direct_chat_runtime.stream` 自行装配,只有 `sanitize_messages`,**无 token 压缩**(`direct_chat_runtime.py:196-200`)。另有一条旧版 `ai_service` 路径按 `ai_max_context_messages=20` 条数截断(非 token,`ai_service.py:175-176`;`domain/ai/services.py:62-68`;`entities.py:30-35`) |

MAS 协作室:独立链路。`_execute_run` 从 `mas_room_messages` 取 **limit=50** 条历史,trace/plan_card 转 system 后作为图初始 messages,无压缩(`mas/mas_room_service.py:386-403`);resume 时 `graph.ainvoke(Command(resume=...))` 直接用 checkpoint 状态续跑,不重建消息、不压缩(`mas_room_service.py:309-317`)。

### B2. 副作用覆盖
- 压缩**唯一副作用**是流内 `context_compressed` ChatChunk(`chat_service.py:3313-3321`),前端 `useAgentChatStream.ts:1074-1076` → `agentHub.ts:2635-2637` 显示一条提示。**不落库、不写 `chat_message_events`/`chat_handoff_events`、无归档指针**——被压缩内容直接丢弃,无任何持久化痕迹。
- 因为压缩在 runtime 分流前,legacy/langgraph 天然共享,当前无双改缺口;但任何压缩副作用若要落库,需注意 langgraph 路径落库走 `persistence_support` 而 legacy 走各自分支。

## C. 消息一致性模型

### C1. 重放语义
- `GET /messages`(`api/v1/chat.py:876-886`)→ `session_service.get_messages`(`session_service.py:167-173`):**直接 select 全部消息原样返回 DB 完整原文**。压缩只存在于单次请求的 `llm_messages` 视图,**投影从不持久化**——重放/刷新后又是完整历史。
- `ChatMessageModel` 无任何压缩相关字段(仅 `last_settled_message_id` 记忆游标,`models/chat.py:57`)。

### C2. 前端双轨
- 前端每轮携带 `session.messages` 过滤后 `slice(-contextLength)`(**默认 20 条,用户可调**,`chat.ts:27`;`agentHub.ts:2128-2132`)的 apiMessages——**前端已经在做条数级截断**,服务端 200K token 压缩只对超长单条内容/后端追加的注入文本兜底。
- 服务端压缩后**前端不感知被丢弃内容**:前端本地与 DB 完整历史本就偏差(前端只发最近 20 条),刷新时 `loadSessionMessages` 用 DB 原文整体替换(`agentHub.ts:1620-1665`)。多端/重开语义 = DB 完整历史;**服务端引入压缩若不改前端契约,重开后前端仍会带完整(前端视图)历史,服务端每轮重新压缩,不产生新偏差**——压缩是请求级瞬态。
- 分享:Studio 分享 `build_shared_snapshot` 读 DB 消息原文构建快照(`studio_sharing.py:79-133`,端点 `api/v1/studio.py:323-327`),`share_token_hash` 存 `chat_sessions`(`models/chat.py:67`)。压缩后分享语义不变(仍原文)。

### C3. 事件时间线扩展性
- `chat_message_events` 结构:`(message_id, seq)` 联合主键 + `event_type String(50)` + `payload JSONB`,**append-only**(`models/chat.py:378-395`)。当前唯一 event_type 是 `tool_output`(`chat_message_event_service.py:35`)。
- 扩展 compaction 事件:**表结构无需迁移**(event_type 是自由 String、payload 是自由 JSONB),新增如 `context_compacted` 类型即可;需改:`chat_message_event_service.py` 加 append 入口(现有 `append_tool_output:65-99` 为样板)、发送管线调用点、以及历史重建 `load_replay`(`chat_message_event_service.py:191-225`,目前过滤只认 tool_output,不会误读新类型)。注意该表按 message_id 挂在**消息**下,compaction 是会话级事件,要么挂到本轮 ai_message_id,要么另用 `chat_handoff_events` 式独立表(`models/chat.py:436-461` 是会话级事件的现成范式)。

## D. 记忆与长期机制交互

### D1. Memory 注入点
- 召回:`agent_memory_service.search_memory`(`agent_memory_service.py:159-184`),v2 双路合并(共享分区 agent_id="" + 当前 Agent 分区,pgvector)。**没有主动预注入**——调用方是 `agent_memory_tool_service.py:103-113` 等工具包装,即记忆以 `cygnusx_search_memory` **工具**形式暴露,由模型按需调用;系统词只有使用纪律后缀 `MEMORY_SYSTEM_PROMPT_SUFFIX`(`chat/configuration.py:183-189`,挂载点 `chat_service.py:3464-3476`)。
- **压缩不会吃掉记忆**:记忆不在消息数组里,压缩只截/摘要 messages;压缩后模型仍可随时调 `cygnusx_search_memory` 重新召回。

### D2. 记忆结算与压缩的互补性(重要好消息)
- `settle_session_memory`(`celery_app/tasks/memory.py:225-343`)从 **DB 全量消息**select(`memory.py:260-265`),游标 `last_settled_message_id` 按 `message_id` 在 DB 序列中定位起点(`memory.py:267-271`),幂等键 `range_key`(`memory.py:277-281`)。
- **游标推进完全不依赖消息在 LLM 窗口内**——它读的是 DB 不是 llm_messages。因此 openai4s 式压缩把旧消息挤出窗口后,只要消息仍落库(现状落库完整原文),记忆结算通道**零影响**。压缩框架若改为"服务端持久化压缩视图",才需要保证 settle 读的是原文层。

### D3. Checkpoint 与压缩
- `postgres_checkpointer`(`infrastructure/execution/checkpointer.py:41-60`)是 **AsyncPostgresSaver**,仅用于 MAS 协作室图(`mas_room_service.py:309,405`)与 orchestrator langgraph 图(`chat_service.py:5686,6290`;`api/v1/chat.py:132-140`)。P0 决策明确:**checkpoint 只作图恢复载体,overdrive_runs/overdrive_events 是权威账本,禁止第二套业务状态存储**(`checkpointer.py:3-9`)。
- 普通 chat(langgraph runtime)的 ReAct 循环**不用** checkpointer——每轮由前端重传 messages,无跨请求快照。
- MAS interrupt→resume:`Command(resume=)` 从 checkpoint 恢复含 messages 的图状态,**不重新过任何压缩管线**(`mas_room_service.py:309-317`)。若对 MAS 引入压缩,恢复后上下文 = checkpoint 快照(未压缩),会与"若曾压缩"不一致——即 MAS 压缩必须做成"每轮输入压缩、checkpoint 存压缩后状态"或干脆不动 MAS。

## E. 配置、估算与配额

### E1. 每模型上下文窗口来源
- **没有 context_window 字段**。`ai_provider_configs` 表只有 `max_tokens`(默认 2048,输出上限,`models/ai_provider.py:29`)。256K 窗口是 `_CONTEXT_COMPRESS_THRESHOLD_TOKENS=200_000` 的**单点硬编码**假设(runtime_support.py:285),所有模型共用;全局 grep 无 262144。不同模型仅 `max_tokens` 不同(`data/ai/*.yaml`:agent 65536、provider 8192 等)。
- **迁移决策点**:openai4s 按模型窗口触发,本平台需先给 `ai_provider_configs` 加 `context_window` 列(或 extra_params 键)。

### E2. Usage 统计与校准
- provider 真实 usage 统一归一化:`normalize_token_usage`(prompt/completion/total/cached,兼容多字段名与缓存命中,`openai_compatible.py:158-186`)。
- 回写链:每次调用 → `record_ai_call` 内存缓冲异步刷 `ai_metrics` 表(`core/ai_metrics.py:30-55`;`models/ai_metric.py:28-30` 有 prompt_tokens/total_tokens),供管理端统计;会话费用用真实 usage + 四档单价(`models/ai_provider.py:26-29`,前端 `tokenCost.ts`)。
- **无 ratio 自校准闭环**:token 估算是纯静态 `len//2+4`,真实 usage 只进统计,从不反哺估算器。openai4s 的校准闭环是纯增量。

### E3. 阈值清单(全部在 `src/cygnusx/core/config.py` 及局部)

| 键 | 默认值 | 定义 | 用途 |
|---|---|---|---|
| `_CONTEXT_COMPRESS_THRESHOLD_TOKENS` | 200_000 | runtime_support.py:285(硬编码) | 256K 压缩触发 |
| `_CONTEXT_KEEP_RECENT_MESSAGES` | 10 | runtime_support.py:287(硬编码) | 保留原文条数 |
| `micro_compaction.threshold_chars` | 4000(500–100K) | studio_loader.py:183-186(YAML) | 工具输出微压缩 |
| `agent_context_cache_ttl_seconds` | 60 | core/config.py:41 | 装配 TTL |
| `memory_settle_min_new_messages` | 4(下限 4) | core/config.py:160 | 结算最小新增消息 |
| `memory_v2_enabled` | False | core/config.py:158 | 记忆 v2 开关 |
| `memory_extraction_model` | qdoubao-seed-evolving | core/config.py:161 | 事实抽取模型 |
| `ai_max_context_messages` | 20 | core/config.py:246 | 旧版 ai_service 条数截断 |
| `contextLength`(前端) | 20 | chat.ts:27 | 前端发送条数 |
| `chat_force_legacy_runtime` | False | core/config.py:37 | legacy 逃生舱 |
| `orchestrator_engine` | legacy | core/config.py:172 | MAS 编排引擎 |
| overdrive limits(summary 1500/upstream 8000/task_instruction 20000/max_tasks 12…) | — | overdrive_runtime.py:14-24 + `data/ai/_overdrive_limits.yaml` | 超频任务级上下文 |

---

## ASCII 现状管线流程图

```
前端请求 (每轮携带 session.messages.slice(-contextLength=20)  ← 前端条数截断
   agentHub.ts:2128-2132, 2198)
        │
        ▼
POST /chat/stream (api/v1/chat.py:635)
        │
        ▼
ChatService._stream_agent_chat_inner (chat_service.py:2582)
        ├─ 2.5 overdrive? ───────────────────────────────► _run_overdrive_turn (:2937)
        │        [❌不过压缩]  长run维持= 上游摘要 build_upstream_context
        │        (overdrive_runtime.py:308-333) + overdrive_task_results 表
        │        + overdrive_runs/events 权威账本; ❌旁路 → return
        │
        ├─ MAS orchestrator? ────────────────────────────► _stream_orchestrator_langgraph (:4081)
        │        [❌不过压缩,分流在压缩之后但独立组装] → return
        │
        ├─ prepare_agent_request (request_preparation.py:32)
        │      └─ AgentContextBuilder.assemble [TTL 60s 缓存: 系统词/工具schema/技能L1]
        │           (agent_context_builder.py:98-158; agent_service.py:802-1031)
        │
        ├─ step 4 发送前管线 (chat_service.py:3205-3321)
        │      1. compact_tool_history 微压缩 (studio_micro_compaction.py:21)
        │      2. sanitize_messages 脱敏 [REDACTED] (core/sanitizer.py:39)
        │      3-7. 技能@ / star_command / Studio附件软链 / 多模态 / 历史文件上下文
        │           (注入 llm_messages, 仅视图不落库)
        │      8. _compress_context_if_needed ★唯一压缩点 (runtime_support.py:301)
        │           估算 len//2+4 > 200_000 (硬编码) ?
        │             ├─ 是 → LLM摘要(prompt强制保留目标/文件/步骤/产物/待办)
        │             │        → [system摘要] + 最近10条   [❌不落库❌无归档]
        │             │        └─ 摘要失败 → 硬截断: 首条user+最近10条
        │             └─ 否 → 原样
        │      └─ yield context_compressed ChatChunk (:3313) ──► 前端提示条
        │                 (useAgentChatStream.ts:1074 → agentHub.ts:2635)
        │
        ├─ runtime 分流 (chat_service.py:4064-4133)
        │      ├─ langgraph (默认) ──► _stream_agent_chat_langgraph (:4107)
        │      │      [✅吃压缩后的 llm_messages; ReAct循环不用checkpointer]
        │      ├─ legacy (engine=legacy / 逃生舱) ──► 手写循环 (:4133+)
        │      │      [✅同吃; 与langgraph双路径,副作用需两边同步]
        │      └─ studio ──► studio 循环 (:4131+)
        │             [✅同吃; 工具路由沙盒]
        │
        ├─ direct_chat (星尘AI助手, 独立入口 direct_chat_entrypoint.py:17)
        │      [❌旁路: 自行装配, 仅脱敏无token压缩 (direct_chat_runtime.py:196-200)]
        │      旧版 ai_service 另有条数截断20 (ai_service.py:175)
        │
        ▼
LLM 调用 (真实 usage → normalize_token_usage → ai_metrics 表; 无ratio校准)
        │
        ▼
落库: chat_messages 完整原文 (压缩投影不持久化)
      chat_message_events (仅tool_output, append-only) / chat_handoff_events
      GET /messages 重放 = DB 原文 (session_service.py:167) → 前端整体替换
      分享 = DB 原文快照 (studio_sharing.py:79)

侧链: memory settle (每N条/删会话触发, celery)
      └─ 读 DB 全量消息, last_settled_message_id 游标 (memory.py:260-271)
         [✅与压缩解耦: 压缩挤窗口不影响结算]

旁链: MAS 协作室 (独立链路, mas_room_service.py:365-418)
      └─ 历史limit=50 → MAS 图 (postgres_checkpointer)
         interrupt→resume 用 checkpoint 快照续跑 [❌不过压缩]
```

---

## 压缩嫁接点清单(候选挂载点)

### 候选 1:扩展 `_compress_context_if_needed`(推荐首选,替换式升级)
- **位置**:`chat/runtime_support.py:301-364`
- **接入方式**:保留函数签名 `(messages, model_config) -> (messages, compressed, tokens_before)`,内部替换为 openai4s 框架:token 估算器换成可校准估算(CJK 比率 + usage 回写 ratio)、超大输出外化(对齐已有 `compact_tool_history` 的"完整内容见工作区文件"模式)、head/tail 保留 + 中段滚动摘要 + 结构化 handoff、归档持久化、双熔断。阈值改为读 `model_config.context_window`(需新增配置,E1)。
- **需同步修改**:阈值/保留数从类常量改为配置;压缩副作用(归档指针)若落库,legacy/langgraph/studio 三分支都要能看到(压缩点在分流前,天然共享,风险低);前端 `context_compressed` 事件 payload 可扩展节省 token 数(向后兼容,`useAgentChatStream.ts:1074` 已按字段取值)。
- **主要风险**:`get_messages` 重放/分享仍是原文——压缩视图瞬态,多端语义安全(见 C2);摘要模型复用当前模型,失败降级路径必须保留(现状已有,346-364)。

### 候选 2:请求级归档持久化——新增 `chat_compaction_events` 或扩展 `chat_message_events`
- **位置**:`chat_message_event_service.py`(+ 迁移;或仿 `ChatHandoffEventModel` `models/chat.py:436` 新表)
- **接入方式**:压缩发生时把(压缩时机、tokens_before/after、归档指针、被压缩消息 id 区间)写入事件;`load_replay` 只认 tool_output 所以不会误读,新类型可直接加。
- **需同步修改**:新表需迁移(注意本仓多 head 分叉须 mergepoint);归档存储选型(建议复用 Studio 工作区/MinIO turn_record 模式,`agentteams_data_tool_service.py:175` 的 max_bytes 读取是现成范式)。
- **主要风险**:写入失败不能阻断聊天(对齐现有"静默降级+WARNING"但要有日志);append-only 表无法更新,压缩事件只能追加。

### 候选 3:direct_chat runtime 补齐压缩
- **位置**:`chat/runtimes/direct_chat_runtime.py`(step 4 前)与旧版 `ai_service.py:175`
- **接入方式**:候选 1 的函数提为模块级纯函数后,在 direct_chat_runtime 装配后调用一次;顺手把旧版 `ai_max_context_messages=20` 条数截断统一到 token 口径。
- **需同步修改**:direct_chat 无 Agent 装配,`model_config` 来自 `ai_provider_configs`,需 context_window 字段;星尘会话落库同 `chat_messages`,无额外副作用。
- **主要风险**:direct_chat 是轻量入口,引入 LLM 摘要会增加延迟;可对短会话(<阈值)保持直通。

### 候选 4:overdrive 长任务上下文滚压
- **位置**:`chat_service.py:848 _run_overdrive_turn` 的 intake/followup 与 `build_upstream_context`(`overdrive_runtime.py:308-333`)
- **接入方式**:openai4s 的"中段滚动摘要 + 结构化 handoff"嫁接到 overdrive 的 session_meta 状态机(`chat_service.py:926-937`),替代现在仅靠 1500/8000 字符摘要链。
- **需同步修改**:**不能动 overdrive_runs/overdrive_events 权威账本**(checkpointer.py:3-9 P0 决策);压缩只能作用于组装给 LLM 的 prompt,状态账本照旧。
- **主要风险**:overdrive 已有成熟的任务级上下文纪律,收益边际;改动波及 `data/ai/_overdrive_limits.yaml` 消费方,建议放最后。

### 候选 5:MAS 协作室消息压缩(谨慎/暂缓)
- **位置**:`mas/mas_room_service.py:386-403`(`_execute_run` 的 initial_messages 组装,limit=50)
- **接入方式**:对超过 token 阈值的房间历史在组装时压缩。
- **需同步修改**:resume 路径(`mas_room_service.py:280-317`)用 checkpoint 快照续跑,必须保证"中断前压过的状态"与"恢复后组装"一致——即压缩需进入图状态而非仅输入组装;两端(mas_graph 内 supervisor/worker 各自 LLM 调用)都要覆盖。
- **主要风险**:最高。checkpoint 一致性问题(D3)、MAS 事件账本语义、以及"副作用 legacy/langgraph 双改"在 MAS 图内是 supervisor 与 worker 两处。建议首期不动 MAS。

---

## 迁移前必须做决策的问题(与 openai4s 架构冲突)

1. **压缩视图是否落库(最核心)**。现状:压缩纯瞬态,DB 恒为完整原文,`GET /messages`/分享/记忆结算全部读原文。openai4s 有归档持久化——若把"压缩后视图"落库,将同时改变重放语义(C1)、分享语义(C2)、并要求记忆结算改读原文层(D2 的解耦被破坏)。**建议决策:维持"视图压缩 + 归档外置(指针落库、原文不删)"**,与现有 `_append_context_to_last_user_message` "仅影响送 LLM 的视图,不落库" 的既定原则一致(runtime_support.py:258)。
2. **重放语义**:DB 原文重放 = 用户刷新后看到完整历史,而被压缩轮次的 LLM 实际看到的更少。是否接受"用户可见历史 ≠ 模型可见上下文"?现状已如此(前端只发 20 条),openai4s 落地不引入新冲突,但归档指针若要在 UI 展示("已压缩 N 条,点开查看归档")需扩展 C3 的事件机制。
3. **前端契约是否变更**:现状前端不重发压缩结果、每轮重建上下文,`context_compressed` 事件仅提示。openai4s 若引入"服务端会话级压缩状态",前端 20 条截断(`agentHub.ts:2130-2131`)与服务端压缩会双重压缩——需决策:前端截断保留(服务端视为兜底)还是前端改为传全量、由服务端统一压缩(改动大,影响 legacy/langgraph/studio/direct 四路)。
4. **每模型 context_window 缺失**:触发阈值无法按模型差异化,必须先加字段(表列或 extra_params)并确定存量模型默认值(现硬编码 200_000/256K 假设)。
5. **token 估算口径**:静态 `len//2+4` 与 openai4s ratio 自校准的衔接——决定是否用 `ai_metrics` 真实 usage 回写校准(数据已在表里,`models/ai_metric.py:28-30`,只差闭环),这是低风险高收益项,建议最先做。
6. **checkpoint 权威性**:P0 决策"checkpoint 只作恢复载体、业务状态以表为准"(checkpointer.py:3-9)。openai4s 压缩若想写进图状态(候选 5)会触碰这条红线——MAS 首期不动可回避。
7. **双熔断的兜底语义**:现状降级是"首条 user + 最近 10 条"硬截断(runtime_support.py:361-364);openai4s 的双熔断(摘要失败+超时/超限)需与该行为对齐或显式替换,并确认极端情况请求仍可发出、不 500。
