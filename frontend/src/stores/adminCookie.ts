/**
 * 饼干账户管理 — 管理端 Store
 *
 * 取代原 useCookieAccounts.ts 的 Mock 数据源，对接真实后端：
 *   GET  /admin/cookies/accounts            （JOIN 用户身份/角色/课题组/存储）
 *   GET  /admin/cookies/stats               （系统大盘）
 *   GET  /admin/cookies/transactions/filtered?user_id=  （单用户流水，供抽屉）
 *   POST /admin/cookies/accounts/{user_id}/adjust       （充值/扣减，复用于 RechargeModal）
 *
 * 与「用户管理」共用同一份 users↔cookie_accounts JOIN 视图，确保两页数据一致。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'

export interface AdminCookieAccount {
  id: number | null
  user_id: string
  balance: number
  frozen_balance: number
  available_balance: number
  total_earned: number
  total_spent: number
  total_adjusted: number
  status: string
  created_at: string | null
  // 关联用户身份
  username: string
  nickname?: string | null
  email: string
  role: string
  lab_group: string | null
  user_status: string
  user_created_at: string | null
  storage_quota: number
  used_storage: number
}

export interface AdminCookieStats {
  total_accounts: number
  active_accounts: number
  total_balance: number
  total_frozen: number
  total_earned: number
  total_spent: number
}

export interface AdminCookieTxn {
  id: number | null
  user_id: string
  username: string
  nickname?: string | null
  email: string
  txn_type: string
  amount: number
  balance_after: number
  source_type: string
  source_id: string
  task_type: string
  description: string
  created_at: string | null
}

export const useAdminCookieStore = defineStore('adminCookie', () => {
  const accounts = ref<AdminCookieAccount[]>([])
  const stats = ref<AdminCookieStats | null>(null)
  const loading = ref(false)
  const search = ref('')
  const statusFilter = ref<'all' | string>('all')

  async function fetchAccounts() {
    loading.value = true
    try {
      const params: Record<string, string | number> = { offset: 0, limit: 200 }
      if (statusFilter.value && statusFilter.value !== 'all') params.status = statusFilter.value
      if (search.value.trim()) params.search = search.value.trim()
      const res = await apiClient.get<AdminCookieAccount[]>('/admin/cookies/accounts', { params })
      accounts.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const res = await apiClient.get<AdminCookieStats>('/admin/cookies/stats')
      stats.value = res.data
    } catch {
      stats.value = null
    }
  }

  /** 拉取单用户流水（供详情抽屉时间线） */
  async function fetchUserTxns(userId: string): Promise<AdminCookieTxn[]> {
    const res = await apiClient.get<{ items: AdminCookieTxn[]; total: number }>('/admin/cookies/transactions/filtered', {
      params: { user_id: userId, offset: 0, limit: 200 },
    })
    return res.data.items
  }

  /** 充值/扣减：amount 为正=增加，为负=扣除；后端 adjust 端点按带符号金额记账 */
  async function adjust(userId: string, amount: number, reason: string) {
    const res = await apiClient.post(`/admin/cookies/accounts/${userId}/adjust`, { amount, reason })
    return res.data
  }

  return {
    accounts,
    stats,
    loading,
    search,
    statusFilter,
    fetchAccounts,
    fetchStats,
    fetchUserTxns,
    adjust,
  }
})
