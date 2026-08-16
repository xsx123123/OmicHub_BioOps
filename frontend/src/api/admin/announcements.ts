import apiClient from '../client'
import type { Announcement, AnnouncementPayload } from '@/types/announcement'

export const adminAnnouncementApi = {
  /** 全部通知列表（管理员） */
  async list(): Promise<Announcement[]> {
    const res = await apiClient.get('/announcements')
    return res.data || []
  },

  /** 创建通知（管理员） */
  async create(payload: AnnouncementPayload): Promise<Announcement> {
    const res = await apiClient.post('/announcements', payload)
    return res.data
  },

  /** 更新通知（管理员，仅传需更新字段） */
  async update(id: string, payload: Partial<AnnouncementPayload>): Promise<Announcement> {
    const res = await apiClient.put(`/announcements/${id}`, payload)
    return res.data
  },

  /** 删除通知（管理员） */
  async remove(id: string): Promise<void> {
    await apiClient.delete(`/announcements/${id}`)
  },
}
