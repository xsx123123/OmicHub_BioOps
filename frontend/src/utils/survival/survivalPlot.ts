/**
 * Plotly figure builder for Kaplan–Meier curves: stepped survival lines,
 * censor ticks, optional 95% CI ribbons, median-survival guides, an in-plot
 * log-rank p annotation and a "number at risk" table on a second y domain.
 * All colors are concrete values resolved for the current theme — never
 * `var(--xxx)` inside chart options (see frontend.md §13.2).
 */
import * as Plotly from 'plotly.js-dist-min'
import { numberAtRisk } from './kmEstimator'
import type { LogRankResult, SurvivalGroupResult } from './survivalTypes'

export interface SurvivalPlotStyle {
  title: string
  xTitle: string
  lineWidth: number
  showCI: boolean
  showCensors: boolean
  showRiskTable: boolean
  width: number
  height: number
  legend?: Partial<Plotly.Legend>
}

export interface SurvivalFigure {
  traces: Plotly.Data[]
  layout: Partial<Plotly.Layout>
}

interface ThemePalette {
  font: string
  muted: string
  grid: string
  axis: string
}

function themePalette(isDark: boolean): ThemePalette {
  return isDark
    ? { font: '#e6e6e6', muted: '#9aa4b2', grid: '#2c3542', axis: '#8a8a8a' }
    : { font: '#333333', muted: '#64748b', grid: '#e2e8f0', axis: '#9a9a9a' }
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const r = parseInt(full.slice(0, 2), 16)
  const g = parseInt(full.slice(2, 4), 16)
  const b = parseInt(full.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

export function formatLogRankP(p: number): string {
  return p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`
}

/** 5–7 evenly spaced tick times aligned with the x axis, starting at 0. */
export function riskTableTimes(maxTime: number): number[] {
  if (!(maxTime > 0)) return [0]
  const target = 6
  const roughStep = maxTime / (target - 1)
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const candidates = [1, 2, 2.5, 5, 10].map((base) => base * magnitude)
  const step = candidates.reduce((best, candidate) => (Math.abs(candidate - roughStep) < Math.abs(best - roughStep) ? candidate : best))
  const times: number[] = []
  for (let time = 0; time <= maxTime + step * 1e-9; time += step) times.push(Math.round(time / step) * step)
  while (times.length > 7) times.splice(times.length - 2, 1)
  return times
}

export function buildSurvivalFigure(
  groups: SurvivalGroupResult[],
  logRank: LogRankResult | null,
  style: SurvivalPlotStyle,
  isDark: boolean,
  colors: string[],
): SurvivalFigure {
  const palette = themePalette(isDark)
  const traces: Plotly.Data[] = []
  const maxTime = Math.max(...groups.map((group) => group.km.maxTime), 1)

  groups.forEach((group, index) => {
    const color = colors[index % colors.length]
    const points = group.km.points
    const last = points[points.length - 1]
    const stepX = [...points.map((point) => point.time), group.km.maxTime]
    const stepY = [...points.map((point) => point.survival), last.survival]

    if (style.showCI) {
      const ciX = [...points.map((point) => point.time), group.km.maxTime, ...[...points.map((point) => point.time), group.km.maxTime].reverse()]
      const ciY = [...points.map((point) => point.upper95), last.upper95, ...[...points.map((point) => point.lower95), last.lower95].reverse()]
      traces.push({
        type: 'scatter', mode: 'lines', x: ciX, y: ciY,
        fill: 'toself', fillcolor: hexToRgba(color, 0.15),
        line: { color: 'transparent', shape: 'hv' },
        hoverinfo: 'skip', showlegend: false, legendgroup: group.name,
      })
    }

    traces.push({
      type: 'scatter', mode: 'lines', name: group.name,
      x: stepX, y: stepY,
      line: { color, shape: 'hv', width: style.lineWidth },
      legendgroup: group.name,
      hovertemplate: `Time: %{x:.4g}<br>Survival: %{y:.4f}<extra>${group.name}</extra>`,
    })

    if (style.showCensors && group.km.censorMarks.length) {
      traces.push({
        type: 'scatter', mode: 'markers', name: `${group.name} censored`,
        x: group.km.censorMarks.map((mark) => mark.time),
        y: group.km.censorMarks.map((mark) => mark.survival),
        marker: { symbol: 'cross', size: 8, color, line: { width: 1.5, color } },
        legendgroup: group.name, showlegend: false,
        hovertemplate: `Censored<br>Time: %{x:.4g}<br>Survival: %{y:.4f}<extra>${group.name}</extra>`,
      })
    }
  })

  const annotations: Partial<Plotly.Annotations>[] = []
  const shapes: Partial<Plotly.Shape>[] = []

  // median-survival guides: horizontal 0.5 line + dashed verticals per group
  const withMedian = groups.filter((group) => group.km.medianSurvival !== null)
  if (withMedian.length) {
    shapes.push({ type: 'line', xref: 'x', yref: 'y', x0: 0, x1: maxTime, y0: 0.5, y1: 0.5, line: { color: palette.muted, width: 1, dash: 'dot' } })
    withMedian.forEach((group) => {
      const index = groups.indexOf(group)
      shapes.push({
        type: 'line', xref: 'x', yref: 'y',
        x0: group.km.medianSurvival ?? 0, x1: group.km.medianSurvival ?? 0, y0: 0, y1: 0.5,
        line: { color: colors[index % colors.length], width: 1, dash: 'dash' },
      })
    })
  }

  if (logRank && Number.isFinite(logRank.p)) {
    annotations.push({
      xref: 'x domain', yref: 'y domain', x: 0.03, y: 0.08, xanchor: 'left', yanchor: 'bottom',
      text: `Log-rank χ²(${logRank.df}) = ${logRank.chi2.toFixed(2)}, ${formatLogRankP(logRank.p)}`,
      showarrow: false, font: { size: 12, color: palette.font },
      bgcolor: hexToRgba(isDark ? '#141414' : '#ffffff', 0.7),
    })
  }

  const layout: Partial<Plotly.Layout> = {
    title: { text: style.title, x: 0.02 },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { family: 'Inter, system-ui, sans-serif', color: palette.font },
    margin: { l: 72, r: 34, t: 64, b: 56 },
    width: style.width,
    height: style.height,
    autosize: false,
    hovermode: 'closest',
    showlegend: true,
    legend: style.legend,
    shapes,
    annotations,
    xaxis: {
      title: { text: style.xTitle },
      gridcolor: palette.grid,
      zeroline: false,
      range: [0, maxTime * 1.02],
    },
    yaxis: {
      title: { text: 'Survival probability' },
      gridcolor: palette.grid,
      zeroline: false,
      range: [0, 1.02],
      domain: style.showRiskTable ? [0.3, 1] : [0, 1],
    },
  }

  if (style.showRiskTable) {
    const times = riskTableTimes(maxTime)
    groups.forEach((group, index) => {
      const color = colors[index % colors.length]
      traces.push({
        type: 'scatter', mode: 'text',
        x: times,
        y: times.map(() => groups.length - 1 - index),
        text: times.map((time) => String(numberAtRisk(group.records, time))),
        textfont: { size: 11, color },
        yaxis: 'y2',
        hoverinfo: 'skip',
        showlegend: false,
      })
    })
    layout.xaxis = { ...(layout.xaxis ?? {}), anchor: 'y2' }
    layout.yaxis2 = {
      domain: [0, 0.16],
      range: [-0.7, groups.length - 0.3],
      tickvals: groups.map((_, index) => groups.length - 1 - index),
      ticktext: groups.map((group) => group.name),
      tickfont: { size: 11, color: palette.muted },
      showgrid: false,
      zeroline: false,
      showline: false,
      title: { text: 'Number at risk', font: { size: 11, color: palette.muted } },
    }
    layout.margin = { l: 72, r: 34, t: 64, b: 76 }
  }

  return { traces, layout }
}
