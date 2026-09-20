/** 通用 API 响应类型 */

export interface ApiResponse<T = unknown> {
  data: T
  message?: string
}

export interface User {
  id: string
  username: string
  email: string
  role: 'admin' | 'user'
  status: 'active' | 'inactive' | 'locked'
  avatar_url?: string | null
  nickname?: string | null
  preferences?: Record<string, unknown>
  storage_quota?: number
  used_storage?: number
  last_login_at?: string | null
  created_at: string
  updated_at: string
  /** 被管理员禁用的模块 key 列表（空数组 = 全部模块可用） */
  disabled_modules?: string[]
}

/** 模块注册表条目（GET /modules/registry 下发，全平台模块权限管控的唯一数据源） */
export interface ModuleRegistryItem {
  key: string
  name: string
  route_prefix: string[]
  api_prefix: string[]
  lockable: boolean
  default_locked: boolean
  ai: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  first_login: boolean
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  first_login: boolean
  requires_2fa: boolean
  challenge_token: string | null
}

export interface TwoFactorSetupResponse {
  secret: string
  otpauth_uri: string
}

export interface TwoFactorStatusResponse {
  enabled: boolean
  has_secret: boolean
}

export interface TwoFactorLoginRequest {
  challenge_token: string
  code: string
}

export interface TwoFactorCodeRequest {
  code: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
  lab_group?: string | null
}

export interface FlowDefinition {
  id: string
  name: string
  description: string
  category: string
  version: string
  tags?: string[]
  docs_url?: string | null
  github_url?: string | null
  icon?: string | null
  color?: string | null
  author?: string | null
  parameter_count?: number
  has_sample_sheet?: boolean
}

export interface DataFile {
  id: string
  path: string
  original_name: string
  size: number
  checksum: string
  file_type: 'fastq' | 'bam' | 'vcf' | 'count_matrix' | 'h5ad' | 'rds' | 'meta' | 'report' | 'image' | 'other'
  status?: string
  directory?: string
  metadata?: Record<string, unknown>
  source?: string
  owner_scope?: 'personal' | 'team'
  team_id?: string | null
  created_at: string
}

export interface TeamInfo {
  id: string
  name: string
  owner_id: string
  description?: string | null
  role: 'owner' | 'writer' | 'reader'
  created_at: string
  updated_at: string
}

/** 存储配额信息 */
export interface QuotaInfo {
  used: number
  total: number
  percent: number
}

/** 用户自定义目录 */
export interface Directory {
  id: string
  path: string
  name: string
  parent_path: string | null
  is_system?: boolean
  created_at: string
}

/** 文件选择器项（供分析选文件） */
export interface FilePickerItem {
  id: string
  original_name: string
  size: number
  file_type: string
  directory: string
  abs_path: string
}

/** 分块上传初始化响应 */
export interface UploadInitResponse {
  upload_id: string
  completed: boolean
  file_id?: string | null
  uploaded_chunks: Array<{ index: number; md5?: string }> | number[]
  chunk_size: number
}

/** 分块上传响应 */
export interface UploadChunkResponse {
  upload_id: string
  index: number
  accepted: boolean
  uploaded: number
}

/** 合并响应 */
export interface UploadMergeResponse {
  file_id: string
  original_name: string
  size: number
  checksum: string
  used_storage: number
}

/** 上传队列项状态 */
export interface UploadQueueItem {
  id: string
  file: File
  uploadId: string | null
  status: 'pending' | 'uploading' | 'merging' | 'completed' | 'paused' | 'failed' | 'cancelled'
  progress: number
  uploadedChunks: number
  totalChunks: number
  speed: number
  error: string
}

export interface TaskLog {
  timestamp: string
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  message: string
  source: string
}

export interface Task {
  id: string
  flow_id: string
  user_id: string
  username?: string | null
  nickname?: string | null
  name: string
  status: 'pending' | 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
  execution_mode: string
  parameters: Record<string, unknown>
  work_dir: string
  result_path: string
  error_message: string
  progress: number
  logs: TaskLog[]
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ChatMessage {
  id: string
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  timestamp: string
}

// ===== AI Copilot =====
export interface Conversation {
  id: string
  user_id: string
  title: string
  model: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface AIMessage {
  id: string
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  tool_calls?: Array<Record<string, unknown>>
  tool_call_id?: string | null
  timestamp: string
}

export interface ConversationDetail extends Conversation {
  messages: AIMessage[]
}

// AI WebSocket 事件
export type AIEvent =
  | { type: 'user_message'; message: AIMessage }
  | { type: 'token'; content: string }
  | { type: 'assistant_message'; message: AIMessage }
  | { type: 'tool_call'; tool: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; result: Record<string, unknown> }
  | { type: 'done' }
  | { type: 'error'; detail: string }
  | { type: 'pong' }

// ===== 代码执行沙盒 =====
export interface SandboxSession {
  id: string
  user_id: string
  container_id: string | null
  status: 'creating' | 'ready' | 'executing' | 'idle' | 'paused' | 'error' | 'destroyed'
  language: string
  last_activity: string
  created_at: string
  expires_at: string | null
}

export type SandboxEvent =
  | { type: 'stdout'; data: string }
  | { type: 'stderr'; data: string }
  | { type: 'echarts'; option: Record<string, unknown> }
  | { type: 'image'; data: string }
  | { type: 'done'; exit_code: number; duration_ms: number }
  | { type: 'error'; detail: string }

// ===== MCP =====
export interface MCPServer {
  id: string
  name: string
  description: string
  transport: 'stdio' | 'sse' | 'builtin'
  command: string
  url: string
  status: 'online' | 'offline' | 'error' | 'starting'
  timeout: number
  auto_restart: boolean
  is_preset: boolean
  tool_count: number
  created_at: string | null
}

export interface MCPTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

// ===== Skill =====
export interface Skill {
  id: string
  skill_id: string
  name: string
  description: string
  prompt: string
  tool_definition: Record<string, unknown> | null
  icon: string
  category: string
  is_active: boolean
  is_builtin: boolean
  created_at: string
  updated_at: string
}

// ===== ChatAssistant (admin) =====
export interface ChatAssistantAdmin {
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
  is_default: boolean
}

// ===== Skill =====
export interface Skill {
  id: string
  skill_id: string
  name: string
  description: string
  prompt: string
  tool_definition: Record<string, unknown> | null
  icon: string
  category: string
  is_active: boolean
  is_builtin: boolean
  created_at: string
  updated_at: string
}

// ===== ChatAssistant (Admin) =====
export interface ChatAssistantAdmin {
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
  is_default: boolean
}

// ===== AI Provider 配置 =====
export interface AIProviderConfig {
  id: string
  name: string
  provider_type: string
  model: string
  base_url: string
  temperature: number
  max_tokens: number
  top_p: number
  timeout: number
  /** 输入/输出/输入缓存/输出缓存单价（元 / M tokens），null = 未配置，费用估算回退到全局单价 */
  input_price?: number | null
  output_price?: number | null
  input_cache_price?: number | null
  output_cache_price?: number | null
  is_active: boolean
  is_default: boolean
  api_key?: string // 脱敏回显："********" 表示已配置，未配置为空
  extra_params: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

// ===== 饼干积分系统 =====
export interface CookieAccount {
  id: number | null
  user_id: string
  balance: number
  frozen_balance: number
  available_balance: number
  total_earned: number
  total_spent: number
  total_adjusted: number
  status: 'active' | 'frozen' | 'suspended'
  created_at: string | null
}

export interface CookieTransaction {
  id: number | null
  user_id: string
  txn_type: 'earn' | 'spend' | 'adjust' | 'refund' | 'freeze' | 'unfreeze'
  amount: number
  balance_after: number
  source_type: string
  source_id: string
  task_type: string
  description: string
  created_at: string | null
}

export interface CookiePricing {
  id: number | null
  pricing_type: 'task_type' | 'resource' | 'sandbox' | 'bonus'
  resource_type: string
  flow_category: string
  base_cost: number
  per_sample_cost: number
  per_comparison_cost: number
  unit: 'per_task' | 'per_hour' | 'per_core_hour' | 'per_gb_hour' | 'per_session' | 'per_user' | 'per_sample' | 'per_comparison'
  is_active: boolean
  priority: number
  description: string
  effective_from: string | null
  effective_until: string | null
}

export interface CookieDiscount {
  id: number
  name: string
  discount_multiplier: number
  date_start: string
  date_end: string
  daily_start: string | null
  daily_end: string | null
  timezone: string
  priority: number
  is_active: boolean
  banner_title: string
  banner_description: string
  created_at?: string | null
  updated_at?: string | null
}

export interface AiTokenRate {
  base_rate: number
  effective_rate: number
  discount: CookieDiscount | null
}

export type QuickEntryColor = 'blue' | 'purple' | 'violet' | 'cyan' | 'green' | 'orange' | 'teal' | 'gray'

export interface HomeQuickEntry {
  key: string
  title: string
  desc: string
  to: string
  icon: string
  icon_bg: QuickEntryColor
}

export interface SiteSettings {
  registration_enabled: boolean
  totp_policy: 'off' | 'optional' | 'required'
  home_quick_entries?: HomeQuickEntry[]
  /** 对话内并行子 Agent fan-out 开关（管理端运行时主开关） */
  subagent_fanout_enabled: boolean
  agentteams_chat_entry_enabled: boolean
  /** Agent 长期记忆运行时开关（26.8.4；与 env MEM0_ENGINE_ENABLED 同时为真才启用） */
  agent_memory_enabled?: boolean
}

export interface UpdateSiteSettings {
  registration_enabled?: boolean
  totp_policy?: 'off' | 'optional' | 'required'
  home_quick_entries?: HomeQuickEntry[]
  subagent_fanout_enabled?: boolean
  agentteams_chat_entry_enabled?: boolean
  agent_memory_enabled?: boolean
}

export interface CostEstimate {
  flow_id: string
  estimated_cost: number
  sample_count: number
  comparison_count: number
  breakdown: Array<{ item: string; cost: string }>
  affordable: boolean
  current_balance: number
}

export interface CookieStats {
  total_accounts: number
  active_accounts: number
  total_balance: number
  total_frozen: number
  total_earned: number
  total_spent: number
}

// ===== 通知提醒 =====
export type NotificationLevel = 'info' | 'warning' | 'error'

export interface Notification {
  id: string
  title: string
  content: string
  level: NotificationLevel
  type?: string
  payload?: Record<string, unknown>
  created_by: string
  is_global: boolean
  target_user_id: string | null
  read_by: string[]
  expires_at: string | null
  created_at: string
  updated_at: string
}

export * from './report'
