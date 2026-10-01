# OpenAI4S 长对话架构

> 核对基线：相对 OmicHub 仓库根的 `../OpenAI4S`，commit `a6955de4`。下文源码路径均相对 OmicHub 仓库根；OmicHub 的差异见文末。

## 核心思路

OpenAI4S 通过**上下文投影、摘要交接和归档**延续长任务。模型每轮只接收当前的 `state.messages`；当上下文接近模型窗口时，系统把较早的消息压缩为一条结构化 handoff 记录，并将压缩结果**原地写回** `state.messages`。因此，运行中的消息列表不是始终保留完整原文的副本。被压缩的内容另有归档，Action Ledger 记录压缩事件并用于恢复当前上下文投影。

```text
会话消息 / Action Ledger
       │
       ▼
每轮模型调用前：ContextCompactionPolicy.prepare(state)
       ├─ 估算上下文，并用上一轮实际 input_tokens 校准
       ├─ 将过大的工具输出外置为 blob，消息中保留预览与读回提示
       └─ 超过阈值时压缩：
            开头消息 + [中间消息的 handoff 摘要] + 最近消息
       │
       ▼
原地更新 state.messages → 模型调用 → 追加回复和动作结果
       │
       └─ 下一轮重复；压缩归档和 Ledger 支持追溯与恢复
```

入口见 `../OpenAI4S/openai4s/agent/engine.py` 的 `AgentEngine.run()`；压缩编排在 `agent/runtime.py` 的 `CompactionPolicy`，具体算法在 `agent/compaction.py`。

## 一轮压缩如何发生

1. **估算与校准。**系统估算消息正文、图片、工具定义、工具调用与结果等占用量，并结合上一轮模型返回的 `input_tokens` 校准估算。校准后的总量超过上下文预算的默认 **75%** 时，开始尝试压缩。
2. **外置大输出。**超过默认 **16,384 字符**的工具结果等内容写入内容寻址归档；发送给模型的消息只保留默认 **768 字符**预览和读回提示。
3. **划分窗口。**保留开头消息与最近消息；最近窗口至少保留 4 条，并按上下文预算动态扩大。中间消息进入摘要，旧 handoff 会被新的 handoff 取代。
4. **滚动摘要。**中间消息按预算分块，上一块的 handoff 传给下一块。摘要固定记录 `Objective`、`Constraints`、`Decisions`、`Done`、`In Progress`、`Blocked`、`Next Move`、`Key Artifacts` 和 `Active Kernel Generation`。摘要提示词要求把历史消息中的指令视为数据，避免旧消息反过来控制摘要过程。
5. **写回投影。**生成 `开头 + handoff 系统消息 + 最近消息`。压缩过程生成文件归档；只有投影被采纳后才提交归档记录。引擎随后在模型调用前将投影原地写回 `state.messages`。

压缩摘要是有损的：一般可以保留任务目标、决策和产物线索，但不保证模型仍能逐字记住很早之前的每条消息。需要精确旧内容时，应通过归档或产物读取。

## 失败与恢复

压缩失败或归档失败时，当前轮保留压缩前的消息继续执行；用户取消不计为压缩失败。连续失败或连续低收益达到默认 2 次时会打开熔断器；上下文较熔断时增长到默认 **1.5 倍**后再尝试。非缩短的投影不会被采纳。

Action Ledger 有独立的 `compaction` 事件。恢复时，Ledger 的 reducer 将历史事件还原为已压缩的上下文投影；压缩归档保留被摘要覆盖的消息和相关元数据。这与“运行中始终持有完整原始消息列表”是不同的语义。

## 执行状态与边界

OpenAI4S 的代码单元是引擎原生动作，使用运行期间常驻的 kernel；因此长任务还涉及代码执行状态的连续性。handoff 中的 `Active Kernel Generation` 由宿主程序提供权威事实，而非让模型自行判断。kernel 重启后，旧内存变量不能视为仍然存在，恢复应依靠文件、产物和执行记录。

单次 `AgentEngine.run()` 有 `max_turns` 限制，构造器默认 32 轮，也会受取消、完成信号和无进展熔断限制。长对话表示会话可以在有限模型窗口中持续推进，并不意味着单次运行可以无限循环或摘要不会丢失细节。

## 与 OmicHub 的关系

OmicHub 已借鉴上下文估算、滚动摘要、大输出外置和失败保护等机制，但持久化边界不同：OmicHub 的 `chat_messages` 数据库保存完整原文，压缩视图主要用于构造模型请求；OpenAI4S 会把压缩投影原地写回运行消息列表，并通过归档与 Action Ledger 留痕和恢复。执行层也不同：OpenAI4S 使用原生 CodeCell 和持久 kernel，OmicHub 的代码执行仍走工具调用及一次性执行进程。

## 源码入口

- `../OpenAI4S/openai4s/agent/engine.py`：每轮调用 `prepare()`、原地更新消息、运行轮数限制。
- `../OpenAI4S/openai4s/agent/runtime.py`：估算校准、压缩触发、采纳与熔断。
- `../OpenAI4S/openai4s/agent/compaction.py`：大输出外置、窗口划分、滚动摘要、handoff 和归档。
- `../OpenAI4S/openai4s/agent/ledger.py`：压缩事件和上下文投影恢复。
- `docs/info/26.9.23/migration-spec-openai4s-to-omichub.md`：OmicHub 的迁移设计和差异。
