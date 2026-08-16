import apiClient from './client'
import type {
  FestivalClaimResponse,
  FestivalTodayResponse,
} from '@/types/festival'

export const festivalApi = {
  /** 获取今日节日 */
  async getTodayFestival(): Promise<FestivalTodayResponse> {
    const res = await apiClient.get<FestivalTodayResponse>('/festival/today')
    return res.data
  },

  /** 领取节日额度 */
  async claimFestival(festivalId: string): Promise<FestivalClaimResponse> {
    const res = await apiClient.post<FestivalClaimResponse>('/festival/claim', { festivalId })
    return res.data
  },
}
