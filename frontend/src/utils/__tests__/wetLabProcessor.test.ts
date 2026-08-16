import { describe, expect, it } from 'vitest'
import {
  analyzePrimer, computeBeads, computeCopyNumber, computeLigation,
  computeMasterMix, computePooling, generateBufferRecipe, genSampleMasterMix,
  genSamplePooling, rcfToRpm, reverseComplementSeq, rpmToRcf,
} from '../wetLabProcessor'

describe('PCR Master Mix 批量配制', () => {
  it('按反应数与损耗余量计算预混液总量', () => {
    const r = computeMasterMix(genSampleMasterMix())
    expect(r.valid).toBe(true)
    // 预混液每孔 = 10 + 0.8 + 0.8 + 7.4 = 19 µL
    expect(r.mixPerReaction).toBeCloseTo(19, 6)
    // 预混液总量 = 19 × 96 × 1.1 = 2006.4 µL
    expect(r.mixTotal).toBeCloseTo(2006.4, 4)
    // 单反应体系总体积含模板 = 20 µL
    expect(r.totalReactionVolume).toBeCloseTo(20, 6)
    // 模板行不加损耗：1 × 96 = 96
    const template = r.rows.find((row) => row.isTemplate)
    expect(template?.total).toBeCloseTo(96, 6)
  })

  it('无有效组分时报错', () => {
    const r = computeMasterMix({ components: [{ name: '', perReaction: 0, isTemplate: false }], reactionCount: 10, extraPercent: 10 })
    expect(r.valid).toBe(false)
  })
})

describe('连接反应摩尔比', () => {
  it('按摩尔比计算插入片段用量与体积', () => {
    const r = computeLigation({ vectorLength: 5000, vectorMass: 100, insertLength: 1000, molarRatio: 3, insertConc: 50 })
    expect(r.valid).toBe(true)
    expect(r.insertMass).toBeCloseTo(60, 6) // 100 × (1000/5000) × 3
    expect(r.insertVolume).toBeCloseTo(1.2, 6)
  })

  it('未提供浓度时体积为 null', () => {
    const r = computeLigation({ vectorLength: 5000, vectorMass: 100, insertLength: 1000, molarRatio: 3, insertConc: null })
    expect(r.insertVolume).toBeNull()
  })

  it('非法输入报错', () => {
    expect(computeLigation({ vectorLength: 0, vectorMass: 100, insertLength: 1000, molarRatio: 3, insertConc: null }).valid).toBe(false)
  })
})

describe('核酸绝对拷贝数', () => {
  it('dsDNA 拷贝数与公式一致', () => {
    const r = computeCopyNumber(50, 3000, 'dsDNA')
    expect(r.valid).toBe(true)
    const expected = (50 * 6.022e23) / (3000 * 1e9 * 660)
    expect(Math.abs(r.copiesPerUl - expected) / expected).toBeLessThan(1e-9)
    expect(r.mw).toBe(3000 * 660)
  })

  it('RNA 使用 340 g/mol/nt', () => {
    const r = computeCopyNumber(10, 1000, 'ssRNA')
    expect(r.mw).toBe(1000 * 340)
  })

  it('非法输入报错', () => {
    expect(computeCopyNumber(0, 1000, 'dsDNA').valid).toBe(false)
  })
})

describe('NGS 文库等摩尔 Pooling', () => {
  it('各文库等摩尔贡献且补液体积非负', () => {
    const input = genSamplePooling()
    const r = computePooling(input)
    expect(r.valid).toBe(true)
    expect(r.rows).toHaveLength(4)
    // 每个文库贡献的 fmol = 摩尔浓度(nM) × 吸取体积(µL) 应相等且等于 总fmol/N
    const totalFmol = input.targetConc * input.targetVolume
    const perLib = totalFmol / 4
    for (const row of r.rows) {
      expect(row.molarConc * row.volume).toBeCloseTo(perLib, 6)
    }
    expect(r.diluentVolume).toBeGreaterThanOrEqual(0)
  })

  it('无有效文库时报错', () => {
    expect(computePooling({ libraries: [], targetConc: 4, targetVolume: 20 }).valid).toBe(false)
  })
})

describe('磁珠纯化与选段', () => {
  it('单向纯化按比例加磁珠', () => {
    const r = computeBeads({ mode: 'single', sampleVolume: 50, ratio1: 0.8, ratio2: 0.8 })
    expect(r.valid).toBe(true)
    expect(r.beads1).toBeCloseTo(40, 6)
    expect(r.beads2).toBeNull()
  })

  it('双向选段分步计算磁珠与上清', () => {
    const r = computeBeads({ mode: 'double', sampleVolume: 50, ratio1: 0.6, ratio2: 0.8 })
    expect(r.valid).toBe(true)
    expect(r.beads1).toBeCloseTo(30, 6)
    expect(r.supernatant).toBeCloseTo(80, 6)
    expect(r.beads2).toBeCloseTo(10, 6)
  })

  it('目标总比例不大于第一步时报错', () => {
    expect(computeBeads({ mode: 'double', sampleVolume: 50, ratio1: 0.8, ratio2: 0.6 }).valid).toBe(false)
  })
})

describe('引物 Tm / 反向互补 / GC%', () => {
  it('统计长度、GC、反向互补与 Wallace Tm', () => {
    const r = analyzePrimer('ATCGGCTA')
    expect(r.valid).toBe(true)
    expect(r.length).toBe(8)
    expect(r.gcPercent).toBeCloseTo(50, 6)
    expect(r.reverseComplement).toBe('TAGCCGAT')
    expect(r.tmWallace).toBe(2 * 4 + 4 * 4) // 24
  })

  it('自动过滤空格与数字', () => {
    const r = analyzePrimer('5-ATCG GCTA-3')
    expect(r.length).toBe(8)
  })

  it('reverseComplementSeq 处理简并碱基', () => {
    expect(reverseComplementSeq('ATGCN')).toBe('NGCAT')
  })

  it('空序列无效', () => {
    expect(analyzePrimer('').valid).toBe(false)
  })
})

describe('RPM ↔ RCF', () => {
  it('RPM → RCF 与公式一致', () => {
    expect(rpmToRcf(12000, 10)).toBeCloseTo(1.118e-5 * 10 * 12000 * 12000, 4)
  })

  it('双向换算可往返', () => {
    const rcf = rpmToRcf(8000, 9.5)
    expect(rcfToRpm(rcf, 9.5)).toBeCloseTo(8000, 4)
  })
})

describe('缓冲液配方生成器', () => {
  it('按目标体积等比缩放 50× TAE', () => {
    const r = generateBufferRecipe('tae50x', 500)
    expect(r.valid).toBe(true)
    const tris = r.rows.find((row) => row.name === 'Tris 碱')
    expect(tris?.amount).toBeCloseTo(121, 6) // 242 × 0.5
    const edta = r.rows.find((row) => row.name.includes('EDTA'))
    expect(edta?.amount).toBeCloseTo(50, 6)
  })

  it('未知配方或非法体积报错', () => {
    expect(generateBufferRecipe('nope', 500).valid).toBe(false)
    expect(generateBufferRecipe('tae50x', 0).valid).toBe(false)
  })
})
