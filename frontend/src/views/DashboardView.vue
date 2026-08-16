<script setup lang="ts">
import { computed, ref, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NSpace, NIcon, NProgress, NTag, NTooltip, NDataTable, NEmpty, NSpin,
  NPopconfirm, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  RocketOutline, EyeOutline,
  RefreshOutline, SearchOutline, TrashOutline,
} from '@vicons/ionicons5'
import axios from 'axios'
import apiClient from '@/api/client'
import { fetchBlastTasks } from '@/api/blast'
import type { Task } from '@/types'
import type { BlastTaskListItem } from '@/types/blast'
import type { StatsOverview } from '@/types/stats'
import { useAuthStore } from '@/stores/auth'
import TrendChart from '@/components/dashboard/TrendChart.vue'
import StudioUsagePanel from '@/components/dashboard/StudioUsagePanel.vue'
import QuickStartSteps from '@/components/dashboard/QuickStartSteps.vue'
import AdminStatsPanel from '@/components/dashboard/AdminStatsPanel.vue'
import AnnouncementBanner from '@/components/AnnouncementBanner.vue'
import PageHeader from '@/components/PageHeader.vue'
import { displayName } from '@/utils/displayName'

const router = useRouter()
const authStore = useAuthStore()

const healthStatus = ref<string>('检测中...')
const healthOk = ref(false)
const healthLoading = ref(true)
const refreshing = ref(false)
const flowCount = ref(0)
const runningTaskCount = ref(0)
const totalTaskCount = ref(0)
const sampleCount = ref(0)
const recentTasks = ref<Task[]>([])
const blastTasks = ref<BlastTaskListItem[]>([])
const loadingOverview = ref(false)
const loadingTasks = ref(false)
const loadingBlastTasks = ref(false)

const message = useMessage()

// ===== 最近任务：真实接口 =====
// 操作列与「任务中心」TaskTable 行为对齐：查看 → 任务详情；删除 → 真实删除；
// 重新运行暂无后端接口，按终态禁用并提示「即将上线」（不再用假 toast 占位）。

// 查看任务详情：跳转任务详情页（与 TaskTable 一致）
function handleView(row: Task) {
  router.push({ name: 'task-detail', params: { taskId: row.id } })
}

// 删除任务：调用真实 DELETE 接口，成功后局部刷新最近任务
async function handleDelete(row: Task) {
  try {
    await apiClient.delete(`/tasks/${row.id}`)
    message.success(`已删除「${row.name}」`)
    await loadRecentTasks()
  } catch (e: unknown) {
    const detail = axios.isAxiosError(e) ? e.response?.data?.detail : undefined
    message.error((detail as string) || '删除失败，请稍后重试')
  }
}

// 终态判定：success / failed / cancelled 视为已结束（与 TaskTable 一致）
function isTerminal(status: Task['status']): boolean {
  return ['success', 'failed', 'cancelled'].includes(status)
}

// 进度归一化为 0–100 整数。
// 后端进度尺度并不统一：分析任务在富集 / arq 路径写 0–100、下载路径写 0–1，
// BLAST 进度为 0–100 整数。这里用 >1 启发式兼容两种尺度，
// 避免「已完成=100」被再次 ×100 渲染成 1000%。
function pct(value: number | null | undefined): number {
  const n = Number(value) || 0
  return Math.round(n > 1 ? n : n * 100)
}

const healthTone = computed(() => {
  if (healthLoading.value) return 'checking'
  return healthOk.value ? 'healthy' : 'error'
})

onMounted(() => {
  void loadDashboard()
})

async function loadDashboard() {
  // 健康检查
  healthLoading.value = true
  healthOk.value = false
  healthStatus.value = '检测中...'
  try {
    const res = await axios.get('/health')
    healthOk.value = res.data.status === 'ok'
    healthStatus.value = healthOk.value ? '系统运行正常' : '异常'
  } catch {
    healthStatus.value = '后端未连接'
  } finally {
    healthLoading.value = false
  }

  // 分析流程数量
  try {
    const res = await apiClient.get<{ total: number }>('/flows')
    flowCount.value = res.data.total ?? 0
  } catch {
    flowCount.value = 0
  }

  // 状态概览（运行任务 / 总任务 / 样本数）— 真实聚合接口
  loadingOverview.value = true
  try {
    const res = await apiClient.get<StatsOverview>('/stats/overview')
    runningTaskCount.value = res.data.running ?? 0
    totalTaskCount.value = res.data.total ?? 0
    sampleCount.value = res.data.samples ?? 0
  } catch {
    runningTaskCount.value = 0
    totalTaskCount.value = 0
    sampleCount.value = 0
  } finally {
    loadingOverview.value = false
  }

  // 最近任务（真实接口，仅取最近 5 条）
  await loadRecentTasks()

  // 最近 BLAST 任务
  loadingBlastTasks.value = true
  try {
    const res = await fetchBlastTasks(undefined, 1, 5)
    blastTasks.value = res.items ?? []
  } catch {
    blastTasks.value = []
  } finally {
    loadingBlastTasks.value = false
  }
}

// 拉取「最近任务」卡片的真实数据（最近 5 条）。
// 注意：不在此处覆盖 totalTaskCount —— 概览「总任务」以 /stats/overview 为准。
async function loadRecentTasks() {
  loadingTasks.value = true
  try {
    const res = await apiClient.get<{ total: number; items: Task[] }>('/tasks', {
      params: { limit: 5 },
    })
    recentTasks.value = res.data.items ?? []
  } catch {
    recentTasks.value = []
  } finally {
    loadingTasks.value = false
  }
}

async function handleRefresh() {
  if (refreshing.value) return

  refreshing.value = true
  await loadDashboard()
  refreshing.value = false

  if (healthOk.value) {
    message.success('仪表板已更新')
  } else {
    message.warning('部分平台状态暂不可用，请稍后重试')
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function statusConfig(status: string) {
  const map: Record<string, { type: 'success' | 'warning' | 'error' | 'info' | 'default'; text: string }> = {
    success: { type: 'success', text: '已完成' },
    failed: { type: 'error', text: '失败' },
    running: { type: 'info', text: '运行中' },
    queued: { type: 'warning', text: '排队中' },
    pending: { type: 'warning', text: '待审核' },
    cancelled: { type: 'default', text: '已取消' },
  }
  return map[status] || { type: 'default', text: status }
}

function taskRowKey(row: Task): string {
  return row.id
}

function blastTaskRowKey(row: BlastTaskListItem): string {
  return row.task_id
}

function renderTaskProgress(value: number | null | undefined) {
  const progress = pct(value)

  return h('div', { class: 'recent-task-progress' }, [
    h(NProgress, {
      type: 'line',
      percentage: progress,
      height: 6,
      color: { stops: ['var(--kimi-chart-1)', 'var(--brand-primary-hover)'] },
      railColor: 'var(--neutral-border)',
      showIndicator: false,
    }),
    h('span', { class: 'recent-task-progress__value' }, `${progress}%`),
  ])
}

const columns: DataTableColumns<Task> = [
  {
    title: '所属用户',
    key: 'user_id',
    width: 90,
    align: 'center',
    render: (row) => displayName(row) || row.user_id,
  },
  { title: '任务名称', key: 'name', width: 220, align: 'center', ellipsis: { tooltip: true } },
  { title: '分析流程', key: 'flow_id', width: 130, align: 'center' },
  {
    title: '提交时间',
    key: 'created_at',
    width: 150,
    align: 'center',
    render: (row) => formatTime(row.created_at),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render: (row) => {
      const cfg = statusConfig(row.status)
      return h(NTag, { type: cfg.type, size: 'small', round: true }, { default: () => cfg.text })
    },
  },
  {
    title: '进度',
    key: 'progress',
    width: 170,
    render: (row) => renderTaskProgress(row.progress),
  },
  {
    title: '操作',
    key: 'actions',
    width: 110,
    align: 'center',
    render: (row) => h(NSpace, { size: 12, justify: 'center' }, {
      default: () => [
        // 查看任务详情
        h(NTooltip, null, {
          trigger: () => h(NButton, {
            size: 'tiny', quaternary: true, circle: true,
            onClick: () => handleView(row),
          }, { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) }),
          default: () => '查看任务详情',
        }),
        // 重新运行：后端接口未上线，仅终态展示并禁用提示（与 TaskTable 一致）
        ...(isTerminal(row.status)
          ? [h(NTooltip, null, {
            trigger: () => h(NButton, {
              size: 'tiny', quaternary: true, circle: true, disabled: true,
            }, { icon: () => h(NIcon, null, { default: () => h(RefreshOutline) }) }),
            default: () => '重新运行功能即将上线',
          })]
          : []),
        // 删除：Popconfirm 二次确认（提示会清理底层计算资源与文件目录）
        h(NPopconfirm, {
          positiveText: '确认删除',
          negativeText: '取消',
          onPositiveClick: () => handleDelete(row),
        }, {
          default: () => '此操作将同时清理该用户底层的计算资源与文件目录，是否继续？',
          trigger: () => h(NTooltip, null, {
            trigger: () => h(NButton, {
              size: 'tiny', quaternary: true, circle: true, type: 'error',
            }, { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) }),
            default: () => '删除任务',
          }),
        }),
      ],
    }),
  },
]

// ===== 最近 BLAST 任务 =====
function blastStatusConfig(status: string) {
  const map: Record<string, { type: 'success' | 'warning' | 'error' | 'info' | 'default'; text: string }> = {
    completed: { type: 'success', text: '已完成' },
    failed: { type: 'error', text: '失败' },
    running: { type: 'info', text: '运行中' },
    queued: { type: 'warning', text: '排队中' },
    cancelled: { type: 'default', text: '已取消' },
  }
  return map[status] || { type: 'default', text: status }
}

const blastColumns: DataTableColumns<BlastTaskListItem> = [
  {
    title: '所属用户',
    key: 'user_id',
    width: 90,
    align: 'center',
    render: (row) => displayName(row) || row.user_id || '-',
  },
  {
    title: '任务 ID',
    key: 'task_id',
    width: 140,
    align: 'center',
    ellipsis: { tooltip: true },
    render: (row) => row.task_id.slice(0, 12),
  },
  { title: '查询标题', key: 'query_title', width: 200, align: 'center', ellipsis: { tooltip: true } },
  { title: '数据库', key: 'db_name', width: 100, align: 'center', ellipsis: { tooltip: true } },
  { title: 'Program', key: 'program', width: 100, align: 'center' },
  {
    title: '提交时间',
    key: 'submitted_at',
    width: 150,
    align: 'center',
    render: (row) => formatTime(row.submitted_at || null),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render: (row) => {
      const cfg = blastStatusConfig(row.status)
      return h(NTag, { type: cfg.type, size: 'small', round: true }, { default: () => cfg.text })
    },
  },
  {
    title: '进度',
    key: 'progress',
    width: 160,
    render: (row) => renderTaskProgress(row.progress),
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    align: 'center',
    render: (row) => h(NTooltip, null, {
      trigger: () => h(NButton, {
        size: 'tiny', quaternary: true, circle: true,
        onClick: () => router.push(`/tools/blast?task=${row.task_id}`),
      }, { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) }),
      default: () => '查看 BLAST 结果',
    }),
  },
]
</script>

<template>
  <div class="dashboard-page">
    <PageHeader title="仪表板" subtitle="掌握当前分析任务、平台运行状态与数据趋势">
      <template #actions>
        <NButton size="small" secondary :loading="refreshing" @click="handleRefresh">
          <template #icon>
            <NIcon :size="16"><RefreshOutline /></NIcon>
          </template>
          刷新数据
        </NButton>
      </template>
    </PageHeader>

    <AnnouncementBanner
      title="RNA-seq / ATAC-seq 分析已就绪"
      description="转录组与表观遗传分析流程均已上线，点击立即开始"
      action-text="立即查看"
      to="/flows"
      dismiss-key="dashboard-analysis-ready"
    />

    <!-- 快速开始（动态画像） -->
    <QuickStartSteps />

    <!-- 数据概览 - 左右分栏 -->
    <section class="overview-grid animate-fade-in-up delay-100">
      <!-- 左侧运行状态 -->
      <div class="arco-card status-card card-hover">
        <div class="arco-card-header">
          <span class="arco-card-title">运行状态</span>
        </div>
        <div class="status-main" role="status" :aria-busy="healthLoading">
          <span class="status-pulse" :class="`status-pulse--${healthTone}`" aria-hidden="true">
            <span class="status-pulse-dot" />
          </span>
          <span class="status-value" aria-live="polite">{{ healthStatus }}</span>
        </div>
        <div class="status-divider" />
        <NSpin :show="loadingOverview">
          <div class="status-metrics">
            <div class="status-metric-row">
              <span class="status-metric-label">分析流程</span>
              <span class="status-metric-value">{{ flowCount }}</span>
            </div>
            <div class="status-metric-row">
              <span class="status-metric-label">运行任务</span>
              <span class="status-metric-value">{{ runningTaskCount }}</span>
            </div>
            <div class="status-metric-row">
              <span class="status-metric-label">数据样本</span>
              <span class="status-metric-value">{{ sampleCount }}</span>
            </div>
          </div>
        </NSpin>
      </div>

      <!-- 右侧趋势图（真实接口 + 7/30 天切换） -->
      <TrendChart />
    </section>

    <StudioUsagePanel />

    <!-- 管理员全平台监控态势（仅管理员可见） -->
    <AdminStatsPanel v-if="authStore.isAdmin" />

    <!-- 最近任务 -->
    <section class="arco-card recent-tasks animate-fade-in-up delay-200">
      <div class="arco-card-header">
        <h3 class="arco-card-title">最近任务</h3>
        <NButton text size="small" class="view-all-btn" @click="router.push('/tasks')">
          查看全部 →
        </NButton>
      </div>
      <NSpin :show="loadingTasks" :aria-busy="loadingTasks">
        <NDataTable
          v-if="recentTasks.length > 0"
          :columns="columns"
          :data="recentTasks"
          :row-key="taskRowKey"
          :bordered="false"
          size="small"
          :single-line="false"
          :scroll-x="970"
          class="recent-table recent-table-surface"
        />
        <NEmpty v-else description="暂无任务">
          <template #extra>
            <div class="empty-extra">
              <p>点击上方按钮提交您的第一个分析任务</p>
              <NButton type="primary" @click="router.push('/flows')">
                <template #icon>
                  <NIcon><RocketOutline /></NIcon>
                </template>
                提交分析任务
              </NButton>
            </div>
          </template>
        </NEmpty>
      </NSpin>
    </section>

    <!-- 最近 BLAST 任务 -->
    <section class="arco-card recent-tasks animate-fade-in-up delay-300">
      <div class="arco-card-header">
        <h3 class="arco-card-title">最近 BLAST 任务</h3>
        <NButton text size="small" class="view-all-btn" @click="router.push('/tools/blast/tasks')">
          查看全部 →
        </NButton>
      </div>
      <NSpin :show="loadingBlastTasks" :aria-busy="loadingBlastTasks">
        <NDataTable
          v-if="blastTasks.length > 0"
          :columns="blastColumns"
          :data="blastTasks"
          :row-key="blastTaskRowKey"
          :bordered="false"
          size="small"
          :single-line="false"
          :scroll-x="1020"
          class="recent-table recent-table-surface"
        />
        <NEmpty v-else description="暂无 BLAST 任务">
          <template #extra>
            <div class="empty-extra">
              <p>点击上方按钮提交您的第一个 BLAST 查询</p>
              <NButton type="primary" @click="router.push('/tools/blast')">
                <template #icon>
                  <NIcon><SearchOutline /></NIcon>
                </template>
                提交 BLAST 查询
              </NButton>
            </div>
          </template>
        </NEmpty>
      </NSpin>
    </section>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 24px;
  min-height: 100%;
  background: var(--neutral-bg);
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  line-height: 32px;
  color: var(--neutral-text-1);
  margin: 0 0 24px;
}

/* 数据概览 */
.overview-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.status-card {
  display: flex;
  flex-direction: column;
}

:root[data-theme="dark"] .status-card {
  background: var(--surface-elevated);
  border-color: var(--border-default);
}

.status-main {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 24px;
}

.status-pulse {
  position: relative;
  display: inline-flex;
  width: 12px;
  height: 12px;
}

.status-pulse-dot {
  position: relative;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--status-color);
}

.status-pulse-dot::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--status-color);
  animation: pulse-ring 1.5s ease-out infinite;
  opacity: 0.6;
}

.status-pulse--healthy {
  --status-color: var(--arco-success);
}

.status-pulse--checking {
  --status-color: var(--arco-primary);
}

.status-pulse--checking .status-pulse-dot::before {
  animation-duration: 2.2s;
}

.status-pulse--error {
  --status-color: var(--arco-danger);
}

.status-pulse--error .status-pulse-dot::before {
  animation: none;
  opacity: 0.18;
  transform: scale(1.75);
}

@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 0.6; }
  100% { transform: scale(2.5); opacity: 0; }
}

.status-value {
  font-size: 32px;
  font-weight: 600;
  line-height: 40px;
  color: var(--neutral-text-1);
  font-variant-numeric: tabular-nums;
}

.status-divider {
  height: 1px;
  background: var(--neutral-border);
  margin-bottom: 16px;
}

.status-metrics {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-metric-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status-metric-label {
  font-size: 14px;
  color: var(--neutral-text-3);
}

.status-metric-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.view-all-btn {
  color: var(--arco-primary);
}

/* 最近任务 / 最近 BLAST 任务：与其他卡片保持统一的 24px 垂直间距 */
.recent-tasks {
  overflow: hidden;
  margin-bottom: 24px;
}

:root[data-theme="dark"] .recent-tasks {
  background: var(--surface-card);
  border-color: var(--border-subtle);
}

.recent-table :deep(th) {
  font-size: 12px;
  color: var(--neutral-text-3);
  font-weight: 500;
  background: transparent;
  border-bottom: 1px solid var(--neutral-border);
}

.recent-table :deep(td) {
  font-size: 13px;
  color: var(--neutral-text-1);
  border-bottom: 1px solid var(--neutral-border);
}

.recent-tasks:is(.is-selected, .card--selected, .card--active, .selected, .active, [aria-selected='true'], [aria-checked='true'], [data-selected='true']) {
  background-color: color-mix(in srgb, var(--arco-primary) 4%, var(--neutral-card));
  border-color: color-mix(in srgb, var(--arco-primary) 40%, var(--neutral-border));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--arco-primary) 40%, transparent);
}

.recent-table-surface :deep(th) {
  background: var(--neutral-bg);
}

.recent-table-surface :deep(.n-data-table-wrapper),
.recent-table-surface :deep(.n-data-table-base-table) {
  background: var(--neutral-card);
}

.recent-table-surface :deep(td) {
  background: var(--neutral-card);
}

.recent-table :deep(tr:hover td) {
  background: var(--neutral-hover);
}

.recent-table-surface :deep(.recent-task-progress) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  white-space: nowrap;
}

.recent-table-surface :deep(.recent-task-progress .n-progress) {
  flex: 1 1 auto;
  min-width: 60px;
}

.recent-table-surface :deep(.recent-task-progress__value) {
  flex: 0 0 44px;
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.empty-extra {
  text-align: center;
}
.empty-extra p {
  font-size: 13px;
  color: var(--neutral-text-3);
  margin: 0 0 12px;
}

/* 响应式 */
@media (max-width: 1024px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .dashboard-page {
    padding: 16px;
  }

  .banner-content {
    flex-wrap: wrap;
  }

  .banner-btn {
    margin-left: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .status-pulse-dot::before {
    animation: none;
    opacity: 0.18;
    transform: scale(1.5);
  }
}
</style>
