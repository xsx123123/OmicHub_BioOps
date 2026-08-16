import { describe, expect, it } from 'vitest'

import { resolveWorkerTokenStatus } from '../agentTeamsWorkerToken'

describe('resolveWorkerTokenStatus', () => {
  const now = new Date('2026-08-12T12:00:00Z')

  it('returns active when neither revoked nor expired', () => {
    expect(resolveWorkerTokenStatus({ revoked_at: null, expires_at: null }, now)).toBe('active')
    expect(
      resolveWorkerTokenStatus({ revoked_at: null, expires_at: '2026-08-13T00:00:00Z' }, now),
    ).toBe('active')
  })

  it('returns expired when expires_at is in the past', () => {
    expect(
      resolveWorkerTokenStatus({ revoked_at: null, expires_at: '2026-08-12T11:59:59Z' }, now),
    ).toBe('expired')
    expect(
      resolveWorkerTokenStatus({ revoked_at: null, expires_at: '2026-08-12T12:00:00Z' }, now),
    ).toBe('expired')
  })

  it('returns revoked even when the token also expired', () => {
    expect(
      resolveWorkerTokenStatus(
        { revoked_at: '2026-08-12T10:00:00Z', expires_at: '2026-08-12T11:00:00Z' },
        now,
      ),
    ).toBe('revoked')
    expect(
      resolveWorkerTokenStatus({ revoked_at: '2026-08-12T10:00:00Z', expires_at: null }, now),
    ).toBe('revoked')
  })
})
