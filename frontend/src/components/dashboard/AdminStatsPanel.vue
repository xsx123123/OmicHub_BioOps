<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { NIcon, NEmpty, NSpin, NTag } from 'naive-ui'
import { AlertCircleOutline, PeopleOutline, FlashOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import apiClient from '@/api/client'
import StorageMonitorPanel from '@/components/dashboard/StorageMonitorPanel.vue'
import { useThemeStore } from '@/stores/theme'
import type {
  AdminStatus,
  AdminUserStats,
  FlowUsage,
  FailedTask,
} from '@/types/stats'

use([CanvasRenderer, PieChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const router = useRouter()

// ECharts 在 canvas 上绘制，无法解析 CSS var()（会得到黑色），
// 必须用 getComputedStyle 解析为具体色值；主题切换后重新解析。
const themeStore = useThemeStore()
const themeVersion = ref(0)
watch(() => themeStore.isDark, async () => {
  await nextTick()
  themeVersion.value++
})

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

const statusData = ref<AdminStatus>({})
const flowUsage = ref<FlowUsage[]>([])
const userStats = ref<AdminUserStats>({ total_users: 0, active_users_7d: 0 })
const failedTasks = ref<FailedTask[]>([])

const loadingStatus = ref(false)
const loadingFlows = ref(false)
const loadingUsers = ref(false)
const loadingFailed = ref(false)

const STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  queued: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#FF7D00',
  queued: '#FF9A2E',
  running: '#165DFF',
  success: '#00B42A',
  failed: '#F53F3F',
  cancelled: '#86909C',
}

const pieOption = computed(() => {
  void themeVersion.value
  const colorText2 = cssVar('--neutral-text-2', '#4e5969')
  const colorCard = cssVar('--neutral-card', '#ffffff')
  return {
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, textStyle: { color: colorText2, fontSize: 12 }, itemWidth: 10, itemHeight: 10 },
  series: [
    {
      name: '任务状态',
      type: 'pie',
      radius: ['40%', '68%'],
      center: ['50%', '46%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: colorCard, borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
      data: Object.entries(statusData.value).map(([k, v]) => ({
        name: STATUS_LABELS[k] ?? k,
        value: v,
        itemStyle: { color: STATUS_COLORS[k] },
      })),
    },
  ],
  }
})

const flowOption = computed(() => {
  void themeVersion.value
  const colorText2 = cssVar('--neutral-text-2', '#4e5969')
  const colorText3 = cssVar('--neutral-text-3', '#86909c')
  const colorBorder = cssVar('--neutral-border', '#e5e6eb')
  const colorPrimary = cssVar('--arco-primary', '#165dff')
  return {
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 12, right: 24, top: 16, bottom: 8, containLabel: true },
  xAxis: {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: colorBorder, type: 'dashed' } },
    axisLabel: { color: colorText3, fontSize: 12 },
  },
  yAxis: {
    type: 'category',
    data: flowUsage.value.map((f) => f.name).reverse(),
    axisLine: { lineStyle: { color: colorBorder } },
    axisTick: { show: false },
    axisLabel: { color: colorText2, fontSize: 12 },
  },
  series: [
    {
      type: 'bar',
      data: flowUsage.value.map((f) => f.count).reverse(),
      barMaxWidth: 18,
      itemStyle: {
        color: colorPrimary,
        borderRadius: [0, 4, 4, 0],
      },
    },
  ],
  }
})

const totalTasks = computed(() =>
  Object.values(statusData.value).reduce((a, b) => a + b, 0),
)

function statusTagType(s: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  return ({
    success: 'success',
    failed: 'error',
    running: 'info',
    queued: 'warning',
    pending: 'warning',
    cancelled: 'default',
  } as const)[s] ?? 'default'
}

function formatTime(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function fetchStatus() {
  loadingStatus.value = true
  try {
    const res = await apiClient.get<AdminStatus>('/admin/stats/status')
    statusData.value = res.data ?? {}
  } catch {
    statusData.value = {}
  } finally {
    loadingStatus.value = false
  }
}

async function fetchFlows() {
  loadingFlows.value = true
  try {
    const res = await apiClient.get<FlowUsage[]>('/admin/stats/flows')
    flowUsage.value = res.data ?? []
  } catch {
    flowUsage.value = []
  } finally {
    loadingFlows.value = false
  }
}

async function fetchUsers() {
  loadingUsers.value = true
  try {
    const res = await apiClient.get<AdminUserStats>('/admin/stats/users')
    userStats.value = res.data ?? { total_users: 0, active_users_7d: 0 }
  } catch {
    userStats.value = { total_users: 0, active_users_7d: 0 }
  } finally {
    loadingUsers.value = false
  }
}

async function fetchFailed() {
  loadingFailed.value = true
  try {
    const res = await apiClient.get<FailedTask[]>('/admin/stats/recent-failed', {
      params: { limit: 10 },
    })
    failedTasks.value = res.data ?? []
  } catch {
    failedTasks.value = []
  } finally {
    loadingFailed.value = false
  }
}

onMounted(() => {
  void fetchStatus()
  void fetchFlows()
  void fetchUsers()
  void fetchFailed()
})
</script>

<template>
  <section class="admin-panel">
    <div class="panel-header">
      <h2 class="section-title">全平台全局监控态势看板</h2>
      <NTag type="warning" size="small" round>管理员</NTag>
    </div>

    <!-- 指标卡片：用户与活跃度 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-icon stat-icon--blue"><NIcon :size="20"><PeopleOutline /></NIcon></div>
        <NSpin :show="loadingUsers">
          <div class="stat-body">
            <span class="stat-value">{{ userStats.total_users }}</span>
            <span class="stat-label">注册用户总数</span>
          </div>
        </NSpin>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--green"><NIcon :size="20"><FlashOutline /></NIcon></div>
        <NSpin :show="loadingUsers">
          <div class="stat-body">
            <span class="stat-value">{{ userStats.active_users_7d }}</span>
            <span class="stat-label">近 7 天活跃用户</span>
          </div>
        </NSpin>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--purple"><NIcon :size="20"><AlertCircleOutline /></NIcon></div>
        <NSpin :show="loadingStatus">
          <div class="stat-body">
            <span class="stat-value">{{ totalTasks }}</span>
            <span class="stat-label">全平台任务总数</span>
          </div>
        </NSpin>
      </div>
    </div>

    <!-- 存储空间监控（全局容量 + Top 用户占用） -->
    <StorageMonitorPanel />

    <!-- 图表区 -->
    <div class="charts-grid">
      <div class="arco-card chart-card">
        <div class="arco-card-header"><span class="arco-card-title">任务状态分布</span></div>
        <NSpin :show="loadingStatus">
          <VChart :option="pieOption" autoresize style="width: 100%; height: 260px;" />
        </NSpin>
      </div>
      <div class="arco-card chart-card">
        <div class="arco-card-header"><span class="arco-card-title">流程使用占比</span></div>
        <NSpin :show="loadingFlows">
          <VChart
            v-if="flowUsage.length > 0"
            :option="flowOption"
            autoresize
            style="width: 100%; height: 260px;"
          />
          <NEmpty v-else description="暂无流程调用记录" style="padding: 60px 0;" />
        </NSpin>
      </div>
    </div>

    <!-- 近期失败任务监控 -->
    <div class="arco-card failed-card">
      <div class="arco-card-header">
        <span class="arco-card-title">
          <NIcon :size="16" class="alert-icon"><AlertCircleOutline /></NIcon>
          近期失败任务监控
        </span>
      </div>
      <NSpin :show="loadingFailed">
        <div v-if="failedTasks.length > 0" class="failed-list">
          <div
            v-for="task in failedTasks"
            :key="task.id"
            class="failed-item"
            @click="router.push(`/tasks/${task.id}`)"
          >
            <div class="failed-main">
              <span class="failed-name">{{ task.name || '(未命名任务)' }}</span>
              <NTag size="tiny" :type="statusTagType('failed')" round>失败</NTag>
            </div>
            <div class="failed-meta">
              <span class="failed-flow">{{ task.flow_id }}</span>
              <span class="failed-error" :title="task.error_message">
                {{ task.error_message || '无错误信息' }}
              </span>
              <span class="failed-time">{{ formatTime(task.created_at) }}</span>
            </div>
          </div>
        </div>
        <NEmpty v-else description="近期无失败任务，系统运行良好" style="padding: 32px 0;" />
      </NSpin>
    </div>
  </section>
</template>

<style scoped>
.admin-panel {
  margin-top: 8px;
  margin-bottom: 24px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 16px 20px;
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon--blue { background: color-mix(in srgb, var(--arco-primary) 10%, transparent); color: var(--arco-primary); }
.stat-icon--green { background: color-mix(in srgb, var(--arco-success) 10%, transparent); color: var(--arco-success); }
.stat-icon--purple { background: color-mix(in srgb, var(--kimi-chart-4) 10%, transparent); color: var(--kimi-chart-4); }

.stat-body {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  line-height: 32px;
  color: var(--neutral-text-1);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 12px;
  color: var(--neutral-text-3);
}

.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.arco-card {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 16px 20px;
}

.arco-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.arco-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--neutral-text-1);
  display: flex;
  align-items: center;
  gap: 6px;
}

.alert-icon {
  color: var(--arco-danger);
}

.failed-list {
  display: flex;
  flex-direction: column;
}

.failed-item {
  padding: 12px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--neutral-border) 50%, transparent);
  cursor: pointer;
  transition: background 0.2s ease;
}

.failed-item:last-child {
  border-bottom: none;
}

.failed-item:hover {
  background: var(--neutral-hover);
  margin: 0 -20px;
  padding: 12px 20px;
}

.failed-main {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.failed-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.failed-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--neutral-text-3);
}

.failed-flow {
  color: var(--arco-primary);
}

.failed-error {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.failed-time {
  flex-shrink: 0;
}

@media (max-width: 1024px) {
  .stat-cards {
    grid-template-columns: 1fr;
  }
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
