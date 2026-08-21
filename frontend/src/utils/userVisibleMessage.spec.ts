import { describe, expect, it } from 'vitest'
import { filterUserVisibleMessages, isUserVisibleMessage } from './userVisibleMessage'

describe('user message visibility policy', () => {
  it('hides explicit internal message types and visible=false rows', () => {
    expect(isUserVisibleMessage({ role: 'assistant', type: 'suggestion', content: '内部建议' })).toBe(false)
    expect(isUserVisibleMessage({ role: 'assistant', visible: false, content: '内部消息' })).toBe(false)
    expect(isUserVisibleMessage({ role: 'assistant', metadata_json: { message_type: 'routing' }, content: '路由' })).toBe(false)
  })

  it('hides the OmicHub AI collaboration suggestion from history and live fallback payloads', () => {
    expect(isUserVisibleMessage({
      role: 'system',
      agent_name: 'OmicHub AI',
      content: '建议升级为协作室协作，以便完成多步骤真实计算。',
    })).toBe(false)
    expect(isUserVisibleMessage({
      role: 'assistant',
      content: '建议升级为协作室协作，以便完成多步骤真实计算。',
    })).toBe(false)
  })

  it('keeps normal system notices, user text, and ordinary assistant replies', () => {
    expect(isUserVisibleMessage({ role: 'system', content: '助手已切换到单细胞助手' })).toBe(true)
    expect(isUserVisibleMessage({ role: 'user', content: '建议升级为协作室协作' })).toBe(true)
    expect(isUserVisibleMessage({ role: 'assistant', content: '这是正常的分析结果。' })).toBe(true)
  })

  it('filters at the array boundary without changing retained messages', () => {
    const visible = { role: 'assistant', content: '正常回复' }
    const internal = { role: 'system', type: 'suggestion', content: '内部建议' }
    expect(filterUserVisibleMessages([visible, internal])).toEqual([visible])
  })
})
