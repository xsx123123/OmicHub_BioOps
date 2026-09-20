// @vitest-environment jsdom
/**
 * cell 时间线投影（WP3 任务 1）——分组纯函数测试
 *
 * 验收要点：
 *  - cell_index 相同的相邻工具卡归入一个 cell 组，组头序号/语言徽标正确
 *  - cell_index 为 null 的工具卡保持单卡渲染，不打乱分组
 *  - 分组不重排顺序：投影可逆（消息流 ↔ cell 时间线），无丢卡
 */
import { describe, expect, it } from 'vitest'
import { groupToolsByCell, cellLanguageBadge } from '@/components/studio/cellTimeline'
import type { ToolCall } from '@/components/ai-chat/types'

function tool(patch: Partial<ToolCall>): ToolCall {
  return {
    id: Math.random().toString(36).slice(2),
    name: 'sandbox_execute',
    arguments: {},
    status: 'success',
    ...patch,
  }
}

describe('groupToolsByCell（cell 时间线分组）', () => {
  it('cell_index 相同的相邻工具卡归入同一 cell 组', () => {
    const tools = [
      tool({ id: 'a', cellIndex: 1, language: 'python' }),
      tool({ id: 'b', cellIndex: 1 }),
      tool({ id: 'c', cellIndex: 2, language: 'r' }),
    ]
    const items = groupToolsByCell(tools)

    expect(items).toHaveLength(2)
    expect(items[0]).toMatchObject({ type: 'cell', cellIndex: 1, language: 'Python' })
    expect((items[0] as { tools: ToolCall[] }).tools.map((t) => t.id)).toEqual(['a', 'b'])
    expect(items[1]).toMatchObject({ type: 'cell', cellIndex: 2, language: 'R' })
    expect((items[1] as { tools: ToolCall[] }).tools.map((t) => t.id)).toEqual(['c'])
  })

  it('cell_index 为 null 的工具卡保持单卡渲染，不打乱分组', () => {
    const tools = [
      tool({ id: 'a', cellIndex: 1, language: 'python' }),
      tool({ id: 'm', cellIndex: null, name: 'ask_user' }),
      tool({ id: 'b', cellIndex: 1 }),
    ]
    const items = groupToolsByCell(tools)

    expect(items).toHaveLength(3)
    expect(items[0]).toMatchObject({ type: 'cell', cellIndex: 1 })
    expect(items[1]).toMatchObject({ type: 'single' })
    expect((items[1] as { tool: ToolCall }).tool.id).toBe('m')
    // 非相邻的同 cell 卡不跨 null 卡合并（保持时序，投影可逆）
    expect(items[2]).toMatchObject({ type: 'cell', cellIndex: 1 })
  })

  it('全部无 cell_index（旧数据）时原样返回单卡序列', () => {
    const tools = [tool({ id: 'a' }), tool({ id: 'b' })]
    const items = groupToolsByCell(tools)

    expect(items).toHaveLength(2)
    expect(items.every((i) => i.type === 'single')).toBe(true)
    expect((items[0] as { tool: ToolCall }).tool.id).toBe('a')
    expect((items[1] as { tool: ToolCall }).tool.id).toBe('b')
  })

  it('分组保留传入顺序，无丢卡（投影可逆）', () => {
    const tools = [
      tool({ id: 'a', cellIndex: 3 }),
      tool({ id: 'b', cellIndex: 3 }),
      tool({ id: 'c' }),
      tool({ id: 'd', cellIndex: 1 }),
    ]
    const items = groupToolsByCell(tools)
    const flattened = items.flatMap((i) => (i.type === 'cell' ? i.tools : [i.tool]))

    expect(flattened.map((t) => t.id)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('cellLanguageBadge：已知语言映射、未知语言透传、缺失为 null', () => {
    expect(cellLanguageBadge(tool({ language: 'python' }))).toBe('Python')
    expect(cellLanguageBadge(tool({ language: 'R' }))).toBe('R')
    expect(cellLanguageBadge(tool({ language: 'julia' }))).toBe('julia')
    expect(cellLanguageBadge(tool({}))).toBeNull()
  })
})
