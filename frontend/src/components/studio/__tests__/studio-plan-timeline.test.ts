// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import StudioPlanTimeline from '@/components/studio/StudioPlanTimeline.vue'
import type { StudioPlanStep } from '@/api/studio'

let cleanup: (() => void) | undefined

afterEach(() => cleanup?.())

function mountTimeline(initialSteps: StudioPlanStep[]) {
  const steps = ref(initialSteps)
  const root = document.createElement('div')
  document.body.appendChild(root)
  const app = createApp({
    render: () => h(StudioPlanTimeline, { steps: steps.value }),
  })
  app.mount(root)
  cleanup = () => { app.unmount(); root.remove() }
  return { root, steps }
}

describe('StudioPlanTimeline', () => {
  it('折叠态显示进度摘要，点击标题可展开', async () => {
    const { root } = mountTimeline([
      { title: '检查输入', status: 'done' },
      { title: '执行分析', status: 'in_progress' },
      { title: '整理结果', status: 'pending' },
    ])

    const heading = root.querySelector<HTMLButtonElement>('.timeline-heading')
    expect(heading?.getAttribute('aria-expanded')).toBe('true')
    expect(root.textContent).toContain('1/3')
    heading?.click()
    await nextTick()
    expect(heading?.getAttribute('aria-expanded')).toBe('false')
    expect(root.textContent).toContain('已完成 1/3')
  })

  it('计划全部完成后自动折叠，手动展开后不再次自动收起', async () => {
    const { root, steps } = mountTimeline([
      { title: '检查输入', status: 'in_progress' },
      { title: '执行分析', status: 'pending' },
    ])
    const heading = () => root.querySelector<HTMLButtonElement>('.timeline-heading')

    steps.value = [
      { title: '检查输入', status: 'done' },
      { title: '执行分析', status: 'done' },
    ]
    await nextTick()
    expect(heading()?.getAttribute('aria-expanded')).toBe('false')

    heading()?.click()
    await nextTick()
    expect(heading()?.getAttribute('aria-expanded')).toBe('true')

    steps.value = [
      { title: '检查输入', status: 'done' },
      { title: '执行分析', status: 'done' },
    ]
    await nextTick()
    expect(heading()?.getAttribute('aria-expanded')).toBe('true')
  })
})
