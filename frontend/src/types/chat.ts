/**
 * 聊天系统类型定义（Cherry Studio 架构）
 */

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
  created_at: string
}
