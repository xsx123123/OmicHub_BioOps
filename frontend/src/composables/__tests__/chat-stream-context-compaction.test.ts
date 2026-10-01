import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from '@/composables/useChatStream'

function sseBody(events: Record<string, unknown>[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const payload = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(payload))
      controller.close()
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useChatStream context compaction events', () => {
  it('forwards the backward-compatible estimated token field', async () => {
    vi.stubGlobal('localStorage', { getItem: vi.fn(() => '') })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      body: sseBody([
        { type: 'context_compressed', estimated_tokens_before: 12345, tokens_after: 4567 },
        { type: 'done', session_id: 's1', message_id: 'm1' },
      ]),
    })))

    const onContextCompressed = vi.fn()
    const onDone = vi.fn()
    const { streamChat } = useChatStream()

    await streamChat(
      { messages: [{ role: 'user', content: 'hello' }], modelId: 'model-1' },
      { onContextCompressed, onDone },
    )

    expect(onContextCompressed).toHaveBeenCalledWith(12345)
    expect(onDone).toHaveBeenCalledWith('s1', 'm1')
  })
})
