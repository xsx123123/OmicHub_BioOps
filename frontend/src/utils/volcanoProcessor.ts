/**
 * 火山图数据处理与 Plotly 配置生成（对齐 R 脚本 DrawVolcanoAddGene 逻辑）。
 *
 * 纯函数模块，不持有状态：解析表格 → 列映射 → 清洗（NA/p=0）→ 分组 →
 * Top N / 自定义标注 → 智能坐标轴范围 → Plotly traces/layout（含暗黑模式）。
 */
import * as Plotly from 'plotly.js-dist-min'

export type VolcanoGroup = 'up' | 'down' | 'non'

export interface VolcanoRow {
  gene: string
  padj: number
  log2fc: number
  negLog10p: number
  group: VolcanoGroup
  isTop: boolean
  isHighlighted: boolean
}

export interface VolcanoColors {
  up: string
  down: string
  non: string
  upTag: string
  downTag: string
}

export type AxisMode = 'auto' | 'manual'

export interface VolcanoConfig {
  pvalCutoff: number
  lfcCutoff: number
  expName: string
  colors: VolcanoColors
  pointSize: number
  alpha: number
  showThreshold: boolean
  labelTopN: number
  customGenes: string[]
  /** 坐标轴与标题配置（v1.1 新增）。 */
  xAxisMode: AxisMode
  xMin: number
  xMax: number
  yAxisMode: AxisMode
  yMin: number
  yMax: number
  xAxisTitle: string
  yAxisTitle: string
  plotTitle: string
  autoWrapTitle: boolean
}

export interface ColMap {
  padj: string
  lfc: string
  gene: string
}

export interface AxisRange {
  xMax: number
  yMax: number
}

export interface ProcessedResult {
  rows: VolcanoRow[]
  stats: { total: number; up: number; down: number; non: number }
  axisRange: AxisRange
}

export interface ParsedTable {
  headers: string[]
  rows: Record<string, string>[]
}

/** 默认配色（对齐 R 脚本默认值）。 */
export const DEFAULT_COLORS: VolcanoColors = {
  up: '#e41749',
  down: '#41b6e6',
  non: '#C7C7C7',
  upTag: '#7FFF00',
  downTag: '#16A085',
}

export const DEFAULT_CONFIG: VolcanoConfig = {
  pvalCutoff: 0.05,
  lfcCutoff: 1,
  expName: 'Volcano',
  colors: { ...DEFAULT_COLORS },
  pointSize: 6,
  alpha: 0.6,
  showThreshold: true,
  labelTopN: 15,
  customGenes: [],
  xAxisMode: 'auto',
  xMin: -7.5,
  xMax: 7.5,
  yAxisMode: 'auto',
  yMin: 0,
  yMax: 250,
  xAxisTitle: '',
  yAxisTitle: '',
  plotTitle: '',
  autoWrapTitle: true,
}

/** 解析 CSV/TSV/空白分隔表格，自动判定分隔符。 */
export function parseDelimited(text: string): ParsedTable {
  const lines = text.replace(/\r\n/g, '\n').split('\n').filter((l) => l.trim() !== '')
  if (!lines.length) return { headers: [], rows: [] }
  const first = lines[0]
  const delim: string | RegExp = first.includes('\t')
    ? '\t'
    : first.includes(',')
      ? ','
      : /\s+/
  const split = (line: string) =>
    delim instanceof RegExp ? line.split(delim) : line.split(delim)
  const headers = split(first).map((h) => h.trim())
  const rows = lines.slice(1).map((line) => {
    const cells = split(line)
    const row: Record<string, string> = {}
    headers.forEach((h, i) => {
      row[h] = (cells[i] ?? '').trim()
    })
    return row
  })
  return { headers, rows }
}

/** 按常见列名启发式匹配 padj / log2FC / gene 列。 */
export function autoDetectColumns(cols: string[]): ColMap {
  const norm = (c: string) => c.toLowerCase().replace(/[^a-z0-9]/g, '')
  const lower = cols.map(norm)
  const findBy = (patterns: string[]) => {
    for (const p of patterns) {
      const idx = lower.findIndex((c) => c.includes(p))
      if (idx >= 0) return cols[idx]
    }
    return ''
  }
  const gene =
    findBy(['genename', 'gene', 'symbol', 'feature', 'name', 'id']) || cols[0] || ''
  const lfc =
    findBy(['log2foldchange', 'log2fc', 'logfc', 'lfc', 'foldchange', 'fc']) || ''
  // 优先 padj/fdr，其次 pvalue
  const padj =
    findBy(['padj', 'padjust', 'fdr', 'qvalue', 'pvalue', 'pval', 'rawp']) || ''
  return { padj, lfc, gene }
}

/** 判断单元格是否为 NA / 空。 */
function isNa(v: string): boolean {
  if (v === '' || v === undefined) return true
  const low = v.toLowerCase()
  return low === 'na' || low === 'nan' || low === 'null' || low === '-'
}

/** 数值解析，NA 返回 NaN。 */
function toNum(v: string): number {
  if (isNa(v)) return NaN
  const n = Number(v)
  return Number.isFinite(n) ? n : NaN
}

/**
 * 核心数据处理 Pipeline（对齐 R 脚本）。
 * 1. 列映射 2. NA 去除 3. p<=0 → Number.MIN_VALUE 4. -log10(padj)
 * 5. 分组 6. 排序 7. Top N（上下调各 N/2）8. 自定义标注 9. 智能坐标轴范围
 */
export function processVolcanoData(
  rawData: Record<string, string>[],
  colMap: ColMap,
  config: VolcanoConfig,
): ProcessedResult {
  const rows: VolcanoRow[] = []
  if (!colMap.lfc || !colMap.padj || !rawData.length) {
    return { rows, stats: { total: 0, up: 0, down: 0, non: 0 }, axisRange: { xMax: 1, yMax: 1 } }
  }

  const customSet = new Set(config.customGenes.map((g) => g.trim()).filter(Boolean))
  const pCut = config.pvalCutoff
  const fcCut = config.lfcCutoff

  for (const r of rawData) {
    const geneRaw = colMap.gene ? r[colMap.gene] : ''
    const fc = toNum(r[colMap.lfc])
    let p = toNum(r[colMap.padj])
    if (!Number.isFinite(fc) || !Number.isFinite(p) || isNa(geneRaw)) continue
    // p=0 / p<0 → 替换为最小正值，避免 -log10(0)=Infinity
    if (p <= 0) p = Number.MIN_VALUE
    const negLog10p = -Math.log10(p)
    let group: VolcanoGroup = 'non'
    if (p < pCut && fc > fcCut) group = 'up'
    else if (p < pCut && fc < -fcCut) group = 'down'
    const gene = geneRaw.trim()
    rows.push({
      gene,
      padj: p,
      log2fc: fc,
      negLog10p,
      group,
      isTop: false,
      isHighlighted: customSet.has(gene),
    })
  }

  // 按 padj 升序（最显著在前）
  rows.sort((a, b) => a.padj - b.padj)

  // Top N：上下调各取 labelTopN/2（按显著性）
  const halfN = Math.max(1, Math.floor(config.labelTopN / 2))
  if (config.labelTopN > 0) {
    let upCount = 0
    let downCount = 0
    for (const row of rows) {
      if (row.group === 'up' && upCount < halfN) {
        row.isTop = true
        upCount++
      } else if (row.group === 'down' && downCount < halfN) {
        row.isTop = true
        downCount++
      }
    }
  }

  const stats = {
    total: rows.length,
    up: rows.filter((r) => r.group === 'up').length,
    down: rows.filter((r) => r.group === 'down').length,
    non: rows.filter((r) => r.group === 'non').length,
  }

  const axisRange = computeAxisRange(rows)
  return { rows, stats, axisRange }
}

/** 智能坐标轴范围（对齐 R 脚本）：Y 轴极端值压缩，X 轴上限 7.5。 */
function computeAxisRange(rows: VolcanoRow[]): AxisRange {
  if (!rows.length) return { xMax: 1, yMax: 1 }
  const ys = rows.map((r) => r.negLog10p).sort((a, b) => b - a) // 降序
  const maxAbsFc = Math.max(...rows.map((r) => Math.abs(r.log2fc)), 1)
  const xMax = Math.min(maxAbsFc * 1.2, 7.5)

  let yMax: number
  const top1 = ys[0]
  const top2 = ys[1] ?? top1
  if (top1 > 300) {
    yMax = 250
  } else if (top2 > 0 && top1 / top2 > 1.4) {
    yMax = (top1 + top2) / 2
  } else {
    yMax = top1 * 1.1
  }
  yMax = Math.max(yMax, 1)
  return { xMax, yMax }
}

/** 生成 Plot 标题：plotTitle 为空则回退 `{expName} Volcano Plot`；autoWrap 且长度 > 30 时从中间插入换行。 */
export function buildPlotTitle(plotTitle: string, expName: string, autoWrap: boolean): string {
  const title = plotTitle.trim() || `${expName} Volcano Plot`
  if (autoWrap && title.length > 30) {
    const mid = Math.ceil(title.length / 2)
    return `${title.slice(0, mid)}\n${title.slice(mid)}`
  }
  return title
}

interface ThemePalette {
  plotBg: string
  paperBg: string
  font: string
  grid: string
  line: string
  axis: string
}

function themePalette(isDark: boolean): ThemePalette {
  return isDark
    ? { plotBg: '#1a1a1a', paperBg: '#141414', font: '#e6e6e6', grid: '#333', line: '#aaa', axis: '#e6e6e6' }
    : { plotBg: '#fafafa', paperBg: '#ffffff', font: '#333', grid: '#eee', line: '#000', axis: '#333' }
}

export interface PlotlyFigure {
  data: Plotly.Data[]
  layout: Partial<Plotly.Layout>
  config: Partial<Plotly.Config>
}

/**
 * 构建 Plotly 图表配置：4 个 trace 分层（Non → Down → Up → 标注），
 * 阈值虚线、标题换行、暗黑模式、focus 基因引线标注。
 */
export function buildPlotlyFigure(
  rows: VolcanoRow[],
  config: VolcanoConfig,
  axisRange: AxisRange,
  isDark: boolean,
  focusGene = '',
): PlotlyFigure {
  const pal = themePalette(isDark)
  const useGL = rows.length > 5000
  const scatterType: 'scatter' | 'scattergl' = useGL ? 'scattergl' : 'scatter'
  const { xMax: xMaxAuto, yMax: yMaxAuto } = axisRange
  // 手动模式直接用 config 值；自动模式用 computeAxisRange 的结果
  const xRange: [number, number] =
    config.xAxisMode === 'manual' ? [config.xMin, config.xMax] : [-xMaxAuto, xMaxAuto]
  const yRange: [number, number] =
    config.yAxisMode === 'manual' ? [config.yMin, config.yMax] : [0, yMaxAuto]
  const c = config.colors

  const byGroup = (g: VolcanoGroup) => rows.filter((r) => r.group === g)
  const nonData = byGroup('non')
  const downData = byGroup('down')
  const upData = byGroup('up')
  const tagData = rows.filter((r) => r.isTop || r.isHighlighted)

  const baseHover =
    '<b>%{text}</b><br>log₂FC: %{x:.3f}<br>-log₁₀padj: %{y:.3f}<extra></extra>'

  const groupTrace = (
    data: VolcanoRow[],
    name: string,
    color: string,
    opacity: number,
  ): Plotly.Data => ({
    x: data.map((r) => r.log2fc),
    y: data.map((r) => r.negLog10p),
    text: data.map((r) => r.gene),
    mode: 'markers',
    type: scatterType,
    name,
    marker: { color, size: config.pointSize, opacity },
    hovertemplate: baseHover,
  })

  const traces: Plotly.Data[] = [
    groupTrace(nonData, `Non-significant (${nonData.length})`, c.non, config.alpha),
    groupTrace(downData, `Down (${downData.length})`, c.down, 1),
    groupTrace(upData, `Up (${upData.length})`, c.up, 1),
  ]

  // 标注层：markers+text，按分组着色，置顶
  if (tagData.length) {
    traces.push({
      x: tagData.map((r) => r.log2fc),
      y: tagData.map((r) => r.negLog10p),
      text: tagData.map((r) => r.gene),
      mode: 'text+markers',
      type: scatterType,
      name: `Labeled (${tagData.length})`,
      textposition: 'top center',
      textfont: { size: 10, color: pal.font },
      marker: {
        size: config.pointSize + 2,
        color: tagData.map((r) => (r.group === 'up' ? c.upTag : r.group === 'down' ? c.downTag : c.non)),
        line: { width: 1, color: pal.font },
      },
      hovertemplate: baseHover,
    })
  }

  const annotations: Partial<Plotly.Annotations>[] = []

  // focus 基因引线标注
  if (focusGene) {
    const fr = rows.find((r) => r.gene === focusGene)
    if (fr) {
      annotations.push({
        x: fr.log2fc,
        y: fr.negLog10p,
        text: `<b>${fr.gene}</b>`,
        showarrow: true,
        arrowhead: 2,
        arrowsize: 1,
        arrowwidth: 2,
        arrowcolor: pal.line,
        ax: 40,
        ay: -40,
        font: { size: 12, color: pal.font },
        bordercolor: pal.line,
        borderwidth: 1,
        borderpad: 4,
        bgcolor: pal.paperBg,
      })
    }
  }

  const shapes: Partial<Plotly.Shape>[] = config.showThreshold
    ? [
        {
          type: 'line', x0: -config.lfcCutoff, x1: -config.lfcCutoff, y0: yRange[0], y1: yRange[1],
          line: { color: pal.line, width: 1, dash: 'dash' },
        },
        {
          type: 'line', x0: config.lfcCutoff, x1: config.lfcCutoff, y0: yRange[0], y1: yRange[1],
          line: { color: pal.line, width: 1, dash: 'dash' },
        },
        {
          type: 'line', x0: xRange[0], x1: xRange[1],
          y0: -Math.log10(config.pvalCutoff), y1: -Math.log10(config.pvalCutoff),
          line: { color: pal.line, width: 1, dash: 'dash' },
        },
      ]
    : []

  const layout: Partial<Plotly.Layout> = {
    title: { text: buildPlotTitle(config.plotTitle, config.expName, config.autoWrapTitle), font: { size: 16, color: pal.font }, x: 0.5 },
    xaxis: {
      title: { text: config.xAxisTitle.trim() || `log₂ fold change (${config.expName})`, font: { color: pal.axis } },
      range: xRange,
      zeroline: false,
      gridcolor: pal.grid,
      color: pal.axis,
    },
    yaxis: {
      title: { text: config.yAxisTitle.trim() || '-log₁₀(padj)', font: { color: pal.axis } },
      range: yRange,
      zeroline: false,
      gridcolor: pal.grid,
      color: pal.axis,
    },
    margin: { t: 40, r: 30, b: 60, l: 60 },
    legend: { orientation: 'h', y: -0.15, x: 0.5, xanchor: 'center', font: { color: pal.font } },
    plot_bgcolor: pal.plotBg,
    paper_bgcolor: pal.paperBg,
    font: { color: pal.font },
    hovermode: 'closest',
    shapes,
    annotations,
  }

  const figureConfig: Partial<Plotly.Config> = {
    responsive: true,
    displaylogo: false,
    displayModeBar: true,
    toImageButtonOptions: { format: 'png', filename: 'volcano_plot', scale: 2 },
    modeBarButtonsToRemove: ['lasso2d'],
  }

  return { data: traces, layout, config: figureConfig }
}

/** p-value / padj 科学计数法格式化。 */
export function formatP(n: number): string {
  if (!Number.isFinite(n)) return 'NA'
  if (n === 0) return '0'
  if (n < 0.001 || n >= 10000) return n.toExponential(2)
  return n.toFixed(n < 0.01 ? 4 : 3)
}

/** 返回按 padj 升序的显著基因（up/down），供右侧列表展示。 */
export function getSignificantGenes(rows: VolcanoRow[], topN = 50): VolcanoRow[] {
  return rows
    .filter((r) => r.group !== 'non')
    .sort((a, b) => a.padj - b.padj)
    .slice(0, topN)
}

/** 内置示例 DEG 数据（200 行，符合火山图分布）。 */
export function genSampleData(): ParsedTable {
  const realGenes = [
    'TP53', 'BRCA1', 'BRCA2', 'EGFR', 'MYC', 'KRAS', 'PTEN', 'RB1', 'APC', 'VHL',
    'CDH1', 'AKT1', 'PIK3CA', 'BRAF', 'CCND1', 'MDM2', 'VEGFA', 'STAT3', 'JUN', 'FOS',
    'ESR1', 'AR', 'WT1', 'NF1', 'ATM', 'CHEK2', 'PALB2', 'STK11', 'CDK4', 'CCNE1',
    'MET', 'ERBB2', 'FGFR1', 'ALK', 'RET', 'ROS1', 'NTRK1', 'KIT', 'PDGFRA', 'FLT3',
    'JAK2', 'BCL2', 'MCL1', 'XIAP', 'CASP3', 'CASP8', 'CASP9', 'BAX', 'BAK1', 'PUMA',
  ]
  const rows: Record<string, string>[] = []
  const rand = (i: number) => ((Math.sin(i * 127.1 + 311.7) * 43758.5453) % 1 + 1) % 1
  for (let i = 0; i < 200; i++) {
    const gene = i < realGenes.length ? realGenes[i] : `Gene_${i}`
    const r1 = rand(i)
    const isUp = r1 > 0.6
    const isDown = !isUp && rand(i + 50) > 0.55
    let log2fc: number
    let padj: number
    if (isUp) {
      log2fc = +(1 + rand(i + 10) * 5).toFixed(3)
      padj = +(rand(i + 100) * 0.04).toExponential(3)
    } else if (isDown) {
      log2fc = +(-(1 + rand(i + 20) * 5)).toFixed(3)
      padj = +(rand(i + 200) * 0.04).toExponential(3)
    } else {
      log2fc = +((rand(i + 30) - 0.5) * 2).toFixed(3)
      padj = +(rand(i + 300) * 0.9 + 0.05).toExponential(3)
    }
    rows.push({ gene, log2FoldChange: String(log2fc), padj: String(padj) })
  }
  return { headers: ['gene', 'log2FoldChange', 'padj'], rows }
}
