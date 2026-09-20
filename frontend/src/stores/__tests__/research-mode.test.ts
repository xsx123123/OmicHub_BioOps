import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { putMock, getMock } = vi.hoisted(() => ({
  putMock: vi.fn(),
  getMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: getMock, put: putMock },
}))

import { useAgentHubStore, type AgentSession } from '@/stores/agentHub'
import type { ResearchModeSettings } from '@/types/chat'

function makeSession(patch: Partial<AgentSession> = {}): AgentSession {
  return {
    id: 'research-1',
    title: '科研会话',
    agent_id: 'agent-router',
    messages: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
    ...patch,
  }
}

const CELL_MODE: ResearchModeSettings = {
  enabled: true,
  render_mode: 'cell_timeline',
  workspace_protocol: 'research',
  ptc_llm_query: true,
}

describe('科研模式设置（WP3 任务 3）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('PUT research-mode 端点并以回显值更新会话', async () => {
    const store = useAgentHubStore()
    const session = makeSession()
    store.sessions = [session]
    putMock.mockResolvedValue({ data: CELL_MODE })

    await store.updateResearchMode(session.id, CELL_MODE)

    expect(putMock).toHaveBeenCalledWith(
      `/chat/sessions/${session.id}/research-mode`,
      CELL_MODE,
    )
    expect(session.research_mode).toEqual(CELL_MODE)
  })

  it('旧会话 research_mode 为 null 时显示全关（默认状态）', () => {
    const store = useAgentHubStore()
    const session = makeSession({ research_mode: null })
    store.sessions = [session]
    expect(store.currentSession?.research_mode ?? null).toBeNull()
  })

  it('PUT 失败时回滚 research_mode 并抛出错误', async () => {
    const store = useAgentHubStore()
    const previous: ResearchModeSettings = {
      enabled: true,
      render_mode: 'message_flow',
      workspace_protocol: 'standard',
      ptc_llm_query: false,
    }
    const session = makeSession({ research_mode: previous })
    store.sessions = [session]
    putMock.mockRejectedValue(new Error('backend offline'))

    await expect(store.updateResearchMode(session.id, CELL_MODE)).rejects.toThrow('backend offline')
    expect(session.research_mode).toEqual(previous)
  })

  it('未登记的会话 ID 不产生任何请求', async () => {
    const store = useAgentHubStore()
    store.sessions = []

    await store.updateResearchMode('no-such-session', CELL_MODE)

    expect(putMock).not.toHaveBeenCalled()
  })
})
