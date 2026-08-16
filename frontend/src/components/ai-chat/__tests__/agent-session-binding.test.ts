// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { AgentTemplate } from '@/types/agent'
import { useAgentHubStore } from '@/stores/agentHub'

interface MockStream {
  controller: ReadableStreamDefaultController<Uint8Array>
  request: RequestInit
}

describe('@Agent 会话绑定', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('首轮显式选择 Agent 后，后续消息沿用同一 Agent', async () => {
    const streams: MockStream[] = []
    const encoder = new TextEncoder()
    vi.stubGlobal('fetch', vi.fn((_url: string, request: RequestInit) => {
      let streamController!: ReadableStreamDefaultController<Uint8Array>
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller
        },
      })
      streams.push({ controller: streamController, request })
      return Promise.resolve(new Response(body, { status: 200 }))
    }))

    const store = useAgentHubStore()
    store.agents = [
      {
        id: 'agent-general',
        agent_id: 'agent-general',
        name: '通用助手',
        model_id: 'model-general',
        is_active: true,
      },
      {
        id: 'agent-shaniu',
        agent_id: 'agent-shaniu',
        name: '傻妞',
        model_id: 'model-shaniu',
        is_active: true,
      },
    ] as unknown as AgentTemplate[]

    const session = store.startSessionFromAgent('agent-general')!
    const firstSend = store.sendMessage('@傻妞 你好', { explicitAgentId: 'agent-shaniu' })
    await vi.waitFor(() => expect(streams).toHaveLength(1))

    const firstPayload = JSON.parse(String(streams[0].request.body))
    expect(firstPayload.agent_id).toBe('agent-shaniu')
    expect(firstPayload.model_id).toBe('model-shaniu')
    expect(session.agent_id).toBe('agent-shaniu')

    streams[0].controller.enqueue(encoder.encode('data: {"type":"text","content":"你好","session_id":"server-session","message_id":"message-1"}\n\n'))
    streams[0].controller.enqueue(encoder.encode('data: {"type":"done","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'))
    streams[0].controller.close()
    await firstSend

    expect(session.id).toBe('server-session')
    expect(session.agent_id).toBe('agent-shaniu')

    const secondSend = store.sendMessage('我继续和你聊')
    await vi.waitFor(() => expect(streams).toHaveLength(2))
    const secondPayload = JSON.parse(String(streams[1].request.body))
    expect(secondPayload.session_id).toBe('server-session')
    expect(secondPayload.agent_id).toBe('agent-shaniu')

    streams[1].controller.enqueue(encoder.encode('data: {"type":"done","usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'))
    streams[1].controller.close()
    await secondSend
    vi.unstubAllGlobals()
  })
})
