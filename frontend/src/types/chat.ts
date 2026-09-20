/**
 * 聊天系统类型定义（Cherry Studio 架构）
 */

/** 科研模式设置（WP3 任务 3；null/undefined = 未开启，旧数据兼容） */
export interface ResearchModeSettings {
  enabled: boolean
  render_mode: 'message_flow' | 'cell_timeline'
  workspace_protocol: 'standard' | 'research'
  ptc_llm_query: boolean
}

export interface ChatSessionDTO {
  session_id: string
  title: string
  assistant_id: string | null
  model_id: string
  message_count: number
  status: string
  created_at: string
  updated_at: string
  last_message_at: string | null
  /** 科研模式设置（后端契约新增字段；旧数据无此字段时为 null/undefined） */
  research_mode?: ResearchModeSettings | null
}

export interface ChatMessageDTO {
  message_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  content_type: string
  status: 'complete' | 'streaming' | 'error'
  metadata_json: Record<string, unknown>
  created_at: string
  tokens?: {
    input: number
    output: number
    total: number
    cached?: number
  }
}

export interface TokenInfo {
  input: number
  output: number
  total: number
}

export interface ChatAssistantDTO {
  assistant_id: string
  name: string
  description: string | null
  system_prompt: string
  default_model_id: string | null
  default_temperature: number
  default_max_tokens: number
  icon: string
  color: string
  category: string
  is_builtin: boolean
  is_active: boolean
}

export interface ChatModelOption {
  id: string
  name: string
  model: string
  provider_type: string
  is_default: boolean
  temperature: number
  max_tokens: number
}

/** 前端展示用的消息结构（含流式状态） */
export interface DisplayMessage {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  status: 'complete' | 'streaming' | 'error'
  /** 错误原因；出错时 content 保留已累计正文 */
  error?: string
  created_at: string
}
