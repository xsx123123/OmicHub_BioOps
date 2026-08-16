<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  NAlert, NButton, NCollapse, NCollapseItem, NDataTable, NEmpty, NIcon, NInput, NInputNumber,
  NProgress, NRadioButton, NRadioGroup, NSelect, NSpin, NSwitch, NTag, NUpload, useMessage,
  type UploadFileInfo,
} from 'naive-ui'
import {
  BuildOutline, DownloadOutline, ExpandOutline, SearchOutline, SparklesOutline,
} from '@vicons/ionicons5'
import { useThemeStore } from '@/stores/theme'
import PageHeader from '@/components/PageHeader.vue'
import {
  cancelTask, downloadTreeResult, fetchPhyloMethods, getTaskResult, getTaskStatus, submitTreeBuild,
  uploadSequenceFile,
} from '@/api/phylo'
import type {
  PhyloMethodOption, PhyloMethodsResponse, PhyloSubmitRequest, PhyloTaskResponse, SequenceType,
  TreeLayout, TreeStatistics,
} from '@/types/phylo'
import {
  computeTreeStatistics, createRenderOptions, downloadBlob, parseNewick,
  PhyloTreeRenderer, svgToPng,
} from '@/utils/phyloProcessor'

const message = useMessage()
const themeStore = useThemeStore()

const POLLING_INTERVAL = 2000
const MAX_POLL_FAILURES = 5

const EXAMPLE_NEWICK = `((((Homo_sapiens:0.004,Pan_troglodytes:0.005)99:0.012,Gorilla_gorilla:0.018)96:0.025,(Pongo_abelii:0.030,Macaca_mulatta:0.045)92:0.020)98:0.040,(((Mus_musculus:0.080,Rattus_norvegicus:0.075)97:0.030,(Oryctolagus_cuniculus:0.065,Cavia_porcellus:0.070)88:0.025)90:0.035,((Canis_lupus:0.055,Felis_catus:0.050)94:0.028,(Bos_taurus:0.045,(Ovis_aries:0.035,Capra_hircus:0.032)98:0.015)91:0.030)93:0.040)95:0.035,(((Equus_caballus:0.052,Sus_scrofa:0.058)89:0.038,(Loxodonta_africana:0.075,Trichechus_manatus:0.080)87:0.040)90:0.045,((Monodelphis_domestica:0.120,Ornithorhynchus_anatinus:0.160)85:0.060,Gallus_gallus:0.220)80:0.070)88:0.050)100;`

const EXAMPLE_SEQUENCES = [
  ['Homo_sapiens', 1542], ['Pan_troglodytes', 1540], ['Gorilla_gorilla', 1538],
  ['Pongo_abelii', 1544], ['Macaca_mulatta', 1536], ['Mus_musculus', 1518],
  ['Rattus_norvegicus', 1521], ['Oryctolagus_cuniculus', 1530], ['Cavia_porcellus', 1512],
  ['Canis_lupus', 1548], ['Felis_catus', 1545], ['Bos_taurus', 1539],
  ['Ovis_aries', 1537], ['Capra_hircus', 1537], ['Equus_caballus', 1541],
  ['Sus_scrofa', 1535], ['Loxodonta_africana', 1552], ['Trichechus_manatus', 1547],
  ['Monodelphis_domestica', 1498], ['Ornithorhynchus_anatinus', 1476], ['Gallus_gallus', 1452],
] as const

// ---------------------------------------------------------------------------
// Refs / State
// ---------------------------------------------------------------------------

const treeCanvasRef = ref<HTMLElement | null>(null)
const rendererRef = ref<PhyloTreeRenderer | null>(null)
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)
const rendererReady = ref(false)
let renderRequestId = 0
let pollingInFlight = false
let pollFailureCount = 0
let styleUpdateTimer: ReturnType<typeof setTimeout> | null = null

const fileId = ref('')
const fileName = ref('')
const fileFormat = ref('')
const fileSequenceCount = ref(0)
const newickString = ref('')
const taskId = ref('')
const isBuilding = ref(false)
const isUploading = ref(false)
const taskProgress = ref(0)
const taskPhase = ref('')
const taskMessage = ref('')
const taskError = ref('')
const renderError = ref('')
const searchKeyword = ref('')
const sequences = ref<Array<{ id: string; length: number }>>([])
const treeLoading = ref(false)

const FALLBACK_METHODS: PhyloMethodsResponse = {
  alignment_tools: [
    { key: 'mafft', label: 'MAFFT', description: '通用首选，快速准确' },
    { key: 'clustalo', label: 'Clustal Omega', description: '适合大规模序列' },
    { key: 'muscle5', label: 'MUSCLE5', description: '高精度比对' },
    { key: 'prealigned', label: '已比对（跳过）', description: '输入已经完成多序列比对' },
  ],
  tree_methods: [
    { key: 'nj', label: 'Neighbor-Joining', supports_bootstrap: true },
    { key: 'upgma', label: 'UPGMA', supports_bootstrap: false },
    { key: 'fasttree', label: 'FastTree', supports_bootstrap: true },
    { key: 'iqtree', label: 'IQ-TREE', supports_bootstrap: true },
    { key: 'mrbayes', label: 'MrBayes', supports_bootstrap: false },
  ],
  substitution_models: {
    dna: ['JC69', 'K2P', 'HKY', 'GTR', 'GTR+I', 'GTR+G', 'GTR+I+G', 'auto'],
    protein: ['LG', 'WAG', 'JTT', 'auto'],
  },
  bootstrap_types: [
    { key: 'standard', label: '标准 Bootstrap' },
    { key: 'ultrafast', label: 'UFBoot (IQ-TREE)' },
  ],
  presets: {},
}

const methods = ref<PhyloMethodsResponse>(FALLBACK_METHODS)

const buildParams = reactive<PhyloSubmitRequest>({
  file_id: '',
  project_name: '',
  alignment_tool: 'mafft',
  alignment_mode: 'auto',
  tree_method: 'nj',
  substitution_model: 'auto',
  bootstrap_enabled: false,
  bootstrap_type: 'standard',
  bootstrap_replicates: 100,
  sequence_type: 'auto',
  advanced_params: '',
})

const vizConfig = reactive({
  layout: 'circular' as TreeLayout,
  isRooted: true,
  showLabels: true,
  showBootstrap: true,
  showScaleBar: true,
  alignTips: true,
  branchWidth: 1.5,
  fontSize: 12,
})

const treeStats = ref<TreeStatistics>({
  sequence_count: 0,
  total_branches: 0,
  total_tree_length: 0,
  mean_branch_length: 0,
  tree_height: 0,
  min_bootstrap: 0,
  max_bootstrap: 0,
  avg_bootstrap: 0,
  has_bootstrap_support: false,
})

const isDark = computed(() => themeStore.isDark)
const hasTree = computed(() => newickString.value.length > 0)
const canBuild = computed(() => Boolean(fileId.value) && Boolean(buildParams.project_name.trim()) && fileFormat.value !== 'newick')
const statusType = computed<'default' | 'info' | 'success' | 'warning' | 'error'>(() => {
  if (taskError.value) return 'error'
  if (isUploading.value || isBuilding.value) return 'info'
  if (taskPhase.value === 'COMPLETED') return 'success'
  if (taskPhase.value === 'CANCELLED') return 'warning'
  return 'default'
})
const statusText = computed(() => {
  if (taskError.value) return taskError.value
  if (isUploading.value) return '正在校验并上传输入文件'
  if (isBuilding.value) return `${taskPhase.value || 'PENDING'} · ${taskMessage.value || '任务处理中'}`
  if (taskPhase.value === 'COMPLETED') return taskMessage.value || '构建完成，可交互查看和导出结果'
  if (taskPhase.value === 'CANCELLED') return taskMessage.value || '任务已取消'
  if (fileName.value) return fileFormat.value === 'newick' ? 'Newick 已载入，可直接可视化' : '输入已就绪，可提交建树任务'
  return '等待上传序列文件或加载可视化示例'
})
const uploadSummary = computed(() => {
  if (!fileName.value) return ''
  const count = fileSequenceCount.value ? ` · ${fileSequenceCount.value} 个末端/序列` : ''
  return `${fileName.value}${fileFormat.value ? ` · ${fileFormat.value.toUpperCase()}` : ''}${count}`
})
const tablePagination = { pageSize: 10, showSizePicker: false }

// ---------------------------------------------------------------------------
// 选项计算
// ---------------------------------------------------------------------------

const alignmentToolOptions = computed(() =>
  methods.value.alignment_tools.map((m: PhyloMethodOption) => ({ label: m.label, value: m.key })),
)

const treeMethodOptions = computed(() =>
  methods.value.tree_methods.map((m: PhyloMethodOption) => ({ label: m.label, value: m.key })),
)

const selectedTreeMethod = computed(() =>
  methods.value.tree_methods.find((m) => m.key === buildParams.tree_method),
)

const supportsBootstrap = computed(
  () => selectedTreeMethod.value?.supports_bootstrap ?? false,
)

watch(
  () => buildParams.tree_method,
  () => {
    if (!supportsBootstrap.value) {
      buildParams.bootstrap_enabled = false
    }
  },
)

const substitutionModelOptions = computed(() => {
  const dna = (methods.value.substitution_models.dna ?? []).map((m: string) => ({
    label: m,
    value: m,
  }))
  const protein = (methods.value.substitution_models.protein ?? []).map((m: string) => ({
    label: m,
    value: m,
  }))
  return buildParams.sequence_type === 'protein' ? protein : dna
})

watch(
  () => buildParams.sequence_type,
  () => {
    if (!substitutionModelOptions.value.some((o) => o.value === buildParams.substitution_model)) {
      buildParams.substitution_model = 'auto'
    }
  },
)

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

onMounted(() => {
  rendererRef.value = new PhyloTreeRenderer()
  void initializeRenderer()
  void loadMethods()
})

onUnmounted(() => {
  stopPolling()
  if (styleUpdateTimer) clearTimeout(styleUpdateTimer)
  renderRequestId++
  rendererRef.value?.destroy()
})

// ---------------------------------------------------------------------------
// 渲染与统计
// ---------------------------------------------------------------------------

async function renderTree(nwk: string) {
  if (!rendererRef.value || !rendererReady.value) return
  const requestId = ++renderRequestId
  treeLoading.value = true
  renderError.value = ''
  try {
    // 让 UI 先完成一帧绘制，再执行较重的 D3 渲染
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    if (requestId !== renderRequestId) return
    const options = createRenderOptions(vizConfig, isDark.value)
    await rendererRef.value.render(nwk, options)
    const root = parseNewick(nwk)
    treeStats.value = computeTreeStatistics(root)
  } catch (error) {
    if (requestId === renderRequestId) {
      renderError.value = error instanceof Error ? error.message : '未知错误'
    }
  } finally {
    if (requestId === renderRequestId) treeLoading.value = false
  }
}

async function updateTreeStyle() {
  if (!hasTree.value || !rendererRef.value || !rendererReady.value) return
  const options = createRenderOptions(vizConfig, isDark.value)
  try {
    await rendererRef.value.updateOptions(options)
    renderError.value = ''
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : '未知错误'
  }
}

function scheduleTreeStyleUpdate() {
  if (styleUpdateTimer) clearTimeout(styleUpdateTimer)
  styleUpdateTimer = setTimeout(() => void updateTreeStyle(), 120)
}

watch(
  () => newickString.value,
  (nwk) => {
    if (nwk && rendererReady.value) nextTick(() => void renderTree(nwk))
  },
)

watch(
  () => vizConfig,
  () => {
    if (hasTree.value) scheduleTreeStyleUpdate()
  },
  { deep: true },
)

watch(isDark, () => {
  if (hasTree.value) scheduleTreeStyleUpdate()
})

async function initializeRenderer() {
  if (!treeCanvasRef.value || !rendererRef.value) return
  treeLoading.value = true
  try {
    await rendererRef.value.init(treeCanvasRef.value, { zoom: true, brush: false })
    rendererReady.value = true
    if (newickString.value) await renderTree(newickString.value)
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : '未知错误'
  } finally {
    if (!rendererReady.value) treeLoading.value = false
  }
}

async function loadMethods() {
  try {
    methods.value = await fetchPhyloMethods()
  } catch {
    methods.value = FALLBACK_METHODS
    message.warning('方法配置暂不可用，已切换到内置安全默认值')
  }
}

// ---------------------------------------------------------------------------
// 文件上传
// ---------------------------------------------------------------------------

async function handleUploadChange({ file }: { file: UploadFileInfo }) {
  if (!file.file || isUploading.value || file.status === 'finished') return
  isUploading.value = true
  taskError.value = ''
  taskPhase.value = ''
  taskMessage.value = ''
  try {
    const resp = await uploadSequenceFile(file.file)
    fileId.value = resp.file_id
    fileName.value = resp.filename
    fileFormat.value = resp.format.toLowerCase()
    fileSequenceCount.value = resp.sequence_count ?? 0
    buildParams.file_id = resp.file_id
    buildParams.sequence_type = (resp.sequence_type?.toLowerCase() === 'protein' ? 'protein' : 'auto') as SequenceType
    sequences.value = await parseSequencesFromFile(file.file)
    if (fileFormat.value === 'newick') {
      newickString.value = await file.file.text()
      sequences.value = extractTipRows(newickString.value)
    } else {
      newickString.value = ''
      rendererRef.value?.clear()
    }
    file.status = 'finished'
    message.success(`已上传 ${resp.sequence_count ?? sequences.value.length} 条序列`)
  } catch (e) {
    file.status = 'error'
    taskError.value = `上传失败：${e instanceof Error ? e.message : '未知错误'}`
  } finally {
    isUploading.value = false
  }
}

function parseSequencesFromFile(file: File): Promise<Array<{ id: string; length: number }>> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result || '')
      const lines = text.split(/\r?\n/)
      const result: Array<{ id: string; length: number }> = []
      let currentId = ''
      let currentSeq = ''
      const pushCurrent = () => {
        if (currentId) {
          result.push({ id: currentId, length: currentSeq.length })
        }
      }
      for (const line of lines) {
        if (line.startsWith('>')) {
          pushCurrent()
          currentId = line.slice(1).trim().split(/\s+/)[0]
          currentSeq = ''
        } else {
          currentSeq += line.trim()
        }
      }
      pushCurrent()
      resolve(result)
    }
    reader.onerror = () => resolve([])
    reader.readAsText(file)
  })
}

function extractTipRows(newick: string): Array<{ id: string; length: number }> {
  const tips = newick.match(/(?:^|[(,])\s*([^():;,\s]+)\s*(?=[:),])/g) ?? []
  return tips.map((token) => ({ id: token.replace(/^[(:,]\s*/, '').trim(), length: 0 }))
}

// ---------------------------------------------------------------------------
// 构建任务
// ---------------------------------------------------------------------------

async function buildTree() {
  if (!fileId.value) {
    message.warning('请先上传序列文件')
    return
  }
  if (!buildParams.project_name.trim()) {
    message.warning('请填写项目名称')
    return
  }
  isBuilding.value = true
  taskError.value = ''
  taskProgress.value = 0
  taskPhase.value = 'PENDING'
  taskMessage.value = '任务投递中...'
  try {
    const resp = await submitTreeBuild(buildParams)
    taskId.value = resp.task_id
    startPolling()
  } catch (e) {
    isBuilding.value = false
    taskError.value = `任务提交失败：${e instanceof Error ? e.message : '未知错误'}`
  }
}

function startPolling() {
  stopPolling()
  pollFailureCount = 0
  void pollTaskStatus()
  pollingTimer.value = setInterval(() => void pollTaskStatus(), POLLING_INTERVAL)
}

async function pollTaskStatus() {
  if (!taskId.value || pollingInFlight) return
  pollingInFlight = true
  try {
    const data: PhyloTaskResponse = await getTaskStatus(taskId.value)
    taskProgress.value = Math.round((data.progress || 0) * 100)
    taskPhase.value = data.phase || data.status
    taskMessage.value = data.message || ''
    if (data.status === 'SUCCESS') {
      await loadCompletedTree(taskId.value)
    } else if (data.status === 'FAILURE') {
      stopPolling()
      isBuilding.value = false
      taskError.value = `构建失败：${data.message || '未知错误'}`
    } else if (data.status === 'REVOKED') {
      stopPolling()
      isBuilding.value = false
      taskPhase.value = 'CANCELLED'
      taskMessage.value = '任务已取消'
    }
    pollFailureCount = 0
  } catch (error) {
    pollFailureCount += 1
    taskMessage.value = `状态连接异常，正在重试（${pollFailureCount}/${MAX_POLL_FAILURES}）`
    if (pollFailureCount >= MAX_POLL_FAILURES) {
      stopPolling()
      isBuilding.value = false
      taskError.value = `无法获取任务状态：${error instanceof Error ? error.message : '网络连接异常'}`
    }
  } finally {
    pollingInFlight = false
  }
}

async function loadCompletedTree(completedTaskId: string) {
  stopPolling()
  isBuilding.value = false
  try {
    const result = await getTaskResult(completedTaskId)
    const nwk = await downloadTreeResult(completedTaskId, 'newick')
    newickString.value = nwk
    treeStats.value = result.statistics
    taskProgress.value = 100
    taskPhase.value = 'COMPLETED'
    taskMessage.value = `构建完成，用时 ${result.execution_time.toFixed(1)} 秒`
    message.success('系统发育树构建完成')
  } catch (error) {
    taskError.value = `结果加载失败：${error instanceof Error ? error.message : '未知错误'}`
  }
}

function stopPolling() {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

async function cancelBuild() {
  if (!taskId.value) return
  try {
    await cancelTask(taskId.value)
    stopPolling()
    isBuilding.value = false
    taskPhase.value = 'CANCELLED'
    taskMessage.value = '已发送取消请求'
  } catch (e) {
    message.error(`取消失败：${e instanceof Error ? e.message : '未知错误'}`)
  }
}

// ---------------------------------------------------------------------------
// 示例数据
// ---------------------------------------------------------------------------

function loadExampleData() {
  stopPolling()
  isBuilding.value = false
  taskId.value = ''
  taskError.value = ''
  taskPhase.value = 'COMPLETED'
  taskMessage.value = '已加载 21 个物种的复杂环形示例（仅可视化，不提交计算）'
  taskProgress.value = 100
  fileId.value = ''
  buildParams.file_id = ''
  fileFormat.value = 'newick'
  fileSequenceCount.value = EXAMPLE_SEQUENCES.length
  newickString.value = EXAMPLE_NEWICK
  sequences.value = EXAMPLE_SEQUENCES.map(([id, length]) => ({ id, length }))
  fileName.value = 'mammal_evolution_example.nwk'
  vizConfig.layout = 'circular'
  message.success('复杂环形示例已加载，不会启动后台任务')
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

function exportSVG() {
  const svg = rendererRef.value?.exportSVG()
  if (!svg) {
    message.warning('没有可导出的树')
    return
  }
  downloadBlob(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }), 'phylogenetic_tree.svg')
}

async function exportPNG() {
  const svg = rendererRef.value?.exportSVG()
  if (!svg) {
    message.warning('没有可导出的树')
    return
  }
  try {
    const background = getComputedStyle(document.documentElement).getPropertyValue('--neutral-card').trim()
    const blob = await svgToPng(svg, background)
    downloadBlob(blob, 'phylogenetic_tree.png')
  } catch (e) {
    message.error(`PNG 导出失败：${e instanceof Error ? e.message : '未知错误'}`)
  }
}

function exportNewick() {
  if (!newickString.value) {
    message.warning('没有可导出的 Newick')
    return
  }
  const nwk = rendererRef.value?.exportNewick() || newickString.value
  downloadBlob(new Blob([nwk], { type: 'text/plain;charset=utf-8' }), 'tree.nwk')
}

// ---------------------------------------------------------------------------
// 序列列表
// ---------------------------------------------------------------------------

const filteredSequences = computed(() => {
  const q = searchKeyword.value.trim().toLowerCase()
  if (!q) return sequences.value
  return sequences.value.filter((s) => s.id.toLowerCase().includes(q))
})

const sequenceColumns = [
  { title: '序列 ID', key: 'id' },
  { title: '长度', key: 'length' },
]

function highlightSequence(row: { id: string }) {
  rendererRef.value?.highlightNode(row.id)
}

function handleRowClick(row: unknown) {
  highlightSequence(row as { id: string })
}
</script>

<template>
  <div class="phylo-page">
    <PageHeader
      title="系统发育树构建"
      subtitle="上传序列、配置比对与建树参数，完成后交互查看矩形、环形或无根树"
      back-to="/tools"
      back-label="返回工具箱"
    >
      <template #actions>
        <NButton size="small" quaternary @click="loadExampleData">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          复杂环形示例
        </NButton>
      </template>
    </PageHeader>

    <!-- 主体三栏 -->
    <div class="phylo-layout">
      <!-- 左：参数面板 -->
      <aside class="param-panel">
        <NCollapse :default-expanded-names="['data', 'alignment', 'tree', 'viz']" arrow-placement="left">
          <NCollapseItem title="数据输入" name="data">
            <div class="form-row">
              <span class="form-label">项目名称</span>
              <NInput v-model:value="buildParams.project_name" size="small" placeholder="例如：TnpD 系统发育分析" />
            </div>
            <NUpload
              accept=".fasta,.fa,.fas,.phylip,.phy,.nex,.nexus,.nwk,.newick"
              :max="1"
              :default-upload="false"
              :show-file-list="false"
              :disabled="isUploading || isBuilding"
              @change="handleUploadChange"
            >
              <NButton size="small" block :loading="isUploading">上传序列 / Newick 文件</NButton>
            </NUpload>
            <p v-if="uploadSummary" class="file-hint">已加载：{{ uploadSummary }}</p>
            <p class="panel-hint">支持 FASTA、Phylip、NEXUS、Newick</p>
            <NAlert v-if="fileFormat === 'newick'" class="inline-alert" type="info" :show-icon="false">
              Newick 文件用于直接可视化；如需重新建树，请上传包含序列的文件。
            </NAlert>
          </NCollapseItem>

          <NCollapseItem title="比对配置" name="alignment">
            <div class="form-row">
              <span class="form-label">比对工具</span>
              <NSelect v-model:value="buildParams.alignment_tool" size="small" :options="alignmentToolOptions" />
            </div>
            <div v-if="buildParams.alignment_tool !== 'prealigned'" class="form-row">
              <span class="form-label">模式</span>
              <NInput v-model:value="buildParams.alignment_mode" size="small" placeholder="auto" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="树构建" name="tree">
            <div class="form-row">
              <span class="form-label">构建方法</span>
              <NSelect v-model:value="buildParams.tree_method" size="small" :options="treeMethodOptions" />
            </div>
            <div class="form-row">
              <span class="form-label">序列类型</span>
              <NRadioGroup v-model:value="buildParams.sequence_type" size="small">
                <NRadioButton value="auto">自动</NRadioButton>
                <NRadioButton value="dna">DNA</NRadioButton>
                <NRadioButton value="protein">蛋白质</NRadioButton>
              </NRadioGroup>
            </div>
            <div class="form-row">
              <span class="form-label">替代模型</span>
              <NSelect v-model:value="buildParams.substitution_model" size="small" :options="substitutionModelOptions" />
            </div>
            <div class="form-row">
              <NSwitch v-model:value="buildParams.bootstrap_enabled" size="small" :disabled="!supportsBootstrap" />
              <span class="switch-label">启用 Bootstrap</span>
            </div>
            <div v-if="buildParams.bootstrap_enabled" class="form-row">
              <span class="form-label">重复次数</span>
              <NInputNumber v-model:value="buildParams.bootstrap_replicates" size="small" :show-button="false" :min="10" :max="10000" />
            </div>
            <div class="form-row">
              <span class="form-label">高级参数</span>
              <NInput v-model:value="buildParams.advanced_params" size="small" placeholder="额外命令行参数" />
            </div>
          </NCollapseItem>

          <NCollapseItem title="可视化" name="viz">
            <div class="form-row">
              <span class="form-label">布局</span>
              <NRadioGroup v-model:value="vizConfig.layout" size="small">
                <NRadioButton value="rectangular">矩形</NRadioButton>
                <NRadioButton value="circular">环形</NRadioButton>
                <NRadioButton value="radial">无根</NRadioButton>
              </NRadioGroup>
            </div>
            <p class="panel-hint">矩形与环形保留根节点；无根模式按辐射状展示拓扑关系。</p>
            <div class="form-row">
              <NSwitch v-model:value="vizConfig.showLabels" size="small" />
              <span class="switch-label">显示标签</span>
            </div>
            <div class="form-row">
              <NSwitch v-model:value="vizConfig.showBootstrap" size="small" />
              <span class="switch-label">显示 Bootstrap</span>
            </div>
            <div class="form-row">
              <NSwitch v-model:value="vizConfig.showScaleBar" size="small" />
              <span class="switch-label">显示比例尺</span>
            </div>
            <div class="form-row">
              <span class="form-label">分支宽度</span>
              <NInputNumber v-model:value="vizConfig.branchWidth" size="small" :show-button="false" :min="0.5" :max="5" :step="0.5" />
            </div>
            <div class="form-row">
              <span class="form-label">字体大小</span>
              <NInputNumber v-model:value="vizConfig.fontSize" size="small" :show-button="false" :min="8" :max="24" />
            </div>
          </NCollapseItem>
        </NCollapse>

        <div class="build-actions">
          <NButton
            type="primary"
            size="small"
            block
            :loading="isBuilding"
            :disabled="isUploading || !canBuild"
            @click="buildTree"
          >
            <template #icon>
              <NIcon><BuildOutline /></NIcon>
            </template>
            构建系统发育树
          </NButton>
          <NButton v-if="isBuilding" size="small" block @click="cancelBuild">取消任务</NButton>
        </div>

        <div v-if="isBuilding || taskProgress > 0" class="progress-area" aria-live="polite">
          <NProgress type="line" :percentage="taskProgress" :indicator-placement="'inside'" />
        </div>
        <div class="status-line" aria-live="polite">
          <NTag size="small" :type="statusType" :bordered="false">{{ statusText }}</NTag>
        </div>
      </aside>

      <!-- 中：工作区 -->
      <main class="work-card">
        <div class="tree-container">
          <div ref="treeCanvasRef" class="tree-canvas" aria-label="系统发育树可视化画布"></div>
          <NEmpty v-if="!hasTree && !treeLoading && !renderError" description="上传序列后提交任务，或加载复杂环形示例" />
          <NAlert v-if="renderError" class="render-error" type="error" title="树渲染失败">
            {{ renderError }}
          </NAlert>
          <div v-if="treeLoading" class="tree-loading">
            <NSpin size="large" description="正在渲染树..." />
          </div>
        </div>
        <div class="work-actions">
          <NButton size="tiny" secondary :disabled="!hasTree || treeLoading" @click="exportSVG">
            <template #icon><NIcon><DownloadOutline /></NIcon></template>
            SVG
          </NButton>
          <NButton size="tiny" secondary :disabled="!hasTree || treeLoading" @click="exportPNG">
            <template #icon><NIcon><DownloadOutline /></NIcon></template>
            PNG
          </NButton>
          <NButton size="tiny" secondary :disabled="!hasTree" @click="exportNewick">
            <template #icon><NIcon><ExpandOutline /></NIcon></template>
            Newick
          </NButton>
        </div>
      </main>

      <!-- 右：统计与序列 -->
      <aside class="side-panel">
        <h3 class="panel-title">树统计信息</h3>
        <div class="stat-grid">
          <div class="stat-item">
            <span class="stat-label">序列数</span>
            <span class="stat-value">{{ treeStats.sequence_count }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">分支数</span>
            <span class="stat-value">{{ treeStats.total_branches }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">树高</span>
            <span class="stat-value">{{ treeStats.tree_height.toFixed(4) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">平均枝长</span>
            <span class="stat-value">{{ treeStats.mean_branch_length.toFixed(4) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Bootstrap 均值</span>
            <span class="stat-value">{{ treeStats.avg_bootstrap.toFixed(1) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Bootstrap 范围</span>
            <span class="stat-value">{{ treeStats.min_bootstrap }}-{{ treeStats.max_bootstrap }}</span>
          </div>
        </div>

        <h3 class="panel-title">节点搜索</h3>
        <NInput v-model:value="searchKeyword" size="small" clearable placeholder="输入序列 ID">
          <template #prefix>
            <NIcon><SearchOutline /></NIcon>
          </template>
        </NInput>

        <h3 class="panel-title">序列列表</h3>
        <NDataTable
          :columns="sequenceColumns"
          :data="filteredSequences"
          :row-key="(row) => row.id"
          :max-height="240"
          :pagination="tablePagination"
          size="small"
          @row-click="handleRowClick"
        />

        <div class="tips">
          <p>💡 操作提示</p>
          <ul>
            <li>滚轮缩放 / 拖拽平移</li>
            <li>点击节点可高亮</li>
            <li>矩形、环形、无根布局可即时切换</li>
          </ul>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.phylo-page {
  padding: 16px;
  min-height: 100%;
}
.phylo-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}
.param-panel,
.work-card,
.side-panel {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 12px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}
.work-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.tree-container {
  min-height: 540px;
  position: relative;
  flex: 1;
  display: grid;
  place-items: center;
}
.tree-canvas {
  min-height: 540px;
  width: 100%;
}
.tree-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--neutral-card) 86%, transparent);
  z-index: 10;
}
.render-error {
  width: min(520px, calc(100% - 32px));
}
.tree-canvas :deep(svg) {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
.tree-canvas :deep(.branch) {
  fill: none;
  stroke: var(--neutral-text-3);
  vector-effect: non-scaling-stroke;
  transition: stroke 320ms cubic-bezier(0.16, 1, 0.3, 1);
}
.tree-canvas :deep(.branch:hover),
.tree-canvas :deep(.branch-selected) {
  stroke: var(--arco-primary);
}
.tree-canvas :deep(.node circle),
.tree-canvas :deep(.internal-node circle) {
  fill: var(--neutral-card);
  stroke: var(--neutral-text-3);
  vector-effect: non-scaling-stroke;
}
.tree-canvas :deep(.node-selected circle) {
  fill: var(--arco-primary);
  stroke: var(--arco-primary);
}
.tree-canvas :deep(text) {
  fill: var(--neutral-text-1);
}
.tree-canvas :deep(.tree-scale-bar path),
.tree-canvas :deep(.tree-scale-bar line) {
  fill: none;
  stroke: var(--neutral-text-2);
  vector-effect: non-scaling-stroke;
}
.work-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.form-label {
  width: 72px;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--neutral-text-2);
}
.switch-label {
  font-size: 13px;
  color: var(--neutral-text-2);
}
.file-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--neutral-text-3);
  word-break: break-all;
}
.inline-alert {
  margin-top: 8px;
}
.panel-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--neutral-text-3);
}
.build-actions {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.progress-area {
  margin-top: 12px;
}
.status-line {
  margin-top: 10px;
  display: flex;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 16px 0 8px;
}
.panel-title:first-child {
  margin-top: 0;
}
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.stat-item {
  background: var(--neutral-hover);
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
}
.stat-label {
  font-size: 11px;
  color: var(--neutral-text-3);
}
.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
}
.tips {
  margin-top: 16px;
  padding: 10px;
  background: var(--neutral-hover);
  border-radius: 8px;
  font-size: 12px;
  color: var(--neutral-text-3);
}
.tips p {
  margin: 0 0 4px;
  font-weight: 500;
}
.tips ul {
  margin: 0;
  padding-left: 16px;
}
@media (max-width: 1200px) {
  .phylo-layout {
    grid-template-columns: 1fr;
  }
  .param-panel,
  .work-card,
  .side-panel {
    max-height: none;
  }
}
@media (max-width: 768px) {
  .phylo-page {
    padding: 12px;
  }
  .tree-container,
  .tree-canvas {
    min-height: 460px;
  }
  .form-row {
    align-items: flex-start;
    flex-wrap: wrap;
  }
}
@media (prefers-reduced-motion: reduce) {
  .tree-canvas :deep(.branch) {
    transition: none;
  }
}
</style>
