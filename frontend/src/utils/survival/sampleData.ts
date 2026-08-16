/**
 * Built-in example data for the survival (KM) chart: a deterministic simulated
 * cohort of 80 patients with censoring. The expression value genuinely drives
 * the hazard, so both median-split and optimal-cutoff grouping yield a small
 * log-rank p. Three CSV views over the same cohort are exported:
 * combined table / expression table / follow-up table.
 */

interface SampleRow {
  id: string
  expression: number
  time: number
  status: 0 | 1
  group: 'Low' | 'High'
}

/** Deterministic LCG so the example is stable across sessions. */
function lcg(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 0xffffffff
  }
}

function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-12)
  const v = Math.max(rand(), 1e-12)
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

function simulateCohort(): SampleRow[] {
  const rand = lcg(20260720)
  const expression = Array.from({ length: 80 }, () => 7 + 1.6 * gaussian(rand))
  const sorted = [...expression].sort((a, b) => a - b)
  const center = (sorted[39] + sorted[40]) / 2
  return expression.map((value, index) => {
    const hazard = 0.055 * Math.exp(1.05 * (value - center))
    const eventTime = -Math.log(Math.max(rand(), 1e-12)) / hazard
    const censorTime = 14 + 42 * rand()
    const time = Math.min(eventTime, censorTime)
    return {
      id: `S${String(index + 1).padStart(3, '0')}`,
      expression: Number(value.toFixed(3)),
      time: Number(time.toFixed(1)),
      status: eventTime <= censorTime ? 1 as const : 0 as const,
      group: value > center ? 'High' as const : 'Low' as const,
    }
  })
}

const cohort = simulateCohort()

function toCsv(headers: string[], rows: Array<Array<string | number>>): string {
  return [headers.join(','), ...rows.map((row) => row.join(','))].join('\n') + '\n'
}

/** 合并表：sample,group,time_months,status（1=事件，0=删失）。 */
export const SAMPLE_SURVIVAL_COMBINED_CSV = toCsv(
  ['sample', 'group', 'time_months', 'status'],
  cohort.map((row) => [row.id, row.group, row.time, row.status]),
)

/** 表达值表：sample,expression（与随访表同一批样本）。 */
export const SAMPLE_EXPRESSION_CSV = toCsv(
  ['sample', 'expression'],
  cohort.map((row) => [row.id, row.expression]),
)

/** 随访表：sample,time_months,status。 */
export const SAMPLE_FOLLOWUP_CSV = toCsv(
  ['sample', 'time_months', 'status'],
  cohort.map((row) => [row.id, row.time, row.status]),
)
