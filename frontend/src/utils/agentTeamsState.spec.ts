import { describe, expect, it } from 'vitest'
import type { AgentTeamsEvent } from '@/api/agentTeams'
import {
  formatAgentTeamsArtifactSize,
  mergeAgentTeamsEvents,
  qcVerdictLabel,
  qcVerdictTagType,
  shouldPollAgentTeamsCase,
} from './agentTeamsState'

const event = (eventId: string): AgentTeamsEvent => ({
  event_id: eventId,
  recorded_at: '2026-07-31T12:00:00Z',
  case_id: 'bioops_case',
  actor: 'data-steward',
  event_type: 'skill.finished',
  payload: {},
})

describe('agentTeamsState', () => {
  it('preserves prior events and ignores cursor replay duplicates', () => {
    expect(mergeAgentTeamsEvents([event('one'), event('two')], [event('two'), event('three')]))
      .toEqual([event('one'), event('two'), event('three')])
  })

  it('replaces an optimistic event when the server returns the same event id', () => {
    const optimistic = { ...event('evt-user-1'), payload: { optimistic: true } }
    const persisted = { ...event('evt-user-1'), actor: 'user-a', event_type: 'room.user_message' }

    expect(mergeAgentTeamsEvents([optimistic], [persisted])).toEqual([persisted])
  })

  it('polls only while the browser page is visible', () => {
    expect(shouldPollAgentTeamsCase('visible')).toBe(true)
    expect(shouldPollAgentTeamsCase('hidden')).toBe(false)
  })

  it('maps qc verdicts to tag types with a default fallback', () => {
    expect(qcVerdictTagType('pass')).toBe('success')
    expect(qcVerdictTagType('warn')).toBe('warning')
    expect(qcVerdictTagType('fail')).toBe('error')
    expect(qcVerdictTagType('inconclusive')).toBe('default')
  })

  it('labels qc verdicts in Chinese and keeps unknown values as-is', () => {
    expect(qcVerdictLabel('pass')).toBe('通过')
    expect(qcVerdictLabel('fail')).toBe('失败')
    expect(qcVerdictLabel('custom-verdict')).toBe('custom-verdict')
  })

  it('formats artifact sizes and tolerates invalid input', () => {
    expect(formatAgentTeamsArtifactSize(0)).toBe('0 B')
    expect(formatAgentTeamsArtifactSize(512)).toBe('512 B')
    expect(formatAgentTeamsArtifactSize(2048)).toBe('2.0 KB')
    expect(formatAgentTeamsArtifactSize(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatAgentTeamsArtifactSize(Number.NaN)).toBe('—')
  })
})
