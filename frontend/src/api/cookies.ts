import apiClient from './client'
import type { AiTokenRate } from '@/types'

export const cookieApi = {
  async getAiTokenRate(): Promise<AiTokenRate> {
    const res = await apiClient.get<AiTokenRate>('/cookies/ai-token-rate')
    return res.data
  },
}
