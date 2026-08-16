/**
 * Types for the pure front-end survival analysis module (KM curves + log-rank).
 * No Vue / network dependencies: everything here is computed in the browser.
 */

/** One subject. status: 1 = event occurred, 0 = right-censored. */
export interface SurvivalRecord {
  id: string
  time: number
  status: 0 | 1
  group?: string
  /** Optional continuous value used for expression-based grouping. */
  value?: number
}

/** One Kaplan–Meier step point at an event time. */
export interface KMPoint {
  time: number
  survival: number
  nRisk: number
  nEvent: number
  nCensor: number
  lower95: number
  upper95: number
}

export interface KMResult {
  /** Starts with { time: 0, survival: 1 } and steps at every event time. */
  points: KMPoint[]
  /** First time where S(t) <= 0.5; null when not reached. */
  medianSurvival: number | null
  n: number
  events: number
  censored: number
  /** Last observed time (event or censor), used to extend the curve tail. */
  maxTime: number
  /** Censor tick positions: time + survival level at that time. */
  censorMarks: Array<{ time: number; survival: number }>
}

export interface LogRankPair {
  groupA: string
  groupB: string
  chi2: number
  df: number
  p: number
}

export interface LogRankResult {
  chi2: number
  df: number
  p: number
  /** Only present when more than 2 groups: df = 1 pairwise comparisons. */
  pairwise?: LogRankPair[]
}

export interface SurvivalGroupResult {
  name: string
  records: SurvivalRecord[]
  km: KMResult
}

export type SurvivalGroupStrategy = 'median' | 'optimal' | 'custom'

export interface ExpressionJoinReport {
  matched: number
  unmatchedExpression: string[]
  unmatchedFollowup: string[]
}
