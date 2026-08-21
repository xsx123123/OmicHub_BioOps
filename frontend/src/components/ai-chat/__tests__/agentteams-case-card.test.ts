// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'
import AgentTeamsCaseCard from '../AgentTeamsCaseCard.vue'

vi.mock('@/api/agentTeams', () => ({
  agentTeamsApi: {
    getCase: vi.fn(),
    getEvents: vi.fn().mockResolvedValue({ events: [] }),
    getCapabilityCheck: vi.fn().mockResolvedValue({ flow_id: null, available: true, stages: [] }),
  },
}))

describe('AgentTeamsCaseCard', () => {
  it('renders the shared stage label and approval action rail', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agent-teams/cases/:id', component: { template: '<div />' } }],
    })
    const host = document.createElement('div')
    const app = createApp({
      render: () => h(AgentTeamsCaseCard, {
        caseInfo: {
          case_id: 'case-1',
          title: 'RNA-seq 全流程交付',
          status: 'approval_pending',
          next_actor: '审批人',
          case_url: '/agent-teams/cases/case-1',
        },
      }),
    })
    app.use(pinia)
    app.use(router)
    app.mount(host)

    expect(host.textContent).toContain(formatAgentTeamsStatus('approval_pending'))
    expect(host.textContent).toContain('审批待处理')
    expect(host.textContent).toContain('打开 Case')

    app.unmount()
  })

  it('renders a real retry action for execution failures', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agent-teams/cases/:id', component: { template: '<div />' } }],
    })
    const host = document.createElement('div')
    const app = createApp({
      render: () => h(AgentTeamsCaseCard, {
        caseInfo: {
          case_id: 'case-failed',
          title: 'RNA-seq 全流程交付',
          status: 'execution_failed',
          next_actor: '流程执行者',
          case_url: '/agent-teams/cases/case-failed',
        },
      }),
    })
    app.use(pinia)
    app.use(router)
    app.mount(host)

    expect(host.textContent).toContain('按冻结计划重试')
    expect(host.textContent).toContain('新的提交版本')

    app.unmount()
  })

  it('makes an unassigned received Case explicit', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/agent-teams/cases/:id', component: { template: '<div />' } }],
    })
    const host = document.createElement('div')
    const app = createApp({
      render: () => h(AgentTeamsCaseCard, {
        caseInfo: {
          case_id: 'case-received',
          title: '等待规划的分析 Case',
          status: 'received',
          next_actor: '协作团队',
          case_url: '/agent-teams/cases/case-received',
        },
      }),
    })
    app.use(pinia)
    app.use(router)
    app.mount(host)

    expect(host.textContent).toContain('尚未派发')
    expect(host.textContent).toContain('等待规划或人工确认')

    app.unmount()
  })
})
