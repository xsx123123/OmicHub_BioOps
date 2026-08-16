import { describe, expect, it } from 'vitest'
import {
  buildVolcanoFigure,
  classifyGene,
  DEG_COLORS,
  formatLog2Fc,
  formatScientific,
  safeMinusLog10P,
} from '../degProcessor'
import type { DegGeneRow } from '@/types/deg'

const gene = (over: Partial<DegGeneRow> = {}): DegGeneRow => ({
  ensembl: 'ENSG00000001',
  symbol: 'Gene1',
  log2_fc: 0,
  pvalue: 1,
  padj: 1,
  base_mean: null,
  log_cpm: null,
  ...over,
})

describe('显著性分类（与 R 脚本同口径：raw pvalue + |log2FC|）', () => {
  it('p < 阈值且 log2FC > 阈值 → 上调', () => {
    expect(classifyGene(gene({ log2_fc: 2, pvalue: 0.001 }), 0.05, 1)).toBe('Up-regulated')
  })

  it('p < 阈值且 log2FC < -阈值 → 下调', () => {
    expect(classifyGene(gene({ log2_fc: -1.5, pvalue: 0.01 }), 0.05, 1)).toBe('Down-regulated')
  })

  it('p 达标但 |log2FC| 不足 → 非显著', () => {
    expect(classifyGene(gene({ log2_fc: 0.5, pvalue: 0.001 }), 0.05, 1)).toBe('Non-significant')
  })

  it('边界值不触发（严格小于）', () => {
    expect(classifyGene(gene({ log2_fc: 1, pvalue: 0.05 }), 0.05, 1)).toBe('Non-significant')
  })
})

describe('-log10(p) 零值安全处理', () => {
  it('p=0 夹到最小正数而不是 Infinity', () => {
    expect(Number.isFinite(safeMinusLog10P(0))).toBe(true)
  })

  it('常规 p 值换算正确', () => {
    expect(safeMinusLog10P(0.01)).toBeCloseTo(2, 6)
  })
})

describe('数值格式化', () => {
  it('极小 p 值用科学计数法', () => {
    expect(formatScientific(1e-8)).toBe('1.000e-8')
  })

  it('常规值保留三位小数', () => {
    expect(formatScientific(0.12345)).toBe('0.123')
  })

  it('null → NA', () => {
    expect(formatScientific(null)).toBe('NA')
    expect(formatLog2Fc(null)).toBe('NA')
  })

  it('log2FC 保留两位', () => {
    expect(formatLog2Fc(-2.567)).toBe('-2.57')
  })
})

describe('火山图 Plotly 配置', () => {
  const rows = [
    gene({ ensembl: 'E1', log2_fc: 2.5, pvalue: 1e-4 }),
    gene({ ensembl: 'E2', log2_fc: -2.0, pvalue: 1e-3 }),
    gene({ ensembl: 'E3', log2_fc: 0.2, pvalue: 0.8 }),
  ]

  it('按 NS / Down / Up 顺序产出三个 trace 且配色与 R 脚本一致', () => {
    const fig = buildVolcanoFigure(rows, {
      contrastName: 'Treat_vs_WT',
      pvalCutoff: 0.05,
      lfcCutoff: 1,
      isDark: false,
    })
    expect(fig.data).toHaveLength(3)
    const [ns, down, up] = fig.data as Array<{ name: string; marker: { color: string }; x: number[] }>
    expect(ns.name).toBe('Non-significant')
    expect(down.name).toBe('Down-regulated')
    expect(up.name).toBe('Up-regulated')
    expect(ns.marker.color).toBe(DEG_COLORS.ns)
    expect(down.marker.color).toBe(DEG_COLORS.down)
    expect(up.marker.color).toBe(DEG_COLORS.up)
    expect(up.x).toEqual([2.5])
    expect(down.x).toEqual([-2.0])
    expect(ns.x).toEqual([0.2])
  })

  it('包含两条 LFC 竖线与一条 p 值横线', () => {
    const fig = buildVolcanoFigure(rows, {
      contrastName: 'A_vs_B',
      pvalCutoff: 0.05,
      lfcCutoff: 1,
      isDark: true,
    })
    const layout = fig.layout as { shapes: Array<{ x0?: number; y0?: number }>; title: { text: string } }
    expect(layout.shapes).toHaveLength(3)
    expect(layout.shapes[0].x0).toBe(1)   // +LFC 竖线
    expect(layout.shapes[1].x0).toBe(-1)  // -LFC 竖线
    expect(layout.shapes[2].y0).toBeCloseTo(safeMinusLog10P(0.05), 6)  // p 值横线
    expect(layout.title.text).toContain('A_vs_B')
  })

  it('空数据不抛异常', () => {
    const fig = buildVolcanoFigure([], {
      contrastName: 'Empty',
      pvalCutoff: 0.05,
      lfcCutoff: 1,
      isDark: false,
    })
    expect((fig.data as unknown[]).length).toBe(3)
  })
})
