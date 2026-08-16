<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import {
  NCard,
  NGrid,
  NGi,
  NStatistic,
  NSelect,
  NButton,
  NIcon,
  NSpin,
  NEmpty,
  NDataTable,
  NTag,
  NSpace,
  NTooltip,
} from 'naive-ui'
import { RefreshOutline, AlertCircleOutline, PulseOutline } from '@vicons/ionicons5'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import PageHeader from '@/components/PageHeader.vue'
import { useThemeStore } from '@/stores/theme'
import {
  adminAiMetricsApi,
  type AiTrendResponse,
  type AiModelMetric,
  type AiAlertStatus,
  type AiAlertHistoryItem,
} from '@/api/admin/aiMetrics'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

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

const days = ref(14)
const daysOptions = [
  { label: '近 7 天', value: 7 },
  { label: '近 14 天', value: 14 },
  { label: '近 30 天', value: 30 },
]
const modelFilter = ref<string | null>(null)
const tokenUnit = ref<'K' | 'M'>('K')

const loading = ref(false)
const trend = ref<AiTrendResponse | null>(null)
const models = ref<AiModelMetric[]>([])
const alertStatus = ref<AiAlertStatus | null>(null)
const alertHistory = ref<AiAlertHistoryItem[]>([])

const modelOptions = computed(() =>
  models.value.map((m) => ({ label: `${m.model}（${m.provider}）`, value: m.model })),
)

async function fetchAll() {
  loading.value = true
  try {
    const [t, m, a, h] = await Promise.all([
      adminAiMetricsApi.getTrend({ days: days.value, model: modelFilter.value || undefined }),
      adminAiMetricsApi.getModels({ days: days.value }),
      adminAiMetricsApi.getAlertStatus(),
      adminAiMetricsApi.getAlertHistory({ limit: 20 }),
    ])
    trend.value = t
    models.value = m
    alertStatus.value = a
    alertHistory.value = h
  } finally {
    loading.value = false
  }
}

watch([days, modelFilter], () => fetchAll())
onMounted(() => fetchAll())

const dates = computed(() => (trend.value?.daily ?? []).map((d) => d.date.slice(5)))

const tokenOption = computed(() => {
  void themeVersion.value
  const text3 = cssVar('--neutral-text-3', '#86909c')
  const border = cssVar('--neutral-border', '#e5e6eb')
  const daily = trend.value?.daily ?? []
  const divisor = tokenUnit.value === 'M' ? 1_000_000 : 1_000
  const tokenData = daily.map((d) => d.total_tokens / divisor)
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, textStyle: { color: text3, fontSize: 12 }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 12, right: 24, top: 16, bottom: 32, containLabel: true },
    xAxis: {
      type: 'category',
      data: dates.value,
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: text3, fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        name: `${tokenUnit.value} tokens`,
        axisLabel: { color: text3, formatter: (value: number) => `${value} ${tokenUnit.value}` },
        splitLine: { lineStyle: { color: border, type: 'dashed' } },
      },
      { type: 'value', name: '🥫', axisLabel: { color: text3 }, splitLine: { show: false } },
    ],
    series: [
      { name: `总 tokens（${tokenUnit.value}）`, type: 'bar', data: tokenData, itemStyle: { color: '#165DFF', borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22 },
      { name: '成本(🥫)', type: 'line', yAxisIndex: 1, smooth: true, data: daily.map((d) => d.cost_cookie), itemStyle: { color: '#FF7D00' } },
    ],
  }
})

const errorOption = computed(() => {
  void themeVersion.value
  const text3 = cssVar('--neutral-text-3', '#86909c')
  const border = cssVar('--neutral-border', '#e5e6eb')
  const daily = trend.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${(v * 100).toFixed(1)}%` },
    grid: { left: 12, right: 24, top: 16, bottom: 24, containLabel: true },
    xAxis: { type: 'category', data: dates.value, axisLine: { lineStyle: { color: border } }, axisLabel: { color: text3, fontSize: 11 } },
    yAxis: { type: 'value', axisLabel: { color: text3, formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: border, type: 'dashed' } } },
    series: [
      { name: '错误率', type: 'line', smooth: true, data: daily.map((d) => d.error_rate), areaStyle: { opacity: 0.12 }, itemStyle: { color: '#F53F3F' } },
    ],
  }
})

const latencyOption = computed(() => {
  void themeVersion.value
  const text3 = cssVar('--neutral-text-3', '#86909c')
  const border = cssVar('--neutral-border', '#e5e6eb')
  const daily = trend.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${Math.round(v)} ms` },
    legend: { bottom: 0, textStyle: { color: text3, fontSize: 12 }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 12, right: 24, top: 16, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: dates.value, axisLine: { lineStyle: { color: border } }, axisLabel: { color: text3, fontSize: 11 } },
    yAxis: { type: 'value', name: 'ms', axisLabel: { color: text3 }, splitLine: { lineStyle: { color: border, type: 'dashed' } } },
    series: [
      { name: '平均', type: 'line', smooth: true, data: daily.map((d) => d.avg_duration_ms), itemStyle: { color: '#00B42A' } },
      { name: 'p95', type: 'line', smooth: true, data: daily.map((d) => d.p95_duration_ms), itemStyle: { color: '#722ED1' } },
    ],
  }
})

const modelColumns = [
  { title: '模型', key: 'model', ellipsis: { tooltip: true } },
  { title: 'Provider', key: 'provider' },
  { title: '调用', key: 'calls', sorter: (a: AiModelMetric, b: AiModelMetric) => a.calls - b.calls },
  {
    title: '错误率',
    key: 'error_rate',
    sorter: (a: AiModelMetric, b: AiModelMetric) => a.error_rate - b.error_rate,
    render: (r: AiModelMetric) => `${(r.error_rate * 100).toFixed(1)}%`,
  },
  { title: '总 tokens', key: 'total_tokens', sorter: (a: AiModelMetric, b: AiModelMetric) => a.total_tokens - b.total_tokens },
  { title: '成本(🥫)', key: 'cost_cookie' },
  { title: '平均耗时(ms)', key: 'avg_duration_ms' },
]

const historyColumns = [
  {
    title: '级别',
    key: 'level',
    width: 80,
    render: (r: AiAlertHistoryItem) => r.level,
  },
  { title: '规则', key: 'rule', width: 120 },
  { title: '内容', key: 'message', ellipsis: { tooltip: true } },
  { title: '时间', key: 'created_at', width: 180, render: (r: AiAlertHistoryItem) => fmtTime(r.created_at) },
]

function fmtTime(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

function ruleTagType(breaching: boolean): 'error' | 'success' {
  return breaching ? 'error' : 'success'
}

const summary = computed(() => trend.value?.summary ?? { calls: 0, errors: 0, error_rate: 0, total_tokens: 0, cost_cookie: 0 })
</script>

<template>
  <div class="ai-metrics">
    <PageHeader
      title="AI 指标仪表盘"
      subtitle="AI 助手 / Agent / AI 工作台调用的 token、成本、延迟、错误率趋势与阈值告警"
    />

    <NCard size="small" class="toolbar">
      <NSpace align="center" :wrap="false">
        <NSelect v-model:value="days" :options="daysOptions" style="width: 130px" />
        <NSelect
          v-model:value="modelFilter"
          :options="modelOptions"
          placeholder="全部模型"
          clearable
          filterable
          style="width: 260px"
        />
        <NButton :loading="loading" @click="fetchAll">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新
        </NButton>
      </NSpace>
    </NCard>

    <NSpin :show="loading">
      <NGrid :x-gap="12" :y-gap="12" :cols="4" responsive="screen" item-responsive class="stat-grid">
        <NGi span="4 m:1">
          <NCard size="small"><NStatistic label="调用次数" :value="summary.calls" /></NCard>
        </NGi>
        <NGi span="4 m:1">
          <NCard size="small">
            <NStatistic label="错误率">
              <template #default>
                <span :style="{ color: summary.error_rate > 0.05 ? '#F53F3F' : undefined }">
                  {{ (summary.error_rate * 100).toFixed(1) }}%
                </span>
              </template>
            </NStatistic>
          </NCard>
        </NGi>
        <NGi span="4 m:1">
          <NCard size="small"><NStatistic label="总 tokens" :value="summary.total_tokens" /></NCard>
        </NGi>
        <NGi span="4 m:1">
          <NCard size="small"><NStatistic label="成本（🥫）" :value="summary.cost_cookie" /></NCard>
        </NGi>
      </NGrid>

      <NCard size="small" title="告警状态（C4）" class="section">
        <template #header-extra>
          <NTag v-if="alertStatus && !alertStatus.enabled" size="small" type="warning">告警已禁用</NTag>
        </template>
        <NSpace v-if="alertStatus" :wrap="true">
          <NTooltip v-for="rule in alertStatus.rules" :key="rule.rule">
            <template #trigger>
              <NTag :type="ruleTagType(rule.breaching)" :bordered="false" round size="large">
                <template #icon><NIcon :component="rule.breaching ? AlertCircleOutline : PulseOutline" /></template>
                {{ rule.label }} · {{ rule.display }}
              </NTag>
            </template>
            当前值 {{ rule.display }}，阈值 {{ rule.threshold }}
          </NTooltip>
        </NSpace>
        <NEmpty v-else description="暂无告警规则状态" />
      </NCard>

      <NGrid :x-gap="12" :y-gap="12" :cols="2" responsive="screen" item-responsive class="section">
        <NGi span="2 m:1">
          <NCard size="small" title="Token 用量与成本趋势">
            <template #header-extra>
              <div class="omichub-segmented-toggle" role="group" aria-label="Token 图表单位切换">
                <button
                  type="button"
                  :class="{ active: tokenUnit === 'K' }"
                  :aria-pressed="tokenUnit === 'K'"
                  @click="tokenUnit = 'K'"
                >
                  K
                </button>
                <button
                  type="button"
                  :class="{ active: tokenUnit === 'M' }"
                  :aria-pressed="tokenUnit === 'M'"
                  @click="tokenUnit = 'M'"
                >
                  M
                </button>
              </div>
            </template>
            <VChart v-if="trend && trend.daily.length" :option="tokenOption" autoresize style="width: 100%; height: 280px" />
            <NEmpty v-else description="暂无数据" />
          </NCard>
        </NGi>
        <NGi span="2 m:1">
          <NCard size="small" title="错误率趋势">
            <VChart v-if="trend && trend.daily.length" :option="errorOption" autoresize style="width: 100%; height: 280px" />
            <NEmpty v-else description="暂无数据" />
          </NCard>
        </NGi>
        <NGi span="2">
          <NCard size="small" title="延迟趋势（平均 / p95）">
            <VChart v-if="trend && trend.daily.length" :option="latencyOption" autoresize style="width: 100%; height: 280px" />
            <NEmpty v-else description="暂无数据" />
          </NCard>
        </NGi>
      </NGrid>

      <NCard size="small" title="按模型聚合" class="section">
        <NDataTable :columns="modelColumns" :data="models" :bordered="false" size="small" :row-key="(r: AiModelMetric) => r.model" />
      </NCard>

      <NCard size="small" title="告警历史" class="section">
        <NDataTable
          :columns="historyColumns"
          :data="alertHistory"
          :bordered="false"
          size="small"
          :row-key="(r: AiAlertHistoryItem) => r.id"
        />
        <NEmpty v-if="!alertHistory.length" description="尚未触发过告警" style="margin-top: 12px" />
      </NCard>
    </NSpin>
  </div>
</template>

<style scoped>
.ai-metrics {
  padding: 16px;
}
.toolbar {
  margin-bottom: 12px;
}
.stat-grid {
  margin-bottom: 12px;
}
.section {
  margin-top: 12px;
}
</style>
