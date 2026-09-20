/**
 * VennUpset 核心计算与 Plotly 图表配置（纯函数，无 Vue 依赖）。
 *
 * 列表文本解析（trim / 去空行 / 去重 / 大小写规范化）
 * → 计算所有非空交集区域（独占区域）
 * → 生成韦恩图 / UpSet 图的 Plotly traces/layout（含暗黑模式，图内标注全英文）。
 */
import * as Plotly from 'plotly.js-dist-min'

export interface NamedSet {
  name: string
  /** 去重后的元素（保留首次出现的原始写法） */
  items: string[]
}

export interface Region {
  /** 成员集合下标（升序），如 [0,2] 表示第 1、3 个集合的交集 */
  indices: number[]
  /** indices 以逗号连接的唯一键，如 "0,2" */
  key: string
  /** 恰好属于这些集合（且不属于其他任何集合）的元素 */
  elements: string[]
}

export interface ParsedList {
  /** 去重后的元素 */
  items: string[]
  /** 解析到的原始条目数（含重复与空行之前的有效 token 数） */
  rawCount: number
  /** 被去重掉的条目数 */
  dupCount: number
}

/** 支持换行 / 逗号 / 分号 / Tab / 空格混合分隔。 */
const SPLIT_RE = /[\n,;\t ]+/

/**
 * 解析列表文本：按分隔符切分、trim、去空、去重。
 * caseSensitive=false 时按小写归一化判重，保留首次出现的原始写法。
 */
export function parseListText(text: string, caseSensitive: boolean): ParsedList {
  const seen = new Set<string>()
  const items: string[] = []
  let rawCount = 0
  for (const token of text.split(SPLIT_RE)) {
    const t = token.trim()
    if (!t) continue
    rawCount++
    const k = caseSensitive ? t : t.toLowerCase()
    if (seen.has(k)) continue
    seen.add(k)
    items.push(t)
  }
  return { items, rawCount, dupCount: rawCount - items.length }
}

/**
 * 计算所有非空交集区域（独占区域）。
 * 对每个元素统计其出现在哪些集合中，按成员掩码分组。
 * 返回按「交集阶数升序、元素数降序」排序的区域列表。
 */
export function computeRegions(sets: NamedSet[], caseSensitive: boolean): Region[] {
  const norm = (s: string) => (caseSensitive ? s : s.toLowerCase())
  const member = new Map<string, { display: string; mask: boolean[] }>()
  sets.forEach((set, i) => {
    for (const item of set.items) {
      const k = norm(item)
      let e = member.get(k)
      if (!e) {
        e = { display: item, mask: sets.map(() => false) }
        member.set(k, e)
      }
      e.mask[i] = true
    }
  })
  const regionMap = new Map<string, Region>()
  for (const { display, mask } of member.values()) {
    const indices: number[] = []
    mask.forEach((m, i) => {
      if (m) indices.push(i)
    })
    if (!indices.length) continue
    const key = indices.join(',')
    let r = regionMap.get(key)
    if (!r) {
      r = { indices, key, elements: [] }
      regionMap.set(key, r)
    }
    r.elements.push(display)
  }
  const regions = [...regionMap.values()]
  for (const r of regions) r.elements.sort((a, b) => a.localeCompare(b))
  regions.sort(
    (a, b) => a.indices.length - b.indices.length || b.elements.length - a.elements.length,
  )
  return regions
}

/** 区域的可读描述，如 "A ∩ B"。 */
export function describeRegion(indices: number[], names: string[]): string {
  return indices.map((i) => names[i] ?? `集合${i + 1}`).join(' ∩ ')
}

/** 示例数据：三组有交集的常见基因列表（集合名用英文，保证图内无中文）。 */
export function genSampleLists(): { name: string; text: string }[] {
  return [
    {
      name: 'RNA-seq DEGs',
      text: [
        'TP53', 'BRCA1', 'EGFR', 'MYC', 'KRAS', 'PTEN', 'AKT1', 'CDKN1A',
        'MDM2', 'RB1', 'VEGFA', 'BCL2', 'BAX', 'CASP3', 'FOS', 'JUN',
        'STAT3', 'NFKB1', 'IL6', 'TNF', 'GAPDH', 'ACTB', 'MMP9', 'CXCL8',
      ].join('\n'),
    },
    {
      name: 'Proteomics Up',
      text: [
        'TP53', 'EGFR', 'MYC', 'AKT1', 'BCL2', 'CASP3', 'STAT3', 'MMP9',
        'HSP90AA1', 'HSPA5', 'VIM', 'ACTB', 'TUBB', 'ENO1', 'PKM', 'LDHA',
        'SOD1', 'CAT', 'GAPDH', 'CXCL8',
      ].join('\n'),
    },
    {
      name: 'GWAS Hits',
      text: [
        'BRCA1', 'BRCA2', 'TP53', 'KRAS', 'PTEN', 'APOE', 'TCF7L2', 'FTO',
        'IL6', 'TNF', 'NFKB1', 'MTHFR', 'VEGFA', 'CDKN2A', 'PALB2', 'ATM',
      ].join('\n'),
    },
  ]
}

/* ==================== 配色（对齐 tools_design.md §5.6.3.1） ==================== */

/**
 * CygnusX 标准离散色板。`color_1_extended` 为 color_1 的登记扩展版：
 * 在 4 色基础上补充青绿与紫，覆盖本工具最多 6 个集合的场景。
 */
export const PLOT_COLOR_PALETTES = {
  color_discrete_friendly: ['#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  colors_discrete_seaside: ['#8ecae6', '#219ebc', '#023047', '#ffb703', '#fb8500'],
  colors_discrete_friendly_long: ['#CC79A7', '#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  colors_discrete_friendly_long_2: ['#fe65b3', '#CC79A7', '#ffd2d8', '#0072B2', '#007aff', '#56B4E9', '#009E73', '#4cd964', '#F5C710', '#E69F00', '#D55E00', '#ff3b30'],
  colors_discrete_apple: ['#ff3b30', '#ff9500', '#ffcc00', '#4cd964', '#5ac8fa', '#007aff', '#5856d6'],
  colors_discrete_ibm: ['#5B8DFE', '#725DEE', '#DD227D', '#FE5F00', '#FFB109'],
  colors_discrete_candy: ['#9b5de5', '#f15bb5', '#fee440', '#00bbf9', '#00f5d4'],
  color_1: ['#ECA669', '#E06681', '#8087E2', '#E2D269'],
  color_1_extended: ['#ECA669', '#E06681', '#8087E2', '#E2D269', '#66B2A0', '#A086C8'],
} as const

export type PaletteKey = keyof typeof PLOT_COLOR_PALETTES

export const DEFAULT_PALETTE_KEY: PaletteKey = 'color_1_extended'

/** 色板下拉选项（label 供 NSelect 使用）。 */
export const PALETTE_OPTIONS: { label: string; value: PaletteKey }[] = [
  { label: 'Color-1 Extended（默认）', value: 'color_1_extended' },
  { label: 'Color-1', value: 'color_1' },
  { label: '色觉友好 Colorblind Friendly', value: 'color_discrete_friendly' },
  { label: '色觉友好扩展 Friendly Long', value: 'colors_discrete_friendly_long' },
  { label: '色觉友好扩展 II Friendly Long 2', value: 'colors_discrete_friendly_long_2' },
  { label: '海岸 Seaside', value: 'colors_discrete_seaside' },
  { label: 'Apple', value: 'colors_discrete_apple' },
  { label: 'IBM', value: 'colors_discrete_ibm' },
  { label: 'Candy', value: 'colors_discrete_candy' },
]

/**
 * 解析实际用色：所选色板颜色数不足集合数时，回退到色觉友好扩展色板（7 色），
 * 并通过 overflow 标记提示调用方展示告警（不静默循环复用颜色）。
 */
export function resolvePaletteColors(key: PaletteKey, nSets: number): { colors: string[]; overflow: boolean } {
  const pal = [...PLOT_COLOR_PALETTES[key]]
  if (pal.length >= nSets) return { colors: pal, overflow: false }
  return { colors: [...PLOT_COLOR_PALETTES.colors_discrete_friendly_long], overflow: true }
}

/* ==================== 样式配置 ==================== */

export interface VennUpsetStyleConfig {
  /** 图标题（留空则用默认英文标题 Venn Diagram / UpSet Plot） */
  title: string
  /** 导出宽度 px */
  width: number
  /** 导出高度 px */
  height: number
  /** 是否显示图例 */
  showLegend: boolean
  /** 离散色板 key */
  palette: PaletteKey
  /** UpSet 柱间隙比例（0~0.9，越大柱越窄；柱宽 = 1 - barGap） */
  barGap: number
}

export const DEFAULT_STYLE: VennUpsetStyleConfig = {
  title: '',
  width: 1000,
  height: 720,
  showLegend: true,
  palette: DEFAULT_PALETTE_KEY,
  barGap: 0.35,
}

/* ==================== 主题与工具函数 ==================== */

interface ThemePalette {
  plotBg: string
  paperBg: string
  font: string
  grid: string
  muted: string
  line: string
  accent: string
}

function themePalette(isDark: boolean): ThemePalette {
  return isDark
    ? { plotBg: '#1a1a1a', paperBg: '#141414', font: '#e6e6e6', grid: '#333', muted: '#3d3d3d', line: '#8a8a8a', accent: '#4C8DFF' }
    : { plotBg: '#ffffff', paperBg: '#ffffff', font: '#333333', grid: '#ececec', muted: '#dcdcdc', line: '#9a9a9a', accent: '#165DFF' }
}

export interface PlotlyFigure {
  data: Plotly.Data[]
  layout: Partial<Plotly.Layout>
  config: Partial<Plotly.Config>
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const r = parseInt(full.slice(0, 2), 16)
  const g = parseInt(full.slice(2, 4), 16)
  const b = parseInt(full.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

/** 转义用户输入，避免集合名中的 < > & 被当作 Plotly 富文本标签解析。 */
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function figureConfig(): Partial<Plotly.Config> {
  return {
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
    toImageButtonOptions: { format: 'png', filename: 'venn_upset_plot', scale: 2 },
  }
}

/* ==================== 韦恩图（2~3 集合） ==================== */

interface VennGeom {
  circles: { cx: number; cy: number; r: number }[]
  labels: Record<string, { x: number; y: number }>
  names: { x: number; y: number }[]
  range: { x: [number, number]; y: [number, number] }
}

const VENN_GEOM: Record<number, VennGeom> = {
  2: {
    circles: [
      { cx: 3.6, cy: 3.4, r: 2.3 },
      { cx: 6.4, cy: 3.4, r: 2.3 },
    ],
    labels: {
      '0': { x: 2.45, y: 3.4 },
      '1': { x: 7.55, y: 3.4 },
      '0,1': { x: 5.0, y: 3.4 },
    },
    names: [{ x: 2.1, y: 6.5 }, { x: 7.9, y: 6.5 }],
    range: { x: [0, 10], y: [0, 7.2] },
  },
  3: {
    circles: [
      { cx: 3.6, cy: 5.0, r: 2.15 },
      { cx: 6.4, cy: 5.0, r: 2.15 },
      { cx: 5.0, cy: 2.8, r: 2.15 },
    ],
    labels: {
      '0': { x: 2.65, y: 5.85 },
      '1': { x: 7.35, y: 5.85 },
      '2': { x: 5.0, y: 1.55 },
      '0,1': { x: 5.0, y: 6.05 },
      '0,2': { x: 3.7, y: 3.45 },
      '1,2': { x: 6.3, y: 3.45 },
      '0,1,2': { x: 5.0, y: 4.4 },
    },
    names: [{ x: 1.9, y: 7.9 }, { x: 8.1, y: 7.9 }, { x: 5.0, y: 0.35 }],
    range: { x: [0, 10], y: [0, 8.8] },
  },
}

/**
 * 韦恩图：圆用 layout.shapes 绘制（scaleanchor 保证正圆），
 * 区域计数用 scatter marker 文本（兼作点击热区，customdata=区域 key），
 * 集合名用 annotation；图例用置于画布外的占位 trace 实现。
 */
export function buildVennFigure(
  sets: NamedSet[],
  regions: Region[],
  style: VennUpsetStyleConfig,
  isDark: boolean,
  colors: string[],
  selectedKey: string | null,
): PlotlyFigure {
  const pal = themePalette(isDark)
  const geom = VENN_GEOM[sets.length]
  const names = sets.map((s) => s.name)

  const circleShapes: Partial<Plotly.Shape>[] = geom
    ? geom.circles.map((c, i) => ({
        type: 'circle',
        x0: c.cx - c.r,
        x1: c.cx + c.r,
        y0: c.cy - c.r,
        y1: c.cy + c.r,
        fillcolor: hexToRgba(colors[i % colors.length], 0.2),
        line: { color: colors[i % colors.length], width: 2.5 },
        layer: 'below',
      }))
    : []

  const regionPts = geom
    ? regions.filter((r) => geom.labels[r.key]).map((r) => ({
        region: r,
        pos: geom.labels[r.key],
        desc: describeRegion(r.indices, names),
      }))
    : []

  const markerColors = regionPts.map((p) =>
    p.region.key === selectedKey ? hexToRgba(pal.accent, 0.16) : 'rgba(0,0,0,0.003)',
  )
  const markerLineWidths = regionPts.map((p) => (p.region.key === selectedKey ? 1.5 : 0))

  const regionTrace: Plotly.Data = {
    x: regionPts.map((p) => p.pos.x),
    y: regionPts.map((p) => p.pos.y),
    mode: 'text+markers',
    type: 'scatter',
    text: regionPts.map((p) => `<b>${p.region.elements.length}</b>`),
    textposition: 'middle center',
    textfont: { size: 17, color: pal.font },
    marker: {
      size: 46,
      color: markerColors,
      line: { color: pal.accent, width: markerLineWidths },
    },
    customdata: regionPts.map((p) => p.region.key),
    hovertext: regionPts.map((p) => `<b>${escapeHtml(p.desc)}</b><br>Exclusive elements: ${p.region.elements.length}`),
    hoverinfo: 'text',
    showlegend: false,
  }

  const annotations: Partial<Plotly.Annotations>[] = geom
    ? geom.names.map((pos, i) => ({
        x: pos.x,
        y: pos.y,
        xref: 'x',
        yref: 'y',
        text: `<b>${escapeHtml(names[i] ?? '')}</b><br>${sets[i]?.items.length ?? 0}`,
        showarrow: false,
        font: { size: 14, color: colors[i % colors.length] },
        xanchor: 'center',
        yanchor: 'middle',
      }))
    : []

  const legendTraces: Plotly.Data[] = style.showLegend
    ? sets.map((s, i) => ({
        x: [-100],
        y: [-100],
        mode: 'markers',
        type: 'scatter',
        marker: { size: 10, color: colors[i % colors.length] },
        name: `${escapeHtml(s.name)} (${s.items.length})`,
        showlegend: true,
        hoverinfo: 'skip',
      }))
    : []

  const layout: Partial<Plotly.Layout> = {
    title: { text: style.title.trim() || 'Venn Diagram', font: { size: 17, color: pal.font }, x: 0.5 },
    xaxis: {
      range: geom ? geom.range.x : [0, 10],
      visible: false,
      scaleanchor: 'y',
      scaleratio: 1,
      constrain: 'domain',
      constraintoward: 'center',
      fixedrange: true,
    },
    yaxis: { range: geom ? geom.range.y : [0, 7.2], visible: false, fixedrange: true },
    margin: { t: 56, r: 24, b: style.showLegend ? 64 : 28, l: 24 },
    plot_bgcolor: pal.plotBg,
    paper_bgcolor: pal.paperBg,
    font: { color: pal.font },
    showlegend: style.showLegend,
    legend: { orientation: 'h', y: -0.12, x: 0.5, xanchor: 'center', font: { size: 12, color: pal.font } },
    shapes: circleShapes,
    annotations,
    hovermode: 'closest',
  }

  return { data: [regionTrace, ...legendTraces], layout, config: figureConfig() }
}

/* ==================== UpSet 图（≥2 集合） ==================== */

/**
 * UpSet 图：上部柱状图为交集大小（yaxis），下部点阵为集合成员矩阵（yaxis2），
 * 成员点按集合着色并生成图例，非成员点为灰色；成员间用竖线连接（shape）。
 * 柱与成员点均携带 customdata=区域 key，供点击选中。
 */
export function buildUpsetFigure(
  sets: NamedSet[],
  regions: Region[],
  style: VennUpsetStyleConfig,
  isDark: boolean,
  colors: string[],
  selectedKey: string | null,
  maxCols = 24,
): PlotlyFigure {
  const pal = themePalette(isDark)
  const names = sets.map((s) => s.name)
  const nSets = sets.length

  const sorted = [...regions].sort(
    (a, b) => b.elements.length - a.elements.length || a.key.localeCompare(b.key),
  )
  const cols = sorted.slice(0, maxCols)
  const nCols = cols.length
  const maxCount = Math.max(1, ...cols.map((c) => c.elements.length))
  const accent = pal.accent

  const barColors = cols.map((c) => {
    if (selectedKey == null) return hexToRgba(accent, 0.72)
    return c.key === selectedKey ? accent : hexToRgba(accent, 0.3)
  })

  const barTrace: Plotly.Data = {
    x: cols.map((_, i) => i),
    y: cols.map((c) => c.elements.length),
    type: 'bar',
    marker: {
      color: barColors,
      line: { color: accent, width: cols.map((c) => (c.key === selectedKey ? 1.5 : 0)) },
    },
    text: cols.map((c) => String(c.elements.length)),
    textposition: 'outside',
    textfont: { size: 11, color: pal.font },
    customdata: cols.map((c) => c.key),
    hovertext: cols.map((c) => `<b>${escapeHtml(describeRegion(c.indices, names))}</b><br>Elements: ${c.elements.length}`),
    hoverinfo: 'text',
    showlegend: false,
    yaxis: 'y',
    xaxis: 'x',
  }

  const mutedX: number[] = []
  const mutedY: number[] = []
  cols.forEach((c, ci) => {
    for (let si = 0; si < nSets; si++) {
      if (!c.indices.includes(si)) {
        mutedX.push(ci)
        mutedY.push(si)
      }
    }
  })
  const mutedTrace: Plotly.Data = {
    x: mutedX,
    y: mutedY,
    mode: 'markers',
    type: 'scatter',
    marker: { size: 11, color: pal.muted },
    hoverinfo: 'skip',
    showlegend: false,
    yaxis: 'y2',
    xaxis: 'x',
  }

  const setTraces: Plotly.Data[] = sets.map((s, si) => {
    const xs: number[] = []
    const keys: string[] = []
    const hovers: string[] = []
    cols.forEach((c, ci) => {
      if (c.indices.includes(si)) {
        xs.push(ci)
        keys.push(c.key)
        hovers.push(`<b>${escapeHtml(names[si] ?? '')}</b><br>${escapeHtml(describeRegion(c.indices, names))}`)
      }
    })
    return {
      x: xs,
      y: xs.map(() => si),
      mode: 'markers',
      type: 'scatter',
      marker: { size: 11, color: colors[si % colors.length], line: { color: pal.paperBg, width: 1 } },
      name: `${escapeHtml(s.name)} (${s.items.length})`,
      showlegend: style.showLegend,
      customdata: keys,
      hovertext: hovers,
      hoverinfo: 'text',
      yaxis: 'y2',
      xaxis: 'x',
    }
  })

  const lineShapes: Partial<Plotly.Shape>[] = cols
    .map((c, ci) => {
      if (c.indices.length < 2) return null
      return {
        type: 'line',
        xref: 'x',
        yref: 'y2',
        x0: ci,
        x1: ci,
        y0: Math.min(...c.indices),
        y1: Math.max(...c.indices),
        line: { color: pal.line, width: 3 },
        layer: 'below',
      } as Partial<Plotly.Shape>
    })
    .filter((s): s is Partial<Plotly.Shape> => s !== null)

  const shapes: Partial<Plotly.Shape>[] = [...lineShapes]
  const selIdx = cols.findIndex((c) => c.key === selectedKey)
  if (selIdx >= 0) {
    shapes.push({
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: selIdx - 0.45,
      x1: selIdx + 0.45,
      y0: 0,
      y1: 1,
      fillcolor: hexToRgba(accent, 0.07),
      line: { width: 0 },
      layer: 'below',
    })
  }

  const layout: Partial<Plotly.Layout> = {
    title: { text: style.title.trim() || 'UpSet Plot', font: { size: 17, color: pal.font }, x: 0.5 },
    xaxis: {
      range: [-0.6, nCols - 0.4],
      showticklabels: false,
      showgrid: false,
      zeroline: false,
      fixedrange: true,
      domain: [0, 1],
    },
    yaxis: {
      domain: [0.42, 1],
      range: [0, maxCount * 1.18],
      visible: false,
      fixedrange: true,
    },
    yaxis2: {
      domain: [0, 0.3],
      range: [-0.6, nSets - 0.4],
      tickvals: sets.map((_, i) => i),
      ticktext: sets.map((s) => `${escapeHtml(s.name)} (${s.items.length})`),
      tickfont: { size: 11, color: pal.font },
      showgrid: false,
      zeroline: false,
      fixedrange: true,
      automargin: true,
      side: 'left',
    },
    margin: { t: 56, r: 24, b: style.showLegend ? 72 : 36, l: 140 },
    plot_bgcolor: pal.plotBg,
    paper_bgcolor: pal.paperBg,
    font: { color: pal.font },
    showlegend: style.showLegend,
    legend: { orientation: 'h', y: -0.15, x: 0.5, xanchor: 'center', font: { size: 12, color: pal.font } },
    shapes,
    hovermode: 'closest',
    bargap: Math.min(0.9, Math.max(0, style.barGap)),
  }

  return { data: [barTrace, mutedTrace, ...setTraces], layout, config: figureConfig() }
}
