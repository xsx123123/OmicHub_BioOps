<script setup lang="ts">
import { computed, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import {
  NButton, NButtonGroup, NCollapse, NCollapseItem, NColorPicker, NDataTable, NDivider,
  NEmpty, NIcon, NInputNumber, NRadioButton, NRadioGroup, NSelect, NSlider, NSpin,
  NSwitch, NTag, NStatistic, NUpload,
  type DataTableColumns, type UploadFileInfo,
} from 'naive-ui'
import { ArrowBackOutline, BarChartOutline, DownloadOutline, SparklesOutline } from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import { useThemeStore } from '@/stores/theme'
import PageHeader from '@/components/PageHeader.vue'
import type {
  ManhattanConfig, ColMap, ManhattanRow, ProcessedResult,
} from '@/utils/manhattanProcessor'
import {
  DEFAULT_CONFIG,
  autoDetectColumns,
  parseDelimited,
  validateData,
  processManhattanData,
  buildPlotlyFigure,
  buildChrDistributionFigure,
  genSampleData,
  getChromosomeOrder,
} from '@/utils/manhattanProcessor'

const router = useRouter()
const message = useMessage()
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

// === 状态 ===
const config = ref<ManhattanConfig>({ ...DEFAULT_CONFIG })
const colMap = ref<Partial<ColMap>>({})
const headers = ref<string[]>([])
const rawRows = ref<Record<string, string>[]>([])
const processed = ref<ProcessedResult | null>(null)
const stats = computed(() => processed.value?.stats || null)
const plotting = ref(false)
const selectedSnpIds = ref<Set<string>>(new Set())
const hoveredSnpId = ref<string | null>(null)
const tableMode = ref<'all' | 'selected'>('all')

const yAxisMaxMode = ref<'auto' | 'manual'>('auto')
const manualYMax = ref(15)
const exportDpi = ref(1000)

const PLOT_DIV_ID = 'manhattan-plot-container'
const CHR_DIST_ID = 'manhattan-chr-dist'

// === 选项 ===
const headerOptions = computed(() => headers.value.map((h) => ({ label: h, value: h })))
const colorSchemeOptions = [
  { label: '经典', value: 'classic' },
  { label: '柔和', value: 'pastel' },
  { label: '灰度', value: 'grayscale' },
]

// === 表格 ===
const tableColumns = computed<DataTableColumns<ManhattanRow>>(() => [
  { type: 'selection', multiple: false },
  { title: 'SNP', key: 'snpId', width: 120, sorter: 'default', fixed: 'left' },
  {
    title: 'Chr',
    key: 'chromosome',
    width: 60,
    sorter: (a, b) => (Number.isNaN(Number(a.chromosome)) ? 1 : 0) - (Number.isNaN(Number(b.chromosome)) ? 1 : 0) || Number(a.chromosome) - Number(b.chromosome),
  },
  { title: 'Position', key: 'position', width: 110, sorter: 'default', render: (row) => row.position.toLocaleString() },
  { title: 'P-value', key: 'pvalue', width: 100, sorter: 'default', render: (row) => row.pvalue.toExponential(2) },
  { title: '-log₁₀(P)', key: 'negLogP', width: 90, sorter: 'default', render: (row) => row.negLogP.toFixed(2) },
  { title: 'Gene', key: 'gene', width: 100, render: (row) => row.gene || '-' },
  {
    title: 'Status',
    key: 'status',
    width: 100,
    render: (row) => {
      if (row.isSignificant) return h(NTag, { size: 'tiny', type: 'error' }, () => 'Genome-wide')
      if (row.isSuggestive) return h(NTag, { size: 'tiny', type: 'warning' }, () => 'Suggestive')
      return h(NTag, { size: 'tiny' }, () => 'NS')
    },
  },
])

const filteredTableData = computed(() => {
  const rows = processed.value?.rows || []
  if (tableMode.value === 'selected' && selectedSnpIds.value.size > 0) {
    return rows.filter((r) => selectedSnpIds.value.has(r.snpId))
  }
  return rows
})

function getRowClassName(row: ManhattanRow) {
  if (selectedSnpIds.value.has(row.snpId)) return 'row-selected'
  if (hoveredSnpId.value === row.snpId) return 'row-hovered'
  return ''
}

function onTableRowClick(row: ManhattanRow) {
  selectedSnpIds.value = new Set([row.snpId])
  renderPlot()
  nextTick(() => scrollTableToRow(row.snpId))
}

function onTableRowDblClick(row: ManhattanRow) {
  zoomToChromosome(row.chromosome)
}

let hoverResetTimer: ReturnType<typeof setTimeout> | null = null

function scrollTableToRow(snpId: string) {
  // naive-ui data-table 没有公开滚动到行 API，这里仅做状态标记
  hoveredSnpId.value = snpId
  if (hoverResetTimer) clearTimeout(hoverResetTimer)
  hoverResetTimer = setTimeout(() => {
    if (hoveredSnpId.value === snpId) hoveredSnpId.value = null
  }, 1200)
}

function onTableSelectionChange(keys: (string | number)[]) {
  selectedSnpIds.value = new Set(keys as string[])
  renderPlot()
}

function showAllData() { tableMode.value = 'all' }
function showSelectedOnly() { tableMode.value = 'selected' }

// === Plotly ===
async function renderPlot() {
  if (!processed.value) return
  plotting.value = true
  try {
    const container = document.getElementById(PLOT_DIV_ID)
    if (!container) return

    const yMax = yAxisMaxMode.value === 'manual' ? manualYMax.value : ('auto' as const)
    const currentConfig: ManhattanConfig = { ...config.value, yAxisMax: yMax }

    const figure = buildPlotlyFigure(
      processed.value,
      currentConfig,
      isDark.value,
      selectedSnpIds.value,
      hoveredSnpId.value,
    )

    await Plotly.react(container, figure.data, figure.layout, figure.config)

    if (!container.hasAttribute('data-events-bound')) {
      bindPlotEvents(container)
      container.setAttribute('data-events-bound', 'true')
    }

    renderChrDist()
  } finally {
    plotting.value = false
  }
}

function bindPlotEvents(container: any) {
  container.on('plotly_selected' as any, (event: any) => {
    const pointIds = event.points?.map((p: any) => p.customdata?.[0]) ?? []
    selectedSnpIds.value = new Set(pointIds)
  })

  container.on('plotly_click' as any, (event: any) => {
    const snpId = event.points?.[0]?.customdata?.[0]
    if (snpId) selectedSnpIds.value = new Set([snpId])
  })

  container.on('plotly_hover' as any, (event: any) => {
    hoveredSnpId.value = event.points?.[0]?.customdata?.[0] || null
  })
  container.on('plotly_unhover' as any, () => {
    hoveredSnpId.value = null
  })

  container.on('plotly_doubleclick' as any, () => {
    selectedSnpIds.value = new Set()
  })
}

function renderChrDist() {
  if (!processed.value) return
  const container = document.getElementById(CHR_DIST_ID)
  if (!container) return
  const figure = buildChrDistributionFigure(
    processed.value.stats.chrDistribution,
    processed.value.chromosomeOrder,
    isDark.value,
  )
  Plotly.react(container, figure.data, figure.layout, figure.config)
}

function zoomToChromosome(chromosome: string) {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container || !processed.value) return

  const { chrBoundaries } = (() => {
    // 复用 processor 内部函数太麻烦，直接基于数据重算边界
    const rows = processed.value!.rows
    const order = processed.value!.chromosomeOrder
    const groups = new Map<string, ManhattanRow[]>()
    rows.forEach((r) => {
      if (!groups.has(r.chromosome)) groups.set(r.chromosome, [])
      groups.get(r.chromosome)!.push(r)
    })
    const boundaries: Array<{ chromosome: string; start: number; end: number }> = []
    let currentX = 0
    const scale = 1e6
    order.forEach((chr) => {
      const group = groups.get(chr)
      if (!group || group.length === 0) return
      group.sort((a, b) => a.position - b.position)
      const maxPos = group[group.length - 1].position
      const start = currentX
      const end = currentX + maxPos / scale
      boundaries.push({ chromosome: chr, start, end })
      currentX = end + (maxPos / scale) * 0.02
    })
    return { chrBoundaries: boundaries }
  })()

  const boundary = chrBoundaries.find((b) => b.chromosome === chromosome)
  if (!boundary) return
  Plotly.relayout(container, {
    'xaxis.range': [boundary.start, boundary.end],
  })
}

function clearSelection() {
  selectedSnpIds.value = new Set()
  renderPlot()
}

function generatePlot() {
  updatePipeline()
}

// === 数据加载 ===
function loadSample() {
  const sample = genSampleData()
  headers.value = sample.headers
  rawRows.value = sample.rows
  colMap.value = autoDetectColumns(sample.headers) as ColMap
  updatePipeline()
  message.success('已加载示例数据')
}

function handleFileChange({ fileList: list }: { fileList: UploadFileInfo[] }) {
  const latest = list[list.length - 1]
  const file = latest?.file
  if (!file) return
  readFile(file, file.name)
}

function readFile(file: File, name: string) {
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const text = reader.result as string
      const { headers: cols, rows } = parseDelimited(text)
      if (!cols.length || !rows.length) {
        message.error('文件解析失败，请检查格式（需含表头与数据行）')
        return
      }
      headers.value = cols
      rawRows.value = rows
      colMap.value = autoDetectColumns(cols) as ColMap
      message.success(`已载入 ${name} · ${rows.length} 条记录`)
      updatePipeline()
    } catch (err: any) {
      message.error('解析失败: ' + err.message)
    }
  }
  reader.onerror = () => message.error('文件读取失败')
  reader.readAsText(file)
}

function handlePaste(e: ClipboardEvent) {
  const text = e.clipboardData?.getData('text') ?? ''
  if (!text.trim()) return
  try {
    const { headers: cols, rows } = parseDelimited(text)
    if (!cols.length || !rows.length) return
    e.preventDefault()
    headers.value = cols
    rawRows.value = rows
    colMap.value = autoDetectColumns(cols) as ColMap
    message.success(`已粘贴 ${rows.length} 条记录`)
    updatePipeline()
  } catch {
    // ignore invalid paste
  }
}

async function updatePipeline() {
  if (!colMap.value.snp || !colMap.value.chromosome || !colMap.value.position || !colMap.value.pvalue) {
    return
  }

  const fullColMap = colMap.value as ColMap
  const errors = validateData(rawRows.value, fullColMap)
  if (errors.length > 0) {
    message.error(`数据校验失败: ${errors.slice(0, 3).join('; ')}${errors.length > 3 ? ` 等${errors.length}处错误` : ''}`)
    return
  }

  processed.value = processManhattanData(rawRows.value, fullColMap, config.value)
  await renderPlot()
}

// === 导出 ===
function exportImage(format: 'png' | 'svg') {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container) return

  const rect = container.getBoundingClientRect()
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')
  const baseName = 'manhattan'

  if (format === 'svg') {
    Plotly.downloadImage(container, {
      format: 'svg',
      filename: `${baseName}_${timestamp}`,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    } as any)
    return
  }

  const dpi = exportDpi.value
  const scale = dpi / 96
  Plotly.downloadImage(container, {
    format: 'png',
    filename: `${baseName}_${timestamp}_${dpi}dpi`,
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    scale,
  } as any)
}

function exportTableData() {
  if (!processed.value) return
  const rows = tableMode.value === 'selected'
    ? processed.value.rows.filter((r) => selectedSnpIds.value.has(r.snpId))
    : processed.value.rows

  const csv = [
    'SNP,Chromosome,Position,P-value,-log10(P),Gene,Is_Significant,Is_Suggestive',
    ...rows.map((r) => `${r.snpId},${r.chromosome},${r.position},${r.pvalue},${r.negLogP},${r.gene || ''},${r.isSignificant},${r.isSuggestive}`),
  ].join('\n')

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `manhattan_data_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

// === 生命周期 ===
let debounceTimer: ReturnType<typeof setTimeout> | null = null

function schedulePipeline() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(updatePipeline, 300)
}

watch(() => [
  config.value.suggestiveLine,
  config.value.genomeWideLine,
  config.value.showSuggestiveLine,
  config.value.showGenomeWideLine,
  config.value.colorScheme,
  config.value.signalColor,
  config.value.pointSize,
  config.value.pointOpacity,
  config.value.showChrLabels,
  config.value.showGeneInHover,
  config.value.showGrid,
  yAxisMaxMode.value,
  manualYMax.value,
], schedulePipeline, { deep: false })

watch(colMap, () => schedulePipeline(), { deep: true })

watch(isDark, () => renderPlot())

onMounted(() => loadSample())

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (hoverResetTimer) clearTimeout(hoverResetTimer)
  const el = document.getElementById(PLOT_DIV_ID)
  if (el) Plotly.purge(el)
  const dist = document.getElementById(CHR_DIST_ID)
  if (dist) Plotly.purge(dist)
})
</script>

<template>
  <div class="manhattan-page" @paste="handlePaste">
    <!-- Toolbar -->
    <PageHeader title="曼哈顿图绘制" subtitle="导入关联分析结果，交互式生成与导出曼哈顿图" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        示例数据
      </NButton>
      <NButton size="small" secondary @click="exportTableData">
        <template #icon><NIcon><DownloadOutline /></NIcon></template>
        导出表格
      </NButton>
      <NButtonGroup>
        <NButton size="tiny" secondary @click="exportImage('png')">PNG</NButton>
        <NButton size="tiny" secondary @click="exportImage('svg')">SVG</NButton>
      </NButtonGroup>
      </template>
    </PageHeader>

    <!-- 主体 -->
    <div class="manhattan-layout">
      <!-- 左侧参数面板 -->
      <aside class="param-panel">
        <NCollapse :default-expanded-names="['data', 'thresholds', 'style']" arrow-placement="left">
          <NCollapseItem title="数据映射" name="data">
            <NUpload
              accept=".csv,.tsv,.txt"
              :max="1"
              :default-upload="false"
              @change="handleFileChange"
            >
              <NButton size="small" block>上传 CSV / TSV</NButton>
            </NUpload>
            <p v-if="rawRows.length" class="hint">已载入 {{ rawRows.length }} 条记录</p>
            <div class="param-row">
              <span class="param-label">SNP 列</span>
              <NSelect v-model:value="colMap.snp" :options="headerOptions" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">染色体列</span>
              <NSelect v-model:value="colMap.chromosome" :options="headerOptions" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">位置列</span>
              <NSelect v-model:value="colMap.position" :options="headerOptions" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">P-value 列</span>
              <NSelect v-model:value="colMap.pvalue" :options="headerOptions" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">基因列(可选)</span>
              <NSelect v-model:value="colMap.gene" :options="headerOptions" size="small" clearable />
            </div>
          </NCollapseItem>

          <NCollapseItem title="阈值线" name="thresholds">
            <div class="param-row">
              <NSwitch v-model:value="config.showSuggestiveLine" size="small" />
              <span class="param-label-inline">显示建议线</span>
              <NInputNumber v-model:value="config.suggestiveLine" :show-button="false" size="small" class="param-input-sm" />
            </div>
            <div class="param-row">
              <NSwitch v-model:value="config.showGenomeWideLine" size="small" />
              <span class="param-label-inline">显示全基因组线</span>
              <NInputNumber v-model:value="config.genomeWideLine" :show-button="false" size="small" class="param-input-sm" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="配色与样式" name="style">
            <div class="param-row">
              <span class="param-label">配色方案</span>
              <NSelect v-model:value="config.colorScheme" :options="colorSchemeOptions" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">信号点颜色</span>
              <NColorPicker v-model:value="config.signalColor" :show-alpha="false" size="small" />
            </div>
            <div class="param-row">
              <span class="param-label">点大小</span>
              <NSlider v-model:value="config.pointSize" :min="1" :max="8" :step="1" />
            </div>
            <div class="param-row">
              <span class="param-label">点透明度</span>
              <NSlider v-model:value="config.pointOpacity" :min="0.3" :max="1.0" :step="0.1" />
            </div>
            <div class="param-row">
              <NSwitch v-model:value="config.showChrLabels" size="small" />
              <span class="param-label-inline">显示染色体标签</span>
            </div>
            <div class="param-row">
              <NSwitch v-model:value="config.showGeneInHover" size="small" />
              <span class="param-label-inline">显示基因名(悬停)</span>
            </div>
            <div class="param-row">
              <NSwitch v-model:value="config.showGrid" size="small" />
              <span class="param-label-inline">显示网格线</span>
            </div>
          </NCollapseItem>

          <NCollapseItem title="坐标轴" name="axis">
            <div class="param-row">
              <span class="param-label">Y轴最大値</span>
              <NRadioGroup v-model:value="yAxisMaxMode" size="small">
                <NRadioButton value="auto">自动</NRadioButton>
                <NRadioButton value="manual">自定义</NRadioButton>
              </NRadioGroup>
              <NInputNumber v-if="yAxisMaxMode === 'manual'" v-model:value="manualYMax" :show-button="false" size="small" class="param-input-sm" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="导出" name="export">
            <div class="param-row">
              <span class="param-label">DPI</span>
              <NSelect v-model:value="exportDpi" :options="[{label:'300',value:300},{label:'600',value:600},{label:'1000',value:1000}]" size="small" />
            </div>
          </NCollapseItem>
        </NCollapse>

        <div class="action-area">
          <NButton size="small" type="primary" :loading="plotting" block @click="generatePlot">
            <template #icon><NIcon><BarChartOutline /></NIcon></template>
            生成图表
          </NButton>
          <NButton v-if="selectedSnpIds.size > 0" size="small" text block @click="clearSelection">
            清除选择 ({{ selectedSnpIds.size }} 个)
          </NButton>
        </div>
      </aside>

      <!-- 中间工作区 -->
      <main class="work-area">
        <div class="plot-card">
          <div v-if="!processed" class="empty-state">
            <NEmpty description="请上传数据或加载示例" />
          </div>
          <NSpin v-else :show="plotting">
            <div :id="PLOT_DIV_ID" class="plot-container" />
          </NSpin>
        </div>

        <div class="table-card">
          <div class="table-header">
            <span class="table-title">
              SNP 明细
              <NTag v-if="selectedSnpIds.size > 0" size="small" type="info">
                已选 {{ selectedSnpIds.size }} 个
              </NTag>
            </span>
            <div class="table-actions">
              <NButton v-if="selectedSnpIds.size > 0" size="tiny" text @click="showAllData">
                显示全部
              </NButton>
              <NButton v-if="selectedSnpIds.size > 0" size="tiny" text @click="showSelectedOnly">
                仅选中
              </NButton>
            </div>
          </div>
          <NDataTable
            :columns="tableColumns"
            :data="filteredTableData"
            :pagination="{ pageSize: 10 }"
            size="small"
            :row-class-name="getRowClassName"
            :scroll-x="700"
            :row-key="(row: ManhattanRow) => row.snpId"
            @update:checked-row-keys="onTableSelectionChange"
            @row-click="onTableRowClick"
            @row-dblclick="onTableRowDblClick"
          />
        </div>
      </main>

      <!-- 右侧统计面板 -->
      <aside class="side-panel">
        <div class="stat-card">
          <div class="stat-title">统计摘要</div>
          <div class="stat-grid">
            <NStatistic label="总 SNP 数" :value="stats?.totalSnpCount || 0" />
            <NStatistic label="全基因组显著" :value="stats?.genomeWideCount || 0">
              <template #suffix>
                <NTag v-if="stats" size="tiny" :type="stats.genomeWideCount > 0 ? 'error' : 'default'">
                  {{ stats.totalSnpCount > 0 ? ((stats.genomeWideCount / stats.totalSnpCount) * 100).toFixed(2) : 0 }}%
                </NTag>
              </template>
            </NStatistic>
            <NStatistic label="建议显著" :value="stats?.suggestiveCount || 0" />
            <NStatistic label="最高峰值">
              <template #default>
                <span v-if="stats" class="peak-value">{{ stats.maxNegLogP.toFixed(2) }}</span>
              </template>
            </NStatistic>
          </div>
          <NDivider />
          <div class="stat-title">峰值 SNP</div>
          <NTag v-if="stats?.peakSnp" size="small" type="error">{{ stats.peakSnp }}</NTag>
        </div>

        <div class="stat-card">
          <div class="stat-title">染色体分布</div>
          <div :id="CHR_DIST_ID" class="mini-chart" />
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.manhattan-page {
  padding: 16px;
  min-height: 100%;
}
.page-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 0;
  flex: 1;
}
.manhattan-layout {
  display: grid;
  grid-template-columns: 280px 1fr 260px;
  gap: 16px;
  align-items: start;
}

.param-panel {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}
.param-panel :deep(.n-collapse-item__header) {
  font-size: 13px;
  font-weight: 600;
}
.param-panel :deep(.n-collapse-item__content-inner) {
  padding-top: 8px;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.param-row:last-child {
  margin-bottom: 0;
}
.param-label {
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  min-width: 70px;
  flex-shrink: 0;
}
.param-label-inline {
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  flex: 1;
}
.param-input-sm {
  width: 70px;
}
.action-area {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 6px 0;
}

.plot-card {
  position: relative;
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 8px;
  min-height: 480px;
}
.plot-container {
  width: 100%;
  height: 480px;
}
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 480px;
}

.table-card {
  margin-top: 12px;
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 8px;
  max-height: 360px;
  overflow-y: auto;
}
.table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding: 0 4px;
}
.table-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1, #1d2129);
  display: flex;
  align-items: center;
  gap: 8px;
}
.table-actions {
  display: flex;
  gap: 4px;
}

.side-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stat-card {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;
}
.stat-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1, #1d2129);
  margin-bottom: 8px;
}
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.peak-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--arco-primary, #165DFF);
}
.mini-chart {
  width: 100%;
  height: 160px;
}

:deep(.row-selected) {
  background-color: var(--arco-primary-light, rgba(22, 93, 255, 0.1)) !important;
}
:deep(.row-hovered) {
  background-color: var(--neutral-bg, rgba(0, 0, 0, 0.04)) !important;
}

@media (max-width: 1200px) {
  .manhattan-layout { grid-template-columns: 1fr; }
  .param-panel, .side-panel { max-height: none; }
}
@media (max-width: 768px) {
  .manhattan-page { padding: 12px; }
}
</style>
