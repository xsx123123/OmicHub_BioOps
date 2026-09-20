/**
 * cell 时间线投影（WP3 任务 1）——纯函数分组工具
 *
 * 同一会话历史里 cell_index 相同的工具卡归入一个 cell 组；
 * cell_index 为 null 的工具卡（非代码工具）保持单卡渲染，不打乱分组。
 *
 * 分组规则：按传入顺序做"连续段"归并 —— 只合并相邻且 cell_index 相同的工具卡，
 * 绝不重排卡片顺序（投影可逆：消息流 ↔ cell 时间线 渲染同一份历史，无丢卡无错乱）。
 */
import type { ToolCall } from '@/components/ai-chat/types'

export type CellTimelineItem =
  | { type: 'cell'; cellIndex: number; language: string | null; tools: ToolCall[] }
  | { type: 'single'; tool: ToolCall }

const LANG_BADGES: Record<string, string> = { python: 'Python', r: 'R', bash: 'Bash' }

/** cell 组头的语言徽标：优先信封 language，其次工具自身 language，缺省 null（不显示） */
export function cellLanguageBadge(tool: ToolCall): string | null {
  const raw = tool.language
  if (!raw) return null
  const normalized = String(raw).toLowerCase()
  return LANG_BADGES[normalized] || normalized
}

export function groupToolsByCell(tools: ToolCall[]): CellTimelineItem[] {
  const items: CellTimelineItem[] = []
  for (const tool of tools) {
    const cellIndex = typeof tool.cellIndex === 'number' ? tool.cellIndex : null
    const last = items[items.length - 1]
    if (cellIndex !== null && last?.type === 'cell' && last.cellIndex === cellIndex) {
      last.tools.push(tool)
      if (!last.language) {
        const badge = cellLanguageBadge(tool)
        if (badge) last.language = badge
      }
      continue
    }
    if (cellIndex !== null) {
      items.push({ type: 'cell', cellIndex, language: cellLanguageBadge(tool), tools: [tool] })
    } else {
      items.push({ type: 'single', tool })
    }
  }
  return items
}
