/**
 * 曼哈顿图数据处理与 Plotly 配置生成。
 *
 * 纯函数模块，不依赖 Vue：解析表格 → 列识别 → 校验 → 染色体排序 →
 * 累积 X 坐标 → Plotly traces/layout（含阈值线、选中高亮、暗黑模式）。
 */
import * as Plotly from 'plotly.js-dist-min'

// ===== 类型 =====
export interface ManhattanConfig {
  suggestiveLine: number
  genomeWideLine: number
  showSuggestiveLine: boolean
  showGenomeWideLine: boolean
  colorScheme: 'classic' | 'pastel' | 'grayscale' | 'custom'
  signalColor: string
  pointSize: number
  pointOpacity: number
  showChrLabels: boolean
  showGeneInHover: boolean
  yAxisMax: 'auto' | number
  yAxisTitle: string
  xAxisTitle: string
  showGrid: boolean
}

export interface ColMap {
  snp: string
  chromosome: string
  position: string
  pvalue: string
  gene?: string
  effect?: string
  maf?: string
}

export interface ManhattanRow {
  snpId: string
  chromosome: string
  position: number
  pvalue: number
  negLogP: number
  gene?: string
  effect?: number
  maf?: number
  isSignificant: boolean
  isSuggestive: boolean
}

export interface ManhattanStats {
  totalSnpCount: number
  genomeWideCount: number
  suggestiveCount: number
  maxNegLogP: number
  peakSnp: string
  chrDistribution: Record<string, number>
}

export interface ProcessedResult {
  rows: ManhattanRow[]
  stats: ManhattanStats
  chromosomeOrder: string[]
}

export interface PlotlyFigure {
  data: Plotly.Data[]
  layout: Partial<Plotly.Layout>
  config: Partial<Plotly.Config>
}

// ===== 默认值 =====
export const DEFAULT_CONFIG: ManhattanConfig = {
  suggestiveLine: 5.0,
  genomeWideLine: 8.0,
  showSuggestiveLine: true,
  showGenomeWideLine: true,
  colorScheme: 'classic',
  signalColor: '#FF4040',
  pointSize: 4,
  pointOpacity: 0.8,
  showChrLabels: true,
  showGeneInHover: true,
  yAxisMax: 'auto',
  yAxisTitle: '-log₁₀(P-value)',
  xAxisTitle: 'Chromosome',
  showGrid: true,
}

export const CHROMOSOME_COLORS: Record<string, string[]> = {
  classic: [
    '#E74C3C', '#3498DB', '#2ECC71', '#F39C12', '#9B59B6',
    '#1ABC9C', '#E91E63', '#00BCD4', '#FF9800', '#673AB7',
  ],
  pastel: [
    '#FF9AA2', '#B5EAD7', '#C7CEEA', '#FFDAC1', '#FFF5BA',
    '#FFB7B2', '#E2F0CB', '#B5EAD7', '#C7CEEA', '#FF9AA2',
  ],
  grayscale: [
    '#333333', '#666666', '#999999', '#BBBBBB', '#555555',
    '#777777', '#444444', '#888888', '#AAAAAA', '#222222',
  ],
}

export const COLUMN_DETECTION_PATTERNS: Record<keyof ColMap, string[]> = {
  snp: ['snp', 'rsid', 'rs', 'id', 'variant', 'marker', 'snpid'],
  chromosome: ['chr', 'chrom', 'chromosome', 'scaffold', 'lg'],
  position: ['pos', 'position', 'bp', 'coord', 'posi', 'location'],
  pvalue: ['pvalue', 'p-value', 'p_value', 'p.value', 'pval', 'pv'],
  gene: ['gene', 'nearest_gene', 'gene_id', 'nearestgene'],
  effect: ['beta', 'effect', 'b', 'or', 'odds_ratio'],
  maf: ['maf', 'freq', 'eaf', 'frequency'],
}

// ===== 列识别 =====
export function autoDetectColumns(headers: string[]): Partial<ColMap> {
  const colMap: Partial<ColMap> = {}
  const lowerHeaders = headers.map((h) => h.toLowerCase().trim())

  for (const [field, patterns] of Object.entries(COLUMN_DETECTION_PATTERNS)) {
    for (let i = 0; i < lowerHeaders.length; i++) {
      const h = lowerHeaders[i]
      const match = patterns.some((p) => h === p || h.includes(p))
      if (match) {
        colMap[field as keyof ColMap] = headers[i]
        break
      }
    }
  }
  return colMap
}

// ===== 解析 =====
export function parseDelimited(text: string): { headers: string[]; rows: Record<string, string>[] } {
  const normalized = text.replace(/\r\n/g, '\n')
  const lines = normalized.split('\n').filter((l) => l.trim() !== '')
  if (lines.length < 2) throw new Error('文件至少需要包含表头和一行数据')

  const first = lines[0]
  const delimiter: string | RegExp = first.includes('\t')
    ? '\t'
    : first.includes(',')
      ? ','
      : /\s+/

  const split = (line: string) =>
    delimiter instanceof RegExp ? line.split(delimiter).filter(Boolean) : line.split(delimiter)

  const headers = split(first).map((h) => h.trim().replace(/^"|"$/g, ''))
  const rows = lines.slice(1).map((line) => {
    const values = split(line).map((v) => v.trim().replace(/^"|"$/g, ''))
    const row: Record<string, string> = {}
    headers.forEach((h, i) => {
      row[h] = values[i] ?? ''
    })
    return row
  })
  return { headers, rows }
}

// ===== 校验 =====
export function validateData(rows: Record<string, string>[], colMap: ColMap): string[] {
  const errors: string[] = []
  rows.forEach((row, i) => {
    const pvalRaw = row[colMap.pvalue]
    const pval = Number(pvalRaw)
    if (!Number.isFinite(pval) || pval <= 0 || pval > 1) {
      errors.push(`第 ${i + 2} 行: P-value "${pvalRaw}" 无效(应在 0~1 之间)`)
    }
    const posRaw = row[colMap.position]
    const pos = Number(posRaw)
    if (!Number.isFinite(pos) || pos < 0 || !Number.isInteger(pos)) {
      errors.push(`第 ${i + 2} 行: Position "${posRaw}" 无效(应为非负整数)`)
    }
    if (!row[colMap.snp] || !String(row[colMap.snp]).trim()) {
      errors.push(`第 ${i + 2} 行: SNP 标识为空`)
    }
  })
  return errors
}

// ===== 染色体标准化 =====
export function normalizeChromosome(chr: string): string {
  const cleaned = String(chr).toUpperCase().replace(/^CHR/, '').trim()
  return cleaned
}

export function getChromosomeOrder(chrs: string[]): string[] {
  const numeric = chrs
    .filter((c) => /^\d+$/.test(c))
    .sort((a, b) => Number(a) - Number(b))
  const stringChrs = chrs.filter((c) => !/^\d+$/.test(c))
  const stringOrder = ['X', 'Y', 'MT', 'M']
  const sortedStrings = stringChrs.sort((a, b) => {
    const idxA = stringOrder.indexOf(a)
    const idxB = stringOrder.indexOf(b)
    if (idxA >= 0 && idxB >= 0) return idxA - idxB
    if (idxA >= 0) return -1
    if (idxB >= 0) return 1
    return String(a).localeCompare(String(b))
  })
  return [...numeric, ...sortedStrings]
}

// ===== 数据处理 =====
export function processManhattanData(
  rawRows: Record<string, string>[],
  colMap: ColMap,
  config: ManhattanConfig,
): ProcessedResult {
  const rows: ManhattanRow[] = rawRows
    .map((row) => {
      const pvalue = Number(row[colMap.pvalue])
      const negLogP = -Math.log10(pvalue)
      const geneRaw = colMap.gene ? row[colMap.gene] : undefined
      const effectRaw = colMap.effect ? row[colMap.effect] : undefined
      const mafRaw = colMap.maf ? row[colMap.maf] : undefined
      return {
        snpId: String(row[colMap.snp] || ''),
        chromosome: normalizeChromosome(row[colMap.chromosome]),
        position: Number(row[colMap.position]) || 0,
        pvalue,
        negLogP,
        gene: geneRaw ? String(geneRaw).trim() : undefined,
        effect: effectRaw ? Number(effectRaw) : undefined,
        maf: mafRaw ? Number(mafRaw) : undefined,
        isSignificant: negLogP >= config.genomeWideLine,
        isSuggestive: negLogP >= config.suggestiveLine && negLogP < config.genomeWideLine,
      }
    })
    .filter((r) => r.snpId && r.chromosome && Number.isFinite(r.pvalue) && r.pvalue > 0)

  const chromosomeOrder = getChromosomeOrder([...new Set(rows.map((r) => r.chromosome))])
  const stats = computeStats(rows, config)

  return { rows, stats, chromosomeOrder }
}

function computeStats(rows: ManhattanRow[], config: ManhattanConfig): ManhattanStats {
  let genomeWideCount = 0
  let suggestiveCount = 0
  let maxNegLogP = 0
  let peakSnp = ''
  const chrDistribution: Record<string, number> = {}

  rows.forEach((row) => {
    if (row.isSignificant) genomeWideCount++
    else if (row.isSuggestive) suggestiveCount++
    if (row.negLogP > maxNegLogP) {
      maxNegLogP = row.negLogP
      peakSnp = row.snpId
    }
    chrDistribution[row.chromosome] = (chrDistribution[row.chromosome] || 0) + 1
  })

  return {
    totalSnpCount: rows.length,
    genomeWideCount,
    suggestiveCount,
    maxNegLogP,
    peakSnp,
    chrDistribution,
  }
}

// ===== X 坐标累积 =====
export function computeXPositions(
  rows: ManhattanRow[],
  chromosomeOrder: string[],
): { xPositions: Map<string, number>; chrBoundaries: Array<{ chromosome: string; start: number; end: number; mid: number }> } {
  const chrGroups = new Map<string, ManhattanRow[]>()
  rows.forEach((row) => {
    if (!chrGroups.has(row.chromosome)) chrGroups.set(row.chromosome, [])
    chrGroups.get(row.chromosome)!.push(row)
  })

  chromosomeOrder.forEach((chr) => {
    const group = chrGroups.get(chr)
    if (group) group.sort((a, b) => a.position - b.position)
  })

  const xPositions = new Map<string, number>()
  const chrBoundaries: Array<{ chromosome: string; start: number; end: number; mid: number }> = []
  let currentX = 0
  const scale = 1e6

  chromosomeOrder.forEach((chr) => {
    const group = chrGroups.get(chr)
    if (!group || group.length === 0) return

    const maxPos = group[group.length - 1].position
    group.forEach((row) => {
      const x = currentX + row.position / scale
      xPositions.set(`${chr}_${row.snpId}`, x)
    })

    const start = currentX
    const end = currentX + maxPos / scale
    chrBoundaries.push({ chromosome: chr, start, end, mid: (start + end) / 2 })
    currentX = end + (maxPos / scale) * 0.02
  })

  return { xPositions, chrBoundaries }
}

// ===== 主题 =====
function getPlotTheme(isDark: boolean) {
  return isDark
    ? {
        plot_bgcolor: '#1a1a2e',
        paper_bgcolor: '#16162a',
        font: { color: '#e0e0e0' },
        gridcolor: '#2a2a4a',
        zerolinecolor: '#2a2a4a',
      }
    : {
        plot_bgcolor: '#fafafa',
        paper_bgcolor: '#ffffff',
        font: { color: '#1d2129' },
        gridcolor: '#e5e6eb',
        zerolinecolor: '#e5e6eb',
      }
}

// ===== 图表配置 =====
export function buildPlotlyFigure(
  result: ProcessedResult,
  config: ManhattanConfig,
  isDark: boolean,
  selectedSnpIds?: Set<string>,
  hoveredSnpId?: string | null,
): PlotlyFigure {
  const { rows, chromosomeOrder } = result
  const useGL = rows.length > 5000
  const { xPositions, chrBoundaries } = computeXPositions(rows, chromosomeOrder)

  const rowsWithX = rows.map((row) => ({
    ...row,
    x: xPositions.get(`${row.chromosome}_${row.snpId}`) || 0,
  }))

  const colors = CHROMOSOME_COLORS[config.colorScheme] || CHROMOSOME_COLORS.classic
  const traces: Plotly.Data[] = []

  chromosomeOrder.forEach((chr, chrIdx) => {
    const chrRows = rowsWithX.filter((r) => r.chromosome === chr)
    const color = colors[chrIdx % colors.length]

    const normalRows = chrRows.filter((r) => !r.isSignificant && !r.isSuggestive)
    if (normalRows.length > 0) {
      traces.push({
        type: useGL ? 'scattergl' : 'scatter',
        mode: 'markers',
        x: normalRows.map((r) => r.x),
        y: normalRows.map((r) => r.negLogP),
        customdata: normalRows.map((r) => [r.snpId, r.chromosome, r.position, r.pvalue, r.gene ?? '']) as any,
        marker: {
          color,
          size: config.pointSize,
          opacity: config.pointOpacity,
        },
        name: `Chr${chr}`,
        showlegend: false,
        hovertemplate: buildHoverTemplate(config),
      })
    }

    const suggestiveRows = chrRows.filter((r) => r.isSuggestive)
    if (suggestiveRows.length > 0) {
      traces.push({
        type: useGL ? 'scattergl' : 'scatter',
        mode: 'markers',
        x: suggestiveRows.map((r) => r.x),
        y: suggestiveRows.map((r) => r.negLogP),
        customdata: suggestiveRows.map((r) => [r.snpId, r.chromosome, r.position, r.pvalue, r.gene ?? '']) as any,
        marker: {
          color: '#F39C12',
          size: config.pointSize + 2,
          opacity: 1.0,
          symbol: 'diamond',
        },
        name: `Suggestive (Chr${chr})`,
        showlegend: false,
        hovertemplate: buildHoverTemplate(config),
      })
    }

    const sigRows = chrRows.filter((r) => r.isSignificant)
    if (sigRows.length > 0) {
      traces.push({
        type: useGL ? 'scattergl' : 'scatter',
        mode: 'markers',
        x: sigRows.map((r) => r.x),
        y: sigRows.map((r) => r.negLogP),
        customdata: sigRows.map((r) => [r.snpId, r.chromosome, r.position, r.pvalue, r.gene ?? '']) as any,
        marker: {
          color: config.signalColor,
          size: config.pointSize + 4,
          opacity: 1.0,
          symbol: 'star',
          line: { color: '#fff', width: 1 },
        },
        name: `Genome-wide (Chr${chr})`,
        showlegend: false,
        hovertemplate: buildHoverTemplate(config),
      })
    }
  })

  // 选中/高亮 trace（置顶）
  if (selectedSnpIds && selectedSnpIds.size > 0) {
    const selected = rowsWithX.filter((r) => selectedSnpIds.has(r.snpId))
    if (selected.length > 0) {
      traces.push({
        type: 'scatter',
        mode: 'markers',
        x: selected.map((r) => r.x),
        y: selected.map((r) => r.negLogP),
        customdata: selected.map((r) => [r.snpId, r.chromosome, r.position]),
        marker: {
          color: '#00FF88',
          size: config.pointSize + 8,
          opacity: 1.0,
          symbol: 'circle',
          line: { color: '#fff', width: 2 },
        },
        name: 'Selected',
        showlegend: true,
        hovertemplate: '<b>%{customdata[0]}</b><br>Chr%{customdata[1]}: %{customdata[2]}<br>SELECTED<extra></extra>',
      })
    }
  }

  // Hover 预览点（黄色光圈）
  if (hoveredSnpId) {
    const hovered = rowsWithX.find((r) => r.snpId === hoveredSnpId)
    if (hovered) {
      traces.push({
        type: 'scatter',
        mode: 'markers',
        x: [hovered.x],
        y: [hovered.negLogP],
        customdata: [[hovered.snpId]],
        marker: {
          color: 'transparent',
          size: config.pointSize + 12,
          opacity: 1,
          line: { color: '#FFD700', width: 2 },
          symbol: 'circle-open',
        },
        name: 'Hovered',
        showlegend: false,
        hoverinfo: 'skip',
      })
    }
  }

  // 阈值线
  const shapes: Partial<Plotly.Shape>[] = []
  const yMax =
    config.yAxisMax === 'auto'
      ? Math.max(10, Math.ceil(result.stats.maxNegLogP * 1.1))
      : config.yAxisMax

  if (config.showSuggestiveLine) {
    shapes.push({
      type: 'line',
      x0: 0,
      x1: 1,
      xref: 'paper',
      y0: config.suggestiveLine,
      y1: config.suggestiveLine,
      line: { color: '#9467BD', width: 1, dash: 'dash' },
    })
  }
  if (config.showGenomeWideLine) {
    shapes.push({
      type: 'line',
      x0: 0,
      x1: 1,
      xref: 'paper',
      y0: config.genomeWideLine,
      y1: config.genomeWideLine,
      line: { color: '#E74C3C', width: 1.5, dash: 'dash' },
    })
  }

  const annotations: Partial<Plotly.Annotations>[] = []
  if (config.showSuggestiveLine) {
    annotations.push({
      x: 1,
      y: config.suggestiveLine,
      xref: 'paper',
      text: `Suggestive (p=1e-${config.suggestiveLine.toFixed(1)})`,
      showarrow: false,
      font: { size: 10, color: '#9467BD' },
      xanchor: 'right',
      yanchor: 'bottom',
    })
  }
  if (config.showGenomeWideLine) {
    annotations.push({
      x: 1,
      y: config.genomeWideLine,
      xref: 'paper',
      text: `Genome-wide (p=1e-${config.genomeWideLine.toFixed(1)})`,
      showarrow: false,
      font: { size: 10, color: '#E74C3C' },
      xanchor: 'right',
      yanchor: 'bottom',
    })
  }

  const theme = getPlotTheme(isDark)
  const layout: Partial<Plotly.Layout> = {
    ...theme,
    title: {
      text: 'Manhattan Plot',
      font: { size: 16, color: theme.font.color },
      x: 0.5,
    },
    xaxis: {
      title: { text: config.xAxisTitle, font: { size: 13, color: theme.font.color } },
      tickmode: 'array',
      tickvals: config.showChrLabels ? chrBoundaries.map((b) => b.mid) : [],
      ticktext: config.showChrLabels ? chrBoundaries.map((b) => String(b.chromosome)) : [],
      showgrid: config.showGrid,
      gridcolor: isDark ? '#2a2a4a' : '#e5e6eb',
      tickangle: 0,
      color: theme.font.color,
      zeroline: false,
    },
    yaxis: {
      title: { text: config.yAxisTitle, font: { size: 13, color: theme.font.color } },
      range: [0, yMax],
      showgrid: config.showGrid,
      gridcolor: isDark ? '#2a2a4a' : '#e5e6eb',
      color: theme.font.color,
      zeroline: false,
    },
    shapes,
    annotations,
    hovermode: 'closest',
    showlegend: false,
    margin: { t: 40, r: 120, b: 60, l: 60 },
    dragmode: 'select',
  }

  const plotConfig: Partial<Plotly.Config> = {
    displayModeBar: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['toImage'],
    scrollZoom: true,
    responsive: true,
  }

  return { data: traces, layout, config: plotConfig }
}

function buildHoverTemplate(config: ManhattanConfig): string {
  let template = '<b>%{customdata[0]}</b><br>'
  template += 'Chr%{customdata[1]}: %{customdata[2]}<br>'
  template += 'P-value: %{customdata[3]:.2e}<br>'
  template += '-log₁₀(P): %{y:.2f}'
  if (config.showGeneInHover) {
    template += '<br>Gene: %{customdata[4]}'
  }
  template += '<extra></extra>'
  return template
}

// ===== 示例数据 =====
export function genSampleData(): { headers: string[]; rows: Record<string, string>[] } {
  const headers = ['SNP', 'Chromosome', 'Position', 'P-value', 'Gene']
  const rows: Record<string, string>[] = []
  const chrCount = 12

  for (let chr = 1; chr <= chrCount; chr++) {
    const snpCount = 800 + Math.floor(Math.random() * 400)
    for (let i = 0; i < snpCount; i++) {
      const pos = Math.floor(Math.random() * 50000000) + 1
      let pvalue: number
      const rand = Math.random()
      if (rand < 0.005) {
        pvalue = Math.pow(10, -(8 + Math.random() * 6))
      } else if (rand < 0.02) {
        pvalue = Math.pow(10, -(5 + Math.random() * 3))
      } else {
        pvalue = Math.random() * 0.5 + 0.001
      }
      rows.push({
        SNP: `rs${1000000 + chr * 100000 + i}`,
        Chromosome: String(chr),
        Position: String(pos),
        'P-value': String(pvalue),
        Gene: `GENE_${chr}_${Math.floor(pos / 1000000)}`,
      })
    }
  }

  rows.push({ SNP: 'rs_peak_001', Chromosome: '3', Position: '12345678', 'P-value': '2.3e-12', Gene: 'PEAK1' })
  rows.push({ SNP: 'rs_peak_002', Chromosome: '7', Position: '23456789', 'P-value': '5.1e-15', Gene: 'PEAK2' })
  rows.push({ SNP: 'rs_peak_003', Chromosome: '11', Position: '34567890', 'P-value': '1.2e-10', Gene: 'PEAK3' })
  rows.push({ SNP: 'rs_peak_004', Chromosome: '5', Position: '15000000', 'P-value': '8.7e-9', Gene: 'PEAK4' })

  return { headers, rows }
}

// ===== 染色体分布迷你图 =====
export function buildChrDistributionFigure(
  chrDistribution: Record<string, number>,
  chromosomeOrder: string[],
  isDark: boolean,
): PlotlyFigure {
  const ordered = chromosomeOrder.filter((chr) => chrDistribution[chr] !== undefined)
  const counts = ordered.map((chr) => chrDistribution[chr])
  const theme = getPlotTheme(isDark)

  const data: Plotly.Data[] = [
    {
      x: ordered,
      y: counts,
      type: 'bar',
      marker: { color: '#3498DB' },
      hovertemplate: 'Chr %{x}<br>Count: %{y}<extra></extra>',
    },
  ]

  const layout: Partial<Plotly.Layout> = {
    ...theme,
    margin: { t: 10, r: 10, b: 30, l: 40 },
    xaxis: { tickfont: { size: 10, color: theme.font.color }, color: theme.font.color },
    yaxis: { tickfont: { size: 10, color: theme.font.color }, color: theme.font.color, zeroline: false },
    bargap: 0.3,
  }

  const config: Partial<Plotly.Config> = {
    displayModeBar: false,
    responsive: true,
  }

  return { data, layout, config }
}
