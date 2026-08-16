// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import { afterEach, describe, expect, it } from 'vitest'
import OverdriveProgressCard from '../OverdriveProgressCard.vue'

describe('OverdriveProgressCard', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('collapses tall details into only a progress bar and expand button', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp({
      components: { NMessageProvider, OverdriveProgressCard },
      template: `
        <NMessageProvider>
          <OverdriveProgressCard :progress="progress" />
        </NMessageProvider>
      `,
      data: () => ({
        progress: {
          phase: 'worker_running',
          label: '正在执行 TP53 单细胞免疫耐受分析方案',
          completed: 1,
          total: 3,
          wave: 2,
          waveTotal: 3,
          waveMode: 'serial',
          activities: [{ id: 'research', label: '文献检索', status: 'completed' }],
          tasks: [{ taskId: 'scrna-immune-tolerance', agentId: 'agent-scrna-advanced', status: 'running' }],
        },
      }),
    })
    app.use(createPinia())
    app.mount(host)

    expect(host.textContent).toContain('正在执行 TP53 单细胞免疫耐受分析方案')
    host.querySelector<HTMLButtonElement>('button[aria-label="收起超频协作详情"]')?.click()
    await nextTick()

    expect(host.textContent).not.toContain('正在执行 TP53 单细胞免疫耐受分析方案')
    expect(host.textContent).not.toContain('文献检索')
    expect(host.querySelector('.overdrive-progress-card__collapsed-progress .n-progress')).not.toBeNull()
    expect(host.querySelector('button[aria-label="展开超频协作详情"]')).not.toBeNull()
    expect(host.querySelectorAll('.overdrive-progress-card__collapsed-progress button')).toHaveLength(1)

    app.unmount()
  })

  it('does not mark the expert step green for completed planning-only runs', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp({
      components: { NMessageProvider, OverdriveProgressCard },
      template: `
        <NMessageProvider>
          <OverdriveProgressCard :progress="progress" />
        </NMessageProvider>
      `,
      data: () => ({
        progress: {
          phase: 'completed',
          label: '方案已生成并完成交付',
          completed: 0,
          total: 0,
          planningOnly: true,
          tasks: [],
        },
      }),
    })
    app.use(createPinia())
    app.mount(host)

    const steps = host.querySelectorAll('.overdrive-progress-card__steps span')
    expect(steps).toHaveLength(3)
    expect(steps[0].className).toContain('is-complete')
    expect(steps[1].className).not.toContain('is-complete')
    expect(steps[2].className).toContain('is-complete')

    app.unmount()
  })
})
