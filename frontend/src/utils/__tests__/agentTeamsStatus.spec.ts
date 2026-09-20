import { describe, expect, it, vi } from 'vitest'
import {
  agentTeamsCaseCategory,
  buildAgentTeamsStageView,
  agentTeamsCaseStageMap,
  agentTeamsFailedStatuses,
  canSendRoomMessage,
  formatAgentTeamsStatus,
} from '@/utils/agentTeamsStatus'
import type { AgentTeamsCaseStatus } from '@/api/agentTeams'

describe('agentTeamsCaseStageMap', () => {
  it('covers every case status exactly once', () => {
    const statuses = Object.keys(agentTeamsCaseStageMap) as AgentTeamsCaseStatus[]
    expect(statuses).toHaveLength(17)
  })

  it('maps statuses onto the five stages of the case lifecycle', () => {
    expect(agentTeamsCaseStageMap.planning_running).toBe('plan')
    expect(agentTeamsCaseStageMap.preflight_blocked).toBe('plan')
    expect(agentTeamsCaseStageMap.approval_pending).toBe('approval')
    expect(agentTeamsCaseStageMap.executing).toBe('execution')
    expect(agentTeamsCaseStageMap.execution_failed).toBe('execution')
    expect(agentTeamsCaseStageMap.quality_running).toBe('quality')
    expect(agentTeamsCaseStageMap.delivery_ready).toBe('delivery')
    expect(agentTeamsCaseStageMap.closed).toBe('delivery')
  })
})

describe('agentTeamsCaseCategory', () => {
  it('groups statuses into sidebar filter chips', () => {
    expect(agentTeamsCaseCategory('approval_pending')).toBe('approval')
    expect(agentTeamsCaseCategory('delivery_ready')).toBe('done')
    expect(agentTeamsCaseCategory('closed')).toBe('done')
    expect(agentTeamsCaseCategory('execution_failed')).toBe('failed')
    expect(agentTeamsCaseCategory('cancelled')).toBe('failed')
    expect(agentTeamsCaseCategory('executing')).toBe('active')
    expect(agentTeamsCaseCategory('queued')).toBe('active')
  })

  it('keeps failed statuses inside the failed category', () => {
    for (const status of agentTeamsFailedStatuses) {
      expect(agentTeamsCaseCategory(status)).toBe('failed')
    }
  })
})

describe('canSendRoomMessage', () => {
  it('allows sending while the case is not terminal', () => {
    expect(canSendRoomMessage('executing')).toBe(true)
    expect(canSendRoomMessage('approval_pending')).toBe(true)
    expect(canSendRoomMessage('delivery_ready')).toBe(true)
  })

  it('allows sending for terminal cases too (post-cancel/close follow-up)', () => {
    expect(canSendRoomMessage('closed')).toBe(true)
    expect(canSendRoomMessage('cancelled')).toBe(true)
  })

  it('blocks sending only when no case is selected', () => {
    expect(canSendRoomMessage('')).toBe(false)
    expect(canSendRoomMessage(null)).toBe(false)
    expect(canSendRoomMessage(undefined)).toBe(false)
  })
})

describe('formatAgentTeamsStatus', () => {
  it('returns plain Chinese label for simple statuses', () => {
    expect(formatAgentTeamsStatus('planning_running')).toBe('规划中')
    expect(formatAgentTeamsStatus('executing')).toBe('执行中')
  })

  it('parameterizes waiting_for_correction with attempt/max_attempts', () => {
    expect(formatAgentTeamsStatus('waiting_for_correction', { attempt: 1, max_attempts: 3 }))
      .toBe('自动修正中（第 1/3 次）')
  })

  it('falls back to waiting_for_correction base text without payload', () => {
    expect(formatAgentTeamsStatus('waiting_for_correction')).toBe('等待修正')
  })

  it('formats planning_failed as terminal failure', () => {
    expect(formatAgentTeamsStatus('planning_failed')).toBe('规划失败')
  })

  it('warns in dev and returns a fallback for unknown statuses', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(formatAgentTeamsStatus('unknown_status_xyz')).toBe('未知状态（unknown_status_xyz）')
    expect(errorSpy).toHaveBeenCalledWith('[AgentTeams] 缺失状态文案映射：unknown_status_xyz')
    errorSpy.mockRestore()
  })
})

describe('buildAgentTeamsStageView', () => {
  it('returns null without a case status so the stage bar stays hidden for case-less rooms', () => {
    expect(buildAgentTeamsStageView(undefined)).toBeNull()
    expect(buildAgentTeamsStageView(null)).toBeNull()
    expect(buildAgentTeamsStageView('')).toBeNull()
  })

  it('marks the current stage from the status mapping', () => {
    const view = buildAgentTeamsStageView('executing')
    expect(view).toHaveLength(5)
    expect(view?.map((stage) => stage.state)).toEqual(['done', 'done', 'current', 'todo', 'todo'])
  })

  it('keeps all stages inactive for pre-start statuses', () => {
    expect(buildAgentTeamsStageView('queued')?.every((stage) => stage.state === 'todo')).toBe(true)
    expect(buildAgentTeamsStageView('received')?.every((stage) => stage.state === 'todo')).toBe(true)
  })

  it('marks failed stages and treats closed as fully done', () => {
    expect(buildAgentTeamsStageView('execution_failed')?.[2].state).toBe('failed')
    expect(buildAgentTeamsStageView('closed')?.every((stage) => stage.state === 'done')).toBe(true)
    expect(buildAgentTeamsStageView('cancelled')?.every((stage) => stage.state === 'todo')).toBe(true)
  })
})
