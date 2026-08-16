// @vitest-environment jsdom
import { createApp, h, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import AskUserModal from '@/components/ai-chat/AskUserModal.vue'
import type { AskRequest } from '@/components/ai-chat/types'

const ask: AskRequest = {
  questions: [
    {
      question: '是否按上述方案开始分析？',
      options: ['确认，按上述方案开始分析（推荐）', '调整方案或参数'],
    },
  ],
  answered: false,
}

let app: ReturnType<typeof createApp> | undefined

afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.innerHTML = ''
})

describe('AskUserModal', () => {
  it('shows the structured confirmation request as a modal', async () => {
    const root = document.createElement('div')
    document.body.appendChild(root)
    app = createApp({
      render: () => h(AskUserModal, { show: true, ask }),
    })
    app.mount(root)
    await nextTick()
    await nextTick()

    expect(document.body.textContent).toContain('确认分析方案')
    expect(document.body.textContent).toContain('是否按上述方案开始分析？')
    expect(document.body.textContent).toContain('确认，按上述方案开始分析（推荐）')
  })
})
