<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  NAlert, NButton, NDataTable, NEmpty, NIcon, NInput, NInputNumber, NRadioButton, NRadioGroup,
  NSelect, NSlider, NSwitch, NTag, useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  AddOutline, BarChartOutline, CopyOutline, DownloadOutline, SparklesOutline, TrashOutline,
} from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import {
  buildUpsetFigure, buildVennFigure, computeRegions, DEFAULT_STYLE, describeRegion,
  genSampleLists, PALETTE_OPTIONS, parseListText, resolvePaletteColors,
  type NamedSet, type PaletteKey, type ParsedList, type VennUpsetStyleConfig,
} from '@/utils/vennUpsetProcessor'
import PageHeader from '@/components/PageHeader.vue'
import ToolActionBar from '@/components/ToolActionBar.vue'
import { useThemeStore } from '@/stores/theme'

const message = useMessage()
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

const PLOT_DIV_ID = 'venn-upset-plot'

const MIN_LISTS = 2
const MAX_LISTS = 6

interface ListEntry {
  id: number
  name: string
  text: string
}

let listSeq = 0
function newList(name = '', text = ''): ListEntry {
  listSeq += 1
  return { id: listSeq, name, text }
}

const lists = ref<ListEntry[]>([newList('集合 A'), newList('集合 B')])
const caseSensitive = ref(false)
const viewMode = ref<'auto' | 'venn' | 'upset'>('auto')

const style = reactive<VennUpsetStyleConfig>({ ...DEFAULT_STYLE })

const exportDpi = ref(1000)
const dpiOptions = [
  { label: '300 DPI', value: 300 },
  { label: '600 DPI', value: 600 },
  { label: '1000 DPI', value: 1000 },
]

const plotting = ref(false)

type Selection = { kind: 'region'; key: string } | { kind: 'set'; index: number } | null
const selection = ref<Selection>(null)

/* ---------- 数据管线 ---------- */

const parsedById = computed(() => {
  const m = new Map<number, ParsedList>()
  for (const l of lists.value) m.set(l.id, parseListText(l.text, caseSensitive.value))
  return m
})

function parsedOf(id: number): ParsedList {
  return parsedById.value.get(id) ?? { items: [], rawCount: 0, dupCount: 0 }
}

const nonEmptySets = computed<NamedSet[]>(() =>
  lists.value
    .filter((l) => parsedOf(l.id).items.length > 0)
    .map((l) => ({ name: l.name.trim() || '未命名集合', items: parsedOf(l.id).items })),
)

const emptyListNames = computed(() =>
  lists.value.filter((l) => !parsedOf(l.id).items.length).map((l) => l.name.trim() || '未命名集合'),
)

const regions = computed(() => computeRegions(nonEmptySets.value, caseSensitive.value))

const effectiveMode = computed<'venn' | 'upset'>(() => {
  const n = nonEmptySets.value.length
  if (viewMode.value === 'venn' && n >= 2 && n <= 3) return 'venn'
  if (viewMode.value === 'upset' && n >= 2) return 'upset'
  return n <= 3 ? 'venn' : 'upset'
})

const paletteResult = computed(() => resolvePaletteColors(style.palette, nonEmptySets.value.length))
const chartColors = computed(() => paletteResult.value.colors)
const paletteOverflow = computed(() => paletteResult.value.overflow)

const selectedRegionKey = computed(() =>
  selection.value?.kind === 'region' ? selection.value.key : null,
)

watch(
  () => lists.value.map((l) => `${l.text}|${l.name}`).join('') + caseSensitive.value,
  () => { selection.value = null },
)

function addList() {
  if (lists.value.length >= MAX_LISTS) return
  lists.value.push(newList(`集合 ${String.fromCharCode(65 + lists.value.length)}`))
}

function removeList(id: number) {
  if (lists.value.length <= MIN_LISTS) return
  lists.value = lists.value.filter((l) => l.id !== id)
}

function loadSample(silent = false) {
  const samples = genSampleLists()
  while (lists.value.length < samples.length) addList()
  samples.forEach((s, i) => {
    lists.value[i].name = s.name
    lists.value[i].text = s.text
  })
  if (!silent) message.success('已载入示例数据（3 个基因列表）')
}

/* ---------- 渲染 ---------- */

let renderedMode: 'venn' | 'upset' | '' = ''

function renderPlot() {
  if (nonEmptySets.value.length < 2) return
  plotting.value = true
  nextTick(() => {
    const container = document.getElementById(PLOT_DIV_ID)
    if (!container) {
      plotting.value = false
      return
    }
    const mode = effectiveMode.value
    const figure =
      mode === 'venn'
        ? buildVennFigure(nonEmptySets.value, regions.value, style, isDark.value, chartColors.value, selectedRegionKey.value)
        : buildUpsetFigure(nonEmptySets.value, regions.value, style, isDark.value, chartColors.value, selectedRegionKey.value)

    if (renderedMode !== mode) {
      Plotly.purge(container)
      container.removeAttribute('data-events-bound')
      renderedMode = mode
    }
    Plotly.react(container, figure.data, figure.layout, figure.config)

    if (!container.hasAttribute('data-events-bound')) {
      bindPlotEvents(container)
      container.setAttribute('data-events-bound', 'true')
    }
    if (!container.hasAttribute('data-native-bound')) {
      bindNativeEvents(container)
      container.setAttribute('data-native-bound', 'true')
    }
    plotting.value = false
  })
}

function bindPlotEvents(container: any) {
  container.on('plotly_click' as any, (event: any) => {
    const key = event.points?.[0]?.customdata
    if (typeof key !== 'string' || !key) return
    if (selection.value?.kind === 'region' && selection.value.key === key) {
      selection.value = null
    } else {
      selection.value = { kind: 'region', key }
    }
  })
}

function bindNativeEvents(container: HTMLElement) {
  // 重渲染会替换光标下的节点，浏览器可能不再派发 dblclick，这里兜底清空选中
  container.addEventListener('dblclick', () => {
    selection.value = null
  })
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null
function scheduleRender() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => renderPlot(), 300)
}

function generate() {
  if (debounceTimer) clearTimeout(debounceTimer)
  renderPlot()
  message.success('图表已生成')
}

watch(
  () => [
    nonEmptySets.value, regions.value, effectiveMode.value,
    style.title, style.width, style.height, style.showLegend, style.palette, style.barGap,
    caseSensitive.value,
  ],
  () => scheduleRender(),
  { deep: false },
)

watch(selectedRegionKey, () => renderPlot())
watch(isDark, () => renderPlot())

/* ---------- 选中区域与结果表 ---------- */

const selectedElements = computed<string[]>(() => {
  const sel = selection.value
  if (!sel) return []
  if (sel.kind === 'set') {
    return [...(nonEmptySets.value[sel.index]?.items ?? [])].sort((a, b) => a.localeCompare(b))
  }
  return regions.value.find((r) => r.key === sel.key)?.elements ?? []
})

const selectedTitle = computed(() => {
  const sel = selection.value
  if (!sel) return ''
  const names = nonEmptySets.value.map((s) => s.name)
  if (sel.kind === 'set') return `${names[sel.index] ?? ''}（全部元素）`
  const r = regions.value.find((x) => x.key === sel.key)
  return r ? describeRegion(r.indices, names) : ''
})

interface ElementRow { value: string }
const elementColumns: DataTableColumns<ElementRow> = [
  { title: '元素 ID', key: 'value', sorter: (a, b) => a.value.localeCompare(b.value) },
]
const elementRows = computed<ElementRow[]>(() => selectedElements.value.map((v) => ({ value: v })))

async function copyElements() {
  if (!selectedElements.value.length) {
    message.warning('暂无可复制的元素')
    return
  }
  try {
    await navigator.clipboard.writeText(selectedElements.value.join('\n'))
    message.success(`已复制 ${selectedElements.value.length} 个元素`)
  } catch {
    message.error('复制失败，请手动选择文本')
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportCsv() {
  if (!selectedElements.value.length) {
    message.warning('暂无可导出的元素')
    return
  }
  const content = `element\n${selectedElements.value.join('\n')}\n`
  downloadBlob(new Blob([content], { type: 'text/csv;charset=utf-8' }), 'venn_upset_elements.csv')
}

/* ---------- 图片导出 ---------- */

function formatTimestamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

function exportImage(format: 'png' | 'svg') {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container || nonEmptySets.value.length < 2) {
    message.warning('暂无可导出的图表')
    return
  }
  const baseName = 'venn_upset_plot'
  const width = style.width
  const height = style.height
  if (format === 'svg') {
    Plotly.downloadImage(container, {
      format: 'svg',
      filename: `${baseName}_${formatTimestamp()}`,
      width,
      height,
    })
    return
  }
  const dpi = exportDpi.value
  const scale = dpi / 96
  // @types/plotly.js-dist-min 的 DownloadImgopts 缺 scale 字段，实际 Plotly 支持，用 as any 逃逸。
  Plotly.downloadImage(container, {
    format: 'png',
    filename: `${baseName}_${formatTimestamp()}_${dpi}dpi`,
    width,
    height,
    scale,
  } as any)
}

/* ---------- 生命周期 ---------- */

onMounted(() => {
  if (lists.value.every((l) => !parsedOf(l.id).items.length)) loadSample(true)
  renderPlot()
})

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const el = document.getElementById(PLOT_DIV_ID)
  if (el) Plotly.purge(el)
})
</script>

<template>
  <div class="venn-upset-page">
    <PageHeader
      title="Venn / UpSet 集合分析"
      subtitle="2~3 个集合绘制韦恩图，4~6 个集合自动切换 UpSet 图，全部在浏览器本地完成"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <NAlert type="info" class="local-alert" :bordered="false">
      纯本地运算，数据不离开浏览器；图内标注为英文，可直接用于论文配图
    </NAlert>

    <div class="venn-upset-layout">
      <!-- 左：列表输入 + 样式 -->
      <aside class="param-panel">
        <div class="panel-header">
          <span class="panel-title">集合列表（{{ lists.length }}/{{ MAX_LISTS }}）</span>
          <NButton size="tiny" text class="sample-link" @click="loadSample()">
            <template #icon><NIcon><SparklesOutline /></NIcon></template>
            试试示例数据
          </NButton>
          <NButton size="tiny" secondary :disabled="lists.length >= MAX_LISTS" @click="addList">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            添加列表
          </NButton>
        </div>

        <div class="case-switch">
          <span>区分大小写</span>
          <NSwitch v-model:value="caseSensitive" size="small" />
        </div>

        <NAlert v-if="emptyListNames.length && nonEmptySets.length" type="warning" class="empty-alert" :bordered="false">
          列表「{{ emptyListNames.join('、') }}」为空，已自动忽略空列表。
        </NAlert>

        <div v-for="(l, i) in lists" :key="l.id" class="list-card">
          <div class="list-card-head">
            <span class="list-dot" :style="{ background: chartColors[i % chartColors.length] }" />
            <NInput v-model:value="l.name" size="small" placeholder="列表名称" class="list-name" />
            <NTag size="small" :bordered="false">{{ parsedOf(l.id).items.length }} 条</NTag>
            <NButton
              size="tiny" quaternary circle
              :disabled="lists.length <= MIN_LISTS"
              @click="removeList(l.id)"
            >
              <template #icon><NIcon><TrashOutline /></NIcon></template>
            </NButton>
          </div>
          <NInput
            v-model:value="l.text"
            type="textarea"
            :autosize="{ minRows: 5, maxRows: 12 }"
            placeholder="粘贴基因 / ID 列表，支持换行、逗号、空格、Tab 混合分隔"
          />
          <div v-if="parsedOf(l.id).dupCount > 0" class="dup-hint">
            已自动去除 {{ parsedOf(l.id).dupCount }} 个重复条目
          </div>
        </div>

        <!-- 图表样式与导出 -->
        <div class="style-block">
          <div class="panel-header">
            <span class="panel-title">图表样式与导出</span>
          </div>

          <div class="field">
            <label>图标题（留空用默认英文标题）</label>
            <NInput v-model:value="style.title" size="small" placeholder="Venn Diagram / UpSet Plot" />
          </div>

          <div class="field">
            <label>色板</label>
            <NSelect v-model:value="style.palette" :options="PALETTE_OPTIONS" size="small" />
          </div>

          <NAlert v-if="paletteOverflow" type="warning" class="empty-alert" :bordered="false">
            所选色板颜色数不足（需 {{ nonEmptySets.length }} 种），已自动改用色觉友好扩展色板。
          </NAlert>

          <div class="switch-row">
            <span>显示图例</span>
            <NSwitch v-model:value="style.showLegend" size="small" />
          </div>

          <div class="field" v-if="effectiveMode === 'upset'">
            <label>柱宽（间隙 {{ Math.round(style.barGap * 100) }}%）</label>
            <NSlider v-model:value="style.barGap" :min="0" :max="0.9" :step="0.05" />
          </div>

          <div class="row-2col">
            <div class="field">
              <label>导出宽度 (px)</label>
              <NInputNumber v-model:value="style.width" :min="100" :max="8000" :step="10" :show-button="false" size="small" />
            </div>
            <div class="field">
              <label>导出高度 (px)</label>
              <NInputNumber v-model:value="style.height" :min="100" :max="8000" :step="10" :show-button="false" size="small" />
            </div>
          </div>
          <p class="hint">
            PNG 按 DPI 放大：{{ style.width }}×{{ style.height }} @ {{ exportDpi }} DPI →
            {{ Math.round(style.width * exportDpi / 96) }}×{{ Math.round(style.height * exportDpi / 96) }} px
          </p>
        </div>
      </aside>

      <!-- 右：图表与结果 -->
      <main class="work-area">
        <div class="work-card">
          <div class="chart-toolbar">
            <NRadioGroup v-model:value="viewMode" size="small">
              <NRadioButton value="auto">自动</NRadioButton>
              <NRadioButton value="venn" :disabled="nonEmptySets.length > 3">韦恩图</NRadioButton>
              <NRadioButton value="upset">UpSet</NRadioButton>
            </NRadioGroup>
            <div class="chart-actions">
              <NButton size="tiny" secondary :disabled="nonEmptySets.length < 2" @click="exportImage('png')">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>PNG
              </NButton>
              <NSelect
                v-model:value="exportDpi"
                :options="dpiOptions"
                size="tiny"
                style="width: 110px"
              />
              <NButton size="tiny" secondary :disabled="nonEmptySets.length < 2" @click="exportImage('svg')">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>SVG
              </NButton>
            </div>
          </div>

          <div class="plot-card">
            <NEmpty
              v-if="nonEmptySets.length < 2"
              class="plot-placeholder"
              description="至少需要 2 个非空列表才能绘制，请在左侧粘贴数据或载入示例"
            />
            <div v-else :id="PLOT_DIV_ID" class="plot-container" />
          </div>
        </div>

        <!-- 选中区域元素表 -->
        <div class="work-card">
          <div class="panel-header">
            <span class="panel-title">
              {{ selection ? `${selectedTitle} · ${selectedElements.length} 个元素` : '点击图中区域查看元素列表' }}
            </span>
            <div class="chart-actions">
              <NButton size="tiny" secondary :disabled="!selectedElements.length" @click="copyElements">
                <template #icon><NIcon><CopyOutline /></NIcon></template>复制
              </NButton>
              <NButton size="tiny" secondary :disabled="!selectedElements.length" @click="exportCsv">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>CSV
              </NButton>
            </div>
          </div>
          <NDataTable
            v-if="selection"
            :columns="elementColumns"
            :data="elementRows"
            size="small"
            :pagination="{ pageSize: 10 }"
            :max-height="320"
          />
          <NEmpty v-else description="点击韦恩图区域或 UpSet 柱子，此处展示该交集的元素；双击图表空白处取消选择" />
        </div>
      </main>
    </div>

    <ToolActionBar
      :ready="nonEmptySets.length >= 2"
      :ready-text="`${nonEmptySets.length} 个集合已就绪`"
      not-ready-text="至少需要 2 个非空列表"
      not-ready-tip="请在左侧粘贴基因列表或点击「试试示例数据」，至少填满 2 个列表"
      primary-label="生成图表"
      :primary-icon="BarChartOutline"
      :loading="plotting"
      @action="generate"
    />
  </div>
</template>

<style scoped>
.venn-upset-page {
  padding: 16px;
  min-height: 100%;
}

.local-alert {
  margin-bottom: 12px;
}

.venn-upset-layout {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
  align-items: start;
}

.param-panel,
.work-card {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;
}

.param-panel {
  max-height: calc(100vh - 140px);
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}

.case-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--neutral-text-2, #4e5969);
  margin-bottom: 10px;
}

.empty-alert {
  margin-bottom: 10px;
}

.list-card {
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 10px;
  padding: 10px;
  margin-bottom: 10px;
}

.list-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.list-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.list-name {
  flex: 1;
  min-width: 0;
}

.dup-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}

.style-block {
  border-top: 1px solid var(--neutral-border, #e5e6eb);
  margin-top: 4px;
  padding-top: 12px;
}

.field {
  margin-bottom: 10px;
}

.field label {
  display: block;
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  margin-bottom: 4px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  margin: 6px 0 10px;
}

.row-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 6px 0 0;
}

.work-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.chart-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.plot-card {
  position: relative;
  min-height: 540px;
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

@media (max-width: 1200px) {
  .venn-upset-layout {
    grid-template-columns: 1fr;
  }
  .param-panel {
    max-height: none;
  }
}

@media (max-width: 768px) {
  .venn-upset-page {
    padding: 16px;
  }
}
</style>
