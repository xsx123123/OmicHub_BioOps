# Token 与饼干消耗架构

> 文档类型：as-built + 对账规范  
> 基线：2026-09-22  
> 适用范围：普通 Chat、Studio/Agent 工具循环、AgentTeams 会诊、个人用量统计和工作台费用展示。

## 1. 目的与边界

本系统同时存在两种费用口径：

1. **模型费用估算（元）**：工作台前端根据模型单价或全局兜底单价估算，供用户观察，不是供应商账单的结算凭证。
2. **平台饼干扣费（饼干）**：后端按 `ai_token_cookie_rate` 对实际记录的 token 扣减，用于平台额度和账户余额控制。

两者不能直接相加或互相推导。只有当 AI Provider 配置的输入、输出、输入缓存、输出缓存单价与供应商账单的模型、区域、单位和时间版本完全一致时，元估算才可能与供应商账单一致。

本系统不在本地使用 tokenizer 重新估算供应商 token；正常情况下以供应商响应中的 `usage` 为事实源。供应商没有返回 usage 时，不应把界面显示或本地字符估算当成真实账单数据。

## 2. 总体数据流

```text
Provider SSE usage
  -> normalize_token_usage()
  -> ChatChunk(done).metadata.usage
  -> 工具循环 merge_token_usage() 累加每次模型请求
  -> assistant message.metadata_json.usage
  -> chat session.total_tokens + CookieService.spend_ai_tokens()
  -> DTO / stats API / 前端工作台
```

入口与主要实现：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| Provider 采集 | `src/cygnusx/infrastructure/ai_provider/openai_compatible.py` | 读取 SSE `usage`，归一化不同供应商字段 |
| 多轮累计 | `merge_token_usage()`、Chat/Studio/LangGraph runtime | 将工具调用产生的多次模型请求相加 |
| 消息落库 | `ChatRuntimeSupport._apply_usage_to_session()` | 写入规范化 usage、累加会话总量、触发饼干扣费 |
| AgentTeams | `application/services/agentteams_usage_service.py` | 把会诊 usage 写入合成聊天消息并扣费 |
| 查询统计 | `StatsService.user_ai_token_usage()` | 从 assistant 消息 usage 聚合个人统计 |
| 前端展示 | `frontend/src/utils/tokenCost.ts`、Studio/AgentSandbox | 按元/M tokens 单价计算展示估算 |

## 3. 规范化 token 契约

`normalize_token_usage()` 输出的核心字段（`cached_output_tokens` 仅在供应商报告该值时写入，缺省按 0 处理）：

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 300,
  "total_tokens": 1500,
  "cached_tokens": 800,
  "cached_output_tokens": 0
}
```

字段映射：

- 输入：`prompt_tokens`，兼容 `input_tokens` / `input`。
- 输出：`completion_tokens`，兼容 `output_tokens` / `output`。
- 总量：优先使用 `total_tokens` / `total`；缺失时使用输入 + 输出。
- 输入缓存：OpenAI `prompt_tokens_details.cached_tokens`，兼容顶层 `cached_tokens` 和 Anthropic `cache_read_input_tokens`。
- 输出缓存：`completion_tokens_details.cached_tokens`，兼容 `cached_output_tokens` 和 `cache_read_output_tokens`。

缓存 token 是对应输入或输出 token 的子集，不应再次加到 `total_tokens`。多轮请求的 `prompt_tokens`、`completion_tokens`、`total_tokens` 和缓存字段均按请求累加。

### 3.1 真实性要求

- 每个 assistant 消息最多应对应一次最终落库的规范化 usage；工具循环的多次 Provider 请求必须先合并，再写入该 assistant 消息。
- 用户消息不暴露 token 用量。
- `chat_sessions.total_tokens` 是该会话所有已计费 assistant 消息的 total 累计，不是 max_tokens 上限，也不是字符数。
- `finish_reason`、推理文本长度、请求的 `max_tokens` 都不能替代 Provider usage。
- Provider 未返回 usage 时，消息可以没有可计费用量；不得伪造平台真实 token。

## 4. 缓存 token 计费

前端 `summarizeUsage()` 使用以下公式，单价单位为“元 / 百万 tokens”：

```text
uncached_input  = max(0, input  - cached_input)
uncached_output = max(0, output - cached_output)

estimated_yuan =
  uncached_input  / 1,000,000 * input_price
  + cached_input  / 1,000,000 * input_cache_price
  + uncached_output / 1,000,000 * output_price
  + cached_output  / 1,000,000 * output_cache_price
```

实现会将缓存量限制在对应输入/输出总量以内，防止异常 Provider payload 产生负的未缓存量或超额收费。

当前支持模型级单价：`ai_provider_configs.input_price`、`output_price`、`input_cache_price`、`output_cache_price`。模型单价缺失时回退到前端设置页 localStorage 中的全局单价。全局默认值是展示兜底值，不能视为供应商官方价格。

## 5. 饼干扣费

后端扣费公式：

```text
raw_cookie_cost = total_tokens / 1000 * ai_token_cookie_rate
message_cookie_cost = ROUND_HALF_UP(raw_cookie_cost, 0.01)
```

扣费入口：`CookieService.spend_ai_tokens()`。

- 仅对 `total_tokens > 0` 的 assistant usage 扣费。
- `source_type=ai_chat`，`source_id=message_id`，以消息 ID 做幂等键，避免同一消息重复扣费。
- 余额不足时扣到可用余额上限；余额为零或账户非 active 时不产生负余额。
- 当前饼干扣费不区分普通输入与缓存输入，也不使用模型元单价；缓存信息用于展示和元估算，不改变饼干公式。
- 折扣活动会改变实际饼干费率，统计接口必须使用同一时点解析出的有效费率。

个人统计的汇总金额按每条消息已经四舍五入的计费结果累加，从而与明细和流水保持一致；不能用“总 token × 费率”替代逐条结算结果。

## 6. 三种金额/用量的区别

| 指标 | 来源 | 是否真实供应商账单 | 用途 |
| --- | --- | --- | --- |
| `message.metadata_json.usage` | Provider usage 归一化 | 是，前提是 Provider 返回完整 usage | 单消息审计、会话累计 |
| `chat_sessions.total_tokens` | assistant usage 的 total 累加 | 是平台记录的 token 累计 | 会话级配额/统计 |
| `cookie_cost` | token × 平台饼干费率，逐条舍入 | 否，属于平台内部额度 | 余额扣减、平台统计 |
| 工作台 `estimated_yuan` | 前端 token × 配置单价 | 仅是估算 | 用户可见费用参考 |

因此，“平台看见的 token 数”和“平台账单金额”必须分别核对：先核对 usage，再核对供应商价目表和单位，最后核对平台饼干规则。

## 7. 对账与排查流程

遇到 token 或费用不一致时，按以下顺序检查：

1. **先读文档**：阅读本文件，并从 `ARCHITECTURE_DESIN/README.md` 找到相关的 Chat、数据库、日志或 Agent 执行架构文档。
2. **锁定一次模型请求**：记录 provider、model、session_id、message_id、请求轮次和最终 `usage`。
3. **对比原始响应**：检查供应商原始 SSE 最后一条 usage 与规范化后的 `metadata_json.usage` 是否一致。
4. **检查多轮请求**：Studio/工具循环必须逐轮累加；不能只看最后一轮，也不能把同一轮重复合并。
5. **核对缓存**：确认 `cached_tokens <= prompt_tokens`、`cached_output_tokens <= completion_tokens`，并确认供应商确实返回了缓存字段。
6. **核对扣费流水**：按 `source_type=ai_chat`、`source_id=message_id` 查是否重复扣费、是否受余额封顶或折扣影响。
7. **核对金额单位**：模型配置价格必须标明元/M tokens；供应商页面可能使用元/百万、元/千、美元/M 或按缓存层级拆分，不能直接混用。
8. **清理统计缓存**：个人统计有短 TTL 缓存，刚发生扣费时应确认缓存是否已过期或主动失效。

建议保留以下对账样本：原始 Provider usage、规范化 usage、消息 ID、会话总量变更、饼干交易流水、模型价格快照和统计 API 响应。

## 8. 修改约束与验证清单

修改 token 或计费逻辑时：

- 不要在前端另写一套 token 字段映射；统一复用后端规范字段。
- 不要用字符数、`max_tokens` 或本地 tokenizer 覆盖 Provider usage。
- 不要把缓存 token 再次加到 total；缓存只是输入/输出的计费子集。
- 不要把元估算直接当成饼干扣费；两者价格源和舍入规则不同。
- 不要取消 message_id 幂等校验。
- 新增 Provider 字段时，同时补充归一化、合并、DTO、统计、前端展示和测试。

最低验证命令：

```bash
.venv/bin/pytest -q tests/unit/test_openai_usage.py \
  tests/unit/test_cookie_ai_billing.py \
  tests/unit/test_stats_service.py \
  tests/unit/test_agentteams_usage_service.py
cd frontend && npm test -- --run src/utils/__tests__/tokenCost.spec.ts
cd frontend && npm run type-check -- --pretty false
```

## 9. 关键文件索引

- Provider usage：`src/cygnusx/infrastructure/ai_provider/openai_compatible.py`
- 普通 Chat/Studio 扣费：`src/cygnusx/application/services/chat/runtime_support.py`
- AgentTeams usage：`src/cygnusx/application/services/agentteams_usage_service.py`
- 饼干扣费：`src/cygnusx/application/services/cookie_service.py`
- 个人 token 统计：`src/cygnusx/application/services/stats_service.py`
- 消息 DTO：`src/cygnusx/application/services/chat/dto_support.py`
- 前端元估算：`frontend/src/utils/tokenCost.ts`
- Provider 价格字段：`src/cygnusx/infrastructure/database/models/ai_provider.py`
