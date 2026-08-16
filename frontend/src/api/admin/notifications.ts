import apiClient from '../client'
import type { Notification } from '@/types'

/** 创建/编辑通知请求体（与后端 CreateNotificationRequest 对齐） */
export interface NotificationPayload {
  title: string
  content: string
  level: string
  is_global: boolean
  target_user_id?: string | null
  expires_at?: string | null
}

export const adminNotificationApi = {
  /** 全部通知列表（管理员，含已过期/定向） */
  async listAll(): Promise<Notification[]> {
    const res = await apiClient.get('/notifications/all')
    return res.data || []
  },

  /** 创建通知（管理员） */
  async create(payload: NotificationPayload): Promise<Notification> {
    const res = await apiClient.post('/notifications', payload)
    return res.data
  },

  /** 编辑通知（管理员，仅传需更新字段） */
  async update(id: string, payload: Partial<NotificationPayload>): Promise<Notification> {
    const res = await apiClient.put(`/notifications/${id}`, payload)
    return res.data
  },

  /** 删除通知（管理员） */
  async remove(id: string): Promise<void> {
    await apiClient.delete(`/notifications/${id}`)
  },
}
