// @vitest-environment jsdom
/**
 * cell 时间线渲染（WP3 任务 1）——KimiMessageItem 投影测试
 *
 *  - 科研模式 + cell_timeline：cell_index 相同的工具卡归入 cell 组（组头 [n] + 语言徽标）
 *  - cell_index 为 null 的工具卡保持原卡片渲染
 *  - 切回消息流（research_mode=null / enabled=false / render_mode=message_flow）：渲染还原，无 cell 组
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'

vi.mock('vue3-lottie', () => ({ Vue3Lottie: { template: '<div />' } }))
vi.mock('vue-echarts', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/studio', () => ({
  studioApi: {
    fetchArtifactBlob: vi.fn().mockResolvedValue('blob:preview'),
    downloadArtifact: vi.fn().mockResolvedValue(undefined),
  },
}))
vi.mock('@/api/client', () => ({ default: { get: vi.fn().mockResolvedValue({ data: new Blob(['x']) }) } }))

import KimiMessageItem from '@/components/ai-chat/KimiMessageItem.vue'
import { useAgentHubStore, type AgentSession } from '@/stores/agentHub'
import type { ChatMessage, ToolCall } from '@/components/ai-chat/types'
import type { ResearchModeSettings } from '@/types/chat'

function makeTool(id: string, cellIndex: number | null, language?: string): ToolCall {
  return {
    id,
    name: 'sandbox_execute',
    arguments: { code: 'print(1)' },
    status: 'success',
    cellIndex,
    language,
  }
}

function seedSession(researchMode: ResearchModeSettings | null) {
  const store = useAgentHubStore()
  const session: AgentSession = {
    id: 'cell-session',
    title: 'cell 会话',
    agent_id: 'agent-router',
    messages: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
    research_mode: researchMode,
  }
  store.sessions = [session]
  store.currentSessionId = session.id
  return session
}

function makeMessage(): ChatMessage {
  return {
    id: 'm-cell',
    role: 'assistant',
    content: '',
    createdAt: '2026-09-10T00:00:00Z',
    toolCalls: [
      makeTool('t-a', 1, 'python'),
      makeTool('t-b', 1),
      makeTool('t-mid', null),
      makeTool('t-c', 2, 'r'),
    ],
  }
}

function mountItem(message: ChatMessage) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render() {
      return h(NMessageProvider, null, {
        default: () => h(KimiMessageItem, { message } as never),
      })
    },
  })
  app.mount(el)
  return { el, app }
}

describe('KimiMessageItem cell 时间线投影（WP3 任务 1）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
      cb(0)
      return 0
    }) as typeof requestAnimationFrame
    global.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
  })

  it('科研模式 cell_timeline：相邻同 cell 卡归组，null 卡保持单卡', async () => {
    seedSession({
      enabled: true,
      render_mode: 'cell_timeline',
      workspace_protocol: 'standard',
      ptc_llm_query: false,
    })
    const { el, app } = mountItem(makeMessage())
    await nextTick()

    const groups = el.querySelectorAll('.studio-cell-group')
    expect(groups).toHaveLength(2)
    expect(groups[0].querySelector('.cell-index')?.textContent).toBe('[1]')
    expect(groups[0].querySelector('.cell-language')?.textContent).toBe('Python')
    expect(groups[1].querySelector('.cell-index')?.textContent).toBe('[2]')
    // cell 组内两张卡（t-a + t-b），null 卡不打乱分组
    expect(groups[0].querySelectorAll('.timeline-tool-entry')).toHaveLength(2)

    app.unmount()
    el.remove()
  })

  it.each([
    ['旧会话 research_mode=null', null],
    ['关闭科研模式', {
      enabled: false,
      render_mode: 'cell_timeline',
      workspace_protocol: 'standard',
      ptc_llm_query: false,
    } satisfies ResearchModeSettings],
    ['渲染形态=消息流', {
      enabled: true,
      render_mode: 'message_flow',
      workspace_protocol: 'standard',
      ptc_llm_query: false,
    } satisfies ResearchModeSettings],
  ])('渲染形态回落消息流：%s 时不出现 cell 组', async (_label, researchMode) => {
    seedSession(researchMode)
    const { el, app } = mountItem(makeMessage())
    await nextTick()

    // 4 张工具卡全部保持原有平铺渲染（ToolCallEntry → MCP 卡），无 cell 分组
    expect(el.querySelectorAll('.studio-cell-group')).toHaveLength(0)
    expect(el.querySelectorAll('.tool-results > *').length).toBeGreaterThan(0)

    app.unmount()
    el.remove()
  })
})
