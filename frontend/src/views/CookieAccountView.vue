<script setup lang="ts">
import type { CookieTransaction } from '@/types'
import type { AiTokenUsage, AiTokenUsageRecord } from '@/types/stats'
import apiClient from '@/api/client'
import {
  NCard,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NGrid,
  NGridItem,
  NStatistic,
  NSpace,
  NTag,
} from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'

const account = ref<any>(null)
const transactions = ref<CookieTransaction[]>([])
const loading = ref(false)
const aiUsage = ref<AiTokenUsage | null>(null)
const tokenUnit = ref<'K' | 'M'>('K')

function formatTokens(value: number): string {
  if (tokenUnit.value === 'M') return `${(value / 1_000_000).toFixed(2)} M`
  return `${(value / 1000).toFixed(1)} K`
}

const statusTagType = computed(() => {
  const map: Record<string, 'success' | 'warning' | 'error'> = {
    active: 'success',
    frozen: 'warning',
    suspended: 'error',
  }
  return map[account.value?.status || 'active'] || 'success'
})

const txnTagType = (type: string) => {
  const map: Record<string, 'success' | 'error' | 'warning' | 'info' | 'default'> = {
    earn: 'success',
    spend: 'error',
    adjust: 'warning',
    refund: 'info',
    freeze: 'warning',
    unfreeze: 'info',
  }
  return map[type] || 'default'
}

const columns = [
  {
    title: '时间',
    key: 'created_at',
    render(row: CookieTransaction) {
      return row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'
    },
  },
  {
    title: '类型',
    key: 'txn_type',
    render(row: CookieTransaction) {
      return h(NTag, { type: txnTagType(row.txn_type), size: 'small', round: true }, { default: () => row.txn_type })
    },
  },
  {
    title: '金额',
    key: 'amount',
    render(row: CookieTransaction) {
      const color = row.amount >= 0 ? 'var(--arco-success)' : 'var(--arco-danger)'
      return h('span', { style: { color, fontWeight: 500 } }, `${row.amount >= 0 ? '+' : ''}${Number(row.amount).toFixed(2)}`)
    },
  },
  { title: '交易后余额', key: 'balance_after', render: (row: CookieTransaction) => Number(row.balance_after).toFixed(2) },
  { title: '说明', key: 'description' },
]

const aiColumns = computed(() => [
  {
    title: '时间',
    key: 'time',
    width: 170,
    render(row: AiTokenUsageRecord) {
      return row.time ? new Date(row.time).toLocaleString('zh-CN') : '-'
    },
  },
  { title: '会话', key: 'title', ellipsis: { tooltip: true } },
  {
    title: `Token 消耗（${tokenUnit.value}）`,
    key: 'total_tokens',
    width: 130,
    render(row: AiTokenUsageRecord) {
      return formatTokens(row.total_tokens)
    },
  },
  {
    title: '饼干扣减',
    key: 'cookie_cost',
    width: 110,
    render(row: AiTokenUsageRecord) {
      return h('span', { style: { color: 'var(--arco-danger)', fontWeight: 500 } }, `-${Number(row.cookie_cost).toFixed(2)} 🥫`)
    },
  },
])

onMounted(async () => {
  loading.value = true
  try {
    const [acctRes, txnRes] = await Promise.all([
      apiClient.get('/cookies/account'),
      apiClient.get('/cookies/transactions'),
    ])
    account.value = acctRes.data
    transactions.value = txnRes.data
  } finally {
    loading.value = false
  }
  try {
    const aiRes = await apiClient.get<AiTokenUsage>('/stats/ai-usage', { params: { days: 30 } })
    aiUsage.value = aiRes.data
  } catch {
    aiUsage.value = null
  }
})
</script>

<template>
  <div class="page-container">
    <PageHeader title="用量统计" subtitle="查看当前饼干余额、账户状态与交易流水" />
    <NSpace vertical :size="24">
      <NCard title="饼干账户" :bordered="false" class="arco-card">
        <NGrid v-if="account" :cols="4" :x-gap="16" :y-gap="16" responsive="screen">
          <NGridItem>
            <NStatistic label="可用余额" :value="Number(account.available_balance).toFixed(1)">
              <template #suffix>🥫</template>
            </NStatistic>
          </NGridItem>
          <NGridItem>
            <NStatistic label="总余额" :value="Number(account.balance).toFixed(1)">
              <template #suffix>🥫</template>
            </NStatistic>
          </NGridItem>
          <NGridItem>
            <NStatistic label="冻结中" :value="Number(account.frozen_balance).toFixed(1)">
              <template #suffix>🥫</template>
            </NStatistic>
          </NGridItem>
          <NGridItem>
            <NStatistic label="累计获得" :value="Number(account.total_earned).toFixed(1)">
              <template #suffix>🥫</template>
            </NStatistic>
          </NGridItem>
        </NGrid>
        <NDescriptions v-if="account" :columns="2" bordered style="margin-top: 16px">
          <NDescriptionsItem label="账户状态">
            <NTag :type="statusTagType" size="small" round>{{ account.status }}</NTag>
          </NDescriptionsItem>
          <NDescriptionsItem label="累计消费">{{ Number(account.total_spent).toFixed(2) }} 🥫</NDescriptionsItem>
          <NDescriptionsItem label="累计调整">{{ Number(account.total_adjusted).toFixed(2) }} 🥫</NDescriptionsItem>
          <NDescriptionsItem label="创建时间">
            {{ account.created_at ? new Date(account.created_at).toLocaleString('zh-CN') : '-' }}
          </NDescriptionsItem>
        </NDescriptions>
      </NCard>

      <NCard title="AI Token 用量" :bordered="false" class="arco-card">
        <template #header-extra>
          <div class="omichub-segmented-toggle unit-toggle" role="group" aria-label="Token 单位切换">
            <button type="button" :class="{ active: tokenUnit === 'K' }" :aria-pressed="tokenUnit === 'K'" @click="tokenUnit = 'K'">K</button>
            <button type="button" :class="{ active: tokenUnit === 'M' }" :aria-pressed="tokenUnit === 'M'" @click="tokenUnit = 'M'">M</button>
          </div>
        </template>
        <div class="ai-rate-banner">
          <span class="rate-chip">转换比例：{{ aiUsage?.rate_per_1k_tokens ?? 1 }} 🥫 = 1K tokens</span>
          <span class="rate-note">饼干耗尽后将无法使用 AI 助手，可通过提交分析任务赚取饼干</span>
        </div>
        <template v-if="aiUsage && aiUsage.summary.messages > 0">
          <NGrid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" style="margin-top: 16px">
            <NGridItem>
              <NStatistic label="近 30 天 Token 消耗" :value="formatTokens(aiUsage.summary.total_tokens)" />
            </NGridItem>
            <NGridItem>
              <NStatistic label="折合饼干" :value="aiUsage.summary.cookie_cost.toFixed(1)">
                <template #suffix>🥫</template>
              </NStatistic>
            </NGridItem>
            <NGridItem>
              <NStatistic label="AI 消息数" :value="aiUsage.summary.messages">
                <template #suffix>条</template>
              </NStatistic>
            </NGridItem>
            <NGridItem>
              <NStatistic label="会话数" :value="aiUsage.summary.sessions">
                <template #suffix>个</template>
              </NStatistic>
            </NGridItem>
          </NGrid>
          <NDataTable
            :columns="aiColumns"
            :data="aiUsage.records"
            :row-key="(row: AiTokenUsageRecord) => `${row.time}-${row.session_id}`"
            :pagination="{ pageSize: 10 }"
            :bordered="false"
            size="small"
            style="margin-top: 16px"
          />
        </template>
        <NEmpty v-else description="近 30 天暂无 AI 对话记录" style="margin-top: 16px" />
      </NCard>

      <NCard title="交易流水" :bordered="false" class="arco-card">
        <NDataTable
          :columns="columns"
          :data="transactions"
          :row-key="(row) => row.id ?? `${row.created_at}-${row.source_id}-${row.txn_type}`"
          :loading="loading"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
          size="small"
        />
      </NCard>
    </NSpace>
  </div>
</template>

<style scoped>
.ai-rate-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  padding: 10px 14px;
  border: 1px solid var(--neutral-border);
  border-radius: 10px;
  background: var(--neutral-fill-2);
}

.rate-chip {
  color: var(--arco-primary);
  font-size: 13px;
  font-weight: 600;
}

.rate-note {
  color: var(--neutral-text-3);
  font-size: 12px;
}

</style>
