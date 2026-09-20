// @vitest-environment jsdom
/**
 * 复现「回复后正文/tokens 不显示，刷新后才出现」的前端 bug。
 *
 * 现有测试都是「按目标状态新鲜挂载」，无法捕获真实浏览器里
 * 同一个 KimiMessageItem 实例从 streaming → done 的活体切换。
 * 这里让同一实例经历：
 *   1. 流式中：isStreaming=true, streamingContent 增长, message.content=''
 *   2. 结束：isStreaming=false, message.content=最终正文, streamingContent 复位为 ''
 * 并断言切换后 DOM 立即出现正文与 tokens（无需刷新/重挂载）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick, reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'

vi.mock('vue3-lottie', () => ({
  Vue3Lottie: { template: '<div />', methods: { setSpeed() {} } },
}))
vi.mock('vue-echarts', () => ({ default: { template: '<div />' } }))

import KimiMessageItem from '@/components/ai-chat/KimiMessageItem.vue'
import KimiMessageList from '@/components/ai-chat/KimiMessageList.vue'
import type { ChatMessage } from '@/components/ai-chat/types'
import type { AgentTemplate } from '@/types/agent'
import { useAgentHubStore } from '@/stores/agentHub'

beforeEach(() => {
  global.requestAnimationFrame = ((cb: FrameRequestCallback) => { cb(0); return 0 }) as typeof requestAnimationFrame
  global.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame
  setActivePinia(createPinia())
})

describe('KimiMessageItem 活体 streaming→done 切换', () => {
  it('同一实例流式结束后，正文与 tokens 立即渲染（无需刷新）', async () => {
    const message = reactive<ChatMessage>({
      id: 'msg-ai-1',
      role: 'assistant',
      content: '',
      thought: '',
      status: 'streaming',
      createdAt: new Date().toISOString(),
      tokens: { input: 0, output: 0, total: 0 },
    })
    const props = reactive({
      message,
      isStreaming: true,
      streamingContent: '',
      streamingThought: '',
    })

    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp({
      render() {
        return h(NMessageProvider, null, {
          default: () => h(KimiMessageItem, props as never),
        })
      },
    })
    app.mount(el)
    await nextTick()

    // 1. 流式中：先来思考，再来正文（模拟真实事件顺序）
    props.streamingThought = '用户打招呼，应友好回应'
    await nextTick()
    props.streamingContent = '你好！我是'
    await nextTick()
    props.streamingContent = '你好！我是 CygnusX AI 助手。'
    await nextTick()
    expect(el.textContent).toContain('你好')

    // 2. 结束（store.onDone 的等效动作）：写回 message，复位 streaming 态
    message.content = '你好！我是 CygnusX AI 助手。'
    message.thought = '用户打招呼，应友好回应'
    message.status = 'complete'
    message.tokens = { input: 4208, output: 321, total: 4529 }
    props.isStreaming = false
    props.streamingContent = ''
    props.streamingThought = ''
    await nextTick()

    // 刷新前就应可见正文与 token
    expect(el.textContent).toContain('你好！我是 CygnusX AI 助手。')
    expect(el.textContent).toContain('Tokens:')
  })

  it('后端回填 message_id 后，后续正文帧仍实时更新同一消息气泡', async () => {
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined
    const encoder = new TextEncoder()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller
        },
      }),
    }))

    const store = useAgentHubStore()
    store.availableModels = [{
      id: 'deepseek-model',
      name: 'deepseek-v4-flash',
      model: 'deepseek-v4-flash-ga-260731',
      provider_type: 'openai_compatible',
      is_default: false,
    }]
    store.agents = [{
      id: 'agent-general',
      agent_id: 'agent-general',
      name: '通用助手',
      description: '',
      avatar: '🤖',
      color: '#4f8ef7',
      model_engine: 'qwen3.7-max',
      model_id: 'deepseek-model',
      is_active: true,
      features: {},
    } as unknown as AgentTemplate]
    const session = store.startSessionFromAgent('agent-general')!
    session.title_locked = true
    const sending = store.sendMessage('测试流式正文')
    await nextTick()
    expect(session.messages.at(-1)?.modelName).toBe('deepseek-v4-flash')

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

    const pushFrame = async (frame: Record<string, unknown>) => {
      streamController!.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`))
      await nextTick()
      await new Promise((resolve) => setTimeout(resolve, 0))
    }

    await pushFrame({ type: 'text', content: '正在分析', is_reasoning: true })
    await pushFrame({
      type: 'text',
      content: '第一段正文',
      model: 'qwen3.7-max',
      session_id: 'server-session-id',
      message_id: 'server-message-id',
    })
    await pushFrame({ type: 'text', content: '，第二段正文', model: 'qwen3.7-max' })

    expect(session.messages.at(-1)?.id).toMatch(/^msg-ai-/)
    expect(session.messages.at(-1)?.backendMessageId).toBe('server-message-id')
    expect(el.textContent).toContain('第一段正文，第二段正文')

    await pushFrame({
      type: 'done',
      content: '',
      session_id: 'server-session-id',
      message_id: 'server-message-id',
      usage: { prompt_tokens: 10, completion_tokens: 6, total_tokens: 16 },
    })
    streamController!.close()
    await sending
    await nextTick()

    expect(el.textContent).toContain('第一段正文，第二段正文')
    expect(session.messages.at(-1)?.tokens).toEqual({ input: 10, output: 6, total: 16, cached: 0 })
    app.unmount()
    vi.unstubAllGlobals()
  })
})
