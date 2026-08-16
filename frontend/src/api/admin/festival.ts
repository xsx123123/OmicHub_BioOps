import apiClient from '../client'
import type {
  FestivalAdminListResponse,
  FestivalAdminUpdateRequest,
  FestivalConfig,
} from '@/types/festival'

export const adminFestivalApi = {
  /** 列出全部节日 */
  async list(): Promise<FestivalAdminListResponse> {
    const res = await apiClient.get<FestivalAdminListResponse>('/admin/festivals')
    return res.data
  },

  /** 更新节日配置 */
  async update(
    festivalId: string,
    payload: FestivalAdminUpdateRequest,
  ): Promise<FestivalConfig> {
    const res = await apiClient.put<FestivalConfig>(`/admin/festivals/${festivalId}`, payload)
    return res.data
  },

  /** 强制重载配置 */
  async reload(): Promise<{ reloaded: boolean }> {
    const res = await apiClient.post<{ reloaded: boolean }>('/admin/festivals/reload')
    return res.data
  },
}
