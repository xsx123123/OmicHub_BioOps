/**
 * ID 转换器核心逻辑（纯函数，无 Vue 依赖）。
 *
 * 粘贴文本解析 → ID 类型自动识别 → 映射结果行构建 → 集合运算 → 导出文本。
 * 实际的 ID 查表由 geneIdMap.ts 提供。
 */

import type { GeneMapEntry, IdType, LookupResult } from './geneIdMap'

export type ConvertStatus = 'success' | 'unmatched' | 'multi'

export interface ConvertRow {
  input: string
  symbols: string[]
  ensembls: string[]
  entrezs: string[]
  uniprots: string[]
  status: ConvertStatus
}

/** 按换行/逗号/空格/分号/Tab 任意混合分隔符解析 ID 列表。 */
export function parseIdList(text: string): { ids: string[]; uniqueIds: string[] } {
  const ids = text
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  return { ids, uniqueIds: [...new Set(ids)] }
}

/**
 * 单条 ID 类型识别：
 * - ENS 前缀（ENSG / ENST / ENSMUSG 等）→ Ensembl
 * - 纯数字 → Entrez
 * - 其余 → Symbol
 */
export function detectIdType(id: string): IdType {
  if (/^ENS[A-Z]*\d+/i.test(id)) return 'ensembl'
  if (/^\d+$/.test(id)) return 'entrez'
  return 'symbol'
}

/** 列表级类型识别：取各条目识别结果中的多数派，并返回各类型计数。 */
export function detectListType(ids: string[]): { type: IdType; counts: Record<IdType, number> } {
  const counts: Record<IdType, number> = { symbol: 0, ensembl: 0, entrez: 0, uniprot: 0 }
  for (const id of ids) counts[detectIdType(id)] += 1
  let best: IdType = 'symbol'
  let bestCount = -1
  for (const t of ['symbol', 'ensembl', 'entrez', 'uniprot'] as IdType[]) {
    if (counts[t] > bestCount) {
      best = t
      bestCount = counts[t]
    }
  }
  return { type: best, counts }
}

/** 由查询结果构建表格行；一对多时各字段为多值（表格内换行展示）。 */
export function buildConvertRows(results: LookupResult[]): ConvertRow[] {
  return results.map(({ id, matches }) => ({
    input: id,
    symbols: uniq(matches.map((m) => m.symbol)),
    ensembls: uniq(matches.map((m) => m.ensembl)),
    entrezs: uniq(matches.map((m) => m.entrez)),
    uniprots: uniq(matches.map((m) => m.uniprot)),
    status: matches.length === 0 ? 'unmatched' : matches.length > 1 ? 'multi' : 'success',
  }))
}

function uniq(arr: string[]): string[] {
  return [...new Set(arr)]
}

export const STATUS_LABEL: Record<ConvertStatus, string> = {
  success: '成功',
  unmatched: '未匹配',
  multi: '一对多',
}

export type SetOp = 'intersect' | 'union' | 'aMinusB' | 'bMinusA'

/** 双列表集合运算；大小写不敏感比较，输出保留 A 列表中的原始写法并去重。 */
export function setOperate(listA: string[], listB: string[], op: SetOp): string[] {
  const key = (s: string) => s.toUpperCase()
  const bKeys = new Set(listB.map(key))
  const aKeys = new Set(listA.map(key))
  switch (op) {
    case 'intersect':
      return [...new Set(listA.filter((a) => bKeys.has(key(a))))]
    case 'union': {
      const seen = new Set<string>()
      const out: string[] = []
      for (const item of [...listA, ...listB]) {
        if (!seen.has(key(item))) {
          seen.add(key(item))
          out.push(item)
        }
      }
      return out
    }
    case 'aMinusB':
      return [...new Set(listA.filter((a) => !bKeys.has(key(a))))]
    case 'bMinusA':
      return [...new Set(listB.filter((b) => !aKeys.has(key(b))))]
  }
}

export const SET_OP_LABEL: Record<SetOp, string> = {
  intersect: '交集 A∩B',
  union: '并集 A∪B',
  aMinusB: '差集 A−B',
  bMinusA: '差集 B−A',
}

/** 结果表导出为 CSV / TSV 文本（多值字段用 " | " 连接）。 */
export function rowsToDelimited(rows: ConvertRow[], delimiter: ',' | '\t'): string {
  const header = ['原始ID', 'Symbol', 'Ensembl', 'Entrez', 'UniProt', '状态']
  const esc = (v: string) => (delimiter === ',' && /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)
  const lines = rows.map((r) =>
    [
      r.input,
      r.symbols.join(' | '),
      r.ensembls.join(' | '),
      r.entrezs.join(' | '),
      r.uniprots.join(' | '),
      STATUS_LABEL[r.status],
    ]
      .map(esc)
      .join(delimiter),
  )
  return [header.join(delimiter), ...lines].join('\n')
}

/** 提取结果表某一列的全部非空值（用于单列一键复制）。 */
export function extractColumn(rows: ConvertRow[], column: 'input' | 'symbol' | 'ensembl' | 'entrez' | 'uniprot'): string[] {
  const out: string[] = []
  for (const r of rows) {
    if (column === 'input') out.push(r.input)
    else {
      const key = `${column}s` as 'symbols' | 'ensembls' | 'entrezs' | 'uniprots'
      out.push(...r[key])
    }
  }
  return out
}
