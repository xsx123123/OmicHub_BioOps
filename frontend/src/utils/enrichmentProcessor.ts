import type { EnrichmentRow } from '@/types/enrichment'

export type EnrichmentSource = 'GO' | 'KEGG'

export interface EnrichmentPlotStyle {
  color: string
  textColor: string
  borderColor: string
  surfaceColor: string
  width: number
  height: number
  topN?: number
}

export const ENRICHMENT_COLOR_OPTIONS = [
  { label: '蓝色', value: 'var(--kimi-chart-1)' },
  { label: '红色', value: 'var(--kimi-chart-2)' },
  { label: '绿色', value: 'var(--kimi-chart-3)' },
  { label: '紫色', value: 'var(--kimi-chart-4)' },
  { label: '橙色', value: 'var(--kimi-chart-5)' },
  { label: '青色', value: 'var(--kimi-chart-6)' },
]

export function isSourceRow(row: EnrichmentRow, source: EnrichmentSource): boolean {
  return source === 'GO' ? row.source.toUpperCase().startsWith('GO') : row.source.toUpperCase() === 'KEGG'
}

export function filterEnrichmentRows(rows: EnrichmentRow[], source: EnrichmentSource): EnrichmentRow[] {
  return rows.filter((row) => isSourceRow(row, source))
}

function geneRatioToNumber(geneRatio: string, fallback: number): number {
  const [numerator, denominator] = geneRatio.split('/', 2).map(Number)
  return Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0
    ? numerator / denominator
    : fallback
}

function parseColor(color: string): [number, number, number] | null {
  const hex = color.trim().match(/^#([\da-f]{3}|[\da-f]{6})$/i)
  if (hex) {
    const value = hex[1].length === 3 ? hex[1].split('').map((part) => part + part).join('') : hex[1]
    return [Number.parseInt(value.slice(0, 2), 16), Number.parseInt(value.slice(2, 4), 16), Number.parseInt(value.slice(4, 6), 16)]
  }
  const rgb = color.trim().match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i)
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : null
}

function mixColor(from: string, to: string, ratio: number): string {
  const start = parseColor(from)
  const end = parseColor(to)
  if (!start || !end) return to
  const mixed = start.map((value, index) => Math.round(value + (end[index] - value) * ratio))
  return `rgb(${mixed.join(', ')})`
}

function colorLuminance(color: string): number {
  const rgb = parseColor(color)
  if (!rgb) return 1
  return (rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722) / 255
}

function buildSequentialColorScale(style: EnrichmentPlotStyle): Array<[number, string]> {
  const contrastTarget = colorLuminance(style.surfaceColor) < 0.5 ? style.textColor : 'rgb(0, 0, 0)'
  return [
    [0, mixColor(style.surfaceColor, style.color, 0.2)],
    [0.55, style.color],
    [1, mixColor(style.color, contrastTarget, 0.28)],
  ]
}

function escapePlotlyText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function wrapEnrichmentLabel(value: string, maxLineLength = 34, maxLines = 2): string {
  const words = value.trim().split(/\s+/).filter(Boolean)
  if (!words.length) return ''
  const lines: string[] = []
  let current = ''
  let truncated = false

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (candidate.length <= maxLineLength || !current) {
      current = candidate
      continue
    }
    lines.push(current)
    current = word
    if (lines.length === maxLines) {
      truncated = true
      break
    }
  }
  if (!truncated && current && lines.length < maxLines) lines.push(current)
  if (!truncated && lines.join(' ').length < value.trim().length) truncated = true
  if (truncated && lines.length) lines[lines.length - 1] = `${lines[lines.length - 1].replace(/[.…]+$/, '')}…`
  return lines.map(escapePlotlyText).join('<br>')
}

export function buildEnrichmentPlot(
  rows: EnrichmentRow[],
  source: EnrichmentSource,
  style: EnrichmentPlotStyle,
): Record<string, unknown> {
  const topRows = filterEnrichmentRows(rows, source)
    .sort((left, right) => left.p_adjust - right.p_adjust)
    .slice(0, style.topN ?? 20)
    .reverse()
  const significance = topRows.map((row) => -Math.log10(Math.max(row.p_adjust, 1e-300)))

  return {
    data: [
      {
        type: 'scatter',
        mode: 'markers',
        x: topRows.map((row) => geneRatioToNumber(row.gene_ratio, row.count)),
        y: topRows.map((row) => wrapEnrichmentLabel(row.description || row.id)),
        text: topRows.map((row) => `${source}: ${row.id}`),
        customdata: topRows.map((row) => [
          escapePlotlyText(row.description || row.id),
          row.gene_ratio,
          row.pvalue,
          row.p_adjust,
          row.q_value,
          row.count,
        ]),
        hovertemplate:
          '<b>%{text}</b><br>%{customdata[0]}<br>GeneRatio=%{customdata[1]} (%{x:.4f})' +
          '<br>Count=%{customdata[5]}<br>p-value=%{customdata[2]:.2e}' +
          '<br>p.adjust=%{customdata[3]:.2e}<br>q-value=%{customdata[4]:.2e}<extra></extra>',
        marker: {
          size: topRows.map((row) => Math.min(10 + Math.sqrt(Math.max(row.count, 1)) * 3.2, 34)),
          color: significance,
          colorscale: buildSequentialColorScale(style),
          cmin: Math.min(...significance),
          cmax: Math.max(...significance),
          showscale: true,
          colorbar: {
            title: { text: '-log10<br>p.adjust', side: 'right' },
            thickness: 12,
            len: 0.72,
            outlinewidth: 0,
            tickfont: { size: 10 },
          },
          opacity: 0.9,
          line: { width: 1, color: style.surfaceColor },
        },
      },
    ],
    layout: {
      title: { text: `${source} Enrichment — Top ${topRows.length}`, x: 0.02, xanchor: 'left' },
      xaxis: {
        title: { text: 'GeneRatio' },
        gridcolor: style.borderColor,
        zerolinecolor: style.borderColor,
      },
      yaxis: {
        title: { text: source === 'GO' ? 'GO Term' : 'KEGG Pathway' },
        automargin: true,
        gridcolor: style.borderColor,
        tickfont: { size: 11 },
      },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: style.textColor },
      margin: { l: 190, r: 92, t: 56, b: 62 },
      width: style.width,
      height: style.height,
      hovermode: 'closest',
      showlegend: false,
    },
  }
}
