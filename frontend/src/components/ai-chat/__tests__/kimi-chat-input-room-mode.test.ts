// @vitest-environment jsdom
/**
 * KimiChatInput roomMode（协作室纯消息场景）发送链路回归测试（jsdom 真实挂载）
 *
 * 背景 bug：P3 复用 KimiChatInput 后，协作室房间内在已有 Case 中按 Enter / 点发送
 * 均无法发出消息。这里以真实挂载 + DOM 事件驱动，验证 roomMode 下
 * Enter 键与发送按钮都能触发 send emit。
 */
import { describe, it, expect, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NDialogProvider, NMessageProvider } from 'naive-ui'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))
const apiClientMocks = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: {} }),
  post: vi.fn().mockResolvedValue({ data: {} }),
}))
vi.mock('@/api/client', () => ({ default: apiClientMocks }))

import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'

function mountComposer(props: Record<string, unknown>, onSend: (...args: unknown[]) => void) {
  setActivePinia(createPinia())
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render() {
      return h(NMessageProvider, null, {
        default: () =>
          h(NDialogProvider, null, {
            default: () =>
              h(KimiChatInput, {
                modelValue: '',
                'onUpdate:modelValue': () => undefined,
                onSend,
                ...props,
              } as never),
          }),
      })
    },
  })
  app.mount(el)
  return { el, app }
}

async function typeText(el: HTMLElement, text: string) {
  const textarea = el.querySelector<HTMLTextAreaElement>('textarea')!
  textarea.value = text
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
  return textarea
}

describe('KimiChatInput roomMode 发送链路', () => {
  it('roomMode 下按 Enter 触发 send emit', async () => {
    const sends: unknown[][] = []
    const { el } = mountComposer({ roomMode: true }, (...args) => sends.push(args))
    await nextTick()
    const textarea = await typeText(el, '帮我做一下系统发育树呀')
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await nextTick()
    expect(sends.length).toBe(1)
    expect(sends[0][0]).toBe('帮我做一下系统发育树呀')
  })

  it('roomMode 下点击发送按钮触发 send emit', async () => {
    const sends: unknown[][] = []
    const { el } = mountComposer({ roomMode: true }, (...args) => sends.push(args))
    await nextTick()
    await typeText(el, '@workspace/chat-uploads/a.treefile 帮我做一下系统发育树呀')
    const btn = el.querySelector<HTMLButtonElement>('.send-btn')!
    expect(btn.disabled).toBe(false)
    btn.click()
    await nextTick()
    expect(sends.length).toBe(1)
  })

  it('roomMode 下输入框中的 @ 文件引用会渲染为高亮 pill', async () => {
    const { el } = mountComposer({ roomMode: true }, () => undefined)
    await nextTick()
    await typeText(el, '@workspace/chat-uploads/a.treefile 帮我可视化')
    const highlight = el.querySelector<HTMLElement>('.input-highlight')
    expect(highlight).not.toBeNull()
    expect(highlight!.innerHTML).toContain('mention-chip')
    expect(highlight!.textContent).toContain('@workspace/chat-uploads/a.treefile')
  })
})
