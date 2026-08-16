// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { createApp, h } from 'vue'
import { NMessageProvider } from 'naive-ui'
import CollaborationRouteNotice from '../CollaborationRouteNotice.vue'
import type { CollaborationRouteInfo } from '../types'

function mountNotice(route: CollaborationRouteInfo) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  createApp({
    render: () => h(NMessageProvider, null, {
      default: () => h(CollaborationRouteNotice, { route }),
    }),
  }).mount(el)
  return el
}

describe('CollaborationRouteNotice', () => {
  it('uses a quiet, user-facing summary for direct-answer routes', () => {
    const el = mountNotice({
      intent: 'chat',
      label: '直接回答',
      reason: '用户问题缺乏上下文和具体领域信息，需要通用助手先进行追问以补全上下文。',
      confidence: 0.9,
      available: true,
      degraded: false,
      message: '',
    })

    expect(el.textContent).toContain('由通用助手直接回复')
    expect(el.textContent).not.toContain('直接回答')
    expect(el.textContent).not.toContain('已选择')
    expect(el.textContent).not.toContain('缺乏上下文')
  })
})
