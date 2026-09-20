import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: { get: getMock, post: postMock },
}))

import { useAgentHubStore, type AgentSession } from '@/stores/agentHub'

function makeSession(patch: Partial<AgentSession> = {}): AgentSession {
  return {
    id: 'archived-1',
    title: '测试会话',
    agent_id: 'agent-router',
    messages: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
    ...patch,
  }
}

describe('会话工作区归档恢复（WP1）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // loadSessionMessages 拉历史消息
    getMock.mockResolvedValue({ data: [] })
  })

  it('点击已归档会话：先调 restore，成功后清除归档标记并进入正常打开流程', async () => {
    const store = useAgentHubStore()
    const session = makeSession({
      workspace_archive: {
        package_id: 'pkg-1',
        created_at: '2026-09-10T00:00:00Z',
        expires_at: '2026-10-10T00:00:00Z',
      },
    })
    store.sessions = [session]
    postMock.mockResolvedValue({ data: { restored: true } })

    await store.openSessionWithRestore(session.id)

    expect(postMock).toHaveBeenCalledWith(`/studio/sessions/${session.id}/restore`)
    expect(session.workspace_archive).toBeNull()
    expect(store.currentSessionId).toBe(session.id)
    // 正常打开流程：加载历史消息
    expect(getMock).toHaveBeenCalledWith(`/chat/sessions/${session.id}/messages`)
  })

  it('幂等响应（restored + idempotent）按成功处理', async () => {
    const store = useAgentHubStore()
    const session = makeSession({
      id: 'archived-idem',
      workspace_archive: {
        package_id: 'pkg-2',
        created_at: '2026-09-10T00:00:00Z',
        expires_at: '2026-10-10T00:00:00Z',
      },
    })
    store.sessions = [session]
    postMock.mockResolvedValue({ data: { restored: true, idempotent: true } })

    await store.openSessionWithRestore(session.id)

    expect(session.workspace_archive).toBeNull()
    expect(store.currentSessionId).toBe(session.id)
  })

  it('not_archived 响应视为已被其他端恢复，继续正常打开流程', async () => {
    const store = useAgentHubStore()
    const session = makeSession({
      id: 'archived-not-archived',
      workspace_archive: {
        package_id: 'pkg-3',
        created_at: '2026-09-10T00:00:00Z',
        expires_at: '2026-10-10T00:00:00Z',
      },
    })
    store.sessions = [session]
    postMock.mockResolvedValue({ data: { restored: false, reason: 'not_archived' } })

    await store.openSessionWithRestore(session.id)

    expect(session.workspace_archive).toBeNull()
    expect(store.currentSessionId).toBe(session.id)
  })

  it('配额不足（409 + detail）：抛错透传后端信息，不进入会话', async () => {
    const store = useAgentHubStore()
    const archive = {
      package_id: 'pkg-4',
      created_at: '2026-09-10T00:00:00Z',
      expires_at: '2026-10-10T00:00:00Z',
    }
    const session = makeSession({ id: 'archived-quota', workspace_archive: archive })
    store.sessions = [session]
    postMock.mockRejectedValue({ response: { status: 409, data: { detail: '归档配额不足，无法恢复' } } })

    await expect(store.openSessionWithRestore(session.id)).rejects.toThrow('归档配额不足，无法恢复')
    expect(session.workspace_archive).toEqual(archive)
    expect(store.currentSessionId).toBe('')
    expect(getMock).not.toHaveBeenCalled()
  })

  it('普通会话不触发 restore，直接打开', async () => {
    const store = useAgentHubStore()
    const session = makeSession({ id: 'normal-1', workspace_archive: null })
    store.sessions = [session]

    await store.openSessionWithRestore(session.id)

    expect(postMock).not.toHaveBeenCalled()
    expect(store.currentSessionId).toBe(session.id)
  })
})
