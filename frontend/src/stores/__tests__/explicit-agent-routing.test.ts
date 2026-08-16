// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { AgentTemplate } from '@/types/agent'
import { useAgentHubStore } from '@/stores/agentHub'

describe('显式 Agent 指派', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('使用 explicitAgentId 覆盖星尘会话的默认 Agent', async () => {
    const streams: Array<{ controller: ReadableStreamDefaultController<Uint8Array>; request: RequestInit }> = []
    const encoder = new TextEncoder()
    vi.stubGlobal('fetch', vi.fn((_url: string, request: RequestInit) => {
      let controller!: ReadableStreamDefaultController<Uint8Array>
      const stream = new ReadableStream<Uint8Array>({
        start(value) {
          controller = value
        },
      })
      streams.push({ controller, request })
      return Promise.resolve(new Response(stream, { status: 200 }))
    }))

    const store = useAgentHubStore()
    store.agents = [
      { id: 'agent-router', agent_id: 'agent-router', name: '星尘 AI', is_active: true, features: { router: true } },
      { id: 'agent-code', agent_id: 'agent-code', name: '代码助手', model_id: 'code-model', is_active: true },
    ] as unknown as AgentTemplate[]
    const session = store.startSessionFromAgent('agent-router')!
    session.title_locked = true

    const sending = store.sendMessage('请调试这段脚本', { explicitAgentId: 'agent-code' })
    await vi.waitFor(() => expect(streams).toHaveLength(1))

    const payload = JSON.parse(String(streams[0].request.body))
    expect(payload.agent_id).toBe('agent-code')
    expect(payload.model_id).toBe('code-model')

    streams[0].controller.enqueue(encoder.encode('data: {"type":"done","usage":{}}\n\n'))
    streams[0].controller.close()
    await sending
  })
})
