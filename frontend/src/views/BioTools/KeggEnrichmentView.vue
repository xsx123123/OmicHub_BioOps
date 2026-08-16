<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { TOOLBOX_RESULT_QUERY } from '@/utils/toolboxResultRoute'
import {
  NAlert,
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NTooltip,
  NUpload,
  useMessage,
  type DataTableColumns,
  type UploadFileInfo,
} from 'naive-ui'
import { DownloadOutline, RefreshOutline, SendOutline, SparklesOutline } from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import {
  downloadEnrichmentResult,
  fetchEnrichmentExample,
  fetchEnrichmentHistory,
  fetchEnrichmentTask,
  fetchSpeciesOptions,
  submitEnrichment,
} from '@/api/enrichment'
import PageHeader from '@/components/PageHeader.vue'
import ToolActionBar from '@/components/ToolActionBar.vue'
import { useThemeStore } from '@/stores/theme'
import type { EnrichmentResult, EnrichmentRow, EnrichmentTask, SpeciesOption } from '@/types/enrichment'
import {
  buildEnrichmentPlot,
  ENRICHMENT_COLOR_OPTIONS,
  filterEnrichmentRows,
  type EnrichmentSource,
} from '@/utils/enrichmentProcessor'

const message = useMessage()
const themeStore = useThemeStore()
const route = useRoute()

const form = reactive({
  projectName: '',
  speciesId: '',
  geneText: '',
  geneFile: null as File | null,
  pValueCutoff: 0.05,
  qValueCutoff: 0.1,
  goColor: 'var(--kimi-chart-3)',
  keggColor: 'var(--kimi-chart-1)',
  chartWidth: 960,
  chartHeight: 480,
  exportCustomSize: false,
  exportWidth: 1600,
  exportHeight: 1000,
})

const exportDpi = ref(300)
const inputMode = ref<'text' | 'file'>('text')
const speciesOptions = ref<SpeciesOption[]>([])
const speciesLoading = ref(false)
const speciesError = ref('')
const sampleLoading = ref(false)
const historyLoading = ref(false)
const historyTasks = ref<EnrichmentTask[]>([])
const openingHistoryTaskId = ref('')
const submitting = ref(false)
const activeTask = ref<EnrichmentTask | null>(null)
const taskError = ref('')
const result = ref<EnrichmentResult | null>(null)
const fileList = ref<UploadFileInfo[]>([])
const goPlotContainer = ref<HTMLElement | null>(null)
const keggPlotContainer = ref<HTMLElement | null>(null)
let taskPollTimer: ReturnType<typeof setTimeout> | undefined
let plotRenderTimer: ReturnType<typeof setTimeout> | undefined

const speciesSelectOptions = computed(() =>
  speciesOptions.value.map((species) => ({ label: species.label, value: species.id })),
)
const selectedSpecies = computed(() =>
  speciesOptions.value.find((species) => species.id === form.speciesId) ?? null,
)
const selectedAnalysisTypes = computed(() => selectedSpecies.value?.analysis_types.join(' / ') || '未配置')
const goRows = computed(() => filterEnrichmentRows(result.value?.table_data ?? [], 'GO'))
const keggRows = computed(() => filterEnrichmentRows(result.value?.table_data ?? [], 'KEGG'))
const hasResults = computed(() => goRows.value.length > 0 || keggRows.value.length > 0)
const isSampleResult = computed(() => result.value?.task_id === 'sample-cop1-hy5-dependent-1576')
const exportDpiOptions = [
  { label: '300 DPI（报告）', value: 300 },
  { label: '600 DPI（投稿）', value: 600 },
  { label: '1000 DPI（精细）', value: 1000 },
]
const resultColumnDescriptions = [
  { field: 'GO ID / Pathway ID', description: 'GO 术语或 KEGG 通路的稳定标识符，可用于数据库检索与结果追踪。' },
  { field: 'Description', description: '术语或通路名称；图中长文本会折成两行并省略，悬停可查看完整名称。' },
  { field: 'GeneRatio', description: '输入基因中命中该术语或通路的比例，格式为命中数 / 参与富集计算的基因数。' },
  { field: 'p-value', description: '富集检验的原始显著性概率，数值越小表示随机出现该富集程度的可能性越低。' },
  { field: 'p.adjust', description: 'clusterProfiler 多重检验校正后的 p-value；气泡颜色深浅按 -log10(p.adjust) 映射。' },
  { field: 'q-value', description: '对假发现率的估计，用于辅助判断多重检验后的结果可靠性。' },
  { field: 'Count', description: '输入 Gene ID 列表中命中该术语或通路的基因数量，同时映射为气泡大小。' },
  { field: '查看 KEGG', description: '仅 KEGG 表提供，打开 KEGG 官方通路详情页面。' },
]

const goColumns: DataTableColumns<EnrichmentRow> = [
  { title: 'GO ID', key: 'id', width: 145, fixed: 'left' },
  { title: 'GO Term', key: 'description', ellipsis: { tooltip: true }, minWidth: 240 },
  { title: 'GeneRatio', key: 'gene_ratio', width: 105 },
  { title: 'p-value', key: 'pvalue', width: 105, render: (row) => formatScientific(row.pvalue) },
  { title: 'p.adjust', key: 'p_adjust', width: 105, render: (row) => formatScientific(row.p_adjust) },
  { title: 'q-value', key: 'q_value', width: 105, render: (row) => formatScientific(row.q_value) },
  { title: 'Count', key: 'count', width: 80 },
]

const keggColumns: DataTableColumns<EnrichmentRow> = [
  { title: 'Pathway ID', key: 'id', width: 145, fixed: 'left' },
  { title: 'KEGG Pathway', key: 'description', ellipsis: { tooltip: true }, minWidth: 240 },
  { title: 'GeneRatio', key: 'gene_ratio', width: 105 },
  { title: 'p-value', key: 'pvalue', width: 105, render: (row) => formatScientific(row.pvalue) },
  { title: 'p.adjust', key: 'p_adjust', width: 105, render: (row) => formatScientific(row.p_adjust) },
  { title: 'q-value', key: 'q_value', width: 105, render: (row) => formatScientific(row.q_value) },
  { title: 'Count', key: 'count', width: 80 },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render: (row) =>
      h(
        'a',
        {
          href: `https://www.kegg.jp/pathway/${row.id}`,
          target: '_blank',
          rel: 'noopener noreferrer',
          class: 'kegg-link',
        },
        '查看 KEGG',
      ),
  },
]

const historyColumns: DataTableColumns<EnrichmentTask> = [
  { title: '项目 ID', key: 'project_name', minWidth: 180, ellipsis: { tooltip: true } },
  { title: '物种', key: 'species_id', width: 145, ellipsis: { tooltip: true } },
  { title: 'Gene 数', key: 'gene_count', width: 90 },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (task) => h(NTag, { size: 'small', type: historyStatusType(task.status) }, { default: () => historyStatusLabel(task.status) }),
  },
  { title: '创建时间', key: 'created_at', width: 175, render: (task) => formatTaskDate(task.created_at) },
  {
    title: '操作',
    key: 'actions',
    width: 210,
    fixed: 'right',
    render: (task) => h(NSpace, { size: 6 }, {
      default: () => [
        h(NButton, {
          size: 'tiny',
          secondary: true,
          disabled: task.status !== 'completed',
          loading: openingHistoryTaskId.value === task.task_id,
          onClick: () => void openHistoryTask(task),
        }, { default: () => '查看结果' }),
        h(NButton, {
          size: 'tiny',
          quaternary: true,
          disabled: task.status !== 'completed',
          onClick: () => void downloadOriginalResult(task),
        }, { default: () => '原始 CSV' }),
      ],
    }),
  },
]

function formatScientific(value: number) {
  if (value === 0) return '0'
  if (value < 0.001 || value >= 10000) return value.toExponential(2)
  return value.toFixed(value < 0.01 ? 4 : 3)
}

function formatTaskDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function historyStatusLabel(status: EnrichmentTask['status']): string {
  return { queued: '排队中', running: '分析中', completed: '已完成', failed: '失败' }[status]
}

function historyStatusType(status: EnrichmentTask['status']): 'default' | 'info' | 'success' | 'error' {
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  return 'default'
}

async function loadSpecies() {
  speciesLoading.value = true
  speciesError.value = ''
  try {
    speciesOptions.value = await fetchSpeciesOptions()
    if (form.speciesId && !selectedSpecies.value) form.speciesId = ''
  } catch (error) {
    speciesError.value = error instanceof Error ? error.message : '无法加载物种配置，请稍后重试。'
  } finally {
    speciesLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    historyTasks.value = await fetchEnrichmentHistory()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '富集历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

// 按任务 id 拉取详情并渲染结果。历史列表「查看结果」与任务中心深链（?taskId=）共用此入口，
// 返回是否成功打开，便于深链在失败时给出提示。
async function openTaskById(taskId: string): Promise<boolean> {
  openingHistoryTaskId.value = taskId
  taskError.value = ''
  try {
    const task = await fetchEnrichmentTask(taskId)
    if (!task.result) throw new Error('历史任务结果不存在')
    stopTaskPolling()
    activeTask.value = task
    result.value = task.result
    form.projectName = task.project_name
    if (speciesOptions.value.some((species) => species.id === task.species_id)) form.speciesId = task.species_id
    await nextTick()
    await renderPlots()
    message.success(`已打开项目：${task.project_name}`)
    return true
  } catch (error) {
    message.error(error instanceof Error ? error.message : '历史结果加载失败')
    return false
  } finally {
    openingHistoryTaskId.value = ''
  }
}

async function openHistoryTask(historyTask: EnrichmentTask) {
  if (historyTask.status !== 'completed') return
  await openTaskById(historyTask.task_id)
}

// 任务中心「查看结果」深链：?taskId= 直达时，等物种配置就绪后直接打开对应任务结果。
async function openDeepLinkedTask() {
  const taskId = route.query[TOOLBOX_RESULT_QUERY]
  if (typeof taskId !== 'string' || !taskId) return
  await loadSpecies()
  await openTaskById(taskId)
}

async function downloadOriginalResult(task: EnrichmentTask) {
  try {
    await downloadEnrichmentResult(task)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '原始结果下载失败')
  }
}

function handleFileChange({ fileList: nextFileList }: { fileList: UploadFileInfo[] }) {
  const latest = nextFileList[nextFileList.length - 1]
  form.geneFile = latest?.file ?? null
}

function clearPlots() {
  if (goPlotContainer.value) Plotly.purge(goPlotContainer.value)
  if (keggPlotContainer.value) Plotly.purge(keggPlotContainer.value)
}

function stopTaskPolling() {
  if (taskPollTimer) clearTimeout(taskPollTimer)
  taskPollTimer = undefined
}

async function loadSample() {
  stopTaskPolling()
  sampleLoading.value = true
  submitting.value = false
  activeTask.value = null
  taskError.value = ''
  try {
    const example = await fetchEnrichmentExample()
    inputMode.value = 'text'
    form.geneText = example.gene_text
    form.geneFile = null
    fileList.value = []
    form.speciesId = example.species_id
    form.projectName = 'COP1-HY5 Example'
    await nextTick()
    form.pValueCutoff = example.p_value_cutoff
    form.qValueCutoff = example.q_value_cutoff
    result.value = example.result
    await nextTick()
    await renderPlots()
    message.success(`已加载 ${example.title}：${example.gene_count} 个 Gene ID 与真实 R 富集结果。`)
  } catch (error) {
    taskError.value = error instanceof Error ? error.message : '示例数据加载失败'
    message.error(taskError.value)
  } finally {
    sampleLoading.value = false
  }
}

function validateCutoffs(): boolean {
  if (!(form.pValueCutoff > 0 && form.pValueCutoff <= 1)) {
    message.warning('p-value cutoff 必须大于 0 且不超过 1')
    return false
  }
  if (!(form.qValueCutoff > 0 && form.qValueCutoff <= 1)) {
    message.warning('q-value cutoff 必须大于 0 且不超过 1')
    return false
  }
  return true
}

const submitBlocker = computed(() => {
  if (speciesError.value) return '物种配置加载失败，请先在物种选择处重试'
  if (!form.projectName.trim()) return '待填写项目 ID'
  if (!form.speciesId) return '待选择物种'
  if (inputMode.value === 'text' && !form.geneText.trim()) return '待输入 Gene ID 列表'
  if (inputMode.value === 'file' && !form.geneFile) return '待上传基因 ID 文件'
  return ''
})
const submitReady = computed(() => !submitBlocker.value)

async function handleSubmit() {
  if (!form.projectName.trim()) {
    message.warning('请输入项目 ID')
    return
  }
  if (!form.speciesId) {
    message.warning('请选择物种')
    return
  }
  if (!validateCutoffs()) return
  if (inputMode.value === 'text' && !form.geneText.trim()) {
    message.warning('请输入 Gene ID 列表')
    return
  }
  if (inputMode.value === 'file' && !form.geneFile) {
    message.warning('请上传基因 ID 文件')
    return
  }

  submitting.value = true
  activeTask.value = null
  taskError.value = ''
  result.value = null
  clearPlots()
  try {
    const payload = new FormData()
    payload.append('project_name', form.projectName.trim())
    payload.append('species_id', form.speciesId)
    payload.append('p_value_cutoff', String(form.pValueCutoff))
    payload.append('q_value_cutoff', String(form.qValueCutoff))
    if (inputMode.value === 'text') {
      payload.append('gene_text', form.geneText)
    } else if (form.geneFile) {
      payload.append('gene_file', form.geneFile)
    }

    const task = await submitEnrichment(payload)
    activeTask.value = task
    await pollEnrichmentTask(task.task_id)
  } catch (error) {
    taskError.value = error instanceof Error ? error.message : '分析任务提交失败'
    message.error(taskError.value)
    submitting.value = false
  }
}

async function pollEnrichmentTask(taskId: string) {
  try {
    const task = await fetchEnrichmentTask(taskId)
    activeTask.value = task
    if (task.status === 'completed' && task.result) {
      result.value = task.result
      submitting.value = false
      await nextTick()
      await renderPlots()
      await loadHistory()
      message.success('GO / KEGG 富集分析完成')
      return
    }
    if (task.status === 'failed') {
      taskError.value = task.error_message || '富集分析失败'
      submitting.value = false
      message.error(taskError.value)
      return
    }
    taskPollTimer = setTimeout(() => {
      void pollEnrichmentTask(taskId)
    }, 1500)
  } catch (error) {
    taskError.value = error instanceof Error ? error.message : '无法查询富集任务状态'
    submitting.value = false
    message.error(taskError.value)
  }
}

async function renderSourcePlot(source: EnrichmentSource, container: HTMLElement | null) {
  if (!container || !result.value) return
  const rows = source === 'GO' ? goRows.value : keggRows.value
  if (!rows.length) {
    Plotly.purge(container)
    return
  }
  const availableWidth = Math.max(container.clientWidth || form.chartWidth, 320)
  const figure = buildEnrichmentPlot(result.value.table_data, source, {
    color: resolveThemeColor(source === 'GO' ? form.goColor : form.keggColor),
    textColor: resolveThemeColor('var(--neutral-text-1)'),
    borderColor: resolveThemeColor('var(--neutral-border)'),
    surfaceColor: resolveThemeColor('var(--neutral-card)'),
    width: Math.min(form.chartWidth, availableWidth),
    height: form.chartHeight,
  })
  const { data, layout } = figure
  if (!Array.isArray(data)) return
  await Plotly.react(
    container,
    data as Plotly.Data[],
    (layout ?? {}) as Partial<Plotly.Layout>,
    {
      responsive: true,
      displaylogo: false,
      displayModeBar: 'hover',
      modeBarButtonsToRemove: ['select2d', 'lasso2d'],
      toImageButtonOptions: { format: 'svg' },
    },
  )
}

function resolveThemeColor(value: string): string {
  const match = value.match(/^var\((--[^)]+)\)$/)
  if (!match) return value
  return getComputedStyle(document.documentElement).getPropertyValue(match[1]).trim() || value
}

async function renderPlots() {
  await Promise.all([
    renderSourcePlot('GO', goPlotContainer.value),
    renderSourcePlot('KEGG', keggPlotContainer.value),
  ])
}

function schedulePlotRender() {
  if (plotRenderTimer) clearTimeout(plotRenderTimer)
  plotRenderTimer = setTimeout(() => {
    void renderPlots()
  }, 200)
}

function exportCsv(rows: EnrichmentRow[], source: 'GO' | 'KEGG' | 'GO_KEGG') {
  if (!rows.length || !result.value) return
  const header = ['Source', 'ID', 'Description', 'GeneRatio', 'pvalue', 'p.adjust', 'qvalue', 'Count']
  const body = rows.map((row) =>
    [
      row.source,
      row.id,
      `"${row.description.replace(/"/g, '""')}"`,
      row.gene_ratio,
      row.pvalue,
      row.p_adjust,
      row.q_value,
      row.count,
    ].join(','),
  )
  const blob = new Blob(['\uFEFF' + [header.join(','), ...body].join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${source.toLowerCase()}_enrichment_${result.value.task_id}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function exportTimestamp(): string {
  const now = new Date()
  const date = [now.getFullYear(), now.getMonth() + 1, now.getDate()].map((value) => String(value).padStart(2, '0')).join('')
  const time = [now.getHours(), now.getMinutes(), now.getSeconds()].map((value) => String(value).padStart(2, '0')).join('')
  return `${date}_${time}`
}

async function exportPlot(source: EnrichmentSource, format: 'png' | 'svg') {
  const container = source === 'GO' ? goPlotContainer.value : keggPlotContainer.value
  const rows = source === 'GO' ? goRows.value : keggRows.value
  if (!container || !rows.length) {
    message.warning(`当前没有可导出的 ${source} 图表`)
    return
  }
  const width = form.exportCustomSize ? form.exportWidth : form.chartWidth
  const height = form.exportCustomSize ? form.exportHeight : form.chartHeight
  const baseName = `${source.toLowerCase()}_enrichment_${exportTimestamp()}`
  try {
    if (format === 'svg') {
      await Plotly.downloadImage(container, { format, width, height, filename: baseName })
      return
    }
    await Plotly.downloadImage(container, {
      format,
      width,
      height,
      scale: exportDpi.value / 96,
      filename: `${baseName}_${exportDpi.value}dpi`,
    } as any)
  } catch {
    message.error(`${source} ${format.toUpperCase()} 导出失败，请稍后重试。`)
  }
}

function handleReset() {
  stopTaskPolling()
  submitting.value = false
  activeTask.value = null
  taskError.value = ''
  form.speciesId = ''
  form.projectName = ''
  form.geneText = ''
  form.geneFile = null
  form.pValueCutoff = 0.05
  form.qValueCutoff = 0.1
  form.goColor = 'var(--kimi-chart-3)'
  form.keggColor = 'var(--kimi-chart-1)'
  form.chartWidth = 960
  form.chartHeight = 480
  form.exportCustomSize = false
  form.exportWidth = 1600
  form.exportHeight = 1000
  exportDpi.value = 300
  fileList.value = []
  inputMode.value = 'text'
  result.value = null
  clearPlots()
}

watch(
  () => form.speciesId,
  () => {
    if (!selectedSpecies.value) return
    form.pValueCutoff = selectedSpecies.value.default_p_value_cutoff
    form.qValueCutoff = selectedSpecies.value.default_q_value_cutoff
  },
)
watch(
  () => [form.goColor, form.keggColor, form.chartWidth, form.chartHeight, themeStore.isDark],
  schedulePlotRender,
)

onMounted(() => {
  void Promise.all([loadSpecies(), loadHistory()]).then(() => openDeepLinkedTask())
})
onBeforeUnmount(() => {
  stopTaskPolling()
  if (plotRenderTimer) clearTimeout(plotRenderTimer)
  clearPlots()
})
</script>

<template>
  <div class="kegg-page">
    <PageHeader
      title="GO / KEGG 富集分析"
      subtitle="提交单列 Gene ID 列表，由 R Docker 中的 clusterProfiler 分别执行 GO 与 KEGG 富集。"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <div class="kegg-layout">
      <aside class="param-panel" aria-label="富集分析参数">
        <NAlert v-if="speciesError" class="species-error" type="error" title="物种配置加载失败" :show-icon="true">
          {{ speciesError }}
        </NAlert>
        <NButton
          v-if="speciesError"
          class="species-retry"
          size="tiny"
          secondary
          type="error"
          :loading="speciesLoading"
          @click="loadSpecies"
        >
          重试加载物种
        </NButton>

        <NForm label-placement="top" :show-feedback="false">
          <NFormItem label="项目 ID" required>
            <div class="project-field">
              <NInput
                v-model:value="form.projectName"
                maxlength="100"
                show-count
                aria-required="true"
                placeholder="例如：Tomato-COP1-HY5"
              />
              <p class="project-path-hint">结果保存到当前用户的 `enrichments/项目 ID/任务 ID/` 目录。</p>
            </div>
          </NFormItem>

          <NFormItem>
            <template #label>
              <span class="label-with-action">
                物种
                <NTooltip placement="top" :delay="300">
                  <template #trigger>
                    <NButton
                      text
                      size="tiny"
                      class="label-refresh"
                      :loading="speciesLoading"
                      aria-label="刷新物种列表"
                      @click="loadSpecies"
                    >
                      <template #icon><NIcon :size="16"><RefreshOutline /></NIcon></template>
                    </NButton>
                  </template>
                  刷新物种列表
                </NTooltip>
              </span>
            </template>
            <NSelect
              v-model:value="form.speciesId"
              :options="speciesSelectOptions"
              placeholder="请选择物种"
              :loading="speciesLoading"
              :disabled="Boolean(speciesError)"
            />
          </NFormItem>

          <NAlert v-if="selectedSpecies" class="species-summary" type="info" :show-icon="false">
            <div class="species-summary-row">
              <span>将执行</span>
              <NTag size="small" type="success">{{ selectedAnalysisTypes }}</NTag>
            </div>
            <span class="species-summary-detail">基因 ID 类型：{{ selectedSpecies.id_type || '由本地参考库识别' }}</span>
          </NAlert>

          <NFormItem>
            <template #label>
              <span class="label-with-action">
                基因 ID 列表
                <NButton text size="tiny" class="sample-link" :loading="sampleLoading" @click="loadSample">
                  <template #icon><NIcon><SparklesOutline /></NIcon></template>
                  试试 COP1/HY5 示例
                </NButton>
              </span>
            </template>
            <NTabs v-model:value="inputMode" type="line" animated>
              <NTabPane name="text" tab="手动输入">
                <NInput
                  v-model:value="form.geneText"
                  type="textarea"
                  :rows="8"
                  placeholder="每行一个 Gene ID，例如：&#10;Solyc02g063527.2&#10;Solyc00g500064.1"
                />
              </NTabPane>
              <NTabPane name="file" tab="上传 CSV / TSV">
                <NUpload
                  v-model:file-list="fileList"
                  :default-upload="false"
                  :max="1"
                  accept=".csv,.tsv"
                  @change="handleFileChange"
                >
                  <NButton block>选择基因列表文件</NButton>
                </NUpload>
                <p class="upload-hint">仅读取第一列 Gene ID；可选首行 `GeneID`，不会解析差异表达统计列。</p>
              </NTabPane>
            </NTabs>
          </NFormItem>

          <div class="parameter-grid" aria-label="显著性阈值">
            <NFormItem label="p-value cutoff">
              <NInputNumber v-model:value="form.pValueCutoff" :min="0.000001" :max="1" :step="0.01" :show-button="false" />
            </NFormItem>
            <NFormItem label="q-value cutoff">
              <NInputNumber v-model:value="form.qValueCutoff" :min="0.000001" :max="1" :step="0.01" :show-button="false" />
            </NFormItem>
          </div>
          <p class="parameter-hint">阈值随任务提交到 clusterProfiler；修改后需要重新提交分析。</p>

          <div class="style-section">
            <h3>图表样式</h3>
            <div class="parameter-grid">
              <NFormItem label="GO 主色">
                <NSelect v-model:value="form.goColor" :options="ENRICHMENT_COLOR_OPTIONS" />
              </NFormItem>
              <NFormItem label="KEGG 主色">
                <NSelect v-model:value="form.keggColor" :options="ENRICHMENT_COLOR_OPTIONS" />
              </NFormItem>
              <NFormItem label="图宽（px）">
                <NInputNumber v-model:value="form.chartWidth" :min="640" :max="1600" :step="40" />
              </NFormItem>
              <NFormItem label="图高（px）">
                <NInputNumber v-model:value="form.chartHeight" :min="360" :max="1000" :step="40" />
              </NFormItem>
            </div>
            <p class="parameter-hint">主色生成连续色阶，颜色深浅表示 -log10(p.adjust)，气泡大小表示 Count；这些设置仅重绘前端 Plotly 图。</p>
          </div>

          <div class="style-section">
            <h3>图片导出</h3>
            <NFormItem label="PNG 分辨率">
              <NSelect v-model:value="exportDpi" :options="exportDpiOptions" />
            </NFormItem>
            <div class="switch-row">
              <span>自定义导出尺寸</span>
              <NSwitch v-model:value="form.exportCustomSize" size="small" />
            </div>
            <div v-if="form.exportCustomSize" class="parameter-grid export-size-grid">
              <NFormItem label="导出宽度（px）">
                <NInputNumber v-model:value="form.exportWidth" :min="100" :max="8000" :step="100" />
              </NFormItem>
              <NFormItem label="导出高度（px）">
                <NInputNumber v-model:value="form.exportHeight" :min="100" :max="8000" :step="100" />
              </NFormItem>
            </div>
            <p class="parameter-hint">PNG 按所选 DPI 输出，SVG 保持矢量；未启用自定义尺寸时沿用当前图宽和图高。</p>
          </div>

          <NButton :disabled="submitting" @click="handleReset">重置</NButton>
        </NForm>
      </aside>

      <main class="result-area" aria-live="polite">
        <NCard class="result-card" :bordered="true">
          <template #header>
            <div class="result-header">
              <div>
                <h2>分析结果</h2>
                <p>GO 与 KEGG 分别展示 Top 20 气泡图和完整统计表。</p>
              </div>
              <NSpace v-if="hasResults" :size="8">
                <NTag v-if="isSampleResult" size="small" type="warning">真实示例结果</NTag>
                <NTag v-if="activeTask?.project_name" size="small" type="info">{{ activeTask.project_name }}</NTag>
                <NButton
                  v-if="activeTask?.status === 'completed'"
                  size="small"
                  secondary
                  @click="downloadOriginalResult(activeTask)"
                >
                  下载容器原始 CSV
                </NButton>
                <NButton size="small" secondary @click="exportCsv(result?.table_data ?? [], 'GO_KEGG')">导出全部 CSV</NButton>
              </NSpace>
            </div>
          </template>

          <NCollapse class="history-section" :default-expanded-names="[]" arrow-placement="left">
            <NCollapseItem :name="'history'" :title="`历史分析结果（${historyTasks.length}）`">
              <template #header-extra>
                <NTooltip :delay="300">
                  <template #trigger>
                    <NButton
                      text
                      size="tiny"
                      class="label-refresh"
                      :loading="historyLoading"
                      aria-label="刷新历史"
                      @click.stop="loadHistory"
                    >
                      <template #icon><NIcon :size="16"><RefreshOutline /></NIcon></template>
                    </NButton>
                  </template>
                  刷新历史
                </NTooltip>
              </template>
              <NDataTable
                :columns="historyColumns"
                :data="historyTasks"
                :loading="historyLoading"
                :row-key="(task) => task.task_id"
                :pagination="{ pageSize: 8 }"
                :scroll-x="900"
                size="small"
              />
              <NEmpty v-if="!historyLoading && !historyTasks.length" size="small" description="当前用户还没有富集分析历史。" />
            </NCollapseItem>
          </NCollapse>

          <div v-if="submitting" class="result-placeholder">
            <NSpin :description="activeTask?.message || '等待 Celery Worker 执行 R 容器任务…'" />
            <p class="task-progress">任务进度 {{ activeTask?.progress ?? 0 }}%</p>
          </div>

          <NAlert v-else-if="taskError" type="error" title="富集任务失败" class="task-error" :show-icon="true">
            {{ taskError }}
          </NAlert>

          <NEmpty
            v-else-if="!result"
            class="result-placeholder"
            description="选择物种并提交单列 Gene ID 列表后，在这里分别查看 GO 与 KEGG 结果。"
          />

          <NEmpty
            v-else-if="!hasResults"
            class="result-placeholder"
            description="未发现满足当前 p-value / q-value 阈值的富集结果。"
          />

          <div v-else class="source-results">
            <section class="source-section" aria-labelledby="go-result-title">
              <div class="source-header">
                <div>
                  <h3 id="go-result-title">GO 富集分析</h3>
                  <p>本地 GO OBO 与注释库，按 p.adjust 排序展示。</p>
                </div>
                <NSpace :size="8">
                  <NTag size="small" type="success">{{ goRows.length }} 条</NTag>
                  <NButton v-if="goRows.length" size="tiny" secondary @click="exportPlot('GO', 'png')">
                    <template #icon><NIcon><DownloadOutline /></NIcon></template>
                    PNG
                  </NButton>
                  <NButton v-if="goRows.length" size="tiny" secondary @click="exportPlot('GO', 'svg')">SVG</NButton>
                  <NButton v-if="goRows.length" size="tiny" secondary @click="exportCsv(goRows, 'GO')">导出 GO CSV</NButton>
                </NSpace>
              </div>
              <NEmpty v-if="!goRows.length" description="当前阈值下没有 GO 富集结果。" />
              <template v-else>
                <div ref="goPlotContainer" class="plot-container" aria-label="GO 富集气泡图" />
                <NDataTable
                  :columns="goColumns"
                  :data="goRows"
                  :row-key="(row) => `GO-${row.id}`"
                  :pagination="{ pageSize: 10 }"
                  :bordered="true"
                  size="small"
                  :scroll-x="900"
                />
              </template>
            </section>

            <section class="source-section" aria-labelledby="kegg-result-title">
              <div class="source-header">
                <div>
                  <h3 id="kegg-result-title">KEGG 富集分析</h3>
                  <p>KEGG 通路独立绘图，并提供通路详情跳转。</p>
                </div>
                <NSpace :size="8">
                  <NTag size="small" type="info">{{ keggRows.length }} 条</NTag>
                  <NButton v-if="keggRows.length" size="tiny" secondary @click="exportPlot('KEGG', 'png')">
                    <template #icon><NIcon><DownloadOutline /></NIcon></template>
                    PNG
                  </NButton>
                  <NButton v-if="keggRows.length" size="tiny" secondary @click="exportPlot('KEGG', 'svg')">SVG</NButton>
                  <NButton v-if="keggRows.length" size="tiny" secondary @click="exportCsv(keggRows, 'KEGG')">导出 KEGG CSV</NButton>
                </NSpace>
              </div>
              <NEmpty v-if="!keggRows.length" description="当前阈值下没有 KEGG 富集结果。" />
              <template v-else>
                <div ref="keggPlotContainer" class="plot-container" aria-label="KEGG 富集气泡图" />
                <NDataTable
                  :columns="keggColumns"
                  :data="keggRows"
                  :row-key="(row) => `KEGG-${row.id}`"
                  :pagination="{ pageSize: 10 }"
                  :bordered="true"
                  size="small"
                  :scroll-x="1000"
                />
              </template>
            </section>

            <NCard size="small" class="column-guide-card" title="结果表字段说明">
              <p class="column-guide-intro">GO 与 KEGG 表采用同一统计字段，便于比较、导出与复现。</p>
              <dl class="column-guide-grid">
                <div v-for="item in resultColumnDescriptions" :key="item.field" class="column-guide-item">
                  <dt>{{ item.field }}</dt>
                  <dd>{{ item.description }}</dd>
                </div>
              </dl>
            </NCard>
          </div>
        </NCard>
      </main>
    </div>

    <ToolActionBar
      :ready="submitReady"
      ready-text="参数已就绪，可提交分析"
      not-ready-text="待完善提交参数"
      :not-ready-tip="submitBlocker"
      primary-label="提交分析"
      :primary-icon="SendOutline"
      :loading="submitting"
      @action="handleSubmit"
    />
  </div>
</template>

<style scoped>
.kegg-page {
  min-height: 100%;
  padding: 16px;
}

.kegg-page :deep(.page-header) {
  margin-bottom: 8px;
}

.kegg-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.param-panel,
.result-card {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
}

.param-panel {
  max-height: calc(100vh - 130px);
  padding: 12px;
  overflow: auto;
}

.species-error,
.task-error {
  margin-bottom: 8px;
}

.species-retry {
  margin-bottom: 12px;
}

.species-summary {
  margin: -2px 0 12px;
}

.species-summary-row,
.result-header,
.source-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.species-summary-row {
  color: var(--neutral-text-2);
  font-size: 12px;
}

.species-summary-detail,
.upload-hint,
.project-path-hint,
.parameter-hint,
.result-header p,
.source-header p {
  display: block;
  margin: 5px 0 0;
  color: var(--neutral-text-3);
  font-size: 12px;
  line-height: 1.5;
}

.project-path-hint {
  margin: 0;
}

.project-field {
  display: grid;
  width: 100%;
  gap: 6px;
}

.parameter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 8px;
}

.parameter-grid :deep(.n-form-item) {
  margin-bottom: 0;
}

.parameter-grid :deep(.n-input-number) {
  width: 100%;
}

.parameter-hint {
  margin: 8px 0 16px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
  margin-bottom: 10px;
  color: var(--neutral-text-2);
  font-size: 13px;
}

.export-size-grid {
  margin-bottom: 8px;
}

.label-with-action {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.label-refresh {
  color: var(--neutral-text-2);
  transition: color 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.label-refresh:hover {
  color: var(--primary-color, #18a058);
}

.label-refresh:hover :deep(.n-icon) {
  animation: kegg-refresh-spin 0.9s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes kegg-refresh-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.sample-link {
  font-weight: 400;
}

.style-section {
  padding-top: 14px;
  margin-top: 4px;
  border-top: 1px solid var(--neutral-border);
}

.style-section h3 {
  margin: 0 0 10px;
  color: var(--neutral-text-1);
  font-size: 13px;
  font-weight: 600;
}

.result-area {
  min-width: 0;
}

.result-card {
  min-height: calc(100vh - 130px);
}

.history-section {
  margin-bottom: 14px;
  padding: 0 2px 12px;
  border-bottom: 1px solid var(--neutral-border);
}

.result-header h2,
.source-header h3 {
  margin: 0;
  color: var(--neutral-text-1);
  font-size: 14px;
  font-weight: 600;
}

.result-placeholder {
  display: grid;
  min-height: 320px;
  place-items: center;
}

.task-progress {
  margin: -116px 0 0;
  color: var(--neutral-text-3);
  font-size: 12px;
}

.source-results {
  display: grid;
  gap: 18px;
}

.source-section {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
}

.source-header {
  margin-bottom: 10px;
}

.source-header :deep(.n-space) {
  justify-content: flex-end;
}

.plot-container {
  width: 100%;
  min-height: 360px;
  margin: 0 auto 14px;
  overflow: hidden;
}

.column-guide-card {
  background: var(--neutral-bg);
}

.column-guide-intro {
  margin: 0 0 12px;
  color: var(--neutral-text-3);
  font-size: 12px;
  line-height: 1.6;
}

.column-guide-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.column-guide-item {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-button);
  background: var(--neutral-card);
}

.column-guide-item dt {
  margin-bottom: 4px;
  color: var(--neutral-text-1);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
}

.column-guide-item dd {
  margin: 0;
  color: var(--neutral-text-2);
  font-size: 12px;
  line-height: 1.6;
}

.kegg-link {
  color: var(--arco-primary);
  font-size: 13px;
}

.kegg-link:hover {
  color: var(--arco-primary-hover);
  text-decoration: underline;
}

.kegg-link:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 3px;
}

@media (max-width: 1100px) {
  .kegg-layout {
    grid-template-columns: 1fr;
  }

  .param-panel,
  .result-card {
    max-height: none;
    min-height: 0;
  }
}

@media (max-width: 640px) {
  .kegg-page {
    padding: 16px;
  }

  .result-header,
  .source-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .parameter-grid {
    grid-template-columns: 1fr;
  }

  .column-guide-grid {
    grid-template-columns: 1fr;
  }

  .plot-container {
    min-height: 320px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .kegg-link {
    transition: none;
  }
}
</style>
