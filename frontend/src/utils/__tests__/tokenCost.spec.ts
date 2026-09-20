// @vitest-environment jsdom

import { describe, expect, it, beforeEach } from 'vitest'
import {
  DEFAULT_TOKEN_PRICING,
  formatTokensInM,
  loadTokenPricing,
  resolvePricing,
  saveTokenPricing,
  summarizeUsage,
} from '../tokenCost'

describe('tokenCost', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips pricing through localStorage with defaults', () => {
    expect(loadTokenPricing()).toEqual(DEFAULT_TOKEN_PRICING)
    saveTokenPricing({ inputPerM: 2.5, outputPerM: 10, inputCachePerM: 0.25, outputCachePerM: 1 })
    expect(loadTokenPricing()).toEqual({ inputPerM: 2.5, outputPerM: 10, inputCachePerM: 0.25, outputCachePerM: 1 })
  })

  it('backfills cache defaults for legacy stored pricing', () => {
    localStorage.setItem('ai_token_pricing', JSON.stringify({ inputPerM: 2.5, outputPerM: 10 }))
    expect(loadTokenPricing()).toEqual({
      inputPerM: 2.5,
      outputPerM: 10,
      inputCachePerM: DEFAULT_TOKEN_PRICING.inputCachePerM,
      outputCachePerM: DEFAULT_TOKEN_PRICING.outputCachePerM,
    })
  })

  it('maps legacy single cachePerM to both input and output cache prices', () => {
    localStorage.setItem(
      'ai_token_pricing',
      JSON.stringify({ inputPerM: 2.5, outputPerM: 10, cachePerM: 0.3 }),
    )
    expect(loadTokenPricing()).toEqual({ inputPerM: 2.5, outputPerM: 10, inputCachePerM: 0.3, outputCachePerM: 0.3 })
  })

  it('falls back to defaults on corrupted storage', () => {
    localStorage.setItem('ai_token_pricing', '{broken')
    expect(loadTokenPricing()).toEqual(DEFAULT_TOKEN_PRICING)
  })

  it('formats tokens in M/K units', () => {
    expect(formatTokensInM(0)).toBe('0')
    expect(formatTokensInM(850)).toBe('850')
    expect(formatTokensInM(12_340)).toBe('12.3K')
    expect(formatTokensInM(2_450_000)).toBe('2.45M')
  })

  it('summarizes usage and cost across messages', () => {
    const usage = summarizeUsage(
      [
        { tokens: { input: 1_000_000, output: 200_000, total: 1_200_000 } },
        { tokens: { input: 500_000, output: 100_000 } },
        {},
      ],
      { inputPerM: 2, outputPerM: 8, inputCachePerM: 0.5, outputCachePerM: 0.5 },
    )
    expect(usage.input).toBe(1_500_000)
    expect(usage.output).toBe(300_000)
    expect(usage.cached).toBe(0)
    expect(usage.cachedOutput).toBe(0)
    expect(usage.total).toBe(1_800_000)
    // 1.5 * 2 + 0.3 * 8 = 5.4
    expect(usage.cost).toBeCloseTo(5.4)
  })

  it('prices cached input and output at their own cache rates', () => {
    const usage = summarizeUsage(
      [{ tokens: { input: 1_000_000, output: 100_000, cached: 800_000, cachedOutput: 40_000 } }],
      { inputPerM: 2, outputPerM: 8, inputCachePerM: 0.25, outputCachePerM: 2 },
    )
    expect(usage.cached).toBe(800_000)
    expect(usage.cachedOutput).toBe(40_000)
    // 未命中输入 0.2M * 2 + 输入缓存 0.8M * 0.25 + 未命中输出 0.06M * 8 + 输出缓存 0.04M * 2
    // = 0.4 + 0.2 + 0.48 + 0.08 = 1.16
    expect(usage.cost).toBeCloseTo(1.16)
  })

  it('clamps cached tokens to input/output to avoid negative uncached cost', () => {
    const usage = summarizeUsage(
      [{ tokens: { input: 100_000, output: 50_000, cached: 300_000, cachedOutput: 300_000 } }],
      { inputPerM: 2, outputPerM: 8, inputCachePerM: 0.25, outputCachePerM: 1 },
    )
    expect(usage.cost).toBeCloseTo((300_000 / 1_000_000) * 0.25 + (300_000 / 1_000_000) * 1)
  })

  it('resolves model pricing over global fallback per field', () => {
    const globalPricing = { inputPerM: 1, outputPerM: 2, inputCachePerM: 0.5, outputCachePerM: 0.5 }
    // 模型全配置：完全覆盖
    expect(resolvePricing(globalPricing, { input: 4, output: 12, inputCache: 1, outputCache: 3 })).toEqual({
      inputPerM: 4,
      outputPerM: 12,
      inputCachePerM: 1,
      outputCachePerM: 3,
    })
    // 部分配置：缺省字段回退全局
    expect(
      resolvePricing(globalPricing, { input: 4, output: null, inputCache: null, outputCache: undefined }),
    ).toEqual({ inputPerM: 4, outputPerM: 2, inputCachePerM: 0.5, outputCachePerM: 0.5 })
    // 未配置：全局兜底
    expect(resolvePricing(globalPricing, null)).toEqual(globalPricing)
  })
})
