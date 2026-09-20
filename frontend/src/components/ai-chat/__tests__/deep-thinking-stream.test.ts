// @vitest-environment jsdom
/**
 * 全链路复现测试：agentHub store + useAgentChatStream SSE 解析 + KimiMessageList 渲染
 *
 * 使用真实抓取的后端 SSE 流（qwen3.7-max，deep_thinking=true，fixture
 * 内为 "hi" 的完整响应：45 个 reasoning 事件 + 正文事件 + done(usage)），
 * 验证流结束后：思考过程与正文分别展示，正文不空白。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('vue3-lottie', () => ({ Vue3Lottie: { template: '<div />' } }))
vi.mock('vue-echarts', () => ({ default: { template: '<div />' } }))

import { useAgentHubStore } from '@/stores/agentHub'
import KimiMessageList from '@/components/ai-chat/KimiMessageList.vue'
import type { AgentTemplate } from '@/types/agent'

const SSE_FIXTURE = readFileSync(
  resolve(__dirname, 'fixtures/sse_deep_thinking.txt'),
  'utf-8',
)

function mockFetchWithSse(sseText: string) {
  const encoder = new TextEncoder()
  // 模拟网络分片：按 ~700 字节切块，验证跨 chunk 的 SSE 行缓冲
  const bytes = encoder.encode(sseText)
  const chunks: Uint8Array[] = []
  for (let i = 0; i < bytes.length; i += 700) chunks.push(bytes.slice(i, i + 700))

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const c of chunks) {
        controller.enqueue(c)
        await new Promise((r) => setTimeout(r, 0))
      }
      controller.close()
    },
  })
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: stream,
  }) as unknown as typeof fetch
}

beforeEach(() => {
  global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    cb(0)
    return 0
  }) as typeof requestAnimationFrame
  global.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame
  setActivePinia(createPinia())
})

describe('深度思考流式聊天全链路', () => {
  it('超频 worker reasoning delta 写入 thought，正式 delta 只写入 content', async () => {
    mockFetchWithSse([
      'data: {"type":"mode_changed","mode":"overdrive","enabled":true}',
      'data: {"type":"room_speech_delta","content":"WORKER_REASONING","sender":{"agent_id":"agent-general","name":"通用助手","role":"worker"},"worker_key":"worker-1","is_reasoning":true}',
      'data: {"type":"room_speech_delta","content":"WORKER_FINAL","sender":{"agent_id":"agent-general","name":"通用助手","role":"worker"},"worker_key":"worker-1"}',
      'data: {"type":"room_speech","content":"WORKER_FINAL","thought":"WORKER_REASONING","sender":{"agent_id":"agent-general","name":"通用助手","role":"worker"},"worker_key":"worker-1","round":1,"session_id":"session-overdrive","message_id":"message-worker"}',
      'data: {"type":"done","session_id":"session-overdrive"}',
      '',
    ].join('\n'))

    const store = useAgentHubStore()
    store.agents = [
      {
        id: 'agent-general',
        agent_id: 'agent-general',
        name: '通用助手',
        description: '',
        avatar: '🤖',
        color: '#4f8ef7',
        model_engine: 'test-model',
        model_id: 'model-id',
        is_active: true,
        features: {},
      } as unknown as AgentTemplate,
    ]
    const session = store.startSessionFromAgent('agent-general')!
    session.overdrive = true

    await store.sendMessage('请协作分析')

    const worker = session.messages.find((message) => message.senderAgent?.role === 'worker')!
    expect(worker.content).toBe('WORKER_FINAL')
    expect(worker.thought).toBe('WORKER_REASONING')
    expect(worker.content).not.toContain('WORKER_REASONING')
  })

  it('SSE(reasoning+content+done) → store → DOM：思考与正文分别展示，正文不空白', async () => {
    mockFetchWithSse(SSE_FIXTURE)

    const store = useAgentHubStore()
    store.agents = [
      {
        id: 'agent-general',
        agent_id: 'agent-general',
        name: '通用助手',
        description: '',
        avatar: '🤖',
        color: '#4f8ef7',
        model_engine: 'qwen3.7-max',
        model_id: 'af51960c-3110-4d91-9052-a5f60e092ed5',
        is_active: true,
        features: {},
      } as unknown as AgentTemplate,
    ]
    const session = store.startSessionFromAgent('agent-general')!

    await store.sendMessage('hi')

    const aiMsg = session.messages.find((m) => m.role === 'assistant')!
    // store 层：正文与思考分离，token 统计写入
    expect(aiMsg.thought?.length).toBeGreaterThan(0)
    expect(aiMsg.content.length).toBeGreaterThan(0)
    expect(aiMsg.content).toContain('你好')
    expect(aiMsg.tokens?.input).toBe(4208)
    expect(aiMsg.tokens?.output).toBe(321)
    expect(store.isStreaming).toBe(false)

    // DOM 层：列表渲染后正文可见、思考面板可见
    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp({
      render() {
        return h(NMessageProvider, null, {
          default: () => h(KimiMessageList, {
            messages: session.messages,
            isTyping: store.isStreaming,
            streamingContent: store.streamingContent,
            streamingThought: store.streamingThought,
          }),
        })
      },
    })
    app.mount(el)
    await nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(el.textContent).toContain('思考过程')
    expect(el.textContent).toContain('你好')
  }, 15000)

  it('仅 done 事件携带 answer：仍写入正文并完成消息状态', async () => {
    mockFetchWithSse([
      'data: {"type":"done","session_id":"session-final","message_id":"message-final","answer":"来自 done 事件的完整正文","usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}',
      '',
    ].join('\n'))

    const store = useAgentHubStore()
    store.agents = [
      {
        id: 'agent-general',
        agent_id: 'agent-general',
        name: '通用助手',
        description: '',
        avatar: '🤖',
        color: '#4f8ef7',
        model_engine: 'test-model',
        model_id: 'model-id',
        is_active: true,
        features: {},
      } as unknown as AgentTemplate,
    ]
    const session = store.startSessionFromAgent('agent-general')!

    await store.sendMessage('测试全量响应')

    const aiMsg = session.messages.find((message) => message.role === 'assistant')!
    expect(aiMsg.id).toMatch(/^msg-ai-/)
    expect(aiMsg.backendMessageId).toBe('message-final')
    expect(aiMsg.content).toBe('来自 done 事件的完整正文')
    expect(aiMsg.status).toBe('complete')
    expect(aiMsg.tokens).toEqual({ input: 12, output: 8, total: 20, cached: 0 })
  })
})
