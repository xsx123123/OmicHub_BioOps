// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  abortStream: vi.fn(),
  get: vi.fn(),
}))

vi.mock('@/api/client', () => ({ default: { get: mocks.get } }))
vi.mock('@/composables/useChatStream', () => ({
  useChatStream: () => ({
    streamChat: mocks.streamChat,
    abortStream: mocks.abortStream,
    isStreaming: ref(false),
  }),
}))

import { useAiAssistantSidebarStore } from '@/stores/aiAssistantSidebar'

const DEMO_MODEL = {
  id: 'm1',
  name: 'Demo Model',
  model: 'demo',
  provider_type: 'openai',
  is_default: true,
  temperature: 0.7,
  max_tokens: 4096,
}

function mockSuccessfulStream() {
  mocks.streamChat.mockImplementation(async (_options: unknown, callbacks: {
    onText: (t: string) => void
    onSessionCreated: (sid: string, mid: string) => void
    onDone: (sid: string, mid: string) => void
  }) => {
    callbacks.onText('你好')
    callbacks.onSessionCreated('cs-1', 'msg-1')
    callbacks.onDone('cs-1', 'msg-1')
  })
}

describe('aiAssistantSidebar store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    mocks.get.mockResolvedValue({ data: [DEMO_MODEL] })
  })

  it('sends messages through the chat stream and completes the assistant reply', async () => {
    mockSuccessfulStream()
    const store = useAiAssistantSidebarStore()

    await store.sendMessage('  你好  ')

    expect(mocks.streamChat).toHaveBeenCalledTimes(1)
    const [options] = mocks.streamChat.mock.calls[0]
    expect(options).toMatchObject({
      modelId: 'm1',
      sessionId: undefined,
      messages: [{ role: 'user', content: '你好' }],
    })

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]).toMatchObject({ role: 'user', content: '你好', status: 'complete' })
    expect(store.messages[1]).toMatchObject({ role: 'assistant', content: '你好', status: 'complete' })
    expect(store.sessionId).toBe('cs-1')
  })

  it('persists session and messages to localStorage after done', async () => {
    mockSuccessfulStream()
    const store = useAiAssistantSidebarStore()
    await store.sendMessage('你好')

    const saved = JSON.parse(localStorage.getItem('ai_assistant_sidebar_state') || '{}')
    expect(saved.sessionId).toBe('cs-1')
    expect(saved.messages).toHaveLength(2)
    expect(saved.messages.every((m: { status: string }) => m.status === 'complete')).toBe(true)
  })

  it('carries sessionId and recent history on follow-up messages', async () => {
    mockSuccessfulStream()
    const store = useAiAssistantSidebarStore()
    await store.sendMessage('第一轮')
    await store.sendMessage('第二轮')

    const [secondOptions] = mocks.streamChat.mock.calls[1]
    expect(secondOptions.sessionId).toBe('cs-1')
    expect(secondOptions.messages).toEqual([
      { role: 'user', content: '第一轮' },
      { role: 'assistant', content: '你好' },
      { role: 'user', content: '第二轮' },
    ])
  })

  it('restores persisted state and seals interrupted streaming messages', () => {
    localStorage.setItem('ai_assistant_sidebar_state', JSON.stringify({
      sessionId: 'cs-old',
      messages: [
        { id: '1', role: 'user', content: 'hi', reasoning: '', status: 'complete', created_at: '' },
        { id: '2', role: 'assistant', content: 'partial', reasoning: '', status: 'streaming', created_at: '' },
      ],
    }))

    const store = useAiAssistantSidebarStore()
    expect(store.sessionId).toBe('cs-old')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[1].status).toBe('complete')
  })

  it('newChat clears local context and persists the empty state', async () => {
    mockSuccessfulStream()
    const store = useAiAssistantSidebarStore()
    await store.sendMessage('你好')

    store.newChat()

    expect(store.messages).toHaveLength(0)
    expect(store.sessionId).toBe('')
    const saved = JSON.parse(localStorage.getItem('ai_assistant_sidebar_state') || '{}')
    expect(saved.sessionId).toBe('')
    expect(saved.messages).toEqual([])
  })

  it('records stream errors on the assistant message', async () => {
    mocks.streamChat.mockImplementation(async (_options: unknown, callbacks: { onError: (e: string) => void }) => {
      callbacks.onError('模型服务异常')
    })
    const store = useAiAssistantSidebarStore()
    await store.sendMessage('你好')

    const last = store.messages[store.messages.length - 1]
    expect(last.status).toBe('error')
    expect(last.error).toBe('模型服务异常')
  })

  it('surfaces a friendly error when no models are available', async () => {
    mocks.get.mockResolvedValue({ data: [] })
    const store = useAiAssistantSidebarStore()
    await store.sendMessage('你好')

    expect(store.loadError).toContain('暂无可用')
    expect(mocks.streamChat).not.toHaveBeenCalled()
  })
})
