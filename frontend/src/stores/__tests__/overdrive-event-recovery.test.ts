import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiClientMocks = vi.hoisted(() => ({ get: vi.fn() }))
const chatApiMocks = vi.hoisted(() => ({
  getActiveOverdriveRun: vi.fn(),
  getLatestOverdriveRun: vi.fn(),
}))

vi.mock('@/api/client', () => ({ default: apiClientMocks }))
vi.mock('@/api/chat', () => ({ chatApi: chatApiMocks }))

import { useAgentHubStore } from '@/stores/agentHub'

describe('agentHub 超频 DB 事件恢复', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiClientMocks.get.mockReset()
    chatApiMocks.getActiveOverdriveRun.mockReset()
    chatApiMocks.getLatestOverdriveRun.mockReset()
    chatApiMocks.getLatestOverdriveRun.mockResolvedValue(null)
  })

  it('以 run/sequence 确定性去重，并拒绝投影到其他会话', async () => {
    chatApiMocks.getActiveOverdriveRun.mockResolvedValue({
      run_id: 'run-a',
      status: 'AWAITING_PLAN_CONFIRMATION',
      event_cursor: 4,
      plan: {
        path: 'output/overdrive/session-a/run-a/plan.md',
        version: 1,
        hash: `sha256:${'a'.repeat(64)}`,
        summary: { title: '执行计划', wave_count: 1 },
        actions: ['approve', 'revise', 'cancel'],
      },
    })
    const planEvent = {
      type: 'ask_request',
      kind: 'plan_confirmation',
      run_id: 'run-a',
      session_id: 'session-a',
      sequence: 1,
      plan_path: 'output/overdrive/session-a/run-a/plan.md',
      plan_version: 1,
      plan_hash: `sha256:${'a'.repeat(64)}`,
      summary: { title: '执行计划', wave_count: 1 },
      actions: ['approve', 'revise', 'cancel'],
    }
    const progressEvent = {
      type: 'overdrive_progress',
      run_id: 'run-a',
      session_id: 'session-a',
      sequence: 2,
      phase: 'worker_running',
      label: '执行助手正在工作',
      completed: 0,
      total: 1,
    }
    const speechEvent = {
      type: 'room_speech',
      run_id: 'run-a',
      session_id: 'session-a',
      sequence: 3,
      message_id: 'overdrive-event-run-a-3',
      content: '助手任务已回流。',
      sender: { agent_id: 'assistant-a', name: '执行助手', role: 'worker' },
    }
    apiClientMocks.get.mockResolvedValue({
      data: {
        event_cursor: 4,
        run: { status: 'COMPLETED' },
        projected_events: [
          planEvent,
          planEvent,
          progressEvent,
          progressEvent,
          speechEvent,
          speechEvent,
          { ...progressEvent, sequence: 4, session_id: 'session-b', label: '错误会话事件' },
        ],
      },
    })

    const store = useAgentHubStore()
    store.sessions.push(
      {
        id: 'session-a',
        title: 'A',
        agent_id: 'agent-general',
        messages: [{ id: 'seed-a', role: 'user', content: '任务 A', createdAt: '2026-08-09T00:00:00Z' }],
        created_at: '2026-08-09T00:00:00Z',
        updated_at: '2026-08-09T00:00:00Z',
      },
      {
        id: 'session-b',
        title: 'B',
        agent_id: 'agent-general',
        messages: [{ id: 'seed-b', role: 'user', content: '任务 B', createdAt: '2026-08-09T00:00:00Z' }],
        created_at: '2026-08-09T00:00:00Z',
        updated_at: '2026-08-09T00:00:00Z',
      },
    )

    await store.selectSession('session-a')
    await vi.waitFor(() => expect(apiClientMocks.get).toHaveBeenCalled())
    await vi.waitFor(() => {
      const sessionA = store.sessions.find((session) => session.id === 'session-a')!
      expect(sessionA.messages.some((message) => message.senderAgent)).toBe(true)
    })

    const sessionA = store.sessions.find((session) => session.id === 'session-a')!
    const sessionB = store.sessions.find((session) => session.id === 'session-b')!
    expect(sessionA.messages.filter((message) => message.askRequest?.planConfirmation?.runId === 'run-a')).toHaveLength(1)
    expect(sessionA.messages.filter((message) => message.overdriveProgress?.runId === 'run-a')).toHaveLength(1)
    expect(sessionA.messages.filter((message) => message.id === 'overdrive-event-run-a-3')).toHaveLength(1)
    expect(sessionA.messages.find((message) => message.overdriveProgress?.runId === 'run-a')?.id)
      .toBe('overdrive-progress-run-a')
    expect(sessionA.messages.some((message) => message.content === '错误会话事件')).toBe(false)
    expect(sessionB.messages).toHaveLength(1)
  })

  it('重放旧计划不会把已提出修改的卡片恢复为待确认', async () => {
    chatApiMocks.getActiveOverdriveRun.mockResolvedValue({
      run_id: 'run-revision',
      status: 'REPLANNING',
      event_cursor: 3,
      plan: { version: 1 },
    })
    apiClientMocks.get.mockResolvedValue({
      data: {
        event_cursor: 3,
        run: { status: 'AWAITING_PLAN_CONFIRMATION' },
        projected_events: [
          {
            type: 'ask_request', kind: 'plan_confirmation', run_id: 'run-revision',
            session_id: 'session-revision', sequence: 1,
            plan_path: 'output/plan.v1.md', plan_version: 1,
            plan_hash: `sha256:${'a'.repeat(64)}`,
            summary: { title: '旧计划' }, actions: ['approve', 'revise', 'cancel'],
          },
          {
            type: 'ask_request', kind: 'plan_confirmation', run_id: 'run-revision',
            session_id: 'session-revision', sequence: 3,
            plan_path: 'output/plan.v2.md', plan_version: 2,
            plan_hash: `sha256:${'b'.repeat(64)}`,
            summary: { title: '新计划' }, actions: ['approve', 'revise', 'cancel'],
          },
        ],
      },
    })
    const store = useAgentHubStore()
    store.sessions.push({
      id: 'session-revision', title: '修订', agent_id: 'agent-general',
      messages: [{
        id: 'plan-card', role: 'system', content: '', createdAt: '2026-08-09T00:00:00Z',
        askRequest: {
          kind: 'plan_confirmation', questions: [], answered: true,
          planConfirmation: {
            runId: 'run-revision', title: '旧计划', summary: '', planPath: 'output/plan.v1.md',
            planVersion: 1, planHash: `sha256:${'a'.repeat(64)}`, waveCount: 1,
            agents: [], serialPreflight: [], risks: [], approvalPoints: [], deliverables: [],
            actions: ['approve', 'revise', 'cancel'], status: 'revision_requested',
          },
        },
      }],
      created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
    })

    await store.selectSession('session-revision')
    await vi.waitFor(() => {
      const plan = store.sessions[0].messages[0].askRequest?.planConfirmation
      expect(plan?.planVersion).toBe(2)
      expect(plan?.status).toBe('pending')
      expect(plan?.title).toBe('新计划')
    })
  })

  it('活动 run 已结束时仍按已知 runId 重放取消状态', async () => {
    chatApiMocks.getActiveOverdriveRun.mockResolvedValue(null)
    apiClientMocks.get.mockResolvedValue({
      data: {
        event_cursor: 4,
        run: { status: 'CANCELLED' },
        projected_events: [{
          type: 'overdrive_progress', run_id: 'run-cancelled', session_id: 'session-cancelled',
          sequence: 4, phase: 'terminated', label: '用户已取消本轮超频协作，计划不会执行',
        }],
      },
    })
    const store = useAgentHubStore()
    store.sessions.push({
      id: 'session-cancelled', title: '已取消', agent_id: 'agent-general',
      messages: [{
        id: 'plan-card', role: 'system', content: '', createdAt: '2026-08-09T00:00:00Z',
        askRequest: {
          kind: 'plan_confirmation', questions: [], answered: false,
          planConfirmation: {
            runId: 'run-cancelled', title: '旧计划', summary: '', planPath: 'output/plan.md',
            planVersion: 1, planHash: `sha256:${'a'.repeat(64)}`, waveCount: 1,
            agents: [], serialPreflight: [], risks: [], approvalPoints: [], deliverables: [],
            actions: ['approve', 'revise', 'cancel'], status: 'pending',
          },
        },
      }],
      created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
    })

    await store.selectSession('session-cancelled')
    await vi.waitFor(() => {
      const messages = store.sessions[0].messages
      expect(messages.find((message) => message.overdriveProgress?.runId === 'run-cancelled')
        ?.overdriveProgress?.phase).toBe('terminated')
    })
    expect(store.sessions[0].messages[0].askRequest?.planConfirmation?.status).toBe('cancelled')
    expect(store.sessions[0].messages[0].askRequest?.answered).toBe(true)
  })

  it('冷启动进入终态会话时从 latest run 重建全部超频卡片', async () => {
    chatApiMocks.getActiveOverdriveRun.mockResolvedValue(null)
    chatApiMocks.getLatestOverdriveRun.mockResolvedValue({
      run_id: 'run-completed',
      status: 'COMPLETED',
      event_cursor: 4,
      plan: { version: 1 },
    })
    const replayPayload = {
      data: {
        event_cursor: 4,
        run: { status: 'COMPLETED' },
        projected_events: [
          {
            type: 'ask_request', kind: 'plan_confirmation', run_id: 'run-completed',
            session_id: 'session-completed', sequence: 1,
            plan_path: 'output/plan.md', plan_version: 1,
            plan_hash: `sha256:${'a'.repeat(64)}`,
            summary: { title: 'TnpD 进化分析计划' }, actions: ['approve', 'revise', 'cancel'],
          },
          {
            type: 'overdrive_progress', run_id: 'run-completed',
            session_id: 'session-completed', sequence: 2,
            phase: 'worker_running', label: '执行中', completed: 1, total: 2,
          },
          {
            type: 'overdrive_progress', run_id: 'run-completed',
            session_id: 'session-completed', sequence: 4,
            phase: 'completed', label: '超频协作已完成', completed: 2, total: 2,
          },
        ],
      },
    }
    apiClientMocks.get.mockImplementation((url: string) => {
      if (url.endsWith('/messages')) {
        return Promise.resolve({
          data: [{
            message_id: 'persisted-text', role: 'assistant', content: '已有文本消息',
            metadata_json: {}, created_at: '2026-08-11T00:00:00Z',
          }],
        })
      }
      return Promise.resolve(replayPayload)
    })
    const store = useAgentHubStore()
    store.sessions.push({
      id: 'session-completed', title: '终态冷启动', agent_id: 'agent-general',
      messages: [],
      created_at: '2026-08-11T00:00:00Z', updated_at: '2026-08-11T00:00:00Z',
    })

    await store.selectSession('session-completed')
    await vi.waitFor(() => {
      const messages = store.sessions[0].messages
      expect(messages.some((message) => message.id === 'persisted-text')).toBe(true)
      expect(messages.some((message) =>
        message.askRequest?.planConfirmation?.runId === 'run-completed')).toBe(true)
      expect(messages.find((message) => message.overdriveProgress?.runId === 'run-completed')
        ?.overdriveProgress?.phase).toBe('completed')
    })
  })
})
