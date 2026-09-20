# CygnusX 🥫 饼干积分系统 — 前端完整设计文档

> 技术栈：Vue 3 + TypeScript + Vite + Naive UI + Pinia + ECharts  
> 版本：v1.0  |  作者：CygnusX Frontend Team

---

## 目录

1. [TypeScript 类型定义](#1-typescript-类型定义)
2. [Pinia Store — cookie.ts](#2-pinia-store)
3. [WebSocket Composable — useCookieWebSocket](#3-websocket-composable)
4. [全局组件 — CookieBalanceBadge.vue](#4-cookiebalancebadgevue)
5. [用户页面 — CookieAccountView.vue](#5-cookieaccountviewvue)
6. [管理后台 — AdminCookieManagementView.vue](#6-admincookiemanagementviewvue)
7. [管理弹窗 — CookieAdjustModal.vue](#7-cookieadjustmodalvue)
8. [交易流水 — AdminCookieTransactionsView.vue](#8-admincookietransactionsviewvue)
9. [定价策略 — AdminCookiePricingView.vue](#9-admincookiepricingviewvue)
10. [任务提交 — TaskSubmitView.vue 饼干预估更新](#10-tasksubmitvue-饼干预估更新)
11. [路由配置](#11-路由配置)
12. [API 接口清单](#12-api-接口清单)

---

## 1. TypeScript 类型定义

```typescript
// types/cookie.d.ts

/** 交易类型 */
export type TransactionType = 'earn' | 'spend' | 'adjust' | 'refund' | 'recharge'

/** 账户状态 */
export type AccountStatus = 'active' | 'frozen' | 'suspended'

/** 定价生效状态 */
export type PricingStatus = 'active' | 'inactive'

/** 资源类型 */
export type ResourceType = 'cpu' | 'memory' | 'gpu'

/** 任务流程类别 */
export type FlowCategory =
  | 'rna_seq'
  | 'chip_seq'
  | 'atac_seq'
  | 'wgs'
  | 'proteomics'
  | 'metabolomics'
  | 'sc_rna_seq'
  | 'data_integration'

// ─────────────────────────────────────────────
// 账户相关
// ─────────────────────────────────────────────

export interface CookieAccount {
  userId: number
  userName: string
  email: string
  avatar?: string
  balance: number
  totalEarned: number
  totalSpent: number
  status: AccountStatus
  lastActiveAt: string
  createdAt: string
  updatedAt: string
}

export interface CookieAccountSummary {
  currentBalance: number
  monthlySpent: number
  monthlyEarned: number
  groupRank: number       // 组内消费排名
  totalGroupMembers: number
}

// ─────────────────────────────────────────────
// 交易流水
// ─────────────────────────────────────────────

export interface CookieTransaction {
  id: number
  userId: number
  userName: string
  type: TransactionType
  amount: number          // 正数 = 收入，负数 = 支出
  balanceAfter: number    // 变动后余额
  description: string
  relatedTaskId?: number  // 关联任务ID
  relatedFlowCategory?: FlowCategory
  operatorId?: number     // 操作者ID（管理员操作）
  operatorName?: string
  createdAt: string
}

export interface TransactionFilters {
  type?: TransactionType | 'all'
  startDate?: string
  endDate?: string
  minAmount?: number
  maxAmount?: number
  page?: number
  pageSize?: number
}

// ─────────────────────────────────────────────
// 费用预估
// ─────────────────────────────────────────────

export interface ResourceEstimate {
  resourceType: ResourceType
  quantity: number        // CPU核数 / 内存GB / GPU卡数
  duration: number        // 小时
  unitPrice: number       // 每小时单价
  subtotal: number
}

export interface CostEstimate {
  flowCategory: FlowCategory
  baseFee: number
  resources: ResourceEstimate[]
  total: number
  discountRate: number    // 折扣率（如0.9 = 9折）
  discountedTotal: number
  currencyUnit: string    // "cookie"
}

export interface EstimateParams {
  flowCategory: FlowCategory
  cpuCores: number
  memoryGb: number
  gpuCards?: number
  estimatedHours: number
}

// ─────────────────────────────────────────────
// 管理员相关
// ─────────────────────────────────────────────

export interface AdminAccountFilters {
  search?: string         // 用户名/邮箱搜索
  status?: AccountStatus | 'all'
  sortBy?: 'balance' | 'totalSpent' | 'lastActiveAt'
  sortOrder?: 'asc' | 'desc'
  page?: number
  pageSize?: number
}

export interface CookieAdjustParams {
  userId: number
  amount: number          // 正数充值 / 负数扣减
  reason: string
  password: string        // 管理员二次确认密码
}

// ─────────────────────────────────────────────
// 定价策略
// ─────────────────────────────────────────────

export interface CookiePricing {
  id: number
  flowCategory: FlowCategory
  resourceType: ResourceType
  unitPrice: number       // 每小时单价（饼干）
  description: string
  status: PricingStatus
  effectiveFrom: string
  effectiveTo?: string
  createdAt: string
  updatedAt: string
}

export interface PricingFormData {
  flowCategory: FlowCategory
  resourceType: ResourceType
  unitPrice: number
  description: string
  effectiveFrom: string
  effectiveTo?: string
}

// ─────────────────────────────────────────────
// WebSocket 事件
// ─────────────────────────────────────────────

export interface BalanceUpdatedEvent {
  type: 'cookie.balance_updated'
  payload: {
    newBalance: number
    change: number
    reason: string
    timestamp: string
  }
}

export interface SystemStatsEvent {
  type: 'cookie.system_stats'
  payload: {
    totalCirculation: number
    todayConsumption: number
    activeAccounts: number
    pendingRecharges: number
  }
}

export type CookieWebSocketEvent = BalanceUpdatedEvent | SystemStatsEvent

// ─────────────────────────────────────────────
// 图表数据
// ─────────────────────────────────────────────

export interface DailyTrend {
  date: string
  spent: number
  earned: number
}

export interface CategoryBreakdown {
  category: FlowCategory
  label: string
  amount: number
  percentage: number
}

export interface AccountStats {
  dailyTrend: DailyTrend[]
  categoryBreakdown: CategoryBreakdown[]
}

// ─────────────────────────────────────────────
// 系统统计（管理员）
// ─────────────────────────────────────────────

export interface SystemStatistics {
  totalCirculation: number    // 系统总流通饼干
  todayConsumption: number
  todayRecharge: number
  activeAccounts: number
  frozenAccounts: number
  pendingRecharges: number
  monthlyGrowth: number       // 月增长率
}
```

---

## 2. Pinia Store

```typescript
// stores/modules/cookie.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  CookieAccount,
  CookieAccountSummary,
  CookieTransaction,
  TransactionFilters,
  CookiePricing,
  CostEstimate,
  EstimateParams,
  AdminAccountFilters,
  CookieAdjustParams,
  AccountStats,
  SystemStatistics,
  BalanceUpdatedEvent,
  CookieWebSocketEvent,
} from '@/types/cookie'
import { useWebSocket } from '@/composables/useWebSocket'

export const useCookieStore = defineStore('cookie', () => {
  // ═══════════════════════════════════════════
  // State
  // ═══════════════════════════════════════════

  const account = ref<CookieAccount | null>(null)
  const accountSummary = ref<CookieAccountSummary | null>(null)
  const transactions = ref<CookieTransaction[]>([])
  const transactionTotal = ref(0)
  const pricing = ref<CookiePricing[]>([])
  const estimate = ref<CostEstimate | null>(null)
  const accountStats = ref<AccountStats | null>(null)
  const systemStats = ref<SystemStatistics | null>(null)
  const adminAccounts = ref<CookieAccount[]>([])
  const adminAccountTotal = ref(0)
  const isLoading = ref(false)
  const wsConnected = ref(false)

  // 最近3笔交易（用于 Header 悬浮卡片）
  const recentTransactions = computed(() => transactions.value.slice(0, 3))

  // 格式化余额
  const formattedBalance = computed(() => {
    if (!account.value) return '0'
    return account.value.balance.toLocaleString()
  })

  // 余额是否充足
  const hasEnoughBalance = computed(() => {
    if (!account.value || !estimate.value) return false
    return account.value.balance >= estimate.value.discountedTotal
  })

  // ═══════════════════════════════════════════
  // Actions — 个人账户
  // ═══════════════════════════════════════════

  /** 获取当前用户账户信息 */
  async function fetchAccount() {
    isLoading.value = true
    try {
      const res = await fetch('/api/v1/cookies/account')
      const data = await res.json()
      account.value = data.data
    } catch (err) {
      console.error('获取饼干账户失败:', err)
      throw err
    } finally {
      isLoading.value = false
    }
  }

  /** 获取账户统计摘要 */
  async function fetchAccountSummary() {
    try {
      const res = await fetch('/api/v1/cookies/account/summary')
      const data = await res.json()
      accountSummary.value = data.data
    } catch (err) {
      console.error('获取账户摘要失败:', err)
    }
  }

  /** 获取交易流水 */
  async function fetchTransactions(filters: TransactionFilters = {}) {
    isLoading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.type && filters.type !== 'all') params.append('type', filters.type)
      if (filters.startDate) params.append('startDate', filters.startDate)
      if (filters.endDate) params.append('endDate', filters.endDate)
      if (filters.minAmount !== undefined) params.append('minAmount', String(filters.minAmount))
      if (filters.maxAmount !== undefined) params.append('maxAmount', String(filters.maxAmount))
      params.append('page', String(filters.page ?? 1))
      params.append('pageSize', String(filters.pageSize ?? 20))

      const res = await fetch(`/api/v1/cookies/transactions?${params}`)
      const data = await res.json()
      transactions.value = data.data.list
      transactionTotal.value = data.data.total
    } catch (err) {
      console.error('获取交易流水失败:', err)
    } finally {
      isLoading.value = false
    }
  }

  /** 获取图表统计数据 */
  async function fetchAccountStats() {
    try {
      const res = await fetch('/api/v1/cookies/account/stats')
      const data = await res.json()
      accountStats.value = data.data
    } catch (err) {
      console.error('获取账户统计失败:', err)
    }
  }

  // ═══════════════════════════════════════════
  // Actions — 费用预估
  // ═══════════════════════════════════════════

  /** 预估任务费用 */
  async function estimateTaskCost(params: EstimateParams) {
    try {
      const res = await fetch('/api/v1/cookies/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
      const data = await res.json()
      estimate.value = data.data
      return data.data
    } catch (err) {
      console.error('费用预估失败:', err)
      estimate.value = null
      throw err
    }
  }

  /** 清除预估 */
  function clearEstimate() {
    estimate.value = null
  }

  // ═══════════════════════════════════════════
  // Actions — 管理员功能
  // ═══════════════════════════════════════════

  /** 获取系统统计（管理员） */
  async function fetchSystemStats() {
    try {
      const res = await fetch('/api/v1/admin/cookies/statistics')
      const data = await res.json()
      systemStats.value = data.data
    } catch (err) {
      console.error('获取系统统计失败:', err)
    }
  }

  /** 获取用户账户列表（管理员） */
  async function fetchAdminAccounts(filters: AdminAccountFilters = {}) {
    isLoading.value = true
    try {
      const params = new URLSearchParams()
      if (filters.search) params.append('search', filters.search)
      if (filters.status && filters.status !== 'all') params.append('status', filters.status)
      if (filters.sortBy) params.append('sortBy', filters.sortBy)
      if (filters.sortOrder) params.append('sortOrder', filters.sortOrder)
      params.append('page', String(filters.page ?? 1))
      params.append('pageSize', String(filters.pageSize ?? 20))

      const res = await fetch(`/api/v1/admin/cookies/accounts?${params}`)
      const data = await res.json()
      adminAccounts.value = data.data.list
      adminAccountTotal.value = data.data.total
    } catch (err) {
      console.error('获取用户账户列表失败:', err)
    } finally {
      isLoading.value = false
    }
  }

  /** 调整用户余额（充值/扣减） */
  async function adjustBalance(params: CookieAdjustParams) {
    const res = await fetch(`/api/v1/admin/cookies/accounts/${params.userId}/adjust`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: params.amount,
        reason: params.reason,
        password: params.password,
      }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '调整余额失败')
    }
    const data = await res.json()
    // 刷新列表
    await fetchAdminAccounts()
    return data.data
  }

  /** 冻结/解冻账户 */
  async function toggleAccountStatus(userId: number, status: 'active' | 'frozen') {
    const res = await fetch(`/api/v1/admin/cookies/accounts/${userId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '操作失败')
    }
    // 更新本地状态
    const idx = adminAccounts.value.findIndex(a => a.userId === userId)
    if (idx !== -1) {
      adminAccounts.value[idx].status = status
    }
    return await res.json()
  }

  // ═══════════════════════════════════════════
  // Actions — 定价策略
  // ═══════════════════════════════════════════

  /** 获取定价策略列表 */
  async function fetchPricing() {
    try {
      const res = await fetch('/api/v1/admin/cookies/pricing')
      const data = await res.json()
      pricing.value = data.data
    } catch (err) {
      console.error('获取定价策略失败:', err)
    }
  }

  /** 创建定价策略 */
  async function createPricing(data: PricingFormData) {
    const res = await fetch('/api/v1/admin/cookies/pricing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '创建失败')
    }
    await fetchPricing()
    return await res.json()
  }

  /** 更新定价策略 */
  async function updatePricing(id: number, data: Partial<PricingFormData>) {
    const res = await fetch(`/api/v1/admin/cookies/pricing/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.message || '更新失败')
    }
    await fetchPricing()
    return await res.json()
  }

  /** 切换定价状态 */
  async function togglePricingStatus(id: number, status: PricingStatus) {
    return updatePricing(id, { status })
  }

  // ═══════════════════════════════════════════
  // Actions — WebSocket
  // ═══════════════════════════════════════════

  let wsCleanup: (() => void) | null = null

  /** 订阅余额变动推送 */
  function subscribeBalanceUpdates() {
    const { connect, disconnect, onMessage } = useWebSocket()

    connect('/ws/cookies')
    wsConnected.value = true

    const unsubscribe = onMessage((event: CookieWebSocketEvent) => {
      if (event.type === 'cookie.balance_updated') {
        handleBalanceUpdate(event.payload)
      } else if (event.type === 'cookie.system_stats') {
        systemStats.value = event.payload
      }
    })

    wsCleanup = () => {
      unsubscribe()
      disconnect()
      wsConnected.value = false
    }
  }

  /** 处理余额更新事件 */
  function handleBalanceUpdate(payload: BalanceUpdatedEvent['payload']) {
    if (account.value) {
      account.value.balance = payload.newBalance
      // 如果 change > 0 则增加 totalEarned，否则增加 totalSpent
      if (payload.change > 0) {
        account.value.totalEarned += payload.change
      } else {
        account.value.totalSpent += Math.abs(payload.change)
      }
    }
    // 触发 UI 动画效果
    if (typeof document !== 'undefined') {
      document.dispatchEvent(new CustomEvent('cookie-balance-bump', {
        detail: payload,
      }))
    }
  }

  /** 取消订阅 */
  function unsubscribeBalanceUpdates() {
    wsCleanup?.()
    wsCleanup = null
  }

  // ═══════════════════════════════════════════
  // Return
  // ═══════════════════════════════════════════

  return {
    // State
    account,
    accountSummary,
    transactions,
    transactionTotal,
    pricing,
    estimate,
    accountStats,
    systemStats,
    adminAccounts,
    adminAccountTotal,
    isLoading,
    wsConnected,

    // Computed
    recentTransactions,
    formattedBalance,
    hasEnoughBalance,

    // Actions
    fetchAccount,
    fetchAccountSummary,
    fetchTransactions,
    fetchAccountStats,
    estimateTaskCost,
    clearEstimate,
    fetchSystemStats,
    fetchAdminAccounts,
    adjustBalance,
    toggleAccountStatus,
    fetchPricing,
    createPricing,
    updatePricing,
    togglePricingStatus,
    subscribeBalanceUpdates,
    unsubscribeBalanceUpdates,
  }
})
```

---

## 3. WebSocket Composable

```typescript
// composables/useWebSocket.ts
import { ref, onUnmounted } from 'vue'

export function useWebSocket() {
  const ws = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  const messageHandlers = ref<((event: any) => void)[]>([])

  function connect(url: string) {
    // 支持自动协议切换和 token 注入
    const token = localStorage.getItem('access_token')
    const fullUrl = `${url}?token=${token}`

    ws.value = new WebSocket(fullUrl)

    ws.value.onopen = () => {
      isConnected.value = true
      console.log('[WebSocket] 已连接:', url)
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        messageHandlers.value.forEach(handler => handler(data))
      } catch (err) {
        console.error('[WebSocket] 消息解析失败:', err)
      }
    }

    ws.value.onclose = () => {
      isConnected.value = false
      console.log('[WebSocket] 连接已关闭')
    }

    ws.value.onerror = (err) => {
      console.error('[WebSocket] 错误:', err)
      isConnected.value = false
    }

    // 页面关闭时自动断开
    onUnmounted(() => {
      disconnect()
    })
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
      isConnected.value = false
    }
  }

  function onMessage(handler: (event: any) => void) {
    messageHandlers.value.push(handler)
    // 返回取消订阅函数
    return () => {
      const idx = messageHandlers.value.indexOf(handler)
      if (idx !== -1) messageHandlers.value.splice(idx, 1)
    }
  }

  function send(data: any) {
    if (ws.value?.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(data))
    } else {
      console.warn('[WebSocket] 连接未就绪，无法发送消息')
    }
  }

  return {
    ws,
    isConnected,
    connect,
    disconnect,
    onMessage,
    send,
  }
}
```

---

## 4. CookieBalanceBadge.vue

```vue
<!-- components/cookie/CookieBalanceBadge.vue -->
<template>
  <n-popover trigger="hover" :delay="200" :duration="300" :show-arrow="false">
    <template #trigger>
      <n-button text class="cookie-balance-btn" @click="handleClick">
        <n-badge
          :value="badgeValue"
          :max="99999"
          :type="badgeType"
          :show-zero="false"
          :offset="[-4, 4]"
        >
          <n-icon
            size="20"
            class="cookie-icon"
            :class="{ 'bump-animation': isBumping }"
          >
            <CookieOutline />
          </n-icon>
        </n-badge>
        <n-text :depth="1" class="balance-text">
          {{ formattedBalance }}
        </n-text>
      </n-button>
    </template>

    <!-- 悬浮卡片内容 -->
    <div class="cookie-popover-card">
      <!-- 余额展示 -->
      <div class="balance-section">
        <n-statistic label="我的饼干余额" tabular-nums>
          <template #prefix>
            <n-icon size="24" color="#f5a623">
              <CookieOutline />
            </n-icon>
          </template>
          <n-number-animation
            :from="prevBalance"
            :to="currentBalance"
            :duration="800"
          />
          <template #suffix>🥫</template>
        </n-statistic>
      </div>

      <n-divider style="margin: 8px 0" />

      <!-- 最近3笔交易 -->
      <div class="recent-transactions">
        <n-text depth="3" style="font-size: 12px;">近期变动</n-text>
        <n-empty
          v-if="!recentTransactions.length"
          description="暂无记录"
          size="small"
        />
        <n-space v-else vertical :size="4" style="margin-top: 6px;">
          <n-space
            v-for="tx in recentTransactions"
            :key="tx.id"
            justify="space-between"
            align="center"
            class="tx-item"
          >
            <n-space align="center" :size="6">
              <n-tag
                :type="getTxTypeColor(tx.type)"
                size="tiny"
                round
              >
                {{ getTxTypeLabel(tx.type) }}
              </n-tag>
              <n-ellipsis style="max-width: 120px; font-size: 12px;">
                {{ tx.description }}
              </n-ellipsis>
            </n-space>
            <n-text
              :type="tx.amount > 0 ? 'success' : 'error'"
              strong
              style="font-size: 13px;"
            >
              {{ tx.amount > 0 ? '+' : '' }}{{ tx.amount }}
            </n-text>
          </n-space>
        </n-space>
      </div>

      <n-divider style="margin: 8px 0" />

      <!-- 快捷入口 -->
      <n-space justify="space-between" align="center">
        <n-text depth="3" style="font-size: 12px;">
          账户状态：
          <n-tag
            :type="account?.status === 'active' ? 'success' : 'error'"
            size="tiny"
            round
          >
            {{ account?.status === 'active' ? '正常' : '已冻结' }}
          </n-tag>
        </n-text>
        <n-button
          text
          type="primary"
          size="tiny"
          @click="handleClick"
        >
          查看明细 →
        </n-button>
      </n-space>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPopover, NBadge, NButton, NIcon, NText, NStatistic,
  NNumberAnimation, NDivider, NSpace, NTag, NEmpty, NEllipsis,
} from 'naive-ui'
import { CookieOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── Local State ────────────────────────────
const isBumping = ref(false)
const prevBalance = ref(0)
const currentBalance = computed(() => account.value?.balance ?? 0)
const bumpTimer = ref<ReturnType<typeof setTimeout> | null>(null)

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const formattedBalance = computed(() => cookieStore.formattedBalance)
const recentTransactions = computed<CookieTransaction[]>(() => cookieStore.recentTransactions)

const badgeValue = computed(() => {
  // 仅在有变动时显示红点提示
  return 0 // 动态红点逻辑可由外部控制
})

const badgeType = computed(() => 'warning' as const)

// ── Watchers ───────────────────────────────

// 监听余额变化 → 触发弹跳动画
watch(() => account.value?.balance, (newVal, oldVal) => {
  if (newVal !== undefined && oldVal !== undefined && newVal !== oldVal) {
    prevBalance.value = oldVal
    triggerBumpAnimation()
  }
}, { immediate: false })

// 监听全局余额变动事件
function handleBalanceBumpEvent(e: Event) {
  triggerBumpAnimation()
}

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  // 订阅 WebSocket 余额推送
  cookieStore.subscribeBalanceUpdates()
  // 获取账户信息
  cookieStore.fetchAccount()
  cookieStore.fetchTransactions({ pageSize: 3 })
  // 监听全局动画事件
  document.addEventListener('cookie-balance-bump', handleBalanceBumpEvent)
})

onUnmounted(() => {
  cookieStore.unsubscribeBalanceUpdates()
  document.removeEventListener('cookie-balance-bump', handleBalanceBumpEvent)
  if (bumpTimer.value) clearTimeout(bumpTimer.value)
})

// ── Methods ────────────────────────────────

function triggerBumpAnimation() {
  isBumping.value = true
  if (bumpTimer.value) clearTimeout(bumpTimer.value)
  bumpTimer.value = setTimeout(() => {
    isBumping.value = false
  }, 600)
}

function handleClick() {
  router.push('/cookies/account')
}

function getTxTypeColor(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxTypeLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得',
    spend: '消费',
    adjust: '调整',
    refund: '退款',
    recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.cookie-balance-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.2s;
}

.cookie-balance-btn:hover {
  background-color: var(--n-button-color-hover);
}

.cookie-icon {
  color: #f5a623;
  transition: transform 0.3s ease;
}

.balance-text {
  font-weight: 600;
  font-size: 14px;
  color: #f5a623;
}

/* 弹跳动画 */
@keyframes cookie-bump {
  0%   { transform: scale(1) rotate(0deg); }
  25%  { transform: scale(1.25) rotate(-10deg); }
  50%  { transform: scale(1.1) rotate(5deg); }
  75%  { transform: scale(1.2) rotate(-5deg); }
  100% { transform: scale(1) rotate(0deg); }
}

.bump-animation {
  animation: cookie-bump 0.6s ease-in-out;
}

/* 悬浮卡片样式 */
.cookie-popover-card {
  min-width: 260px;
  padding: 4px;
}

.balance-section {
  text-align: center;
  padding: 8px 0;
}

.recent-transactions {
  max-height: 180px;
  overflow-y: auto;
}

.tx-item {
  padding: 4px 6px;
  border-radius: 6px;
  transition: background-color 0.15s;
}

.tx-item:hover {
  background-color: var(--n-action-color);
}

/* 暗色模式适配 */
:deep(.n-statistic-value) {
  color: var(--n-text-color);
}

:deep(.n-statistic-value__suffix) {
  font-size: 18px;
}
</style>
```

---

## 5. CookieAccountView.vue

```vue
<!-- views/cookie/CookieAccountView.vue -->
<template>
  <div class="cookie-account-page">
    <!-- 页面标题 -->
    <n-page-header title="🥫 我的饼干账户" subtitle="查看饼干余额、交易流水与消费统计" />

    <n-space vertical :size="24" style="margin-top: 20px;">

      <!-- ═══════════ 顶部统计卡片行 ═══════════ -->
      <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
        <!-- 当前余额 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--primary" :bordered="false">
            <n-statistic label="当前余额" tabular-nums>
              <template #prefix>
                <n-icon size="28" color="#f5a623"><CookieOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--primary">
                {{ formattedBalance }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-tag
              :type="account?.status === 'active' ? 'success' : 'error'"
              size="small"
              round
              class="status-tag"
            >
              {{ account?.status === 'active' ? '账户正常' : '账户已冻结' }}
            </n-tag>
          </n-card>
        </n-grid-item>

        <!-- 本月消费 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--danger" :bordered="false">
            <n-statistic label="本月消费" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#d03050"><TrendingDownOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--danger">
                {{ summary?.monthlySpent ?? 0 }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">较上月 --</n-text>
          </n-card>
        </n-grid-item>

        <!-- 本月获得 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--success" :bordered="false">
            <n-statistic label="本月获得" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#18a058"><TrendingUpOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--success">
                {{ summary?.monthlyEarned ?? 0 }}
              </span>
              <template #suffix>🥫</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">含系统奖励</n-text>
          </n-card>
        </n-grid-item>

        <!-- 组内排名 -->
        <n-grid-item span="1 s:2 m:1">
          <n-card class="stat-card stat-card--info" :bordered="false">
            <n-statistic label="消费排名" tabular-nums>
              <template #prefix>
                <n-icon size="22" color="#2080f0"><TrophyOutline /></n-icon>
              </template>
              <span class="stat-number stat-number--info">
                {{ summary?.groupRank ?? '--' }}
              </span>
              <template #suffix>/ {{ summary?.totalGroupMembers ?? '--' }}</template>
            </n-statistic>
            <n-text depth="3" style="font-size: 12px;">组内排名</n-text>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 中部图表区 ═══════════ -->
      <n-grid :cols="2" :x-gap="16" :y-gap="16" responsive="screen">
        <!-- 消费趋势折线图 -->
        <n-grid-item span="2 m:1">
          <n-card title="📈 消费趋势（近30天）" :bordered="false">
            <div ref="trendChartRef" class="chart-container" />
          </n-card>
        </n-grid-item>

        <!-- 消费类型饼图 -->
        <n-grid-item span="2 m:1">
          <n-card title="📊 消费构成" :bordered="false">
            <div ref="pieChartRef" class="chart-container" />
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 底部交易流水表格 ═══════════ -->
      <n-card title="🧾 交易流水" :bordered="false">
        <!-- 筛选条件 -->
        <n-space align="center" wrap :size="12" style="margin-bottom: 16px;">
          <n-select
            v-model:value="filters.type"
            :options="typeOptions"
            placeholder="交易类型"
            clearable
            style="width: 140px;"
          />
          <n-date-picker
            v-model:formatted-value="filters.startDate"
            type="date"
            placeholder="开始日期"
            value-format="yyyy-MM-dd"
          />
          <n-date-picker
            v-model:formatted-value="filters.endDate"
            type="date"
            placeholder="结束日期"
            value-format="yyyy-MM-dd"
          />
          <n-input-number
            v-model:value="filters.minAmount"
            placeholder="最小金额"
            :min="0"
            style="width: 130px;"
          />
          <n-input-number
            v-model:value="filters.maxAmount"
            placeholder="最大金额"
            :min="0"
            style="width: 130px;"
          />
          <n-button type="primary" @click="handleSearch">
            <template #icon><n-icon><SearchOutline /></n-icon></template>
            查询
          </n-button>
          <n-button @click="handleReset">重置</n-button>
        </n-space>

        <!-- 表格 -->
        <n-data-table
          :columns="columns"
          :data="transactions"
          :loading="isLoading"
          :pagination="pagination"
          :row-key="(row: CookieTransaction) => row.id"
          @update:page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        />
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NGrid, NGridItem, NCard, NStatistic, NIcon,
  NText, NTag, NSpace, NSelect, NDatePicker, NInputNumber,
  NButton, NDataTable, NDivider, NEllipsis, NEmpty,
} from 'naive-ui'
import {
  CookieOutline, TrendingDownOutline, TrendingUpOutline,
  TrophyOutline, SearchOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType, TransactionFilters } from '@/types/cookie'
import * as echarts from 'echarts'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const router = useRouter()
const cookieStore = useCookieStore()

// ── Refs ───────────────────────────────────
const trendChartRef = ref<HTMLDivElement>()
const pieChartRef = ref<HTMLDivElement>()
let trendChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null

// ── Filters ────────────────────────────────
const filters = ref<TransactionFilters>({
  type: 'all',
  startDate: undefined,
  endDate: undefined,
  minAmount: undefined,
  maxAmount: undefined,
  page: 1,
  pageSize: 20,
})

const typeOptions: SelectOption[] = [
  { label: '全部类型', value: 'all' },
  { label: '获得', value: 'earn' },
  { label: '消费', value: 'spend' },
  { label: '调整', value: 'adjust' },
  { label: '退款', value: 'refund' },
  { label: '充值', value: 'recharge' },
]

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const summary = computed(() => cookieStore.accountSummary)
const transactions = computed(() => cookieStore.transactions)
const transactionTotal = computed(() => cookieStore.transactionTotal)
const isLoading = computed(() => cookieStore.isLoading)
const formattedBalance = computed(() => cookieStore.formattedBalance)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 20,
  pageCount: Math.ceil(transactionTotal.value / (filters.value.pageSize ?? 20)),
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  showQuickJumper: true,
  prefix: () => `共 ${transactionTotal.value} 条`,
}))

// ── Table Columns ──────────────────────────
const columns = computed<DataTableColumns<CookieTransaction>>(() => [
  {
    title: '时间',
    key: 'createdAt',
    width: 170,
    render: (row) => formatDate(row.createdAt),
  },
  {
    title: '类型',
    key: 'type',
    width: 100,
    render: (row) => h(NTag, {
      type: getTxTagType(row.type),
      size: 'small',
      round: true,
    }, { default: () => getTxLabel(row.type) }),
  },
  {
    title: '金额',
    key: 'amount',
    width: 120,
    align: 'right',
    render: (row) => h('span', {
      style: {
        color: row.amount > 0 ? '#18a058' : '#d03050',
        fontWeight: 600,
      },
    }, `${row.amount > 0 ? '+' : ''}${row.amount} 🥫`),
  },
  {
    title: '余额',
    key: 'balanceAfter',
    width: 120,
    align: 'right',
    render: (row) => `${row.balanceAfter.toLocaleString()} 🥫`,
  },
  {
    title: '描述',
    key: 'description',
    render: (row) => h(NEllipsis, { style: 'max-width: 300px;' }, {
      default: () => row.description,
    }),
  },
  {
    title: '操作者',
    key: 'operatorName',
    width: 120,
    render: (row) => row.operatorName || '--',
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchAccount()
  cookieStore.fetchAccountSummary()
  cookieStore.fetchTransactions()
  cookieStore.fetchAccountStats()

  // 延迟初始化图表（确保 DOM 已渲染）
  setTimeout(() => {
    initTrendChart()
    initPieChart()
  }, 300)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  trendChart?.dispose()
  pieChart?.dispose()
  window.removeEventListener('resize', handleResize)
})

// ── Chart Methods ──────────────────────────

function initTrendChart() {
  if (!trendChartRef.value) return
  trendChart = echarts.init(trendChartRef.value, undefined, { renderer: 'svg' })

  const stats = cookieStore.accountStats
  const dates = stats?.dailyTrend.map(d => d.date) ?? []
  const spentData = stats?.dailyTrend.map(d => d.spent) ?? []
  const earnedData = stats?.dailyTrend.map(d => d.earned) ?? []

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'var(--n-card-color)',
      borderColor: 'var(--n-border-color)',
      textStyle: { color: 'var(--n-text-color)' },
    },
    legend: {
      data: ['消费', '获得'],
      textStyle: { color: 'var(--n-text-color)' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
      axisLine: { lineStyle: { color: 'var(--n-text-color-disabled)' } },
      axisLabel: { color: 'var(--n-text-color)' },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: 'var(--n-divider-color)' } },
      axisLabel: { color: 'var(--n-text-color)' },
    },
    series: [
      {
        name: '消费',
        type: 'line',
        smooth: true,
        data: spentData,
        itemStyle: { color: '#d03050' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(208, 48, 80, 0.3)' },
            { offset: 1, color: 'rgba(208, 48, 80, 0.02)' },
          ]),
        },
      },
      {
        name: '获得',
        type: 'line',
        smooth: true,
        data: earnedData,
        itemStyle: { color: '#18a058' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(24, 160, 88, 0.3)' },
            { offset: 1, color: 'rgba(24, 160, 88, 0.02)' },
          ]),
        },
      },
    ],
  }

  trendChart.setOption(option)
}

function initPieChart() {
  if (!pieChartRef.value) return
  pieChart = echarts.init(pieChartRef.value, undefined, { renderer: 'svg' })

  const stats = cookieStore.accountStats
  const data = stats?.categoryBreakdown.map(c => ({
    name: c.label,
    value: c.amount,
  })) ?? []

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 🥫 ({d}%)',
      backgroundColor: 'var(--n-card-color)',
      borderColor: 'var(--n-border-color)',
      textStyle: { color: 'var(--n-text-color)' },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { color: 'var(--n-text-color)' },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: 'var(--n-card-color)',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold',
            color: 'var(--n-text-color)',
          },
        },
        data,
      },
    ],
  }

  pieChart.setOption(option)
}

function handleResize() {
  trendChart?.resize()
  pieChart?.resize()
}

// ── Table Methods ──────────────────────────

function handleSearch() {
  filters.value.page = 1
  cookieStore.fetchTransactions(filters.value)
}

function handleReset() {
  filters.value = {
    type: 'all',
    startDate: undefined,
    endDate: undefined,
    minAmount: undefined,
    maxAmount: undefined,
    page: 1,
    pageSize: 20,
  }
  cookieStore.fetchTransactions(filters.value)
}

function handlePageChange(page: number) {
  filters.value.page = page
  cookieStore.fetchTransactions(filters.value)
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  cookieStore.fetchTransactions(filters.value)
}

// ── Helpers ────────────────────────────────

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getTxTagType(type: TransactionType) {
  const map: Record<string, 'success' | 'error' | 'info' | 'warning' | 'default'> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得',
    spend: '消费',
    adjust: '调整',
    refund: '退款',
    recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.cookie-account-page {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.stat-card {
  border-radius: 12px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--n-box-shadow);
}

.stat-card :deep(.n-card__content) {
  padding: 16px;
}

.stat-number {
  font-size: 28px;
  font-weight: 700;
}

.stat-number--primary { color: #f5a623; }
.stat-number--danger  { color: #d03050; }
.stat-number--success { color: #18a058; }
.stat-number--info    { color: #2080f0; }

.status-tag {
  margin-top: 8px;
}

.chart-container {
  width: 100%;
  height: 280px;
}

/* 暗色模式图表文字颜色适配 */
:deep(.n-statistic__label) {
  color: var(--n-text-color-3);
}
</style>
```

---

## 6. AdminCookieManagementView.vue

```vue
<!-- views/admin/AdminCookieManagementView.vue -->
<template>
  <div class="admin-cookie-page">
    <!-- 页面标题 -->
    <n-page-header title="🥫 饼干管理" subtitle="管理系统饼干流通、用户账户与充值" />

    <n-space vertical :size="20" style="margin-top: 20px;">

      <!-- ═══════════ 统计概览卡片 ═══════════ -->
      <n-grid :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card" :bordered="false">
            <n-statistic label="系统总流通饼干">
              <template #prefix>
                <n-icon size="22" color="#f5a623"><ServerOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.totalCirculation ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--danger" :bordered="false">
            <n-statistic label="今日消费">
              <template #prefix>
                <n-icon size="22" color="#d03050"><TrendingDownOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.todayConsumption ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--success" :bordered="false">
            <n-statistic label="活跃账户数">
              <template #prefix>
                <n-icon size="22" color="#18a058"><PeopleOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.activeAccounts ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>

        <n-grid-item span="2 s:1 m:1">
          <n-card class="admin-stat-card admin-stat-card--warning" :bordered="false">
            <n-statistic label="待处理充值">
              <template #prefix>
                <n-icon size="22" color="#f0a020"><TimeOutline /></n-icon>
              </template>
              <n-number-animation
                :from="0"
                :to="systemStats?.pendingRecharges ?? 0"
                show-separator
              />
            </n-statistic>
          </n-card>
        </n-grid-item>
      </n-grid>

      <!-- ═══════════ 用户账户管理表格 ═══════════ -->
      <n-card title="👥 用户账户管理" :bordered="false">
        <!-- 搜索栏 -->
        <n-space align="center" wrap :size="12" style="margin-bottom: 16px;">
          <n-input
            v-model:value="filters.search"
            placeholder="搜索用户名或邮箱..."
            clearable
            style="width: 260px;"
          >
            <template #prefix>
              <n-icon><SearchOutline /></n-icon>
            </template>
          </n-input>
          <n-select
            v-model:value="filters.status"
            :options="statusOptions"
            placeholder="账户状态"
            clearable
            style="width: 140px;"
          />
          <n-select
            v-model:value="filters.sortBy"
            :options="sortOptions"
            placeholder="排序方式"
            style="width: 150px;"
          />
          <n-button type="primary" @click="handleSearch">
            <template #icon><n-icon><SearchOutline /></n-icon></template>
            查询
          </n-button>
          <n-button @click="handleReset">重置</n-button>
          <n-button @click="router.push('/admin/cookies/transactions')">
            <template #icon><n-icon><ListOutline /></n-icon></template>
            交易流水
          </n-button>
          <n-button @click="router.push('/admin/cookies/pricing')">
            <template #icon><n-icon><PricetagOutline /></n-icon></template>
            定价策略
          </n-button>
        </n-space>

        <!-- 用户账户表格 -->
        <n-data-table
          :columns="columns"
          :data="adminAccounts"
          :loading="isLoading"
          :pagination="pagination"
          :row-key="(row: CookieAccount) => row.userId"
          @update:page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        />
      </n-card>
    </n-space>

    <!-- ═══════════ 充值/扣减弹窗 ═══════════ -->
    <CookieAdjustModal
      v-model:show="showAdjustModal"
      :user="selectedUser"
      :mode="adjustMode"
      @success="handleAdjustSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NGrid, NGridItem, NCard, NStatistic, NIcon,
  NNumberAnimation, NSpace, NInput, NSelect, NButton,
  NDataTable, NTag, NPopconfirm, NText, NAvatar, NTooltip,
} from 'naive-ui'
import {
  ServerOutline, TrendingDownOutline, PeopleOutline,
  TimeOutline, SearchOutline, ListOutline, PricetagOutline,
  AddOutline, RemoveOutline, LockOpenOutline, LockClosedOutline,
  EyeOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import CookieAdjustModal from '@/components/cookie/CookieAdjustModal.vue'
import type { CookieAccount, AccountStatus, AdminAccountFilters } from '@/types/cookie'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const filters = ref<AdminAccountFilters>({
  search: '',
  status: 'all',
  sortBy: 'balance',
  sortOrder: 'desc',
  page: 1,
  pageSize: 20,
})
const showAdjustModal = ref(false)
const selectedUser = ref<CookieAccount | null>(null)
const adjustMode = ref<'recharge' | 'deduct'>('recharge')

// ── Options ────────────────────────────────
const statusOptions: SelectOption[] = [
  { label: '全部状态', value: 'all' },
  { label: '正常', value: 'active' },
  { label: '已冻结', value: 'frozen' },
  { label: '已停用', value: 'suspended' },
]

const sortOptions: SelectOption[] = [
  { label: '余额 ↓', value: 'balance' },
  { label: '总消费 ↓', value: 'totalSpent' },
  { label: '最近活跃 ↓', value: 'lastActiveAt' },
]

// ── Computed ───────────────────────────────
const adminAccounts = computed(() => cookieStore.adminAccounts)
const adminAccountTotal = computed(() => cookieStore.adminAccountTotal)
const isLoading = computed(() => cookieStore.isLoading)
const systemStats = computed(() => cookieStore.systemStats)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 20,
  pageCount: Math.ceil(adminAccountTotal.value / (filters.value.pageSize ?? 20)),
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  showQuickJumper: true,
  prefix: () => `共 ${adminAccountTotal.value} 个账户`,
}))

// ── Table Columns ──────────────────────────
const columns = computed<DataTableColumns<CookieAccount>>(() => [
  {
    title: '用户信息',
    key: 'userInfo',
    minWidth: 220,
    render: (row) => h(NSpace, { align: 'center', size: 10 }, {
      default: () => [
        h(NAvatar, {
          src: row.avatar,
          fallbackSrc: '/default-avatar.png',
          round: true,
          size: 36,
        }),
        h('div', {}, [
          h(NText, { strong: true }, { default: () => row.userName }),
          h('br'),
          h(NText, { depth: 3, style: 'font-size: 12px;' }, {
            default: () => row.email,
          }),
        ]),
      ],
    }),
  },
  {
    title: '当前余额',
    key: 'balance',
    width: 130,
    sorter: true,
    align: 'right',
    render: (row) => h(NText, {
      strong: true,
      style: { color: '#f5a623', fontSize: '15px' },
    }, { default: () => `${row.balance.toLocaleString()} 🥫` }),
  },
  {
    title: '总消费',
    key: 'totalSpent',
    width: 130,
    sorter: true,
    align: 'right',
    render: (row) => `${row.totalSpent.toLocaleString()} 🥫`,
  },
  {
    title: '总获得',
    key: 'totalEarned',
    width: 130,
    align: 'right',
    render: (row) => `${row.totalEarned.toLocaleString()} 🥫`,
  },
  {
    title: '账户状态',
    key: 'status',
    width: 110,
    render: (row) => {
      const statusMap: Record<AccountStatus, { type: 'success' | 'error' | 'warning', label: string }> = {
        active: { type: 'success', label: '正常' },
        frozen: { type: 'error', label: '已冻结' },
        suspended: { type: 'warning', label: '已停用' },
      }
      const s = statusMap[row.status]
      return h(NTag, { type: s.type, size: 'small', round: true }, {
        default: () => s.label,
      })
    },
  },
  {
    title: '最后活跃',
    key: 'lastActiveAt',
    width: 170,
    render: (row) => formatDateTime(row.lastActiveAt),
  },
  {
    title: '操作',
    key: 'actions',
    width: 280,
    fixed: 'right',
    render: (row) => h(NSpace, { size: 4 }, {
      default: () => [
        // 充值按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'success',
            ghost: true,
            onClick: () => openAdjustModal(row, 'recharge'),
          }, {
            icon: () => h(NIcon, null, { default: () => h(AddOutline) }),
            default: () => '充值',
          }),
          default: () => '增加用户饼干余额',
        }),
        // 扣减按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'error',
            ghost: true,
            onClick: () => openAdjustModal(row, 'deduct'),
          }, {
            icon: () => h(NIcon, null, { default: () => h(RemoveOutline) }),
            default: () => '扣减',
          }),
          default: () => '减少用户饼干余额',
        }),
        // 冻结/解冻按钮
        h(NPopconfirm, {
          onPositiveClick: () => toggleStatus(row),
        }, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: row.status === 'active' ? 'warning' : 'primary',
            ghost: true,
          }, {
            icon: () => h(NIcon, null, {
              default: () => h(row.status === 'active' ? LockClosedOutline : LockOpenOutline),
            }),
            default: () => row.status === 'active' ? '冻结' : '解冻',
          }),
          default: () => `确定要${row.status === 'active' ? '冻结' : '解冻'}该账户吗？`,
        }),
        // 查看明细按钮
        h(NTooltip, {}, {
          trigger: () => h(NButton, {
            size: 'tiny',
            type: 'info',
            ghost: true,
            onClick: () => viewUserTransactions(row.userId),
          }, {
            icon: () => h(NIcon, null, { default: () => h(EyeOutline) }),
            default: () => '明细',
          }),
          default: () => '查看该用户的交易流水',
        }),
      ],
    }),
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchSystemStats()
  cookieStore.fetchAdminAccounts(filters.value)
  cookieStore.subscribeBalanceUpdates()
})

onUnmounted(() => {
  cookieStore.unsubscribeBalanceUpdates()
})

// ── Methods ────────────────────────────────

function handleSearch() {
  filters.value.page = 1
  cookieStore.fetchAdminAccounts(filters.value)
}

function handleReset() {
  filters.value = {
    search: '',
    status: 'all',
    sortBy: 'balance',
    sortOrder: 'desc',
    page: 1,
    pageSize: 20,
  }
  cookieStore.fetchAdminAccounts(filters.value)
}

function handlePageChange(page: number) {
  filters.value.page = page
  cookieStore.fetchAdminAccounts(filters.value)
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  cookieStore.fetchAdminAccounts(filters.value)
}

function openAdjustModal(user: CookieAccount, mode: 'recharge' | 'deduct') {
  selectedUser.value = user
  adjustMode.value = mode
  showAdjustModal.value = true
}

async function toggleStatus(row: CookieAccount) {
  const newStatus = row.status === 'active' ? 'frozen' : 'active'
  try {
    await cookieStore.toggleAccountStatus(row.userId, newStatus)
    window.$message?.success(`账户已${newStatus === 'active' ? '解冻' : '冻结'}`)
  } catch (err: any) {
    window.$message?.error(err.message || '操作失败')
  }
}

function viewUserTransactions(userId: number) {
  router.push({
    path: '/admin/cookies/transactions',
    query: { userId: String(userId) },
  })
}

function handleAdjustSuccess() {
  cookieStore.fetchAdminAccounts(filters.value)
  cookieStore.fetchSystemStats()
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.admin-cookie-page {
  padding: 20px;
}

.admin-stat-card {
  border-radius: 12px;
  background: linear-gradient(135deg, var(--n-card-color) 0%, var(--n-action-color) 100%);
}

.admin-stat-card :deep(.n-card__content) {
  padding: 16px;
}

.admin-stat-card--danger :deep(.n-statistic-value) {
  color: #d03050;
}

.admin-stat-card--success :deep(.n-statistic-value) {
  color: #18a058;
}

.admin-stat-card--warning :deep(.n-statistic-value) {
  color: #f0a020;
}
</style>
```

---

## 7. CookieAdjustModal.vue

```vue
<!-- components/cookie/CookieAdjustModal.vue -->
<template>
  <n-modal
    v-model:show="show"
    :mask-closable="false"
    preset="card"
    :title="modalTitle"
    :bordered="false"
    class="adjust-modal"
    style="width: 480px;"
  >
    <n-space v-if="user" vertical :size="20">
      <!-- 用户信息 -->
      <n-card embedded size="small">
        <n-space align="center" :size="12">
          <n-avatar
            :src="user.avatar"
            fallback-src="/default-avatar.png"
            round
            size="48"
          />
          <div>
            <n-text strong style="font-size: 16px;">{{ user.userName }}</n-text>
            <br />
            <n-text depth="3" style="font-size: 13px;">{{ user.email }}</n-text>
          </div>
        </n-space>
      </n-card>

      <!-- 当前余额 -->
      <n-descriptions label-placement="left" :column="1" bordered>
        <n-descriptions-item label="当前余额">
          <n-text strong style="color: #f5a623; font-size: 18px;">
            {{ user.balance.toLocaleString() }} 🥫
          </n-text>
        </n-descriptions-item>
        <n-descriptions-item label="操作类型">
          <n-tag :type="mode === 'recharge' ? 'success' : 'error'" size="small" round>
            {{ mode === 'recharge' ? '🔼 充值（增加余额）' : '🔽 扣减（减少余额）' }}
          </n-tag>
        </n-descriptions-item>
      </n-descriptions>

      <!-- 调整表单 -->
      <n-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-placement="left"
        label-width="100"
      >
        <n-form-item label="调整金额" path="amount">
          <n-input-number
            v-model:value="formData.amount"
            :min="mode === 'recharge' ? 1 : undefined"
            :max="mode === 'deduct' ? -1 : undefined"
            :placeholder="mode === 'recharge' ? '请输入充值金额（正数）' : '请输入扣减金额（负数）'"
            style="width: 100%;"
            :show-button="true"
            :precision="0"
          >
            <template #suffix>🥫</template>
          </n-input-number>
        </n-form-item>

        <!-- 变更后余额预览 -->
        <n-form-item label="变更后余额">
          <n-text
            :type="newBalance >= 0 ? 'success' : 'error'"
            strong
            style="font-size: 16px;"
          >
            {{ newBalance.toLocaleString() }} 🥫
          </n-text>
          <n-text v-if="newBalance < 0" type="error" style="margin-left: 8px;">
            余额不能为负数！
          </n-text>
        </n-form-item>

        <n-form-item label="调整原因" path="reason">
          <n-input
            v-model:value="formData.reason"
            type="textarea"
            :rows="3"
            placeholder="请详细说明调整原因（必填）..."
            maxlength="200"
            show-count
          />
        </n-form-item>

        <!-- 二次确认密码 -->
        <n-form-item label="确认密码" path="password">
          <n-input
            v-model:value="formData.password"
            type="password"
            placeholder="请输入您的管理员密码以确认操作"
            show-password-on="mousedown"
          />
        </n-form-item>
      </n-form>

      <!-- 操作记录提示 -->
      <n-alert type="warning" :show-icon="true" size="small">
        此操作将被记录在系统日志中，且不可撤销。请确认金额和原因无误后再提交。
      </n-alert>

      <!-- 按钮 -->
      <n-space justify="end" :size="12">
        <n-button @click="show = false">取消</n-button>
        <n-button
          type="primary"
          :loading="submitting"
          :disabled="!isFormValid"
          @click="handleSubmit"
        >
          确认{{ mode === 'recharge' ? '充值' : '扣减' }}
        </n-button>
      </n-space>
    </n-space>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  NModal, NCard, NSpace, NAvatar, NText, NTag,
  NDescriptions, NDescriptionsItem, NForm, NFormItem,
  NInputNumber, NInput, NAlert, NButton,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieAccount, CookieAdjustParams } from '@/types/cookie'

// ═══════════════════════════════════════════
// Props & Emits
// ═══════════════════════════════════════════

const props = defineProps<{
  show: boolean
  user: CookieAccount | null
  mode: 'recharge' | 'deduct'
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'success': []
}>()

// ═══════════════════════════════════════════
// State
// ═══════════════════════════════════════════

const show = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val),
})

const cookieStore = useCookieStore()
const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

const formData = ref({
  amount: undefined as number | undefined,
  reason: '',
  password: '',
})

// ═══════════════════════════════════════════
// Computed
// ═══════════════════════════════════════════

const modalTitle = computed(() => {
  if (!props.user) return ''
  return props.mode === 'recharge'
    ? `🥫 充值 — ${props.user.userName}`
    : `🥫 扣减 — ${props.user.userName}`
})

const newBalance = computed(() => {
  if (!props.user || formData.value.amount === undefined) return props.user?.balance ?? 0
  const adjustment = props.mode === 'recharge'
    ? Math.abs(formData.value.amount)
    : -Math.abs(formData.value.amount)
  return props.user.balance + adjustment
})

const isFormValid = computed(() => {
  return (
    formData.value.amount !== undefined &&
    formData.value.amount !== 0 &&
    formData.value.reason.trim().length > 0 &&
    formData.value.password.length > 0 &&
    newBalance.value >= 0
  )
})

// ═══════════════════════════════════════════
// Form Rules
// ═══════════════════════════════════════════

const formRules: FormRules = {
  amount: [
    { required: true, message: '请输入调整金额', trigger: ['blur', 'input'], type: 'number' },
    {
      validator: (_rule, value: number) => {
        if (props.mode === 'recharge' && value <= 0) {
          return new Error('充值金额必须大于0')
        }
        if (props.mode === 'deduct' && value >= 0) {
          return new Error('扣减金额必须小于0')
        }
        return true
      },
      trigger: ['blur', 'input'],
    },
  ],
  reason: [
    { required: true, message: '请输入调整原因', trigger: 'blur' },
    { min: 2, max: 200, message: '原因长度为2-200字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入确认密码', trigger: 'blur' },
  ],
}

// ═══════════════════════════════════════════
// Watch
// ═══════════════════════════════════════════

watch(() => props.show, (val) => {
  if (val) {
    // 打开弹窗时重置表单
    formData.value = {
      amount: props.mode === 'recharge' ? undefined : undefined,
      reason: '',
      password: '',
    }
  }
})

watch(() => props.mode, () => {
  formData.value.amount = undefined
})

// ═══════════════════════════════════════════
// Methods
// ═══════════════════════════════════════════

async function handleSubmit() {
  if (!formRef.value) return

  await formRef.value.validate(async (errors) => {
    if (errors) return
    if (!props.user) return

    submitting.value = true
    try {
      const adjustAmount = props.mode === 'recharge'
        ? Math.abs(formData.value.amount!)
        : -Math.abs(formData.value.amount!)

      const params: CookieAdjustParams = {
        userId: props.user.userId,
        amount: adjustAmount,
        reason: formData.value.reason,
        password: formData.value.password,
      }

      await cookieStore.adjustBalance(params)

      window.$message?.success(
        `${props.mode === 'recharge' ? '充值' : '扣减'}成功！余额已更新。`
      )
      show.value = false
      emit('success')
    } catch (err: any) {
      window.$message?.error(err.message || '操作失败')
    } finally {
      submitting.value = false
    }
  })
}
</script>

<style scoped>
.adjust-modal :deep(.n-card-header) {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.adjust-modal :deep(.n-card__content) {
  padding: 20px;
}
</style>
```


---

## 8. AdminCookieTransactionsView.vue

```vue
<!-- views/admin/AdminCookieTransactionsView.vue -->
<template>
  <div class="admin-transactions-page">
    <n-page-header title="🧾 交易流水查询" subtitle="查看和管理全站饼干交易记录" />

    <!-- 面包屑导航 -->
    <n-breadcrumb style="margin-top: 8px;">
      <n-breadcrumb-item @click="router.push('/admin/cookies')">
        饼干管理
      </n-breadcrumb-item>
      <n-breadcrumb-item>交易流水</n-breadcrumb-item>
    </n-breadcrumb>

    <n-card :bordered="false" style="margin-top: 16px;">
      <!-- ═══════════ 高级筛选栏 ═══════════ -->
      <n-card title="🔍 筛选条件" embedded size="small" style="margin-bottom: 16px;">
        <n-grid :cols="4" :x-gap="12" :y-gap="12" responsive="screen">
          <n-grid-item span="4 s:2 m:1">
            <n-input
              v-model:value="filters.searchUser"
              placeholder="用户名 / 邮箱"
              clearable
            >
              <template #prefix>
                <n-icon><PersonOutline /></n-icon>
              </template>
            </n-input>
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-select
              v-model:value="filters.type"
              :options="typeOptions"
              placeholder="交易类型"
              clearable
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-date-picker
              v-model:formatted-value="filters.startDate"
              type="datetime"
              placeholder="开始时间"
              value-format="yyyy-MM-dd HH:mm:ss"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-date-picker
              v-model:formatted-value="filters.endDate"
              type="datetime"
              placeholder="结束时间"
              value-format="yyyy-MM-dd HH:mm:ss"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-input-number
              v-model:value="filters.minAmount"
              placeholder="最小金额"
              :min="0"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:2 m:1">
            <n-input-number
              v-model:value="filters.maxAmount"
              placeholder="最大金额"
              :min="0"
              clearable
              style="width: 100%;"
            />
          </n-grid-item>

          <n-grid-item span="4 s:4 m:2">
            <n-space>
              <n-button type="primary" @click="handleSearch">
                <template #icon><n-icon><SearchOutline /></n-icon></template>
                查询
              </n-button>
              <n-button @click="handleReset">重置</n-button>
              <n-button type="info" ghost @click="handleExport">
                <template #icon><n-icon><DownloadOutline /></n-icon></template>
                导出 CSV
              </n-button>
            </n-space>
          </n-grid-item>
        </n-grid>
      </n-card>

      <!-- ═══════════ 统计汇总 ═══════════ -->
      <n-space :size="24" style="margin-bottom: 16px;">
        <n-statistic label="查询结果" tabular-nums>
          <n-number-animation :from="0" :to="transactionTotal" show-separator />
          <template #suffix>条</template>
        </n-statistic>
        <n-statistic label="收入合计" tabular-nums>
          <n-text type="success">
            <n-number-animation :from="0" :to="stats.income" show-separator />
          </n-text>
          <template #suffix>🥫</template>
        </n-statistic>
        <n-statistic label="支出合计" tabular-nums>
          <n-text type="error">
            <n-number-animation :from="0" :to="stats.expense" show-separator />
          </n-text>
          <template #suffix>🥫</template>
        </n-statistic>
      </n-space>

      <!-- ═══════════ 流水表格 ═══════════ -->
      <n-data-table
        :columns="columns"
        :data="transactions"
        :loading="isLoading"
        :pagination="pagination"
        :row-key="(row: CookieTransaction) => row.id"
        @update:page="handlePageChange"
        @update:page-size="handlePageSizeChange"
      />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NPageHeader, NBreadcrumb, NBreadcrumbItem, NCard, NGrid, NGridItem,
  NInput, NSelect, NDatePicker, NInputNumber, NButton, NSpace,
  NDataTable, NText, NTag, NIcon, NEllipsis, NStatistic,
  NNumberAnimation,
} from 'naive-ui'
import {
  PersonOutline, SearchOutline, DownloadOutline,
} from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookieTransaction, TransactionType, TransactionFilters } from '@/types/cookie'
import type { DataTableColumns, SelectOption, PaginationProps } from 'naive-ui'

const route = useRoute()
const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const filters = ref<TransactionFilters & { searchUser?: string }>({
  searchUser: '',
  type: 'all',
  startDate: undefined,
  endDate: undefined,
  minAmount: undefined,
  maxAmount: undefined,
  page: 1,
  pageSize: 50,
})

const stats = ref({ income: 0, expense: 0 })

// ── Options ────────────────────────────────
const typeOptions: SelectOption[] = [
  { label: '全部类型', value: 'all' },
  { label: '获得', value: 'earn' },
  { label: '消费', value: 'spend' },
  { label: '调整', value: 'adjust' },
  { label: '退款', value: 'refund' },
  { label: '充值', value: 'recharge' },
]

// ── Computed ───────────────────────────────
const transactions = computed(() => cookieStore.transactions)
const transactionTotal = computed(() => cookieStore.transactionTotal)
const isLoading = computed(() => cookieStore.isLoading)

const pagination = computed<PaginationProps>(() => ({
  page: filters.value.page ?? 1,
  pageSize: filters.value.pageSize ?? 50,
  pageCount: Math.ceil(transactionTotal.value / (filters.value.pageSize ?? 50)),
  showSizePicker: true,
  pageSizes: [20, 50, 100, 200],
  showQuickJumper: true,
  prefix: () => `共 ${transactionTotal.value} 条`,
}))

// ── Columns ────────────────────────────────
const columns = computed<DataTableColumns<CookieTransaction>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 70,
  },
  {
    title: '用户',
    key: 'userName',
    width: 130,
    render: (row) => h(NEllipsis, null, { default: () => row.userName }),
  },
  {
    title: '时间',
    key: 'createdAt',
    width: 170,
    render: (row) => formatDateTime(row.createdAt),
  },
  {
    title: '类型',
    key: 'type',
    width: 90,
    render: (row) => h(NTag, {
      type: getTxTagType(row.type),
      size: 'small',
      round: true,
    }, { default: () => getTxLabel(row.type) }),
  },
  {
    title: '金额',
    key: 'amount',
    width: 110,
    align: 'right',
    render: (row) => h(NText, {
      strong: true,
      type: row.amount > 0 ? 'success' : 'error',
    }, { default: () => `${row.amount > 0 ? '+' : ''}${row.amount} 🥫` }),
  },
  {
    title: '变动后余额',
    key: 'balanceAfter',
    width: 120,
    align: 'right',
    render: (row) => `${row.balanceAfter.toLocaleString()} 🥫`,
  },
  {
    title: '描述',
    key: 'description',
    minWidth: 200,
    render: (row) => h(NEllipsis, { style: 'max-width: 280px;' }, {
      default: () => row.description,
    }),
  },
  {
    title: '关联任务',
    key: 'relatedTaskId',
    width: 100,
    render: (row) => row.relatedTaskId
      ? h(NButton, { text: true, type: 'info', size: 'tiny' }, {
          default: () => `#${row.relatedTaskId}`,
        })
      : '--',
  },
  {
    title: '操作者',
    key: 'operatorName',
    width: 110,
    render: (row) => row.operatorName || '系统',
  },
])

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  // 如果从用户管理页跳转过来，自动填入用户ID
  const userId = route.query.userId
  if (userId) {
    filters.value.searchUser = String(userId)
  }
  handleSearch()
})

// ── Methods ────────────────────────────────

function handleSearch() {
  filters.value.page = 1
  // 同时计算统计
  calculateStats()
  cookieStore.fetchTransactions({
    type: filters.value.type === 'all' ? undefined : filters.value.type as TransactionType,
    startDate: filters.value.startDate,
    endDate: filters.value.endDate,
    minAmount: filters.value.minAmount,
    maxAmount: filters.value.maxAmount,
    page: filters.value.page,
    pageSize: filters.value.pageSize,
  })
}

function handleReset() {
  filters.value = {
    searchUser: '',
    type: 'all',
    startDate: undefined,
    endDate: undefined,
    minAmount: undefined,
    maxAmount: undefined,
    page: 1,
    pageSize: 50,
  }
  handleSearch()
}

function handlePageChange(page: number) {
  filters.value.page = page
  handleSearch()
}

function handlePageSizeChange(size: number) {
  filters.value.pageSize = size
  filters.value.page = 1
  handleSearch()
}

function handleExport() {
  // CSV 导出
  const headers = ['ID', '用户', '时间', '类型', '金额', '余额', '描述', '操作者']
  const rows = transactions.value.map(tx => [
    tx.id,
    tx.userName,
    tx.createdAt,
    tx.type,
    tx.amount,
    tx.balanceAfter,
    tx.description,
    tx.operatorName || '系统',
  ])
  const csv = [headers, ...rows]
    .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
    .join('\n')

  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `cookie-transactions-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)

  window.$message?.success('CSV 导出成功')
}

function calculateStats() {
  // 计算收入/支出合计（基于当前查询结果）
  const income = transactions.value
    .filter(t => t.amount > 0)
    .reduce((sum, t) => sum + t.amount, 0)
  const expense = transactions.value
    .filter(t => t.amount < 0)
    .reduce((sum, t) => sum + Math.abs(t.amount), 0)
  stats.value = { income, expense }
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getTxTagType(type: TransactionType) {
  const map: Record<string, 'success' | 'error' | 'info' | 'warning' | 'default'> = {
    earn: 'success',
    spend: 'error',
    adjust: 'info',
    refund: 'warning',
    recharge: 'success',
  }
  return map[type] ?? 'default'
}

function getTxLabel(type: TransactionType): string {
  const map: Record<string, string> = {
    earn: '获得', spend: '消费', adjust: '调整',
    refund: '退款', recharge: '充值',
  }
  return map[type] ?? type
}
</script>

<style scoped>
.admin-transactions-page {
  padding: 20px;
}
</style>
```

---

## 9. AdminCookiePricingView.vue

```vue
<!-- views/admin/AdminCookiePricingView.vue -->
<template>
  <div class="admin-pricing-page">
    <n-page-header title="🏷️ 定价策略管理" subtitle="管理系统资源定价与计费规则" />

    <n-breadcrumb style="margin-top: 8px;">
      <n-breadcrumb-item @click="router.push('/admin/cookies')">
        饼干管理
      </n-breadcrumb-item>
      <n-breadcrumb-item>定价策略</n-breadcrumb-item>
    </n-breadcrumb>

    <n-card :bordered="false" style="margin-top: 16px;">
      <!-- 新增按钮 -->
      <n-space justify="space-between" align="center" style="margin-bottom: 16px;">
        <n-text depth="3">配置各任务类型的资源单价，影响任务提交时的费用预估</n-text>
        <n-button type="primary" @click="openCreateModal">
          <template #icon><n-icon><AddOutline /></n-icon></template>
          新增定价策略
        </n-button>
      </n-space>

      <!-- 定价表格 -->
      <n-data-table
        :columns="columns"
        :data="pricingList"
        :loading="isLoading"
        :row-key="(row: CookiePricing) => row.id"
        :pagination="false"
      />
    </n-card>

    <!-- ═══════════ 新增/编辑弹窗 ═══════════ -->
    <n-modal
      v-model:show="showModal"
      preset="card"
      :title="isEdit ? '✏️ 编辑定价策略' : '➕ 新增定价策略'"
      style="width: 500px;"
      :bordered="false"
      :mask-closable="false"
    >
      <n-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-placement="left"
        label-width="110"
      >
        <n-form-item label="任务类型" path="flowCategory">
          <n-select
            v-model:value="formData.flowCategory"
            :options="flowCategoryOptions"
            placeholder="选择任务类型"
            :disabled="isEdit"
          />
        </n-form-item>

        <n-form-item label="资源类型" path="resourceType">
          <n-select
            v-model:value="formData.resourceType"
            :options="resourceTypeOptions"
            placeholder="选择资源类型"
            :disabled="isEdit"
          />
        </n-form-item>

        <n-form-item label="单价" path="unitPrice">
          <n-input-number
            v-model:value="formData.unitPrice"
            :min="0"
            :precision="2"
            placeholder="每小时单价（饼干）"
            style="width: 100%;"
          >
            <template #suffix>🥫 / 小时</template>
          </n-input-number>
        </n-form-item>

        <n-form-item label="描述" path="description">
          <n-input
            v-model:value="formData.description"
            type="textarea"
            :rows="2"
            placeholder="定价策略说明..."
            maxlength="200"
            show-count
          />
        </n-form-item>

        <n-form-item label="生效时间" path="effectiveFrom">
          <n-date-picker
            v-model:formatted-value="formData.effectiveFrom"
            type="datetime"
            placeholder="生效时间"
            value-format="yyyy-MM-dd HH:mm:ss"
            style="width: 100%;"
          />
        </n-form-item>

        <n-form-item label="过期时间" path="effectiveTo">
          <n-date-picker
            v-model:formatted-value="formData.effectiveTo"
            type="datetime"
            placeholder="留空表示长期有效"
            value-format="yyyy-MM-dd HH:mm:ss"
            clearable
            style="width: 100%;"
          />
        </n-form-item>
      </n-form>

      <template #footer>
        <n-space justify="end" :size="12">
          <n-button @click="showModal = false">取消</n-button>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            {{ isEdit ? '保存修改' : '创建策略' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NPageHeader, NBreadcrumb, NBreadcrumbItem, NCard, NSpace,
  NButton, NDataTable, NText, NTag, NIcon, NModal, NForm,
  NFormItem, NSelect, NInputNumber, NInput, NDatePicker,
  NSwitch, NPopconfirm,
} from 'naive-ui'
import type { FormInst, FormRules, DataTableColumns, SelectOption } from 'naive-ui'
import { AddOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { CookiePricing, PricingFormData, FlowCategory, ResourceType } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const showModal = ref(false)
const isEdit = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

const formData = ref<PricingFormData>({
  flowCategory: 'rna_seq',
  resourceType: 'cpu',
  unitPrice: 0,
  description: '',
  effectiveFrom: new Date().toISOString().slice(0, 19).replace('T', ' '),
  effectiveTo: undefined,
})

// ── Options ────────────────────────────────
const flowCategoryOptions: SelectOption[] = [
  { label: 'RNA-seq', value: 'rna_seq' },
  { label: 'ChIP-seq', value: 'chip_seq' },
  { label: 'ATAC-seq', value: 'atac_seq' },
  { label: 'WGS', value: 'wgs' },
  { label: 'Proteomics', value: 'proteomics' },
  { label: 'Metabolomics', value: 'metabolomics' },
  { label: 'scRNA-seq', value: 'sc_rna_seq' },
  { label: 'Data Integration', value: 'data_integration' },
]

const resourceTypeOptions: SelectOption[] = [
  { label: 'CPU', value: 'cpu' },
  { label: '内存', value: 'memory' },
  { label: 'GPU', value: 'gpu' },
]

const flowCategoryLabel = (v: FlowCategory) =>
  flowCategoryOptions.find(o => o.value === v)?.label ?? v

const resourceTypeLabel = (v: ResourceType) =>
  resourceTypeOptions.find(o => o.value === v)?.label ?? v

// ── Computed ───────────────────────────────
const pricingList = computed(() => cookieStore.pricing)
const isLoading = computed(() => cookieStore.isLoading)

// ── Columns ────────────────────────────────
const columns = computed<DataTableColumns<CookiePricing>>(() => [
  {
    title: 'ID',
    key: 'id',
    width: 60,
  },
  {
    title: '任务类型',
    key: 'flowCategory',
    width: 140,
    render: (row) => h(NTag, { type: 'info', size: 'small' }, {
      default: () => flowCategoryLabel(row.flowCategory),
    }),
  },
  {
    title: '资源类型',
    key: 'resourceType',
    width: 100,
    render: (row) => resourceTypeLabel(row.resourceType),
  },
  {
    title: '单价',
    key: 'unitPrice',
    width: 130,
    align: 'right',
    render: (row) => h(NText, { strong: true }, {
      default: () => `${row.unitPrice} 🥫/小时`,
    }),
  },
  {
    title: '描述',
    key: 'description',
    minWidth: 200,
    render: (row) => h(NText, { depth: 2 }, { default: () => row.description }),
  },
  {
    title: '生效时间',
    key: 'effectiveFrom',
    width: 170,
    render: (row) => formatDateTime(row.effectiveFrom),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => h(NSwitch, {
      value: row.status === 'active',
      onUpdateValue: (val: boolean) => handleToggleStatus(row.id, val),
    }, {
      checked: () => '生效',
      unchecked: () => '停用',
    }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    fixed: 'right',
    render: (row) => h(NButton, {
      size: 'tiny',
      type: 'primary',
      ghost: true,
      onClick: () => openEditModal(row),
    }, { default: () => '编辑' }),
  },
])

// ── Form Rules ─────────────────────────────
const formRules: FormRules = {
  flowCategory: [{ required: true, message: '请选择任务类型', trigger: 'blur', type: 'string' }],
  resourceType: [{ required: true, message: '请选择资源类型', trigger: 'blur', type: 'string' }],
  unitPrice: [
    { required: true, message: '请输入单价', trigger: 'blur', type: 'number' },
    { min: 0, message: '单价不能为负数', trigger: 'blur', type: 'number' },
  ],
  effectiveFrom: [{ required: true, message: '请选择生效时间', trigger: 'blur', type: 'string' }],
}

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchPricing()
})

// ── Methods ────────────────────────────────

function openCreateModal() {
  isEdit.value = false
  editingId.value = null
  formData.value = {
    flowCategory: 'rna_seq',
    resourceType: 'cpu',
    unitPrice: 0,
    description: '',
    effectiveFrom: new Date().toISOString().slice(0, 19).replace('T', ' '),
    effectiveTo: undefined,
  }
  showModal.value = true
}

function openEditModal(pricing: CookiePricing) {
  isEdit.value = true
  editingId.value = pricing.id
  formData.value = {
    flowCategory: pricing.flowCategory,
    resourceType: pricing.resourceType,
    unitPrice: pricing.unitPrice,
    description: pricing.description,
    effectiveFrom: pricing.effectiveFrom,
    effectiveTo: pricing.effectiveTo,
  }
  showModal.value = true
}

async function handleToggleStatus(id: number, active: boolean) {
  try {
    await cookieStore.togglePricingStatus(id, active ? 'active' : 'inactive')
    window.$message?.success(active ? '定价策略已生效' : '定价策略已停用')
  } catch (err: any) {
    window.$message?.error(err.message || '操作失败')
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (errors) => {
    if (errors) return

    submitting.value = true
    try {
      if (isEdit.value && editingId.value) {
        await cookieStore.updatePricing(editingId.value, formData.value)
        window.$message?.success('定价策略已更新')
      } else {
        await cookieStore.createPricing(formData.value)
        window.$message?.success('定价策略已创建')
      }
      showModal.value = false
    } catch (err: any) {
      window.$message?.error(err.message || '操作失败')
    } finally {
      submitting.value = false
    }
  })
}

// ── Helpers ────────────────────────────────

function formatDateTime(dateStr: string): string {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.admin-pricing-page {
  padding: 20px;
}
</style>
```

---

## 10. TaskSubmitView.vue 饼干预估更新

```vue
<!-- views/task/TaskSubmitView.vue — 饼干预估区域（嵌入在提交表单底部） -->

<!-- ═══════════ 在 TaskSubmitView.vue 的 <template> 中，提交按钮上方插入 ═══════════ -->
<template>
  <!-- ... 原有表单内容 ... -->

  <!-- 🥫 饼干预估区域 -->
  <n-card
    size="small"
    class="cost-estimate-card"
    :bordered="false"
  >
    <template #header>
      <n-space align="center" :size="8">
        <n-icon size="18" color="#f5a623"><CookieOutline /></n-icon>
        <n-text strong>饼干预估</n-text>
        <n-tag v-if="estimate" size="tiny" type="warning" round>
          实时计算
        </n-tag>
      </n-space>
    </template>

    <n-space vertical :size="12">
      <!-- 费用明细 -->
      <n-skeleton v-if="!estimate && isEstimating" text :repeat="4" />

      <template v-else-if="estimate">
        <!-- 基础费用 -->
        <n-space justify="space-between" align="center">
          <n-text depth="2">
            基础费用（{{ flowCategoryLabel }}）
          </n-text>
          <n-text>{{ estimate.baseFee }} 🥫</n-text>
        </n-space>

        <!-- 资源费用明细 -->
        <n-space
          v-for="res in estimate.resources"
          :key="res.resourceType"
          justify="space-between"
          align="center"
        >
          <n-text depth="2">
            {{ resourceLabel(res.resourceType) }}
            <n-text depth="3" style="font-size: 12px;">
              （{{ res.quantity }}{{ resourceUnit(res.resourceType) }} × {{ res.duration }}小时 @ {{ res.unitPrice }}🥫/h）
            </n-text>
          </n-text>
          <n-text>{{ res.subtotal }} 🥫</n-text>
        </n-space>

        <!-- 折扣信息 -->
        <n-space
          v-if="estimate.discountRate < 1"
          justify="space-between"
          align="center"
        >
          <n-text depth="2" type="success">
            折扣优惠（{{ (estimate.discountRate * 10).toFixed(1) }}折）
          </n-text>
          <n-text type="success">
            -{{ (estimate.total - estimate.discountedTotal).toFixed(0) }} 🥫
          </n-text>
        </n-space>

        <n-divider style="margin: 8px 0;" />

        <!-- 预估总计 -->
        <n-space justify="space-between" align="center">
          <n-text strong style="font-size: 15px;">预估总计</n-text>
          <n-text type="warning" strong style="font-size: 18px;">
            {{ Math.ceil(estimate.discountedTotal) }} 🥫
          </n-text>
        </n-space>
      </template>

      <n-empty
        v-else
        description="选择任务类型和资源后显示预估费用"
        size="small"
      />

      <n-divider style="margin: 8px 0;" />

      <!-- 余额检查 -->
      <n-alert
        v-if="account && estimate && account.balance < estimate.discountedTotal"
        type="error"
        :show-icon="true"
      >
        <n-space vertical :size="4">
          <n-text strong>余额不足！</n-text>
          <n-text>
            当前余额 <n-text strong>{{ account.balance }}</n-text> 🥫，
            还需 <n-text type="error" strong>{{ Math.ceil(estimate.discountedTotal - account.balance) }}</n-text> 🥫
          </n-text>
          <n-button
            text
            type="primary"
            size="small"
            @click="goToAccount"
          >
            前往饼干账户 →
          </n-button>
        </n-space>
      </n-alert>

      <n-space
        v-else-if="account && estimate"
        justify="space-between"
        align="center"
      >
        <n-space align="center" :size="8">
          <n-icon size="16" color="#f5a623"><CookieOutline /></n-icon>
          <n-text depth="2">当前余额</n-text>
        </n-space>
        <n-text>
          <n-text strong style="color: #f5a623;">{{ account.balance }}</n-text>
          🥫（执行后剩余 <n-text strong>{{ account.balance - Math.ceil(estimate.discountedTotal) }}</n-text> 🥫）
        </n-text>
      </n-space>
    </n-space>
  </n-card>

  <!-- 提交按钮 -->
  <n-space justify="end" style="margin-top: 16px;">
    <n-button
      type="primary"
      size="large"
      :disabled="!canSubmit"
      :loading="submitting"
      @click="handleSubmit"
    >
      <template #icon><n-icon><SendOutline /></n-icon></template>
      提交任务（{{ estimate ? Math.ceil(estimate.discountedTotal) + ' 🥫' : '...' }}）
    </n-button>
  </n-space>

  <!-- ═══════════ 余额不足弹窗 ═══════════ -->
  <n-modal
    v-model:show="showInsufficientModal"
    preset="card"
    title="🥫 饼干余额不足"
    style="width: 420px;"
    :bordered="false"
  >
    <n-space vertical align="center" :size="20">
      <n-icon size="64" color="#f5a623" class="cookie-large-icon">
        <CookieOutline />
      </n-icon>

      <n-text style="font-size: 16px;">
        您的饼干余额不足，无法提交此任务。
      </n-text>

      <n-descriptions bordered :column="1" style="width: 100%;">
        <n-descriptions-item label="当前余额">
          <n-text strong style="color: #f5a623;">{{ account?.balance ?? 0 }} 🥫</n-text>
        </n-descriptions-item>
        <n-descriptions-item label="预估消耗">
          <n-text strong type="error">
            {{ estimate ? Math.ceil(estimate.discountedTotal) : '--' }} 🥫
          </n-text>
        </n-descriptions-item>
        <n-descriptions-item label="差额">
          <n-text strong type="error">
            {{ estimate && account ? Math.ceil(estimate.discountedTotal - account.balance) : '--' }} 🥫
          </n-text>
        </n-descriptions-item>
      </n-descriptions>

      <n-text depth="3" style="font-size: 13px;">
        请联系管理员充值饼干，或前往饼干账户页面查看详情。
      </n-text>

      <n-space :size="12">
        <n-button @click="showInsufficientModal = false">取消</n-button>
        <n-button type="primary" @click="goToAccount">
          前往饼干账户
        </n-button>
      </n-space>
    </n-space>
  </n-modal>
</template>

<script setup lang="ts">
// ═══════════════════════════════════════════
// 在 TaskSubmitView.vue 的 <script setup> 中新增
// ═══════════════════════════════════════════

import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NSpace, NText, NTag, NIcon, NDivider, NAlert,
  NButton, NModal, NDescriptions, NDescriptionsItem, NSkeleton, NEmpty,
} from 'naive-ui'
import { CookieOutline, SendOutline } from '@vicons/ionicons5'
import { useCookieStore } from '@/stores/modules/cookie'
import type { FlowCategory, ResourceType, EstimateParams } from '@/types/cookie'

const router = useRouter()
const cookieStore = useCookieStore()

// ── State ──────────────────────────────────
const showInsufficientModal = ref(false)
const isEstimating = ref(false)
const estimateDebounceTimer = ref<ReturnType<typeof setTimeout> | null>(null)

// 表单数据（从原有 TaskSubmitView 中获取或传入）
const formData = ref({
  flowCategory: 'rna_seq' as FlowCategory,
  cpuCores: 8,
  memoryGb: 16,
  gpuCards: 0,
  estimatedHours: 2,
})

// ── Computed ───────────────────────────────
const account = computed(() => cookieStore.account)
const estimate = computed(() => cookieStore.estimate)

const flowCategoryLabel = computed(() => {
  const labels: Record<FlowCategory, string> = {
    rna_seq: 'RNA-seq',
    chip_seq: 'ChIP-seq',
    atac_seq: 'ATAC-seq',
    wgs: 'WGS',
    proteomics: 'Proteomics',
    metabolomics: 'Metabolomics',
    sc_rna_seq: 'scRNA-seq',
    data_integration: 'Data Integration',
  }
  return labels[formData.value.flowCategory] ?? formData.value.flowCategory
})

const canSubmit = computed(() => {
  if (!estimate.value || !account.value) return false
  return account.value.balance >= estimate.value.discountedTotal &&
         account.value.status === 'active'
})

// ── Watch — 实时计算预估费用 ────────────────

// 监听资源参数变化，防抖调用预估接口
watch(
  () => [
    formData.value.flowCategory,
    formData.value.cpuCores,
    formData.value.memoryGb,
    formData.value.gpuCards,
    formData.value.estimatedHours,
  ],
  () => {
    isEstimating.value = true
    if (estimateDebounceTimer.value) clearTimeout(estimateDebounceTimer.value)
    estimateDebounceTimer.value = setTimeout(() => {
      refreshEstimate()
    }, 500)
  },
  { immediate: true, deep: true }
)

// ── Lifecycle ──────────────────────────────
onMounted(() => {
  cookieStore.fetchAccount()
})

onUnmounted(() => {
  cookieStore.clearEstimate()
  if (estimateDebounceTimer.value) clearTimeout(estimateDebounceTimer.value)
})

// ── Methods ────────────────────────────────

/** 刷新费用预估 */
async function refreshEstimate() {
  try {
    const params: EstimateParams = {
      flowCategory: formData.value.flowCategory,
      cpuCores: formData.value.cpuCores,
      memoryGb: formData.value.memoryGb,
      gpuCards: formData.value.gpuCards || undefined,
      estimatedHours: formData.value.estimatedHours,
    }
    await cookieStore.estimateTaskCost(params)
  } catch (err) {
    console.error('费用预估失败:', err)
  } finally {
    isEstimating.value = false
  }
}

/** 提交任务 */
async function handleSubmit() {
  // 余额检查
  if (!account.value || !estimate.value) return
  if (account.value.balance < estimate.value.discountedTotal) {
    showInsufficientModal.value = true
    return
  }
  if (account.value.status !== 'active') {
    window.$message?.error('账户已被冻结，无法提交任务')
    return
  }

  // 执行原有提交逻辑...
  // await submitTask()
}

/** 跳转到饼干账户 */
function goToAccount() {
  showInsufficientModal.value = false
  router.push('/cookies/account')
}

/** 资源标签 */
function resourceLabel(type: ResourceType): string {
  const labels: Record<ResourceType, string> = {
    cpu: 'CPU',
    memory: '内存',
    gpu: 'GPU',
  }
  return labels[type] ?? type
}

/** 资源单位 */
function resourceUnit(type: ResourceType): string {
  const units: Record<ResourceType, string> = {
    cpu: '核',
    memory: 'GB',
    gpu: '卡',
  }
  return units[type] ?? ''
}
</script>

<style scoped>
.cost-estimate-card {
  background: linear-gradient(135deg, rgba(245, 166, 35, 0.05) 0%, rgba(245, 166, 35, 0.01) 100%);
  border: 1px solid rgba(245, 166, 35, 0.15);
  border-radius: 10px;
}

.cost-estimate-card :deep(.n-card-header) {
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(245, 166, 35, 0.1);
}

.cookie-large-icon {
  animation: gentle-float 3s ease-in-out infinite;
}

@keyframes gentle-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}
</style>
```

---

## 11. 路由配置

```typescript
// router/index.ts — 在现有路由配置中新增以下路由

import type { RouteRecordRaw } from 'vue-router'

const cookieRoutes: RouteRecordRaw[] = [
  // ── 用户饼干账户 ─────────────────────────
  {
    path: '/cookies/account',
    name: 'CookieAccount',
    component: () => import('@/views/cookie/CookieAccountView.vue'),
    meta: {
      requiresAuth: true,
      title: '我的饼干',
      icon: 'CookieOutline',
    },
  },

  // ── 管理员：饼干管理 ─────────────────────
  {
    path: '/admin/cookies',
    name: 'AdminCookieManagement',
    component: () => import('@/views/admin/AdminCookieManagementView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '饼干管理',
      icon: 'CookieOutline',
      menuGroup: 'admin',
    },
  },
  {
    path: '/admin/cookies/transactions',
    name: 'AdminCookieTransactions',
    component: () => import('@/views/admin/AdminCookieTransactionsView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '交易流水',
      icon: 'ListOutline',
      menuGroup: 'admin',
      hiddenInMenu: true, // 不在侧边栏显示，通过饼干管理页面进入
    },
  },
  {
    path: '/admin/cookies/pricing',
    name: 'AdminCookiePricing',
    component: () => import('@/views/admin/AdminCookiePricingView.vue'),
    meta: {
      requiresAuth: true,
      requiresAdmin: true,
      title: '定价策略',
      icon: 'PricetagOutline',
      menuGroup: 'admin',
      hiddenInMenu: true,
    },
  },
]

// 合并到主路由
export const routes: RouteRecordRaw[] = [
  // ... 现有路由 ...
  ...cookieRoutes,
]

// 侧边栏菜单配置（AdminLayout）
export const adminMenuOptions = [
  // ... 现有菜单 ...
  {
    label: '饼干管理',
    key: 'cookie-management',
    icon: () => h(NIcon, null, { default: () => h(CookieOutline) }),
    children: [
      {
        label: () => h(RouterLink, { to: '/admin/cookies' }, { default: () => '账户管理' }),
        key: 'admin-cookies',
        icon: () => h(NIcon, null, { default: () => h(PeopleOutline) }),
      },
      {
        label: () => h(RouterLink, { to: '/admin/cookies/transactions' }, { default: () => '交易流水' }),
        key: 'admin-cookies-transactions',
        icon: () => h(NIcon, null, { default: () => h(ListOutline) }),
      },
      {
        label: () => h(RouterLink, { to: '/admin/cookies/pricing' }, { default: () => '定价策略' }),
        key: 'admin-cookies-pricing',
        icon: () => h(NIcon, null, { default: () => h(PricetagOutline) }),
      },
    ],
  },
]
```

---

## 12. API 接口清单

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/v1/cookies/account` | 获取当前用户账户信息 | 登录用户 |
| `GET` | `/api/v1/cookies/account/summary` | 获取账户统计摘要 | 登录用户 |
| `GET` | `/api/v1/cookies/transactions` | 获取交易流水（带筛选） | 登录用户 |
| `GET` | `/api/v1/cookies/account/stats` | 获取图表统计数据 | 登录用户 |
| `POST` | `/api/v1/cookies/estimate` | 预估任务费用 | 登录用户 |
| `GET` | `/api/v1/admin/cookies/statistics` | 获取系统统计 | 管理员 |
| `GET` | `/api/v1/admin/cookies/accounts` | 获取用户账户列表 | 管理员 |
| `POST` | `/api/v1/admin/cookies/accounts/:userId/adjust` | 调整用户余额 | 管理员 |
| `PUT` | `/api/v1/admin/cookies/accounts/:userId/status` | 修改账户状态 | 管理员 |
| `GET` | `/api/v1/admin/cookies/pricing` | 获取定价策略列表 | 管理员 |
| `POST` | `/api/v1/admin/cookies/pricing` | 创建定价策略 | 管理员 |
| `PUT` | `/api/v1/admin/cookies/pricing/:id` | 更新定价策略 | 管理员 |

---

## 13. 组件文件清单

```
src/
├── types/
│   └── cookie.d.ts                    # TypeScript 类型定义
├── stores/
│   └── modules/
│       └── cookie.ts                  # Pinia Store
├── composables/
│   └── useWebSocket.ts               # WebSocket 封装
├── components/
│   └── cookie/
│       ├── CookieBalanceBadge.vue    # Header 饼干余额显示
│       └── CookieAdjustModal.vue     # 管理员充值/扣减弹窗
├── views/
│   ├── cookie/
│   │   └── CookieAccountView.vue     # 用户饼干账户页
│   └── admin/
│       ├── AdminCookieManagementView.vue      # 管理员账户管理
│       ├── AdminCookieTransactionsView.vue    # 交易流水查询
│       └── AdminCookiePricingView.vue         # 定价策略管理
└── router/
    └── index.ts                       # 路由配置（新增饼干路由）
```

---

## 14. 暗黑模式适配说明

所有组件遵循以下暗黑模式适配原则：

1. **使用 Naive UI CSS 变量**：`var(--n-card-color)`、`var(--n-text-color)`、`var(--n-border-color)` 等自动响应主题切换
2. **ECharts 图表适配**：通过 `textStyle: { color: 'var(--n-text-color)' }` 注入主题颜色
3. **自定义颜色使用透明度**：如饼干主题色 `#f5a623` 在不同主题下保持可读性
4. **卡片背景渐变**：使用 `rgba(245, 166, 35, 0.05)` 等低透明度确保暗色下不突兀
5. **Naive UI 自动处理**：`NTag`、`NAlert`、`NButton` 等组件自动适配暗黑模式

---

## 15. 关键交互流程图

```
用户打开页面
  ├── Header 加载 CookieBalanceBadge
  │     ├── 连接 WebSocket /ws/cookies
  │     ├── 获取账户信息 GET /api/v1/cookies/account
  │     └── 获取最近3笔交易 GET /api/v1/cookies/transactions?pageSize=3
  │
  ├── 用户调整任务参数
  │     └── 防抖500ms → POST /api/v1/cookies/estimate
  │           └── 实时更新预估费用显示
  │
  ├── 用户点击"提交任务"
  │     ├── 余额充足？→ 正常提交
  │     └── 余额不足？→ 显示余额不足弹窗 → 引导到账户页
  │
  ├── 任务执行完成
  │     └── WebSocket 推送 cookie.balance_updated
  │           └── CookieBalanceBadge 弹跳动画 + 余额更新
  │
  └── 用户点击饼干图标
        └── 跳转 /cookies/account
              ├── 统计卡片（余额/消费/排名）
              ├── ECharts 图表（趋势/构成）
              └── 交易流水表格（筛选/分页）

管理员操作
  ├── 打开 /admin/cookies
  │     ├── 统计概览卡片
  │     ├── 用户账户表格（搜索/排序/分页）
  │     └── 操作：充值/扣减/冻结/查看明细
  │
  ├── 点击"充值/扣减"
  │     └── CookieAdjustModal 弹窗
  │           ├── 输入金额（实时预览变更后余额）
  │           ├── 输入原因（必填）
  │           ├── 输入管理员密码（二次确认）
  │           └── 提交 → POST /api/v1/admin/cookies/accounts/:id/adjust
  │
  ├── 点击"交易流水"
  │     └── AdminCookieTransactionsView
  │           ├── 高级筛选（用户/类型/时间/金额）
  │           ├── 汇总统计（收入/支出）
  │           └── 导出 CSV
  │
  └── 点击"定价策略"
        └── AdminCookiePricingView
              ├── 定价列表（任务类型/资源类型/单价）
              ├── 状态开关（生效/停用）
              ├── 新增/编辑定价
              └── 实时影响任务提交的费用预估
```

---

*文档生成完毕 — CygnusX 🥫 Cookie System Frontend v1.0*
