import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { CookieAccount, CookieTransaction, CostEstimate } from '@/types'
import apiClient from '@/api/client'

export const useCookieStore = defineStore('cookie', () => {
  const account = ref<CookieAccount | null>(null)
  const transactions = ref<CookieTransaction[]>([])
  const loading = ref(false)

  // 后端 balance/frozen_balance/available_balance 用 Decimal，Pydantic v2 序列化为 JSON 字符串
  // （如 "100.50"）。TS 类型标注为 number 但运行时是 string，直接 .toFixed 会抛
  // "toFixed is not a function"。
  // ⚠️ 不能只在 computed 里写 Number()：esbuild 信任 TS 类型标注，会把 Number(number)
  //    当 no-op 优化掉。必须在数据入口处（fetchAccount / WS 推送）强制转 number，
  //    让 account.value 本身存的就是 number。
  const toNum = (v: unknown): number => {
    const n = typeof v === 'number' ? v : parseFloat(String(v))
    return Number.isFinite(n) ? n : 0
  }

  const balance = computed(() => account.value?.available_balance ?? 0)
  const isLoggedIn = computed(() => account.value !== null)

  async function fetchAccount() {
    try {
      const res = await apiClient.get<CookieAccount>('/cookies/account')
      // 入口处强制把 Decimal 字符串转 number，避免后续 .toFixed 崩溃
      const a = res.data
      a.balance = toNum(a.balance) as number
      a.frozen_balance = toNum(a.frozen_balance) as number
      a.available_balance = toNum(a.available_balance) as number
      a.total_earned = toNum(a.total_earned) as number
      a.total_spent = toNum(a.total_spent) as number
      a.total_adjusted = toNum(a.total_adjusted) as number
      account.value = a
    } catch {
      account.value = null
    }
  }

  async function fetchTransactions(offset = 0, limit = 50) {
    loading.value = true
    try {
      const res = await apiClient.get<CookieTransaction[]>('/cookies/transactions', {
        params: { offset, limit },
      })
      transactions.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function estimateCost(flowId: string, sampleCount = 0, comparisonCount = 0): Promise<CostEstimate> {
    const res = await apiClient.get<CostEstimate>('/cookies/estimate', {
      params: { flow_id: flowId, sample_count: sampleCount, comparison_count: comparisonCount },
    })
    return res.data
  }

  function updateBalanceFromWebSocket(data: { balance: number; frozen_balance: number }) {
    if (account.value) {
      const b = toNum(data.balance)
      const f = toNum(data.frozen_balance)
      account.value.balance = b
      account.value.frozen_balance = f
      account.value.available_balance = b - f
    }
  }

  return { account, transactions, loading, balance, isLoggedIn, fetchAccount, fetchTransactions, estimateCost, updateBalanceFromWebSocket }
})
