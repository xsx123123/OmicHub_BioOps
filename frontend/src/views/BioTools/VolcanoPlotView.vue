<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton, NCard, NCheckbox, NCollapse, NCollapseItem, NColorPicker,
  NDataTable, NEmpty, NIcon, NInput, NInputNumber, NRadioGroup, NRadioButton, NSelect, NSlider, NSpace,
  NSpin, NStatistic, NSwitch, NTag, NUpload, useMessage,
  type DataTableColumns, type UploadFileInfo,
} from 'naive-ui'
import {
  ArrowBackOutline, BarChartOutline, ContractOutline, DownloadOutline, ExpandOutline,
  RefreshOutline, SparklesOutline,
} from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import { useThemeStore } from '@/stores/theme'
import PageHeader from '@/components/PageHeader.vue'
import {
  autoDetectColumns, buildPlotlyFigure, DEFAULT_COLORS, formatP, genSampleData,
  getSignificantGenes, parseDelimited, processVolcanoData,
  type AxisMode, type ColMap, type ProcessedResult, type VolcanoConfig, type VolcanoRow,
} from '@/utils/volcanoProcessor'

const router = useRouter()
const message = useMessage()
const themeStore = useThemeStore()

const PLOT_DIV_ID = 'volcano-plot'

const form = reactive({
  pvalCutoff: 0.05,
  lfcCutoff: 1,
  expName: 'Volcano',
  pointSize: 6,
  alpha: 0.6,
  showThreshold: true,
  labelTopNEnabled: true,
  labelTopN: 15,
  customGenesText: '',
  // 坐标轴与标题（v1.1）
  xAxisMode: 'auto' as AxisMode,
  xMin: -7.5,
  xMax: 7.5,
  yAxisMode: 'auto' as AxisMode,
  yMin: 0,
  yMax: 250,
  xAxisTitle: '',
  yAxisTitle: '',
  plotTitle: '',
  autoWrapTitle: true,
  // 导出尺寸：关闭时跟随图表容器实际尺寸，开启时用自定义宽高（单位 px）
  exportCustomSize: false,
  exportWidth: 1200,
  exportHeight: 800,
})

const colors = reactive({ ...DEFAULT_COLORS })

const colMap = reactive<ColMap>({ padj: '', lfc: '', gene: '' })

const rawData = ref<Record<string, string>[]>([])
const headers = ref<string[]>([])
const fileName = ref('')
const hasFile = ref(false)
const plotting = ref(false)
const focusGene = ref('')
const searchQuery = ref('')
const selectedGenes = ref<Set<string>>(new Set())
const showTable = ref(false)
const isFullscreen = ref(false)

const processed = ref<ProcessedResult>({
  rows: [],
  stats: { total: 0, up: 0, down: 0, non: 0 },
  axisRange: { xMax: 1, yMax: 1 },
})

/** 切换到手动模式时，用当前自动计算的值填充输入框，避免从默认值突跳。 */
watch(() => form.xAxisMode, (mode) => {
  if (mode === 'manual') {
    const auto = processed.value.axisRange.xMax
    form.xMin = -auto
    form.xMax = auto
  }
})
watch(() => form.yAxisMode, (mode) => {
  if (mode === 'manual') {
    form.yMin = 0
    form.yMax = processed.value.axisRange.yMax
  }
})

const columnOptions = computed(() => headers.value.map((h) => ({ label: h, value: h })))
const isDark = computed(() => themeStore.isDark)

const config = computed<VolcanoConfig>(() => ({
  pvalCutoff: form.pvalCutoff,
  lfcCutoff: form.lfcCutoff,
  expName: form.expName,
  colors: { ...colors },
  pointSize: form.pointSize,
  alpha: form.alpha,
  showThreshold: form.showThreshold,
  labelTopN: form.labelTopNEnabled ? form.labelTopN : 0,
  customGenes: parseCustomGenes(form.customGenesText),
  xAxisMode: form.xAxisMode,
  xMin: form.xMin,
  xMax: form.xMax,
  yAxisMode: form.yAxisMode,
  yMin: form.yMin,
  yMax: form.yMax,
  xAxisTitle: form.xAxisTitle,
  yAxisTitle: form.yAxisTitle,
  plotTitle: form.plotTitle,
  autoWrapTitle: form.autoWrapTitle,
}))

function parseCustomGenes(text: string): string[] {
  return text
    .split(/[,，\n\s]+/)
    .map((g) => g.trim())
    .filter(Boolean)
}

const geneSet = computed(() => new Set(rawData.value.map((r) => (colMap.gene ? r[colMap.gene] : '')).filter(Boolean)))

const invalidCustomGenes = computed(() => {
  const list = parseCustomGenes(form.customGenesText)
  if (!list.length || !geneSet.value.size) return []
  return list.filter((g) => !geneSet.value.has(g))
})

/** 手动轴范围合法性校验：最小值必须小于最大值。 */
const xRangeInvalid = computed(() => form.xMin >= form.xMax)
const yRangeInvalid = computed(() => form.yMin >= form.yMax)

const significantGenes = computed(() => getSignificantGenes(processed.value.rows, 50))

const searchResults = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return []
  return processed.value.rows.filter((r) => r.gene.toLowerCase().includes(q)).slice(0, 30)
})

function handleFileChange({ fileList: list }: { fileList: UploadFileInfo[] }) {
  const latest = list[list.length - 1]
  const file = latest?.file
  if (!file) return
  readFile(file)
}

function readFile(file: File) {
  const reader = new FileReader()
  reader.onload = () => {
    const text = reader.result as string
    const { headers: cols, rows } = parseDelimited(text)
    if (!cols.length || !rows.length) {
      message.error('文件解析失败，请检查格式（需含表头与数据行）')
      return
    }
    loadTable(cols, rows, file.name)
    message.success(`已载入 ${rows.length} 条记录，已自动匹配列`)
  }
  reader.onerror = () => message.error('文件读取失败')
  reader.readAsText(file)
}

function loadTable(cols: string[], rows: Record<string, string>[], name: string) {
  headers.value = cols
  rawData.value = rows
  fileName.value = name
  hasFile.value = true
  const detected = autoDetectColumns(cols)
  colMap.padj = detected.padj
  colMap.lfc = detected.lfc
  colMap.gene = detected.gene
  focusGene.value = ''
  updatePipeline()
}

function handlePaste(e: ClipboardEvent) {
  const text = e.clipboardData?.getData('text') ?? ''
  if (!text.trim()) return
  const { headers: cols, rows } = parseDelimited(text)
  if (!cols.length || !rows.length) return
  e.preventDefault()
  loadTable(cols, rows, 'pasted_data')
  message.success(`已粘贴 ${rows.length} 条记录`)
}

function loadSample() {
  const { headers: cols, rows } = genSampleData()
  loadTable(cols, rows, 'sample_DEG.tsv')
  message.info('已载入示例数据')
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null

function schedulePipeline() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    updatePipeline()
  }, 300)
}

function updatePipeline() {
  if (!rawData.value.length || !colMap.lfc || !colMap.padj) {
    processed.value = {
      rows: [], stats: { total: 0, up: 0, down: 0, non: 0 },
      axisRange: { xMax: 1, yMax: 1 },
    }
    const el = document.getElementById(PLOT_DIV_ID)
    if (el) Plotly.purge(el)
    return
  }
  processed.value = processVolcanoData(rawData.value, colMap, config.value)
  renderPlot()
}

function renderPlot() {
  if (!processed.value.rows.length) return
  plotting.value = true
  nextTick(() => {
    const container = document.getElementById(PLOT_DIV_ID)
    if (!container) {
      plotting.value = false
      return
    }
    const figure = buildPlotlyFigure(
      processed.value.rows,
      config.value,
      processed.value.axisRange,
      isDark.value,
      focusGene.value,
    )
    Plotly.react(container, figure.data, figure.layout, figure.config)
    plotting.value = false
  })
}

const exportDpi = ref(1000)
const dpiOptions = [
  { label: '300 DPI', value: 300 },
  { label: '600 DPI', value: 600 },
  { label: '1000 DPI', value: 1000 },
]

function formatTimestamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

function exportImage(format: 'png' | 'svg') {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container) return
  const baseName = `volcano_${config.value.expName || 'plot'}`
  const rect = container.getBoundingClientRect()
  // 自定义导出尺寸优先；否则跟随图表容器实际尺寸
  const width = form.exportCustomSize ? form.exportWidth : Math.round(rect.width)
  const height = form.exportCustomSize ? form.exportHeight : Math.round(rect.height)
  if (format === 'svg') {
    // SVG 为矢量，无 DPI 概念，直接导出
    Plotly.downloadImage(container, {
      format: 'svg',
      filename: `${baseName}_${formatTimestamp()}`,
      width,
      height,
    })
    return
  }
  // PNG 高 DPI：scale = 目标DPI / 屏幕DPI(96)。
  // @types/plotly.js-dist-min 的 DownloadImgopts 缺 scale 字段，实际 Plotly 支持，用 as any 逃逸。
  const dpi = exportDpi.value
  const scale = dpi / 96
  Plotly.downloadImage(container, {
    format: 'png',
    filename: `${baseName}_${formatTimestamp()}_${dpi}dpi`,
    width,
    height,
    scale,
  } as any)
}

function resetView() {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container) return
  const { xMax, yMax } = processed.value.axisRange
  Plotly.relayout(container, {
    'xaxis.range': [-xMax, xMax],
    'yaxis.range': [0, yMax],
  })
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  nextTick(() => {
    const event = new Event('resize')
    window.dispatchEvent(event)
    if (isFullscreen.value) renderPlot()
  })
}

function focusOnGene(gene: string) {
  if (!gene) return
  focusGene.value = gene
  renderPlot()
  message.info(`已定位基因：${gene}`)
}

function clearFocus() {
  focusGene.value = ''
  renderPlot()
}

function toggleSelectGene(gene: string) {
  const s = new Set(selectedGenes.value)
  if (s.has(gene)) s.delete(gene)
  else s.add(gene)
  selectedGenes.value = s
}

function annotateSelected() {
  if (!selectedGenes.value.size) {
    message.warning('请先勾选要标注的基因')
    return
  }
  const existing = parseCustomGenes(form.customGenesText)
  const merged = Array.from(new Set([...existing, ...selectedGenes.value]))
  form.customGenesText = merged.join(', ')
  selectedGenes.value = new Set()
  message.success(`已加入标注：共 ${merged.length} 个基因`)
}

function handleReset() {
  rawData.value = []
  headers.value = []
  fileName.value = ''
  hasFile.value = false
  colMap.padj = ''
  colMap.lfc = ''
  colMap.gene = ''
  focusGene.value = ''
  searchQuery.value = ''
  selectedGenes.value = new Set()
  form.customGenesText = ''
  const el = document.getElementById(PLOT_DIV_ID)
  if (el) Plotly.purge(el)
  processed.value = {
    rows: [], stats: { total: 0, up: 0, down: 0, non: 0 },
    axisRange: { xMax: 1, yMax: 1 },
  }
}

const tableColumns: DataTableColumns<VolcanoRow> = [
  { title: '基因', key: 'gene', width: 130, fixed: 'left' },
  {
    title: 'log2FC', key: 'log2fc', width: 110,
    sorter: (a, b) => a.log2fc - b.log2fc,
    render: (row) => row.log2fc.toFixed(3),
  },
  {
    title: 'padj', key: 'padj', width: 130,
    sorter: (a, b) => a.padj - b.padj,
    render: (row) => formatP(row.padj),
  },
  {
    title: '-log10(padj)', key: 'negLog10p', width: 130,
    sorter: (a, b) => a.negLog10p - b.negLog10p,
    render: (row) => row.negLog10p.toFixed(3),
  },
  {
    title: '分组', key: 'group', width: 90,
    render: (row) => {
      const map: Record<string, { text: string; type: 'error' | 'info' | 'default' }> = {
        up: { text: '上调', type: 'error' },
        down: { text: '下调', type: 'info' },
        non: { text: '非显著', type: 'default' },
      }
      return map[row.group].text
    },
  },
  {
    title: '标注', key: 'tag', width: 90,
    render: (row) => {
      if (row.isHighlighted) return '自定义'
      if (row.isTop) return 'TopN'
      return '-'
    },
  },
]

watch(
  () => [
    form.pvalCutoff, form.lfcCutoff, form.expName, form.pointSize, form.alpha,
    form.showThreshold, form.labelTopNEnabled, form.labelTopN, form.customGenesText,
    colors.up, colors.down, colors.non, colors.upTag, colors.downTag,
    colMap.padj, colMap.lfc, colMap.gene, rawData.value,
    form.xAxisMode, form.xMin, form.xMax, form.yAxisMode, form.yMin, form.yMax,
    form.xAxisTitle, form.yAxisTitle, form.plotTitle, form.autoWrapTitle,
  ],
  () => schedulePipeline(),
  { deep: false },
)

watch(isDark, () => renderPlot())

onMounted(() => {
  loadSample()
})

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const el = document.getElementById(PLOT_DIV_ID)
  if (el) Plotly.purge(el)
})
</script>

<template>
  <div class="volcano-page" @paste="handlePaste">
    <PageHeader title="火山图绘制" subtitle="导入差异表达结果，交互式筛选与导出火山图" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        示例数据
      </NButton>
      </template>
    </PageHeader>

    <div class="volcano-layout">
      <aside class="param-panel">
        <NCollapse :default-expanded-names="['data', 'thresh', 'axis', 'label', 'style']" arrow-placement="left">
          <NCollapseItem title="数据上传与列映射" name="data">
            <NUpload
              accept=".csv,.tsv,.txt"
              :max="1"
              :default-upload="false"
              @change="handleFileChange"
            >
              <NButton size="small" block>上传 CSV / TSV</NButton>
            </NUpload>
            <p class="hint">{{ hasFile ? `${fileName} · ${rawData.length} 行` : '未上传时使用示例数据，也可直接粘贴表格' }}</p>
            <div class="col-map">
              <NSelect v-model:value="colMap.padj" :options="columnOptions" placeholder="padj 列" size="small" />
              <NSelect v-model:value="colMap.lfc" :options="columnOptions" placeholder="log2FC 列" size="small" />
              <NSelect v-model:value="colMap.gene" :options="columnOptions" placeholder="基因名列" size="small" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="阈值与颜色" name="thresh">
            <div class="row-2col">
              <div class="field">
                <label>pvalue 阈值</label>
                <NInputNumber v-model:value="form.pvalCutoff" :min="0" :max="1" :step="0.01" :show-button="false" size="small" />
              </div>
              <div class="field">
                <label>|log2FC| 阈值</label>
                <NInputNumber v-model:value="form.lfcCutoff" :min="0" :step="0.1" :show-button="false" size="small" />
              </div>
            </div>
            <div class="color-grid">
              <div class="color-field"><label>上调</label><NColorPicker v-model:value="colors.up" size="small" :show-alpha="false" /></div>
              <div class="color-field"><label>下调</label><NColorPicker v-model:value="colors.down" size="small" :show-alpha="false" /></div>
              <div class="color-field"><label>非显著</label><NColorPicker v-model:value="colors.non" size="small" :show-alpha="false" /></div>
              <div class="color-field"><label>上调标注</label><NColorPicker v-model:value="colors.upTag" size="small" :show-alpha="false" /></div>
              <div class="color-field"><label>下调标注</label><NColorPicker v-model:value="colors.downTag" size="small" :show-alpha="false" /></div>
            </div>
            <div class="switch-row">
              <span>显示阈值线</span>
              <NSwitch v-model:value="form.showThreshold" size="small" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="坐标轴与标题" name="axis">
            <div class="switch-row">
              <span>X 轴范围</span>
              <NRadioGroup v-model:value="form.xAxisMode" size="small">
                <NRadioButton value="auto">自动</NRadioButton>
                <NRadioButton value="manual">手动</NRadioButton>
              </NRadioGroup>
            </div>
            <div class="row-2col" v-if="form.xAxisMode === 'manual'">
              <div class="field">
                <label>最小值</label>
                <NInputNumber v-model:value="form.xMin" :step="0.1" :show-button="false" size="small" :status="xRangeInvalid ? 'error' : undefined" />
              </div>
              <div class="field">
                <label>最大值</label>
                <NInputNumber v-model:value="form.xMax" :step="0.1" :show-button="false" size="small" :status="xRangeInvalid ? 'error' : undefined" />
              </div>
            </div>
            <p class="hint error" v-if="form.xAxisMode === 'manual' && xRangeInvalid">X 轴最小值必须小于最大值</p>

            <div class="switch-row">
              <span>Y 轴范围</span>
              <NRadioGroup v-model:value="form.yAxisMode" size="small">
                <NRadioButton value="auto">自动</NRadioButton>
                <NRadioButton value="manual">手动</NRadioButton>
              </NRadioGroup>
            </div>
            <div class="row-2col" v-if="form.yAxisMode === 'manual'">
              <div class="field">
                <label>最小值</label>
                <NInputNumber v-model:value="form.yMin" :step="1" :show-button="false" size="small" :status="yRangeInvalid ? 'error' : undefined" />
              </div>
              <div class="field">
                <label>最大值</label>
                <NInputNumber v-model:value="form.yMax" :step="10" :show-button="false" size="small" :status="yRangeInvalid ? 'error' : undefined" />
              </div>
            </div>
            <p class="hint error" v-if="form.yAxisMode === 'manual' && yRangeInvalid">Y 轴最小值必须小于最大值</p>

            <div class="field">
              <label>X 轴标题</label>
              <NInput v-model:value="form.xAxisTitle" size="small" placeholder="留空使用默认" />
            </div>
            <div class="field">
              <label>Y 轴标题</label>
              <NInput v-model:value="form.yAxisTitle" size="small" placeholder="留空使用默认" />
            </div>
            <div class="field">
              <label>Plot 标题</label>
              <NInput v-model:value="form.plotTitle" size="small" placeholder="留空使用「实验名 Volcano Plot」" />
            </div>
            <div class="switch-row">
              <span>标题自动换行</span>
              <NSwitch v-model:value="form.autoWrapTitle" size="small" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="标注设置" name="label">
            <div class="switch-row">
              <span>自动标注 Top N</span>
              <NSwitch v-model:value="form.labelTopNEnabled" size="small" />
            </div>
            <div class="field" v-if="form.labelTopNEnabled">
              <label>Top N 数量（上下调各 N/2）</label>
              <NInputNumber v-model:value="form.labelTopN" :min="1" :max="100" :show-button="false" size="small" />
            </div>
            <div class="field">
              <label>自定义标注基因（逗号/换行分隔）</label>
              <NInput v-model:value="form.customGenesText" type="textarea" :rows="3" size="small" placeholder="TP53, BRCA1, EGFR" />
            </div>
            <p class="hint error" v-if="invalidCustomGenes.length">
              未找到：{{ invalidCustomGenes.join(', ') }}
            </p>
            <NButton size="tiny" block quaternary :disabled="!selectedGenes.size" @click="annotateSelected">
              标注右侧勾选的 {{ selectedGenes.size }} 个基因
            </NButton>
          </NCollapseItem>

          <NCollapseItem title="图表样式" name="style">
            <div class="field">
              <label>实验名称</label>
              <NInput v-model:value="form.expName" size="small" placeholder="Volcano" />
            </div>
            <div class="field">
              <label>点大小 ({{ form.pointSize }})</label>
              <NSlider v-model:value="form.pointSize" :min="2" :max="15" :step="1" />
            </div>
            <div class="field">
              <label>非显著透明度 ({{ form.alpha.toFixed(2) }})</label>
              <NSlider v-model:value="form.alpha" :min="0.1" :max="1" :step="0.05" />
            </div>

            <div class="switch-row">
              <span>自定义导出尺寸</span>
              <NSwitch v-model:value="form.exportCustomSize" size="small" />
            </div>
            <div class="row-2col" v-if="form.exportCustomSize">
              <div class="field">
                <label>宽度 (px)</label>
                <NInputNumber v-model:value="form.exportWidth" :min="100" :max="8000" :step="10" :show-button="false" size="small" />
              </div>
              <div class="field">
                <label>高度 (px)</label>
                <NInputNumber v-model:value="form.exportHeight" :min="100" :max="8000" :step="10" :show-button="false" size="small" />
              </div>
            </div>
            <p class="hint" v-if="form.exportCustomSize">
              PNG 按 DPI 放大：{{ form.exportWidth }}×{{ form.exportHeight }} @ {{ exportDpi }}DPI → {{ Math.round(form.exportWidth * exportDpi / 96) }}×{{ Math.round(form.exportHeight * exportDpi / 96) }}px
            </p>
          </NCollapseItem>
        </NCollapse>
        <NButton block quaternary size="small" class="reset-btn" @click="handleReset">重置全部</NButton>
      </aside>

      <main class="plot-area" :class="{ fullscreen: isFullscreen }">
        <div class="plot-toolbar">
          <NButton size="small" type="primary" :loading="plotting" @click="updatePipeline">
            <template #icon><NIcon><BarChartOutline /></NIcon></template>生成图表
          </NButton>
          <NButton size="tiny" secondary @click="exportImage('png')">
            <template #icon><NIcon><DownloadOutline /></NIcon></template>PNG
          </NButton>
          <NSelect
            v-model:value="exportDpi"
            :options="dpiOptions"
            size="tiny"
            style="width: 116px"
          />
          <NButton size="tiny" secondary @click="exportImage('svg')">SVG</NButton>
          <NButton size="tiny" secondary @click="resetView">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>重置视图
          </NButton>
          <NButton size="tiny" secondary @click="toggleFullscreen">
            <template #icon><NIcon><ExpandOutline v-if="!isFullscreen" /><ContractOutline v-else /></NIcon></template>
            {{ isFullscreen ? '退出全屏' : '全屏' }}
          </NButton>
          <NButton v-if="focusGene" size="tiny" tertiary @click="clearFocus">
            清除定位 ({{ focusGene }})
          </NButton>
        </div>

        <div class="plot-card">
          <NEmpty
            v-if="!processed.rows.length"
            class="plot-placeholder"
            description="请上传差异表达结果（含 padj 与 log2FoldChange 列），或载入示例数据；也可直接粘贴表格。"
          />
          <div v-else :id="PLOT_DIV_ID" class="plot-container" />
          <div v-if="plotting" class="plot-overlay">
            <NSpin description="绘图中..." />
          </div>
        </div>
      </main>

      <aside class="gene-panel">
        <div class="stats-grid">
          <div class="stat stat-total"><NStatistic label="总基因" :value="processed.stats.total" /></div>
          <div class="stat stat-up"><NStatistic label="上调" :value="processed.stats.up" /></div>
          <div class="stat stat-down"><NStatistic label="下调" :value="processed.stats.down" /></div>
          <div class="stat stat-non"><NStatistic label="非显著" :value="processed.stats.non" /></div>
        </div>

        <div class="search-section">
          <NInput v-model:value="searchQuery" placeholder="🔍 搜索基因名" clearable size="small" />
          <div class="search-results" v-if="searchQuery.trim()">
            <div v-if="!searchResults.length" class="search-empty">无匹配基因</div>
            <div
              v-for="r in searchResults"
              :key="r.gene"
              class="search-item"
              @click="focusOnGene(r.gene)"
            >
              <span class="gene-name">{{ r.gene }}</span>
              <NTag size="tiny" :type="r.group === 'up' ? 'error' : r.group === 'down' ? 'info' : 'default'">
                {{ r.group === 'up' ? '↑' : r.group === 'down' ? '↓' : '·' }} {{ r.log2fc.toFixed(2) }}
              </NTag>
            </div>
          </div>
        </div>

        <div class="sig-section">
          <div class="sig-header">
            <span>显著基因 Top {{ significantGenes.length }}</span>
            <NButton size="tiny" quaternary :disabled="!selectedGenes.size" @click="annotateSelected">
              标注选中 ({{ selectedGenes.size }})
            </NButton>
          </div>
          <div class="sig-list">
            <div v-if="!significantGenes.length" class="search-empty">当前阈值下无显著基因</div>
            <div v-for="r in significantGenes" :key="r.gene" class="sig-item">
              <NCheckbox
                :checked="selectedGenes.has(r.gene)"
                @update:checked="toggleSelectGene(r.gene)"
              />
              <span class="sig-gene" @click="focusOnGene(r.gene)">
                {{ r.gene }}
                <span :class="r.group === 'up' ? 'arrow-up' : 'arrow-down'">
                  {{ r.group === 'up' ? '↑' : '↓' }}{{ r.log2fc.toFixed(2) }}
                </span>
              </span>
              <span class="sig-p">{{ r.negLog10p.toFixed(1) }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <div class="bottom-table">
      <div class="bottom-header" @click="showTable = !showTable">
        <span>数据预览 · 共 {{ processed.rows.length }} 条</span>
        <NTag size="small" round>{{ showTable ? '收起' : '展开' }}</NTag>
      </div>
      <div v-if="showTable" class="bottom-table-body">
        <NDataTable
          :columns="tableColumns"
          :data="processed.rows"
          :row-key="(row) => row.gene"
          :pagination="{ pageSize: 20 }"
          :bordered="true"
          size="small"
          :scroll-x="700"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.volcano-page {
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
  color: var(--neutral-text-1);
  margin: 0;
  flex: 1;
}
.volcano-layout {
  display: grid;
  grid-template-columns: 300px 1fr 280px;
  gap: 12px;
  align-items: start;
}
.param-panel,
.gene-panel {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
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
.hint {
  font-size: 12px;
  color: var(--neutral-text-3);
  margin: 6px 0;
}
.hint.error {
  color: #f53f3f;
}
.col-map {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}
.row-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.field {
  margin-bottom: 10px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin-bottom: 4px;
}
.color-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 8px 0;
}
.color-field label {
  display: block;
  font-size: 11px;
  color: var(--neutral-text-3);
  margin-bottom: 3px;
}
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--neutral-text-2);
  margin: 6px 0;
}
.reset-btn {
  margin-top: 10px;
}
.plot-area {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.plot-area.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: var(--neutral-card);
  padding: 16px;
  max-height: 100vh;
}
.plot-toolbar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.plot-card {
  position: relative;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 8px;
  min-height: 540px;
}
.plot-area.fullscreen .plot-card {
  flex: 1;
  min-height: 0;
}
.plot-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--neutral-card);
  opacity: 0.6;
  border-radius: 12px;
}
.plot-placeholder {
  height: 520px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.plot-container {
  width: 100%;
  height: 560px;
}
.plot-area.fullscreen .plot-container {
  height: calc(100vh - 120px);
}
.gene-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.stat {
  text-align: center;
  padding: 6px 0;
  border-radius: 8px;
  background: var(--neutral-bg);
}
.stat-up :deep(.n-statistic-value__content) { color: #e41749; }
.stat-down :deep(.n-statistic-value__content) { color: #41b6e6; }
.stat-non :deep(.n-statistic-value__content) { color: #86909c; }
.stat-total :deep(.n-statistic-value__content) { color: var(--neutral-text-1); }
.search-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.search-results {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
}
.search-empty {
  padding: 10px;
  font-size: 12px;
  color: var(--neutral-text-3);
  text-align: center;
}
.search-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  cursor: pointer;
  border-bottom: 1px solid var(--neutral-border);
  font-size: 12px;
}
.search-item:hover {
  background: var(--neutral-bg);
}
.search-item .gene-name {
  font-weight: 500;
  color: var(--neutral-text-1);
}
.sig-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 6px;
}
.sig-list {
  max-height: 360px;
  overflow-y: auto;
}
.sig-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 4px;
  border-bottom: 1px solid var(--neutral-border);
  font-size: 12px;
}
.sig-gene {
  flex: 1;
  cursor: pointer;
  color: var(--neutral-text-1);
}
.sig-gene:hover {
  color: var(--arco-primary, #165dff);
}
.arrow-up { color: #e41749; margin-left: 4px; }
.arrow-down { color: #41b6e6; margin-left: 4px; }
.sig-p {
  color: var(--neutral-text-3);
  font-size: 11px;
}
.bottom-table {
  margin-top: 16px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  overflow: hidden;
}
.bottom-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}
.bottom-table-body {
  padding: 0 12px 12px;
}
@media (max-width: 1200px) {
  .volcano-layout {
    grid-template-columns: 1fr;
  }
  .param-panel,
  .gene-panel {
    max-height: none;
  }
}
</style>
