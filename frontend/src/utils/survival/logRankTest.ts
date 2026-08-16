/**
 * Log-rank (Mantel–Cox) test for 2+ groups, plus a self-contained
 * chi-square survival function based on the regularized incomplete gamma
 * function Q(a, x) (Numerical Recipes gammq). No third-party statistics lib.
 */
import type { LogRankPair, LogRankResult, SurvivalRecord } from './survivalTypes'

/* ----------------------- chi-square p via gammq ----------------------- */

const FPMIN = 1e-300
const EPS = 1e-14
const ITMAX = 1000

function gammln(x: number): number {
  const cof = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
  let y = x
  let tmp = x + 5.5
  tmp -= (x + 0.5) * Math.log(tmp)
  let ser = 1.000000000190015
  for (let j = 0; j < 6; j += 1) {
    y += 1
    ser += cof[j] / y
  }
  return -tmp + Math.log(2.5066282746310005 * ser / x)
}

/** Regularized lower incomplete gamma P(a, x) by series expansion. */
function gser(a: number, x: number): number {
  const gln = gammln(a)
  if (x <= 0) return 0
  let ap = a
  let sum = 1 / a
  let del = sum
  for (let n = 1; n <= ITMAX; n += 1) {
    ap += 1
    del *= x / ap
    sum += del
    if (Math.abs(del) < Math.abs(sum) * EPS) break
  }
  return sum * Math.exp(-x + a * Math.log(x) - gln)
}

/** Regularized upper incomplete gamma Q(a, x) by continued fraction. */
function gcf(a: number, x: number): number {
  const gln = gammln(a)
  let b = x + 1 - a
  let c = 1 / FPMIN
  let d = 1 / b
  let h = d
  for (let i = 1; i <= ITMAX; i += 1) {
    const an = -i * (i - a)
    b += 2
    d = an * d + b
    if (Math.abs(d) < FPMIN) d = FPMIN
    c = b + an / c
    if (Math.abs(c) < FPMIN) c = FPMIN
    d = 1 / d
    const del = d * c
    h *= del
    if (Math.abs(del - 1) < EPS) break
  }
  return Math.exp(-x + a * Math.log(x) - gln) * h
}

/** Regularized upper incomplete gamma function Q(a, x). */
export function gammq(a: number, x: number): number {
  if (x < 0 || a <= 0) return Number.NaN
  if (x < a + 1) return 1 - gser(a, x)
  return gcf(a, x)
}

/** Chi-square survival function: P(Chi2_df >= x). */
export function chiSquareP(x: number, df: number): number {
  if (!(x >= 0) || df < 1) return Number.NaN
  return Math.min(1, Math.max(0, gammq(df / 2, x / 2)))
}

/* --------------------------- log-rank test ---------------------------- */

/**
 * O - E log-rank test across `groups` (each an array of SurvivalRecord).
 * For 2 groups returns df = 1; for k > 2 returns overall df = k - 1 plus
 * all pairwise two-group comparisons (df = 1 each).
 */
export function logRankTest(groupNames: string[], groups: SurvivalRecord[][]): LogRankResult {
  const k = groups.length
  if (k < 2) throw new Error('log-rank test needs at least 2 groups')

  const eventTimes = new Set<number>()
  groups.forEach((records) => records.forEach((record) => { if (record.status === 1) eventTimes.add(record.time) }))
  const times = [...eventTimes].sort((a, b) => a - b)

  const observed = new Array<number>(k).fill(0)
  const expected = new Array<number>(k).fill(0)
  const variance = Array.from({ length: k }, () => new Array<number>(k).fill(0))

  times.forEach((time) => {
    const nRisk = groups.map((records) => records.reduce((count, record) => count + (record.time >= time ? 1 : 0), 0))
    const dEvent = groups.map((records) => records.reduce((count, record) => count + (record.time === time && record.status === 1 ? 1 : 0), 0))
    const n = nRisk.reduce((sum, value) => sum + value, 0)
    const d = dEvent.reduce((sum, value) => sum + value, 0)
    if (n < 2 || d === 0) return
    const factor = (d * (n - d)) / (n * n * (n - 1))
    for (let i = 0; i < k; i += 1) {
      observed[i] += dEvent[i]
      expected[i] += (d * nRisk[i]) / n
      for (let j = 0; j < k; j += 1) {
        if (i === j) variance[i][j] += factor * nRisk[i] * (n - nRisk[i])
        else variance[i][j] -= factor * nRisk[i] * nRisk[j]
      }
    }
  })

  const chi2 = quadraticChi2(observed, expected, variance)
  const df = k - 1
  const result: LogRankResult = { chi2, df, p: chiSquareP(chi2, df) }
  if (k > 2) {
    const pairwise: LogRankPair[] = []
    for (let i = 0; i < k; i += 1) {
      for (let j = i + 1; j < k; j += 1) {
        const pair = logRankTest([groupNames[i], groupNames[j]], [groups[i], groups[j]])
        pairwise.push({ groupA: groupNames[i], groupB: groupNames[j], chi2: pair.chi2, df: 1, p: pair.p })
      }
    }
    result.pairwise = pairwise
  }
  return result
}

/**
 * chi2 = (O - E)' V^- (O - E) over the first k-1 groups (the k-th is
 * linearly dependent). For k = 2 this reduces to (O1 - E1)^2 / V11.
 */
function quadraticChi2(observed: number[], expected: number[], variance: number[][]): number {
  const size = observed.length - 1
  if (size < 1) return 0
  const diff = observed.slice(0, size).map((value, index) => value - expected[index])
  const matrix = variance.slice(0, size).map((row) => row.slice(0, size))
  const inverse = invertMatrix(matrix)
  let chi2 = 0
  for (let i = 0; i < size; i += 1) {
    for (let j = 0; j < size; j += 1) chi2 += diff[i] * inverse[i][j] * diff[j]
  }
  return Math.max(0, chi2)
}

/** Gauss–Jordan inverse with partial pivoting for small symmetric matrices. */
function invertMatrix(matrix: number[][]): number[][] {
  const n = matrix.length
  const augmented = matrix.map((row, i) => [...row, ...Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))])
  for (let pivot = 0; pivot < n; pivot += 1) {
    let best = pivot
    for (let row = pivot + 1; row < n; row += 1) {
      if (Math.abs(augmented[row][pivot]) > Math.abs(augmented[best][pivot])) best = row
    }
    ;[augmented[pivot], augmented[best]] = [augmented[best], augmented[pivot]]
    const divisor = augmented[pivot][pivot] || FPMIN
    for (let column = 0; column < 2 * n; column += 1) augmented[pivot][column] /= divisor
    for (let row = 0; row < n; row += 1) {
      if (row === pivot) continue
      const factor = augmented[row][pivot]
      for (let column = 0; column < 2 * n; column += 1) augmented[row][column] -= factor * augmented[pivot][column]
    }
  }
  return augmented.map((row) => row.slice(n))
}
