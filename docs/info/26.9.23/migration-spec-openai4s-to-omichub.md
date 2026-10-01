# OmicHub 上下文压缩框架迁移实施文档（openai4s → OmicHub）

> 执行者：codex。本文档是迁移实施规格，不代表所有阶段已经完成；按 §4 核对源码后，依 §6 的 P0→P5 顺序推进。
> 证据基线（2026-09-23）：OpenAI4S = `../OpenAI4S`，目标 commit `a6955de46295f01c11e6eb1b4e641104d71e145c`；OmicHub = 本仓库当前工作树。
> 依据材料（路径相对 OmicHub 仓库根）：
> - `docs/info/26.9.23/context-pipeline-investigation-report.md` —— OmicHub 现状调查与嫁接点清单
> - `../OpenAI4S/notes/prompt-openai4s-investigation.md` —— OpenAI4S 资产核对范围
> - OpenAI4S 可执行资产以 `openai4s/agent/compaction.py`、`openai4s/agent/runtime.py`、`openai4s/agent/engine.py`、`openai4s/prompts.py` 为准；commit 漂移时必须重新核对行号和行为。

---

## 1. 背景与目标

OmicHub（仓库 `cygnusx`）现有长对话维持机制为：发送前单点压缩 `_compress_context_if_needed`（`src/cygnusx/application/services/chat/runtime_support.py:301-364`）——静态 token 估算（`len//2+4`）、硬编码 200K 阈值、LLM 自由文本摘要（仅靠 prompt 措辞约束保留项）、失败硬截断、无熔断、无归档、无校准。

目标：将 openai4s 的上下文压缩框架迁移至 OmicHub，按 §6 的 P0→P5 顺序实施。核心收益：

1. token 估算可校准（CJK 正确换算 + provider 真实 usage 回写 ratio）
2. per-model 上下文窗口触发（替换硬编码 200K）
3. 原子分段 + head/tail/middle 窗口 + 滚动摘要 + 9 字段结构化 handoff（替换自由文本摘要）
4. 摘要健壮性（截断检测与双倍预算重试、防注入 prompt、输入瘦身、host 权威事实改写）
5. 治理（双熔断 + 1.5× 自愈、采纳原则：失败保留原上下文，替换硬截断降级）
6. 超大输出外化（preview + 沙盒 blob + 读回契约）
7. 压缩事件与归档留痕（`chat_message_events` 扩展，DB 原文权威不变）

## 2. 范围

### 2.1 本期内（必须完成）

P0 配置与决策落地 → P1 估算与触发 → P2 压缩核心 → P3 治理层 → P4 外化 → P5 事件与归档。

### 2.2 明确排除（不得实施）

| 排除项 | 原因 |
|---|---|
| Action Ledger `kind=compaction` group 恢复机制 | OmicHub 有 `chat_messages` DB 权威原文 + 每轮重压缩，无需事件溯源恢复。约束：若重放路径重建 handoff note，必须与运行时 note 共享同一构造常量（`COMPACTION_NOTE_PREFIX` 等价物），保证字节一致 |
| 子代理独立 context budget（delegation） | MAS 子代理场景暂缓 |
| overdrive 长任务滚压 | 已有任务级上下文纪律（上游摘要 + `overdrive_task_results`），边际收益低；`_run_overdrive_turn`（chat_service.py:848）本期不动 |
| MAS 协作室压缩 | 触碰 "checkpoint 只作恢复载体" P0 红线（checkpointer.py:3-9）与 interrupt/resume 一致性风险 |

### 2.3 约束红线（全程不得违反）

- **R1**：`chat_messages` 表永远是完整原文权威。压缩视图（投影）**不落库**；重放（`GET /messages`）、分享（`build_shared_snapshot`）、记忆结算（`settle_session_memory` 读 DB 全量消息）语义全部不变。
- **R2**：checkpoint 只作图恢复载体，禁止把压缩状态写进任何 LangGraph checkpoint（P0 决策，checkpointer.py:3-9）。
- **R3**：压缩点在 runtime 分流之前（chat_service.py:3310），legacy / langgraph / studio 天然共享；新增任何压缩副作用必须保证三分支都能看到。
- **R4**：压缩失败/被拒/归档失败时，**必须原样返回未压缩上下文继续跑**（采纳原则），绝不硬截断、绝不 500。
- **R5**：用户取消（SSE 中断）不算压缩失败，不计入熔断。

---

## 3. openai4s 架构说明（目标架构，迁移蓝本）

### 3.1 模块划分与调用链

```
engine.run() 每轮循环顶部（engine.py:88-96）
  │  state.messages[:] = prepared   ← 原地替换（engine.py:90-91）
  ▼
ContextCompactionPolicy.prepare(state)        runtime.py（编排层）
  ├── _calibration_ratio(state)               自校准 ratio（runtime.py:771-788）
  ├── _should_trigger(calibrated_total)       触发判断（runtime.py:790-802）
  ├── externalize_large_outputs()             先外化（compaction.py:947-1087）
  ├── compact()                               核心算法（compaction.py:1371-1489）
  │     ├── segment_messages / _compaction_windows   分段与窗口
  │     ├── _summary_chunk × N                滚动摘要（compaction.py:1331-1368）
  │     ├── _normalize_handoff                host 权威改写（compaction.py:1096-1152）
  │     └── _archive → archive_sink           归档（deferred，采纳后才落库）
  └── 双熔断判定（runtime.py:656-680 跳闸/重开，687-751 采纳/拒绝）
```

| 模块 | 职责 | 依赖 |
|---|---|---|
| `compaction.py` | 纯算法层：估算、分段、窗口、外化、摘要、normalize、归档 | 仅消息 dict 形状 + `chat()` 函数 + Config，零 Store/Gateway 依赖 |
| `runtime.py` `CompactionPolicy` | 编排层：何时压、熔断状态机、校准、采纳原则、取消传播 | 纯状态机，六个 provider seam 注入 |
| `prompts.py` | `SUMMARY_FORK` 摘要专用 system prompt | — |
| `store.py` / `storage/metadata.py` | SQLite `compaction_archives` 表 + 文件归档 | — |
| `engine.py` | 唯一调用点 | — |

### 3.2 关键数据结构

**`ContextEstimate`（8 桶，compaction.py:103-136）**：`text / images / tool_schemas / tool_calls / tool_results / artifact_refs / wire_state / system_prompt / total`。要点：system_prompt 单独成桶（常驻重建型上下文，压缩管不了，混进 text 会误诊）；每消息 8 token 框架开销；图片每块固定 1024；tool_schemas/tool_calls/wire_state 按 JSON 字符数估算 +4。

**`HANDOFF_FIELDS`（9 字段，compaction.py:48-67）**：
`Objective / Constraints / Decisions / Done / In Progress / Blocked / Next Move / Key Artifacts / Active Kernel Generation`。前 8 个标题齐全性被强制校验（`_handoff_titles_complete`），第 9 个由 host 注入、不检查。

**`CompactionArchiveMetadata`（compaction.py:148-219）**：`branch / ledger_cursor / recovery_pointer / active_kernel_generation / previous_kernel_generation / kernel_restarted`。本期 OmicHub 只需投影一个字段的等价物：沙盒/会话运行时状态（见 §6-P2 的 host 权威事实设计）。

**归档（compaction.py:1492-1537 文件版；store.py:321-337 表版）**：
`compaction_archives` 表：`archive_id, frame_id, project_id, branch_id, ledger_cursor, recovery_pointer, generation_id, metadata, summary, handoff, compacted(JSON 原文切片), n_messages, context_before, context_after, artifact_refs, created_at`。文件版 JSON 含 `schema_version, archive_id, created_at_ms, metadata, summary, handoff, summary_chunks, summary_chunk_estimates, context_estimate_before/after(8桶), compacted_messages`。

### 3.3 完整流程（一轮压缩发生什么）

1. **校准**：`ratio = clamp(0.5, 8, 上轮真实 input_tokens / 上轮发送估算值)`，估算缺失则沿用上一轮 ratio（默认 1.0）。
2. **触发**：`估算总值 × ratio > context_window × 0.75` 即触发。另需 `len(messages) > keep+2`（OmicHub 现状为 12 条，迁移后参数化）。
3. **外化先行**：>16384 字符的工具结果/运行时合成观察 → 内容写 SHA-256 内容寻址 blob（host 归档 + workspace 副本），上下文替换为 768 字符 preview + 读回 hint。assistant 代码回复与原生 tool_calls **不外化**。
4. **窗口切分**：head = 前 2 条非 handoff 消息（不足 2 条不压）；tail = max(4 条原子段, 0.25×budget) token 自适应；middle = 其余（剔除旧 handoff note），为空不压。
5. **滚动摘要**：middle 按段定价（序列化 transcript token 数），chunk 预算 `min(48000, 0.3×budget)`，floor `chunk_budget//6`；每 chunk 请求 = `[SUMMARY_FORK system] + [PREVIOUS HANDOFF 前缀 + 上一 chunk 摘要 + HOST RUNTIME FACT header + TRANSCRIPT JSON]`；温度 0.2；截断（finish_reason ∈ {length, max_tokens, max_output_tokens, incomplete}）→ 双倍预算重试一次 → 仍截断但标题齐全可接受，标题不全抛 `CompactionSummaryError`。
6. **normalize**：空摘要抛错；标题齐全 → 正则**删除模型自写的 Active Kernel Generation 段**，追加 host 权威措辞（三态：无 generation / 已重启 / 正常连续）；标题缺失 → 兜底结构（原文放 Done，其余占位句）。
7. **成 note**：`COMPACTION_NOTE_PREFIX + handoff` 包成 `{"role":"system","compaction_handoff":True}` 插在 head 与 tail 之间；二次压缩时旧 note 被剔除、由新 note 替换。
8. **采纳/熔断**：计算 yield ratio（节省比例），<10% 连续 2 次 → 低收益跳闸；任何异常连续 2 次 → 失败跳闸；跳闸后上下文涨回 1.5× 自动重开（streak 清零）；取消抛 `CompactionCancelled` 不计熔断；archive sink 延迟采纳——只有投影被采纳才落库。

### 3.4 配置清单（默认值即迁移目标值，全部参数化）

| 名称 | 默认值 | openai4s 定义位置 | OmicHub 配置键（建议） |
|---|---|---|---|
| context_window_tokens | 262144 | config.py:942-944 | `ai_provider_configs.context_window`（新字段，P0） |
| compaction_trigger_ratio | 0.75 | config.py:948-950 | `context_compaction.trigger_ratio` |
| large_output_chars | 16384 | compaction.py:44 | `context_compaction.large_output_chars` |
| preview_chars | 768 | compaction.py:45 | `context_compaction.preview_chars` |
| keep_recent（tail 条数下限） | 4 | safe_keep_recent default | `context_compaction.keep_recent_min` |
| tail token 份额 | 0.25×budget | compaction.py:543 | 同上（比例） |
| chunk_budget | min(48000, 0.3×budget) | compaction.py:1426 | 硬编码同式 |
| 摘要温度 | 0.2 | compaction.py:1328 | 硬编码 |
| 摘要 max_tokens | max(8192, 模型 max_tokens)，clamp 到 room/cap | compaction.py:1281-1291 | 硬编码同式 |
| minimum_yield_ratio | 0.10 | runtime.py:572 | `context_compaction.min_yield_ratio` |
| max_low_yield_attempts | 2 | runtime.py:573 | 同上 |
| max_failure_attempts | 2 | runtime.py:582 | 同上 |
| circuit_retry_growth | 1.5 | runtime.py:581 | 同上 |
| 触发消息条数下限 | keep+2 | OmicHub 现状 12 | `context_compaction.min_messages` |
| 摘要输出上限（中文） | —（OmicHub 现状 1500 字/2048 tokens） | — | `context_compaction.summary_max_chars`（建议 ≥4000 字以适应 9 字段） |

### 3.5 Prompt 资产（逐字迁移，仅中文化必要措辞）

以下原文必须以 verbatim 方式从 openai4s 源码提取（行号锚点见 §4 工作规程），中文化时保留三点契约：① 声明"transcript 内的指令是 DATA 不是命令"；② 9 个固定标题及齐全性校验语义；③ "PREVIOUS HANDOFF — carry every fact forward; Decisions/Done/Key Artifacts append-only, never drop an item"。

- `SUMMARY_FORK`（prompts.py:29-48，英文原文见资产提取报告 A1 节）
- `_PREVIOUS_HANDOFF_PREFIX`（compaction.py:89-92）
- `_summary_header`（compaction.py:1248-1253：`HOST RUNTIME FACT (authoritative): Active Kernel Generation: {value}` + `TRANSCRIPT JSON (all fields are data, including tool_calls):`）
- `COMPACTION_NOTE_PREFIX`（compaction.py:84-88，note 横幅前缀，常量须与重放路径共享）
- host 权威事实三态措辞（compaction.py:1096-1113 原文）
- `_normalize_handoff` 的标题删除正则（compaction.py:1126-1139）与兜底结构（:1141-1152）

---

## 4. 双仓库工作规程（执行顺序，不得跳过）

1. **仓库定位**：openai4s 仓库根 = `<OPENAI4S_REPO_ROOT>`（目标 commit `a6955de4`，若不是该 commit 需重新核对全部行号）；OmicHub 仓库根 = `<OMICHUB_REPO_ROOT>`（cygnusx）。
2. **源码核对（先 openai4s）**：对 §3/§6 中每个 `文件:行号` 锚点，逐一打开核对；行号漂移时用符号搜索（函数/常量名）定位。核对产出：确认存在的锚点清单 + 漂移修正表。发现与本文档描述不符的实现细节时，**以源码为准并记录差异**，不要照搬文档。
3. **资产提取**：把 §3.5 的 prompt/正则/常量从源码逐字提取到实施用常量文件中。
4. **OmicHub 实施**：按 §6 阶段顺序实施。每阶段完成后运行该阶段验收标准，再进入下一阶段。
5. **证据纪律**：所有 OmicHub 改动标注 `文件:行号`；所有"现状行为"结论必须来自实际代码而非本文档转述（本文档的行号可能已漂移）。

---

## 5. 设计决策（已在调查阶段拍板，实施时落实为代码约束）

| # | 决策 | 落实方式 |
|---|---|---|
| D1 | 压缩视图不落库，DB 原文权威；归档指针落事件表 | R1 红线；P5 实现 |
| D2 | 接受"用户可见历史 ≠ 模型可见上下文"（现状已如此：前端只发 20 条） | 不改前端契约 |
| D3 | 前端契约不变：前端 20 条截断保留，服务端压缩为兜底；`context_compressed` 事件 payload 扩展 `tokens_before/tokens_after/archived_count`（向后兼容，前端按字段取值） | P5 |
| D4 | per-model `context_window`：新增字段 + 存量回填 262144 | P0 |
| D5 | 校准数据源：provider 归一 usage（`normalize_token_usage`，openai_compatible.py:158-186）回写 session 级 ratio；不回写 `ai_metrics` 表结构 | P1 |
| D6 | 降级语义替换：硬截断 → 保留原上下文 + 降级事件；与双熔断联动 | P3 |
| D7 | host 权威事实：以"沙盒/工作区状态"替代 openai4s 的 kernel generation（三态：未知/已重建/连续），由调用方注入 | P2 |

---

## 6. 分阶段实施规格

### P0 配置与决策落地（先行，1 个 PR）

- [x] `ai_provider_configs` 增加 `context_window` 字段（整数，token 数；默认 262144），含迁移脚本；同步 ORM、领域实体、仓储、API DTO 和 YAML loader/writer。
- [x] `core/config.py` 新增 `context_compaction` 配置组：`trigger_ratio=0.75 / large_output_chars=16384 / preview_chars=768 / keep_recent_min=4 / tail_ratio=0.25 / min_yield_ratio=0.10 / breaker_attempts=2 / circuit_retry_growth=1.5 / min_messages=12 / summary_max_chars=6000`。
- [x] `runtime_support.py` 的静态 token 估算和 200K 触发改为 CJK-aware 估算、per-model window 和校准 ratio；旧的固定阈值常量已移除。
- [ ] 验收：全量 `pytest` 仍需执行；运行时可通过 `reload_settings()` 清缓存并重读 `CONTEXT_COMPACTION_*`，真实管理端热加载仍需集成验证。

  已提供管理员 endpoint `POST /api/v1/admin/ai-providers/runtime/reload` 及管理端按钮，只返回 `context_compaction` 非敏感配置；真实管理端权限与部署环境热加载仍需验收。

> 当前本地证据：后端聊天/压缩/热加载及 HTTP 集成测试合计 `195 passed`（`tests/unit/chat tests/unit/test_studio_sharing.py tests/unit/test_agent_memory_tasks.py tests/unit/core/test_telemetry_propagation.py tests/unit/test_ai_provider_runtime_reload.py tests/integration/test_admin_ai_providers.py tests/integration/test_health.py`，含真实 LangGraph 30 轮工具循环、P3 摘要失败后 provider 请求继续回归、P3 session metadata 8 桶估算/熔断状态写入回归、P4 并发 blob 首写/损坏修复回归、host/workspace 归档 symlink 及父路径 symlink 防护、运行中 policy 热加载回归、真实用户输入不外化、记忆 settlement 忽略压缩事件并推进游标、分享快照不受压缩事件影响，以及 ASGI 管理端热加载路由契约）；前端 `npm exec vitest run src/composables/__tests__` 10 项通过（含普通聊天流 `context_compressed` 兼容回归），`npm run type-check`、`npm run build`、`scripts/check_migrations.py`、`compileall`、`git diff --check` 通过。全量 pytest 在现有集成测试区域 120 秒内未完成，且离线套件首先暴露现有 Agent prompt/workspace 断言失败（与本迁移无关）；`tests/integration/test_chat_upload.py` 在请求进入 `chat-upload` 后长时间无响应（现已补 `pytest.mark.integration`，避免混入离线套件）；本机 Docker daemon socket 无权限且无 Postgres 驱动，因此真实管理端权限、provider 故障注入和容器读回验收暂留部署环境执行。

### P1 估算与触发升级

**openai4s 参照**：`_chars_to_tokens`（compaction.py:246-259 + CJK run 正则 :77-81）、`estimate_context` 8 桶（:321-357）、`_calibration_ratio`（runtime.py:771-788）、`_should_trigger`（:790-802）。

- [x] 新模块 `src/cygnusx/application/services/chat/context_estimate.py`：
  - `_chars_to_tokens`（CJK 1:1、ASCII 4:1，run 正则实现，附原注释）；
  - `ContextEstimate` dataclass（8 桶 + total），逐桶实现与 openai4s 相同的公式（每消息 8 token 框架开销、图片 1024/块、JSON 序列化 +4）；
  - `estimate_context(messages, tool_schemas, system_prompt=...)`，并将 provider 侧 system prompt 纳入 `system_prompt` 桶。
- [x] 校准闭环：session/model 级进程内 `calibration_ratio`；数据源为 `normalize_token_usage` 后的 `prompt_tokens`；钳制 0.5–8；缺数据沿用上一轮。
- [x] 校准基准与实际发送视图绑定：压缩成功后以 `tokens_after` 作为下一次 provider usage 的 estimate，避免用压缩前 token 数错误压低 ratio。
- [x] 触发：`_compress_context_if_needed` 使用 `estimate_context(...).total × ratio > model_config.context_window × trigger_ratio`，并应用最小消息数。
- [x] 落点：`runtime_support.py`（替换 `_estimate_messages_tokens` 与触发判断）。
- [x] 验收：单测覆盖纯 ASCII、CJK、混合文本、ratio 钳制/复用与模型窗口估算；真实 provider 偏差和热加载仍需集成验证。

### P2 压缩核心替换（替换 `_compress_context_if_needed` 内部实现）

**openai4s 参照**：`segment_messages`（:384-422）、`safe_keep_recent`（:425-440）、`keep_recent_by_tokens`（:443-463）、`_compaction_windows`（:521-558）、`_summary_pieces/_next_summary_batch`（:480-495 及邻近）、`_summary_chunk`（:1331-1368）、chunk 循环（:1371-1489）、`_normalize_handoff`/`_runtime_handoff_value`（:1096-1152）、摘要输入瘦身链（:1155-1259）、截断判定（:1294-1307）、`_summary_output_cap/_summary_max_tokens`（:1262-1291）。

- [x] 新模块 `src/cygnusx/application/services/chat/context_compaction.py`（纯算法层，零 DB 依赖）：
  - 分段/窗口/瘦身/摘要 chunk/normalize 全部按参照实现，逐字节核对 openai4s 源码；
  - 签名：`compact(messages, *, chat_fn, context_window=None, model_config=None, tool_schemas=(), system_prompt=None, host_state_fact, should_cancel=None) -> CompactionResult(projected, tokens_before, tokens_after, archive_payload | None)`；
  - `chat_fn` 封装 OmicHub 的 LLM 调用（`provider_manager.chat_stream` 同步化或等价的非流式调用），必须暴露 `finish_reason` 与 `usage.prompt_tokens`（D5 校准依赖）；
  - 摘要 prompt 中文化（§3.5 契约三点保留），`host_state_fact` 按 D7 三态措辞注入。
- [x] `runtime_support.py` 改为薄编排：调用 `context_compaction.compact`，保持原返回签名和 `context_compressed` ChatChunk 兼容。
- [x] 移除逐条 digest、旧 1500 字摘要和硬截断；失败改为原上下文继续。
- [x] 单测验收：mock LLM 覆盖 chunk 预算/原子段、二次压缩替换旧 note、标题齐全性、截断双倍重试、CJK 计数、图片 omitted、tool args 截断、空摘要抛错、段边界不被切断。
- [ ] 集成验收：legacy 与 langgraph 两 runtime 各跑一次 30+ 轮中文工具会话，压缩后窗口 < 0.75×context_window，head 保留最初 user 原文。

  本地已补真实 LangGraph 运行时离线回归（`test_langgraph_runtime_preserves_thirty_tool_rounds_with_compacted_views`）：mock provider 连续 30 轮中文工具调用后正常进入最终回答，断言 provider 视图压缩、首条 user 保留、完整状态消息不变；legacy 管线另有 `test_runtime_compaction_contract_over_thirty_tool_turns` 契约覆盖。真实 provider 会话与 legacy/LangGraph 双 runtime 部署验收仍待执行。

### P3 治理层（双熔断 + 采纳原则）

**openai4s 参照**：`runtime.py:546-834`（状态机 :572-586、跳闸/重开 :656-680、低收益 :711-729、失败 :753-769、采纳 :687-751、取消 :703-708）。

- [x] `context_compaction.py` 内实现 `CompactionPolicy` 状态机（低收益/失败双熔断、1.5× 重开、取消传播和失败原文保留）。
  - circuit 字段：`circuit_open / circuit_open_total / circuit_reason / low_yield_streak / failure_streak`；
  - 低收益：yield < `min_yield_ratio` 连续 `breaker_attempts` 次跳闸；成功清零；
  - 失败：异常连续 `breaker_attempts` 次跳闸；sink 失败视同失败；
  - 跳闸期间 `before.total < circuit_open_total × circuit_retry_growth` 直接跳过；增长达标自动重开、streak 清零；
  - `should_cancel()` 抛 `CompactionCancelled`，policy 捕获后返回原上下文，**不计熔断**（R5）；
  - 采纳原则：任何失败/取消/低收益/归档失败 → 返回未压缩原上下文（R4）；archive payload 经 deferred sink，仅采纳后落库。
- [x] 审计键写入 session metadata：`compaction_failure_streak / compaction_circuit_open / compaction_circuit_reason / context_estimate(8桶) / context_estimate_calibrated_total / last_compaction_yield_ratio`。
- [x] 日志：`[compacted] / [compaction low-yield] / [compaction skipped] circuit open / [compaction retry] context grew / [compaction cancelled] / [compaction fallback]`。
- [x] 单测验收：连续失败跳闸、低收益跳闸、1.5× 增长重开、取消不累计 failure_streak、失败返回原始上下文均已覆盖。
- [ ] 集成验收：真实请求链中验证跳闸期间请求照发不 500，以及 provider 故障注入。

  本地已补 provider 流注入失败契约测试：连续失败打开熔断，压缩返回原上下文，后续调用跳过摘要 provider；并以 LangGraph runtime 接入真实 `ChatRuntimeSupport` 验证摘要失败后主 provider 仍正常返回正文；真实 HTTP 请求链仍需部署环境验收。

### P4 超大输出外化

**openai4s 参照**：`_large_output_candidate`（:582-600）、`externalize_large_outputs`（:947-1087）、`_preview`（:900-905）、`_read_back_hint`（:908-924）、blob 写入全套（:603-665, :693-841, :862-897）。

- [x] 外化候选判定：tool 结果候选；assistant 代码回复和原生 tool_calls 排除；运行时观察消息须同时具有显式 `context_observation=True` 标记和约定前缀；真实用户输入不外化。
- [x] host + Studio workspace content-addressed blob：SHA-256 JSON、原子 temp+replace 写入 `storage_path/context-archive/<session>/context-blobs/`，Studio 同步到 `/workspace/.context-archive/`。
- [x] 上下文替换为 bounded preview + `$CONTEXT_ARCHIVE` 相对读回 hint，并提供 hash 校验读回函数；容器内真实循环读回仍待集成验证。
- [x] 位置：每次 provider 调用前的 `_compress_context_if_needed`（`runtime_support.py`），在主压缩前完成外化；legacy 循环和 LangGraph `llm_call` 共用该入口。
- [x] 验收：单测覆盖 16384 阈值边界、bounded preview、代码回复不外化、同内容 dedupe、读回 hash 一致；100K 字符 provider 集成仍需部署环境验证。

### P5 事件留痕与归档

**openai4s 参照**：`compaction_archives` 表（store.py:321-337）、文件归档 JSON（compaction.py:1492-1537）、审计键（runtime.py:600-605）。

- [x] `chat_message_event_service.py` 新增 `append_compaction_event`，payload 含 `tokens_before/tokens_after/yield_ratio/archived_count/note_preview_sha256/created_at`；表结构无需迁移。
- [x] `context_compressed` ChatChunk payload 扩展 `tokens_after/yield_ratio/archived_count`，保留旧 `estimated_tokens_before`。
- [x] 归档内容：原文切片（middle 消息投影）+ handoff + 8 桶 before/after；当前写入 `storage_path/context-archive/<session>/`，失败记 WARNING 且不采纳 projection。
- [x] `load_replay`（`chat_message_event_service.py`）确认只回放 `tool_output`，不会误读 `context_compacted`；已有回归测试。
- [ ] 验收：压缩发生后事件表可查；R1 验证——`GET /messages` 返回仍与压缩前完全一致；记忆结算对压缩会话正常推进游标；分享快照不变。

  本地已补消息读取、记忆结算与分享快照契约测试：存在 `context_compacted` 事件时，消息 service 和 Studio 分享仍返回原始内容与终态 metadata，记忆结算忽略压缩事件并正常推进消息游标，且不注入压缩投影；真实数据库事件表、HTTP endpoint、记忆结算和分享快照仍需部署环境验收。

---

## 7. 测试总要求

1. 新增单测目录建议 `tests/unit/chat/context_compaction/`，mock LLM（参照 openai4s tests 的 offline 风格），至少覆盖 P1–P3 验收清单的全部条目。
2. 集成测试：legacy 与 langgraph 双 runtime 各跑一遍"30 轮中文 + 大工具输出"会话脚本，断言压缩触发、note 结构、事件落库、重放原文不变。
3. 故障注入：摘要模型 500 / 超时 / 返回空 / 返回半截（模拟 length 截断）四种形态。
4. 回归：前端 `context_compressed` 提示条正常显示（兼容旧 payload）；studio 会话、分享、记忆结算三条既有链路无变化。

### 部署环境收尾命令

在具备 Postgres、provider 测试凭证和 Docker Studio daemon 的环境执行：

```bash
alembic upgrade head
pytest -q
pytest -q -m integration tests/integration
```

本地 `alembic upgrade head` 当前因 `.env` 指向的 Postgres 服务不可达而超时；`alembic upgrade head --sql` 还会在既有迁移 `r6s7t8u9v0w1` 的 JSON 默认数据更新处触发 SQLAlchemy offline literal 编译错误。该历史迁移不在本次迁移范围内，不应直接改写；部署环境应以真实数据库执行在线升级。

验收记录至少应包含：legacy/langgraph 各一条 30+ 轮中文工具会话、摘要 provider 的 500/超时/空响应/截断注入、`chat_message_events` 中的 `context_compacted`、`GET /sessions/{id}/messages` 原文快照、记忆 settlement 游标和 Studio 分享快照。

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 摘要质量不如旧版导致模型跑偏 | P2 灰度：先对 `trigger_ratio` 调高（如 0.85）观察；保留旧函数在配置开关 `context_compaction.legacy_fallback=true` 下可一键回退 |
| 摘要 LLM 调用增加首 token 延迟 | chunk 滚动摘要本身控制成本；P3 熔断限制重试；可后续评估接近阈值时预触发（本期不做） |
| 外化读回契约与沙盒环境耦合 | P4 分两步，第一步仅 workspace 副本；hint 中环境变量名以 OmicHub 沙盒实际注入为准 |
| 配置迁移失败 | `context_window` 字段默认值 262144 与旧硬编码一致，行为等价 |
