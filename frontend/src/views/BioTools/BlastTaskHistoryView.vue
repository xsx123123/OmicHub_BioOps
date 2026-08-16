<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NDataTable, NIcon, NInput, NPagination, NSelect, NSpace, NTag, useMessage } from 'naive-ui'
import { ArrowBackOutline, RefreshOutline, SearchOutline } from '@vicons/ionicons5'
import { fetchBlastTasks } from '@/api/blast'
import PageHeader from '@/components/PageHeader.vue'
import type { BlastTaskListItem, TaskStatus } from '@/types/blast'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const tasks = ref<BlastTaskListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const status = ref<TaskStatus | 'all'>('all')
const search = ref('')

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '排队中', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' },
]
const statusText: Record<string, string> = {
  queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消',
}
const statusType: Record<string, 'default' | 'success' | 'warning' | 'error'> = {
  queued: 'default', running: 'warning', completed: 'success', failed: 'error', cancelled: 'default',
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString() : '-'
}

const columns = [
  { title: '任务 ID', key: 'task_id', width: 170, ellipsis: { tooltip: true } },
  { title: '查询名称', key: 'query_title', minWidth: 150, ellipsis: { tooltip: true } },
  { title: '数据库', key: 'db_name', minWidth: 140, ellipsis: { tooltip: true } },
  { title: '算法', key: 'program', width: 90 },
  {
    title: '状态', key: 'status', width: 90,
    render: (row: BlastTaskListItem) => h(NTag, { size: 'small', type: statusType[row.status] || 'default' }, { default: () => statusText[row.status] || row.status }),
  },
  { title: '命中数', key: 'hit_count', width: 80, render: (row: BlastTaskListItem) => row.hit_count ?? '-' },
  { title: '提交时间', key: 'submitted_at', width: 170, render: (row: BlastTaskListItem) => formatTime(row.submitted_at) },
  {
    title: '操作', key: 'actions', width: 150,
    render: (row: BlastTaskListItem) => h(NSpace, { size: 4 }, { default: () => [
      h(NButton, { size: 'tiny', disabled: row.status !== 'completed', onClick: () => router.push({ path: '/tools/blast', query: { task: row.task_id } }) }, { default: () => '查看' }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push({ path: '/tools/blast', query: { rerun: row.task_id } }) }, { default: () => '重新运行' }),
    ] }),
  },
]

async function loadTasks(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const response = await fetchBlastTasks(status.value === 'all' ? undefined : status.value, page.value, pageSize.value, search.value.trim() || undefined)
    tasks.value = response.items
    total.value = response.total
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载 BLAST 任务失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => loadTasks())
</script>

<template>
  <div class="history-page">
    <PageHeader title="BLAST 任务中心" subtitle="查询、筛选和打开历史 BLAST 检索任务" back-to="/tools/blast" back-label="返回 BLAST">
      <template #actions>
        <NButton :loading="loading" @click="loadTasks()"><template #icon><NIcon><RefreshOutline /></NIcon></template>刷新</NButton>
      </template>
    </PageHeader>

    <div class="filter-card">
      <NSelect v-model:value="status" :options="statusOptions" style="width: 150px" @update:value="loadTasks(true)" />
      <NInput v-model:value="search" clearable placeholder="搜索任务 ID 或查询名称" @keyup.enter="loadTasks(true)">
        <template #prefix><NIcon><SearchOutline /></NIcon></template>
      </NInput>
      <NButton type="primary" @click="loadTasks(true)">搜索</NButton>
    </div>

    <div class="table-card">
      <NDataTable :columns="columns" :data="tasks" :row-key="(row) => row.task_id" :loading="loading" :bordered="false" :single-line="false" :scroll-x="920" />
      <div class="pagination-row">
        <span>共 {{ total }} 条</span>
        <NPagination v-model:page="page" v-model:page-size="pageSize" :item-count="total" :page-sizes="[10, 20, 50]" show-size-picker @update:page="loadTasks()" @update:page-size="loadTasks(true)" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-page { padding: 16px; min-height: 100%; }
.page-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.page-toolbar h1 { margin: 0; font-size: 20px; color: var(--neutral-text-1); }
.filter-card { display: grid; grid-template-columns: 150px minmax(240px, 420px) auto auto; gap: 10px; align-items: center; margin-bottom: 12px; padding: 14px; border: 1px solid var(--neutral-border); border-radius: 12px; background: var(--neutral-card); }
.table-card { overflow: hidden; border: 1px solid var(--neutral-border); border-radius: 12px; background: var(--neutral-card); }
.pagination-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; color: var(--neutral-text-2); font-size: 12px; }
@media (max-width: 760px) { .filter-card { grid-template-columns: 1fr 1fr; } .filter-card :deep(.n-input) { grid-column: 1 / -1; } .pagination-row { align-items: flex-start; gap: 12px; flex-direction: column; } }
</style>
