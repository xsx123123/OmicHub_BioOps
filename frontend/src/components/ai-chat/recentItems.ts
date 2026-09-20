/**
 * @ 与 / 面板的"最近使用"记录（localStorage，各保留最近 5 条）
 *
 * Part C 统一体验：最近使用置顶，其余按名称排序。
 */

const STORAGE_KEY = 'cygnusx.panel.recent.v1'
const MAX_RECENT = 5

export type PanelKind = 'mention' | 'slash'

interface RecentStore {
  mention: string[]
  slash: string[]
}

function readStore(): RecentStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { mention: [], slash: [] }
    const parsed = JSON.parse(raw) as Partial<RecentStore>
    return {
      mention: Array.isArray(parsed.mention) ? parsed.mention.filter((x) => typeof x === 'string') : [],
      slash: Array.isArray(parsed.slash) ? parsed.slash.filter((x) => typeof x === 'string') : [],
    }
  } catch {
    return { mention: [], slash: [] }
  }
}

export function getRecent(kind: PanelKind): string[] {
  return readStore()[kind].slice(0, MAX_RECENT)
}

/** 记录一次使用（置顶，去重，截断到 5 条） */
export function pushRecent(kind: PanelKind, id: string): void {
  if (!id) return
  const store = readStore()
  store[kind] = [id, ...store[kind].filter((x) => x !== id)].slice(0, MAX_RECENT)
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    // 隐私模式等场景写入失败时静默降级（仅失去置顶能力）
  }
}

/** 最近使用排序权重：越近越小，未使用返回较大值 */
export function recentRank(kind: PanelKind, id: string): number {
  const idx = getRecent(kind).indexOf(id)
  return idx === -1 ? MAX_RECENT + 1 : idx
}
