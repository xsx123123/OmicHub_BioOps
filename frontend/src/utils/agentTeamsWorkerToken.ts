export interface AgentTeamsWorkerTokenRecord {
  token_id: string
  identity: string
  note: string
  created_at: string
  expires_at?: string | null
  revoked_at?: string | null
}

export type WorkerTokenStatus = 'active' | 'expired' | 'revoked'

export function resolveWorkerTokenStatus(
  record: Pick<AgentTeamsWorkerTokenRecord, 'expires_at' | 'revoked_at'>,
  now: Date = new Date(),
): WorkerTokenStatus {
  if (record.revoked_at) return 'revoked'
  if (record.expires_at && new Date(record.expires_at).getTime() <= now.getTime()) return 'expired'
  return 'active'
}

export const WORKER_TOKEN_STATUS_MAP: Record<
  WorkerTokenStatus,
  { label: string; type: 'success' | 'warning' | 'error' }
> = {
  active: { label: '有效', type: 'success' },
  expired: { label: '已过期', type: 'warning' },
  revoked: { label: '已吊销', type: 'error' },
}
