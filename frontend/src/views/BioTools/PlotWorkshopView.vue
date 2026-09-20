<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NCard, NCollapse, NCollapseItem, NEmpty, NIcon, NInput,
  NInputNumber, NRadioButton, NRadioGroup, NSelect, NSlider, NSpace, NSwitch, NTag, NUpload, useMessage,
  type UploadFileInfo,
} from 'naive-ui'
import { ArrowBackOutline, ContractOutline, DownloadOutline, ExpandOutline, RefreshOutline, SparklesOutline } from '@vicons/ionicons5'
import * as Plotly from 'plotly.js-dist-min'
import { useThemeStore } from '@/stores/theme'
import PageHeader from '@/components/PageHeader.vue'
import { fetchPosthocComparisons, type PosthocResult } from '@/api/plotStats'
import { CONTINUOUS_PALETTES, DISCRETE_PALETTES } from '@/components/charts/palettes'
import {
  buildWorkshopResult, CHART_DEFINITIONS, DEFAULT_COLUMN_MAP, DEFAULT_WORKSHOP_CONFIG, inferColumnMap, parseDelimited, resultToCsv,
  type ChartKind, type ColumnMap, type SurvivalWorkshopOptions,
} from '@/utils/chartWorkshopProcessor'
import { SAMPLE_EXPRESSION_CSV, SAMPLE_FOLLOWUP_CSV, SAMPLE_SURVIVAL_COMBINED_CSV } from '@/utils/survival/sampleData'
import type { SurvivalGroupStrategy } from '@/utils/survival/survivalTypes'

const PLOT_DIV_ID = 'plot-workshop-figure'
const router = useRouter()
const message = useMessage()
const themeStore = useThemeStore()

const chartType = ref<ChartKind>('bar')
const table = ref(parseDelimited(''))
const fileName = ref('')
const plotting = ref(false)
const isFullscreen = ref(false)
const exportDpi = ref(300)
const posthocLoading = ref(false)
const posthocResult = ref<PosthocResult | null>(null)
const form = reactive({ ...DEFAULT_WORKSHOP_CONFIG, exportCustomSize: false, exportWidth: 1200, exportHeight: 800 })
const colMap = reactive<ColumnMap>({ ...DEFAULT_COLUMN_MAP })

// 生存分析（KM）专属 UI 状态：保持在组件内，不写入 DEFAULT_WORKSHOP_CONFIG。
const survivalInputMode = ref<'combined' | 'expression'>('combined')
const followTable = ref(parseDelimited(''))
const followFileName = ref('')
const survivalStrategy = ref<SurvivalGroupStrategy>('median')
const survivalCustomCutoff = ref(0)
const survivalShowCI = ref(false)
const survivalShowCensors = ref(true)
const survivalShowRiskTable = ref(true)
const survivalOptions = computed<SurvivalWorkshopOptions>(() => ({
  inputMode: survivalInputMode.value,
  followupTable: followTable.value.headers.length ? followTable.value : null,
  strategy: survivalStrategy.value,
  customCutoff: survivalCustomCutoff.value,
  showCI: survivalShowCI.value,
  showCensors: survivalShowCensors.value,
  showRiskTable: survivalShowRiskTable.value,
  isDark: themeStore.isDark,
}))

const chartOptions = Object.values(CHART_DEFINITIONS).map(({ label, kind }) => ({ label, value: kind }))

const discreteOptions = Object.keys(DISCRETE_PALETTES).map((value) => ({ label: value, value }))
const continuousOptions = Object.keys(CONTINUOUS_PALETTES).map((value) => ({ label: value, value }))
const columnOptions = computed(() => table.value.headers.map((header) => ({ label: header, value: header })))
const enrichmentPathwayOptions = computed(() => {
  const idColumn = table.value.headers.find((header) => ['id', 'go id', 'pathway id'].includes(header.trim().toLowerCase()))
  const descriptionColumn = table.value.headers.find((header) => ['description', 'go term', 'kegg pathway'].includes(header.trim().toLowerCase()))
  if (!idColumn || !descriptionColumn) return []
  return table.value.rows
    .map((row) => ({ label: `${row[idColumn]} · ${row[descriptionColumn]}`, value: row[idColumn] }))
    .filter((option) => option.value)
})
const result = computed(() => buildWorkshopResult(chartType.value, table.value, colMap, form, { survival: survivalOptions.value }))
const isDark = computed(() => themeStore.isDark)
const chartLabel = computed(() => chartOptions.find((option) => option.value === chartType.value)?.label ?? '')
const hasErrors = computed(() => result.value.messages.some((item) => item.severity === 'error'))
const plotCanvasStyle = computed(() => ({ width: `${form.plotWidth}px`, height: `${form.plotHeight}px` }))

function canUseNumericRange(axis: 'x' | 'y') {
  if (axis === 'x') return ['scatter', 'line', 'histogram', 'pca', 'enrichment', 'survival'].includes(chartType.value)
  return !['heatmap', 'corr-heatmap', 'enrichment', 'survival'].includes(chartType.value)
}

function validRange(mode: 'auto' | 'manual', min: number, max: number) {
  return mode === 'manual' && Number.isFinite(min) && Number.isFinite(max) && min < max ? [min, max] as [number, number] : undefined
}

function applyConfiguredAxisRanges(layout: Partial<Plotly.Layout>) {
  const configured = { ...layout, xaxis: { ...(layout.xaxis ?? {}) }, yaxis: { ...(layout.yaxis ?? {}) } }
  const xRange = canUseNumericRange('x') ? validRange(form.xRangeMode, form.xMin, form.xMax) : undefined
  const yRange = canUseNumericRange('y') ? validRange(form.yRangeMode, form.yMin, form.yMax) : undefined
  if (xRange) configured.xaxis = { ...(configured.xaxis ?? {}), autorange: false, range: xRange }
  if (yRange) configured.yaxis = { ...(configured.yaxis ?? {}), autorange: false, range: yRange }
  return configured
}

const examples: Record<ChartKind, { fileName: string; text: string; description: string }> = {
  bar: { fileName: 'example_bar.csv', description: '长表：分组列 + 数值列；每一行是一个生物学重复。', text: 'group,value\nControl,78.2\nControl,81.5\nControl,76.9\nTreatment,92.4\nTreatment,95.1\nTreatment,89.8\n' },
  boxplot: { fileName: 'example_boxplot.csv', description: '长表：分组列 + 数值列；与柱状图共用格式和统计。', text: 'group,value\nControl,78.2\nControl,81.5\nControl,76.9\nTreatment,92.4\nTreatment,95.1\nTreatment,89.8\n' },
  violin: { fileName: 'example_violin.csv', description: '长表：分组列 + 数值列；展示分布形态、箱线和原始重复点。', text: 'group,value\nControl,78.2\nControl,81.5\nControl,76.9\nTreatment,92.4\nTreatment,95.1\nTreatment,89.8\n' },
  scatter: { fileName: 'example_scatter.csv', description: 'X、Y 数值列；可选 group 分组列以显示不同颜色与独立拟合。', text: 'expression,trait,group\n8.21,72.5,Control\n7.95,69.1,Control\n5.12,45.3,Control\n9.02,82.1,Treatment\n8.87,79.4,Treatment\n6.78,61.2,Treatment\n' },
  heatmap: { fileName: 'example_heatmap.csv', description: '宽表矩阵：第一列为 ID，其余每列为数值样本。', text: 'gene,Sample_A1,Sample_A2,Sample_B1,Sample_B2\nTP53,8.21,7.95,5.12,5.44\nBRCA1,4.10,4.33,6.78,6.91\nEGFR,9.02,8.87,3.21,3.05\nMYC,6.72,6.34,8.55,8.28\n' },
  'corr-heatmap': { fileName: 'example_correlation.csv', description: '宽表数值矩阵：每个数值列为一个变量，自动计算 Pearson 或 Spearman 相关性。', text: 'gene,Height,Weight,Yield,Chlorophyll\nG1,18.2,5.1,32.8,2.9\nG2,21.5,5.9,39.4,3.2\nG3,16.8,4.7,28.1,2.5\nG4,24.1,6.4,45.3,3.6\n' },
  histogram: { fileName: 'example_histogram.csv', description: '一列数值，另可选一列分组；支持直方图叠加与高斯核密度曲线。', text: 'group,value\nControl,78.2\nControl,81.5\nControl,76.9\nTreatment,92.4\nTreatment,95.1\nTreatment,89.8\n' },
  'mean-error': { fileName: 'example_mean_error.csv', description: '摘要数据：分组、均值和 SD（或 SEM）三列，无需原始重复。', text: 'group,mean,sd\nControl,78.9,2.3\nTreatment_A,92.4,3.1\nTreatment_B,88.7,2.8\n' },
  pca: { fileName: 'example_pca.csv', description: '宽表表达矩阵：第一列为特征 ID，其余列为样本数值。', text: 'gene,Sample_A1,Sample_A2,Sample_B1,Sample_B2\nGene_1,8.2,7.9,5.1,5.4\nGene_2,4.1,4.3,6.8,6.9\nGene_3,9.0,8.8,3.2,3.1\nGene_4,6.7,6.3,8.6,8.3\n' },
  enrichment: { fileName: 'example_enrichment.csv', description: 'clusterProfiler 标准结果：至少包含 ID、Description、GeneRatio、p.adjust、Count，可直接使用富集工具下载的原始 CSV。', text: 'Source,ID,Description,GeneRatio,pvalue,p.adjust,qvalue,Count\nGO:BP,GO:0015979,photosynthesis,28/420,1.2e-12,3.5e-10,2.8e-10,28\nGO:CC,GO:0009523,photosystem II,16/420,8.1e-11,1.1e-8,8.9e-9,16\nGO:MF,GO:0005506,iron ion binding,24/420,3.2e-8,2.4e-6,1.9e-6,24\nKEGG,sly00195,Photosynthesis,21/420,7.8e-10,4.3e-8,3.7e-8,21\nKEGG,sly01100,Metabolic pathways,44/420,2.1e-6,7.8e-5,6.9e-5,44\n' },
  line: { fileName: 'example_line.csv', description: '宽表：第一列为 X，其余每列为一条线；也支持 X + value + line 的长表。', text: 'time,Control,Treatment\n0,10.2,12.1\n24,25.4,18.3\n48,44.1,30.2\n72,55.8,42.4\n' },
  survival: { fileName: 'example_survival.csv', description: '合并表：样本 ID、分组、生存时间、结局状态（1=事件，0=删失）；也支持「表达值 + 随访表」两表模式。', text: SAMPLE_SURVIVAL_COMBINED_CSV },
}

const chartGuides: Record<ChartKind, { purpose: string; why: string; suitableFor: string; reading: string }> = {
  bar: { purpose: '比较不同处理组或条件的平均水平，并同时展示组内重复的离散程度。', why: '当研究重点是组间均值差异时，柱状图能够快速突出效应方向和大小。', suitableFor: '两组或多组重复实验、表达量、丰度、活性和表型指标。', reading: '先看柱高和误差线，再结合原始散点、p 值或显著性字母判断差异是否可靠。' },
  boxplot: { purpose: '概括各组数据的中位数、四分位范围、整体跨度与异常值。', why: '它比仅展示均值更能反映组内变异、偏态和潜在离群点。', suitableFor: '重复数较多、分布可能不对称的表达量、丰度和表型数据。', reading: '比较中位线、箱体高度、须和离群点；箱体重叠较少通常表示组间分布差异更明显。' },
  violin: { purpose: '同时展示数据分布密度、箱线摘要和每个生物学重复。', why: '适合识别双峰、偏态或长尾等箱线图无法完整表达的分布结构。', suitableFor: '样本量相对充足的单细胞指标、表达量、评分和连续表型。', reading: '琴身越宽表示该数值附近数据越集中，并结合内部箱线和散点判断中心与离散程度。' },
  scatter: { purpose: '观察两个连续变量之间的关系，并计算拟合趋势和相关性。', why: '可用于发现正负相关、非线性趋势、分组差异与异常样本。', suitableFor: '基因表达与表型、两个组学指标、剂量与响应等配对数据。', reading: '关注点云方向、拟合线、置信区间、相关系数与决定系数，避免只凭视觉判断相关。' },
  heatmap: { purpose: '以颜色矩阵展示大量特征在多个样本中的相对高低模式。', why: '能够快速识别共同变化的基因模块、样本分群和异常表达模式。', suitableFor: '标准化后的表达矩阵、代谢物丰度、蛋白丰度和通路评分。', reading: '根据色标判断相对高低，并结合行列聚类和样本注释识别模块，而不是比较不同色标下的绝对值。' },
  'corr-heatmap': { purpose: '汇总多个变量两两之间的相关方向与强度。', why: '适合快速发现共线变量、协同变化模块和后续建模中的冗余信息。', suitableFor: '表型指标、环境变量、组学特征摘要和通路活性评分。', reading: '颜色与数值分别表示相关方向和强度；接近 ±1 关系强，接近 0 表示线性或秩相关较弱。' },
  histogram: { purpose: '展示连续变量在不同数值区间中的频数或概率密度。', why: '在统计检验或建模前，可用于判断偏态、长尾、多峰和异常范围。', suitableFor: '测序深度、表达量、质量分数、片段长度和连续表型。', reading: '观察峰的位置、宽度、尾部和组间重叠；分箱数量会影响外观，应结合密度曲线判断。' },
  'mean-error': { purpose: '直接绘制已经汇总好的均值及 SD、SEM 或其他误差范围。', why: '当只有摘要统计或需要清晰比较效应量时，比重复构造原始数据更合适。', suitableFor: '文献汇总、平台输出的均值误差表、时间点或处理组摘要数据。', reading: '比较均值点及误差棒重叠情况，同时明确误差列代表 SD、SEM 还是置信区间。' },
  pca: { purpose: '把高维组学矩阵压缩到主要变异方向，用二维图展示样本整体关系。', why: '常用于质量控制、发现批次效应、检查组间分离和异常样本。', suitableFor: '转录组、蛋白组、代谢组等经过适当标准化的特征 × 样本矩阵。', reading: '坐标轴百分比表示解释方差；样本越近整体谱越相似，分离并不自动等同于统计显著。' },
  enrichment: { purpose: '使用 GO/KEGG 富集结果重新绘制可投稿的气泡图，并自由选择关注的 pathway 或 term。', why: '默认 Top 20 不一定覆盖研究重点，手动筛选可突出与课题相关的生物过程和通路。', suitableFor: 'clusterProfiler 或 CygnusX 富集工具导出的标准 CSV，包含 GeneRatio、p.adjust 和 Count。', reading: 'X 轴表示 GeneRatio，气泡大小表示 Count，颜色表示 -log10(p.adjust)；颜色值越高通常越显著。' },
  line: { purpose: '展示指标随时间、剂量或有序条件变化的趋势。', why: '能够突出变化方向、拐点、响应速度以及不同系列之间的动态差异。', suitableFor: '时间序列、剂量梯度、生长曲线和连续采样实验。', reading: '关注整体趋势和系列间距离；若存在重复测量，应结合误差带判断波动是否稳定。' },
  survival: { purpose: '用 Kaplan–Meier 曲线比较不同分组（或表达高低组）的生存概率随时间的变化。', why: '生存数据含删失，直接比较生存时间会失真；KM 估计与 log-rank 检验是队列预后分析的标准方法。', suitableFor: '临床随访队列（time + status）、按分组或基因表达高低划分的预后比较。', reading: '曲线下降越快表示事件累积越快；结合中位生存期、删失刻度、风险人数表和 log-rank p 值判断组间差异。' },
}
const currentChartGuide = computed(() => chartGuides[chartType.value])
const transformationDescription = computed(() => {
  if (chartType.value === 'heatmap') {
    const normalization = { 'row-zscore': '按行 Z-score（每个特征减去行均值并除以行 SD）', 'column-zscore': '按列 Z-score（每个样本减去列均值并除以列 SD）', log2: 'log2(x + 1)', none: '不做数值转换' }[form.normalization]
    const missing = { 'drop-row': '缺失/非数值行删除', zero: '缺失值填 0', 'row-mean': '缺失值填入该行均值' }[form.missingValue]
    const clustering = form.cluster === 'none' ? '不聚类' : `${form.cluster === 'both' ? '行和列' : form.cluster === 'rows' ? '行' : '列'}聚类（${form.clusterDistance === 'pearson' ? 'Pearson 距离' : '欧氏距离'}）`
    return `当前流程：${missing} → ${normalization} → ${clustering}。色块展示的是转换后的数值，不是原始值。`
  }
  if (chartType.value === 'corr-heatmap') return `当前流程：使用原始数值按 ${form.correlation === 'pearson' ? 'Pearson' : 'Spearman'} 方法计算变量两两相关系数，结果范围为 -1 到 1。`
  if (chartType.value === 'pca') return '当前流程：以每个特征在样本间的均值为中心化基准，基于协方差矩阵提取主成分；未进行额外缩放。'
  if (chartType.value === 'mean-error') return '当前流程：直接使用输入的均值和误差列绘图，不会从摘要数据反推原始重复。'
  if (chartType.value === 'enrichment') return `当前流程：解析标准富集结果 → ${form.selectedEnrichmentIds.length ? `保留手动选择的 ${form.selectedEnrichmentIds.length} 个 pathway/term` : '按 p.adjust 选择 Top 20'} → GeneRatio 映射到 X 轴、Count 映射气泡大小、-log10(p.adjust) 映射颜色。`
  if (chartType.value === 'histogram') return '当前流程：原始数值按分箱统计；开启密度曲线时，额外使用高斯核密度估计进行平滑展示。'
  if (chartType.value === 'survival') {
    const grouping = survivalInputMode.value === 'combined'
      ? '按分组列直接分组'
      : `按表达值${{ median: '中位数二分', optimal: '最佳截点（min p）', custom: `自定义截断值 ${survivalCustomCutoff.value}` }[survivalStrategy.value]}分组`
    return `当前流程：Kaplan–Meier 乘积极限估计（95% CI 为 Greenwood 方差 + log(-log) 变换）→ ${grouping} → log-rank 检验（O−E 法）。全部计算在浏览器本地完成。`
  }
  if (chartType.value === 'bar' || chartType.value === 'boxplot' || chartType.value === 'violin') return '当前流程：保留原始数值，按分组计算均值、SD/SEM/95% CI 或分布摘要；未进行标准化。'
  return '当前流程：保留原始数值，按 X 和系列分组汇总重复值；可选显示 SD 误差带和平滑曲线。'
})

function applyTable(text: string, name: string) {
  const parsed = parseDelimited(text)
  table.value = parsed
  fileName.value = name
  Object.assign(colMap, inferColumnMap(parsed.headers, chartType.value))
  form.selectedEnrichmentIds = []
  if (!parsed.headers.length || !parsed.rows.length) message.error('文件解析失败：请确认文件包含表头和至少一行数据。')
}

function downloadText(text: string, name: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

function loadExample(downloadOnly = false) {
  const example = examples[chartType.value]
  if (downloadOnly) { downloadText(example.text, example.fileName, 'text/csv;charset=utf-8'); return }
  applyTable(example.text, example.fileName)
  message.success(`已加载 ${chartLabel.value} 示例数据`)
}

function handleFileChange({ fileList }: { fileList: UploadFileInfo[] }) {
  const file = fileList[fileList.length - 1]?.file
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => applyTable(String(reader.result ?? ''), file.name)
  reader.onerror = () => message.error('读取文件失败，请重试。')
  reader.readAsText(file)
}

function handleFollowupChange({ fileList }: { fileList: UploadFileInfo[] }) {
  const file = fileList[fileList.length - 1]?.file
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const parsed = parseDelimited(String(reader.result ?? ''))
    followTable.value = parsed
    followFileName.value = file.name
    if (!parsed.headers.length || !parsed.rows.length) message.error('随访表解析失败：请确认文件包含表头和至少一行数据。')
  }
  reader.onerror = () => message.error('读取随访表失败，请重试。')
  reader.readAsText(file)
}

function loadSurvivalExpressionExample() {
  applyTable(SAMPLE_EXPRESSION_CSV, 'example_expression.csv')
  followTable.value = parseDelimited(SAMPLE_FOLLOWUP_CSV)
  followFileName.value = 'example_followup.csv'
  message.success('已加载表达值表与随访表示例（同一批样本）。')
}

function handleAnnotationUpload({ fileList }: { fileList: UploadFileInfo[] }) {
  const file = fileList[fileList.length - 1]?.file
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    const parsed = parseDelimited(String(reader.result ?? ''))
    const sampleColumn = parsed.headers.find((header) => header.toLowerCase() === 'sample')
    const groupColumn = parsed.headers.find((header) => header.toLowerCase() === 'group')
    if (!sampleColumn || !groupColumn) { message.error('注释文件需要 sample 和 group 两列。'); return }
    form.sampleAnnotations = Object.fromEntries(parsed.rows.map((row) => [row[sampleColumn].trim(), row[groupColumn].trim()]).filter(([sample, group]) => sample && group))
    message.success(`已读取 ${Object.keys(form.sampleAnnotations).length} 个样本注释。`)
  }
  reader.readAsText(file)
}

function changeChart(kind: ChartKind) {
  chartType.value = kind
  posthocResult.value = null
  form.posthocLetters = {}
  form.selectedEnrichmentIds = []
  loadExample()
}

async function loadPosthoc() {
  const groups: Record<string, number[]> = {}
  table.value.rows.forEach((row) => {
    const group = row[colMap.group]?.trim()
    const value = Number(row[colMap.value])
    if (group && Number.isFinite(value)) (groups[group] ??= []).push(value)
  })
  if (Object.keys(groups).length < 3 || Object.values(groups).some((values) => values.length < 2)) {
    message.warning('至少需要 3 个分组，且每组至少 2 个有效重复。')
    return
  }
  posthocLoading.value = true
  try {
    posthocResult.value = await fetchPosthocComparisons({ groups, method: 'tukey', adjust: 'fdr_bh' })
    form.posthocLetters = posthocResult.value.letters
    message.success('已生成 Tukey 事后比较与字母分组。')
  } catch {
    message.error('事后比较计算失败，请确认后端统计服务可用。')
  } finally {
    posthocLoading.value = false
  }
}

function exportStatistics() {
  const baseRows = result.value.statistics.length ? result.value.statistics : result.value.summaries.map((summary) => ({ group: summary.group, n: summary.n, mean: summary.mean, sd: summary.sd }))
  const posthocRows = posthocResult.value?.comparisons.map((comparison) => ({ comparison: `${comparison.group_a} vs ${comparison.group_b}`, method: posthocResult.value?.method ?? '', adjustment: posthocResult.value?.adjust ?? '', p_value: comparison.p_value })) ?? []
  const csv = resultToCsv([...baseRows, ...posthocRows])
  if (!csv) { message.warning('当前图表没有可导出的统计结果。'); return }
  downloadText(csv, chartType.value === 'enrichment' ? 'enrichment_selected_results.csv' : `plot_workshop_${chartType.value}_statistics.csv`, 'text/csv;charset=utf-8')
}

function exportImage(format: 'png' | 'svg') {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container || !result.value.traces.length) return
  const width = form.exportCustomSize ? form.exportWidth : form.plotWidth
  const height = form.exportCustomSize ? form.exportHeight : form.plotHeight
  if (format === 'svg') {
    Plotly.downloadImage(container, { format, width, height, filename: `plot_workshop_${chartType.value}` })
    return
  }
  Plotly.downloadImage(container, { format, width, height, scale: exportDpi.value / 96, filename: `plot_workshop_${chartType.value}_${exportDpi.value}dpi` } as any)
}

function resetView() {
  const container = document.getElementById(PLOT_DIV_ID)
  if (container) Plotly.relayout(container, { 'xaxis.autorange': true, 'yaxis.autorange': true })
}

function resetAll() {
  Object.assign(form, { ...DEFAULT_WORKSHOP_CONFIG, exportCustomSize: false, exportWidth: 1200, exportHeight: 800 })
  loadExample()
}

function renderPlot() {
  const container = document.getElementById(PLOT_DIV_ID)
  if (!container) return
  const current = result.value
  if (!current.traces.length) { Plotly.purge(container); return }
  plotting.value = true
  const layout = applyConfiguredAxisRanges(current.layout)
  if (isDark.value) {
    Object.assign(layout, { paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { ...(layout.font ?? {}), color: '#e2e8f0' } })
    layout.xaxis = { ...(layout.xaxis ?? {}), gridcolor: '#334155', zerolinecolor: '#475569' }
    layout.yaxis = { ...(layout.yaxis ?? {}), gridcolor: '#334155', zerolinecolor: '#475569' }
  }
  nextTick(() => {
    Plotly.react(container, current.traces, layout, { ...current.config, scrollZoom: true })
      .finally(() => { plotting.value = false })
  })
}

let renderTimer: ReturnType<typeof setTimeout> | undefined
function scheduleRender() {
  if (renderTimer) clearTimeout(renderTimer)
  renderTimer = setTimeout(renderPlot, 80)
}

watch(() => [chartType.value, table.value, colMap, form, isDark.value], scheduleRender, { deep: true })
watch(isFullscreen, () => nextTick(() => { window.dispatchEvent(new Event('resize')); renderPlot() }))
onMounted(() => loadExample())
onUnmounted(() => {
  if (renderTimer) clearTimeout(renderTimer)
  const container = document.getElementById(PLOT_DIV_ID)
  if (container) Plotly.purge(container)
})
</script>

<template>
  <div class="workshop-page">
    <PageHeader title="组学绘图工坊" subtitle="上传数据、即时校验、交互绘图并导出高清图表" back-to="/tools" back-label="返回工具箱" />

    <div class="workshop-layout">
      <aside class="parameter-panel">
        <NCollapse :default-expanded-names="['data', 'core', 'style', 'export']" arrow-placement="left">
          <NCollapseItem title="数据上传与列映射" name="data">
            <template #header-extra>
              <NButton text size="tiny" class="sample-link" @click.stop="loadExample()">
                <template #icon><NIcon><SparklesOutline /></NIcon></template>
                试试示例数据
              </NButton>
            </template>
            <NSelect :value="chartType" :options="chartOptions" size="small" @update:value="(value) => changeChart(value as ChartKind)" />
            <NUpload accept=".csv,.tsv,.txt" :max="1" :default-upload="false" @change="handleFileChange"><NButton block size="small" class="upload-button">上传 CSV / TSV</NButton></NUpload>
            <p class="file-state">{{ fileName || '尚未上传文件' }}</p>
            <NCard size="small" class="format-card" :bordered="false"><strong>格式要求</strong><p>{{ examples[chartType].description }}</p><code>{{ examples[chartType].text.split('\n').slice(0, 3).join('\n') }}</code></NCard>
            <NButton text size="tiny" class="sample-file-link" @click="loadExample(true)">
              <template #icon><NIcon><DownloadOutline /></NIcon></template>
              下载示例文件（.csv）
            </NButton>
            <div v-if="table.headers.length" class="mapping-grid">
              <template v-if="chartType === 'survival'">
                <NAlert type="info" :show-icon="true" :bordered="false" style="margin-bottom: 8px">纯本地运算，数据不离开浏览器。</NAlert>
                <label>输入方式</label>
                <NRadioGroup v-model:value="survivalInputMode" size="small">
                  <NRadioButton value="combined">合并表</NRadioButton>
                  <NRadioButton value="expression">表达值 + 随访表</NRadioButton>
                </NRadioGroup>
                <template v-if="survivalInputMode === 'combined'">
                  <p class="axis-range-hint">状态兼容 1/0、Dead/Alive、Event/Censored、DECEASED/LIVING。</p>
                  <label>生存时间列</label><NSelect v-model:value="colMap.x" :options="columnOptions" size="small" />
                  <label>结局状态列</label><NSelect v-model:value="colMap.y" :options="columnOptions" size="small" />
                  <label>分组列（可选）</label><NSelect v-model:value="colMap.group" clearable :options="columnOptions" size="small" />
                </template>
                <template v-else>
                  <label>样本 ID 列（表达值表）</label><NSelect v-model:value="colMap.id" :options="columnOptions" size="small" />
                  <label>表达值列</label><NSelect v-model:value="colMap.value" :options="columnOptions" size="small" />
                  <label>随访表</label>
                  <NUpload accept=".csv,.tsv,.txt" :max="1" :default-upload="false" @change="handleFollowupChange"><NButton block size="small" class="upload-button">上传随访表</NButton></NUpload>
                  <p class="file-state">{{ followFileName || '尚未上传随访表' }}</p>
                  <NButton block size="small" secondary @click="loadSurvivalExpressionExample">载入配套示例（表达值 + 随访表）</NButton>
                  <p class="axis-range-hint">随访表需包含样本 ID、生存时间与结局状态列（自动识别）；两表按样本 ID 内连接。</p>
                  <p v-if="result.survival?.joinMatched != null" class="axis-range-hint">已匹配 {{ result.survival.joinMatched }} 个样本。</p>
                  <label>分组方式</label>
                  <NRadioGroup v-model:value="survivalStrategy" size="small">
                    <NRadioButton value="median">中位数</NRadioButton>
                    <NRadioButton value="optimal">最佳截点</NRadioButton>
                    <NRadioButton value="custom">自定义</NRadioButton>
                  </NRadioGroup>
                  <template v-if="survivalStrategy === 'custom'"><label>截断值</label><NInputNumber v-model:value="survivalCustomCutoff" :show-button="false" size="small" :step="0.1" /></template>
                  <NAlert v-if="survivalStrategy === 'optimal'" type="warning" :show-icon="true" :bordered="false" style="margin-top: 8px">最佳截点（min p）存在多重检验偏倚，p 值偏乐观。</NAlert>
                </template>
              </template>
              <template v-else-if="chartType === 'enrichment'"><NAlert type="info" :show-icon="false" :bordered="false">标准富集列会自动识别，不需要手动映射。</NAlert></template>
              <template v-else-if="chartType === 'heatmap' || chartType === 'corr-heatmap' || chartType === 'pca'"><label>ID 列</label><NSelect v-model:value="colMap.id" :options="columnOptions" size="small" /></template>
              <template v-else-if="chartType === 'scatter'"><label>X 数值列</label><NSelect v-model:value="colMap.x" :options="columnOptions" size="small" /><label>Y 数值列</label><NSelect v-model:value="colMap.y" :options="columnOptions" size="small" /><label>分组列（可选）</label><NSelect v-model:value="colMap.group" clearable :options="columnOptions" size="small" /></template>
              <template v-else-if="chartType === 'mean-error'"><label>分组列</label><NSelect v-model:value="colMap.group" :options="columnOptions" size="small" /><label>均值列</label><NSelect v-model:value="colMap.value" :options="columnOptions" size="small" /><label>误差列（SD / SEM）</label><NSelect v-model:value="colMap.error" :options="columnOptions" size="small" /></template>
              <template v-else-if="chartType === 'histogram'"><label>数值列</label><NSelect v-model:value="colMap.value" :options="columnOptions" size="small" /><label>分组列（可选）</label><NSelect v-model:value="colMap.group" clearable :options="columnOptions" size="small" /></template>
              <template v-else-if="chartType === 'line'"><label>X 列</label><NSelect v-model:value="colMap.x" :options="columnOptions" size="small" /><label>数值列（长表）</label><NSelect v-model:value="colMap.value" clearable :options="columnOptions" size="small" /><label>系列列（长表）</label><NSelect v-model:value="colMap.series" clearable :options="columnOptions" size="small" /></template>
              <template v-else><label>分组列</label><NSelect v-model:value="colMap.group" :options="columnOptions" size="small" /><label>数值列</label><NSelect v-model:value="colMap.value" :options="columnOptions" size="small" /></template>
            </div>
            <div class="validation-list"><NAlert v-for="(item, index) in result.messages" :key="`${item.text}-${index}`" :type="item.severity" :show-icon="true" :bordered="false">{{ item.text }}</NAlert></div>
          </NCollapseItem>

          <NCollapseItem title="核心计算" name="core">
            <template v-if="chartType === 'survival'"><div class="switch-row"><span>95% 置信区间带</span><NSwitch v-model:value="survivalShowCI" size="small" /></div><div class="switch-row"><span>显示删失点</span><NSwitch v-model:value="survivalShowCensors" size="small" /></div><div class="switch-row"><span>风险人数表</span><NSwitch v-model:value="survivalShowRiskTable" size="small" /></div></template>
            <template v-else-if="chartType === 'enrichment'"><label>选择 pathway / GO term</label><NSelect v-model:value="form.selectedEnrichmentIds" multiple filterable clearable max-tag-count="responsive" size="small" placeholder="不选择时按 p.adjust 展示 Top 20" :options="enrichmentPathwayOptions" /><p class="axis-range-hint">可搜索 ID 或描述并多选；选择后只重绘这些结果，不修改原始 CSV。</p><NButton block size="small" secondary @click="form.selectedEnrichmentIds = []">恢复 p.adjust Top 20</NButton></template>
            <template v-else-if="chartType === 'heatmap'"><label>标准化</label><NSelect v-model:value="form.normalization" size="small" :options="[{ label: '行 Z-score', value: 'row-zscore' }, { label: '列 Z-score', value: 'column-zscore' }, { label: 'log2(x+1)', value: 'log2' }, { label: '无', value: 'none' }]" /><label>缺失值处理</label><NSelect v-model:value="form.missingValue" size="small" :options="[{ label: '删除该行', value: 'drop-row' }, { label: '填 0', value: 'zero' }, { label: '填行均值', value: 'row-mean' }]" /><label>聚类</label><NSelect v-model:value="form.cluster" size="small" :options="[{ label: '无', value: 'none' }, { label: '行', value: 'rows' }, { label: '列', value: 'columns' }, { label: '双向', value: 'both' }]" /><label v-if="form.cluster !== 'none'">距离</label><NSelect v-if="form.cluster !== 'none'" v-model:value="form.clusterDistance" size="small" :options="[{ label: '欧氏距离', value: 'euclidean' }, { label: 'Pearson 相关', value: 'pearson' }]" /><div class="switch-row"><span>显示单元格数值</span><NSwitch v-model:value="form.showValues" size="small" /></div><NUpload accept=".csv,.tsv,.txt" :max="1" :default-upload="false" @change="handleAnnotationUpload"><NButton block size="small">上传样本注释</NButton></NUpload><p class="file-state">注释格式：sample,group</p></template>
            <template v-else-if="chartType === 'pca'"><NUpload accept=".csv,.tsv,.txt" :max="1" :default-upload="false" @change="handleAnnotationUpload"><NButton block size="small">上传样本分组注释</NButton></NUpload><p class="file-state">注释格式：sample,group；未上传时根据样本名末尾重复编号自动推断分组。</p></template>
            <template v-else-if="chartType === 'corr-heatmap'"><label>相关性方法</label><NSelect v-model:value="form.correlation" size="small" :options="[{ label: 'Pearson r', value: 'pearson' }, { label: 'Spearman ρ', value: 'spearman' }]" /></template>
            <template v-else-if="chartType === 'histogram'"><label>分箱数</label><NInputNumber v-model:value="form.binCount" :min="5" :max="100" size="small" /><div class="switch-row"><span>显示密度曲线</span><NSwitch v-model:value="form.showDensity" size="small" /></div></template>
            <template v-else-if="chartType === 'scatter'"><label>拟合方法</label><NSelect v-model:value="form.regression" size="small" :options="[{ label: '线性回归', value: 'linear' }, { label: '二次多项式', value: 'quadratic' }, { label: '三次多项式', value: 'cubic' }, { label: 'LOESS 平滑', value: 'loess' }]" /><label>相关系数</label><NSelect v-model:value="form.correlation" size="small" :options="[{ label: 'Pearson r', value: 'pearson' }, { label: 'Spearman ρ', value: 'spearman' }]" /><div class="switch-row"><span>95% 置信带</span><NSwitch v-model:value="form.showConfidence" size="small" /></div></template>
            <template v-else-if="chartType === 'bar' || chartType === 'boxplot' || chartType === 'violin'"><label>两组检验</label><NSelect v-model:value="form.testMethod" size="small" :options="[{ label: 'Student t', value: 'student' }, { label: 'Welch t', value: 'welch' }, { label: 'Mann–Whitney U', value: 'mann-whitney' }]" /><label v-if="chartType === 'bar'">误差棒</label><NSelect v-if="chartType === 'bar'" v-model:value="form.errorBar" size="small" :options="[{ label: 'SD', value: 'sd' }, { label: 'SEM', value: 'sem' }, { label: '95% CI', value: 'ci95' }]" /><div class="switch-row"><span>显示全部重复点</span><NSwitch v-model:value="form.showPoints" size="small" /></div><div v-if="chartType === 'boxplot'" class="switch-row"><span>缺口箱线</span><NSwitch v-model:value="form.notch" size="small" /></div><NButton size="small" block :loading="posthocLoading" @click="loadPosthoc">计算 Tukey 字母分组</NButton><div class="switch-row"><span>显示显著性横线</span><NSwitch v-model:value="form.showSignificance" size="small" /></div><label>显著性标注</label><NSelect v-model:value="form.significanceDisplay" size="small" :options="[{ label: '显示 p 值', value: 'p-value' }, { label: '显示星号', value: 'stars' }]" /></template>
            <template v-else><div class="switch-row"><span>显示数据点</span><NSwitch v-model:value="form.showPoints" size="small" /></div><div class="switch-row"><span>平滑曲线</span><NSwitch v-model:value="form.smoothLine" size="small" /></div><div class="switch-row"><span>重复 X 的 SD 误差带</span><NSwitch v-model:value="form.showLineError" size="small" /></div></template>
          </NCollapseItem>

          <NCollapseItem title="颜色、坐标轴与标题" name="style">
            <template v-if="chartType === 'heatmap' || chartType === 'corr-heatmap' || chartType === 'enrichment'"><label>连续色板</label><NSelect v-model:value="form.continuousPalette" :options="continuousOptions" size="small" /></template>
            <template v-else><label>离散色板</label><NSelect v-model:value="form.discretePalette" :options="discreteOptions" size="small" /></template>
            <label>主标题</label><NInput v-model:value="form.title" size="small" placeholder="留空使用默认标题" /><label>X 轴标题</label><NInput v-model:value="form.xTitle" size="small" placeholder="自动使用映射列名" /><label>Y 轴标题</label><NInput v-model:value="form.yTitle" size="small" placeholder="自动使用映射列名" />
            <label>X 轴范围</label><NSelect v-model:value="form.xRangeMode" size="small" :options="[{ label: '自动', value: 'auto' }, { label: '手动', value: 'manual' }]" /><div v-if="form.xRangeMode === 'manual'" class="two-input"><NInputNumber v-model:value="form.xMin" :min="-1000000000" :max="1000000000" placeholder="最小值" size="small" /><NInputNumber v-model:value="form.xMax" :min="-1000000000" :max="1000000000" placeholder="最大值" size="small" /></div>
            <label>Y 轴范围</label><NSelect v-model:value="form.yRangeMode" size="small" :options="[{ label: '自动', value: 'auto' }, { label: '手动', value: 'manual' }]" /><div v-if="form.yRangeMode === 'manual'" class="two-input"><NInputNumber v-model:value="form.yMin" :min="-1000000000" :max="1000000000" placeholder="最小值" size="small" /><NInputNumber v-model:value="form.yMax" :min="-1000000000" :max="1000000000" placeholder="最大值" size="small" /></div>
            <p class="axis-range-hint">分类轴会自动管理范围；手动范围需满足最小值小于最大值。</p>
            <label>图表宽度（px）</label><NInputNumber v-model:value="form.plotWidth" :min="420" :max="4000" :step="20" size="small" />
            <label>图表高度（px）</label><NInputNumber v-model:value="form.plotHeight" :min="360" :max="4000" :step="20" size="small" />
            <label>图例位置</label><NSelect v-model:value="form.legendPosition" size="small" :options="[{ label: '顶部', value: 'top' }, { label: '底部', value: 'bottom' }, { label: '左侧', value: 'left' }, { label: '右侧', value: 'right' }]" />
            <label>图例排列</label><NSelect v-model:value="form.legendOrientation" size="small" :options="[{ label: '自动', value: 'auto' }, { label: '横向', value: 'h' }, { label: '纵向', value: 'v' }]" />
            <label>图例字号</label><NSlider v-model:value="form.legendFontSize" :min="8" :max="24" :step="1" />
            <template v-if="chartType === 'bar'"><label>柱子宽度</label><NSlider v-model:value="form.barWidth" :min="0.1" :max="0.95" :step="0.05" /><p class="control-value">当前宽度：{{ form.barWidth.toFixed(2) }}</p></template>
            <label>线条 / 误差线宽度</label><NSlider v-model:value="form.lineWidth" :min="1" :max="8" :step="0.5" />
            <template v-if="chartType === 'boxplot' || chartType === 'violin'"><label>箱体 / 琴身宽度</label><NSlider v-model:value="form.distributionWidth" :min="0.2" :max="0.95" :step="0.05" /></template>
            <template v-if="chartType === 'histogram'"><label>直方图柱间距</label><NSlider v-model:value="form.histogramGap" :min="0" :max="0.8" :step="0.05" /></template>
            <template v-if="chartType === 'scatter'"><label>点大小</label><NSlider v-model:value="form.pointSize" :min="4" :max="20" /></template>
          </NCollapseItem>

          <NCollapseItem title="导出" name="export">
            <label>PNG 分辨率</label><NSelect v-model:value="exportDpi" size="small" :options="[{ label: '300 DPI', value: 300 }, { label: '600 DPI', value: 600 }, { label: '1000 DPI', value: 1000 }]" /><div class="switch-row"><span>自定义尺寸</span><NSwitch v-model:value="form.exportCustomSize" size="small" /></div><div v-if="form.exportCustomSize" class="two-input"><NInputNumber v-model:value="form.exportWidth" :min="100" :max="8000" size="small" /><NInputNumber v-model:value="form.exportHeight" :min="100" :max="8000" size="small" /></div>
            <NSpace vertical :size="8"><NButton block size="small" :disabled="hasErrors" @click="exportImage('png')">导出 PNG</NButton><NButton block size="small" :disabled="hasErrors" @click="exportImage('svg')">导出 SVG</NButton><NButton block size="small" :disabled="!result.statistics.length && !result.summaries.length" @click="exportStatistics">{{ chartType === 'enrichment' ? '导出当前筛选 CSV' : '导出统计 CSV' }}</NButton></NSpace>
          </NCollapseItem>
        </NCollapse>
        <NButton block quaternary size="small" class="reset-button" @click="resetAll"><template #icon><NIcon><RefreshOutline /></NIcon></template>重置当前图表</NButton>
      </aside>

      <main class="plot-area" :class="{ fullscreen: isFullscreen }">
        <div class="plot-actions"><NTag :type="hasErrors ? 'error' : 'success'" size="small">{{ result.validRows }} 条有效数据</NTag><NSpace><NButton size="tiny" @click="resetView"><template #icon><NIcon><ContractOutline /></NIcon></template>重置视图</NButton><NButton size="tiny" @click="isFullscreen = !isFullscreen"><template #icon><NIcon><ExpandOutline /></NIcon></template>{{ isFullscreen ? '退出全屏' : '全屏' }}</NButton></NSpace></div>
        <div v-if="!hasErrors" class="plot-stage"><div :id="PLOT_DIV_ID" class="plot-canvas" :style="plotCanvasStyle" /></div>
        <NEmpty v-else description="修正数据或列映射后即可生成图表" class="plot-empty" />
        <p class="plot-hint">拖动缩放、悬停查看详情；导出图与当前配色、标题及筛选状态保持一致。</p>
      </main>

      <aside class="result-panel">
        <NCard size="small" :title="`${chartLabel}说明`" :segmented="{ content: true }" class="guide-card">
          <div class="guide-section"><strong>图表作用</strong><p>{{ currentChartGuide.purpose }}</p></div>
          <div class="guide-section"><strong>为什么绘制</strong><p>{{ currentChartGuide.why }}</p></div>
          <div class="guide-section"><strong>适用数据</strong><p>{{ currentChartGuide.suitableFor }}</p></div>
          <div class="guide-section"><strong>如何解读</strong><p>{{ currentChartGuide.reading }}</p></div><div class="guide-section conversion-guide"><strong>本次绘图的数值转换</strong><p>{{ transformationDescription }}</p></div>
        </NCard>
        <NCard size="small" title="数据摘要" :segmented="{ content: true }"><div class="metric"><strong>{{ result.validRows }}</strong><span>有效数据行</span></div><div v-for="summary in result.summaries" :key="summary.group" class="summary-row"><span>{{ summary.group }}</span><span>n={{ summary.n }} · {{ summary.mean.toFixed(3) }} ± {{ summary.sd.toFixed(3) }}</span></div><p v-if="!result.summaries.length" class="muted">{{ chartType === 'scatter' ? '回归、相关性与 p 值在下方结果中显示。' : '当前图表不需要分组汇总。' }}</p></NCard>
        <NCard size="small" title="统计结果" :segmented="{ content: true }" class="statistics-card"><div v-if="result.statistics.length" class="statistics-list"><div v-for="(row, rowIndex) in result.statistics" :key="rowIndex" class="stat-row"><template v-for="(value, key) in row" :key="String(key)"><span>{{ key }}</span><strong>{{ value }}</strong></template></div></div><NEmpty v-else size="small" description="暂无可用统计结果" /></NCard>
        <NCard v-if="chartType === 'survival' && result.survival" size="small" title="生存分析结果" :segmented="{ content: true }" class="statistics-card">
          <div class="statistics-list">
            <div v-for="group in result.survival.groups" :key="group.name" class="stat-row">
              <span>分组</span><strong>{{ group.name }}</strong>
              <span>n / 事件 / 删失</span><strong>{{ group.n }} / {{ group.events }} / {{ group.censored }}</strong>
              <span>中位生存</span><strong>{{ group.medianSurvival === null ? 'NR' : group.medianSurvival.toFixed(2) }}</strong>
            </div>
            <div v-if="result.survival.logRank" class="stat-row">
              <span>Log-rank</span><strong>χ²({{ result.survival.logRank.df }}) = {{ result.survival.logRank.chi2.toFixed(3) }}</strong>
              <span>p 值</span><strong>{{ result.survival.logRank.p < 0.001 ? result.survival.logRank.p.toExponential(3) : result.survival.logRank.p.toFixed(4) }}</strong>
            </div>
            <div v-if="result.survival.cutoff !== null" class="stat-row">
              <span>分组截断值</span><strong>{{ result.survival.cutoff.toFixed(4) }}</strong>
              <span v-if="result.survival.optimalP !== null">最小 p</span><strong v-if="result.survival.optimalP !== null">{{ result.survival.optimalP.toExponential(3) }}</strong>
            </div>
            <NAlert v-if="result.survival.strategy === 'optimal'" type="warning" :show-icon="true" :bordered="false">最佳截点（min p）分组存在多重检验偏倚，上述 p 值偏乐观，建议用独立队列验证。</NAlert>
            <NCollapse v-if="result.survival.pairwise.length" arrow-placement="left">
              <NCollapseItem title="两两比较 p 值" name="pairwise">
                <div class="statistics-list"><div v-for="pair in result.survival?.pairwise ?? []" :key="`${pair.groupA}-${pair.groupB}`" class="stat-row"><span>{{ pair.groupA }} vs {{ pair.groupB }}</span><strong>χ² = {{ pair.chi2.toFixed(3) }} · p {{ pair.p < 0.001 ? '< 0.001' : `= ${pair.p.toFixed(4)}` }}</strong></div></div>
              </NCollapseItem>
            </NCollapse>
          </div>
        </NCard>
        <NCard v-if="posthocResult" size="small" title="两两比较 p 值" :segmented="{ content: true }" class="statistics-card"><div class="statistics-list"><div v-for="comparison in posthocResult.comparisons" :key="`${comparison.group_a}-${comparison.group_b}`" class="stat-row"><span>comparison</span><strong>{{ comparison.group_a }} vs {{ comparison.group_b }}</strong><span>{{ posthocResult.method }} · {{ posthocResult.adjust }}</span><strong>p={{ comparison.p_value.toExponential(3) }}</strong></div></div></NCard>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.workshop-page { min-height: 100%; padding: 40px 24px 24px; color: var(--text-color-1, #1e293b); box-sizing: border-box; }
.page-toolbar { display: flex; align-items: center; gap: 18px; min-height: 70px; border-bottom: 1px solid var(--border-color, #e2e8f0); }
.toolbar-title { flex: 1; }.toolbar-title h1 { margin: 0; font-size: 20px; }.toolbar-title span, .file-state, .plot-hint, .muted { color: var(--text-color-3, #64748b); font-size: 12px; }
.workshop-layout { display: grid; grid-template-columns: 280px minmax(480px, 1fr) 270px; gap: 16px; padding-top: 16px; align-items: start; }
.parameter-panel, .result-panel { border: 1px solid var(--border-color, #e2e8f0); border-radius: 12px; background: var(--card-color, #fff); padding: 8px; max-height: calc(100vh - 118px); overflow: auto; }
.parameter-panel :deep(.n-collapse-item__content-wrapper) { padding: 0 4px 10px; }.parameter-panel label { display: block; margin: 10px 0 5px; font-size: 12px; color: var(--text-color-2, #475569); }.upload-button { margin-top: 10px; }.file-state { margin: 7px 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.format-card { margin: 8px 0; background: var(--code-color, #f8fafc); }.sample-file-link { margin: 0 0 6px; }.format-card p { margin: 5px 0; font-size: 12px; color: var(--text-color-2, #475569); }.format-card code { display: block; white-space: pre-wrap; font-size: 11px; color: #0369a1; }.control-value { margin: 3px 0 0; color: var(--text-color-3, #64748b); font-size: 11px; }.mapping-grid { display: grid; grid-template-columns: 1fr; }.validation-list { display: grid; gap: 6px; margin-top: 10px; }.validation-list :deep(.n-alert) { padding: 7px 9px; font-size: 12px; }.switch-row { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; font-size: 12px; }.two-input { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }.reset-button { margin-top: 10px; }
.plot-area { min-width: 0; min-height: 660px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 12px; background: var(--card-color, #fff); padding: 12px; display: flex; flex-direction: column; }.plot-area.fullscreen { position: fixed; z-index: 20; inset: 14px; min-height: auto; box-shadow: 0 18px 48px rgb(15 23 42 / 22%); }.plot-actions { display: flex; justify-content: space-between; align-items: center; gap: 8px; }.plot-stage { flex: 1; min-height: 570px; overflow: auto; display: grid; place-items: start center; padding: 8px 0; }.plot-canvas { flex: none; max-width: none; }.plot-empty { flex: 1; display: grid; place-items: center; }.plot-hint { margin: 2px 0 0; }
.result-panel { display: grid; gap: 12px; }.guide-card { border-top: 3px solid #0072B2; }.guide-section + .guide-section { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider-color, #f1f5f9); }.guide-section strong { color: var(--text-color-1, #1e293b); font-size: 12px; }.guide-section p { margin: 4px 0 0; color: var(--text-color-2, #475569); font-size: 12px; line-height: 1.65; }.metric { display: grid; gap: 2px; margin-bottom: 10px; }.metric strong { font-size: 26px; color: #0072B2; }.metric span { font-size: 12px; color: var(--text-color-3, #64748b); }.summary-row { display: flex; justify-content: space-between; gap: 8px; padding: 7px 0; border-top: 1px solid var(--divider-color, #f1f5f9); font-size: 12px; }.summary-row span:last-child { text-align: right; color: var(--text-color-2, #475569); }.statistics-card { max-height: 440px; overflow: auto; }.statistics-list { display: grid; gap: 8px; }.stat-row { display: grid; grid-template-columns: minmax(85px, 1fr) minmax(90px, 1.25fr); gap: 3px 9px; padding: 8px; border-radius: 7px; background: var(--code-color, #f8fafc); font-size: 11px; }.stat-row span { color: var(--text-color-3, #64748b); text-transform: capitalize; }.stat-row strong { font-weight: 600; overflow-wrap: anywhere; }
@media (max-width: 1280px) { .workshop-layout { grid-template-columns: 260px minmax(420px, 1fr); }.result-panel { grid-column: 1 / -1; grid-template-columns: 1fr 1fr; max-height: none; }.statistics-card { max-height: 280px; } }
@media (max-width: 840px) { .workshop-page { padding: 24px 12px 16px; }.page-toolbar { flex-wrap: wrap; padding: 12px 0; }.workshop-layout { grid-template-columns: 1fr; }.parameter-panel, .result-panel { max-height: none; }.plot-area { min-height: 500px; }.plot-stage { min-height: 420px; }.result-panel { grid-template-columns: 1fr; } }
</style>
