<script setup lang="ts">
import apiClient from '@/api/client'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NInput,
  NSelect,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'
import { h, onMounted, ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import { displayName } from '@/utils/displayName'

const route = useRoute()

interface TxnRow {
  id: number
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

const message = useMessage()
const loading = ref(false)
const data = ref<TxnRow[]>([])
const total = ref(0)

const filters = reactive({
  user_id: '',
  txn_type: null as string | null,
  source_type: null as string | null,
  date_range: null as [number, number] | null,
})

const page = reactive({ offset: 0, limit: 20 })

const txnTypeOptions = [
  { label: '全部', value: '' },
  { label: '获得 earn', value: 'earn' },
  { label: '消费 spend', value: 'spend' },
  { label: '调整 adjust', value: 'adjust' },
  { label: '退还 refund', value: 'refund' },
  { label: '冻结 freeze', value: 'freeze' },
  { label: '解冻 unfreeze', value: 'unfreeze' },
]

const sourceTypeOptions = [
  { label: '全部', value: '' },
  { label: '任务 task', value: 'task' },
  { label: '沙盒 sandbox', value: 'sandbox' },
  { label: '管理员 admin', value: 'admin' },
  { label: '注册 signup', value: 'signup' },
]

function txnTagType(type: string): 'success' | 'error' | 'warning' | 'info' | 'default' {
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
    width: 180,
    render: (row: TxnRow) => (row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-'),
  },
  { title: '用户', key: 'username', width: 100, render: (row: TxnRow) => displayName(row) || '-' },
  { title: '邮箱', key: 'email', ellipsis: { tooltip: true } },
  {
    title: '类型',
    key: 'txn_type',
    width: 100,
    render: (row: TxnRow) => h(NTag, { type: txnTagType(row.txn_type), size: 'small', round: true }, { default: () => row.txn_type }),
  },
  {
    title: '金额',
    key: 'amount',
    width: 100,
    render: (row: TxnRow) => {
      const color = row.amount >= 0 ? 'var(--arco-success)' : 'var(--arco-danger)'
      return h('span', { style: { color, fontWeight: 500 } }, `${row.amount >= 0 ? '+' : ''}${Number(row.amount).toFixed(2)}`)
    },
  },
  { title: '交易后余额', key: 'balance_after', width: 110, render: (row: TxnRow) => Number(row.balance_after).toFixed(2) },
  { title: '来源', key: 'source_type', width: 80 },
  { title: '说明', key: 'description', ellipsis: { tooltip: true } },
]

async function fetchData() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      offset: page.offset,
      limit: page.limit,
    }
    if (filters.user_id) params.user_id = filters.user_id
    if (filters.txn_type) params.txn_type = filters.txn_type
    if (filters.source_type) params.source_type = filters.source_type
    if (filters.date_range) {
      params.date_from = new Date(filters.date_range[0]).toISOString()
      params.date_to = new Date(filters.date_range[1]).toISOString()
    }
    const res = await apiClient.get('/admin/cookies/transactions/filtered', { params })
    data.value = res.data.items
    total.value = res.data.total
  } catch (e: any) {
    message.error(e.response?.data?.detail || '获取交易流水失败')
  } finally {
    loading.value = false
  }
}

function handlePageChange(currentPage: number) {
  page.offset = (currentPage - 1) * page.limit
  fetchData()
}

function applyFilters() {
  page.offset = 0
  fetchData()
}

function resetFilters() {
  filters.user_id = ''
  filters.txn_type = null
  filters.source_type = null
  filters.date_range = null
  page.offset = 0
  fetchData()
}

onMounted(() => {
  // 接收跨页跳转带来的 user_id（来自「用户管理」→ 查看资产流水）
  const q = route.query.user_id
  if (q && typeof q === 'string') {
    filters.user_id = q
  }
  fetchData()
})
</script>

<template>
  <div class="page-container">
    <PageHeader title="交易流水审计" subtitle="按用户、来源和时间范围追踪平台饼干流水" />
    <NSpace vertical :size="24">
      <NCard title="筛选条件" :bordered="false" class="arco-card">
        <NSpace :size="16" align="center" wrap>
          <NInput
            v-model:value="filters.user_id"
            placeholder="用户 ID（跨页跳转带入）"
            clearable
            style="width: 280px"
          />
          <NSelect
            v-model:value="filters.txn_type"
            :options="txnTypeOptions"
            placeholder="交易类型"
            clearable
            style="width: 160px"
          />
          <NSelect
            v-model:value="filters.source_type"
            :options="sourceTypeOptions"
            placeholder="来源"
            clearable
            style="width: 160px"
          />
          <NDatePicker
            v-model:value="filters.date_range"
            type="datetimerange"
            clearable
            style="width: 400px"
          />
          <NButton type="primary" @click="applyFilters">查询</NButton>
          <NButton @click="resetFilters">重置</NButton>
        </NSpace>
      </NCard>

      <NCard title="全局交易流水审计" :bordered="false" class="arco-card">
        <NDataTable
          :columns="columns"
          :data="data"
          :row-key="(row) => row.id"
          :loading="loading"
          :pagination="{
            page: Math.floor(page.offset / page.limit) + 1,
            pageSize: page.limit,
            itemCount: total,
            onChange: handlePageChange,
            showSizePicker: false,
          }"
          :bordered="false"
          size="small"
        />
      </NCard>
    </NSpace>
  </div>
</template>
