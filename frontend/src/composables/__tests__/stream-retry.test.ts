import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentChatStream, type AgentChatStreamOptions } from '@/composables/useAgentChatStream'

function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

function sseEvent(type: string, extra: Record<string, unknown> = {}): string {
  return `data: ${JSON.stringify({ type, ...extra })}\n\n`
}

function installFetch(results: Array<{ ok: boolean; chunks: string[]; status?: number; errorText?: string }>): ReturnType<typeof vi.fn> {
  const mock = vi.fn()
  results.forEach((result) => {
    mock.mockImplementationOnce(() =>
      Promise.resolve({
        ok: result.ok,
        status: result.status ?? (result.ok ? 200 : 500),
        body: sseBody(result.chunks),
        text: () => Promise.resolve(result.errorText || ''),
      }),
    )
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const localStorageStub = {
  getItem: vi.fn(() => ''),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
}

describe('useAgentChatStream 流式连接自动重试', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', localStorageStub)
  })

  const options: AgentChatStreamOptions = {
    agentId: 'agent-1',
    messages: [{ role: 'user', content: 'hi' }],
  }

  it('连接被掐断（无 done/error 且未输出正文）后自动重试并成功', async () => {
    const fetchMock = installFetch([
      { ok: true, chunks: [''] }, // 首次：流结束但无任何事件 → 被判定为中断
      {
        ok: true,
        chunks: [
          sseEvent('text', { content: '你好' }),
          sseEvent('done', { session_id: 's1', message_id: 'm1' }),
        ],
      },
    ])

    const onText = vi.fn()
    const onDone = vi.fn()
    const onRetry = vi.fn()
    const onError = vi.fn()

    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onText, onDone, onRetry, onError })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onRetry).toHaveBeenCalledWith(1, 2)
    expect(onText).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('建流前收到 500 时自动重试并成功，不把内部错误暴露给用户', async () => {
    const fetchMock = installFetch([
      { ok: false, status: 500, errorText: '{"detail":"系统内部错误，请联系管理员"}', chunks: [] },
      { ok: true, chunks: [sseEvent('text', { content: '已恢复' }), sseEvent('done')] },
    ])
    const onText = vi.fn()
    const onRetry = vi.fn()
    const onError = vi.fn()

    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onText, onRetry, onError })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onRetry).toHaveBeenCalledWith(1, 2)
    expect(onText).toHaveBeenCalledWith('已恢复', false)
    expect(onError).not.toHaveBeenCalled()
  })

  it('已输出正文后断连不重试，直接报错', async () => {
    const fetchMock = installFetch([
      { ok: true, chunks: [sseEvent('text', { content: '部分内容' })] }, // 有正文但无 done
    ])

    const onText = vi.fn()
    const onRetry = vi.fn()
    const onError = vi.fn()

    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onText, onRetry, onError })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onRetry).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith(
      '流式连接意外中断，请重新发送；如果频繁出现，请检查模型服务或反向代理超时配置',
    )
  })

  it('重试次数用尽后给出中断提示', async () => {
    const fetchMock = installFetch([
      { ok: true, chunks: [''] },
      { ok: true, chunks: [''] },
      { ok: true, chunks: [''] },
    ])

    const onRetry = vi.fn()
    const onError = vi.fn()

    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onRetry, onError })

    expect(fetchMock).toHaveBeenCalledTimes(3) // 1 次首次 + 2 次重试
    expect(onRetry).toHaveBeenCalledTimes(2)
    expect(onRetry).toHaveBeenLastCalledWith(2, 2)
    expect(onError).toHaveBeenCalledWith(
      '流式连接意外中断，请重新发送；如果频繁出现，请检查模型服务或反向代理超时配置',
    )
  })

  it('收到 error 事件时不重试', async () => {
    const fetchMock = installFetch([
      { ok: true, chunks: [sseEvent('error', { content: '模型内部错误' })] },
    ])

    const onError = vi.fn()
    const onRetry = vi.fn()

    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onError, onRetry })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onRetry).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('模型内部错误')
  })

  it('正常结束后复位 isStreaming，同一实例可再次发送（回归：第二条消息不被吞）', async () => {
    const fetchMock = installFetch([
      { ok: true, chunks: [sseEvent('text', { content: '你好' }), sseEvent('done', { session_id: 's1', message_id: 'm1' })] },
      { ok: true, chunks: [sseEvent('text', { content: '再问' }), sseEvent('done', { session_id: 's1', message_id: 'm2' })] },
    ])

    const { streamChat, isStreaming } = useAgentChatStream()
    await streamChat(options, {})
    expect(isStreaming.value).toBe(false)

    const onText = vi.fn()
    const onDone = vi.fn()
    await streamChat(options, { onText, onDone })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(onText).toHaveBeenCalledTimes(1)
    expect(onDone).toHaveBeenCalled()
  })
})
