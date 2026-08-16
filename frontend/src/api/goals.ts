import apiClient from './client'

export type GoalStatus =
  | 'draft'
  | 'in_progress'
  | 'waiting_user'
  | 'waiting_external'
  | 'paused'
  | 'completed'
  | 'blocked'
  | 'cancelled'
  | 'failed'

export interface GoalRuntimeGoal {
  id: string
  session_id: string | null
  user_id: string
  manager_agent_id: string
  objective: string
  success_criteria: unknown[]
  mode: string
  permission: string
  status: GoalStatus
  plan_snapshot: Record<string, unknown>
  turn_count: number
  max_turns: number
  token_budget: number | null
  tokens_used: number
  deadline_at: string | null
  version: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface GoalEvent {
  id: string
  goal_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface GoalStartPayload {
  objective: string
  session_id: string
  manager_agent_id?: string
  success_criteria?: unknown[]
  mode?: 'chat'
  permission?: 'safe'
  max_turns?: number
  token_budget?: number
  deadline_at?: string
}

function goalStreamUrl(goalId: string, after: number): string {
  return `/api/v1/goals/${encodeURIComponent(goalId)}/events/stream?after=${after}`
}

function parseEventFrames(buffer: string, onEvent: (event: GoalEvent) => void): string {
  const frames = buffer.split(/\r?\n\r?\n/)
  const remainder = frames.pop() || ''
  for (const frame of frames) {
    const data = frame
      .split(/\r?\n/)
      .find((line) => line.startsWith('data: '))
      ?.slice(6)
    if (!data) continue
    try {
      onEvent(JSON.parse(data) as GoalEvent)
    } catch {
      // Keep the event stream alive if an individual payload is malformed.
    }
  }
  return remainder
}

export const goalsApi = {
  async start(payload: GoalStartPayload): Promise<GoalRuntimeGoal> {
    const response = await apiClient.post<GoalRuntimeGoal>('/goals/start', payload)
    return response.data
  },

  async list(sessionId?: string): Promise<GoalRuntimeGoal[]> {
    const response = await apiClient.get<GoalRuntimeGoal[]>('/goals', {
      params: sessionId ? { session_id: sessionId } : undefined,
    })
    return response.data
  },

  async get(goalId: string): Promise<GoalRuntimeGoal> {
    const response = await apiClient.get<GoalRuntimeGoal>(`/goals/${goalId}`)
    return response.data
  },

  async control(goalId: string, action: 'pause' | 'resume' | 'cancel', reason = ''): Promise<GoalRuntimeGoal> {
    const response = await apiClient.post<GoalRuntimeGoal>(`/goals/${goalId}/${action}`, { reason })
    return response.data
  },

  async streamEvents(
    goalId: string,
    after: number,
    onEvent: (event: GoalEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const token = localStorage.getItem('access_token')
    const response = await fetch(goalStreamUrl(goalId, after), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      signal,
    })
    if (!response.ok || !response.body) throw new Error('Goal 实时状态连接失败')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer = parseEventFrames(buffer + decoder.decode(value, { stream: true }), onEvent)
      }
    } finally {
      reader.releaseLock()
    }
  },
}
