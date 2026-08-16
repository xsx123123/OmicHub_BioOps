<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type ComponentPublicInstance } from 'vue'
import { useRoute } from 'vue-router'
import { TOOLBOX_RESULT_QUERY } from '@/utils/toolboxResultRoute'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NInputNumber,
  NProgress,
  NRadioButton,
  NRadioGroup,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  NTooltip,
  NUpload,
  NUploadDragger,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
  type UploadFileInfo,
} from 'naive-ui'
import {
  CloudUploadOutline,
  DocumentTextOutline,
  DownloadOutline,
  InformationCircleOutline,
  RefreshOutline,
  SendOutline,
  SparklesOutline,
  TimeOutline,
} from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import {
  downloadDegArtifact,
  fetchDegArtifactUrl,
  fetchDegDefaults,
  fetchDegExamples,
  fetchDegHistory,
  fetchDegTask,
  submitDeg,
} from '@/api/deg'
import PageHeader from '@/components/PageHeader.vue'
import ToolActionBar from '@/components/ToolActionBar.vue'
import { useThemeStore } from '@/stores/theme'
import type { DegContrastResult, DegContrastStat, DegGeneRow, DegTask } from '@/types/deg'
import {
  buildVolcanoFigure,
  formatLog2Fc,
  formatScientific,
} from '@/utils/degProcessor'

const message = useMessage()
const themeStore = useThemeStore()
const route = useRoute()
const formRef = ref<FormInst | null>(null)
// 用户是否已尝试提交：提交前不显示任何校验红字，避免一进来就"满屏报错"。
const submitAttempted = ref(false)
// 三个必填文件是否都已就位（示例数据 / 手动上传完成后即 true）。
const allUploadsPresent = computed(
  () => !!form.countsFile && !!form.metadataFile && !!form.pairsFile,
)
// 校验反馈改为「派生」而非「粘性 ref」：仅在提交过 且 仍缺必填文件时显示。
// 这样示例数据/手动上传一旦补齐文件，红字会随响应式自动消失，
// 不再依赖 restoreValidation() 的调用时机（此前为粘性 ref，提交后恒为 true，
// 配合旧构建未执行 restoreValidation 时，载入示例后红字仍残留）。
const showUploadFeedback = computed(() => submitAttempted.value && !allUploadsPresent.value)

// ---------------------------------------------------------------- state
const form = reactive({
  projectName: '',
  method: 'auto' as 'auto' | 'deseq2' | 'edger',
  lfc: 1.0,
  pval: 0.05,
  bcv: 0.4,
  countsFile: null as File | null,
  metadataFile: null as File | null,
  pairsFile: null as File | null,
  annotationFile: null as File | null,
})

const countsFileList = ref<UploadFileInfo[]>([])
const metadataFileList = ref<UploadFileInfo[]>([])
const pairsFileList = ref<UploadFileInfo[]>([])
const annotationFileList = ref<UploadFileInfo[]>([])
const uploadLimits = reactive({
  counts: 200,
  metadata: 5,
  pairs: 5,
  annotation: 50,
  minSamples: 2,
  maxSamples: 500,
  maxContrasts: 50,
  maxGenes: 100_000,
})

const submitting = ref(false)
const activeTask = ref<DegTask | null>(null)
const taskError = ref('')
const historyTasks = ref<DegTask[]>([])
const historyLoading = ref(false)
const exampleLoading = ref(false)
const activeContrast = ref('')
const pcaUrl = ref('')
// 火山图容器：位于对比 v-for（NTabPane）内，不能用单一 ref——
// 在 v-for 里 ref 会被收集成「数组」，直接交给 Plotly 会触发
// `el.getAttribute is not a function`（压缩后 Xt.getAttribute）。
// 改为按对比名登记的回调 ref，渲染时取「当前对比」对应的真实 DOM 节点。
const plotContainers = ref<Record<string, HTMLElement>>({})
function setPlotContainer(name: string) {
  // 参数类型须兼容 Vue 的 VNodeRef（Element | ComponentPublicInstance | null）。
  return (el: Element | ComponentPublicInstance | null) => {
    if (el && el instanceof HTMLElement) plotContainers.value[name] = el
    else delete plotContainers.value[name]
  }
}
let taskPollTimer: ReturnType<typeof setTimeout> | undefined
const objectUrls: string[] = []

const methodOptions = [
  { label: '自动路由', value: 'auto' },
  { label: 'DESeq2', value: 'deseq2' },
  { label: 'edgeR', value: 'edger' },
]

const formRules: FormRules = {
  projectName: [
    { required: true, message: '请填写项目名称', trigger: ['input', 'blur'] },
  ],
  countsFile: [{ required: true, message: '请选择表达矩阵文件', trigger: 'change' }],
  metadataFile: [{ required: true, message: '请选择样本信息表', trigger: 'change' }],
  pairsFile: [{ required: true, message: '请选择比较对文件', trigger: 'change' }],
}

const result = computed(() => activeTask.value?.result ?? null)
const contrasts = computed(() => result.value?.contrasts ?? [])
const currentContrast = computed<DegContrastResult | null>(
  () => contrasts.value.find((c) => c.name === activeContrast.value) ?? null,
)

const submitBlocker = computed(() => {
  if (!form.projectName.trim()) return '待填写项目名称'
  if (!form.countsFile) return '待上传表达矩阵'
  if (!form.metadataFile) return '待上传样本信息表'
  if (!form.pairsFile) return '待上传比较对文件'
  return ''
})
const submitReady = computed(() => !submitBlocker.value)
const isWorking = computed(
  () =>
    activeTask.value?.status === 'queued' ||
    activeTask.value?.status === 'running' ||
    submitting.value,
)

// ---------------------------------------------------------------- tables
const statColumns: DataTableColumns<DegContrastStat> = [
  { title: '比较对', key: 'contrast', width: 150, fixed: 'left' },
  {
    title: '方法',
    key: 'method',
    width: 130,
    render: (row) =>
      row.method
        ? h(NTag, { size: 'small', type: row.method.includes('NoRep') ? 'warning' : 'info' }, { default: () => row.method })
        : h(NTag, { size: 'small', type: 'success' }, { default: () => 'DESeq2' }),
  },
  { title: '对照组', key: 'control', width: 90 },
  { title: '处理组', key: 'treat', width: 90 },
  { title: 'N(ctrl)', key: 'n_control', width: 80 },
  { title: 'N(treat)', key: 'n_treat', width: 80 },
  {
    title: '上调',
    key: 'up_regulated',
    width: 80,
    render: (row) => h('span', { style: `color: #e41749; font-weight: 600` }, String(row.up_regulated)),
  },
  {
    title: '下调',
    key: 'down_regulated',
    width: 80,
    render: (row) => h('span', { style: `color: #41b6e6; font-weight: 600` }, String(row.down_regulated)),
  },
  { title: '差异基因总数', key: 'total_deg', width: 110 },
  {
    title: '离散度假设',
    key: 'dispersion_assumption',
    ellipsis: { tooltip: true },
    minWidth: 160,
  },
]

const geneColumns: DataTableColumns<DegGeneRow> = [
  { title: 'Gene ID', key: 'ensembl', width: 160, fixed: 'left' },
  { title: 'Symbol', key: 'symbol', width: 120, ellipsis: { tooltip: true } },
  {
    title: 'log2FC',
    key: 'log2_fc',
    width: 100,
    sorter: (a, b) => a.log2_fc - b.log2_fc,
    render: (row) => formatLog2Fc(row.log2_fc),
  },
  {
    title: 'P-value',
    key: 'pvalue',
    width: 120,
    sorter: (a, b) => a.pvalue - b.pvalue,
    defaultSortOrder: 'ascend',
    render: (row) => formatScientific(row.pvalue),
  },
  {
    title: 'padj',
    key: 'padj',
    width: 120,
    sorter: (a, b) => (a.padj ?? 1) - (b.padj ?? 1),
    render: (row) => formatScientific(row.padj),
  },
  {
    title: 'baseMean / logCPM',
    key: 'base_mean',
    width: 140,
    render: (row) =>
      row.base_mean !== null
        ? row.base_mean.toFixed(1)
        : row.log_cpm !== null
          ? row.log_cpm.toFixed(2)
          : 'NA',
  },
]

// ---------------------------------------------------------------- helpers
type UploadTarget = 'countsFile' | 'metadataFile' | 'pairsFile' | 'annotationFile'

const uploadTargetLabels: Record<UploadTarget, string> = {
  countsFile: '表达矩阵',
  metadataFile: '样本信息表',
  pairsFile: '比较对文件',
  annotationFile: '基因注释文件',
}

const uploadTargetLimits: Record<UploadTarget, keyof typeof uploadLimits> = {
  countsFile: 'counts',
  metadataFile: 'metadata',
  pairsFile: 'pairs',
  annotationFile: 'annotation',
}

function bindUploadList(target: UploadTarget) {
  return (list: UploadFileInfo[]) => {
    form[target] = list[0]?.file ?? null
    formRef.value?.restoreValidation()
  }
}

function validateUpload(target: UploadTarget) {
  return ({ file }: { file: UploadFileInfo }): boolean => {
    const rawFile = file.file
    if (!rawFile) return false

    const isDelimitedText = /\.(csv|tsv|txt)$/i.test(rawFile.name)
    if (!isDelimitedText) {
      message.error(`${uploadTargetLabels[target]}仅支持 CSV、TSV 或 TXT 文件`)
      return false
    }

    const limit = uploadLimits[uploadTargetLimits[target]]
    if (rawFile.size > limit * 1024 * 1024) {
      message.error(`${uploadTargetLabels[target]}不能超过 ${limit} MB`)
      return false
    }
    return true
  }
}

function fileToUploadInfo(file: File): UploadFileInfo {
  return { id: file.name, name: file.name, status: 'finished', file }
}

async function loadDefaults() {
  try {
    const defaults = await fetchDegDefaults()
    form.method = defaults.method
    form.lfc = defaults.lfc
    form.pval = defaults.pval
    form.bcv = defaults.bcv
    uploadLimits.counts = defaults.max_counts_file_size_mb
    uploadLimits.metadata = defaults.max_metadata_file_size_mb
    uploadLimits.pairs = defaults.max_pairs_file_size_mb
    uploadLimits.annotation = defaults.max_annotation_file_size_mb
    uploadLimits.minSamples = defaults.min_samples
    uploadLimits.maxSamples = defaults.max_samples
    uploadLimits.maxContrasts = defaults.max_contrasts
    uploadLimits.maxGenes = defaults.max_genes
  } catch {
    // 默认值加载失败时保留页面内置默认，不打扰用户
  }
}

async function loadExample() {
  exampleLoading.value = true
  try {
    const examples = await fetchDegExamples()
    const mk = (key: string, name: string) =>
      examples[key] ? new File([examples[key]], name, { type: 'text/csv' }) : null
    form.countsFile = mk('counts', 'counts.csv')
    form.metadataFile = mk('metadata', 'metadata.csv')
    form.pairsFile = mk('pairs', 'pairs.csv')
    form.annotationFile = mk('annotation', 'annotation.csv')
    countsFileList.value = form.countsFile ? [fileToUploadInfo(form.countsFile)] : []
    metadataFileList.value = form.metadataFile ? [fileToUploadInfo(form.metadataFile)] : []
    pairsFileList.value = form.pairsFile ? [fileToUploadInfo(form.pairsFile)] : []
    annotationFileList.value = form.annotationFile ? [fileToUploadInfo(form.annotationFile)] : []
    if (!form.projectName.trim()) form.projectName = 'DEG Demo'
    // 程序化填入与手动上传走同一契约：清除遗留校验错误（此前缺这步，示例载入后红字仍在）
    formRef.value?.restoreValidation()
    message.success('已载入示例数据（含 3v3 与 1v1 两个比较对）')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '示例数据加载失败')
  } finally {
    exampleLoading.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    historyTasks.value = await fetchDegHistory(30)
  } catch {
    // 历史加载失败不阻塞主流程
  } finally {
    historyLoading.value = false
  }
}

async function handleSubmit() {
  // 数据已齐备（示例数据 / 手动上传填满了全部必填项）时直接提交：
  // 不再被 naive-ui validate() 的不透明 reject 阻塞——此前示例载入后所有必填项
  // 其实都已就位，但 validate() 偶发 reject 会弹出笼统的"请完善必填信息"，无法提交。
  if (submitReady.value) {
    submitAttempted.value = true
    // 仍异步触发一次校验以同步表单视觉态；失败也不阻断已齐备的提交。
    void formRef.value?.validate().catch(() => {})
  } else {
    // 确有缺失：标记"已尝试提交"以派生行内红字，并跑校验拿到具体缺项。
    submitAttempted.value = true
    try {
      await formRef.value?.validate()
    } catch (e) {
      const errs = (e as { errors?: Array<{ field?: string; message?: string }> } | null)?.errors ?? []
      const missing = errs.map((err) => err.message).filter(Boolean)
      // 诊断日志：把真实校验失败项打到控制台，便于排查"为何被拦"。
      console.warn('[DEG] 表单校验未通过：', errs)
      message.warning(missing.length ? `请完善：${missing.join('、')}` : submitBlocker.value || '请完善必填信息后再提交')
    }
    return
  }
  submitting.value = true
  activeTask.value = null
  taskError.value = ''
  revokeObjectUrls()
  try {
    const payload = new FormData()
    payload.append('project_name', form.projectName.trim())
    payload.append('method', form.method)
    payload.append('lfc', String(form.lfc))
    payload.append('pval', String(form.pval))
    payload.append('bcv', String(form.bcv))
    payload.append('counts_file', form.countsFile as File)
    payload.append('metadata_file', form.metadataFile as File)
    payload.append('pairs_file', form.pairsFile as File)
    if (form.annotationFile) payload.append('annotation_file', form.annotationFile)

    const task = await submitDeg(payload)
    activeTask.value = task
    message.info(task.message || '任务已提交')
    await pollDegTask(task.task_id)
  } catch (error) {
    taskError.value = extractError(error) || 'DEG 分析任务提交失败'
    message.error(taskError.value)
    submitting.value = false
  }
}

async function pollDegTask(taskId: string) {
  try {
    const task = await fetchDegTask(taskId)
    activeTask.value = task
    if (task.status === 'completed' && task.result) {
      submitting.value = false
      activeContrast.value = task.result.contrasts[0]?.name ?? ''
      await loadPca(task)
      await nextTick()
      renderVolcano()
      await loadHistory()
      message.success(`DEG 分析完成（引擎：${task.result.engine.toUpperCase()}）`)
      return
    }
    if (task.status === 'failed') {
      taskError.value = task.error_message || 'DEG 分析失败'
      submitting.value = false
      message.error(taskError.value)
      return
    }
    taskPollTimer = setTimeout(() => void pollDegTask(taskId), 2000)
  } catch (error) {
    taskError.value = extractError(error) || '无法查询 DEG 任务状态'
    submitting.value = false
    message.error(taskError.value)
  }
}

async function openHistoryTask(task: DegTask) {
  // 历史列表(/deg/tasks)为精简 DTO，不含 result（后端"结果按需通过任务详情加载"）。
  // 故须用详情接口(/deg/tasks/{id})重新拉取，否则已完成任务也渲染不出统计/PCA/火山图。
  // 先置 activeTask 让工作区与高亮即时出现，再异步补全详情。
  activeTask.value = task
  taskError.value = task.status === 'failed' ? task.error_message || 'DEG 分析失败' : ''
  if (task.status !== 'completed') {
    message.info('该任务未完成，仅可查看状态')
    return
  }
  let detail = task
  if (!task.result) {
    try {
      detail = await fetchDegTask(task.task_id)
      // 竞态保护：拉取期间用户若已切到别的任务，则放弃本次渲染。
      if (activeTask.value?.task_id !== task.task_id) return
      activeTask.value = detail
    } catch (error) {
      taskError.value = extractError(error) || '加载历史结果失败'
      message.error(taskError.value)
      return
    }
  }
  if (detail.result) {
    activeContrast.value = detail.result.contrasts[0]?.name ?? ''
    await loadPca(detail)
    await nextTick()
    renderVolcano()
  }
}

// 任务中心「查看结果」深链：?taskId= 直达时，拉取详情后复用历史结果打开流程。
async function openDeepLinkedTask() {
  const taskId = route.query[TOOLBOX_RESULT_QUERY]
  if (typeof taskId !== 'string' || !taskId) return
  try {
    const detail = await fetchDegTask(taskId)
    await openHistoryTask(detail)
  } catch (error) {
    taskError.value = extractError(error) || '加载历史结果失败'
    message.error(taskError.value)
  }
}

async function loadPca(task: DegTask) {
  revokeObjectUrls()
  const pca = task.result?.pca_png
  if (!pca) return
  try {
    const url = await fetchDegArtifactUrl(task.task_id, pca)
    objectUrls.push(url)
    pcaUrl.value = url
  } catch {
    pcaUrl.value = ''
  }
}

function renderVolcano() {
  const contrast = currentContrast.value
  const el = contrast ? plotContainers.value[contrast.name] : undefined
  if (!el || !contrast) return
  const figure = buildVolcanoFigure(contrast.top_genes, {
    contrastName: contrast.name,
    pvalCutoff: form.pval,
    lfcCutoff: form.lfc,
    isDark: themeStore.isDark,
  })
  Plotly.react(el, figure.data, figure.layout, figure.config)
}

watch(
  () => [activeContrast.value, form.pval, form.lfc] as const,
  () => {
    if (result.value) nextTick(renderVolcano)
  },
)
watch(
  () => themeStore.isDark,
  () => {
    if (result.value) nextTick(renderVolcano)
  },
)

async function download(filename: string) {
  if (!activeTask.value || !filename) return
  try {
    await downloadDegArtifact(activeTask.value, filename)
  } catch (error) {
    message.error(extractError(error) || `下载失败：${filename}`)
  }
}

function revokeObjectUrls() {
  for (const url of objectUrls.splice(0)) URL.revokeObjectURL(url)
  pcaUrl.value = ''
}

function extractError(error: unknown): string {
  if (error instanceof Error) return error.message
  const anyErr = error as { response?: { data?: { detail?: string; message?: string } } }
  return anyErr?.response?.data?.detail || anyErr?.response?.data?.message || ''
}

function statusTagType(status: string): 'default' | 'info' | 'success' | 'error' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'running') return 'info'
  return 'warning'
}

onMounted(() => {
  void Promise.all([loadDefaults(), loadHistory()]).then(() => openDeepLinkedTask())
})

onBeforeUnmount(() => {
  if (taskPollTimer) clearTimeout(taskPollTimer)
  for (const el of Object.values(plotContainers.value)) Plotly.purge(el)
  plotContainers.value = {}
  revokeObjectUrls()
})
</script>

<template>
  <div class="deg-analysis-page" role="main" aria-label="DEG 差异表达分析">
    <PageHeader
      title="DEG 差异表达分析"
      subtitle="DESeq2 / edgeR 双引擎，无生物学重复（1v1）样本自动切换 edgeR"
      back-to="/tools"
      back-label="返回工具箱"
    />

    <NForm ref="formRef" :model="form" :rules="formRules">
      <section class="project-name-card" aria-labelledby="deg-project-name">
        <div class="project-name-card__copy">
          <span class="project-name-card__eyebrow">分析项目</span>
          <h2 id="deg-project-name">为本次差异表达分析命名</h2>
          <p>项目名称将用于任务历史和结果文件的识别。</p>
        </div>
        <NFormItem path="projectName" :show-feedback="showUploadFeedback" class="project-name-card__input">
          <NInput v-model:value="form.projectName" size="large" placeholder="例如：水稻 drought vs control" />
        </NFormItem>
      </section>

      <main class="deg-analysis-layout">
        <!-- ======================= 左：参数列 ======================= -->
        <aside class="param-panel" aria-label="DEG 分析输入与参数">
          <NCollapse arrow-placement="left" :default-expanded-names="['data', 'params']">
          <NCollapseItem title="数据输入" name="data">
            <template #header-extra>
              <NButton text size="tiny" :loading="exampleLoading" @click.stop="loadExample">
                <template #icon><NIcon><SparklesOutline /></NIcon></template>
                试试示例数据
              </NButton>
            </template>
            <div class="data-input-intro">
              <NIcon size="18" aria-hidden="true"><DocumentTextOutline /></NIcon>
              <p>按顺序选择 3 个必填表；系统会在提交前核对样本、分组与比较对是否一致。</p>
            </div>

            <NFormItem path="countsFile" :show-feedback="showUploadFeedback">
              <div class="file-field">
                <div class="file-field__heading">
                  <span>1. 表达矩阵 <em>必填</em></span>
                  <span class="file-field__limit">≤ {{ uploadLimits.counts }} MB</span>
                </div>
                <NUpload
                  v-model:file-list="countsFileList"
                  :default-upload="false"
                  :max="1"
                  accept=".csv,.tsv,.txt"
                  :on-before-upload="validateUpload('countsFile')"
                  @update:file-list="bindUploadList('countsFile')"
                >
                  <NUploadDragger class="file-picker">
                    <div class="file-picker__content">
                      <NIcon size="22" aria-hidden="true"><CloudUploadOutline /></NIcon>
                      <strong>{{ form.countsFile ? form.countsFile.name : '点击选择或拖入 Raw Counts 文件' }}</strong>
                      <span>CSV / TSV / TXT · 首列为 GeneID，后续每列为样本名</span>
                    </div>
                  </NUploadDragger>
                </NUpload>
                <p class="file-field__help">仅接受整数 Raw Counts；样本列名须与样本信息表的 Sample 完全对应。</p>
              </div>
            </NFormItem>

            <NFormItem path="metadataFile" :show-feedback="showUploadFeedback">
              <div class="file-field">
                <div class="file-field__heading">
                  <span>2. 样本信息表 <em>必填</em></span>
                  <span class="file-field__limit">≤ {{ uploadLimits.metadata }} MB</span>
                </div>
                <NUpload
                  v-model:file-list="metadataFileList"
                  :default-upload="false"
                  :max="1"
                  accept=".csv,.tsv,.txt"
                  :on-before-upload="validateUpload('metadataFile')"
                  @update:file-list="bindUploadList('metadataFile')"
                >
                  <NUploadDragger class="file-picker">
                    <div class="file-picker__content">
                      <NIcon size="22" aria-hidden="true"><CloudUploadOutline /></NIcon>
                      <strong>{{ form.metadataFile ? form.metadataFile.name : '点击选择或拖入样本信息表' }}</strong>
                      <span>CSV / TSV / TXT · 必需列：Sample、Group</span>
                    </div>
                  </NUploadDragger>
                </NUpload>
                <p class="file-field__help">每行对应一个样本；至少 {{ uploadLimits.minSamples }} 个有效样本，最多 {{ uploadLimits.maxSamples }} 个。</p>
              </div>
            </NFormItem>

            <NFormItem path="pairsFile" :show-feedback="showUploadFeedback">
              <div class="file-field">
                <div class="file-field__heading">
                  <span>3. 比较对文件 <em>必填</em></span>
                  <span class="file-field__limit">≤ {{ uploadLimits.pairs }} MB</span>
                </div>
                <NUpload
                  v-model:file-list="pairsFileList"
                  :default-upload="false"
                  :max="1"
                  accept=".csv,.tsv,.txt"
                  :on-before-upload="validateUpload('pairsFile')"
                  @update:file-list="bindUploadList('pairsFile')"
                >
                  <NUploadDragger class="file-picker">
                    <div class="file-picker__content">
                      <NIcon size="22" aria-hidden="true"><CloudUploadOutline /></NIcon>
                      <strong>{{ form.pairsFile ? form.pairsFile.name : '点击选择或拖入比较对文件' }}</strong>
                      <span>CSV / TSV / TXT · 必需列：Treat、Control</span>
                    </div>
                  </NUploadDragger>
                </NUpload>
                <p class="file-field__help">每行定义一组 Treat vs Control；分组名称必须已在样本信息表中出现（最多 {{ uploadLimits.maxContrasts }} 组）。</p>
              </div>
            </NFormItem>

            <NFormItem path="annotationFile" :show-feedback="false">
              <div class="file-field">
                <div class="file-field__heading">
                  <span>4. 基因注释 <em class="file-field__optional">可选</em></span>
                  <span class="file-field__limit">≤ {{ uploadLimits.annotation }} MB</span>
                </div>
                <NUpload
                  v-model:file-list="annotationFileList"
                  :default-upload="false"
                  :max="1"
                  accept=".csv,.tsv,.txt"
                  :on-before-upload="validateUpload('annotationFile')"
                  @update:file-list="bindUploadList('annotationFile')"
                >
                  <NUploadDragger class="file-picker">
                    <div class="file-picker__content">
                      <NIcon size="22" aria-hidden="true"><CloudUploadOutline /></NIcon>
                      <strong>{{ form.annotationFile ? form.annotationFile.name : '点击选择或拖入注释文件' }}</strong>
                      <span>CSV / TSV / TXT · 首列为基因 ID，可附加 Symbol 等列</span>
                    </div>
                  </NUploadDragger>
                </NUpload>
                <p class="file-field__help">注释会合并到结果表；不上传时仍可完成分析。表达矩阵最多 {{ uploadLimits.maxGenes }} 行基因。</p>
              </div>
            </NFormItem>
          </NCollapseItem>

          <NCollapseItem title="分析参数" name="params">
            <NFormItem label="分析方法" label-placement="top" :show-feedback="false">
              <NRadioGroup v-model:value="form.method" size="small">
                <NRadioButton v-for="opt in methodOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </NRadioButton>
              </NRadioGroup>
            </NFormItem>
            <NAlert v-if="form.method !== 'deseq2'" type="info" :bordered="false" style="margin: 8px 0">
              任一比较组无生物学重复（1v1）时，edgeR 以预设 BCV 运行 exactTest；
              有重复的比较组走标准 QL F-test。1v1 结果属探索性，建议补重复复验。
            </NAlert>
            <NAlert v-else type="warning" :bordered="false" style="margin: 8px 0">
              强制 DESeq2：若存在 1v1 比较组，提交时会被拒绝（DESeq2 无法估计离散度）。
            </NAlert>
            <NFormItem label="|log2FC| 阈值" label-placement="left" :show-feedback="false">
              <NInputNumber v-model:value="form.lfc" :min="0" :step="0.25" :show-button="false" size="small" style="width: 100%" />
            </NFormItem>
            <NFormItem label="P-value 阈值" label-placement="left" :show-feedback="false">
              <NInputNumber v-model:value="form.pval" :min="0.0001" :max="1" :step="0.01" :show-button="false" size="small" style="width: 100%" />
            </NFormItem>
            <NFormItem label-placement="left" :show-feedback="false">
              <template #label>
                BCV（edgeR 无重复模式）
                <NTooltip trigger="hover">
                  <template #trigger>
                    <span class="param-help">?</span>
                  </template>
                  生物学变异系数：0.4 人/异质样本（默认）、0.1 建系/模式生物、0.01 技术重复
                </NTooltip>
              </template>
              <NInputNumber v-model:value="form.bcv" :min="0.01" :max="2" :step="0.1" :show-button="false" size="small" :disabled="form.method === 'deseq2'" style="width: 100%" />
            </NFormItem>
          </NCollapseItem>
          </NCollapse>
        </aside>

        <aside class="side-column" aria-label="分析说明与历史记录">
          <section class="work-card guide-card" aria-labelledby="deg-guide-title">
            <div class="card-header">
              <div class="card-title-with-icon">
                <NIcon :size="18" aria-hidden="true"><InformationCircleOutline /></NIcon>
                <h3 id="deg-guide-title">分析说明</h3>
              </div>
            </div>
            <ol class="guide-list">
              <li>上传 Raw Counts、样本信息和比较对文件。</li>
              <li>选择阈值；自动路由会按重复数选择 DESeq2 或 edgeR。</li>
              <li>提交后可在此查看进度、统计表、PCA 与火山图。</li>
            </ol>
          </section>

          <section class="work-card history-card" aria-labelledby="deg-history-title">
            <div class="card-header">
              <div class="card-title-with-icon">
                <NIcon :size="18" aria-hidden="true"><TimeOutline /></NIcon>
                <h3 id="deg-history-title">历史分析</h3>
              </div>
              <NButton text size="tiny" aria-label="刷新历史分析" :loading="historyLoading" @click="loadHistory">
                <template #icon><NIcon><RefreshOutline /></NIcon></template>
              </NButton>
            </div>
            <div v-if="!historyTasks.length && !historyLoading" class="history-empty">暂无历史分析</div>
            <button
              v-for="task in historyTasks"
              :key="task.task_id"
              class="history-item"
              :class="{ active: activeTask?.task_id === task.task_id }"
              type="button"
              @click="openHistoryTask(task)"
            >
              <span class="history-name">{{ task.project_name || 'DEG Project' }}</span>
              <NTag :type="statusTagType(task.status)" size="small" :bordered="false">
                {{ task.status === 'completed' ? `完成 · ${task.engine_resolved?.toUpperCase() ?? ''}` : task.status }}
              </NTag>
            </button>
          </section>

          <section v-if="!activeTask && !taskError" class="work-card empty-card submit-guide-card" aria-label="提交分析提示">
          <NEmpty description="上传数据后点击「提交分析」运行差异表达分析">
            <template #extra>
              <p class="empty-hint">
                支持 DESeq2（有生物学重复）与 edgeR（1v1 无重复）；方法选「自动路由」时按比较组重复数自动选择引擎。
              </p>
            </template>
          </NEmpty>
          </section>
        </aside>
      </main>

      <!-- ======================= 分析工作区 ======================= -->
      <section v-if="activeTask || taskError" class="work-area">
        <!-- 失败 -->
        <NAlert v-if="taskError" type="error" :title="activeTask?.status === 'failed' ? 'DEG 分析失败' : '出错了'" style="margin-bottom: 16px">
          <pre class="error-pre">{{ taskError }}</pre>
        </NAlert>

        <!-- 进行中 -->
        <div v-if="isWorking" class="work-card progress-card">
          <NSpin size="small" />
          <div class="progress-info">
            <p class="progress-message">{{ activeTask?.message || '正在提交任务…' }}</p>
            <NProgress
              type="line"
              :percentage="activeTask?.progress ?? 0"
              :show-indicator="true"
              :height="10"
              :border-radius="5"
            />
            <p v-if="activeTask?.engine_resolved" class="progress-engine">
              引擎：{{ activeTask.engine_resolved.toUpperCase() }}
              <template v-if="activeTask.no_replicate_contrasts.length">
                ｜ 无重复比较对：{{ activeTask.no_replicate_contrasts.join('、') }}
              </template>
            </p>
          </div>
        </div>

        <!-- 结果 -->
        <template v-if="result">
          <!-- 统计汇总 -->
          <div class="work-card">
            <div class="card-header">
              <h3>差异基因统计汇总</h3>
              <NSpace size="small">
                <NButton size="tiny" secondary @click="download('All_Contrast_DEG_Statistics.csv')">
                  <template #icon><NIcon><DownloadOutline /></NIcon></template>
                  统计表 CSV
                </NButton>
                <NButton v-if="result.log_file" size="tiny" secondary @click="download(result.log_file)">
                  运行日志
                </NButton>
              </NSpace>
            </div>
            <NDataTable
              :columns="statColumns"
              :data="result.statistics"
              :pagination="false"
              size="small"
              :scroll-x="1100"
              :bordered="false"
            />
          </div>

          <!-- PCA -->
          <div v-if="pcaUrl" class="work-card">
            <div class="card-header">
              <h3>全局 PCA（所有样本）</h3>
              <NButton size="tiny" secondary @click="download(result.pca_png)">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                PNG
              </NButton>
            </div>
            <img :src="pcaUrl" alt="Global PCA" class="pca-image" />
          </div>

          <!-- 每比较对结果 -->
          <div class="work-card">
            <NTabs v-model:value="activeContrast" type="line" size="small">
              <NTabPane v-for="contrast in contrasts" :key="contrast.name" :name="contrast.name" :tab="contrast.name">
                <div class="contrast-toolbar">
                  <NSpace size="small">
                    <NButton size="tiny" secondary :disabled="!contrast.deg_csv" @click="download(contrast.deg_csv)">
                      <template #icon><NIcon><DownloadOutline /></NIcon></template>
                      全量 DEG CSV（{{ contrast.total_genes }} 行）
                    </NButton>
                    <NButton size="tiny" secondary :disabled="!contrast.volcano_labeled_png" @click="download(contrast.volcano_labeled_png)">
                      火山图（标注版 PNG）
                    </NButton>
                    <NButton size="tiny" secondary :disabled="!contrast.volcano_png" @click="download(contrast.volcano_png)">
                      火山图（简洁版 PNG）
                    </NButton>
                  </NSpace>
                  <span v-if="contrast.stat.method === 'edgeR-NoRep'" class="norep-badge">
                    ⚠ 无重复 1v1 · {{ contrast.stat.dispersion_assumption }} · 探索性结果
                  </span>
                </div>
                <div class="plot-card">
                  <div :ref="setPlotContainer(contrast.name)" class="plot-container" />
                </div>
                <NDataTable
                  :columns="geneColumns"
                  :data="contrast.top_genes"
                  :pagination="{ pageSize: 20 }"
                  size="small"
                  :scroll-x="840"
                  :bordered="false"
                  style="margin-top: 12px"
                />
                <p class="table-note">
                  表格展示按 P-value 排序的前 {{ contrast.top_genes.length }} 个基因（共 {{ contrast.total_genes }} 行），完整结果请下载 CSV。
                </p>
              </NTabPane>
            </NTabs>
          </div>
        </template>
      </section>
    </NForm>

    <ToolActionBar
      :ready="submitReady"
      :loading="isWorking"
      ready-text="参数已就绪"
      :not-ready-text="submitBlocker || '待完善必填参数'"
      :not-ready-tip="submitBlocker"
      primary-label="提交分析"
      :primary-icon="SendOutline"
      @action="handleSubmit"
    />
  </div>
</template>

<style scoped>
.deg-analysis-page {
  min-height: 100%;
  padding: 40px 24px 24px;
  box-sizing: border-box;
}

.deg-analysis-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
  align-items: start;
}

.project-name-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 480px);
  gap: 24px;
  align-items: center;
  margin-bottom: 16px;
  padding: 20px;
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: var(--radius-card, 12px);
  background: var(--neutral-card, #fff);
}

.project-name-card__eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--primary-color, var(--arco-primary));
  font-size: var(--font-micro-size);
  font-weight: 600;
  line-height: var(--font-micro-height);
  letter-spacing: 0.06em;
}

.project-name-card__copy h2 {
  margin: 0;
  color: var(--neutral-text-1, #1d2129);
  font-size: 18px;
  font-weight: 600;
  line-height: 1.45;
}

.project-name-card__copy p {
  margin: 6px 0 0;
  color: var(--neutral-text-3, #86909c);
  font-size: 12px;
  line-height: 1.6;
}

.project-name-card__input {
  margin: 0;
}

.param-panel,
.work-card {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 12px;
}

.param-panel {
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}

.param-panel :deep(.n-collapse-item__header) {
  font-size: 13px;
  font-weight: 600;
}

.param-panel :deep(.n-form-item) {
  margin-bottom: var(--space-md);
}

.data-input-intro {
  display: flex;
  gap: var(--space-sm);
  align-items: flex-start;
  padding: var(--space-sm) var(--space-md);
  margin-bottom: var(--space-lg);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
  color: var(--neutral-text-2);
  font-size: var(--font-caption-size);
  line-height: var(--font-caption-height);
}

.data-input-intro :deep(.n-icon) {
  flex: 0 0 auto;
  color: var(--primary-color, var(--arco-primary));
}

.data-input-intro p,
.file-field__help {
  margin: 0;
}

.file-field {
  width: 100%;
}

.file-field__heading {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-xs);
  color: var(--neutral-text-1);
  font-size: var(--font-small-size);
  font-weight: 600;
  line-height: var(--font-small-height);
}

.file-field__heading em {
  margin-left: var(--space-xs);
  color: var(--error-color, var(--arco-danger));
  font-size: var(--font-micro-size);
  font-style: normal;
  font-weight: 500;
}

.file-field__heading .file-field__optional {
  color: var(--neutral-text-3);
}

.file-field__limit {
  flex: 0 0 auto;
  color: var(--neutral-text-3);
  font-size: var(--font-micro-size);
  font-weight: 400;
}

.file-picker {
  min-height: 0;
  padding: var(--space-sm) var(--space-md);
}

/* 紧凑单行拖拽区：图标 + 文件名 + 格式说明一行排列，避免大面积空荡的居中大框 */
.file-picker.file-picker {
  display: flex;
  align-items: center;
  text-align: left;
}

.file-picker__content {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
  justify-content: flex-start;
  width: 100%;
  color: var(--neutral-text-3);
}

.file-picker__content span {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-picker__content :deep(.n-icon) {
  color: var(--primary-color, var(--arco-primary));
}

.file-picker__content strong {
  max-width: 100%;
  overflow: hidden;
  color: var(--neutral-text-1);
  font-size: var(--font-caption-size);
  font-weight: 500;
  line-height: var(--font-caption-height);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-picker__content span,
.file-field__help {
  color: var(--neutral-text-3);
  font-size: var(--font-micro-size);
  line-height: var(--font-micro-height);
}

.file-field__help {
  margin-top: var(--space-xs);
}

.file-field :deep(.n-upload-file-list) {
  margin-top: var(--space-sm);
}

.param-help {
  display: inline-block;
  margin-left: 4px;
  width: 14px;
  height: 14px;
  line-height: 14px;
  text-align: center;
  border-radius: 50%;
  background: var(--neutral-border, #e5e6eb);
  color: var(--neutral-text-2, #4e5969);
  font-size: 10px;
  cursor: help;
}

.work-area {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 16px;
}

.side-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.card-title-with-icon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.card-title-with-icon :deep(.n-icon) {
  color: var(--primary-color, var(--arco-primary));
}

.guide-card {
  padding: 16px;
}

.guide-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 20px;
  color: var(--neutral-text-2, #4e5969);
  font-size: 12px;
  line-height: 1.6;
}

.history-card {
  padding: 16px 12px 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.card-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}

.empty-card {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.submit-guide-card {
  padding: 20px;
  text-align: center;
}

.empty-hint {
  max-width: 420px;
  color: var(--neutral-text-3, #86909c);
  font-size: 12px;
  line-height: 1.6;
}

.progress-card {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 20px;
}

.progress-info {
  flex: 1;
  min-width: 0;
}

.progress-message {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--neutral-text-1, #1d2129);
}

.progress-engine {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}

.error-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 12px;
  max-height: 240px;
  overflow-y: auto;
}

.pca-image {
  display: block;
  max-width: 100%;
  border-radius: 8px;
}

.contrast-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.norep-badge {
  font-size: 12px;
  color: #d46b08;
}

.plot-card {
  position: relative;
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
  padding: 8px;
}

.plot-container {
  width: 100%;
  height: 480px;
}

.table-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}

.history-empty {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  padding: 8px 0;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px;
  margin-bottom: 4px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: background 320ms cubic-bezier(0.16, 1, 0.3, 1);
}

.history-item:hover {
  background: var(--neutral-bg, #f5f6f7);
}

.history-item.active {
  border-color: var(--arco-primary, #165dff);
  background: var(--arco-primary-light, rgba(22, 93, 255, 0.08));
}

.history-name {
  font-size: 12px;
  color: var(--neutral-text-1, #1d2129);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1200px) {
  .deg-analysis-layout {
    grid-template-columns: 1fr;
  }
  .param-panel {
    max-height: none;
  }

  .side-column {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .submit-guide-card {
    grid-column: 1 / -1;
  }
}

@media (max-width: 768px) {
  .deg-analysis-page {
    padding: 24px 12px 16px;
  }

  .project-name-card,
  .side-column {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .project-name-card {
    align-items: stretch;
    padding: 16px;
  }

  .project-name-card__input {
    width: 100%;
  }
}
</style>
