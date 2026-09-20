/**
 * 建议追问 Chips 阶段 2 结构化通道的端到端冒烟（前端半段）：
 * 含"可选下一步"的回复文本 → done 事件携带 suggestions → onDone 回调拿到
 * 归一化后的结构化建议（供 agentHub 落到消息模型）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
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

const REPLY_WITH_NEXT_STEPS = [
  '分析已完成，进化树已构建。',
  '',
  '**可选下一步**',
  '',
  '1. 标签精简/分组着色：把叶片名改成短名，并按分组着色',
  '2. 提供 .contree 文件路径：我可以基于它叠加更多注释',
].join('\n')

// 与后端 suggestions_metadata(full_content) 的输出结构一致
const BACKEND_SUGGESTIONS = [
  {
    label: '标签精简/分组着色',
    prompt: '标签精简/分组着色：把叶片名改成短名，并按分组着色',
    action: 'send',
  },
  {
    label: '提供 .contree 文件路径',
    prompt: '提供 .contree 文件路径：我可以基于它叠加更多注释',
    action: 'prefill',
  },
]

const options: AgentChatStreamOptions = {
  agentId: 'agent-1',
  messages: [{ role: 'user', content: '帮我构建进化树' }],
}

// 与 stream-retry.test.ts 相同：streamChat 会读 access_token，node 环境需 stub
const localStorageStub = {
  getItem: vi.fn(() => ''),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
}
vi.stubGlobal('localStorage', localStorageStub)

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.stubGlobal('localStorage', localStorageStub)
})

describe('useAgentChatStream done 事件 suggestions 通道', () => {
  it('done 事件携带结构化 suggestions 时原样透传给 onDone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          body: sseBody([
            sseEvent('text', { content: REPLY_WITH_NEXT_STEPS, session_id: 's1', message_id: 'm1' }),
            sseEvent('done', {
              session_id: 's1',
              message_id: 'm1',
              suggestions: BACKEND_SUGGESTIONS,
            }),
          ]),
          text: () => Promise.resolve(''),
        }),
      ),
    )

    const onDone = vi.fn()
    const onText = vi.fn()
    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onDone, onText })

    // 正文经 text 事件流出（done 事件的 content 恒为空，finalContent 仅是断流兜底）
    expect(onText).toHaveBeenCalledWith(REPLY_WITH_NEXT_STEPS, false)
    expect(onDone).toHaveBeenCalledTimes(1)
    const [, messageId, , , , , suggestions] = onDone.mock.calls[0]
    expect(messageId).toBe('m1')
    // action 以字段值为准，不走关键词判定
    expect(suggestions).toEqual(BACKEND_SUGGESTIONS)
  })

  it('done 事件无 suggestions 字段时 onDone 收到 undefined（渲染层回退正则解析）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          body: sseBody([
            sseEvent('text', { content: '好的', session_id: 's1', message_id: 'm1' }),
            sseEvent('done', { session_id: 's1', message_id: 'm1' }),
          ]),
          text: () => Promise.resolve(''),
        }),
      ),
    )

    const onDone = vi.fn()
    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onDone })

    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onDone.mock.calls[0][6]).toBeUndefined()
  })

  it('suggestions 形状不完整时被过滤，不抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          body: sseBody([
            sseEvent('done', {
              session_id: 's1',
              message_id: 'm1',
              suggestions: [
                { label: '有效条目', prompt: '有效条目：继续', action: 'send' },
                { label: '', prompt: '缺 label 被丢弃', action: 'send' },
                'not-an-object',
                { label: '非法 action 回退 send', prompt: '某条目', action: 'unknown' },
              ],
            }),
          ]),
          text: () => Promise.resolve(''),
        }),
      ),
    )

    const onDone = vi.fn()
    const { streamChat } = useAgentChatStream()
    await streamChat(options, { onDone })

    expect(onDone.mock.calls[0][6]).toEqual([
      { label: '有效条目', prompt: '有效条目：继续', action: 'send' },
      { label: '非法 action 回退 send', prompt: '某条目', action: 'send' },
    ])
  })
})
