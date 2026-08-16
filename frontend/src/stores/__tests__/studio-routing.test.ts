import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { AgentTemplate } from '@/types/agent'
import { useAgentHubStore } from '@/stores/agentHub'

describe('星尘 AI 工作台路由', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('为路由到默认 Studio Agent 的聊天会话排队工作台跳转', () => {
    const store = useAgentHubStore()
    store.agents = [
      { id: 'agent-router', agent_id: 'agent-router', name: '星尘 AI', is_active: true },
      {
        id: 'agent-viz',
        agent_id: 'agent-viz',
        name: '可视化助手',
        is_active: true,
        features: { studio: { default_mode: 'studio' } },
      },
      {
        id: 'agent-general',
        agent_id: 'agent-general',
        name: '通用助手',
        is_active: true,
        features: { studio: { default_mode: 'studio' } },
      },
    ] as unknown as AgentTemplate[]
    store.startSessionFromAgent('agent-router')

    store.maybeRedirectToStudio('agent-general', '通用助手')
    expect(store.studioRedirect).toEqual({ agentId: 'agent-general', agentName: '通用助手' })

    store.clearStudioRedirect()

    store.maybeRedirectToStudio('agent-viz', '可视化助手')
    expect(store.studioRedirect).toEqual({ agentId: 'agent-viz', agentName: '可视化助手' })
  })
})
