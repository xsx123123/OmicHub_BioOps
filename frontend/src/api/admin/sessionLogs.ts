import apiClient from '../client'

/** 会话摘要（来自 chat_sessions 表及运行时编排配置） */
export interface SessionSummary {
  session_id: string
  user_id: string
  user_name: string
  title: string
  mode: string
  /** 统一归因后的执行模式：对话 / 工作台 / 超频（多 Agent 编排） */
  execution_mode: 'chat' | 'studio' | 'overdrive'
  agent_id: string | null
  assistant_id: string | null
  status: string
  message_count: number
  total_tokens: number
  last_message_at: string | null
}

/** 单条 Trace 摘要（会话的调用链列表项） */
export interface TraceSummary {
  trace_id: string
  session_id: string
  root_name: string
  start_time: string
  duration_ms: number
  span_count: number
  has_error: boolean
  service: string
}

/** span 树节点（瀑布图） */
export interface SpanNode {
  trace_id: string
  span_id: string
  parent_span_id: string | null
  name: string
  kind: string
  service: string
  start_time: string
  end_time: string
  start_ns: number
  duration_ms: number
  status_code: string
  status_message: string
  session_id: string
  request_id: string
  attributes: Record<string, unknown>
  events: { name: string; timestamp: string; attributes: Record<string, unknown> }[]
  children: SpanNode[]
}

/** 单会话运行报告（span + 日志聚合） */
export interface SessionReport {
  session_id: string
  cookie_rate: number
  summary: {
    trace_count: number
    span_count: number
    log_event_count: number
    wall_duration_ms: number
    ai_calls: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    cost_cookie: number
    ai_duration_ms: number
    error_count: number
  }
  models: { model: string; calls: number; tokens: number; errors: number }[]
  tool_calls: { tool: string; count: number }[]
  skill_calls: { skill: string; count: number }[]
  errors: { name: string; message: string; time: string }[]
}

/** 单条观测日志事件（来自结构化 JSON 日志） */
export interface SessionLogEvent {
  timestamp: string
  level: string
  /** semantic（业务埋点）/ sql（SQLAlchemy echo）/ system（框架日志） */
  category: 'semantic' | 'sql' | 'system'
  event: string | null
  message: string
  logger: string
  function: string
  line: number | null
  trace_id: string
  span_id: string
  request_id: string
  /** sql 类事件在未揭示敏感原文时为 true（message 已脱敏） */
  redacted: boolean
  data: Record<string, unknown>
}

export interface SessionEventsResponse {
  session_id: string
  log_dir: string
  include_archives: boolean
  categories: string[]
  levels: string[] | null
  reveal_sensitive: boolean
  count: number
  events: SessionLogEvent[]
}

/** 用户对 AI 消息的点赞/点踩反馈（点踩附带上下文快照） */
export interface SessionFeedback {
  feedback_id: string
  session_id: string
  message_id: string
  user_id: string
  user_name: string
  rating: 'like' | 'dislike'
  comment: string | null
  status: string
  context: {
    session_mode?: string
    execution_hint?: {
      assistant_id?: string | null
      agent_id?: string | null
      overdrive?: boolean
      sender_agent?: string | null
    }
    model?: string
    message_excerpt?: string
    user_question_excerpt?: string
    message_status?: string
  }
  session_title: string
  execution_mode: 'chat' | 'studio' | 'overdrive'
  created_at: string | null
}

export const adminSessionLogsApi = {
  /** 会话列表（供排查选择） */
  async listSessions(params?: {
    search?: string
    mode?: string
    limit?: number
  }): Promise<SessionSummary[]> {
    const res = await apiClient.get('/admin/session-logs/sessions', { params })
    return res.data || []
  },

  /** 用户会话反馈列表（点赞 / 点踩） */
  async listFeedbacks(params?: {
    rating?: 'like' | 'dislike'
    search?: string
    limit?: number
    offset?: number
  }): Promise<{ total: number; items: SessionFeedback[] }> {
    const res = await apiClient.get('/admin/session-logs/feedbacks', { params })
    return res.data || { total: 0, items: [] }
  },

  /** 按会话聚合的日志事件时间线 */
  async getEvents(
    sessionId: string,
    params?: {
      categories?: string
      levels?: string
      search?: string
      reveal_sensitive?: boolean
      include_archives?: boolean
      limit?: number
    },
  ): Promise<SessionEventsResponse> {
    const res = await apiClient.get(`/admin/session-logs/${sessionId}/events`, { params })
    return res.data
  },

  /** 会话的 Trace 列表 */
  async getTraces(
    sessionId: string,
    params?: { include_archives?: boolean; limit?: number },
  ): Promise<{ session_id: string; count: number; traces: TraceSummary[] }> {
    const res = await apiClient.get(`/admin/session-logs/${sessionId}/traces`, { params })
    return res.data
  },

  /** 单条 Trace 的 span 树 */
  async getTraceDetail(
    traceId: string,
    params?: { include_archives?: boolean },
  ): Promise<{ trace_id: string; span_count: number; tree: SpanNode[] }> {
    const res = await apiClient.get(`/admin/session-logs/traces/${traceId}`, { params })
    return res.data
  },

  /** 单会话运行报告 */
  async getReport(
    sessionId: string,
    params?: { include_archives?: boolean },
  ): Promise<SessionReport> {
    const res = await apiClient.get(`/admin/session-logs/${sessionId}/report`, { params })
    return res.data
  },

  /** 导出会话日志为文件（json/csv），返回 Blob 供前端下载 */
  async exportEvents(
    sessionId: string,
    params?: {
      format?: 'json' | 'csv'
      categories?: string
      levels?: string
      search?: string
      include_archives?: boolean
      limit?: number
    },
  ): Promise<Blob> {
    const res = await apiClient.get(`/admin/session-logs/${sessionId}/events/export`, {
      params,
      responseType: 'blob',
    })
    return res.data as Blob
  },
}
