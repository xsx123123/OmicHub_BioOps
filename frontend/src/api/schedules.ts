import apiClient from './client'

export interface Schedule {
  id: string
  user_id: string
  workspace_id: string | null
  team_id: string | null
  title: string
  description: string | null
  timezone: string
  start_at: string
  end_at: string | null
  duration_seconds: number
  recurrence_rule: string | null
  next_fire_at: string | null
  last_fired_at: string | null
  status: string
  source: string
  metadata_json: Record<string, unknown>
  version: number
  created_at: string
  updated_at: string
}

export interface Delivery {
  id: string
  schedule_id: string
  occurrence_id: string
  user_id: string
  channel: string
  reminder_offset_minutes: number
  due_at: string
  sent_at: string | null
  status: string
  attempt_count: number
  next_retry_at: string | null
  last_error: string | null
  notification_id: string | null
  created_at: string
  updated_at: string
}

export interface ScheduleCreatePayload {
  title: string
  start_at: string
  timezone?: string
  description?: string | null
  end_at?: string | null
  recurrence_rule?: string | null
  reminder_offsets_minutes?: number[]
  workspace_id?: string | null
  team_id?: string | null
  metadata_json?: Record<string, unknown>
}

export const schedulesApi = {
  async list(status?: string) {
    const response = await apiClient.get<{ items: Schedule[]; total: number }>('/schedules', {
      params: status ? { status } : undefined,
    })
    return response.data
  },
  async create(payload: ScheduleCreatePayload) {
    const response = await apiClient.post<Schedule>('/schedules', payload)
    return response.data
  },
  async update(id: string, payload: Record<string, unknown>) {
    const response = await apiClient.patch<Schedule>(`/schedules/${id}`, payload)
    return response.data
  },
  async cancel(id: string) {
    const response = await apiClient.post<Schedule>(`/schedules/${id}/cancel`)
    return response.data
  },
  async deliveries(id: string) {
    const response = await apiClient.get<Delivery[]>(`/schedules/${id}/deliveries`)
    return response.data
  },
  async snooze(id: string, minutes: number) {
    const response = await apiClient.post<Delivery>(`/reminders/${id}/snooze`, { minutes })
    return response.data
  },
  async complete(id: string) {
    const response = await apiClient.post<Delivery>(`/reminders/${id}/complete`)
    return response.data
  },
}
