/**
 * Input parsing for survival analysis: combined-table mode and
 * expression + follow-up table mode, plus expression grouping strategies.
 * Pure functions, no network access.
 */
import { logRankTest } from './logRankTest'
import type { ExpressionJoinReport, SurvivalGroupStrategy, SurvivalRecord } from './survivalTypes'

/** Structural view of a parsed delimited table (matches ParsedTable). */
export interface TableLike {
  headers: string[]
  rows: Record<string, string>[]
}

export interface SurvivalParseOutcome {
  records: SurvivalRecord[]
  errors: string[]
  warnings: string[]
}

const TIME_ALIASES = ['time', 'os.time', 'os_time', 'survival_time', 'survtime', 'followup', 'follow_up', 'days', 'months', 'duration', 'time_to_event', 'os']
const STATUS_ALIASES = ['status', 'event', 'os.status', 'os_status', 'censor', 'censoring', 'vital_status', 'survival_status', 'outcome', 'dead', 'deceased', 'alive']
const ID_ALIASES = ['sample', 'sample_id', 'sampleid', 'id', 'patient', 'patient_id', 'subject', 'subject_id', 'case', 'case_id', 'barcode']

/** Exact, then substring, header matching against known aliases. */
export function detectColumn(headers: string[], aliases: string[]): string {
  const normalized = headers.map((header) => header.trim().toLowerCase())
  const exact = normalized.findIndex((header) => aliases.includes(header))
  if (exact >= 0) return headers[exact]
  const partial = normalized.findIndex((header) => aliases.some((alias) => header.includes(alias)))
  return partial >= 0 ? headers[partial] : ''
}

const STATUS_EVENT_TOKENS = new Set(['1', 'dead', 'death', 'event', 'deceased', 'yes', 'true', 'relapse', 'progressed'])
const STATUS_CENSOR_TOKENS = new Set(['0', 'alive', 'living', 'censored', 'censor', 'no', 'false', 'none', 'disease-free', 'diseasefree'])

/** Map a raw status cell to 1 (event) / 0 (censored); null when unmappable. */
export function mapStatus(raw: string): 0 | 1 | null {
  const token = raw.trim().toLowerCase()
  if (STATUS_EVENT_TOKENS.has(token)) return 1
  if (STATUS_CENSOR_TOKENS.has(token)) return 0
  return null
}

const numberPattern = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i

function parseTime(raw: string): number | null {
  const token = raw.trim()
  if (!token || !numberPattern.test(token)) return null
  const value = Number(token)
  if (!Number.isFinite(value) || value < 0) return null
  return value
}

/** Combined-table mode: one row per subject with time / status (+ optional group). */
export function parseSurvivalRecords(table: TableLike, timeColumn: string, statusColumn: string, groupColumn = ''): SurvivalParseOutcome {
  const records: SurvivalRecord[] = []
  const errors: string[] = []
  const warnings: string[] = []
  if (!timeColumn) errors.push('未识别到生存时间列（time / OS.time / days 等），请手动选择。')
  if (!statusColumn) errors.push('未识别到结局状态列（status / event / vital_status 等），请手动选择。')
  if (!timeColumn || !statusColumn) return { records, errors, warnings }
  table.rows.forEach((row, index) => {
    const time = parseTime(row[timeColumn] ?? '')
    const status = mapStatus(row[statusColumn] ?? '')
    if (time === null) { errors.push(`第 ${index + 2} 行生存时间 “${row[timeColumn] ?? ''}” 非数值或为负数。`); return }
    if (status === null) { errors.push(`第 ${index + 2} 行结局状态 “${row[statusColumn] ?? ''}” 无法映射为事件/删失。`); return }
    records.push({ id: `row_${index + 1}`, time, status, group: groupColumn ? row[groupColumn]?.trim() || undefined : undefined })
  })
  return { records, errors, warnings }
}

export interface ExpressionJoinOutcome extends SurvivalParseOutcome {
  report: ExpressionJoinReport
  timeColumn: string
  statusColumn: string
}

/**
 * Expression + follow-up mode: inner join on sample ID. The expression table
 * supplies `value`; the follow-up table supplies time / status (auto-detected).
 */
export function joinExpressionFollowup(
  expressionTable: TableLike,
  followupTable: TableLike,
  expressionIdColumn: string,
  expressionValueColumn: string,
): ExpressionJoinOutcome {
  const errors: string[] = []
  const warnings: string[] = []
  const report: ExpressionJoinReport = { matched: 0, unmatchedExpression: [], unmatchedFollowup: [] }
  const empty: ExpressionJoinOutcome = { records: [], errors, warnings, report, timeColumn: '', statusColumn: '' }

  if (!expressionIdColumn) errors.push('请选择表达值表的样本 ID 列。')
  if (!expressionValueColumn) errors.push('请选择表达值列。')
  if (!followupTable.headers.length) errors.push('请上传随访表（CSV / TSV）。')
  if (errors.length) return empty

  const followupIdColumn = detectColumn(followupTable.headers, ID_ALIASES) || followupTable.headers[0]
  const timeColumn = detectColumn(followupTable.headers, TIME_ALIASES)
  const statusColumn = detectColumn(followupTable.headers, STATUS_ALIASES)
  if (!timeColumn) errors.push('随访表中未识别到生存时间列（time / OS.time / days 等）。')
  if (!statusColumn) errors.push('随访表中未识别到结局状态列（status / event / vital_status 等）。')
  if (errors.length) return { ...empty, timeColumn, statusColumn }

  const followupById = new Map<string, { time: number; status: 0 | 1 }>()
  followupTable.rows.forEach((row, index) => {
    const id = row[followupIdColumn]?.trim()
    if (!id) return
    const time = parseTime(row[timeColumn] ?? '')
    const status = mapStatus(row[statusColumn] ?? '')
    if (time === null) { errors.push(`随访表第 ${index + 2} 行生存时间 “${row[timeColumn] ?? ''}” 非数值或为负数。`); return }
    if (status === null) { errors.push(`随访表第 ${index + 2} 行结局状态 “${row[statusColumn] ?? ''}” 无法映射为事件/删失。`); return }
    followupById.set(id, { time, status })
  })

  const records: SurvivalRecord[] = []
  expressionTable.rows.forEach((row, index) => {
    const id = row[expressionIdColumn]?.trim()
    if (!id) return
    const rawValue = (row[expressionValueColumn] ?? '').trim()
    const value = numberPattern.test(rawValue) ? Number(rawValue) : Number.NaN
    if (!Number.isFinite(value)) { errors.push(`表达值表第 ${index + 2} 行表达值 “${rawValue}” 非数值。`); return }
    const followup = followupById.get(id)
    if (!followup) { report.unmatchedExpression.push(id); return }
    records.push({ id, time: followup.time, status: followup.status, value })
  })
  report.matched = records.length
  const expressionIds = new Set(expressionTable.rows.map((row) => row[expressionIdColumn]?.trim()).filter(Boolean))
  followupById.forEach((_, id) => { if (!expressionIds.has(id)) report.unmatchedFollowup.push(id) })
  if (report.unmatchedExpression.length) warnings.push(`${report.unmatchedExpression.length} 个表达值样本未匹配到随访记录（如 ${report.unmatchedExpression.slice(0, 3).join('、')}${report.unmatchedExpression.length > 3 ? ' 等' : ''}）。`)
  if (report.unmatchedFollowup.length) warnings.push(`${report.unmatchedFollowup.length} 个随访样本无表达值，未纳入分析。`)
  return { records, errors, warnings, report, timeColumn, statusColumn }
}

/* ------------------------- grouping strategies ------------------------- */

export interface ExpressionGrouping {
  groups: SurvivalRecord[][]
  names: string[]
  cutoff: number
  /** Only for the optimal-cutoff strategy: the best (minimum) log-rank p. */
  optimalP?: number
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function quantile(sorted: number[], q: number): number {
  const position = (sorted.length - 1) * q
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

function splitByCutoff(records: SurvivalRecord[], cutoff: number): SurvivalRecord[][] {
  const low = records.filter((record) => (record.value ?? 0) <= cutoff).map((record) => ({ ...record, group: 'Low expression' }))
  const high = records.filter((record) => (record.value ?? 0) > cutoff).map((record) => ({ ...record, group: 'High expression' }))
  return [low, high]
}

/**
 * Group expression-joined records by median split, an optimal cutoff
 * (20%–80% quantile candidates, minimum log-rank p), or a custom cutoff.
 */
export function groupByExpression(records: SurvivalRecord[], strategy: SurvivalGroupStrategy, customCutoff: number): ExpressionGrouping {
  const values = records.map((record) => record.value ?? 0)
  const sorted = [...values].sort((a, b) => a - b)
  if (strategy === 'median') {
    const cutoff = median(values)
    return { groups: splitByCutoff(records, cutoff), names: ['Low expression', 'High expression'], cutoff }
  }
  if (strategy === 'custom') {
    const cutoff = Number.isFinite(customCutoff) ? customCutoff : median(values)
    return { groups: splitByCutoff(records, cutoff), names: ['Low expression', 'High expression'], cutoff }
  }
  // optimal cutoff: scan 20%–80% quantile candidates, keep the minimum-p split
  let bestCutoff = median(values)
  let bestP = Number.POSITIVE_INFINITY
  const candidates = new Set<number>()
  for (let q = 20; q <= 80; q += 1) candidates.add(quantile(sorted, q / 100))
  candidates.forEach((cutoff) => {
    const [low, high] = splitByCutoff(records, cutoff)
    if (low.length < 3 || high.length < 3) return
    if (!low.some((record) => record.status === 1) || !high.some((record) => record.status === 1)) return
    try {
      const { p } = logRankTest(['Low expression', 'High expression'], [low, high])
      if (Number.isFinite(p) && p < bestP) { bestP = p; bestCutoff = cutoff }
    } catch { /* degenerate split, skip candidate */ }
  })
  return {
    groups: splitByCutoff(records, bestCutoff),
    names: ['Low expression', 'High expression'],
    cutoff: bestCutoff,
    optimalP: Number.isFinite(bestP) ? bestP : undefined,
  }
}
