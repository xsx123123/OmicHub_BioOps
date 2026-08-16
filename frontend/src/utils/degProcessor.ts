/**
 * DEG 差异表达分析处理器 —— 纯函数模块：火山图构建、显著性分类、格式化。
 * 视图只管交互与 Plotly.react/purge，数据处理都在这里。
 *
 * 配色与 R 脚本 run_deseq2.r / run_edger.r 的火山图口径一致：
 * Up #e41749 / Down #41b6e6 / NS #D3D3D3。
 */

import type { PlotlyFigure } from '@/utils/geneExpressionProcessor'
import type { DegGeneRow } from '@/types/deg'

export const DEG_COLORS = {
  up: '#e41749',
  down: '#41b6e6',
  ns: '#D3D3D3',
} as const

export type DegSignificance = 'Up-regulated' | 'Down-regulated' | 'Non-significant'

/** 按阈值分类基因（与 R 脚本同口径：raw pvalue + |log2FC|）。 */
export function classifyGene(
  row: DegGeneRow,
  pvalCutoff: number,
  lfcCutoff: number,
): DegSignificance {
  if (row.pvalue < pvalCutoff && row.log2_fc > lfcCutoff) return 'Up-regulated'
  if (row.pvalue < pvalCutoff && row.log2_fc < -lfcCutoff) return 'Down-regulated'
  return 'Non-significant'
}

/** p 值为 0 时夹到最小正数，避免 -log10 产生 Infinity（同 R 脚本口径）。 */
export function safeMinusLog10P(pvalue: number): number {
  const p = pvalue > 0 ? pvalue : Number.MIN_VALUE
  return -Math.log10(p)
}

export function formatScientific(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'NA'
  if (value === 0) return '0'
  if (Math.abs(value) >= 0.001 && Math.abs(value) < 1000) return value.toFixed(digits)
  return value.toExponential(digits)
}

export function formatLog2Fc(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'NA'
  return value.toFixed(2)
}

export interface DegVolcanoOptions {
  contrastName: string
  pvalCutoff: number
  lfcCutoff: number
  isDark: boolean
  width?: number
  height?: number
}

/** 由 Top 基因行构建交互式火山图 Plotly 配置。 */
export function buildVolcanoFigure(
  rows: DegGeneRow[],
  options: DegVolcanoOptions,
): PlotlyFigure {
  const { contrastName, pvalCutoff, lfcCutoff, isDark } = options
  const textColor = isDark ? '#e5e6eb' : '#1d2129'
  const gridColor = isDark ? '#3a3f4b' : '#e5e6eb'
  const bgColor = 'rgba(0,0,0,0)'

  const groups: Record<DegSignificance, DegGeneRow[]> = {
    'Up-regulated': [],
    'Down-regulated': [],
    'Non-significant': [],
  }
  for (const row of rows) {
    groups[classifyGene(row, pvalCutoff, lfcCutoff)].push(row)
  }

  const traceOf = (key: DegSignificance, color: string, size: number) => {
    const members = groups[key]
    return {
      type: members.length > 5000 ? 'scattergl' : 'scatter',
      mode: 'markers',
      name: key,
      x: members.map((r) => r.log2_fc),
      y: members.map((r) => safeMinusLog10P(r.pvalue)),
      text: members.map(
        (r) =>
          `${r.symbol || r.ensembl}<br>log2FC = ${formatLog2Fc(r.log2_fc)}` +
          `<br>P-value = ${formatScientific(r.pvalue)}` +
          `<br>padj = ${formatScientific(r.padj)}`,
      ),
      hoverinfo: 'text',
      marker: { size, color, opacity: 0.75 },
    }
  }

  const xValues = rows.map((r) => Math.abs(r.log2_fc))
  const xMax = Math.min(Math.max(1, ...xValues) * 1.2, 9)

  return {
    data: [
      traceOf('Non-significant', DEG_COLORS.ns, 5),
      traceOf('Down-regulated', DEG_COLORS.down, 6),
      traceOf('Up-regulated', DEG_COLORS.up, 6),
    ],
    layout: {
      title: { text: `${contrastName} Volcano Plot`, font: { size: 14, color: textColor } },
      paper_bgcolor: bgColor,
      plot_bgcolor: bgColor,
      font: { color: textColor, family: 'sans-serif' },
      xaxis: {
        title: { text: 'RNA-seq log2 fold change' },
        gridcolor: gridColor,
        zeroline: false,
        range: [-xMax, xMax],
      },
      yaxis: {
        title: { text: '-log10(P-value)' },
        gridcolor: gridColor,
        zeroline: false,
      },
      shapes: [
        vline(lfcCutoff),
        vline(-lfcCutoff),
        hline(safeMinusLog10P(pvalCutoff)),
      ],
      legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center' },
      margin: { t: 40, r: 30, b: 60, l: 60 },
      width: options.width,
      height: options.height ?? 480,
    },
    config: { responsive: true, displaylogo: false },
  } as unknown as PlotlyFigure
}

function vline(x: number) {
  return {
    type: 'line',
    x0: x,
    x1: x,
    y0: 0,
    y1: 1,
    yref: 'paper',
    line: { color: '#C0C0C0', width: 1, dash: 'dot' },
  }
}

function hline(y: number) {
  return {
    type: 'line',
    x0: 0,
    x1: 1,
    xref: 'paper',
    y0: y,
    y1: y,
    line: { color: '#C0C0C0', width: 1, dash: 'dot' },
  }
}
