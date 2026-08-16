// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import AiLoading from '@/components/ai-chat/AiLoading.vue'

describe('AiLoading', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('按 0/2/5/10 秒阶段轮换文案与动画', async () => {
    const el = document.createElement('div')
    const app = createApp({ render: () => h(AiLoading) })
    app.mount(el)

    expect(el.querySelector('.ai-loading')?.getAttribute('aria-label')).toContain('星尘正在穿越神经网络')
    expect(el.querySelector('.typing-dots')).not.toBeNull()

    vi.advanceTimersByTime(2250)
    await nextTick()
    expect(el.querySelector('.ai-loading')?.getAttribute('aria-label')).toContain('正在理解你的问题')
    expect(el.querySelector('.shimmer-bars')).not.toBeNull()

    vi.advanceTimersByTime(3000)
    await nextTick()
    expect(el.querySelector('.ai-loading')?.getAttribute('aria-label')).toContain('正在检索工作区数据')
    expect(el.querySelector('.pulse-orbit')).not.toBeNull()

    vi.advanceTimersByTime(5000)
    await nextTick()
    expect(el.querySelector('.ai-loading')?.getAttribute('aria-label')).toContain('内容较多，正在努力生成')
    expect(el.querySelector('.typewriter-placeholder')).not.toBeNull()

    app.unmount()
  })
})
