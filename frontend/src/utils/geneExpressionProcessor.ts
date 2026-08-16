/**
 * 基因表达矩阵 Explorer：解析、PCA、图表配置生成。
 *
 * 纯函数模块，不依赖 Vue；PCA 使用 JavaScript 原生幂迭代实现，不引入外部数学库。
 */
import * as Plotly from 'plotly.js-dist-min'
import { CONTINUOUS_PALETTES, DISCRETE_PALETTES, EXPLORER_DISCRETE_PALETTES } from '@/components/charts/palettes'

// ===== 类型 =====
export interface ExpressionMatrix {
  geneIds: string[] // 基因名列表
  sampleNames: string[] // 样本名列
  data: number[][] // 二维数值矩阵 [geneIdx][sampleIdx]
}

export interface GroupMapping {
  sample: string
  group: string
}

export interface PCAResult {
  scores: number[][] // 样本得分 [sampleIdx][PC]
  explainedVariance: number[] // 各主成分方差贡献率
  pc1: number[] // PC1 坐标
  pc2: number[] // PC2 坐标
}

export interface ProcessedData {
  matrix: ExpressionMatrix
  groups: GroupMapping[]
  pca: PCAResult
  geneVariances: number[] // 每个基因的跨样本方差
  sampleMedians: number[] // 每个样本的中位数表达
}

export interface ExplorerConfig {
  pointSize: number
  pointOpacity: number
  boxplotMode: 'all' | 'top20'
  colorScheme: string
  showOutliers: boolean
  logTransform: boolean
  showPCA: boolean
  showExpression: boolean
  showVariance: boolean
}

export const DEFAULT_CONFIG: ExplorerConfig = {
  pointSize: 10,
  pointOpacity: 0.7,
  boxplotMode: 'all',
  colorScheme: 'Friendly',
  showOutliers: true,
  logTransform: false,
  showPCA: true,
  showExpression: true,
  showVariance: true,
}

// ===== 调色方案 =====
const PALETTES: Record<string, readonly string[]> = {
  ...DISCRETE_PALETTES,
  ...EXPLORER_DISCRETE_PALETTES,
}

function resolvePalette(name: string): readonly string[] {
  return PALETTES[name] ?? PALETTES.Friendly
}

function resolveContinuousPalette(name: string): readonly string[] {
  return CONTINUOUS_PALETTES[name as keyof typeof CONTINUOUS_PALETTES] ?? CONTINUOUS_PALETTES.BluePinkYellow
}

function buildColorscale(colors: readonly string[]): Array<[number, string]> {
  return colors.map((c, i) => [i / Math.max(1, colors.length - 1), c] as [number, string])
}

// ===== 解析 =====
export function autoDetectDelimiter(text: string): string {
  const lines = text.replace(/\r\n/g, '\n').split('\n').filter((l) => l.trim() !== '')
  if (!lines.length) return ','
  let tabs = 0
  let commas = 0
  for (const line of lines.slice(0, 5)) {
    tabs += (line.match(/\t/g) || []).length
    commas += (line.match(/,/g) || []).length
  }
  if (tabs > commas) return '\t'
  if (commas > 0) return ','
  return '\\s+'
}

function splitLine(line: string, delimiter: string): string[] {
  if (delimiter === '\\s+') return line.trim().split(/\s+/)
  return line.split(delimiter)
}

function toNum(v: string): number {
  const t = v.trim()
  if (t === '' || t.toLowerCase() === 'na' || t.toLowerCase() === 'nan' || t.toLowerCase() === 'null') return NaN
  const n = Number(t)
  return Number.isFinite(n) ? n : NaN
}

export function parseExpressionMatrix(
  text: string,
  delimiter?: 'auto' | 'comma' | 'tab',
): ExpressionMatrix {
  const raw = text.replace(/\r\n/g, '\n')
  const lines = raw.split('\n').filter((l) => l.trim() !== '')
  if (!lines.length) throw new Error('文件为空')

  let delim: string
  if (delimiter === 'auto' || !delimiter) {
    delim = autoDetectDelimiter(raw)
  } else if (delimiter === 'comma') {
    delim = ','
  } else if (delimiter === 'tab') {
    delim = '\t'
  } else {
    delim = ','
  }

  const headers = splitLine(lines[0], delim).map((h) => h.trim())
  if (headers.length < 2) throw new Error('表头至少需要基因名列 + 一个样本列')

  const geneIds: string[] = []
  const data: number[][] = []

  for (let i = 1; i < lines.length; i++) {
    const cells = splitLine(lines[i], delim)
    if (cells.length < headers.length) continue
    const gene = cells[0].trim()
    if (!gene) continue
    const row: number[] = []
    for (let j = 1; j < headers.length; j++) {
      const v = toNum(cells[j])
      if (Number.isNaN(v)) {
        throw new Error(`第 ${i + 1} 行基因 "${gene}" 的数值无法解析: "${cells[j]}"`)
      }
      row.push(v)
    }
    geneIds.push(gene)
    data.push(row)
  }

  if (!geneIds.length) throw new Error('未解析到任何基因行')

  return {
    geneIds,
    sampleNames: headers.slice(1),
    data,
  }
}

export function parseGroupMapping(text: string): GroupMapping[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n').filter((l) => l.trim() !== '')
  if (!lines.length) return []

  const headers = lines[0].trim().split(/[,\t]/).map((h) => h.trim().toLowerCase())
  const sampleIdx = headers.indexOf('sample')
  const groupIdx = headers.indexOf('group')
  if (sampleIdx < 0 || groupIdx < 0) {
    throw new Error('分组表头需包含 sample 与 group 列')
  }

  const result: GroupMapping[] = []
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].trim().split(/[,\t]/)
    const sample = (cells[sampleIdx] ?? '').trim()
    const group = (cells[groupIdx] ?? '').trim()
    if (sample && group) {
      result.push({ sample, group })
    }
  }
  return result
}

// ===== 计算 =====
export function applyLogTransform(matrix: ExpressionMatrix): ExpressionMatrix {
  return {
    geneIds: matrix.geneIds,
    sampleNames: matrix.sampleNames,
    data: matrix.data.map((row) => row.map((v) => Math.log2(v + 1))),
  }
}

export function computeGeneVariances(matrix: ExpressionMatrix): number[] {
  return matrix.data.map((row) => variance(row))
}

function variance(arr: number[]): number {
  const n = arr.length
  if (n < 2) return 0
  const mean = arr.reduce((a, b) => a + b, 0) / n
  const sq = arr.reduce((sum, v) => sum + (v - mean) * (v - mean), 0)
  return sq / (n - 1)
}

function mean(arr: number[]): number {
  return arr.reduce((a, b) => a + b, 0) / arr.length
}

function normalize(v: number[]): number[] {
  const len = Math.sqrt(v.reduce((s, x) => s + x * x, 0))
  if (len === 0) return v.map(() => 0)
  return v.map((x) => x / len)
}

function randomVector(n: number, seed: number): number[] {
  // 确定性伪随机，保证可复现
  let s = seed + 12345
  const v: number[] = []
  for (let i = 0; i < n; i++) {
    s = (s * 16807) % 2147483647
    v.push((s / 2147483647) * 2 - 1)
  }
  return normalize(v)
}

function matMulVec(A: number[][], v: number[]): number[] {
  return A.map((row) => row.reduce((sum, a, i) => sum + a * v[i], 0))
}

function transpose(A: number[][]): number[][] {
  if (!A.length) return []
  const cols = A[0].length
  const out: number[][] = Array.from({ length: cols }, () => [])
  for (let i = 0; i < A.length; i++) {
    for (let j = 0; j < cols; j++) {
      out[j].push(A[i][j])
    }
  }
  return out
}

function powerIteration(A: number[][], nComp: number, maxIter = 100, tol = 1e-10) {
  const n = A.length
  const values: number[] = []
  const vectors: number[][] = []
  let working = A.map((row) => [...row])

  for (let k = 0; k < nComp; k++) {
    let v = randomVector(n, k)
    let prev = 0
    let eigenvalue = 0

    for (let iter = 0; iter < maxIter; iter++) {
      const Av = matMulVec(working, v)
      eigenvalue = Math.sqrt(Av.reduce((s, x) => s + x * x, 0))
      if (eigenvalue === 0) break
      v = normalize(Av)
      if (Math.abs(eigenvalue - prev) < tol) break
      prev = eigenvalue
    }

    values.push(eigenvalue)
    vectors.push(v)

    // deflation
    if (k < nComp - 1) {
      for (let i = 0; i < n; i++) {
        for (let j = 0; j < n; j++) {
          working[i][j] -= eigenvalue * v[i] * v[j]
        }
      }
    }
  }

  return { values, vectors }
}

export function computePCA(matrix: ExpressionMatrix, nComponents = 2): PCAResult {
  const g = matrix.data.length
  const s = matrix.sampleNames.length
  if (g === 0 || s === 0) throw new Error('表达矩阵为空')
  if (s < 2) throw new Error('PCA 至少需要 2 个样本')

  // 1. 每基因（特征）中心化
  const geneMeans = matrix.data.map((row) => mean(row))
  const centered = matrix.data.map((row, i) => row.map((v) => v - geneMeans[i]))

  // 2. 转置为样本 x 基因
  const Xs = transpose(centered) // s x g

  // 3. 基因协方差矩阵 (g x g)
  const denom = s - 1
  const C: number[][] = Array.from({ length: g }, () => Array(g).fill(0))
  for (let i = 0; i < g; i++) {
    for (let j = i; j < g; j++) {
      let sum = 0
      for (let k = 0; k < s; k++) {
        sum += Xs[k][i] * Xs[k][j]
      }
      C[i][j] = sum / denom
      if (i !== j) C[j][i] = C[i][j]
    }
  }

  const k = Math.min(nComponents, g, s)
  const { values, vectors } = powerIteration(C, k)

  // 4. 样本得分 = Xs · V
  const scores: number[][] = Xs.map((row) =>
    vectors.map((vec) => row.reduce((sum, x, i) => sum + x * vec[i], 0)),
  )

  const totalVariance = trace(C)
  const explainedVariance = values.map((ev) => (totalVariance > 0 ? ev / totalVariance : 0))

  return {
    scores,
    explainedVariance,
    pc1: scores.map((r) => r[0] ?? 0),
    pc2: scores.map((r) => r[1] ?? 0),
  }
}

function trace(A: number[][]): number {
  let sum = 0
  for (let i = 0; i < A.length; i++) sum += A[i][i]
  return sum
}

function sampleVariance(values: number[]): number {
  return variance(values)
}

export function getSampleGroup(sample: string, groups: GroupMapping[]): string | undefined {
  return groups.find((g) => g.sample === sample)?.group
}

// ===== 图表配置生成 =====
export interface PlotlyFigure {
  data: Plotly.Data[]
  layout: Partial<Plotly.Layout>
  config: Partial<Plotly.Config>
}

interface ThemePalette {
  plotBg: string
  paperBg: string
  font: string
  grid: string
  axis: string
}

function themePalette(isDark: boolean): ThemePalette {
  return isDark
    ? { plotBg: '#1a1a2e', paperBg: '#16162a', font: '#e0e0e0', grid: '#2a2a4a', axis: '#e0e0e0' }
    : { plotBg: '#fafafa', paperBg: '#ffffff', font: '#1d2129', grid: '#e5e6eb', axis: '#1d2129' }
}

export function buildExplorerFigure(
  processed: ProcessedData,
  config: ExplorerConfig,
  isDark: boolean,
): PlotlyFigure {
  const pal = themePalette(isDark)
  const traces: Plotly.Data[] = []
  const { matrix, groups, pca, geneVariances } = processed
  const samples = matrix.sampleNames

  // 分组颜色（PCA 用）与样本颜色（箱线图用）分离
  const groupNames = Array.from(new Set(groups.map((g) => g.group))).sort()
  const palette = resolvePalette(config.colorScheme)
  const groupColorMap: Record<string, string> = {}
  groupNames.forEach((g, i) => {
    groupColorMap[g] = palette[i % palette.length]
  })
  const sampleColorMap: Record<string, string> = {}
  samples.forEach((s, i) => {
    sampleColorMap[s] = palette[i % palette.length]
  })

  const groupColor = (s: string) => {
    const g = getSampleGroup(s, groups)
    return g ? groupColorMap[g] : palette[0]
  }
  const sampleColor = (s: string) => sampleColorMap[s] ?? palette[0]

  // Row 1: PCA（按分组着色）
  if (config.showPCA) {
    traces.push({
      x: pca.pc1,
      y: pca.pc2,
      mode: 'markers',
      type: 'scatter',
      name: 'PCA',
      text: samples,
      hovertemplate: '<b>%{text}</b><br>PC1: %{x:.3f}<br>PC2: %{y:.3f}<extra></extra>',
      marker: {
        size: config.pointSize,
        opacity: config.pointOpacity,
        color: groups.length ? samples.map(groupColor) : palette[0],
        line: { width: 1, color: pal.axis },
      },
      xaxis: 'x',
      yaxis: 'y',
    })
  }

  // Row 2: 样本表达箱线图（按样本着色）
  if (config.showExpression) {
    let orderedSamples = samples
    if (config.boxplotMode === 'top20' && samples.length > 20) {
      const sampleVars = samples.map((_, i) => ({
        idx: i,
        var: sampleVariance(matrix.data.map((row) => row[i])),
      }))
      sampleVars.sort((a, b) => b.var - a.var)
      orderedSamples = sampleVars.slice(0, 20).map((v) => samples[v.idx])
    }

    orderedSamples.forEach((sample) => {
      const idx = samples.indexOf(sample)
      const y = matrix.data.map((row) => row[idx])
      const color = sampleColor(sample)
      traces.push({
        y,
        type: 'box',
        name: sample,
        xaxis: 'x2',
        yaxis: 'y2',
        boxpoints: config.showOutliers ? 'outliers' : false,
        marker: { color },
        line: { color },
        fillcolor: color + '80',
      } as Plotly.Data)
    })
  }

  // Row 3: 基因方差小提琴图（连续配色）
  if (config.showVariance) {
    const continuous = resolveContinuousPalette('BluePinkYellow')
    traces.push({
      y: geneVariances,
      type: 'violin',
      name: 'Gene Variance',
      xaxis: 'x3',
      yaxis: 'y3',
      points: config.showOutliers ? 'outliers' : false,
      box: { visible: true, width: 0.08 },
      meanline: { visible: true },
      line: { color: pal.axis, width: 1 },
      fillcolor: 'rgba(160, 51, 224, 0.25)',
      marker: {
        color: geneVariances,
        colorscale: buildColorscale(continuous) as any,
        showscale: false,
        size: 6,
      },
      hovertemplate: 'variance: %{y:.3f}<extra></extra>',
    } as Plotly.Data)
  }

  const shownRows = [config.showPCA, config.showExpression, config.showVariance].filter(Boolean).length
  const rowHeights = shownRows > 0 ? Array(shownRows).fill(1 / shownRows) : [1]

  const layout: Partial<Plotly.Layout> = {
    grid: {
      rows: shownRows || 1,
      columns: 1,
      pattern: 'independent',
      roworder: 'top to bottom',
    },
    height: 780,
    paper_bgcolor: pal.paperBg,
    plot_bgcolor: pal.plotBg,
    font: { color: pal.font },
    margin: { t: 40, r: 30, b: 50, l: 60 },
    showlegend: false,
  }

  if (config.showPCA) {
    layout.xaxis = {
      title: { text: `PC1 (${(pca.explainedVariance[0] * 100).toFixed(1)}%)`, font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      zeroline: false,
    }
    layout.yaxis = {
      title: { text: `PC2 (${(pca.explainedVariance[1] * 100).toFixed(1)}%)`, font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      zeroline: false,
    }
  }

  if (config.showExpression) {
    layout.xaxis2 = {
      title: { text: 'Sample', font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      anchor: 'y2',
      tickangle: -45,
    }
    layout.yaxis2 = {
      title: { text: 'Expression Value', font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      anchor: 'x2',
      zeroline: false,
    }
  }

  if (config.showVariance) {
    layout.xaxis3 = {
      title: { text: 'Gene Variance', font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      anchor: 'y3',
      showticklabels: false,
    }
    layout.yaxis3 = {
      title: { text: 'Variance', font: { color: pal.axis } },
      gridcolor: pal.grid,
      color: pal.axis,
      anchor: 'x3',
      zeroline: false,
    }
  }

  // 显式设置每个 subplot 的 domain，避免行高被 Plotly 均分后太扁
  const available = 1 - 0.12 // 留出标题/边距后的可用空间
  const gap = 0.06
  const usable = available - gap * (shownRows - 1)
  const h = shownRows > 0 ? usable / shownRows : available
  const axisAssignments: Array<{ x: string; y: string }> = []
  if (config.showPCA) axisAssignments.push({ x: 'xaxis', y: 'yaxis' })
  if (config.showExpression) axisAssignments.push({ x: 'xaxis2', y: 'yaxis2' })
  if (config.showVariance) axisAssignments.push({ x: 'xaxis3', y: 'yaxis3' })

  axisAssignments.forEach((_, idx) => {
    const top = 1 - idx * (h + gap)
    const bottom = top - h
    const xkey = axisAssignments[idx].x as keyof Plotly.Layout
    const ykey = axisAssignments[idx].y as keyof Plotly.Layout
    ;(layout[xkey] as Partial<Plotly.LayoutAxis>) = {
      ...(layout[xkey] as Partial<Plotly.LayoutAxis>),
      domain: [0, 1],
    }
    ;(layout[ykey] as Partial<Plotly.LayoutAxis>) = {
      ...(layout[ykey] as Partial<Plotly.LayoutAxis>),
      domain: [bottom, top],
    }
  })

  const figureConfig: Partial<Plotly.Config> = {
    responsive: true,
    displaylogo: false,
    displayModeBar: true,
    toImageButtonOptions: { format: 'png', filename: 'gene_expression_explorer', scale: 2 },
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  }

  return { data: traces, layout, config: figureConfig }
}

// ===== 辅助 =====
export function genSampleData(): { matrixText: string; groupText: string } {
  const genes = Array.from({ length: 20 }, (_, i) => `GENE${String(i + 1).padStart(3, '0')}`)
  const samples = ['Treat_1', 'Treat_2', 'Treat_3', 'Treat_4', 'Ctrl_1', 'Ctrl_2', 'Ctrl_3', 'Ctrl_4']

  const matrixRows: string[] = [`gene_id,${samples.join(',')}`]
  // 确定性随机，保证示例可复现
  let seed = 42
  const rand = () => {
    seed = (seed * 9301 + 49297) % 233280
    return seed / 233280
  }

  for (const gene of genes) {
    const base = 2 + rand() * 18
    const treatmentShift = rand() > 0.5 ? 4 + rand() * 8 : -(2 + rand() * 4)
    const row = [gene]
    for (let i = 0; i < samples.length; i++) {
      const isTreat = i < 4
      const noise = (rand() - 0.5) * 3
      const v = Math.max(0, base + (isTreat ? treatmentShift : 0) + noise)
      row.push(v.toFixed(2))
    }
    matrixRows.push(row.join(','))
  }

  const groupText = ['sample,group', ...samples.map((s, i) => `${s},${i < 4 ? 'Treatment' : 'Control'}`)].join('\n')

  return { matrixText: matrixRows.join('\n'), groupText }
}

export function formatVariance(n: number): string {
  if (!Number.isFinite(n)) return 'NA'
  if (n === 0) return '0'
  if (n < 0.001 || n >= 10000) return n.toExponential(2)
  return n.toFixed(3)
}
