/**
 * Kaplan–Meier product-limit estimator with Greenwood variance and
 * log(-log) transformed 95% confidence intervals. Pure functions.
 */
import type { KMPoint, KMResult, SurvivalRecord } from './survivalTypes'

/**
 * Estimate the KM curve for one group of records.
 * Points start at { time: 0, survival: 1 } and step at every distinct event time.
 */
export function kaplanMeier(records: SurvivalRecord[]): KMResult {
  const sorted = [...records].sort((a, b) => a.time - b.time)
  const n = sorted.length
  const events = sorted.filter((record) => record.status === 1).length
  const maxTime = n ? sorted[n - 1].time : 0

  const points: KMPoint[] = [{ time: 0, survival: 1, nRisk: n, nEvent: 0, nCensor: 0, lower95: 1, upper95: 1 }]
  const censorMarks: Array<{ time: number; survival: number }> = []

  let survival = 1
  let greenwoodSum = 0 // sum of d / (n_i * (n_i - d)), Greenwood variance accumulator
  let index = 0
  while (index < n) {
    const time = sorted[index].time
    let nEvent = 0
    let nCensor = 0
    while (index < n && sorted[index].time === time) {
      if (sorted[index].status === 1) nEvent += 1
      else nCensor += 1
      index += 1
    }
    const nRisk = n - index + nEvent + nCensor // at risk just before this time
    if (nEvent > 0) {
      survival *= (nRisk - nEvent) / nRisk
      if (nRisk - nEvent > 0) greenwoodSum += nEvent / (nRisk * (nRisk - nEvent))
      const [lower95, upper95] = confidenceInterval(survival, greenwoodSum)
      points.push({ time, survival, nRisk, nEvent, nCensor, lower95, upper95 })
    }
    if (nCensor > 0) {
      for (let mark = 0; mark < nCensor; mark += 1) censorMarks.push({ time, survival })
      // keep the last event point's censor tally honest
      if (points.length > 1) points[points.length - 1].nCensor += nCensor
    }
  }

  const medianPoint = points.find((point) => point.survival <= 0.5)
  return {
    points,
    medianSurvival: medianPoint ? medianPoint.time : null,
    n,
    events,
    censored: n - events,
    maxTime,
    censorMarks,
  }
}

/** 95% CI on S(t) via Greenwood variance + log(-log) transform, clamped to [0, 1]. */
function confidenceInterval(survival: number, greenwoodSum: number): [number, number] {
  if (survival <= 0) return [0, 0]
  if (survival >= 1) return [1, 1]
  // var(log(-log S)) = greenwoodSum / (log S)^2
  const se = Math.sqrt(greenwoodSum) / Math.abs(Math.log(survival))
  const factor = Math.exp(1.959963984540054 * se)
  const lower = Math.pow(survival, factor)
  const upper = Math.pow(survival, 1 / factor)
  return [Math.max(0, Math.min(1, lower)), Math.max(0, Math.min(1, upper))]
}

/** Number of subjects at risk at time t (time >= t still under observation). */
export function numberAtRisk(records: SurvivalRecord[], time: number): number {
  return records.reduce((count, record) => count + (record.time >= time ? 1 : 0), 0)
}
