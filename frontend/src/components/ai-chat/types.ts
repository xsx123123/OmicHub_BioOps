import type { DataFile } from '@/types'
import type { AgentTemplate, SkillItem } from '@/types/agent'

// ===== Token 统计 =====
export interface TokenInfo {
  input?: number
  output?: number
  total?: number
}

export interface WebSearchSource {
  title: string
  url: string
  snippet: string
  publishedAt?: string | null
}

export interface KnowledgeCitationSource {
  citationId: string
  docId: string
  title: string
  category: string
  excerpt: string
  sectionPath: string
  url: string
}

// ===== 聊天消息 =====
/** 智能路由：目标专家信息（route 事件） */
export interface RoutedAgentInfo {
  agentId: string
  name: string
  avatar: string
  color: string
  reason: string
  intent?: string
  confidence?: number
  transition?: {
    visible: boolean
    stage: 'specialist_intake' | 'execution_ready'
    title: string
    message: string
    nextStep: string
    requiresExecutionConfirmation: boolean
    autoStart: boolean
  }
}

export interface CollaborationRouteInfo {
  intent: 'transfer' | 'fanout' | 'consult' | 'case' | 'dag' | 'chat'
  label: string
  reason: string
  confidence: number
  available: boolean
  degraded: boolean
  message: string
}

export interface ExpertConsultation {
  experts: Array<{ agent_id: string; name: string; opinion: string }>
  consultationId?: string
  consultationSummary?: string
  caseAvailable?: boolean
}

export interface AgentTeamsCaseCardPayload {
  case_id: string
  title: string
  status: string
  next_actor: string
  case_url: string
  updated_at?: string
  plan_hash?: string | null
  plan_version?: number
  proposed_submission?: Record<string, unknown> | null
}

export interface OverdriveProgress {
  runId?: string
  caseId?: string
  label: string
  completed: number
  total: number
  phase: 'manager_ready' | 'researching' | 'replanning' | 'plan_ready' | 'serial_preflight' | 'recruiting' | 'workers_starting' | 'worker_running' | 'tool_running' | 'worker_finished' | 'peer_reviewing' | 'summarizing' | 'awaiting_input' | 'awaiting_approval' | 'paused' | 'failed' | 'terminated' | 'completed'
  wave?: number
  waveTotal?: number
  waveMode?: 'parallel' | 'serial'
  fallback?: boolean
  /** 方案规划型 run:不经过专家执行,确认计划即完成交付。 */
  planningOnly?: boolean
  warning?: string
  stalledTaskIds?: string[]
  activities?: Array<{
    id: string
    label: string
    kind: 'search' | 'model' | 'sandbox' | 'mcp'
    status: string
    queries?: string[]
    accepted?: number
    rejected?: number
    durationMs?: number
    error?: string
  }>
  tasks?: Array<{ taskId: string; agentId: string; status: string; errorSummary?: string }>
  artifacts?: Array<{
    path: string
    kind?: string
    status?: string
    source?: string
    qualityStatus?: string
    downloadUrl?: string
    previewUrl?: string
  }>
  /** 只读进度卡（如对话内 fan-out）：隐藏超频专属的暂停/终止/指令控制条。 */
  readonly?: boolean
}

export interface OverdriveApproval {
  approvalId: string
  runId?: string
  caseId?: string
  toolName: string
  arguments: Record<string, unknown>
  status: 'pending' | 'executing' | 'completed' | 'rejected' | 'failed'
  result?: Record<string, unknown>
  error?: string
  reason?: string
}

export interface ChatMessage {
  id: string
  /** 后端持久化消息 ID；流式期间不覆盖 id，避免虚拟列表 key 变化导致渲染缓存错位 */
  backendMessageId?: string
  /** 用户操作的受控元数据；仅在当前请求中透传到后端。 */
  metadata?: Record<string, unknown>
  role: 'user' | 'assistant' | 'system'
  content: string
  thought?: string
  /** 思考过程用时（秒），AI 消息专属 */
  thinkingDuration?: number
  /** 实际使用的模型名，AI 消息专属 */
  modelName?: string
  toolCalls?: ToolCall[]
  /** 正文/工具调用的交错时间线（AI 消息专属）：按实际发生顺序记录 text 段与 tool 段，
   *  前端据此把工具卡片渲染在对应正文之后，而不是全部堆在消息底部 */
  timeline?: TimelineSegment[]
  /** 技能调用卡片（AI 消息专属）：Agent 加载技能时由 skill 事件驱动 */
  skillInvocations?: SkillInvocationCard[]
  /** 联网搜索的标准化来源；用于预搜索和历史重载。 */
  webSources?: WebSearchSource[]
  /** 知识库检索的可核验来源；从 knowledge_search 工具结果恢复。 */
  knowledgeSources?: KnowledgeCitationSource[]
  charts?: ChartData[]
  /** Studio ask_user 澄清卡片（AI 消息专属，回答后标记 answered） */
  askRequest?: AskRequest
  /** 智能路由：本条 AI 消息实际由哪位专家回答（路由器会话专属） */
  routedAgent?: RoutedAgentInfo
  senderAgent?: {
    id: string
    name: string
    avatar?: string
    color?: string
    role?: 'manager' | 'worker'
    round?: number
  }
  collaborationRoute?: CollaborationRouteInfo
  consultation?: ExpertConsultation
  agentTeamsCases?: AgentTeamsCaseCardPayload[]
  /** 超频协作生命周期：Manager/专家/工具的实时进度卡片。 */
  overdriveProgress?: OverdriveProgress
  /** 普通超频聊天的持久化工具审批记录。 */
  overdriveApproval?: OverdriveApproval
  overdriveSummary?: string
  overdriveArtifacts?: Record<string, string>
  overdriveTaskStatus?: string
  overdriveErrorSummary?: string
  attachments?: FileAttachment[]
  feedback?: 'like' | 'dislike'
  /** 是否被编辑过，用户消息专属 */
  edited?: boolean
  /** 编辑历史，用户消息专属 */
  editHistory?: string[]
  /** Token 统计 */
  tokens?: TokenInfo
  /** 消息状态，用于流式错误/空内容识别 */
  status?: 'complete' | 'streaming' | 'error' | 'empty'
  /** 模型结束原因（done 事件透传），length 表示输出预算耗尽 */
  finishReason?: string
  createdAt: string
}

// ===== 图表数据 =====
export interface ChartData {
  id: string
  type: 'echarts' | 'plotly'
  option: Record<string, unknown>
}

// ===== 工具调用 =====
/** 交错时间线中的一段：正文文本 / 工具调用 / 技能调用（按发生顺序排列） */
export interface TimelineSegment {
  kind: 'text' | 'tool' | 'skill'
  /** kind=text 时的 Markdown 文本 */
  text?: string
  /** kind=tool 时对应的 ToolCall.id */
  toolCallId?: string
  /** kind=skill 时对应的 SkillInvocationCard.id */
  skillCardId?: string
}

/** 技能调用卡片（会话流内可视化：加载 spinner → 成功✓/失败✗ + 耗时；同技能多次调用合并计数） */
export interface SkillInvocationCard {
  id: string
  skill_id: string
  name: string
  icon: string
  version: string
  source: string
  /** 触发加载的 Agent 名称 */
  agent?: string
  status: 'running' | 'success' | 'error'
  duration_ms?: number
  summary?: string
  error?: string
  /** 同一消息内对同一技能的调用次数（合并展示，不刷屏） */
  count: number
  /** 技能不可用回退通用流程时的标注 */
  fallback?: boolean
  ts: number
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: unknown
  uiPayload?: Record<string, unknown>
  mcpServer?: string
  /** 调用理由（后端 tool_call 事件 metadata.purpose 透传） */
  purpose?: string
  status: 'pending' | 'running' | 'awaiting_approval' | 'success' | 'error' | 'timed_out'
  /** Studio 工具执行过程中累计的 stdout/stderr 输出（流式填充） */
  output?: string
  /** Studio 代码卡片的语言（python / r / bash） */
  language?: string
  /** Studio HITL 审批状态（内存态；刷新/断流后由 loadSessionMessages 从 Redis 重建） */
  approval?: ToolApproval
}

/** Studio 工具审批（supervised 模式下受控工具挂起等待用户决议） */
export interface ToolApproval {
  approval_id: string
  status: 'pending' | 'approved' | 'edited' | 'rejected' | 'timeout'
  risk_hint?: string
  timeout_seconds?: number
}

/** Studio ask_user 澄清请求中的单个问题 */
export interface AskQuestion {
  question: string
  /** 可点选的互斥选项；用户也可选"其他"自由输入 */
  options?: string[]
}

export type PlanDecisionAction = 'approve' | 'revise' | 'cancel'

export interface PlanAgentSummary {
  agentId: string
  name: string
  reason?: string
}

/** 超频计划确认卡使用的冻结计划快照。 */
export interface PlanConfirmation {
  runId: string
  title: string
  summary: string
  planPath: string
  planVersion: number
  planHash: string
  planningMode?: 'llm' | 'llm_repaired' | 'rule_merge' | 'rule_override' | 'rule_preflight'
  waveCount: number
  agents: PlanAgentSummary[]
  serialPreflight: string[]
  risks: string[]
  approvalPoints: string[]
  deliverables: string[]
  actions: PlanDecisionAction[]
  status: 'pending' | 'submitting' | 'approved' | 'revision_requested' | 'cancelled' | 'error'
  feedback?: string
  error?: string
}

/** Studio ask_user 澄清请求（附着在 AI 消息上，用户下一条消息回答） */
export interface AskRequest {
  kind?: 'questions' | 'plan_confirmation'
  /** 一次可包含多个问题，前端逐个分页收集 */
  questions: AskQuestion[]
  /** kind=plan_confirmation 时存在；必须连同版本与 hash 原样提交。 */
  planConfirmation?: PlanConfirmation
  /** 用户按问题顺序给出的答案；空串表示该问题被跳过 */
  answers?: string[]
  answered?: boolean
}

// ===== 文件附件 =====
export type AttachmentKind = 'image' | 'file' | 'directory'

export interface FileAttachment {
  name: string
  size: number
  /** Uploads retain their MIME type; controlled directory references use `directory`. */
  type: string
  url?: string
  file_id?: string
  /** 来源：upload=输入框上传；workspace=@ 引用的工作区文件 */
  source?: 'upload' | 'workspace'
  /** 目录引用始终由服务端只读、递归解析；普通文件忽略该字段。 */
  recursive?: boolean
}

// ===== @ 提及项（文件 / 智能体 / 技能）=====
export type MentionKind = 'directory' | 'file' | 'agent' | 'skill'

export interface MentionDirectory {
  id: string
  path: string
  name: string
  parent_path?: string | null
  is_system?: boolean
}

/** @ 补全面板中的一个可选项 */
export interface MentionItem {
  kind: MentionKind
  /** 列表渲染唯一 key */
  key: string
  name: string
  /** 文件为所在路径；智能体/技能为一句话能力描述 */
  description: string
  /** 条目对应的 UUID（仅作为 tooltip 展示，主行禁止裸显） */
  uuid?: string
  file?: DataFile
  directory?: MentionDirectory
  agent?: AgentTemplate
  skill?: SkillItem
}

// ===== 会话 =====
export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: string
  updatedAt: string
  model: string
  shared?: boolean
  settings?: SessionSettings
}

// ===== 会话设置 =====
export interface SessionSettings {
  temperature?: number
  maxTokens?: number
  topP?: number
  systemPrompt?: string
}

// ===== 用户信息 =====
export interface UserInfo {
  id: string
  name: string
  avatar: string
  role: string
  roleTag?: string
}

// ===== 快捷提示 =====
export interface QuickPrompt {
  icon: string
  text: string
  category: string
}

// ===== 模型能力 =====
export type Capability = 'longContext' | 'code' | 'multimodal' | 'bio'

// ===== 模型类型 =====
export type ModelType = 'general' | 'bio'

// ===== 模型选项 =====
export interface ModelOption {
  id: string
  name: string
  description: string
  provider: string
  /** 推断出的能力标签 */
  capabilities?: Capability[]
  /** 通用 / 生信专用 */
  modelType?: ModelType
  /** 上下文窗口大小（k） */
  contextWindow?: number
}

// ===== 消息操作类型 =====
export type MessageAction = 'copy' | 'regenerate' | 'retry' | 'translate' | 'delete'

// ===== 复制模式 =====
export type CopyMode = 'plain' | 'markdown' | 'citation'

// ===== 对话级设置 =====
export interface ConversationSettings {
  temperature: number
  maxTokens: number
  contextLength: number
}

// ===== 系统状态 =====
export type SystemStatus = 'ready' | 'thinking' | 'toolCalling' | 'webSearching'

// ===== 插件选项 =====
export interface PluginOption {
  id: string
  name: string
  description: string
  icon: string
}

// ===== Slash 命令 =====
export interface SlashCommand {
  id: string
  name: string
  description: string
  icon: string
  category: string
  shortcut?: string
}

// ===== 发送选项 =====
export interface SendOptions {
  agentMode: boolean
  model: string
  plugins: string[]
  attachments?: File[]
}
