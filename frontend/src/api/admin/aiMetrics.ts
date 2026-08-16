import apiClient from '../client'

/** 按日聚合的 AI 调用指标 */
export interface AiDailyMetric {
  date: string
  calls: number
  errors: number
  error_rate: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_cookie: number
  avg_duration_ms: number
  p95_duration_ms: number
}

export interface AiTrendResponse {
  days: number
  model: string | null
  provider: string | null
  cookie_rate: number
  summary: {
    calls: number
    errors: number
    error_rate: number
    total_tokens: number
    cost_cookie: number
  }
  daily: AiDailyMetric[]
}

/** 按模型聚合 */
export interface AiModelMetric {
  provider: string
  model: string
  calls: number
  errors: number
  error_rate: number
  total_tokens: number
  cost_cookie: number
  avg_duration_ms: number
}

/** 告警规则当前状态 */
export interface AiAlertRule {
  rule: string
  label: string
  value: number
  threshold: number
  breaching: boolean
  display: string
}

export interface AiAlertStatus {
  enabled: boolean
  rules: AiAlertRule[]
}

/** 告警历史 */
export interface AiAlertHistoryItem {
  id: string
  rule: string
  level: string
  message: string
  metric_value: number
  threshold: number
  created_at: string | null
}

export const adminAiMetricsApi = {
  async getTrend(params?: {
    days?: number
    model?: string
    provider?: string
  }): Promise<AiTrendResponse> {
    const res = await apiClient.get('/admin/ai-metrics/trend', { params })
    return res.data
  },

  async getModels(params?: { days?: number }): Promise<AiModelMetric[]> {
    const res = await apiClient.get('/admin/ai-metrics/models', { params })
    return res.data || []
  },

  async getAlertStatus(): Promise<AiAlertStatus> {
    const res = await apiClient.get('/admin/ai-metrics/alerts/status')
    return res.data
  },

  async getAlertHistory(params?: { limit?: number }): Promise<AiAlertHistoryItem[]> {
    const res = await apiClient.get('/admin/ai-metrics/alerts/history', { params })
    return res.data || []
  },
}
