<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, CustomChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import {
  NAlert, NButton, NCard, NDataTable, NIcon, NInput, NRadioButton, NRadioGroup, NSelect, NTag, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { CopyOutline, DownloadOutline, SparklesOutline } from '@vicons/ionicons5'
import { useThemeStore } from '@/stores/theme'
import {
  computeQpcr, formatNum, genSampleCtData, parseCtTable, toCsv, type QpcrDetailRow,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

use([CanvasRenderer, GridComponent, LegendComponent, TooltipComponent, BarChart, CustomChart])

const message = useMessage()
const { copy } = useWlcCopy()
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

const ctText = ref('')
const controlGroup = ref('')
const errorType = ref<'sd' | 'sem'>('sd')

const ctParsed = computed(() => parseCtTable(ctText.value))
const groupOptions = computed(() => ctParsed.value.groups.map((g) => ({ label: g, value: g })))
const activeControl = computed(() => {
  if (controlGroup.value && ctParsed.value.groups.includes(controlGroup.value)) return controlGroup.value
  return ctParsed.value.groups[0] ?? ''
})
const qpcrResult = computed(() => computeQpcr(ctParsed.value.rows, activeControl.value))

const qpcrColumns = computed<DataTableColumns<QpcrDetailRow>>(() => [
  { title: '样本', key: 'sample', sorter: (a, b) => a.sample.localeCompare(b.sample) },
  { title: '分组', key: 'group' },
  { title: '目的基因 Ct', key: 'targetCt', sorter: (a, b) => a.targetCt - b.targetCt },
  { title: '内参 Ct', key: 'refCt' },
  { title: 'ΔCt', key: 'dCt', sorter: (a, b) => a.dCt - b.dCt, render: (r) => r.dCt.toFixed(3) },
  { title: 'ΔΔCt', key: 'ddCt', sorter: (a, b) => a.ddCt - b.ddCt, render: (r) => r.ddCt.toFixed(3) },
  { title: '2^-ΔΔCt', key: 'relExp', sorter: (a, b) => a.relExp - b.relExp, render: (r) => r.relExp.toFixed(3) },
])

const chartOption = computed<EChartsCoreOption>(() => {
  const textColor = isDark.value ? '#c9cdd4' : '#4e5969'
  const axisColor = isDark.value ? '#3a3a3c' : '#e5e6eb'
  if (!('groupStats' in qpcrResult.value)) return {}
  const stats = qpcrResult.value.groupStats
  const names = stats.map((s) => s.group)
  const means = stats.map((s) => +s.mean.toFixed(3))
  return {
    grid: { top: 40, right: 24, bottom: 40, left: 64 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const arr = params as { dataIndex: number }[]
        const i = arr[0]?.dataIndex ?? 0
        const s = stats[i]
        return `${s.group}<br/>均值: ${s.mean.toFixed(3)}<br/>SD: ${s.sd.toFixed(3)}<br/>SEM: ${s.sem.toFixed(3)}<br/>n = ${s.n}`
      },
    },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: axisColor } },
    },
    yAxis: {
      type: 'value',
      name: '相对表达量',
      nameTextStyle: { color: textColor },
      axisLabel: { color: textColor },
      splitLine: { lineStyle: { color: axisColor } },
    },
    series: [
      {
        type: 'bar',
        data: means,
        barMaxWidth: 48,
        itemStyle: { color: '#165DFF', borderRadius: [4, 4, 0, 0] },
      },
      {
        type: 'custom',
        renderItem: (_params: unknown, api: {
          value: (i: number) => number
          coord: (v: [number, number]) => number[]
          size: (v: [number, number]) => number[]
        }) => {
          const x = api.coord([api.value(0), api.value(1)])[0]
          const yHigh = api.coord([0, api.value(1) + api.value(2)])[1]
          const yLow = api.coord([0, Math.max(api.value(1) - api.value(2), 0)])[1]
          const cap = 6
          const style = { stroke: isDark.value ? '#86909c' : '#4e5969', lineWidth: 1.5 }
          return {
            type: 'group',
            children: [
              { type: 'line', shape: { x1: x, y1: yHigh, x2: x, y2: yLow }, style },
              { type: 'line', shape: { x1: x - cap, y1: yHigh, x2: x + cap, y2: yHigh }, style },
              { type: 'line', shape: { x1: x - cap, y1: yLow, x2: x + cap, y2: yLow }, style },
            ],
          }
        },
        data: stats.map((s, i) => [i, +s.mean.toFixed(3), +(errorType.value === 'sd' ? s.sd : s.sem).toFixed(3)]),
        tooltip: { show: false },
        z: 10,
      },
    ],
  }
})

const chartRef = ref<InstanceType<typeof VChart> | null>(null)

function loadSample() {
  ctText.value = genSampleCtData()
  controlGroup.value = '对照组'
  message.info('已载入示例 Ct 数据（对照组 / 处理组，各 3 个样本）')
}

function exportChartPng() {
  if (!chartRef.value || !('groupStats' in qpcrResult.value)) {
    message.warning('暂无可导出的图表')
    return
  }
  try {
    const url = chartRef.value.getDataURL({
      type: 'png',
      pixelRatio: 3,
      backgroundColor: isDark.value ? '#1d1d1f' : '#ffffff',
    })
    const a = document.createElement('a')
    a.href = url
    a.download = `qpcr_relative_expression_${Date.now()}.png`
    a.click()
    message.success('已导出 PNG')
  } catch {
    message.error('导出失败')
  }
}

function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  message.success(`已导出 ${filename}`)
}

function exportQpcrCsv() {
  if (!('details' in qpcrResult.value)) {
    message.warning('暂无数据可导出')
    return
  }
  const rows = qpcrResult.value.details.map((d) => [
    d.sample, d.group, d.targetCt, d.refCt, d.dCt.toFixed(3), d.ddCt.toFixed(3), d.relExp.toFixed(3),
  ])
  downloadText(toCsv(['样本', '分组', '目的基因Ct', '内参Ct', 'ΔCt', 'ΔΔCt', '2^-ΔΔCt'], rows), 'qpcr_details.csv')
}

function buildSummary(): string {
  if (!('groupStats' in qpcrResult.value)) return ''
  const lines = qpcrResult.value.groupStats.map(
    (s) => `- ${s.group}：均值 ${formatNum(s.mean)}（SD ${formatNum(s.sd)}，n=${s.n}）`,
  )
  return ['【qPCR 相对表达 2^-ΔΔCt】对照组归一化为 1', ...lines].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">qPCR 相对表达 2^-ΔΔCt</div>
        <div class="wlc-desc">粘贴 Ct 数据（Tab 分隔：样本名 | 分组 | 目的基因Ct | 内参Ct），自动计算相对表达量并绘图。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid is-wide">
      <div class="wlc-form">
        <NInput v-model:value="ctText" type="textarea" :autosize="{ minRows: 8, maxRows: 14 }"
          placeholder="支持从 Excel 直接粘贴，如：&#10;Ctrl-1&#9;对照组&#9;22.35&#9;17.12&#10;Treat-1&#9;处理组&#9;19.82&#9;17.31" />
        <div class="wlc-stat-row">
          <NTag v-if="ctParsed.rows.length" size="small" type="success">{{ ctParsed.rows.length }} 行有效</NTag>
          <NTag v-if="ctParsed.skipped.length" size="small" type="warning">跳过 {{ ctParsed.skipped.length }} 行</NTag>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">对照组</span>
          <NSelect v-model:value="controlGroup" size="small" :options="groupOptions" placeholder="选择对照组" style="flex: 1" />
        </div>
        <div class="wlc-row">
          <span class="wlc-label">误差棒</span>
          <NRadioGroup v-model:value="errorType" size="small">
            <NRadioButton value="sd">SD</NRadioButton>
            <NRadioButton value="sem">SEM</NRadioButton>
          </NRadioGroup>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="'details' in qpcrResult">
          <div class="wlc-result-head">
            <div class="wlc-hero">相对表达量（对照组归一化为 1）</div>
            <div style="display: flex; gap: 6px">
              <NButton size="tiny" secondary @click="copy(buildSummary(), '统计摘要')">
                <template #icon><NIcon><CopyOutline /></NIcon></template>复制
              </NButton>
              <NButton size="tiny" secondary @click="exportChartPng">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>PNG
              </NButton>
              <NButton size="tiny" secondary @click="exportQpcrCsv">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>CSV
              </NButton>
            </div>
          </div>
          <VChart ref="chartRef" :option="chartOption" autoresize style="width: 100%; height: 300px" />
          <NDataTable size="small" :columns="qpcrColumns" :data="qpcrResult.details"
            :pagination="{ pageSize: 10 }" :scroll-x="640" class="wlc-table" />
        </template>
        <NAlert v-else-if="ctText.trim()" type="warning" :bordered="false">{{ qpcrResult.error }}</NAlert>
        <div v-else class="wlc-empty">粘贴 Ct 数据后自动计算 2^-ΔΔCt</div>
        <div class="wlc-formula">
          2^(-ΔΔCt) 法（Livak）：ΔCt = 目的基因Ct − 内参Ct；ΔΔCt = ΔCt(样本) − ΔCt(对照组均值)；
          相对表达量 = 2^(−ΔΔCt)，对照组归一化为 1。同组重复自动取均值，误差棒可选 SD / SEM。
        </div>
      </div>
    </div>
  </NCard>
</template>
