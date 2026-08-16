<script setup lang="ts">
import apiClient from '@/api/client'
import {
  NButton,
  NCard,
  NDataTable,
  NInputNumber,
  NDatePicker,
  NTimePicker,
  NSwitch,
  NTag,
  NModal,
  NSelect,
  NSpace,
  NInput,
  useMessage,
} from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import type { CookieDiscount } from '@/types'

withDefaults(defineProps<{ embedded?: boolean }>(), {
  embedded: false,
})

const message = useMessage()
const pricing = ref<any[]>([])
const discounts = ref<CookieDiscount[]>([])
const loading = ref(false)
const discountLoading = ref(false)
const showEdit = ref(false)
const showDiscountEdit = ref(false)
const editForm = ref<any>({
  pricing_type: 'task_type',
  resource_type: '',
  flow_category: '',
  base_cost: 1,
  per_sample_cost: 0,
  per_comparison_cost: 0,
  unit: 'per_sample',
  priority: 0,
  description: '',
  effective_until: null,
})
const discountForm = ref<any>({
  name: '',
  discount_multiplier: 0.01,
  date_range: null,
  daily_start: null,
  daily_end: null,
  timezone: 'Asia/Shanghai',
  priority: 100,
  is_active: true,
  banner_title: 'AI 饼干限时优惠',
  banner_description: '当前 Token 换算享受限时优惠，欢迎使用 AI 助手。',
})

const typeOptions = [
  { label: '任务类型', value: 'task_type' },
  { label: '资源', value: 'resource' },
  { label: '沙盒', value: 'sandbox' },
  { label: '奖励', value: 'bonus' },
]
const unitOptions = [
  { label: '每次任务', value: 'per_task' },
  { label: '每小时', value: 'per_hour' },
  { label: '每核时', value: 'per_core_hour' },
  { label: '每GB时', value: 'per_gb_hour' },
  { label: '每次会话', value: 'per_session' },
  { label: '每用户', value: 'per_user' },
  { label: '每样本', value: 'per_sample' },
  { label: '每比较组', value: 'per_comparison' },
]

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '类型', key: 'pricing_type' },
  { title: '流程类别', key: 'flow_category' },
  { title: '资源类型', key: 'resource_type' },
  { title: '基础费用', key: 'base_cost', render: (r: any) => Number(r.base_cost).toFixed(2) },
  { title: '单样本费用', key: 'per_sample_cost', render: (r: any) => Number(r.per_sample_cost || 0).toFixed(2) },
  { title: '每组比较费用', key: 'per_comparison_cost', render: (r: any) => Number(r.per_comparison_cost || 0).toFixed(2) },
  { title: '单位', key: 'unit' },
  { title: '优先级', key: 'priority' },
  {
    title: '状态',
    key: 'is_active',
    render: (r: any) => (r.is_active ? '启用' : '停用'),
  },
  {
    title: '操作',
    key: 'actions',
    render: (row: any) => h(NSpace, {}, {
      default: () => [
        h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', type: 'error', onClick: () => delPricing(row.id) }, { default: () => '删除' }),
      ],
    }),
  },
]

async function fetchPricing() {
  loading.value = true
  try {
    const res = await apiClient.get('/admin/cookies/pricing')
    pricing.value = res.data
  } finally {
    loading.value = false
  }
}

function openEdit(row?: any) {
  if (row) {
    editForm.value = { ...row }
  } else {
    editForm.value = { pricing_type: 'task_type', resource_type: '', flow_category: '', base_cost: 1, per_sample_cost: 0, per_comparison_cost: 0, unit: 'per_sample', priority: 0, description: '', effective_until: null }
  }
  showEdit.value = true
}

async function savePricing() {
  const data = { ...editForm.value }
  if (data.id) {
    await apiClient.put(`/admin/cookies/pricing/${data.id}`, data)
    message.success('更新成功')
  } else {
    await apiClient.post('/admin/cookies/pricing', data)
    message.success('创建成功')
  }
  showEdit.value = false
  await fetchPricing()
}

async function delPricing(id: number) {
  await apiClient.delete(`/admin/cookies/pricing/${id}`)
  message.success('已删除')
  await fetchPricing()
}

onMounted(fetchPricing)

async function fetchDiscounts() {
  discountLoading.value = true
  try {
    const res = await apiClient.get('/admin/cookies/discounts')
    discounts.value = res.data
  } finally {
    discountLoading.value = false
  }
}

function formatDate(value: number | null) {
  if (!value) return ''
  const date = new Date(value)
  return date.toISOString().slice(0, 10)
}

function formatTime(value: number | null) {
  if (value === null || value === undefined) return null
  const date = new Date(value)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:00`
}

function openDiscountEdit(row?: CookieDiscount) {
  if (row) {
    discountForm.value = {
      ...row,
      date_range: [new Date(`${row.date_start}T00:00:00`).getTime(), new Date(`${row.date_end}T00:00:00`).getTime()],
      daily_start: row.daily_start ? new Date(`1970-01-01T${row.daily_start}`).getTime() : null,
      daily_end: row.daily_end ? new Date(`1970-01-01T${row.daily_end}`).getTime() : null,
    }
  } else {
    discountForm.value = {
      name: '', discount_multiplier: 0.01, date_range: null,
      daily_start: null, daily_end: null, timezone: 'Asia/Shanghai', priority: 100,
      is_active: true, banner_title: 'AI 饼干限时优惠',
      banner_description: '当前 Token 换算享受限时优惠，欢迎使用 AI 助手。',
    }
  }
  showDiscountEdit.value = true
}

async function saveDiscount() {
  const range = discountForm.value.date_range
  if (!range?.[0] || !range?.[1]) {
    message.error('请选择生效日期范围')
    return
  }
  const data = {
    name: discountForm.value.name,
    discount_multiplier: discountForm.value.discount_multiplier,
    date_start: formatDate(range[0]),
    date_end: formatDate(range[1]),
    daily_start: formatTime(discountForm.value.daily_start),
    daily_end: formatTime(discountForm.value.daily_end),
    timezone: discountForm.value.timezone,
    priority: discountForm.value.priority,
    is_active: discountForm.value.is_active,
    banner_title: discountForm.value.banner_title,
    banner_description: discountForm.value.banner_description,
  }
  if (discountForm.value.id) {
    await apiClient.put(`/admin/cookies/discounts/${discountForm.value.id}`, data)
    message.success('优惠规则已更新')
  } else {
    await apiClient.post('/admin/cookies/discounts', data)
    message.success('优惠规则已创建')
  }
  showDiscountEdit.value = false
  await fetchDiscounts()
}

async function deleteDiscount(id: number) {
  await apiClient.delete(`/admin/cookies/discounts/${id}`)
  message.success('优惠规则已删除')
  await fetchDiscounts()
}

const discountColumns = computed(() => [
  { title: '规则', key: 'name' },
  { title: '折扣倍率', key: 'discount_multiplier', render: (row: CookieDiscount) => `${row.discount_multiplier} 倍` },
  { title: '日期', key: 'date_start', render: (row: CookieDiscount) => `${row.date_start} 至 ${row.date_end}` },
  { title: '每日时段', key: 'daily_start', render: (row: CookieDiscount) => row.daily_start ? `${row.daily_start.slice(0, 5)} - ${row.daily_end?.slice(0, 5)}` : '全天' },
  { title: '状态', key: 'is_active', render: (row: CookieDiscount) => h(NTag, { type: row.is_active ? 'success' : 'default' }, { default: () => row.is_active ? '启用' : '停用' }) },
  { title: '操作', key: 'actions', render: (row: CookieDiscount) => h(NSpace, {}, { default: () => [
    h(NButton, { size: 'small', onClick: () => openDiscountEdit(row) }, { default: () => '编辑' }),
    h(NButton, { size: 'small', type: 'error', onClick: () => deleteDiscount(row.id) }, { default: () => '删除' }),
  ] }) },
])

onMounted(fetchDiscounts)
</script>

<template>
  <div class="page-container" :class="{ 'page-container--embedded': embedded }">
    <PageHeader v-if="!embedded" title="饼干定价管理" subtitle="维护任务、资源和奖励的计费策略" />
    <NSpace vertical :size="24">
      <NCard title="定价策略管理" :bordered="false" class="arco-card">
        <template #header-extra>
          <NButton type="primary" @click="openEdit()">新建定价</NButton>
        </template>
        <NDataTable :columns="columns" :data="pricing" :row-key="(row) => row.id" :loading="loading" :pagination="{ pageSize: 20 }" :bordered="false" size="small" />
      </NCard>

      <NCard title="AI Token 时段优惠" :bordered="false" class="arco-card">
        <template #header-extra>
          <NButton type="primary" secondary @click="openDiscountEdit()">新增优惠</NButton>
        </template>
        <p class="helper-text">默认换算为 1 🥫/1K tokens；倍率 0.01 表示按原价的 1% 计费。优惠生效时会自动显示在首页条幅。</p>
        <NDataTable :columns="discountColumns" :data="discounts" :loading="discountLoading" :row-key="(row) => row.id" :pagination="{ pageSize: 10 }" :bordered="false" size="small" />
      </NCard>

      <NModal v-model:show="showEdit" :title="editForm.id ? '编辑定价' : '新建定价'" preset="dialog" style="width: 560px">
        <NSpace vertical :size="16" style="padding: 16px 0">
          <div>定价类型:</div>
          <NSelect v-model:value="editForm.pricing_type" :options="typeOptions" />
          <div>流程类别 (如 rna_seq):</div>
          <NInput v-model:value="editForm.flow_category" placeholder="留空表示通用" />
          <div>资源类型:</div>
          <NInput v-model:value="editForm.resource_type" placeholder="如 cpu_core_per_hour" />
          <div>基础费用:</div>
          <NInputNumber v-model:value="editForm.base_cost" :step="0.1" :min="0" style="width: 100%" />
          <div>单样本费用:</div>
          <NInputNumber v-model:value="editForm.per_sample_cost" :step="0.1" :min="0" style="width: 100%" />
          <div>每组比较费用:</div>
          <NInputNumber v-model:value="editForm.per_comparison_cost" :step="0.1" :min="0" style="width: 100%" />
          <div>计价单位:</div>
          <NSelect v-model:value="editForm.unit" :options="unitOptions" />
          <div>优先级 (数字越大越优先):</div>
          <NInputNumber v-model:value="editForm.priority" :step="1" style="width: 100%" />
          <div>描述:</div>
          <NInput v-model:value="editForm.description" type="textarea" placeholder="可选" />
          <NButton type="primary" @click="savePricing">保存</NButton>
        </NSpace>
      </NModal>

      <NModal v-model:show="showDiscountEdit" :title="discountForm.id ? '编辑 Token 优惠' : '新增 Token 优惠'" preset="dialog" style="width: 620px">
        <NSpace vertical :size="14" style="padding: 16px 0">
          <div>规则名称</div>
          <NInput v-model:value="discountForm.name" placeholder="如：暑期夜间优惠" />
          <div>折扣倍率（1.00=原价，0.01=1%）</div>
          <NInputNumber v-model:value="discountForm.discount_multiplier" :min="0" :max="1" :step="0.01" style="width: 100%" />
          <div>生效日期</div>
          <NDatePicker v-model:value="discountForm.date_range" type="daterange" clearable style="width: 100%" />
          <div>每天生效时间（留空表示全天；支持跨午夜）</div>
          <NSpace>
            <NTimePicker v-model:value="discountForm.daily_start" format="HH:mm" clearable />
            <span class="time-separator">至</span>
            <NTimePicker v-model:value="discountForm.daily_end" format="HH:mm" clearable />
          </NSpace>
          <div>时区</div>
          <NInput v-model:value="discountForm.timezone" placeholder="Asia/Shanghai" />
          <div>优先级（越大越优先）</div>
          <NInputNumber v-model:value="discountForm.priority" :step="1" style="width: 100%" />
          <NSpace align="center"><span>启用规则</span><NSwitch v-model:value="discountForm.is_active" /></NSpace>
          <div>首页条幅标题</div>
          <NInput v-model:value="discountForm.banner_title" />
          <div>首页条幅内容</div>
          <NInput v-model:value="discountForm.banner_description" type="textarea" />
          <NButton type="primary" @click="saveDiscount">保存优惠规则</NButton>
        </NSpace>
      </NModal>
    </NSpace>
  </div>
</template>

<style scoped>
.page-container--embedded { padding: 0; background: transparent; }
.helper-text { color: var(--neutral-text-2); margin: 0 0 16px; font-size: 13px; }
.time-separator { line-height: 34px; color: var(--neutral-text-2); }
</style>
