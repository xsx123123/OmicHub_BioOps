<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { NButton, NIcon, NSpin } from 'naive-ui'
import { CalendarOutline, StatsChartOutline } from '@vicons/ionicons5'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DatasetComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import apiClient from '@/api/client'
import EmptyState from '@/components/EmptyState.vue'
import { useThemeStore } from '@/stores/theme'
import type { TrendPoint } from '@/types/stats'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DatasetComponent,
])

const selectedDays = ref<number>(7)
const chartMode = ref<'bar' | 'area'>('bar')
const trendData = ref<TrendPoint[]>([])
const loading = ref(false)

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

const trendOption = computed(() => {
  void themeVersion.value // 主题切换时触发重算
  const colorCard = cssVar('--neutral-card', '#ffffff')
  const colorBorder = cssVar('--neutral-border', '#e5e6eb')
  const colorText1 = cssVar('--neutral-text-1', '#1d2129')
  const colorText2 = cssVar('--neutral-text-2', '#4e5969')
  const colorText3 = cssVar('--neutral-text-3', '#86909c')
  const colorPrimary = cssVar('--arco-primary', '#165dff')
  const colorWarning = cssVar('--arco-warning', '#ff7d00')
  const isAreaChart = chartMode.value === 'area'
  return {
  tooltip: {
    trigger: 'axis',
    backgroundColor: colorCard,
    borderColor: colorBorder,
    borderWidth: 1,
    textStyle: { color: colorText1, fontSize: 12 },
    extraCssText: 'box-shadow: 0 4px 20px rgba(0,0,0,0.08); border-radius: 8px;',
  },
  legend: {
    data: ['分析任务数', '样本数量'],
    bottom: 0,
    textStyle: { color: colorText2, fontSize: 12 },
    itemWidth: 10,
    itemHeight: 10,
  },
  grid: { left: 12, right: 12, top: 24, bottom: 32, containLabel: true },
  xAxis: {
    type: 'category',
    data: trendData.value.map((d) => d.date),
    axisLine: { lineStyle: { color: colorBorder } },
    axisTick: { show: false },
    axisLabel: { color: colorText3, fontSize: 12 },
  },
  yAxis: [
    {
      type: 'value',
      name: '任务数',
      nameTextStyle: { color: colorText3, fontSize: 11, align: 'left', padding: [0, 0, 0, -20] },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: colorBorder, type: 'dashed' } },
      axisLabel: { color: colorText3, fontSize: 12 },
    },
    {
      type: 'value',
      name: '样本数',
      nameTextStyle: { color: colorText3, fontSize: 11, align: 'right', padding: [0, -20, 0, 0] },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: colorText3, fontSize: 12 },
    },
  ],
  series: [
    {
      name: '分析任务数',
      type: isAreaChart ? 'line' : 'bar',
      data: trendData.value.map((d) => d.tasks),
      itemStyle: { color: colorPrimary, borderRadius: [4, 4, 0, 0] },
      lineStyle: isAreaChart ? { color: colorPrimary, width: 2 } : undefined,
      areaStyle: isAreaChart ? { color: colorPrimary, opacity: 0.16 } : undefined,
      symbol: isAreaChart ? 'circle' : undefined,
      symbolSize: isAreaChart ? 6 : undefined,
      smooth: isAreaChart,
      barMaxWidth: isAreaChart ? undefined : 32,
    },
    {
      name: '样本数量',
      type: 'line',
      yAxisIndex: 1,
      data: trendData.value.map((d) => d.samples),
      itemStyle: { color: colorWarning },
      lineStyle: { color: colorWarning, width: 2 },
      symbol: 'circle',
      symbolSize: 6,
      smooth: true,
      areaStyle: isAreaChart ? { color: colorWarning, opacity: 0.12 } : undefined,
    },
  ],
  }
})

async function fetchTrend() {
  loading.value = true
  try {
    const res = await apiClient.get<TrendPoint[]>('/stats/trend', {
      params: { days: selectedDays.value },
    })
    trendData.value = res.data ?? []
  } catch {
    trendData.value = []
  } finally {
    loading.value = false
  }
}

function toggleDays(days: number) {
  if (selectedDays.value === days) return
  selectedDays.value = days
}

function toggleChartMode(mode: 'bar' | 'area') {
  chartMode.value = mode
}

watch(selectedDays, fetchTrend)
onMounted(fetchTrend)
</script>

<template>
  <div class="arco-card trend-card">
    <div class="arco-card-header">
      <span class="arco-card-title">任务提交趋势</span>
      <div class="trend-controls">
        <div class="cygnusx-segmented-toggle chart-toggle" role="group" aria-label="趋势图形态切换">
          <button
            type="button"
            :class="{ active: chartMode === 'bar' }"
            :aria-pressed="chartMode === 'bar'"
            @click="toggleChartMode('bar')"
          >
            柱状
          </button>
          <button
            type="button"
            :class="{ active: chartMode === 'area' }"
            :aria-pressed="chartMode === 'area'"
            @click="toggleChartMode('area')"
          >
            面积
          </button>
        </div>
        <div class="days-toggle">
          <NButton
            size="small"
            :type="selectedDays === 7 ? 'primary' : 'default'"
            ghost
            @click="toggleDays(7)"
          >
            近 7 天
          </NButton>
          <NButton
            size="small"
            :type="selectedDays === 30 ? 'primary' : 'default'"
            ghost
            @click="toggleDays(30)"
          >
            近 30 天
          </NButton>
          <NIcon :size="14" class="cal-icon"><CalendarOutline /></NIcon>
        </div>
      </div>
    </div>
    <div class="trend-chart-wrap">
      <NSpin :show="loading">
        <VChart
          v-if="trendData.length"
          :option="trendOption"
          autoresize
          style="width: 100%; height: 260px;"
        />
        <EmptyState
          v-else-if="!loading"
          :icon="StatsChartOutline"
          title="暂无趋势数据"
          description="提交分析任务后，这里会展示近期的任务与样本变化。"
        />
      </NSpin>
    </div>
  </div>
</template>

<style scoped>
.arco-card {
  background: var(--neutral-card);
  border: none;
  border-radius: var(--radius-card);
  padding: 16px 20px;
  box-shadow: var(--shadow-card);
  min-width: 0;
}

.arco-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

:root[data-theme="dark"] .trend-card .arco-card-header {
  margin: -16px -20px 12px;
  padding: 12px 20px;
  background: var(--surface-elevated);
  border-bottom: 1px solid var(--border-subtle);
  border-radius: var(--radius-card) var(--radius-card) 0 0;
}

.arco-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.days-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
}

.trend-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cal-icon {
  color: var(--neutral-text-3);
  margin-left: 2px;
}

.trend-chart-wrap {
  width: 100%;
}

@media (max-width: 640px) {
  .arco-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .trend-controls {
    width: 100%;
    justify-content: space-between;
  }
}

</style>
