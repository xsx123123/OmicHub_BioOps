/**
 * 基因 ID 映射查询接口。
 *
 * 当前数据源为内置 mock 数据（geneIdMapData.ts），接口设计为异步形态，
 * 未来可无缝替换为 IndexedDB 或后端 API，调用方无需改动。
 */

import { buildMockEntries } from './geneIdMapData'

export type Species = 'human' | 'mouse'

export interface GeneMapEntry {
  symbol: string
  ensembl: string
  entrez: string
  uniprot: string
}

export type IdType = 'symbol' | 'ensembl' | 'entrez' | 'uniprot'

export interface LookupResult {
  /** 用户输入的原始 ID */
  id: string
  /** 命中的映射条目；>1 条表示一对多，0 条表示未匹配 */
  matches: GeneMapEntry[]
}

/** 已加载的物种数据缓存。 */
const cache = new Map<Species, GeneMapEntry[]>()

/** 各字段的规范化函数（查询键统一大小写规则）。 */
const NORMALIZERS: Record<IdType, (v: string) => string> = {
  symbol: (v) => v.toUpperCase(),
  ensembl: (v) => v.toUpperCase(),
  entrez: (v) => v.trim(),
  uniprot: (v) => v.toUpperCase(),
}

/** 加载指定物种的映射表（带缓存；异步形态，未来可换 IndexedDB / API）。 */
export async function loadGeneMap(species: Species): Promise<GeneMapEntry[]> {
  const hit = cache.get(species)
  if (hit) return hit
  const entries = buildMockEntries(species)
  cache.set(species, entries)
  return entries
}

/** 同步读取已加载的物种映射表；未加载返回 null（供 computed 内使用）。 */
export function getGeneMapSync(species: Species): GeneMapEntry[] | null {
  return cache.get(species) ?? null
}

/**
 * 批量查询：按指定 ID 类型在给定物种的映射表中查找。
 * 已加载数据时同步完成；未加载时先加载。
 */
export async function lookup(
  species: Species,
  ids: string[],
  idType: IdType,
): Promise<LookupResult[]> {
  const entries = await loadGeneMap(species)
  return lookupEntries(entries, ids, idType)
}

/** 在已加载的映射表上同步查询（纯函数，视图层 computed 直接调用）。 */
export function lookupEntries(
  entries: GeneMapEntry[],
  ids: string[],
  idType: IdType,
): LookupResult[] {
  const normalize = NORMALIZERS[idType]
  const index = new Map<string, GeneMapEntry[]>()
  for (const e of entries) {
    const key = normalize(e[idType])
    const list = index.get(key)
    if (list) list.push(e)
    else index.set(key, [e])
  }
  return ids.map((id) => ({
    id,
    matches: index.get(normalize(id)) ?? [],
  }))
}
