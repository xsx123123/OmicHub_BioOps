<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import {
  NButton, NCollapse, NCollapseItem, NDivider, NEmpty, NFlex, NIcon,
  NInputNumber, NSelect, NSpace, NSwitch, NUpload, NSpin,
  type UploadFileInfo,
} from 'naive-ui'
import { ArrowBackOutline, GridOutline, SparklesOutline } from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import { useThemeStore } from '@/stores/theme'
import PageHeader from '@/components/PageHeader.vue'
import {
  type ExpressionMatrix, type GroupMapping, type ProcessedData,
  type ExplorerConfig, type PCAResult,
  DEFAULT_CONFIG,
  parseExpressionMatrix, parseGroupMapping, autoDetectDelimiter,
  computePCA, computeGeneVariances, applyLogTransform, getSampleGroup,
  buildExplorerFigure, genSampleData,
} from '@/utils/geneExpressionProcessor'

const EXPLORE_PLOT_ID = 'gene-expression-explorer-plot'
const router = useRouter()
const message = useMessage()
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

// === 状态 ===
const matrix = ref<ExpressionMatrix | null>(null)
const groups = ref<GroupMapping[]>([])
const processed = ref<ProcessedData | null>(null)
const config = reactive<ExplorerConfig>({ ...DEFAULT_CONFIG })
const delimiter = ref<'auto' | 'comma' | 'tab'>('auto')
const processing = ref(false)
const hasData = computed(() => matrix.value !== null)
const exportDpi = ref(300)

// === 选项数据 ===
const delimiterOptions = [
  { label: '自动检测', value: 'auto' },
  { label: '逗号', value: 'comma' },
  { label: '制表符', value: 'tab' },
]
const boxplotOptions = [
  { label: '全部样本', value: 'all' },
  { label: 'Top20方差', value: 'top20' },
]
const colorSchemeOptions = [
  { label: 'Friendly', value: 'Friendly' },
  { label: 'Friendly Long', value: 'Friendly Long' },
  { label: 'Friendly Long 2', value: 'Friendly Long 2' },
  { label: 'Seaside', value: 'Seaside' },
  { label: 'Apple', value: 'Apple' },
  { label: 'IBM', value: 'IBM' },
  { label: 'Candy', value: 'Candy' },
  { label: 'Color 1', value: 'Color 1' },
  { label: 'Set2', value: 'Set2' },
  { label: 'Set1', value: 'Set1' },
  { label: 'Set3', value: 'Set3' },
  { label: 'Pastel1', value: 'Pastel1' },
  { label: 'Dark24', value: 'Dark24' },
]
const dpiOptions = [
  { label: '300', value: 300 },
  { label: '600', value: 600 },
  { label: '1000', value: 1000 },
]

// === 文件上传处理 ===
function handleMatrixUpload({ file }: { file: UploadFileInfo }) {
  const rawFile = file.file
  if (!rawFile) return
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result as string
    try {
      const detected = delimiter.value === 'auto' ? autoDetectDelimiter(text) : ','
      const d: 'comma' | 'tab' = detected === '\t' ? 'tab' : 'comma'
      matrix.value = parseExpressionMatrix(text, delimiter.value === 'auto' ? 'auto' : d)
      message.success(`成功加载 ${matrix.value.geneIds.length} 个基因 × ${matrix.value.sampleNames.length} 个样本`)
      scheduleGenerate()
    } catch (err: any) {
      message.error('解析表达矩阵失败: ' + err.message)
    }
  }
  reader.readAsText(rawFile)
}

function handleGroupUpload({ file }: { file: UploadFileInfo }) {
  const rawFile = file.file
  if (!rawFile) return
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result as string
    try {
      groups.value = parseGroupMapping(text)
      message.success(`成功加载 ${groups.value.length} 个样本分组`)
      scheduleGenerate()
    } catch (err: any) {
      message.error('解析分组表失败: ' + err.message)
    }
  }
  reader.readAsText(rawFile)
}

// === 核心流程 ===
async function generatePlot() {
  if (!matrix.value) {
    message.warning('请先上传表达矩阵')
    return
  }
  processing.value = true

  try {
    // 1. 数据预处理
    const workingMatrix = config.logTransform ? applyLogTransform(matrix.value) : matrix.value

    // 2. 计算
    const pca = computePCA(workingMatrix, 2)
    const geneVariances = computeGeneVariances(workingMatrix)

    processed.value = {
      matrix: workingMatrix,
      groups: groups.value,
      pca,
      geneVariances,
      sampleMedians: workingMatrix.sampleNames.map((_, i) => {
        const vals = workingMatrix.data.map((row) => row[i]).filter((v) => !Number.isNaN(v))
        vals.sort((a, b) => a - b)
        return vals[Math.floor(vals.length / 2)]
      }),
    }

    // 3. 渲染
    await renderPlot()
  } catch (err: any) {
    message.error('计算失败: ' + err.message)
  } finally {
    processing.value = false
  }
}

async function renderPlot() {
  if (!processed.value) return
  const container = document.getElementById(EXPLORE_PLOT_ID)
  if (!container) return

  const figure = buildExplorerFigure(processed.value, config, isDark.value)
  await Plotly.react(container, figure.data, figure.layout, figure.config)
}

// === debounce ===
let debounceTimer: ReturnType<typeof setTimeout> | null = null
function scheduleGenerate() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(generatePlot, 300)
}

// === 参数监听 ===
watch(() => [
  config.pointSize, config.pointOpacity, config.boxplotMode,
  config.colorScheme, config.showOutliers, config.logTransform,
  config.showPCA, config.showExpression, config.showVariance,
], scheduleGenerate, { deep: false })

watch(isDark, () => renderPlot())

// === 导出 ===
function exportImage(format: 'png' | 'svg') {
  const container = document.getElementById(EXPLORE_PLOT_ID)
  if (!container) return
  const scale = format === 'png' ? exportDpi.value / 96 : 1
  Plotly.downloadImage(container, {
    format,
    filename: `gene_expression_explorer_${formatTimestamp()}_${exportDpi.value}dpi`,
    scale,
  } as any)
}

function formatTimestamp(): string {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}_${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`
}

// === 示例数据 ===
function loadSample() {
  const { matrixText, groupText } = genSampleData()
  matrix.value = parseExpressionMatrix(matrixText, 'comma')
  groups.value = parseGroupMapping(groupText)
  delimiter.value = 'comma'
  message.info('已加载示例数据(20基因×8样本)')
  generatePlot()
}

// === 生命周期 ===
onMounted(() => loadSample())

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const el = document.getElementById(EXPLORE_PLOT_ID)
  if (el) Plotly.purge(el)
})
</script>

<template>
  <div class="gene-expression-explorer-page">
    <PageHeader title="基因表达矩阵 Explorer" subtitle="上传表达矩阵，交互式探索样本分布、PCA 与基因方差" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" quaternary @click="loadSample">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          示例数据
        </NButton>
      </template>
    </PageHeader>

    <div class="gene-expression-explorer-layout">
      <!-- 左：参数面板 -->
      <aside class="param-panel">
        <NCollapse :default-expanded-names="['data', 'chart', 'display']" arrow-placement="left">
          <NCollapseItem title="数据输入" name="data">
            <NSpace vertical>
              <NUpload
                accept=".csv,.tsv,.txt"
                :max="1"
                :default-upload="false"
                @before-upload="handleMatrixUpload"
              >
                <NButton size="small" block>上传表达矩阵</NButton>
              </NUpload>
              <NSelect v-model:value="delimiter" :options="delimiterOptions" size="small" />
              <NUpload
                accept=".csv,.tsv"
                :max="1"
                :default-upload="false"
                @before-upload="handleGroupUpload"
              >
                <NButton size="small" block secondary>上传分组表（可选）</NButton>
              </NUpload>
            </NSpace>
          </NCollapseItem>

          <NCollapseItem title="图表参数" name="chart">
            <NSpace vertical>
              <NFlex justify="space-between" align="center">
                <span>PCA 点大小</span>
                <NInputNumber v-model:value="config.pointSize" :min="3" :max="30" size="small" style="width: 90px" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>PCA 透明度</span>
                <NInputNumber v-model:value="config.pointOpacity" :min="0.1" :max="1" :step="0.1" size="small" style="width: 90px" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>箱线图展示</span>
                <NSelect v-model:value="config.boxplotMode" :options="boxplotOptions" size="small" style="width: 110px" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>调色方案</span>
                <NSelect v-model:value="config.colorScheme" :options="colorSchemeOptions" size="small" style="width: 110px" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>显示离群点</span>
                <NSwitch v-model:value="config.showOutliers" size="small" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>对数变换 log2(x+1)</span>
                <NSwitch v-model:value="config.logTransform" size="small" />
              </NFlex>
            </NSpace>
          </NCollapseItem>

          <NCollapseItem title="显示控制" name="display">
            <NSpace vertical>
              <NFlex justify="space-between" align="center">
                <span>PCA</span>
                <NSwitch v-model:value="config.showPCA" size="small" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>表达箱线图</span>
                <NSwitch v-model:value="config.showExpression" size="small" />
              </NFlex>
              <NFlex justify="space-between" align="center">
                <span>方差图</span>
                <NSwitch v-model:value="config.showVariance" size="small" />
              </NFlex>
              <NDivider style="margin: 8px 0" />
              <NFlex justify="space-between" align="center">
                <span>导出DPI</span>
                <NSelect v-model:value="exportDpi" :options="dpiOptions" size="small" style="width: 100px" />
              </NFlex>
              <NFlex gap="small">
                <NButton size="tiny" secondary @click="exportImage('png')">PNG</NButton>
                <NButton size="tiny" secondary @click="exportImage('svg')">SVG</NButton>
              </NFlex>
            </NSpace>
          </NCollapseItem>
        </NCollapse>

        <NButton type="primary" block style="margin-top: 12px" :loading="processing" @click="generatePlot">
          <template #icon><NIcon><GridOutline /></NIcon></template>
          生成图表
        </NButton>
      </aside>

      <!-- 右：图表工作区 -->
      <main class="work-area">
        <div class="plot-card">
          <div v-if="!hasData" class="empty-state">
            <NEmpty description="请上传表达矩阵或加载示例数据">
              <template #icon><NIcon :size="48"><GridOutline /></NIcon></template>
            </NEmpty>
          </div>
          <NSpin v-else-if="processing" description="计算中..." />
          <div v-show="hasData && !processing" :id="EXPLORE_PLOT_ID" class="plot-container" />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.gene-expression-explorer-page {
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
.gene-expression-explorer-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
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
.work-area {
  min-width: 0;
}
.plot-card {
  position: relative;
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 8px;
  min-height: 720px;
}
.plot-container {
  width: 100%;
  height: 780px;
}
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 540px;
}

@media (max-width: 1200px) {
  .gene-expression-explorer-layout {
    grid-template-columns: 1fr;
  }
  .param-panel {
    max-height: none;
  }
}
</style>
