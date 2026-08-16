/**
 * Pure data processing functions used by PlotWorkshopView.
 * Parsing, validation, statistics and Plotly configuration live here so the
 * view only owns user interaction and reactive state.
 */
import * as Plotly from 'plotly.js-dist-min'
import Papa from 'papaparse'
import { computePCA, type ExpressionMatrix } from '@/utils/geneExpressionProcessor'
import {
  CONTINUOUS_PALETTES,
  DISCRETE_PALETTES,
  type ContinuousPaletteName,
  type DiscretePaletteName,
} from '@/components/charts/palettes'
import { wrapEnrichmentLabel } from '@/utils/enrichmentProcessor'
import { kaplanMeier } from '@/utils/survival/kmEstimator'
import { logRankTest } from '@/utils/survival/logRankTest'
import { groupByExpression, joinExpressionFollowup, parseSurvivalRecords } from '@/utils/survival/survivalData'
import { buildSurvivalFigure } from '@/utils/survival/survivalPlot'
import type { LogRankPair, SurvivalGroupStrategy, SurvivalRecord } from '@/utils/survival/survivalTypes'

export type ChartKind = 'bar' | 'line' | 'scatter' | 'heatmap' | 'corr-heatmap' | 'boxplot' | 'violin' | 'histogram' | 'mean-error' | 'pca' | 'enrichment' | 'survival'
export type Severity = 'success' | 'warning' | 'error'
export type Normalization = 'row-zscore' | 'column-zscore' | 'log2' | 'none'
export type ErrorBarMode = 'sd' | 'sem' | 'ci95'

export interface ChartColumnRequirement {
  role: keyof ColumnMap
  label: string
  type: 'numeric' | 'category' | 'id'
  optional?: boolean
}

export interface ChartDefinition {
  kind: ChartKind
  label: string
  requiredColumns: ChartColumnRequirement[]
}

export const CHART_DEFINITIONS: Record<ChartKind, ChartDefinition> = {
  bar: { kind: 'bar', label: '分组柱状图', requiredColumns: [{ role: 'group', label: '分组列', type: 'category' }, { role: 'value', label: '数值列', type: 'numeric' }] },
  line: { kind: 'line', label: '折线图', requiredColumns: [{ role: 'x', label: 'X 列', type: 'numeric' }, { role: 'value', label: '数值列', type: 'numeric', optional: true }, { role: 'series', label: '系列列', type: 'category', optional: true }] },
  scatter: { kind: 'scatter', label: '散点拟合图', requiredColumns: [{ role: 'x', label: 'X 数值列', type: 'numeric' }, { role: 'y', label: 'Y 数值列', type: 'numeric' }, { role: 'group', label: '分组列', type: 'category', optional: true }] },
  heatmap: { kind: 'heatmap', label: '表达热图', requiredColumns: [{ role: 'id', label: 'ID 列', type: 'id' }] },
  'corr-heatmap': { kind: 'corr-heatmap', label: '相关性热图', requiredColumns: [{ role: 'id', label: 'ID 列', type: 'id', optional: true }] },
  boxplot: { kind: 'boxplot', label: '分组箱线图', requiredColumns: [{ role: 'group', label: '分组列', type: 'category' }, { role: 'value', label: '数值列', type: 'numeric' }] },
  violin: { kind: 'violin', label: '小提琴图', requiredColumns: [{ role: 'group', label: '分组列', type: 'category' }, { role: 'value', label: '数值列', type: 'numeric' }] },
  histogram: { kind: 'histogram', label: '直方图 / 密度图', requiredColumns: [{ role: 'value', label: '数值列', type: 'numeric' }, { role: 'group', label: '分组列', type: 'category', optional: true }] },
  'mean-error': { kind: 'mean-error', label: '均值误差棒点图', requiredColumns: [{ role: 'group', label: '分组列', type: 'category' }, { role: 'value', label: '均值列', type: 'numeric' }, { role: 'error', label: '误差列', type: 'numeric' }] },
  pca: { kind: 'pca', label: 'PCA 主成分分析', requiredColumns: [{ role: 'id', label: 'ID 列', type: 'id' }] },
  enrichment: { kind: 'enrichment', label: '富集结果气泡图', requiredColumns: [] },
  survival: { kind: 'survival', label: '生存分析 KM', requiredColumns: [{ role: 'x', label: '生存时间列', type: 'numeric' }, { role: 'y', label: '结局状态列', type: 'category' }, { role: 'group', label: '分组列', type: 'category', optional: true }] },
}

export interface ParsedTable {
  headers: string[]
  rows: Record<string, string>[]
}

export interface ValidationMessage {
  severity: Severity
  text: string
}

export interface ColumnMap {
  id: string
  group: string
  value: string
  x: string
  y: string
  series: string
  error: string
}

export interface WorkshopConfig {
  title: string
  xTitle: string
  yTitle: string
  discretePalette: DiscretePaletteName
  continuousPalette: ContinuousPaletteName
  normalization: Normalization
  missingValue: 'drop-row' | 'zero' | 'row-mean'
  errorBar: ErrorBarMode
  testMethod: 'student' | 'welch' | 'mann-whitney'
  showPoints: boolean
  showOutliers: boolean
  notch: boolean
  regression: 'linear' | 'quadratic' | 'cubic' | 'loess'
  correlation: 'pearson' | 'spearman'
  pointSize: number
  barWidth: number
  lineWidth: number
  distributionWidth: number
  histogramGap: number
  plotWidth: number
  plotHeight: number
  xRangeMode: 'auto' | 'manual'
  xMin: number
  xMax: number
  yRangeMode: 'auto' | 'manual'
  yMin: number
  yMax: number
  alpha: number
  smoothLine: boolean
  showValues: boolean
  binCount: number
  showDensity: boolean
  posthocLetters: Record<string, string>
  cluster: 'none' | 'rows' | 'columns' | 'both'
  clusterDistance: 'euclidean' | 'pearson'
  sampleAnnotations: Record<string, string>
  showConfidence: boolean
  showLineError: boolean
  showSignificance: boolean
  significanceDisplay: 'p-value' | 'stars'
  legendPosition: 'top' | 'bottom' | 'left' | 'right'
  legendOrientation: 'auto' | 'h' | 'v'
  legendFontSize: number
  selectedEnrichmentIds: string[]
}

export interface GroupSummary {
  group: string
  n: number
  mean: number
  sd: number
}

export interface WorkshopResult {
  messages: ValidationMessage[]
  traces: Plotly.Data[]
  layout: Partial<Plotly.Layout>
  config: Partial<Plotly.Config>
  summaries: GroupSummary[]
  statistics: Array<Record<string, string | number>>
  validRows: number
  /** Only populated for the survival (KM) chart. */
  survival?: SurvivalSummary
}

export interface SurvivalSummary {
  groups: Array<{ name: string; n: number; events: number; censored: number; medianSurvival: number | null }>
  logRank: { chi2: number; df: number; p: number } | null
  pairwise: LogRankPair[]
  medianFollowup: number
  /** Expression mode only: cutoff actually used for grouping. */
  cutoff: number | null
  strategy: SurvivalGroupStrategy | null
  joinMatched: number | null
  optimalP: number | null
}

/** Extra, chart-scoped inputs that do not belong in DEFAULT_WORKSHOP_CONFIG. */
export interface SurvivalWorkshopOptions {
  inputMode: 'combined' | 'expression'
  followupTable: ParsedTable | null
  strategy: SurvivalGroupStrategy
  customCutoff: number
  showCI: boolean
  showCensors: boolean
  showRiskTable: boolean
  isDark: boolean
}

export interface WorkshopExtras {
  survival?: SurvivalWorkshopOptions
}

const numberPattern = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i

export const DEFAULT_COLUMN_MAP: ColumnMap = { id: '', group: '', value: '', x: '', y: '', series: '', error: '' }

export const DEFAULT_WORKSHOP_CONFIG: WorkshopConfig = {
  title: '', xTitle: '', yTitle: '',
  discretePalette: 'Friendly', continuousPalette: 'RdBu',
  normalization: 'row-zscore', missingValue: 'drop-row', errorBar: 'sd', testMethod: 'welch',
  showPoints: true, showOutliers: true, notch: false,
  regression: 'linear', correlation: 'pearson', pointSize: 9, barWidth: 0.62, lineWidth: 2.5, distributionWidth: 0.65, histogramGap: 0.15, plotWidth: 900, plotHeight: 620, xRangeMode: 'auto', xMin: 0, xMax: 100, yRangeMode: 'auto', yMin: 0, yMax: 100, alpha: 0.78,
  smoothLine: false, showValues: false, binCount: 24, showDensity: true, posthocLetters: {}, cluster: 'none', clusterDistance: 'euclidean', sampleAnnotations: {}, showConfidence: true, showLineError: true, showSignificance: true, significanceDisplay: 'p-value', legendPosition: 'top', legendOrientation: 'auto', legendFontSize: 12, selectedEnrichmentIds: [],
}

/** CSV/TSV/semicolon parser backed by PapaParse delimiter sniffing. */
export function parseDelimited(text: string): ParsedTable {
  const parsed = Papa.parse<string[]>(text.replace(/^\uFEFF/, ''), {
    skipEmptyLines: 'greedy',
  })
  const [headerRow, ...dataRows] = parsed.data
  if (!headerRow?.length) return { headers: [], rows: [] }
  const headers = headerRow.map((header, index) => header.trim() || `column_${index + 1}`)
  const rows = dataRows.map((values) => Object.fromEntries(headers.map((header, index) => [header, (values[index] ?? '').trim()])))
  return { headers, rows }
}

export function inferColumnMap(headers: string[], kind: ChartKind): ColumnMap {
  const find = (...names: string[]) => headers.find((header) => names.some((name) => header.toLowerCase() === name || header.toLowerCase().includes(name))) ?? ''
  const numeric = headers.filter((header) => /value|expression|count|score|mean|x|y|time|day|hour|trait|log2/i.test(header))
  const group = find('group', 'condition', 'treatment', 'class', 'line')
  const base = { ...DEFAULT_COLUMN_MAP, id: find('gene', 'id', 'feature', 'name'), group }
  if (kind === 'enrichment') return base
  if (kind === 'survival') return { ...base, id: find('sample', 'id', 'patient'), x: find('time', 'os.time', 'days', 'months', 'follow') || numeric[0] || '', y: find('status', 'event', 'vital', 'outcome', 'censor'), value: find('expression', 'value', 'tpm', 'fpkm') || numeric[1] || '' }
  if (kind === 'heatmap' || kind === 'corr-heatmap' || kind === 'pca') return { ...base, id: base.id || headers[0] || '' }
  if (kind === 'scatter') return { ...base, x: find('x', 'expression', 'trait') || numeric[0] || '', y: find('y', 'trait', 'value') || numeric[1] || '' }
  if (kind === 'line') return { ...base, x: find('time', 'day', 'hour', 'x') || headers[0] || '', value: find('value', 'expression') || numeric[0] || '', series: find('line', 'series', 'group', 'condition') || group }
  if (kind === 'mean-error') return { ...base, group: group || headers[0] || '', value: find('mean', 'value', 'expression') || numeric[0] || '', error: find('sd', 'sem', 'error') || numeric[1] || '' }
  return { ...base, value: find('value', 'expression', 'score') || numeric[0] || '' }
}

function enrichmentHeader(headers: string[], ...aliases: string[]): string {
  return headers.find((header) => aliases.includes(header.trim().toLowerCase())) ?? ''
}

function enrichmentRatio(value: string): number | null {
  const [numerator, denominator] = value.split('/', 2).map(Number)
  if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) return numerator / denominator
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function processEnrichment(table: ParsedTable, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  const idColumn = enrichmentHeader(table.headers, 'id', 'go id', 'pathway id')
  const descriptionColumn = enrichmentHeader(table.headers, 'description', 'go term', 'kegg pathway')
  const ratioColumn = enrichmentHeader(table.headers, 'generatio', 'gene_ratio')
  const pValueColumn = enrichmentHeader(table.headers, 'pvalue', 'p-value')
  const pAdjustColumn = enrichmentHeader(table.headers, 'p.adjust', 'p_adjust', 'padj')
  const qValueColumn = enrichmentHeader(table.headers, 'qvalue', 'q-value', 'q_value')
  const countColumn = enrichmentHeader(table.headers, 'count')
  const sourceColumn = enrichmentHeader(table.headers, 'source')
  const missing = [
    ['ID', idColumn],
    ['Description', descriptionColumn],
    ['GeneRatio', ratioColumn],
    ['p.adjust', pAdjustColumn],
    ['Count', countColumn],
  ].filter(([, column]) => !column).map(([label]) => label)
  if (missing.length) {
    messages.push({ severity: 'error', text: `富集结果缺少标准列：${missing.join('、')}。` })
    return { messages, traces: [], layout: layoutBase('enrichment', config), config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: 0 }
  }

  const rows = table.rows.flatMap((row) => {
    const id = row[idColumn]?.trim()
    const description = row[descriptionColumn]?.trim()
    const geneRatio = row[ratioColumn]?.trim()
    const ratio = enrichmentRatio(geneRatio)
    const pAdjust = finite(row[pAdjustColumn] ?? '')
    const count = finite(row[countColumn] ?? '')
    if (!id || !description || ratio === null || pAdjust === null || count === null) return []
    return [{
      id,
      description,
      geneRatio,
      ratio,
      pvalue: finite(row[pValueColumn] ?? '') ?? pAdjust,
      pAdjust,
      qvalue: finite(row[qValueColumn] ?? '') ?? 0,
      count,
      source: sourceColumn ? row[sourceColumn]?.trim() || 'Enrichment' : 'Enrichment',
    }]
  }).sort((left, right) => left.pAdjust - right.pAdjust)

  const selected = new Set(config.selectedEnrichmentIds)
  const visibleRows = (selected.size ? rows.filter((row) => selected.has(row.id)) : rows.slice(0, 20)).reverse()
  if (!rows.length) messages.push({ severity: 'error', text: '没有可用于绘图的有效富集结果行。' })
  else if (!visibleRows.length) messages.push({ severity: 'error', text: '所选 pathway/term 在当前数据中不存在。' })
  else messages.push({ severity: 'success', text: selected.size ? `已选择 ${visibleRows.length} 个 pathway/term 重新绘图。` : `已按 p.adjust 展示 Top ${visibleRows.length}。` })

  const significance = visibleRows.map((row) => -Math.log10(Math.max(row.pAdjust, 1e-300)))
  const palette = CONTINUOUS_PALETTES[config.continuousPalette]
  const colorscale = palette.map((color, index) => [index / Math.max(palette.length - 1, 1), color] as [number, string])
  const minSignificance = significance.length ? Math.min(...significance) : 0
  const maxSignificance = significance.length ? Math.max(...significance) : 1
  const trace: Plotly.Data = {
    type: 'scatter',
    mode: 'markers',
    x: visibleRows.map((row) => row.ratio),
    y: visibleRows.map((row) => wrapEnrichmentLabel(row.description)),
    text: visibleRows.map((row) => `${row.source}: ${row.id}`),
    customdata: visibleRows.map((row) => [row.description, row.geneRatio, row.count, row.pvalue, row.pAdjust, row.qvalue]),
    hovertemplate: '<b>%{text}</b><br>%{customdata[0]}<br>GeneRatio=%{customdata[1]} (%{x:.4f})<br>Count=%{customdata[2]}<br>p-value=%{customdata[3]:.2e}<br>p.adjust=%{customdata[4]:.2e}<br>q-value=%{customdata[5]:.2e}<extra></extra>',
    marker: {
      size: visibleRows.map((row) => Math.min(10 + Math.sqrt(Math.max(row.count, 1)) * 3.2, 36)),
      color: significance,
      colorscale,
      cmin: minSignificance,
      cmax: maxSignificance === minSignificance ? minSignificance + 1e-6 : maxSignificance,
      showscale: true,
      colorbar: { title: { text: '-log10<br>p.adjust' }, thickness: 13, outlinewidth: 0 },
      opacity: config.alpha,
      line: { width: 0 },
    },
  }
  const layout = layoutBase('enrichment', config)
  layout.title = { text: config.title || `Enrichment Analysis — ${visibleRows.length} Selected Terms`, x: 0.02, xanchor: 'left' }
  layout.xaxis = { title: { text: config.xTitle || 'GeneRatio' }, gridcolor: '#e2e8f0', zeroline: false }
  layout.yaxis = { title: { text: config.yTitle || 'Pathway / GO Term' }, automargin: true, gridcolor: '#e2e8f0' }
  layout.margin = { l: 190, r: 96, t: 60, b: 64 }
  return {
    messages,
    traces: visibleRows.length ? [trace] : [],
    layout,
    config: { responsive: true, displaylogo: false },
    summaries: [],
    statistics: visibleRows.map((row) => ({ Source: row.source, ID: row.id, Description: row.description, GeneRatio: row.geneRatio, pvalue: row.pvalue, 'p.adjust': row.pAdjust, qvalue: row.qvalue, Count: row.count })),
    validRows: visibleRows.length,
  }
}

function finite(value: string): number | null {
  const normalized = value.trim()
  if (!normalized || !numberPattern.test(normalized)) return null
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

function mean(values: number[]) { return values.reduce((sum, value) => sum + value, 0) / values.length }
function sd(values: number[]) {
  if (values.length < 2) return 0
  const average = mean(values)
  return Math.sqrt(values.reduce((sum, value) => sum + (value - average) ** 2, 0) / (values.length - 1))
}
function error(values: number[], mode: ErrorBarMode) {
  const deviation = sd(values)
  if (mode === 'sd') return deviation
  if (mode === 'sem') return deviation / Math.sqrt(values.length)
  return 1.96 * deviation / Math.sqrt(values.length)
}
function rank(values: number[]) {
  const order = values.map((value, index) => ({ value, index })).sort((left, right) => left.value - right.value)
  const ranks = Array(values.length).fill(0)
  let start = 0
  while (start < order.length) {
    let end = start
    while (end + 1 < order.length && order[end + 1].value === order[start].value) end += 1
    const averageRank = (start + end + 2) / 2
    for (let index = start; index <= end; index += 1) ranks[order[index].index] = averageRank
    start = end + 1
  }
  return ranks
}
function correlation(left: number[], right: number[], method: WorkshopConfig['correlation']) {
  const x = method === 'spearman' ? rank(left) : left
  const y = method === 'spearman' ? rank(right) : right
  const xMean = mean(x); const yMean = mean(y)
  const numerator = x.reduce((sum, value, index) => sum + (value - xMean) * (y[index] - yMean), 0)
  const denominator = Math.sqrt(x.reduce((sum, value) => sum + (value - xMean) ** 2, 0) * y.reduce((sum, value) => sum + (value - yMean) ** 2, 0))
  return denominator ? numerator / denominator : 0
}
function normalP(value: number) {
  const z = Math.abs(value)
  const t = 1 / (1 + 0.2316419 * z)
  const density = Math.exp(-(z ** 2) / 2) / Math.sqrt(2 * Math.PI)
  const tail = density * (0.319381530 * t - 0.356563782 * t ** 2 + 1.781477937 * t ** 3 - 1.821255978 * t ** 4 + 1.330274429 * t ** 5)
  return Math.min(1, 2 * tail)
}
function studentP(left: number[], right: number[]) {
  const pooledVariance = (((left.length - 1) * sd(left) ** 2) + ((right.length - 1) * sd(right) ** 2)) / Math.max(1, left.length + right.length - 2)
  const standardError = Math.sqrt(pooledVariance * (1 / left.length + 1 / right.length))
  return standardError ? normalP((mean(left) - mean(right)) / standardError) : 1
}
function welchP(left: number[], right: number[]) {
  const standardError = Math.sqrt(sd(left) ** 2 / left.length + sd(right) ** 2 / right.length)
  return standardError ? normalP((mean(left) - mean(right)) / standardError) : 1
}
function mannWhitneyP(left: number[], right: number[]) {
  const combined = [...left, ...right]
  const ranks = rank(combined)
  const leftRankSum = ranks.slice(0, left.length).reduce((sum, value) => sum + value, 0)
  const u = leftRankSum - left.length * (left.length + 1) / 2
  const meanU = left.length * right.length / 2
  const standardDeviation = Math.sqrt(left.length * right.length * (left.length + right.length + 1) / 12)
  return standardDeviation ? normalP((u - meanU) / standardDeviation) : 1
}
function oneWayAnova(groups: number[][]) {
  const values = groups.flat()
  const grandMean = mean(values)
  const between = groups.reduce((sum, group) => sum + group.length * (mean(group) - grandMean) ** 2, 0)
  const within = groups.reduce((sum, group) => sum + group.reduce((inner, value) => inner + (value - mean(group)) ** 2, 0), 0)
  const dfBetween = groups.length - 1
  const dfWithin = values.length - groups.length
  const f = dfBetween && dfWithin && within ? (between / dfBetween) / (within / dfWithin) : 0
  // Wilson–Hilferty normal approximation is stable for the small browser-side summary needed here.
  const z = f > 0 ? (Math.cbrt(f) - (1 - 2 / (9 * Math.max(1, dfBetween)))) / Math.sqrt(2 / (9 * Math.max(1, dfBetween))) : 0
  return { f, p: normalP(z), dfBetween, dfWithin }
}
function star(pValue: number) { return pValue < 0.001 ? '***' : pValue < 0.01 ? '**' : pValue < 0.05 ? '*' : 'ns' }
function range(values: number[]) { return [Math.min(...values), Math.max(...values)] }
function titleFor(kind: ChartKind) { return CHART_DEFINITIONS[kind].label }
function legendConfig(config: WorkshopConfig): Partial<Plotly.Legend> {
  const orientation = config.legendOrientation === 'auto' ? (config.legendPosition === 'left' || config.legendPosition === 'right' ? 'v' : 'h') : config.legendOrientation
  const positions = {
    top: { x: 0.5, y: 1.14, xanchor: 'center' as const, yanchor: 'bottom' as const },
    bottom: { x: 0.5, y: -0.2, xanchor: 'center' as const, yanchor: 'top' as const },
    left: { x: -0.02, y: 1, xanchor: 'right' as const, yanchor: 'top' as const },
    right: { x: 1.02, y: 1, xanchor: 'left' as const, yanchor: 'top' as const },
  }
  return { ...positions[config.legendPosition], orientation, font: { size: config.legendFontSize } }
}
function layoutBase(kind: ChartKind, config: WorkshopConfig): Partial<Plotly.Layout> {
  const margin = config.legendPosition === 'top' ? { l: 68, r: 34, t: 96, b: 72 }
    : config.legendPosition === 'bottom' ? { l: 68, r: 34, t: 58, b: 142 }
      : { l: 68, r: 68, t: 58, b: 72 }
  return {
    title: { text: config.title.trim() || titleFor(kind), x: 0.02 },
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { family: 'Inter, system-ui, sans-serif', color: '#334155' },
    margin, width: config.plotWidth, height: config.plotHeight, autosize: false,
    hovermode: 'closest', showlegend: true, legend: legendConfig(config),
  }
}
function addSignificanceBracket(layout: Partial<Plotly.Layout>, groups: Array<[string, number[]]>, pValue: number, config: WorkshopConfig) {
  if (!config.showSignificance || groups.length !== 2) return
  const values = groups.flatMap(([, groupValues]) => groupValues)
  const minValue = Math.min(...values); const maxValue = Math.max(...values)
  const pad = Math.max(Math.abs(maxValue - minValue) * 0.08, Math.abs(maxValue) * 0.08, 1)
  const bracketY = maxValue + pad
  const capY = bracketY - pad * 0.32
  layout.yaxis = { ...(layout.yaxis ?? {}), range: [Math.min(0, minValue - pad * 0.12), bracketY + pad * 1.05] }
  layout.shapes = [
    ...(layout.shapes ?? []),
    { type: 'line', xref: 'x', yref: 'y', x0: groups[0][0], x1: groups[0][0], y0: capY, y1: bracketY, line: { color: '#475569', width: config.lineWidth } },
    { type: 'line', xref: 'x', yref: 'y', x0: groups[0][0], x1: groups[1][0], y0: bracketY, y1: bracketY, line: { color: '#475569', width: config.lineWidth } },
    { type: 'line', xref: 'x', yref: 'y', x0: groups[1][0], x1: groups[1][0], y0: capY, y1: bracketY, line: { color: '#475569', width: config.lineWidth } },
  ]
  const label = config.significanceDisplay === 'stars' ? star(pValue) : `p = ${pValue.toExponential(2)}`
  layout.annotations = [
    ...(layout.annotations ?? []),
    { x: 0.5, xref: 'paper', y: bracketY + pad * 0.52, yref: 'y', text: label, showarrow: false, font: { size: 12, color: '#334155' } },
  ]
  if (config.significanceDisplay === 'stars') {
    layout.annotations.push({ x: 0.5, xref: 'paper', y: config.legendPosition === 'bottom' ? -0.36 : -0.22, yref: 'paper', text: '显著性：*** p < 0.001 · ** p < 0.01 · * p < 0.05 · ns p ≥ 0.05', showarrow: false, font: { size: 10, color: '#64748b' } })
  }
}

function groupedRows(table: ParsedTable, map: ColumnMap, messages: ValidationMessage[]) {
  const groups = new Map<string, number[]>()
  table.rows.forEach((row, index) => {
    const group = row[map.group]?.trim()
    const value = finite(row[map.value] ?? '')
    if (!group) messages.push({ severity: 'error', text: `第 ${index + 2} 行「${map.group || '分组'}」为空。` })
    else if (value === null) messages.push({ severity: 'error', text: `第 ${index + 2} 行「${map.value}」含非数值 “${row[map.value] ?? ''}”。` })
    else groups.set(group, [...(groups.get(group) ?? []), value])
  })
  return groups
}

function processGrouped(kind: 'bar' | 'boxplot' | 'violin', table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  if (!map.group || !map.value) messages.push({ severity: 'error', text: '请选择分组列和数值列。' })
  const groups = groupedRows(table, map, messages)
  if (groups.size && (groups.size < 2 || groups.size > 12)) messages.push({ severity: 'error', text: `检测到 ${groups.size} 组，分组数量必须在 2–12 之间。` })
  if (groups.size > DISCRETE_PALETTES[config.discretePalette].length) messages.push({ severity: 'error', text: `「${config.discretePalette}」色板仅支持 ${DISCRETE_PALETTES[config.discretePalette].length} 个类别；请筛选分组或切换扩展色板。` })
  const entries = Array.from(groups.entries())
  const summaries = entries.map(([group, values]) => ({ group, n: values.length, mean: mean(values), sd: sd(values) }))
  const statistics: Array<Record<string, string | number>> = summaries.map((item) => ({ group: item.group, n: item.n, mean: item.mean.toFixed(4), sd: item.sd.toFixed(4) }))
  const canTest = entries.length === 2 && entries.every(([, values]) => values.length >= 3)
  if (entries.length === 2 && !canTest) messages.push({ severity: 'warning', text: '每组至少需要 3 个重复才能进行显著性检验；仍可绘图。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：已识别 ${entries.length} 组，共 ${entries.reduce((sum, [, values]) => sum + values.length, 0)} 行。` })
  const colors = DISCRETE_PALETTES[config.discretePalette]
  const traces: Plotly.Data[] = kind === 'bar'
    ? entries.map(([group, values], index) => ({ type: 'bar', name: group, x: [group], y: [summaries[index].mean], width: config.barWidth, marker: { color: colors[index] }, error_y: { type: 'data', array: [error(values, config.errorBar)], visible: true, thickness: config.lineWidth, width: config.lineWidth * 4 }, hovertemplate: '%{x}<br>Mean: %{y:.3f}<extra>%{fullData.name}</extra>' }))
    : entries.map(([group, values], index) => kind === 'violin'
      ? ({ type: 'violin', name: group, y: values, width: config.distributionWidth, line: { color: colors[index], width: config.lineWidth }, fillcolor: colors[index], opacity: 0.62, box: { visible: true }, meanline: { visible: true }, points: config.showPoints ? 'all' : false, jitter: 0.42, pointpos: 0 })
      : ({ type: 'box', name: group, y: values, width: config.distributionWidth, line: { color: colors[index], width: config.lineWidth }, marker: { color: colors[index] }, boxpoints: config.showPoints ? 'all' : (config.showOutliers ? 'outliers' : false), jitter: 0.42, pointpos: 0, notched: config.notch }))
  if (kind === 'bar' && config.showPoints) traces.push({ type: 'scatter', mode: 'markers', x: entries.flatMap(([group, values]) => values.map(() => group)), y: entries.flatMap(([, values]) => values), marker: { color: '#1e293b', size: 6, opacity: 0.58 }, hovertemplate: '%{x}<br>%{y:.3f}<extra>重复</extra>', showlegend: false })
  const layout = layoutBase(kind, config)
  layout.barmode = kind === 'bar' ? 'group' : layout.barmode
  layout.xaxis = { title: { text: config.xTitle || map.group }, categoryorder: 'array', categoryarray: summaries.map((item) => item.group) }
  layout.yaxis = { title: { text: config.yTitle || map.value }, zeroline: false, gridcolor: '#e2e8f0' }
  if (canTest) {
    const pValue = config.testMethod === 'student' ? studentP(entries[0][1], entries[1][1]) : config.testMethod === 'mann-whitney' ? mannWhitneyP(entries[0][1], entries[1][1]) : welchP(entries[0][1], entries[1][1])
    const testNames = { student: 'Student t', welch: 'Welch t', 'mann-whitney': 'Mann–Whitney U' }
    statistics.push({ comparison: `${entries[0][0]} vs ${entries[1][0]}`, test: testNames[config.testMethod], p_value: pValue.toExponential(3), significance: star(pValue) })
    const maxValue = Math.max(...entries.flatMap(([, values]) => values))
    addSignificanceBracket(layout, entries, pValue, config)
  } else if (entries.length >= 3 && entries.every(([, values]) => values.length >= 3)) {
    const anova = oneWayAnova(entries.map(([, values]) => values))
    statistics.push({ comparison: '所有分组', test: 'One-way ANOVA', f_value: anova.f.toFixed(4), df: `${anova.dfBetween}, ${anova.dfWithin}`, p_value: anova.p.toExponential(3) })
  } else if (entries.length >= 3) {
    messages.push({ severity: 'warning', text: '每组至少需要 3 个重复才能计算 one-way ANOVA。' })
  }
  if (entries.length >= 3 && Object.keys(config.posthocLetters).length) {
    const highest = Math.max(...entries.flatMap(([, values]) => values))
    layout.annotations = entries.map(([group], index) => ({ x: group, y: highest + Math.max(Math.abs(highest) * 0.08, 1) * (index % 2 + 1), text: config.posthocLetters[group] ?? '', showarrow: false, font: { size: 14, color: '#334155' } }))
  }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries, statistics, validRows: entries.reduce((sum, [, values]) => sum + values.length, 0) }
}

function polynomial(points: Array<[number, number]>, degree: number) {
  const size = degree + 1
  const matrix = Array.from({ length: size }, (_, row) => Array.from({ length: size + 1 }, (_, column) => column === size ? points.reduce((sum, [x, y]) => sum + y * x ** row, 0) : points.reduce((sum, [x]) => sum + x ** (row + column), 0)))
  for (let pivot = 0; pivot < size; pivot += 1) {
    const best = Array.from({ length: size - pivot }, (_, offset) => pivot + offset).reduce((current, index) => Math.abs(matrix[index][pivot]) > Math.abs(matrix[current][pivot]) ? index : current, pivot)
    ;[matrix[pivot], matrix[best]] = [matrix[best], matrix[pivot]]
    const divisor = matrix[pivot][pivot] || 1
    for (let column = pivot; column <= size; column += 1) matrix[pivot][column] /= divisor
    for (let row = 0; row < size; row += 1) if (row !== pivot) { const factor = matrix[row][pivot]; for (let column = pivot; column <= size; column += 1) matrix[row][column] -= factor * matrix[pivot][column] }
  }
  return matrix.map((row) => row[size])
}
function regressionLine(points: Array<[number, number]>, method: WorkshopConfig['regression']) {
  const degree = method === 'cubic' ? 3 : method === 'quadratic' ? 2 : 1
  const coefficients = polynomial(points, degree)
  const [minX, maxX] = range(points.map(([x]) => x))
  const x = Array.from({ length: 80 }, (_, index) => minX + (maxX - minX) * index / 79)
  if (method === 'loess') {
    const sorted = [...points].sort((left, right) => left[0] - right[0]); const window = Math.max(3, Math.ceil(sorted.length / 4))
    return { x: sorted.map(([value]) => value), y: sorted.map((_, index) => mean(sorted.slice(Math.max(0, index - window), Math.min(sorted.length, index + window + 1)).map(([, value]) => value))), equation: 'LOESS 平滑' }
  }
  const y = x.map((value) => coefficients.reduce((sum, coefficient, index) => sum + coefficient * value ** index, 0))
  const equation = coefficients.map((coefficient, index) => `${coefficient >= 0 && index ? '+' : ''}${coefficient.toFixed(3)}${index === 0 ? '' : index === 1 ? 'x' : `x^${index}`}`).reverse().join(' ')
  return { x, y, equation: `y = ${equation}` }
}

function processScatter(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []; const pointsByGroup = new Map<string, Array<[number, number]>>()
  if (!map.x || !map.y) messages.push({ severity: 'error', text: '请选择 X 和 Y 数值列。' })
  table.rows.forEach((row, index) => {
    const x = finite(row[map.x] ?? ''); const y = finite(row[map.y] ?? '')
    if (x === null || y === null) messages.push({ severity: 'warning', text: `第 ${index + 2} 行已剔除：${x === null ? `「${map.x}」` : `「${map.y}」`} 不是数值。` })
    else { const group = map.group && row[map.group]?.trim() ? row[map.group].trim() : 'All samples'; pointsByGroup.set(group, [...(pointsByGroup.get(group) ?? []), [x, y]]) }
  })
  const entries = Array.from(pointsByGroup.entries()); const validRows = entries.reduce((sum, [, points]) => sum + points.length, 0)
  if (validRows < 5) messages.push({ severity: 'error', text: '至少需要 5 个有效点才能进行拟合。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：${validRows} 个有效点${entries.length > 1 ? `，${entries.length} 个分组` : ''}。` })
  const colors = DISCRETE_PALETTES[config.discretePalette]; const traces: Plotly.Data[] = []; const statistics: Array<Record<string, string | number>> = []
  entries.forEach(([group, points], index) => {
    const color = colors[index % colors.length]; const x = points.map(([value]) => value); const y = points.map(([, value]) => value)
    traces.push({ type: 'scatter', mode: 'markers', name: group, x, y, marker: { size: config.pointSize, color, opacity: config.alpha }, hovertemplate: `${map.x}: %{x:.4g}<br>${map.y}: %{y:.4g}<extra>${group}</extra>` })
    if (points.length >= 5 && new Set(x).size > 1) {
      const fit = regressionLine(points, config.regression); const r = correlation(x, y, config.correlation); const rSquared = r ** 2
      if (config.showConfidence && config.regression !== 'loess') {
        const band = 1.96 * sd(y) / Math.sqrt(points.length)
        traces.push({ type: 'scatter', mode: 'lines', x: [...fit.x, ...[...fit.x].reverse()], y: [...fit.y.map((value) => value + band), ...[...fit.y].reverse().map((value) => value - band)], fill: 'toself', fillcolor: `${color}22`, line: { color: 'transparent', width: config.lineWidth }, hoverinfo: 'skip', showlegend: false })
      }
      traces.push({ type: 'scatter', mode: 'lines', name: `${group} 拟合`, x: fit.x, y: fit.y, line: { color, width: config.lineWidth }, hoverinfo: 'skip' })
      statistics.push({ group, equation: fit.equation, r: r.toFixed(4), r_squared: rSquared.toFixed(4), p_value: normalP(r * Math.sqrt((points.length - 2) / Math.max(1e-12, 1 - rSquared))).toExponential(3) })
    } else messages.push({ severity: 'warning', text: `「${group}」X 方差为 0 或有效点不足，无法拟合。` })
  })
  const layout = layoutBase('scatter', config); layout.xaxis = { title: { text: config.xTitle || map.x }, gridcolor: '#e2e8f0', zeroline: false }; layout.yaxis = { title: { text: config.yTitle || map.y }, gridcolor: '#e2e8f0', zeroline: false }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries: [], statistics, validRows }
}

function clusterOrder(vectors: number[][], distance: WorkshopConfig['clusterDistance']): number[] {
  if (vectors.length < 3) return vectors.map((_, index) => index)
  const itemDistance = (left: number[], right: number[]) => {
    if (distance === 'pearson') return 1 - correlation(left, right, 'pearson')
    return Math.sqrt(left.reduce((sum, value, index) => sum + (value - right[index]) ** 2, 0))
  }
  type Cluster = { leaves: number[] }
  let clusters: Cluster[] = vectors.map((_, index) => ({ leaves: [index] }))
  const clusterDistance = (left: Cluster, right: Cluster) => {
    const pairs = left.leaves.flatMap((leftIndex) => right.leaves.map((rightIndex) => itemDistance(vectors[leftIndex], vectors[rightIndex])))
    return mean(pairs)
  }
  while (clusters.length > 1) {
    let leftIndex = 0
    let rightIndex = 1
    let shortest = clusterDistance(clusters[leftIndex], clusters[rightIndex])
    for (let left = 0; left < clusters.length; left += 1) {
      for (let right = left + 1; right < clusters.length; right += 1) {
        const current = clusterDistance(clusters[left], clusters[right])
        if (current < shortest) { leftIndex = left; rightIndex = right; shortest = current }
      }
    }
    const left = clusters[leftIndex]
    const right = clusters[rightIndex]
    const merged = { leaves: [...left.leaves, ...right.leaves] }
    clusters = clusters.filter((_, index) => index !== leftIndex && index !== rightIndex)
    clusters.push(merged)
  }
  return clusters[0].leaves
}

function processHeatmap(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []; const id = map.id || table.headers[0]; const valueColumns = table.headers.filter((header) => header !== id)
  if (!id || valueColumns.length < 2) messages.push({ severity: 'error', text: '热图需要 1 个 ID 列和至少 2 个数值列。' })
  if (table.rows.length > 5000 || valueColumns.length > 200) messages.push({ severity: 'error', text: `矩阵为 ${table.rows.length} × ${valueColumns.length}，超过 5000 行或 200 列上限。` })
  const seen = new Set<string>(); const labels: string[] = []; const matrix: number[][] = []
  table.rows.forEach((row, rowIndex) => {
    const label = row[id]?.trim() || `row_${rowIndex + 1}`
    if (seen.has(label)) { messages.push({ severity: 'warning', text: `ID「${label}」重复，保留首行。` }); return }
    seen.add(label)
    const values = valueColumns.map((column) => finite(row[column] ?? ''))
    if (values.some((value) => value === null)) {
      const bad = values.findIndex((value) => value === null)
      if (config.missingValue === 'drop-row') { messages.push({ severity: 'warning', text: `第 ${rowIndex + 2} 行「${valueColumns[bad]}」为空或非数值，已删除该行。` }); return }
      const nonNull = values.filter((value): value is number => value !== null); const fill = config.missingValue === 'zero' ? 0 : (nonNull.length ? mean(nonNull) : 0)
      matrix.push(values.map((value) => value ?? fill)); labels.push(label); return
    }
    matrix.push(values as number[]); labels.push(label)
  })
  if (!matrix.length) messages.push({ severity: 'error', text: '没有可用于绘图的数值行。' })
  let normalized = matrix.map((row) => [...row])
  if (config.normalization === 'row-zscore') normalized = matrix.map((row) => { const deviation = sd(row); return deviation ? row.map((value) => (value - mean(row)) / deviation) : row.map(() => 0) })
  if (config.normalization === 'column-zscore') normalized = matrix.map((row, rowIndex) => row.map((value, columnIndex) => { const values = matrix.map((line) => line[columnIndex]); const deviation = sd(values); return deviation ? (value - mean(values)) / deviation : 0 }))
  if (config.normalization === 'log2') normalized = matrix.map((row) => row.map((value) => Math.log2(value + 1)))
  let orderedLabels = labels
  let orderedColumns = valueColumns
  if (config.cluster === 'rows' || config.cluster === 'both') {
    const order = clusterOrder(normalized, config.clusterDistance)
    normalized = order.map((index) => normalized[index])
    orderedLabels = order.map((index) => labels[index])
  }
  if (config.cluster === 'columns' || config.cluster === 'both') {
    const columnVectors = valueColumns.map((_, column) => normalized.map((row) => row[column]))
    const order = clusterOrder(columnVectors, config.clusterDistance)
    normalized = normalized.map((row) => order.map((column) => row[column]))
    orderedColumns = order.map((index) => valueColumns[index])
  }
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：${matrix.length} 个特征 × ${valueColumns.length} 个样本。` })
  const flattened = normalized.flat(); const maxAbs = Math.max(...flattened.map((value) => Math.abs(value)), 1)
  const trace: Plotly.Data = { type: 'heatmap', x: orderedColumns, y: orderedLabels, z: normalized, colorscale: CONTINUOUS_PALETTES[config.continuousPalette] as unknown as Plotly.ColorScale, zmin: config.continuousPalette === 'RdBu' ? -maxAbs : Math.min(...flattened), zmax: config.continuousPalette === 'RdBu' ? maxAbs : Math.max(...flattened), colorbar: { title: { text: config.normalization === 'none' ? 'Value' : config.normalization } }, texttemplate: config.showValues ? '%{z:.2f}' : undefined, hovertemplate: '%{y}<br>%{x}: %{z:.3f}<extra></extra>' }
  const layout = layoutBase('heatmap', config); layout.xaxis = { title: { text: config.xTitle || 'Samples' }, side: 'top' }; layout.yaxis = { title: { text: config.yTitle || id }, autorange: 'reversed' }
  const annotatedGroups = orderedColumns.map((sample) => config.sampleAnnotations[sample]).filter((group): group is string => Boolean(group))
  if (annotatedGroups.length) {
    const groupOrder = Array.from(new Set(annotatedGroups))
    const colors = DISCRETE_PALETTES[config.discretePalette]
    const colorByGroup = Object.fromEntries(groupOrder.map((group, index) => [group, colors[index % colors.length]]))
    layout.shapes = orderedColumns.flatMap((sample, index) => {
      const group = config.sampleAnnotations[sample]
      return group ? [{ type: 'rect', xref: 'paper', yref: 'paper', x0: index / orderedColumns.length, x1: (index + 1) / orderedColumns.length, y0: 1.015, y1: 1.05, line: { width: 0 }, fillcolor: colorByGroup[group] }] : []
    })
    layout.annotations = groupOrder.map((group, index) => ({ x: 1.01, xref: 'paper', y: 1.04 - index * 0.06, yref: 'paper', text: group, showarrow: false, xanchor: 'left', font: { size: 10, color: colorByGroup[group] } }))
  }
  return { messages, traces: [trace], layout, config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: matrix.length }
}

function processLine(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []; const xColumn = map.x || table.headers[0]; const seriesColumn = map.series || map.group
  const isLong = Boolean(seriesColumn && map.value)
  const candidateColumns = isLong ? [map.value] : table.headers.filter((header) => header !== xColumn && header !== seriesColumn)
  const groups = new Map<string, Array<[string, number]>>()
  table.rows.forEach((row, index) => {
    const x = row[xColumn]?.trim(); if (!x) { messages.push({ severity: 'warning', text: `第 ${index + 2} 行「${xColumn}」为空，已剔除。` }); return }
    if (isLong) {
      const value = finite(row[map.value] ?? ''); const group = row[seriesColumn]?.trim()
      if (value === null || !group) { messages.push({ severity: 'warning', text: `第 ${index + 2} 行缺少有效的数值或系列分组，已剔除。` }); return }
      groups.set(group, [...(groups.get(group) ?? []), [x, value]])
    } else candidateColumns.forEach((column) => { const value = finite(row[column] ?? ''); if (value !== null) groups.set(column, [...(groups.get(column) ?? []), [x, value]]) })
  })
  if (!groups.size) messages.push({ severity: 'error', text: '未识别到可绘制的折线数据；请选择 X、数值和系列列。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：已识别 ${groups.size} 条线。` })
  const colors = DISCRETE_PALETTES[config.discretePalette]
  const traces: Plotly.Data[] = []
  Array.from(groups.entries()).forEach(([name, points], index) => {
    const byX = new Map<string, number[]>()
    points.forEach(([x, value]) => byX.set(x, [...(byX.get(x) ?? []), value]))
    const x = Array.from(byX.keys())
    const means = x.map((value) => mean(byX.get(value) ?? []))
    const deviations = x.map((value) => sd(byX.get(value) ?? []))
    const color = colors[index % colors.length]
    if (config.showLineError && Array.from(byX.values()).some((values) => values.length > 1)) {
      traces.push({ type: 'scatter', mode: 'lines', x: [...x, ...[...x].reverse()], y: [...means.map((value, point) => value + deviations[point]), ...[...means].reverse().map((value, point) => value - deviations[means.length - point - 1])], fill: 'toself', fillcolor: `${color}20`, line: { color: 'transparent', width: config.lineWidth }, hoverinfo: 'skip', showlegend: false })
    }
    traces.push({ type: 'scatter', mode: config.showPoints ? 'lines+markers' : 'lines', name, x, y: means, line: { color, shape: config.smoothLine ? 'spline' : 'linear', width: config.lineWidth }, marker: { size: Math.max(4, config.pointSize - 2) }, hovertemplate: `${xColumn}: %{x}<br>${map.value || name}: %{y:.3f}<extra>${name}</extra>` })
  })
  const layout = layoutBase('line', config); layout.xaxis = { title: { text: config.xTitle || xColumn }, gridcolor: '#e2e8f0' }; layout.yaxis = { title: { text: config.yTitle || map.value || 'Value' }, gridcolor: '#e2e8f0' }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: Array.from(groups.values()).reduce((sum, values) => sum + values.length, 0) }
}


function processCorrelationHeatmap(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  const numericColumns = table.headers.filter((header) => header !== map.id)
  if (numericColumns.length < 2) messages.push({ severity: 'error', text: '相关性热图至少需要 2 个数值列。' })
  const rows = table.rows.map((row, index) => {
    const values = numericColumns.map((column) => finite(row[column] ?? ''))
    if (values.some((value) => value === null)) {
      messages.push({ severity: 'warning', text: `第 ${index + 2} 行含空值或非数值，已剔除。` })
      return null
    }
    return values as number[]
  }).filter((row): row is number[] => row !== null)
  if (rows.length < 3) messages.push({ severity: 'error', text: '至少需要 3 行完整数值数据才能计算相关性。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：使用 ${rows.length} 行数据计算 ${numericColumns.length} × ${numericColumns.length} ${config.correlation} 相关矩阵。` })
  const matrix = numericColumns.map((_, left) => numericColumns.map((_, right) => correlation(rows.map((row) => row[left]), rows.map((row) => row[right]), config.correlation)))
  const trace: Plotly.Data = { type: 'heatmap', x: numericColumns, y: numericColumns, z: matrix, colorscale: CONTINUOUS_PALETTES[config.continuousPalette] as unknown as Plotly.ColorScale, zmin: -1, zmax: 1, reversescale: true, colorbar: { title: { text: 'r' } }, texttemplate: '%{z:.2f}', hovertemplate: '%{y} × %{x}<br>r = %{z:.4f}<extra></extra>' }
  const layout = layoutBase('corr-heatmap', config); layout.xaxis = { title: { text: config.xTitle || 'Variables' }, side: 'top' }; layout.yaxis = { title: { text: config.yTitle || 'Variables' }, autorange: 'reversed' }
  return { messages, traces: [trace], layout, config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: rows.length }
}

function processHistogram(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  if (!map.value) messages.push({ severity: 'error', text: '请选择数值列。' })
  const groups = new Map<string, number[]>()
  table.rows.forEach((row, index) => {
    const value = finite(row[map.value] ?? '')
    if (value === null) { messages.push({ severity: 'warning', text: `第 ${index + 2} 行「${map.value}」不是数值，已剔除。` }); return }
    const group = map.group && row[map.group]?.trim() ? row[map.group].trim() : 'All samples'
    groups.set(group, [...(groups.get(group) ?? []), value])
  })
  if (groups.size > DISCRETE_PALETTES[config.discretePalette].length) messages.push({ severity: 'error', text: `「${config.discretePalette}」色板不足以区分 ${groups.size} 个分组。` })
  const values = Array.from(groups.values()).flat()
  if (!values.length) messages.push({ severity: 'error', text: '没有可绘制的数值数据。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：${values.length} 个有效值${groups.size > 1 ? `，${groups.size} 个分组` : ''}。` })
  const colors = DISCRETE_PALETTES[config.discretePalette]
  const [minValue, maxValue] = range(values)
  const step = Math.max((maxValue - minValue) / Math.max(1, config.binCount), 1e-9)
  const traces: Plotly.Data[] = []
  Array.from(groups.entries()).forEach(([group, groupValues], index) => {
    const color = colors[index]
    traces.push({ type: 'histogram', name: group, x: groupValues, xbins: { start: minValue, end: maxValue, size: step }, histnorm: config.showDensity ? 'probability density' : undefined, opacity: groups.size > 1 ? 0.55 : 0.8, marker: { color }, hovertemplate: `${map.value}: %{x:.4g}<br>count: %{y}<extra>${group}</extra>` })
    if (config.showDensity && groupValues.length > 1) {
      const deviation = sd(groupValues) || step
      const bandwidth = Math.max(1e-9, 1.06 * deviation * Math.pow(groupValues.length, -0.2))
      const x = Array.from({ length: 100 }, (_, point) => minValue + (maxValue - minValue) * point / 99)
      const y = x.map((point) => groupValues.reduce((sum, value) => sum + Math.exp(-0.5 * ((point - value) / bandwidth) ** 2), 0) / (groupValues.length * bandwidth * Math.sqrt(2 * Math.PI)))
      traces.push({ type: 'scatter', mode: 'lines', name: `${group} KDE`, x, y, line: { color, width: config.lineWidth }, hoverinfo: 'skip' })
    }
  })
  const layout = layoutBase('histogram', config); layout.barmode = 'overlay'; layout.bargap = config.histogramGap; layout.xaxis = { title: { text: config.xTitle || map.value }, gridcolor: '#e2e8f0' }; layout.yaxis = { title: { text: config.yTitle || (config.showDensity ? 'Density' : 'Count') }, gridcolor: '#e2e8f0' }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries: Array.from(groups.entries()).map(([group, groupValues]) => ({ group, n: groupValues.length, mean: mean(groupValues), sd: sd(groupValues) })), statistics: [], validRows: values.length }
}


function processMeanError(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  if (!map.group || !map.value || !map.error) messages.push({ severity: 'error', text: '请选择分组、均值和误差（SD 或 SEM）列。' })
  const records: Array<{ group: string; mean: number; error: number }> = []
  table.rows.forEach((row, index) => {
    const group = row[map.group]?.trim(); const average = finite(row[map.value] ?? ''); const spread = finite(row[map.error] ?? '')
    if (!group || average === null || spread === null || spread < 0) messages.push({ severity: 'error', text: `第 ${index + 2} 行需要有效的分组、均值和非负误差值。` })
    else records.push({ group, mean: average, error: spread })
  })
  if (records.length > DISCRETE_PALETTES[config.discretePalette].length) messages.push({ severity: 'error', text: `「${config.discretePalette}」色板不足以区分 ${records.length} 个分组。` })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：已识别 ${records.length} 个摘要分组。` })
  const colors = DISCRETE_PALETTES[config.discretePalette]
  const traces: Plotly.Data[] = records.map((record, index) => ({ type: 'scatter', mode: 'markers', name: record.group, x: [record.group], y: [record.mean], marker: { size: config.pointSize + 3, color: colors[index] }, error_y: { type: 'data', array: [record.error], visible: true, thickness: config.lineWidth, width: config.lineWidth * 4 }, hovertemplate: '%{x}<br>Mean: %{y:.4g}<extra>%{fullData.name}</extra>' }))
  const layout = layoutBase('mean-error', config); layout.xaxis = { title: { text: config.xTitle || map.group }, categoryorder: 'array', categoryarray: records.map((record) => record.group) }; layout.yaxis = { title: { text: config.yTitle || map.value }, gridcolor: '#e2e8f0' }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries: records.map((record) => ({ group: record.group, n: 1, mean: record.mean, sd: record.error })), statistics: records.map((record) => ({ group: record.group, mean: record.mean, error: record.error, error_column: map.error })), validRows: records.length }
}


function processPca(table: ParsedTable, map: ColumnMap, config: WorkshopConfig): WorkshopResult {
  const messages: ValidationMessage[] = []
  const idColumn = map.id || table.headers[0]
  const sampleNames = table.headers.filter((header) => header !== idColumn)
  if (sampleNames.length < 2) messages.push({ severity: 'error', text: 'PCA 需要至少 2 个数值样本列。' })
  const geneIds: string[] = []
  const data: number[][] = []
  table.rows.forEach((row, index) => {
    const values = sampleNames.map((column) => finite(row[column] ?? ''))
    if (values.some((value) => value === null)) {
      messages.push({ severity: 'warning', text: `第 ${index + 2} 行含空值或非数值，已从 PCA 中剔除。` })
      return
    }
    geneIds.push(row[idColumn]?.trim() || `feature_${index + 1}`)
    data.push(values as number[])
  })
  if (data.length < 2) messages.push({ severity: 'error', text: 'PCA 至少需要 2 个完整特征行。' })
  if (!messages.some((message) => message.severity === 'error')) messages.unshift({ severity: 'success', text: `检测通过：${data.length} 个特征 × ${sampleNames.length} 个样本。` })
  let pca
  try {
    pca = computePCA({ geneIds, sampleNames, data } satisfies ExpressionMatrix)
  } catch (error) {
    messages.push({ severity: 'error', text: error instanceof Error ? error.message : 'PCA 计算失败。' })
    pca = null
  }
  if (!pca) return { messages, traces: [], layout: layoutBase('pca', config), config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: data.length }
  const colors = DISCRETE_PALETTES[config.discretePalette]
  const inferGroup = (sample: string) => config.sampleAnnotations[sample] || sample.replace(/^(?:sample[_-]?)/i, '').replace(/(?:[_-]?(?:rep|r)?\d+)$/i, '') || sample
  const sampleGroups = sampleNames.map(inferGroup)
  const groupNames = Array.from(new Set(sampleGroups))
  const traces: Plotly.Data[] = groupNames.map((group, groupIndex) => {
    const indices = sampleGroups.map((sampleGroup, index) => sampleGroup === group ? index : -1).filter((index) => index >= 0)
    return { type: 'scatter', mode: 'text+markers', name: group, x: indices.map((index) => pca.pc1[index]), y: indices.map((index) => pca.pc2[index]), text: indices.map((index) => sampleNames[index]), textposition: 'top center', marker: { size: config.pointSize + 2, color: colors[groupIndex % colors.length], opacity: config.alpha }, hovertemplate: '%{text}<br>PC1: %{x:.4f}<br>PC2: %{y:.4f}<extra>%{fullData.name}</extra>' }
  })
  const layout = layoutBase('pca', config); layout.xaxis = { title: { text: config.xTitle || `PC1 (${(pca.explainedVariance[0] * 100).toFixed(1)}%)` }, gridcolor: '#e2e8f0', zeroline: true }; layout.yaxis = { title: { text: config.yTitle || `PC2 (${(pca.explainedVariance[1] * 100).toFixed(1)}%)` }, gridcolor: '#e2e8f0', zeroline: true }
  return { messages, traces, layout, config: { responsive: true, displaylogo: false }, summaries: [], statistics: [{ pc1_variance: pca.explainedVariance[0], pc2_variance: pca.explainedVariance[1] }], validRows: data.length }
}

function emptySurvivalResult(messages: ValidationMessage[], config: WorkshopConfig): WorkshopResult {
  return { messages, traces: [], layout: layoutBase('survival', config), config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: 0 }
}

function processSurvival(table: ParsedTable, map: ColumnMap, config: WorkshopConfig, options?: SurvivalWorkshopOptions): WorkshopResult {
  const opts: SurvivalWorkshopOptions = options ?? {
    inputMode: 'combined', followupTable: null, strategy: 'median', customCutoff: 0,
    showCI: false, showCensors: true, showRiskTable: true, isDark: false,
  }
  const messages: ValidationMessage[] = []
  let records: SurvivalRecord[] = []
  let groupNames: string[] = []
  let cutoff: number | null = null
  let optimalP: number | null = null
  let joinMatched: number | null = null
  let timeLabel = 'Time'

  if (opts.inputMode === 'combined') {
    if (!map.x || !map.y) messages.push({ severity: 'error', text: '请选择生存时间列和结局状态列。' })
    const parsed = parseSurvivalRecords(table, map.x, map.y, map.group)
    parsed.errors.slice(0, 8).forEach((text) => messages.push({ severity: 'error', text }))
    if (parsed.errors.length > 8) messages.push({ severity: 'error', text: `……另有 ${parsed.errors.length - 8} 行数据错误。` })
    records = parsed.records
    timeLabel = map.x || 'Time'
    const names = Array.from(new Set(records.map((record) => record.group ?? 'All patients')))
    groupNames = names.length ? names : ['All patients']
    records = records.map((record) => ({ ...record, group: record.group ?? 'All patients' }))
  } else {
    if (!opts.followupTable || !opts.followupTable.headers.length) messages.push({ severity: 'error', text: '请上传随访表（包含样本 ID、生存时间、结局状态）。' })
    const joined = joinExpressionFollowup(table, opts.followupTable ?? { headers: [], rows: [] }, map.id, map.value)
    joined.errors.slice(0, 8).forEach((text) => messages.push({ severity: 'error', text }))
    if (joined.errors.length > 8) messages.push({ severity: 'error', text: `……另有 ${joined.errors.length - 8} 行数据错误。` })
    joined.warnings.forEach((text) => messages.push({ severity: 'warning', text }))
    joinMatched = joined.report.matched
    timeLabel = joined.timeColumn || 'Time'
    if (joined.report.matched > 0 && joined.report.matched < 6) messages.push({ severity: 'error', text: `表达值表与随访表仅匹配 ${joined.report.matched} 个样本，不足以进行生存分析；请检查样本 ID 是否一致。` })
    const grouping = groupByExpression(joined.records, opts.strategy, opts.customCutoff)
    cutoff = grouping.cutoff
    optimalP = grouping.optimalP ?? null
    groupNames = grouping.names
    records = grouping.groups.flat()
    if (opts.strategy === 'optimal') messages.push({ severity: 'warning', text: `最佳截点 = ${cutoff.toFixed(4)}（min p）；该策略存在多重检验偏倚，p 值偏乐观。` })
  }

  if (messages.some((message) => message.severity === 'error')) return emptySurvivalResult(messages, config)
  if (records.length < 6) {
    messages.push({ severity: 'error', text: `有效样本仅 ${records.length} 例，至少需要 6 例。` })
    return emptySurvivalResult(messages, config)
  }

  const groupedRecords = groupNames.map((name) => records.filter((record) => record.group === name))
  const tooSmall = groupNames.filter((_, index) => groupedRecords[index].length < 3)
  if (tooSmall.length) {
    messages.push({ severity: 'error', text: `分组 ${tooSmall.map((name) => `「${name}」`).join('、')} 样本数不足 3 例。` })
    return emptySurvivalResult(messages, config)
  }

  const groups = groupNames.map((name, index) => ({ name, records: groupedRecords[index], km: kaplanMeier(groupedRecords[index]) }))
  let logRank: ReturnType<typeof logRankTest> | null = null
  if (groups.length >= 2 && groups.every((group) => group.records.some((record) => record.status === 1))) {
    try {
      logRank = logRankTest(groupNames, groupedRecords)
    } catch { logRank = null }
  } else if (groups.length >= 2) {
    messages.push({ severity: 'warning', text: '存在无事件的分组，无法计算 log-rank 检验。' })
  }

  const times = records.map((record) => record.time).sort((a, b) => a - b)
  const medianFollowup = times.length % 2 ? times[(times.length - 1) / 2] : (times[times.length / 2 - 1] + times[times.length / 2]) / 2
  messages.unshift({ severity: 'success', text: `检测通过：${records.length} 例样本，${groups.length} 组，中位随访时间 ${medianFollowup.toFixed(2)}。` })

  const colors = DISCRETE_PALETTES[config.discretePalette]
  const figure = buildSurvivalFigure(groups, logRank, {
    title: config.title.trim() || 'Kaplan–Meier Survival Curves',
    xTitle: config.xTitle.trim() || `Time (${timeLabel})`,
    lineWidth: config.lineWidth,
    showCI: opts.showCI,
    showCensors: opts.showCensors,
    showRiskTable: opts.showRiskTable,
    width: config.plotWidth,
    height: config.plotHeight,
    legend: legendConfig(config),
  }, opts.isDark, [...colors])

  const statistics: Array<Record<string, string | number>> = groups.map((group) => ({
    group: group.name,
    n: group.km.n,
    events: group.km.events,
    censored: group.km.censored,
    median_survival: group.km.medianSurvival === null ? 'NR' : Number(group.km.medianSurvival.toFixed(2)),
  }))
  if (logRank) statistics.push({ test: 'Log-rank', chi2: Number(logRank.chi2.toFixed(4)), df: logRank.df, p_value: logRank.p < 0.001 ? logRank.p.toExponential(3) : Number(logRank.p.toFixed(4)) })
  statistics.push({ metric: 'Median follow-up', value: Number(medianFollowup.toFixed(2)) })
  if (cutoff !== null) statistics.push({ metric: 'Expression cutoff', value: Number(cutoff.toFixed(4)) })

  return {
    messages,
    traces: figure.traces,
    layout: { ...layoutBase('survival', config), ...figure.layout, title: figure.layout.title, legend: figure.layout.legend },
    config: { responsive: true, displaylogo: false },
    summaries: groups.map((group) => ({ group: group.name, n: group.km.n, mean: mean(group.records.map((record) => record.time)), sd: sd(group.records.map((record) => record.time)) })),
    statistics,
    validRows: records.length,
    survival: {
      groups: groups.map((group) => ({ name: group.name, n: group.km.n, events: group.km.events, censored: group.km.censored, medianSurvival: group.km.medianSurvival })),
      logRank: logRank ? { chi2: logRank.chi2, df: logRank.df, p: logRank.p } : null,
      pairwise: logRank?.pairwise ?? [],
      medianFollowup,
      cutoff,
      strategy: opts.inputMode === 'expression' ? opts.strategy : null,
      joinMatched,
      optimalP,
    },
  }
}

export function buildWorkshopResult(kind: ChartKind, table: ParsedTable, map: ColumnMap, config: WorkshopConfig, extras?: WorkshopExtras): WorkshopResult {
  if (!table.headers.length) return { messages: [{ severity: 'error', text: '请先上传 CSV、TSV 或分号分隔数据文件。' }], traces: [], layout: layoutBase(kind, config), config: { responsive: true, displaylogo: false }, summaries: [], statistics: [], validRows: 0 }
  if (kind === 'bar' || kind === 'boxplot' || kind === 'violin') return processGrouped(kind, table, map, config)
  if (kind === 'scatter') return processScatter(table, map, config)
  if (kind === 'heatmap') return processHeatmap(table, map, config)
  if (kind === 'corr-heatmap') return processCorrelationHeatmap(table, map, config)
  if (kind === 'histogram') return processHistogram(table, map, config)
  if (kind === 'mean-error') return processMeanError(table, map, config)
  if (kind === 'pca') return processPca(table, map, config)
  if (kind === 'enrichment') return processEnrichment(table, config)
  if (kind === 'survival') return processSurvival(table, map, config, extras?.survival)
  return processLine(table, map, config)
}

export function resultToCsv(rows: Array<Record<string, string | number>>) {
  if (!rows.length) return ''
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))))
  return [headers.join(','), ...rows.map((row) => headers.map((header) => `"${String(row[header] ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')
}
