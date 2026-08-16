import apiClient from './client'
import type { Announcement } from '@/types/announcement'

export const announcementApi = {
  /** 获取当前生效的通知（首页调用，登录用户可见，按优先级排序） */
  async getActive(): Promise<Announcement[]> {
    const res = await apiClient.get('/announcements/active')
    return res.data || []
  },
}
