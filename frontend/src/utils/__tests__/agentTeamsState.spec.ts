import { describe, expect, it } from 'vitest'
import type { AgentTeamsEvent } from '@/api/agentTeams'
import { mergeAgentTeamsEvents } from '@/utils/agentTeamsState'

function makeEvent(eventId: string, eventType = 'case.state_changed', recordedAt = '2026-08-12T08:00:00Z'): AgentTeamsEvent {
  return {
    event_id: eventId,
    recorded_at: recordedAt,
    case_id: 'case-1',
    actor: 'bioops-manager',
    event_type: eventType,
    payload: {},
  }
}

describe('mergeAgentTeamsEvents', () => {
  it('merges incoming events without duplicates against current', () => {
    const current = [makeEvent('evt-1'), makeEvent('evt-2')]
    const incoming = [makeEvent('evt-2', 'room.agent_message'), makeEvent('evt-3')]
    const merged = mergeAgentTeamsEvents(current, incoming)
    expect(merged.map((e) => e.event_id)).toEqual(['evt-1', 'evt-2', 'evt-3'])
    expect(merged.find((e) => e.event_id === 'evt-2')?.event_type).toBe('room.agent_message')
  })

  it('deduplicates repeated event_ids within incoming, keeping the last occurrence', () => {
    const current = [makeEvent('evt-1')]
    const incoming = [makeEvent('evt-2'), makeEvent('evt-2', 'room.agent_message'), makeEvent('evt-3')]
    const merged = mergeAgentTeamsEvents(current, incoming)
    expect(merged.map((e) => e.event_id)).toEqual(['evt-1', 'evt-2', 'evt-3'])
    expect(merged.find((e) => e.event_id === 'evt-2')?.event_type).toBe('room.agent_message')
  })

  it('handles empty current and incoming', () => {
    expect(mergeAgentTeamsEvents([], [])).toEqual([])
    expect(mergeAgentTeamsEvents([], [makeEvent('evt-1')]).map((e) => e.event_id)).toEqual(['evt-1'])
  })
})
