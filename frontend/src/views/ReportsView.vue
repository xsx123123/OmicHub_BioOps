<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Report, ReportFilter } from '@/types/report'
import { reportApi } from '@/api/report'
import { studioApi } from '@/api/studio'
import { useApi } from '@/composables/useApi'
import {
  NInput, NSelect, NButton, NIcon, NSpin, NPagination,
  useMessage,
} from 'naive-ui'
import {
  SearchOutline, RefreshOutline,
  DocumentTextOutline, CalendarOutline, TimeOutline, StarOutline,
} from '@vicons/ionicons5'
import ReportCardMinimal from '@/components/report/ReportCardMinimal.vue'
import ReportStatCard from '@/components/report/ReportStatCard.vue'
import ReportPreviewModal from '@/components/report/ReportPreviewModal.vue'
import ReportEmptyState from '@/components/report/ReportEmptyState.vue'
import PageHeader from '@/components/PageHeader.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const previewReport = ref<Report | null>(null)
const taskIdFromQuery = computed(() => route.query.taskId as string | undefined)

const filter = ref<ReportFilter>({
  keyword: '',
  flow_id: '',
  status: '',
  date_range: '',
  is_starred: undefined,
  page: 1,
  page_size: 10,
})

const flowOptions = [
  { label: '全部流程', value: '' },
  { label: 'RNA-seq', value: 'rna_seq' },
  { label: 'ATAC-seq', value: 'atac_seq' },
  { label: 'RNA-seq', value: 'rna-seq' },
]

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '已完成', value: 'completed' },
  { label: '生成中', value: 'generating' },
  { label: '失败', value: 'failed' },
  { label: '已过期', value: 'expired' },
]

const dateOptions = [
  { label: '全部时间', value: '' },
  { label: '最近7天', value: '7d' },
  { label: '最近30天', value: '30d' },
  { label: '最近90天', value: '90d' },
]

const {
  data: reportData,
  loading,
  execute: fetchReports,
} = useApi(() => {
  return reportApi.getReports(filter.value).then(res => res.data)
}, {
  initialData: { items: [], total: 0 },
})

const {
  data: stats,
  execute: fetchStats,
} = useApi(() => {
  return reportApi.getReportStats().then(res => res.data)
}, {
  initialData: { total: 0, starred: 0, generating: 0, today: 0 },
})

const reports = computed(() => reportData.value?.items || [])
const total = computed(() => reportData.value?.total || 0)

const highlightedReportId = ref<string | null>(null)

async function loadData() {
  await Promise.all([fetchReports(), fetchStats()])
}

function onFilterChange() {
  filter.value.page = 1
  fetchReports()
}

function handlePreview(report: Report) {
  previewReport.value = report
  if (!report.is_read) {
    reportApi.markAsRead(report.id).catch(() => {})
  }
}

function handleDownload(report: Report, fileId: string) {
  const link = document.createElement('a')
  link.href = `/api/v1/reports/${report.id}/files/${fileId}/download`
  link.download = report.title
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function handleViewTask(report: Report) {
  router.push({ name: 'task-detail', params: { taskId: report.task_id } })
}

async function handleOptimize(report: Report) {
  try {
    const session = await studioApi.createSessionFromReport({
      report_id: report.id,
      agent_id: 'agent-viz',
    })
    router.push({ name: 'studio', params: { sessionId: session.session_id } })
  } catch {
    message.error('创建 AI 工作台会话失败')
  }
}

async function handleToggleStar(report: Report) {
  try {
    await reportApi.toggleStar(report.id, !report.is_starred)
    message.success(report.is_starred ? '已取消收藏' : '已收藏')
    await loadData()
  } catch {
    message.error('操作失败')
  }
}

async function handleDelete(report: Report) {
  try {
    await reportApi.deleteReport(report.id)
    message.success('已删除')
    await loadData()
  } catch {
    message.error('删除失败')
  }
}

watch(
  () => route.query.taskId,
  (taskId) => {
    if (taskId) {
      highlightedReportId.value = null
      filter.value.keyword = String(taskId)
      filter.value.page = 1
      loadData().then(() => {
        const matched = reports.value.find(r => r.task_id === taskId)
        if (matched) {
          highlightedReportId.value = matched.id
        }
      })
    } else {
      highlightedReportId.value = null
    }
  },
  { immediate: true },
)

onMounted(() => {
  if (!taskIdFromQuery.value) {
    loadData()
  }
})
</script>

<template>
  <div class="reports-page">
    <PageHeader title="结果报告中心" subtitle="查看和管理所有分析生成的报告，支持在线预览和下载">
      <template #actions>
        <NButton secondary :loading="loading" @click="loadData">
          <template #icon>
            <NIcon :component="RefreshOutline" />
          </template>
          刷新报告
        </NButton>
      </template>
    </PageHeader>

    <!-- 顶部数据看板 -->
    <div class="stats-dashboard">
      <ReportStatCard
        title="总报告数"
        :value="stats?.total || 0"
        :icon="DocumentTextOutline"
        color="blue"
      />
      <ReportStatCard
        title="今日生成"
        :value="stats?.today || 0"
        :icon="CalendarOutline"
        color="purple"
      />
      <ReportStatCard
        title="生成中"
        :value="stats?.generating || 0"
        :icon="TimeOutline"
        color="orange"
        :breathing="(stats?.generating || 0) > 0"
      />
      <ReportStatCard
        title="收藏"
        :value="stats?.starred || 0"
        :icon="StarOutline"
        color="amber"
      />
    </div>

    <!-- 筛选与搜索栏 -->
    <div class="filter-bar">
      <NInput
        v-model:value="filter.keyword"
        placeholder="搜索报告名称、流程..."
        clearable
        style="width: 280px"
        @update:value="onFilterChange"
      >
        <template #prefix>
          <NIcon :size="14" :component="SearchOutline" />
        </template>
      </NInput>

      <NSelect
        v-model:value="filter.flow_id"
        :options="flowOptions"
        placeholder="分析流程"
        clearable
        style="width: 160px"
        @update:value="onFilterChange"
      />

      <NSelect
        v-model:value="filter.status"
        :options="statusOptions"
        placeholder="状态"
        clearable
        style="width: 140px"
        @update:value="onFilterChange"
      />

      <NSelect
        v-model:value="filter.date_range"
        :options="dateOptions"
        placeholder="时间范围"
        clearable
        style="width: 140px"
        @update:value="onFilterChange"
      />

    </div>

    <!-- 报告卡片列表 -->
    <NSpin :show="loading && reports.length === 0" style="width: 100%;">
      <div v-if="!loading && reports.length === 0">
        <ReportEmptyState />
      </div>

      <div v-else class="report-list">
        <ReportCardMinimal
          v-for="(report, index) in reports"
          :key="report.id"
          :report="report"
          class="stagger-item"
          :style="{ animationDelay: `${index * 0.05}s` }"
          :class="{ 'report-card--highlight': report.id === highlightedReportId }"
          @preview="handlePreview"
          @download="handleDownload"
          @view-task="handleViewTask"
          @toggle-star="handleToggleStar"
          @delete="handleDelete"
          @optimize="handleOptimize"
        />
      </div>
    </NSpin>

    <div v-if="total > 0" class="pagination-bar">
      <NPagination
        v-model:page="filter.page"
        v-model:page-size="filter.page_size"
        :item-count="total"
        :page-sizes="[10, 20, 50]"
        show-size-picker
        show-quick-jumper
        @update:page="fetchReports"
        @update:page-size="onFilterChange"
      />
    </div>

    <ReportPreviewModal
      :report="previewReport"
      @close="previewReport = null"
    />
  </div>
</template>

<style scoped>
.reports-page {
  min-height: 100%;
  background: var(--neutral-bg);
  padding: 24px;
}

/* 顶部数据看板 */
.stats-dashboard {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  background: var(--neutral-card);
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--neutral-border);
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.filter-bar :deep(.n-input) {
  background: var(--neutral-hover);
  border-radius: 10px;
  transition: all 0.2s ease;
  --n-border: none;
  --n-border-hover: none;
  --n-border-focus: none;
  --n-box-shadow-focus: none;
}
.filter-bar :deep(.n-input .n-input__border),
.filter-bar :deep(.n-input .n-input__state-border) {
  border: none;
}
.filter-bar :deep(.n-input.n-input--focus) {
  background: var(--neutral-card);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 12%, transparent), 0 0 0 4px color-mix(in srgb, var(--kimi-chart-4) 6%, transparent);
}
.filter-bar :deep(.n-input .n-input__input-el),
.filter-bar :deep(.n-input .n-input__placeholder) {
  font-size: 13px;
}
.filter-bar :deep(.n-base-selection) {
  border: none;
  background: var(--neutral-hover);
  border-radius: 10px;
  font-size: 13px;
  transition: all 0.2s ease;
}
.filter-bar :deep(.n-base-selection .n-base-selection__border),
.filter-bar :deep(.n-base-selection .n-base-selection__state-border) {
  border: none !important;
}
.filter-bar :deep(.n-base-selection:hover) {
  background: var(--neutral-hover);
}
.filter-bar :deep(.n-base-selection--active),
.filter-bar :deep(.n-base-selection--focus) {
  background: var(--neutral-card);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 12%, transparent), 0 0 0 4px color-mix(in srgb, var(--kimi-chart-4) 6%, transparent);
}
/* 报告卡片列表 */
.report-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}
.report-card--highlight {
  box-shadow: inset 0 0 0 2px var(--arco-primary), 0 8px 24px color-mix(in srgb, var(--arco-primary) 10%, transparent) !important;
}
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 0;
}

@media (max-width: 1024px) {
  .stats-dashboard {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 768px) {
  .reports-page {
    padding: 16px;
  }
  .stats-dashboard {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
    padding: 12px;
  }
  .filter-bar :deep(.n-input),
  .filter-bar :deep(.n-base-selection) {
    width: 100% !important;
  }
}
@media (max-width: 640px) {
  .stats-dashboard {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
