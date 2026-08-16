import { describe, expect, it } from 'vitest'
import { sortPersistedChatMessages } from '../chatMessageOrder'

describe('sortPersistedChatMessages', () => {
  it('puts the user request before an assistant reply with the same timestamp', () => {
    const messages = sortPersistedChatMessages([
      { message_id: 'f-response', role: 'assistant', created_at: '2026-08-03T11:30:38.851Z' },
      { message_id: 'a-request', role: 'user', created_at: '2026-08-03T11:30:38.851Z' },
    ])

    expect(messages.map((message) => message.message_id)).toEqual(['a-request', 'f-response'])
  })

  it('keeps distinct timestamps chronological', () => {
    const messages = sortPersistedChatMessages([
      { message_id: 'later', role: 'user', created_at: '2026-08-03T11:31:00.000Z' },
      { message_id: 'earlier', role: 'assistant', created_at: '2026-08-03T11:30:00.000Z' },
    ])

    expect(messages.map((message) => message.message_id)).toEqual(['earlier', 'later'])
  })
})
