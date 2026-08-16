<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { NSpin, NEmpty, NIcon, NButton, NProgress } from 'naive-ui'
import { RefreshOutline, ServerOutline } from '@vicons/ionicons5'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import apiClient from '@/api/client'
import { useThemeStore } from '@/stores/theme'
import type { StorageUsage, UserStorageUsage } from '@/types/stats'
import { displayName } from '@/utils/displayName'

use([CanvasRenderer, PieChart, TooltipComponent, LegendComponent])

const loading = ref(false)
const data = ref<StorageUsage | null>(null)

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

// 生信目录可能很大，首次统计耗时；单独放宽超时避免前端误判接口超时
const REQUEST_TIMEOUT = 60000

async function fetchStorage() {
  loading.value = true
  try {
    const res = await apiClient.get<StorageUsage>('/admin/storage/usage', {
      params: { top_n: 5 },
      timeout: REQUEST_TIMEOUT,
    })
    data.value = res.data ?? null
  } catch {
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(fetchStorage)

function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const idx = Math.min(i, units.length - 1)
  const v = bytes / Math.pow(1024, idx)
  return `${v.toFixed(idx > 0 && v < 10 ? 2 : 1)} ${units[idx]}`
}

const globalUsage = computed(() => data.value?.global_usage ?? null)
const users = computed<UserStorageUsage[]>(() => data.value?.users ?? [])
// total===0 表示 data_root 不可读 / 不存在
const unavailable = computed(() => !globalUsage.value || globalUsage.value.total === 0)

// 用量越大颜色越警示：绿 → 橙 → 红
const usageColor = computed(() => {
  const p = globalUsage.value?.used_percent ?? 0
  if (p >= 90) return '#F53F3F'
  if (p >= 75) return '#FF7D00'
  return '#00B42A'
})

function rankClass(i: number): string {
  return i === 0 ? 'rank-1' : i === 1 ? 'rank-2' : i === 2 ? 'rank-3' : ''
}

const pieOption = computed(() => {
  void themeVersion.value
  const colorText2 = cssVar('--neutral-text-2', '#4e5969')
  const colorCard = cssVar('--neutral-card', '#ffffff')
  return {
  tooltip: {
    trigger: 'item',
    formatter: (p: { name: string; value: number; percent: number }) =>
      `${p.name}: ${formatBytes(p.value)} (${p.percent}%)`,
  },
  legend: {
    bottom: 0,
    textStyle: { color: colorText2, fontSize: 12 },
    itemWidth: 10,
    itemHeight: 10,
    type: 'scroll',
  },
  series: [
    {
      name: '用户存储占用',
      type: 'pie',
      radius: ['40%', '68%'],
      center: ['50%', '46%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: colorCard, borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
      data: users.value.map((u) => ({ name: displayName(u), value: u.size })),
    },
  ],
  }
})
</script>

<template>
  <div class="arco-card storage-card">
    <div class="arco-card-header">
      <span class="arco-card-title">
        <NIcon :size="16" class="storage-icon"><ServerOutline /></NIcon>
        存储空间监控
      </span>
      <div class="header-right">
        <span v-if="data" class="data-root" :title="data.data_root">{{ data.data_root }}</span>
        <NButton text size="small" class="refresh-btn" :loading="loading" @click="fetchStorage">
          <template #icon>
            <NIcon :size="16"><RefreshOutline /></NIcon>
          </template>
          刷新
        </NButton>
      </div>
    </div>

    <NSpin :show="loading">
      <!-- 全局容量 -->
      <div v-if="globalUsage && !unavailable" class="global-block">
        <div class="global-progress">
          <NProgress
            type="line"
            :percentage="Math.round(globalUsage.used_percent)"
            :height="14"
            :color="usageColor"
            rail-color="var(--neutral-border)"
            indicator-placement="inside"
            :show-indicator="true"
          />
        </div>
        <div class="global-stats">
          <div class="gstat">
            <span class="gstat-label">总容量</span>
            <span class="gstat-value">{{ formatBytes(globalUsage.total) }}</span>
          </div>
          <div class="gstat">
            <span class="gstat-label">已用</span>
            <span class="gstat-value used">{{ formatBytes(globalUsage.used) }}</span>
          </div>
          <div class="gstat">
            <span class="gstat-label">剩余</span>
            <span class="gstat-value free">{{ formatBytes(globalUsage.free) }}</span>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="unavailable">
        数据目录不可读或路径不存在，无法获取磁盘容量
      </div>

      <!-- Top 用户占用 -->
      <div class="users-block">
        <div class="users-title">
          用户空间占用 Top {{ users.length }}
          <span v-if="data && data.users_total > users.length" class="users-total">
            （共 {{ data.users_total }} 个用户目录）
          </span>
        </div>
        <div v-if="users.length > 0" class="users-grid">
          <div class="users-pie">
            <VChart :option="pieOption" autoresize style="width: 100%; height: 220px;" />
          </div>
          <div class="users-list">
            <div v-for="(u, i) in users" :key="u.user_id" class="user-row">
              <span class="user-rank" :class="rankClass(i)">{{ i + 1 }}</span>
              <span class="user-name" :title="displayName(u)">{{ displayName(u) }}</span>
              <span class="user-size">{{ formatBytes(u.size) }}</span>
              <span class="user-percent">{{ u.percent.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
        <NEmpty v-else description="暂无用户数据" style="padding: 24px 0;" />
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.storage-card {
  margin-bottom: 16px;
}

.storage-icon {
  color: #165dff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.data-root {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.refresh-btn {
  color: var(--arco-primary, #165dff) !important;
}

/* 全局容量 */
.global-block {
  margin-bottom: 20px;
}

.global-progress {
  margin-bottom: 14px;
}

.global-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.gstat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  background: var(--neutral-hover, #f7f8fa);
  border-radius: 8px;
}

.gstat-label {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}

.gstat-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
}

.gstat-value.used {
  color: #ff7d00;
}

.gstat-value.free {
  color: #00b42a;
}

.unavailable {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
  margin-bottom: 16px;
}

/* Top 用户 */
.users-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin-bottom: 12px;
}

.users-total {
  font-size: 12px;
  font-weight: 400;
  color: var(--neutral-text-3, #86909c);
}

.users-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: center;
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.user-row {
  display: grid;
  grid-template-columns: 24px 1fr auto auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.user-row:hover {
  background: var(--neutral-hover, #f7f8fa);
}

.user-rank {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--neutral-border, #e5e6eb);
  color: var(--neutral-text-3, #86909c);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.rank-1 {
  background: rgba(255, 125, 0, 0.15);
  color: #ff7d00;
}

.rank-2 {
  background: rgba(22, 93, 255, 0.12);
  color: #165dff;
}

.rank-3 {
  background: rgba(0, 180, 42, 0.12);
  color: #00b42a;
}

.user-name {
  font-size: 13px;
  color: var(--neutral-text-1, #1d2129);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-size {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
}

.user-percent {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  min-width: 48px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 768px) {
  .users-grid {
    grid-template-columns: 1fr;
  }

  .global-stats {
    grid-template-columns: 1fr;
  }
}
</style>
