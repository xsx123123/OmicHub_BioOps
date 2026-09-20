/**
 * Token 用量展示与计费：单价在设置页配置（localStorage 持久化），
 * 工作台顶栏按会话汇总消息 tokens 后换算费用。
 * 缓存命中的输入/输出 tokens 分别按输入/输出缓存单价计价，未命中部分按对应输入/输出单价计价。
 */

export interface TokenPricing {
  /** 输入单价：元 / M tokens */
  inputPerM: number
  /** 输出单价：元 / M tokens */
  outputPerM: number
  /** 输入缓存命中单价：元 / M tokens */
  inputCachePerM: number
  /** 输出缓存命中单价：元 / M tokens */
  outputCachePerM: number
}

const STORAGE_KEY = 'ai_token_pricing'

export const DEFAULT_TOKEN_PRICING: TokenPricing = {
  inputPerM: 1,
  outputPerM: 2,
  inputCachePerM: 0.5,
  outputCachePerM: 0.5,
}

export function loadTokenPricing(): TokenPricing {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_TOKEN_PRICING }
    const parsed = JSON.parse(raw)
    // 兼容旧格式：单一 cachePerM 同时作为输入/输出缓存价
    const legacyCache = Number.isFinite(parsed.cachePerM) ? Math.max(0, parsed.cachePerM) : undefined
    return {
      inputPerM: Number.isFinite(parsed.inputPerM) ? Math.max(0, parsed.inputPerM) : DEFAULT_TOKEN_PRICING.inputPerM,
      outputPerM: Number.isFinite(parsed.outputPerM) ? Math.max(0, parsed.outputPerM) : DEFAULT_TOKEN_PRICING.outputPerM,
      inputCachePerM: Number.isFinite(parsed.inputCachePerM)
        ? Math.max(0, parsed.inputCachePerM)
        : legacyCache ?? DEFAULT_TOKEN_PRICING.inputCachePerM,
      outputCachePerM: Number.isFinite(parsed.outputCachePerM)
        ? Math.max(0, parsed.outputCachePerM)
        : legacyCache ?? DEFAULT_TOKEN_PRICING.outputCachePerM,
    }
  } catch {
    return { ...DEFAULT_TOKEN_PRICING }
  }
}

export function saveTokenPricing(pricing: TokenPricing): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(pricing))
}

/** 按 M 单位格式化 token 数：≥1M 显示 "x.xxM"，不足显示 K，便于顶栏紧凑展示 */
export function formatTokensInM(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens <= 0) return '0'
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return String(Math.round(tokens))
}

export interface SessionUsage {
  input: number
  output: number
  /** 缓存命中的输入 tokens（含在 input 内） */
  cached: number
  /** 缓存命中的输出 tokens（含在 output 内） */
  cachedOutput: number
  total: number
  cost: number
}

/** 模型级单价（AI 配置中心配置）覆盖全局单价；未配置字段回退到全局值 */
export function resolvePricing(
  globalPricing: TokenPricing,
  modelPrice?: {
    input?: number | null
    output?: number | null
    inputCache?: number | null
    outputCache?: number | null
  } | null,
): TokenPricing {
  return {
    inputPerM: modelPrice?.input ?? globalPricing.inputPerM,
    outputPerM: modelPrice?.output ?? globalPricing.outputPerM,
    inputCachePerM: modelPrice?.inputCache ?? globalPricing.inputCachePerM,
    outputCachePerM: modelPrice?.outputCache ?? globalPricing.outputCachePerM,
  }
}

export interface HasTokens {
  tokens?: {
    input?: number
    output?: number
    total?: number
    cached?: number
    cachedOutput?: number
  }
}

/** 汇总会话全部消息的 token 消耗，并按定价换算费用（缓存命中部分按对应缓存单价） */
export function summarizeUsage(messages: HasTokens[], pricing: TokenPricing): SessionUsage {
  let input = 0
  let output = 0
  let cached = 0
  let cachedOutput = 0
  let total = 0
  for (const message of messages) {
    const tokens = message.tokens
    if (!tokens) continue
    input += tokens.input || 0
    output += tokens.output || 0
    cached += tokens.cached || 0
    cachedOutput += tokens.cachedOutput || 0
    total += tokens.total ?? (tokens.input || 0) + (tokens.output || 0)
  }
  // 缓存 tokens 含在 input/output 内，避免重复计费：未命中部分按输入/输出单价，命中部分按对应缓存单价
  const uncachedInput = Math.max(0, input - cached)
  const uncachedOutput = Math.max(0, output - cachedOutput)
  const cost =
    (uncachedInput / 1_000_000) * pricing.inputPerM +
    (cached / 1_000_000) * pricing.inputCachePerM +
    (uncachedOutput / 1_000_000) * pricing.outputPerM +
    (cachedOutput / 1_000_000) * pricing.outputCachePerM
  return { input, output, cached, cachedOutput, total, cost }
}
