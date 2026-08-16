import { describe, expect, it } from 'vitest'
import {
  activeOverdriveProgress,
  conversationMessagesWithoutProgress,
  latestOverdriveProgress,
} from '@/components/ai-chat/overdriveUi'
import type { ChatMessage } from '@/components/ai-chat/types'

const userMessage: ChatMessage = {
  id: 'user',
  role: 'user',
  content: '开始分析',
  createdAt: '2026-08-06T10:00:00Z',
}

describe('overdrive 固定进度 Dock 状态', () => {
  it('从滚动消息中移除进度消息，并选择最新活动进度', () => {
    const messages: ChatMessage[] = [
      userMessage,
      {
        id: 'progress',
        role: 'system',
        content: '代码助手正在执行',
        createdAt: '2026-08-06T10:00:01Z',
        overdriveProgress: {
          phase: 'tool_running',
          label: '代码助手正在执行',
          completed: 1,
          total: 3,
        },
      },
    ]

    expect(conversationMessagesWithoutProgress(messages)).toEqual([userMessage])
    expect(activeOverdriveProgress(messages)?.phase).toBe('tool_running')
  })

  it('协作完成后隐藏固定进度 Dock', () => {
    const messages: ChatMessage[] = [
      userMessage,
      {
        id: 'progress',
        role: 'system',
        content: '已完成',
        createdAt: '2026-08-06T10:00:01Z',
        overdriveProgress: {
          phase: 'completed',
          label: '已完成',
          completed: 3,
          total: 3,
        },
      },
    ]

    expect(activeOverdriveProgress(messages)).toBeNull()
  })

  it('协作完成后仍可取到最近一次进度，用于保留完成态卡片', () => {
    const messages: ChatMessage[] = [
      userMessage,
      {
        id: 'progress',
        role: 'system',
        content: '已完成',
        createdAt: '2026-08-06T10:00:01Z',
        overdriveProgress: {
          phase: 'completed',
          label: '本轮超频协作已结束',
          completed: 3,
          total: 3,
        },
      },
    ]

    expect(latestOverdriveProgress(messages)?.phase).toBe('completed')
    expect(latestOverdriveProgress([])).toBeNull()
  })
})
