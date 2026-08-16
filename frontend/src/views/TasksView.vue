<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Task } from '@/types'
import TaskTable from '@/components/task/TaskTable.vue'
import AgentTeamsCasesPanel from '@/components/task/AgentTeamsCasesPanel.vue'
import AppLoading from '@/components/AppLoading.vue'
import EmptyState from '@/components/EmptyState.vue'
import PageHeader from '@/components/PageHeader.vue'
import apiClient from '@/api/client'
import { useApi } from '@/composables/useApi'
import { exportTasksToExcel } from '@/utils/taskExport'
import { NInput, NSelect, NButton, NIcon, NTabs, NTabPane, useMessage } from 'naive-ui'
import { BeakerOutline, DownloadOutline, RefreshOutline, SearchOutline } from '@vicons/ionicons5'

const message = useMessage()
const route = useRoute()
const router = useRouter()

// tab 与地址栏 query 同步，支持 /tasks?tab=agent-teams 深链（如 Case 详情页返回）
const activeTab = ref<'analysis' | 'agent-teams'>(route.query.tab === 'agent-teams' ? 'agent-teams' : 'analysis')
watch(activeTab, (tab) => {
  router.replace({ query: tab === 'analysis' ? {} : { tab } })
})

const statusFilter = ref<Task['status'] | 'all'>('all')
const searchQuery = ref('')
const knownCompletedTaskIds = ref(new Set<string>())
const hasInitializedTaskSnapshot = ref(false)
const exporting = ref(false)

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '待审核', value: 'pending' },
  { label: '排队中', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' },
]

const {
  data: tasks,
  loading,
  execute: fetchTasks,
} = useApi<Task[]>(
  async () => {
    const res = await apiClient.get<{ items: Task[]; total: number }>('/tasks', {
      params: statusFilter.value === 'all' ? {} : { status: statusFilter.value },
    })
    return res.data.items
  },
  { initialData: [] },
)

const filteredTasks = computed(() => {
  let list = tasks.value || []
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.flow_id.toLowerCase().includes(q) ||
        (t.error_message || '').toLowerCase().includes(q),
    )
  }
  return list
})

watch(tasks, (nextTasks) => {
  const taskList = nextTasks ?? []
  const completedIds = new Set(
    taskList.filter((task) => task.status === 'success').map((task) => task.id),
  )

  if (hasInitializedTaskSnapshot.value) {
    const newlyCompleted = taskList.filter(
      (task) => task.status === 'success' && !knownCompletedTaskIds.value.has(task.id),
    )
    if (newlyCompleted.length) {
      const name = newlyCompleted[0].name
      const suffix = newlyCompleted.length > 1 ? `，另有 ${newlyCompleted.length - 1} 项已完成` : ''
      message.success(`⭐ 「${name}」分析已完成${suffix}`)
    }
  }

  knownCompletedTaskIds.value = completedIds
  hasInitializedTaskSnapshot.value = true
})

async function handleDelete(task: Task) {
  try {
    await apiClient.delete(`/tasks/${task.id}`)
    message.success(`已删除「${task.name}」`)
    await fetchTasks()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除失败，请稍后重试')
  }
}

/** 受限并发：把任务切成最多 concurrency 路并行，避免批量时打爆后端连接。 */
async function runWithConcurrency<T>(items: T[], concurrency: number, worker: (item: T) => Promise<void>) {
  const results: PromiseSettledResult<void>[] = []
  for (let i = 0; i < items.length; i += concurrency) {
    const chunk = items.slice(i, i + concurrency)
    const settled = await Promise.allSettled(chunk.map(worker))
    results.push(...settled)
  }
  return results
}

const failDetail = (r: PromiseSettledResult<void>) =>
  r.status === 'rejected' ? (r.reason?.response?.data?.detail || r.reason?.message || '') : ''

/** 批量删除：复用单删接口 DELETE /tasks/{id}，逐项容错，结束统一刷新并汇总结果。 */
async function handleBatchDelete(list: Task[]) {
  if (!list.length) return
  const results = await runWithConcurrency(list, 6, async (t) => {
    await apiClient.delete(`/tasks/${t.id}`)
  })
  const failed = results.filter((r) => r.status === 'rejected')
  await fetchTasks()
  if (!failed.length) {
    message.success(`已删除 ${list.length} 个任务`)
  } else {
    const detail = failDetail(failed[0] as PromiseRejectedResult)
    message.warning(`已删除 ${list.length - failed.length} 个，${failed.length} 个失败${detail ? `（${detail}）` : ''}`)
  }
}

/** 批量取消：复用 POST /tasks/{id}/cancel，仅对未结束任务有意义（表格已据此过滤）。 */
async function handleBatchCancel(list: Task[]) {
  if (!list.length) return
  const results = await runWithConcurrency(list, 6, async (t) => {
    await apiClient.post(`/tasks/${t.id}/cancel`)
  })
  const failed = results.filter((r) => r.status === 'rejected')
  await fetchTasks()
  if (!failed.length) {
    message.success(`已取消 ${list.length} 个任务`)
  } else {
    const detail = failDetail(failed[0] as PromiseRejectedResult)
    message.warning(`已取消 ${list.length - failed.length} 个，${failed.length} 个失败${detail ? `（${detail}）` : ''}`)
  }
}

/** 导出当前视图（已应用搜索 / 状态筛选）为 Excel，纯前端生成、即时下载。 */
function handleExport() {
  const list = filteredTasks.value
  if (!list.length) {
    message.warning('当前没有可导出的任务')
    return
  }
  exporting.value = true
  try {
    exportTasksToExcel(list)
    message.success(`已导出 ${list.length} 条任务`)
  } catch (e: any) {
    message.error(e?.message || '导出失败，请稍后重试')
  } finally {
    exporting.value = false
  }
}

onMounted(fetchTasks)
</script>

<template>
  <div class="page-container tasks-page">
    <PageHeader title="任务中心" subtitle="管理和监控所有生信分析任务的执行状态" />

    <NTabs v-model:value="activeTab" type="line" animated class="tasks-tabs">
      <NTabPane name="analysis" tab="分析任务">
        <div class="tasks-toolbar">
          <NInput
            v-model:value="searchQuery"
            placeholder="搜索任务名称、流程、错误信息..."
            clearable
            class="task-search"
          >
            <template #prefix>
              <NIcon :size="14"><SearchOutline /></NIcon>
            </template>
          </NInput>
          <NSelect
            v-model:value="statusFilter"
            :options="statusOptions"
            style="width: 140px"
            @update:value="fetchTasks"
          />
          <NButton :loading="exporting" :disabled="!filteredTasks.length" @click="handleExport">
            <template #icon>
              <NIcon><DownloadOutline /></NIcon>
            </template>
            导出 Excel
          </NButton>
          <NButton type="primary" :loading="loading" @click="fetchTasks">
            <template #icon>
              <NIcon><RefreshOutline /></NIcon>
            </template>
            刷新
          </NButton>
        </div>

        <div v-if="loading && !filteredTasks.length" class="tasks-loading">
          <AppLoading text="加载任务列表..." />
        </div>
        <EmptyState
          v-else-if="!filteredTasks.length"
          :icon="BeakerOutline"
          :title="searchQuery || statusFilter !== 'all' ? '没有匹配的任务' : '暂时没有分析任务'"
          :description="searchQuery || statusFilter !== 'all' ? '请调整搜索关键词或筛选条件后重试。' : '前往分析中心提交第一个任务后，执行进度会显示在这里。'"
        />
        <TaskTable
          v-else
          :tasks="filteredTasks"
          :loading="loading"
          show-user
          @delete="handleDelete"
          @batch-delete="handleBatchDelete"
          @batch-cancel="handleBatchCancel"
        />
      </NTabPane>
      <NTabPane name="agent-teams" tab="AgentTeams 协作">
        <AgentTeamsCasesPanel />
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.tasks-page {
  min-height: 100%;
  background: var(--neutral-bg);
}

.tasks-tabs {
  margin-top: 8px;
}

.tasks-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.tasks-toolbar :deep(.n-input),
.tasks-toolbar :deep(.n-base-selection) {
  color: var(--neutral-text-1);
  background: var(--neutral-card);
  border-color: var(--neutral-border);
}

.tasks-toolbar :deep(.n-input__input-el),
.tasks-toolbar :deep(.n-base-selection-input__content) {
  color: var(--neutral-text-1);
}

.tasks-toolbar :deep(.n-input__input-el::placeholder) {
  color: var(--neutral-text-3);
}

.tasks-toolbar :deep(.n-button:not(.n-button--primary-type)) {
  color: var(--neutral-text-1);
  background: var(--neutral-card);
  border-color: var(--neutral-border);
}

.tasks-toolbar :deep(.n-button:not(.n-button--primary-type):hover) {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
  border-color: var(--brand-primary);
}

.task-search {
  width: 260px;
}

.tasks-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
}

@media (max-width: 768px) {
  .tasks-toolbar {
    justify-content: flex-start;
  }
  .tasks-toolbar :deep(.n-input),
  .tasks-toolbar :deep(.n-select) {
    width: 100% !important;
  }

  .task-search {
    flex: 1 1 220px;
  }
}
</style>
