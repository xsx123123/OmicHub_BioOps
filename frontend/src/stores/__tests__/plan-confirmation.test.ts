import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentHubStore } from '@/stores/agentHub'

const chatApiMocks = vi.hoisted(() => ({
  decideOverdrivePlan: vi.fn().mockResolvedValue({ status: 'SERIAL_PREFLIGHT' }),
}))

vi.mock('@/api/chat', () => ({ chatApi: chatApiMocks }))

describe('agentHub 计划确认决策', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    chatApiMocks.decideOverdrivePlan.mockClear()
  })

  it('提交冻结版本与 hash，并将卡片落为已确认状态', async () => {
    const store = useAgentHubStore()
    store.sessions.push({
      id: 'session-1',
      title: '超频任务',
      agent_id: 'agent-general',
      overdrive: true,
      messages: [{
        id: 'plan-card',
        role: 'system',
        content: '',
        createdAt: '2026-08-09T00:00:00Z',
        askRequest: {
          kind: 'plan_confirmation',
          questions: [],
          answered: false,
          planConfirmation: {
            runId: 'run-1',
            title: '执行计划',
            summary: '',
            planPath: 'output/plan.md',
            planVersion: 2,
            planHash: `sha256:${'a'.repeat(64)}`,
            waveCount: 1,
            agents: [],
            serialPreflight: [],
            risks: [],
            approvalPoints: [],
            deliverables: [],
            actions: ['approve', 'revise', 'cancel'],
            status: 'pending',
          },
        },
      }, {
        id: 'overdrive-progress-run-1',
        role: 'system',
        content: '规划 Agent 已交付 plan.md，等待你确认',
        createdAt: '2026-08-09T00:00:01Z',
        overdriveProgress: {
          runId: 'run-1', phase: 'plan_ready', label: '规划 Agent 已交付 plan.md，等待你确认',
          completed: 3, total: 3,
        },
      }],
      created_at: '2026-08-09T00:00:00Z',
      updated_at: '2026-08-09T00:00:00Z',
    })
    store.currentSessionId = 'session-1'

    await store.decideOverdrivePlan('run-1', 'approve')

    expect(chatApiMocks.decideOverdrivePlan).toHaveBeenCalledWith(
      'session-1',
      'run-1',
      expect.objectContaining({
        action: 'approve',
        planVersion: 2,
        planHash: `sha256:${'a'.repeat(64)}`,
      }),
    )
    const ask = store.sessions[0].messages[0].askRequest
    expect(ask?.answered).toBe(true)
    expect(ask?.planConfirmation?.status).toBe('approved')
  })

  it('取消后立即把同一 run 的进度卡落为已终止', async () => {
    const store = useAgentHubStore()
    store.sessions.push({
      id: 'session-1', title: '超频任务', agent_id: 'agent-general', overdrive: true,
      messages: [{
        id: 'plan-card', role: 'system', content: '', createdAt: '2026-08-09T00:00:00Z',
        askRequest: {
          kind: 'plan_confirmation', questions: [], answered: false,
          planConfirmation: {
            runId: 'run-1', title: '执行计划', summary: '', planPath: 'output/plan.md',
            planVersion: 2, planHash: `sha256:${'a'.repeat(64)}`, waveCount: 1,
            agents: [], serialPreflight: [], risks: [], approvalPoints: [], deliverables: [],
            actions: ['approve', 'revise', 'cancel'], status: 'pending',
          },
        },
      }, {
        id: 'overdrive-progress-run-1', role: 'system', content: '', createdAt: '2026-08-09T00:00:01Z',
        overdriveProgress: {
          runId: 'run-1', phase: 'plan_ready', label: '规划 Agent 已交付 plan.md，等待你确认',
          completed: 3, total: 3,
        },
      }],
      created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
    })
    store.currentSessionId = 'session-1'

    await store.decideOverdrivePlan('run-1', 'cancel')

    const progress = store.sessions[0].messages[1].overdriveProgress
    expect(progress).toMatchObject({
      phase: 'terminated', completed: 0, total: 0, readonly: true,
      label: '用户已取消本轮超频协作，计划不会执行',
    })
    expect(progress?.warning).toContain('专家协作与结论交付均未开始')
  })
})
