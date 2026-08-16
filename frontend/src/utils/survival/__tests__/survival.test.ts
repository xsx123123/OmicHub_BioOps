import { describe, expect, it } from 'vitest'
import { kaplanMeier, numberAtRisk } from '../kmEstimator'
import { chiSquareP, gammq, logRankTest } from '../logRankTest'
import { groupByExpression, joinExpressionFollowup, mapStatus, parseSurvivalRecords } from '../survivalData'
import { riskTableTimes } from '../survivalPlot'
import type { SurvivalRecord } from '../survivalTypes'
import { LUNG } from './lungData'

describe('kaplanMeier 手算小用例', () => {
  // times: 1,2,3,4,5,6 ; status: 1,1,0,1,0,1
  const records: SurvivalRecord[] = [
    { id: 'a', time: 1, status: 1 },
    { id: 'b', time: 2, status: 1 },
    { id: 'c', time: 3, status: 0 },
    { id: 'd', time: 4, status: 1 },
    { id: 'e', time: 5, status: 0 },
    { id: 'f', time: 6, status: 1 },
  ]
  const km = kaplanMeier(records)

  it('阶梯点含 t=0 S=1 起点', () => {
    expect(km.points[0]).toMatchObject({ time: 0, survival: 1, nRisk: 6 })
  })

  it('S(t) 逐步乘积与手算一致', () => {
    const expected: Array<[number, number, number]> = [
      // [time, nRisk, S(t)] 手算：5/6, 5/6*4/5, 4/6*2/3, 4/9*0
      [1, 6, 5 / 6],
      [2, 5, (5 / 6) * (4 / 5)],
      [4, 3, (5 / 6) * (4 / 5) * (2 / 3)],
      [6, 1, 0],
    ]
    expect(km.points.slice(1)).toHaveLength(expected.length)
    expected.forEach(([time, nRisk, survival], index) => {
      const point = km.points[index + 1]
      expect(point.time).toBe(time)
      expect(point.nRisk).toBe(nRisk)
      expect(Math.abs(point.survival - survival)).toBeLessThan(1e-10)
    })
  })

  it('删失点与中位生存期正确', () => {
    expect(km.censorMarks).toEqual([
      { time: 3, survival: (5 / 6) * (4 / 5) },
      { time: 5, survival: (5 / 6) * (4 / 5) * (2 / 3) },
    ])
    expect(km.medianSurvival).toBe(4) // S 首次 ≤ 0.5：S(4) = 4/9
    expect(km.events).toBe(4)
    expect(km.censored).toBe(2)
  })

  it('未达中位时返回 null', () => {
    const all = kaplanMeier([
      { id: 'a', time: 1, status: 0 },
      { id: 'b', time: 2, status: 0 },
      { id: 'c', time: 5, status: 1 }, // nRisk = 3，S = 2/3 > 0.5
      { id: 'd', time: 6, status: 0 },
      { id: 'e', time: 7, status: 0 },
    ])
    expect(all.medianSurvival).toBeNull()
  })

  it('numberAtRisk 计数正确', () => {
    expect(numberAtRisk(records, 0)).toBe(6)
    expect(numberAtRisk(records, 3)).toBe(4)
    expect(numberAtRisk(records, 6)).toBe(1)
    expect(numberAtRisk(records, 7)).toBe(0)
  })
})

describe('卡方 p 值（gammq 自实现）', () => {
  it('已知值', () => {
    expect(chiSquareP(3.841458820984, 1)).toBeCloseTo(0.05, 4)
    expect(chiSquareP(10.82756617, 1)).toBeCloseTo(0.001, 4)
    expect(chiSquareP(10.32674, 1)).toBeCloseTo(0.001311, 4)
    expect(chiSquareP(16.266, 2)).toBeCloseTo(0.0002935, 4)
    expect(chiSquareP(0, 1)).toBe(1)
    expect(gammq(0.5, 0)).toBe(1)
  })
})

describe('R survival::lung 数据集（228 例，按 sex 分组）', () => {
  const group1: SurvivalRecord[] = LUNG.filter((row) => row.sex === 1).map((row, index) => ({ id: `m${index}`, time: row.time, status: row.event }))
  const group2: SurvivalRecord[] = LUNG.filter((row) => row.sex === 2).map((row, index) => ({ id: `f${index}`, time: row.time, status: row.event }))
  const km1 = kaplanMeier(group1)
  const km2 = kaplanMeier(group2)
  const lr = logRankTest(['sex=1', 'sex=2'], [group1, group2])

  it('log-rank 卡方与 p 值吻合 R survdiff', () => {
    expect(lr.chi2).toBeCloseTo(10.32674, 3)
    expect(lr.df).toBe(1)
    expect(lr.p).toBeCloseTo(0.001311165, 3)
  })

  it('中位生存期 sex=1 → 270、sex=2 → 426', () => {
    expect(km1.medianSurvival).toBe(270)
    expect(km2.medianSurvival).toBe(426)
    expect(km1.n).toBe(138)
    expect(km1.events).toBe(112)
    expect(km2.n).toBe(90)
    expect(km2.events).toBe(53)
  })

  it('抽验 S(t) 点（以 R survfit 输出为准）', () => {
    const survivalAt = (km: typeof km1, time: number) => {
      let value = 1
      km.points.forEach((point) => { if (point.time <= time) value = point.survival })
      return value
    }
    // R: summary(survfit(Surv(time,status)~sex, lung), times=...)
    const expected1: Array<[number, number]> = [
      [100, 0.82608696], [200, 0.60730724], [270, 0.49369877], [300, 0.44108889],
      [400, 0.29767780], [500, 0.22321169], [600, 0.14508760], [800, 0.06696351], [1000, 0.03571387],
    ]
    const expected2: Array<[number, number]> = [
      [100, 0.92208835], [200, 0.79459349], [270, 0.70451505], [300, 0.67420259],
      [400, 0.50891426], [426, 0.48934064], [500, 0.41104614], [600, 0.34325958], [800, 0.08321444],
    ]
    expected1.forEach(([time, survival]) => expect(survivalAt(km1, time)).toBeCloseTo(survival, 3))
    expected2.forEach(([time, survival]) => expect(survivalAt(km2, time)).toBeCloseTo(survival, 3))
  })

  it('3 组拆分给出总体 p 与两两比较', () => {
    const third = Math.ceil(group1.length / 2)
    const g1a = group1.slice(0, third)
    const g1b = group1.slice(third)
    const multi = logRankTest(['m1', 'm2', 'f'], [g1a, g1b, group2])
    expect(multi.df).toBe(2)
    expect(multi.p).toBeGreaterThanOrEqual(0)
    expect(multi.p).toBeLessThanOrEqual(1)
    expect(multi.pairwise).toHaveLength(3)
    multi.pairwise?.forEach((pair) => {
      expect(pair.df).toBe(1)
      expect(pair.p).toBeGreaterThanOrEqual(0)
      expect(pair.p).toBeLessThanOrEqual(1)
    })
  })
})

describe('survivalData 输入解析与分组', () => {
  it('status 别名映射', () => {
    expect(mapStatus('1')).toBe(1)
    expect(mapStatus('Dead')).toBe(1)
    expect(mapStatus('DECEASED')).toBe(1)
    expect(mapStatus('event')).toBe(1)
    expect(mapStatus('0')).toBe(0)
    expect(mapStatus('Alive')).toBe(0)
    expect(mapStatus('LIVING')).toBe(0)
    expect(mapStatus('censored')).toBe(0)
    expect(mapStatus('???')).toBeNull()
  })

  it('合并表解析收集非法行错误', () => {
    const table = {
      headers: ['time', 'status'],
      rows: [
        { time: '10', status: '1' },
        { time: '-3', status: '0' },
        { time: 'abc', status: '1' },
        { time: '5', status: 'unknown' },
      ],
    }
    const outcome = parseSurvivalRecords(table, 'time', 'status')
    expect(outcome.records).toHaveLength(1)
    expect(outcome.errors).toHaveLength(3)
  })

  it('表达值 + 随访表内连接并报告未匹配', () => {
    const expression = {
      headers: ['sample', 'expression'],
      rows: [
        { sample: 'S1', expression: '8.1' },
        { sample: 'S2', expression: '3.2' },
        { sample: 'S3', expression: 'bad' },
        { sample: 'S4', expression: '5.5' },
      ],
    }
    const followup = {
      headers: ['sample', 'time', 'status'],
      rows: [
        { sample: 'S1', time: '10', status: '1' },
        { sample: 'S2', time: '20', status: '0' },
        { sample: 'S5', time: '30', status: '1' },
      ],
    }
    const outcome = joinExpressionFollowup(expression, followup, 'sample', 'expression')
    expect(outcome.report.matched).toBe(2)
    expect(outcome.report.unmatchedExpression).toEqual(['S4'])
    expect(outcome.report.unmatchedFollowup).toEqual(['S5'])
    expect(outcome.errors).toHaveLength(1)
    expect(outcome.records.find((record) => record.id === 'S1')).toMatchObject({ time: 10, status: 1, value: 8.1 })
  })

  it('中位数 / 自定义 / 最佳截点分组', () => {
    const records: SurvivalRecord[] = Array.from({ length: 20 }, (_, index) => ({
      id: `s${index}`,
      time: index < 10 ? 30 - index : 5 + index * 0.1,
      status: 1,
      value: index,
    }))
    const byMedian = groupByExpression(records, 'median', 0)
    expect(byMedian.cutoff).toBe(9.5)
    expect(byMedian.groups[0]).toHaveLength(10)
    expect(byMedian.groups[1]).toHaveLength(10)
    const byCustom = groupByExpression(records, 'custom', 4.5)
    expect(byCustom.groups[0]).toHaveLength(5)
    const byOptimal = groupByExpression(records, 'optimal', 0)
    expect(byOptimal.optimalP).toBeDefined()
    expect(byOptimal.optimalP!).toBeLessThan(0.01)
    expect(byOptimal.groups[0].length).toBeGreaterThanOrEqual(3)
    expect(byOptimal.groups[1].length).toBeGreaterThanOrEqual(3)
  })
})

describe('riskTableTimes', () => {
  it('返回 5–7 个含 0 的均匀时间点', () => {
    const times = riskTableTimes(1022)
    expect(times.length).toBeGreaterThanOrEqual(5)
    expect(times.length).toBeLessThanOrEqual(7)
    expect(times[0]).toBe(0)
    const step = times[1] - times[0]
    times.slice(1).forEach((time, index) => expect(time - times[index]).toBeCloseTo(step, 6))
  })
})
