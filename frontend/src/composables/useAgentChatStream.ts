/**
 * useAgentChatStream — Agent 调度中枢的 SSE 流式聊天 Composable
 *
 * 基于 fetch + ReadableStream 解析 Server-Sent Events。
 * 与 useChatStream 的区别：
 *  - payload 用 agent_id（走后端 Agent 编排闭环）
 *  - 解析 tool_call / tool_result 事件，供前端渲染工具调用气泡
 */
import { ref } from 'vue'
import { reportChatDiagnostic } from '@/utils/chatDiagnostics'
import type { PlanAgentSummary, PlanConfirmation } from '@/components/ai-chat/types'

export interface AgentChatStreamOptions {
  agentId: string
  messages: { role: string; content: string; metadata?: Record<string, unknown> }[]
  sessionId?: string
  /** 当前会话运行模式；Studio 模式会由后端装配工作区工具与上下文。 */
  mode?: 'chat' | 'studio'
  /** 当前请求强制使用的模型配置 ID（覆盖 Agent 默认模型） */
  modelId?: string
  /** 温度（0-1），后端 Agent 编排层可透传给底层模型 */
  temperature?: number
  /** 单次回复最大 token 数 */
  maxTokens?: number
  /** 是否开启深度思考/推理模式 */
  deepThinking?: boolean
  /** 当前用户消息的附件 */
  attachments?: ChatAttachment[]
  /** 是否启用联网搜索 */
  enableWebSearch?: boolean
  /** 是否启用代码执行（仅作标记，实际由前端 Pyodide 执行） */
  enableCodeExecution?: boolean
  mcpMode?: 'off' | 'auto' | 'manual'
  extraMcpServers?: string[]
  /** 当前会话是否启用 multi-agent 协作运行时 */
  multiAgent?: boolean
  overdrive?: boolean
  /** 工具调用轮次上限扩展：true 时后端按 1000 轮执行（用户在触顶弹窗确认继续后置位） */
  extendMaxRounds?: boolean
}

export interface ChatAttachment {
  type: 'image' | 'file' | 'directory'
  url: string
  name: string
  mime_type: string
  file_id?: string
  source?: 'upload' | 'workspace'
  recursive?: boolean
}

export interface ToolCallEvent {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  mcp_server?: string
  /** 调用理由（为什么调这个工具，后端 metadata 透传） */
  purpose?: string
}
export interface ToolResultEvent {
  tool_call_id: string
  tool_name: string
  success: boolean
  result: unknown
  ui_payload?: Record<string, unknown>
  mcp_server?: string
  checkpoint_id?: string
}

export interface StudioPlanStep {
  title: string
  status: 'pending' | 'in_progress' | 'done'
}

/** Studio HITL：审批请求事件（supervised 模式下受控工具挂起等待用户决议） */
export interface ApprovalRequestEvent {
  approval_id: string
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  risk_hint?: string
  timeout_seconds?: number
  approval_kind?: 'tool' | 'plan'
}

export type ApprovalAction = 'approved' | 'edited' | 'rejected' | 'timeout'

/** Studio HITL：审批决议事件（批准后工具照常执行，随后有正常 tool_output/tool_result） */
export interface ApprovalResolvedEvent {
  approval_id: string
  tool_call_id: string
  action: ApprovalAction
}

export interface LoopGuardTriggeredEvent {
  reason: 'max_tool_calls_per_turn' | 'max_consecutive_failures'
  tool_calls: number
  consecutive_failures: number
  tool_name?: string
  error_type?: string
  downgraded_to_supervised: boolean
}

/** Studio HITL：ask_user 澄清请求（本轮随后结束，用户在下一条消息回答） */
export interface AskRequestEvent {
  tool_call_id: string
  kind: 'questions' | 'plan_confirmation'
  /** 多问题列表（优先）；兼容后端平铺的 question/options 单问题字段 */
  questions?: Array<{ question: string; options?: string[] }>
  question?: string
  options?: string[]
  planConfirmation?: PlanConfirmation
}

/** 智能路由：route 事件（路由器 Agent 分派目标专家后、正文开始前推送） */
export interface RouteEvent {
  agent_id: string
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
    next_step: string
    requires_execution_confirmation: boolean
    auto_start: boolean
  }
}

/** 同一会话内 Agent 交接事件。完整摘要仍由同名工具结果卡片保存和渲染。 */
export interface HandoffEvent {
  source_agent_id: string
  source_agent_name?: string
  target_agent_id: string
  target_agent_name?: string
  reason: string
  handoff_summary?: string
  user_intent?: string
  artifacts?: string[]
  constraints?: string[]
  hop_index: number
}

export interface ConsultationEvent {
  experts: Array<{ agent_id: string; name: string; opinion: string }>
  consultation_id?: string
  consultation_summary?: string
  case_available?: boolean
}

export interface CollaborationRouteEvent {
  intent: 'transfer' | 'fanout' | 'consult' | 'case' | 'dag' | 'chat'
  label: string
  reason: string
  confidence: number
  available: boolean
  degraded: boolean
  message: string
}

export interface AgentTeamsCaseEvent {
  phase: 'created' | 'status_changed'
  case_id: string
  title: string
  status: string
  next_actor: string
  case_url: string
  session_id?: string
  message_id?: string
}

export interface TokenUsage {
  input?: number
  output?: number
  total?: number
  input_tokens?: number
  output_tokens?: number
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export interface RoomSpeechEvent {
  sender: { agent_id: string; name: string; avatar?: string; color?: string; role: 'manager' | 'worker' }
  content: string
  round: number
  messageId?: string
  sessionId?: string
  workerKey?: string
  isReasoning?: boolean
  thought?: string
  summary?: string
  artifacts?: Record<string, string>
  taskStatus?: string
  errorSummary?: string
}

export interface OverdriveProgressEvent {
  runId?: string
  phase: 'manager_ready' | 'researching' | 'replanning' | 'plan_ready' | 'serial_preflight' | 'recruiting' | 'workers_starting' | 'worker_running' | 'tool_running' | 'worker_finished' | 'peer_reviewing' | 'summarizing' | 'awaiting_input' | 'awaiting_approval' | 'paused' | 'failed' | 'terminated' | 'completed'
  label: string
  completed: number
  total: number
  wave?: number
  waveTotal?: number
  waveMode?: 'parallel' | 'serial'
  fallback?: boolean
  /** 方案规划型 run:不经过专家执行,确认计划即完成交付。 */
  planningOnly?: boolean
  warning?: string
  stalledTaskId?: string
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
  tasks?: Array<{ taskId: string; agentId: string; status: string; errorSummary?: string; statusLine?: string }>
}

export interface OverdriveApprovalEvent {
  approval: {
    approval_id: string
    run_id?: string
    tool_name: string
    arguments: Record<string, unknown>
    status: 'pending' | 'executing' | 'completed' | 'rejected' | 'failed'
    result?: Record<string, unknown>
    error?: string
    reason?: string
    case_id?: string
  }
  workerKey?: string
  agentId?: string
}

/**
 * 对话内并行子 Agent(fan-out)事件。后端 `type="subagents"` 发送：
 * - started:   { phase, tool_call_id, tasks:[{index, agent_id, task}] }
 * - aggregated:{ phase, tool_call_id, success, summary, progress:[{index, agent_id, status, elapsed_s}] }
 * 复用超频群聊的多 Agent 泳道展示（OverdriveProgress.tasks）。
 */
export interface SubagentFanoutEvent {
  phase: 'started' | 'aggregated'
  toolCallId: string
  tasks: Array<{ index: number; agentId: string; task: string; status: string }>
  success?: boolean
  summary?: string
}

/** Skill 调用生命周期事件（skill.invoked / skill.completed / skill.failed 三时机） */
export interface SkillStreamEvent {
  /** invoked=技能被匹配加载；completed=加载成功；failed=加载失败/技能不可用 */
  phase: 'invoked' | 'completed' | 'failed'
  tool_call_id: string
  message_id?: string
  skill_id: string
  name: string
  version: string
  source: string
  icon: string
  agent?: string
  duration_ms?: number
  summary?: string
  error?: string
}

export interface WebSearchSource {
  title: string
  url: string
  snippet: string
  publishedAt?: string | null
}

export interface RoundLimitEvent {
  sessionId: string
  messageId: string
  maxRounds: number
  canExtend: boolean
}

export interface AgentExecutionEvent {
  eventType: string
  sessionId?: string
  runId?: string
  agentId?: string
  round: number
  executionPath?: string
  payload: Record<string, unknown>
}

export interface AgentStreamCallbacks {
  onText?: (text: string, isReasoning?: boolean) => void
  onSessionCreated?: (sessionId: string, messageId: string) => void
  onToolCall?: (event: ToolCallEvent) => void
  onToolResult?: (event: ToolResultEvent) => void
  /** Skill 调用生命周期（invoked/completed/failed），驱动会话流内技能调用卡片 */
  onSkill?: (event: SkillStreamEvent) => void
  onWebSearchResults?: (sources: WebSearchSource[]) => void
  /**
   * Studio 工具执行过程中的 stdout/stderr 增量输出
   * （sandbox_execute 边跑边推；Studio 工具事件带 tool_call_id，旧事件可能仅带工具名）
   */
  onToolOutput?: (tool: string, stream: 'stdout' | 'stderr', data: string, toolCallId?: string) => void
  onPlan?: (steps: StudioPlanStep[]) => void
  onApprovalRequest?: (event: ApprovalRequestEvent) => void
  onApprovalResolved?: (event: ApprovalResolvedEvent) => void
  onLoopGuardTriggered?: (event: LoopGuardTriggeredEvent) => void
  /** 统一 Agent 执行生命周期事件，供调试时间线与房间投影使用。 */
  onExecutionEvent?: (event: AgentExecutionEvent) => void
  onAskRequest?: (event: AskRequestEvent) => void
  onRoute?: (event: RouteEvent) => void
  onHandoff?: (event: HandoffEvent) => void
  onConsultation?: (event: ConsultationEvent) => void
  onCollaborationRoute?: (event: CollaborationRouteEvent) => void
  onAgentTeamsCase?: (event: AgentTeamsCaseEvent) => void
  /** 工具调用轮次触顶：can_extend 为 true 时可由用户确认后以扩展上限继续 */
  onRoundLimit?: (event: RoundLimitEvent) => void
  /** 上下文超窗触发历史压缩时回调（estimatedTokens 为压缩前估算值） */
  onContextCompressed?: (estimatedTokens: number) => void
  onRoomSpeech?: (event: RoomSpeechEvent) => void
  onRoomSpeechDelta?: (event: RoomSpeechEvent) => void
  onOverdriveProgress?: (event: OverdriveProgressEvent) => void
  onStudioPromoted?: (event: { sessionId?: string; agentId: string; agentName: string; reason?: string }) => void
  onOverdriveApproval?: (event: OverdriveApprovalEvent) => void
  onSubagentFanout?: (event: SubagentFanoutEvent) => void
  onModeChanged?: (enabled: boolean, degraded?: boolean) => void
  /** 流式连接中断后自动重试时的进度通知（attempt 从 1 开始） */
  onRetry?: (attempt: number, maxAttempts: number) => void
  onError?: (error: string) => void
  onDone?: (
    sessionId: string,
    messageId: string,
    usage?: TokenUsage,
    finishReason?: string,
    finalContent?: string,
    finalReasoning?: string,
  ) => void
}

export interface NormalizedAgentStreamEvent {
  type: string
  content: string
  reasoning: string
  isReasoning: boolean
  sessionId?: string
  messageId?: string
  metadata?: Record<string, unknown>
  raw: Record<string, unknown>
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.length > 0) return value
  }
  return ''
}

function stringList(...values: unknown[]): string[] {
  for (const value of values) {
    if (Array.isArray(value)) {
      return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    }
  }
  return []
}

function normalizePlanAgents(value: unknown): PlanAgentSummary[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((raw) => {
    if (typeof raw === 'string' && raw.trim()) {
      return [{ agentId: raw, name: raw }]
    }
    const item = asRecord(raw)
    if (!item) return []
    const agentId = firstString(item.agent_id, item.agentId, item.id)
    const name = firstString(item.display_name, item.name, item.agent_name, agentId)
    if (!agentId && !name) return []
    return [{
      agentId: agentId || name,
      name: name || agentId,
      reason: firstString(item.reason, item.task_summary) || undefined,
    }]
  })
}

/** 将 ask_request 的冻结计划契约归一化为 UI 模型。 */
export function normalizePlanConfirmation(data: Record<string, unknown>): PlanConfirmation | undefined {
  if (data.kind !== 'plan_confirmation') return undefined
  const summary = asRecord(data.summary) || asRecord(data.plan_summary) || {}
  const actions = stringList(data.actions)
    .filter((action): action is PlanConfirmation['actions'][number] =>
      action === 'approve' || action === 'revise' || action === 'cancel')
  const runId = firstString(data.run_id, data.runId)
  const planPath = firstString(data.plan_path, data.path, summary.plan_path)
  const planHash = firstString(data.plan_hash, data.hash, summary.plan_hash)
  const planVersion = Number(data.plan_version ?? data.version ?? summary.plan_version ?? 0)
  const rawPlanningMode = firstString(data.planning_mode, summary.planning_mode)
  const planningMode = [
    'llm',
    'llm_repaired',
    'rule_merge',
    'rule_override',
    'rule_preflight',
  ].includes(rawPlanningMode)
    ? rawPlanningMode as PlanConfirmation['planningMode']
    : undefined
  return {
    runId,
    title: firstString(data.title, summary.title) || '执行计划待确认',
    summary: firstString(data.plan_summary_text, summary.summary, summary.description, data.description),
    planPath,
    planVersion: Number.isFinite(planVersion) ? planVersion : 0,
    planHash,
    planningMode,
    waveCount: Number(data.wave_count ?? summary.wave_count ?? summary.estimated_waves ?? 0) || 0,
    agents: normalizePlanAgents(data.agents ?? summary.agents ?? summary.agent_ids),
    serialPreflight: stringList(data.serial_preflight, summary.serial_preflight, summary.manager_tasks),
    risks: stringList(data.risks, summary.risks),
    approvalPoints: stringList(data.approval_points, summary.approval_points),
    deliverables: stringList(data.deliverables, summary.deliverables),
    actions: actions.length ? actions : ['approve', 'revise', 'cancel'],
    status: 'pending',
  }
}

export function normalizeAgentStreamEvent(data: Record<string, unknown>): NormalizedAgentStreamEvent {
  const nestedData = asRecord(data.data)
  const delta = asRecord(data.delta) || asRecord(nestedData?.delta)
  const message = asRecord(data.message) || asRecord(nestedData?.message)
  const firstChoice = Array.isArray(data.choices) ? asRecord(data.choices[0]) : undefined
  const choiceDelta = asRecord(firstChoice?.delta)
  const choiceMessage = asRecord(firstChoice?.message)

  const reasoning = firstString(
    data.reasoning_content,
    data.reasoning,
    nestedData?.reasoning_content,
    nestedData?.reasoning,
    delta?.reasoning_content,
    delta?.reasoning,
    message?.reasoning_content,
    choiceDelta?.reasoning_content,
    choiceDelta?.reasoning,
    choiceMessage?.reasoning_content,
  )
  const content = firstString(
    data.content,
    data.text,
    data.answer,
    typeof data.delta === 'string' ? data.delta : undefined,
    nestedData?.content,
    nestedData?.text,
    nestedData?.answer,
    delta?.content,
    delta?.text,
    delta?.answer,
    message?.content,
    message?.text,
    message?.answer,
    choiceDelta?.content,
    choiceDelta?.text,
    choiceMessage?.content,
    firstChoice?.text,
  )
  const declaredType = firstString(data.type, data.event, nestedData?.type)
  const isReasoning = Boolean(data.is_reasoning)
    || declaredType === 'reasoning'
    || (!!reasoning && !content)
  const type = declaredType || (content || reasoning ? 'text' : '')

  return {
    type,
    content,
    reasoning,
    isReasoning,
    sessionId: firstString(data.session_id, data.sessionId, nestedData?.session_id) || undefined,
    messageId: firstString(data.message_id, data.messageId, nestedData?.message_id) || undefined,
    metadata: asRecord(data.metadata) || nestedData,
    raw: data,
  }
}

export function useAgentChatStream() {
  const isStreaming = ref(false)
  const isPaused = ref(false)
  const abortController = ref<AbortController | null>(null)

  /** 流式连接中断后的自动重试次数（不含首次请求） */
  const STREAM_RETRY_LIMIT = 2
  /** 重试基础间隔（毫秒），按第 N 次 × 该值退避 */
  const STREAM_RETRY_BASE_DELAY_MS = 800

  function isRetryableStreamStatus(status: number): boolean {
    return status === 408 || status === 429 || status === 500 || status === 502 || status === 503 || status === 504
  }

  async function streamChat(
    options: AgentChatStreamOptions,
    callbacks: AgentStreamCallbacks,
  ): Promise<void> {
    if (isStreaming.value) return
    isStreaming.value = true
    isPaused.value = false
    abortController.value = new AbortController()

    let retries = 0

    // 自动重试策略：仅当「连接被掐断且尚未收到任何正文/工具调用」时重试，
    // 避免把已展示给用户的内容重复生成一遍；收到 done / error 或已输出正文则
    // 立即结束（与后端 chat_stream 的「未输出才重试」语义保持一致）。
    // finally 中必须复位 isStreaming：任何 return 路径（done/error/重试耗尽/
    // 用户取消）都不能让它停留在 true，否则下一次发送会被入口守卫直接吞掉。
    try {
    while (true) {
      let receivedContent = false
      let terminalEvent = false
      let transportDropped = false
      let retryExhaustedMessage = '流式连接意外中断，请重新发送；如果频繁出现，请检查模型服务或反向代理超时配置'

      const processLine = (line: string) => {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith("data:")) return
        const data = trimmed.slice(5).trimStart()
        if (!data) return
        try {
          const parsed = JSON.parse(data) as Record<string, unknown>
          const normalized = normalizeAgentStreamEvent(parsed)
          handleStreamEvent(normalized, callbacks)
          if (normalized.type === 'done' || normalized.type === 'error') {
            terminalEvent = true
          } else if (normalized.type) {
            receivedContent = true
          }
        } catch (error) {
          reportChatDiagnostic({
            phase: 'stream-parse',
            rawResponseSummary: data.slice(0, 1000),
            error,
          })
        }
      }

      try {
        const token = localStorage.getItem('access_token')
        const response = await fetch('/api/v1/chat/stream', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            agent_id: options.agentId,
            session_id: options.sessionId,
            mode: options.mode,
            model_id: options.modelId,
            messages: options.messages,
            stream: true,
            temperature: options.temperature,
            max_tokens: options.maxTokens,
            deep_thinking: options.deepThinking,
            attachments: options.attachments || [],
            enable_web_search: options.enableWebSearch || false,
            enable_code_execution: options.enableCodeExecution || false,
            mcp_mode: options.mcpMode || 'auto',
            extra_mcp_servers: options.extraMcpServers || [],
            multi_agent: options.multiAgent ?? false,
            overdrive: options.overdrive,
            extend_max_rounds: options.extendMaxRounds || false,
          }),
          signal: abortController.value?.signal,
        })

        if (!response.ok) {
          const errorText = await response.text()
          if (!isRetryableStreamStatus(response.status)) {
            callbacks.onError?.(`请求失败 (${response.status}): ${errorText}`)
            return
          }
          reportChatDiagnostic({
            phase: 'stream-http-retry',
            rawResponseSummary: `HTTP ${response.status}: ${errorText.slice(0, 1000)}`,
          })
          retryExhaustedMessage = '服务暂时波动，已自动重试仍未恢复，请稍后再试。'
          transportDropped = true
        } else {
          if (!response.body) {
            callbacks.onError?.('浏览器不支持流式响应')
            return
          }

          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split("\n")
            buffer = lines.pop() || ""
            for (const line of lines) processLine(line)
          }

          buffer += decoder.decode()
          if (buffer.trim()) processLine(buffer)

          if (terminalEvent) return
          // 流结束但未收到 done / error：连接被反向代理或网络掐断
          transportDropped = true
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // 用户主动取消
          return
        }
        if (receivedContent) {
          // 已输出正文后再断连：不重试（避免重复内容），直接报错
          callbacks.onError?.(err instanceof Error ? err.message : '未知错误')
          return
        }
        // 网络异常且尚未收到任何内容 → 可重试
        transportDropped = true
      }

      if (!transportDropped || receivedContent) {
        if (transportDropped) {
          callbacks.onError?.("流式连接意外中断，请重新发送；如果频繁出现，请检查模型服务或反向代理超时配置")
        }
        return
      }

      if (retries >= STREAM_RETRY_LIMIT) {
        callbacks.onError?.(retryExhaustedMessage)
        return
      }

      retries += 1
      callbacks.onRetry?.(retries, STREAM_RETRY_LIMIT)
      await new Promise((resolve) => setTimeout(resolve, STREAM_RETRY_BASE_DELAY_MS * retries))
    }
    } finally {
      isStreaming.value = false
      abortController.value = null
    }
  }

  function handleStreamEvent(event: NormalizedAgentStreamEvent, cb: AgentStreamCallbacks): void {
    const data = event.raw
    const { type, content, reasoning, sessionId, messageId, isReasoning } = event

    switch (type) {
      case 'agent_turn_started':
      case 'agent_context_reinjected':
      case 'agent_turn_continued':
      case 'agent_final_result':
      case 'agent_turn_failed':
      case 'agent_loop_guard_triggered':
        cb.onExecutionEvent?.({
          eventType: String(data.event_type || type),
          sessionId: typeof data.session_id === 'string' ? data.session_id : sessionId,
          runId: typeof data.run_id === 'string' ? data.run_id : undefined,
          agentId: typeof data.agent_id === 'string' ? data.agent_id : undefined,
          round: Number(data.round || 0),
          executionPath: typeof data.execution_path === 'string' ? data.execution_path : undefined,
          payload: data,
        })
        break
      case 'text':
      case 'content':
      case 'message':
      case 'delta':
      case 'reasoning':
        cb.onText?.(isReasoning ? reasoning || content : content, isReasoning)
        if (sessionId && messageId) cb.onSessionCreated?.(sessionId, messageId)
        break
      case 'tool_call':
        cb.onToolCall?.({
          tool_call_id: (data.tool_call_id as string) || '',
          tool_name: (data.tool_name as string) || '',
          arguments: (data.arguments as Record<string, unknown>) || {},
          mcp_server: typeof data.mcp_server === 'string' ? data.mcp_server : undefined,
          purpose: typeof data.purpose === 'string' ? data.purpose : undefined,
        })
        break
      case 'mode_changed':
        if (data.mode === 'overdrive') cb.onModeChanged?.(Boolean(data.enabled), Boolean(data.degraded))
        break
      case 'studio_promoted':
        cb.onStudioPromoted?.({
          sessionId,
          agentId: String(data.agent_id || ''),
          agentName: String(data.agent_name || 'AI 工作台'),
          reason: typeof data.reason === 'string' ? data.reason : undefined,
        })
        break
      case 'room_speech': {
        const sender = asRecord(data.sender)
        if (!sender) break
        cb.onRoomSpeech?.({
          sender: {
            agent_id: String(sender.agent_id || ''),
            name: String(sender.name || '专家'),
            avatar: typeof sender.avatar === 'string' ? sender.avatar : undefined,
            color: typeof sender.color === 'string' ? sender.color : undefined,
            role: sender.role === 'worker' ? 'worker' : 'manager',
          },
          content,
          round: Number(data.round) || 1,
          messageId,
          sessionId,
          workerKey: typeof data.worker_key === 'string' ? data.worker_key : undefined,
          thought: typeof data.thought === 'string' ? data.thought : undefined,
          summary: typeof data.summary === 'string' ? data.summary : undefined,
          artifacts: (asRecord(data.artifacts) || undefined) as Record<string, string> | undefined,
          taskStatus: typeof data.task_status === 'string' ? data.task_status : undefined,
          errorSummary: typeof data.error_summary === 'string' ? data.error_summary : undefined,
        })
        if (sessionId && messageId) cb.onSessionCreated?.(sessionId, messageId)
        break
      }
      case 'room_speech_delta': {
        const sender = asRecord(data.sender)
        if (!sender) break
        cb.onRoomSpeechDelta?.({
          sender: {
            agent_id: String(sender.agent_id || ''),
            name: String(sender.name || '专家'),
            avatar: typeof sender.avatar === 'string' ? sender.avatar : undefined,
            color: typeof sender.color === 'string' ? sender.color : undefined,
            role: sender.role === 'worker' ? 'worker' : 'manager',
          },
          content,
          round: Number(data.round) || 1,
          sessionId,
          workerKey: typeof data.worker_key === 'string' ? data.worker_key : undefined,
          isReasoning: Boolean(data.is_reasoning),
        })
        break
      }
      case 'overdrive_progress': {
        const rawTasks = Array.isArray(data.tasks) ? data.tasks : []
        const rawActivities = Array.isArray(data.activities) ? data.activities : []
        cb.onOverdriveProgress?.({
          runId: typeof data.run_id === 'string' ? data.run_id : undefined,
          phase: String(data.phase || 'worker_running') as OverdriveProgressEvent['phase'],
          label: String(data.label || '超频协作进行中'),
          completed: Number(data.completed || 0),
          total: Number(data.total || 0),
          wave: Number(data.wave) || undefined,
          waveTotal: Number(data.wave_total) || undefined,
          waveMode: data.wave_mode === 'parallel' ? 'parallel' : data.wave_mode === 'serial' ? 'serial' : undefined,
          planningOnly: Boolean(data.planning_only) || undefined,
          warning: typeof data.warning === 'string' ? data.warning : undefined,
          activities: rawActivities.map((raw) => {
            const activity = asRecord(raw) || {}
            return {
              id: String(activity.id || ''),
              label: String(activity.label || activity.id || '规划活动'),
              kind: ['model', 'sandbox', 'mcp'].includes(String(activity.kind))
                ? String(activity.kind) as 'model' | 'sandbox' | 'mcp'
                : 'search',
              status: String(activity.status || 'pending'),
              queries: Array.isArray(activity.queries) ? activity.queries.map(String) : undefined,
              accepted: Number(activity.accepted || 0),
              rejected: Number(activity.rejected || 0),
              durationMs: Number(activity.duration_ms || activity.durationMs || 0),
              error: typeof activity.error === 'string' ? activity.error : undefined,
            }
          }),
          tasks: rawTasks.map((raw) => {
            const task = asRecord(raw) || {}
            return {
              taskId: String(task.task_id || ''),
              agentId: String(task.agent_id || ''),
              status: String(task.status || 'pending'),
              errorSummary: typeof task.error_summary === 'string' ? task.error_summary : undefined,
              statusLine: typeof task.status_line === 'string' && task.status_line.trim()
                ? task.status_line.trim()
                : undefined,
            }
          }),
        })
        break
      }
      case 'schedule_fallback':
        cb.onOverdriveProgress?.({ phase: 'workers_starting', label: String(data.label || '已使用默认分工'), completed: 0, total: 0, fallback: true })
        break
      case 'schedule_warning':
        cb.onOverdriveProgress?.({ phase: 'workers_starting', label: String(data.label || '调度已降级'), completed: 0, total: 0, warning: String(data.label || '') })
        break
      case 'worker_stalled':
        cb.onOverdriveProgress?.({ phase: 'worker_running', label: String(data.label || '任务长时间无新进度'), completed: 0, total: 0, stalledTaskId: String(data.task_id || '') })
        break
      case 'overdrive_approval_request': {
        const approval = asRecord(data.approval)
        if (!approval || typeof approval.approval_id !== 'string' || typeof approval.tool_name !== 'string') break
        cb.onOverdriveApproval?.({
          approval: {
            approval_id: approval.approval_id,
            run_id: typeof approval.run_id === 'string' ? approval.run_id : undefined,
            tool_name: approval.tool_name,
            arguments: (asRecord(approval.arguments) || {}) as Record<string, unknown>,
            status: String(approval.status || 'pending') as OverdriveApprovalEvent['approval']['status'],
            result: asRecord(approval.result),
            error: typeof approval.error === 'string' ? approval.error : undefined,
            reason: typeof approval.reason === 'string' ? approval.reason : undefined,
            case_id: typeof approval.case_id === 'string' ? approval.case_id : undefined,
          },
          workerKey: typeof data.worker_key === 'string' ? data.worker_key : undefined,
          agentId: typeof data.agent_id === 'string' ? data.agent_id : undefined,
        })
        break
      }
      case 'subagents': {
        const phase = data.phase === 'aggregated' ? 'aggregated' : 'started'
        const rawTasks = Array.isArray(data.tasks) ? data.tasks : []
        const rawProgress = Array.isArray(data.progress) ? data.progress : []
        // started 带 tasks[{index,agent_id,task}]；aggregated 带 progress[{index,agent_id,status,elapsed_s}]
        const tasks =
          phase === 'aggregated'
            ? rawProgress.map((raw) => {
                const item = asRecord(raw) || {}
                return {
                  index: Number(item.index || 0),
                  agentId: String(item.agent_id || ''),
                  task: '',
                  status: String(item.status || 'completed') === 'ok'
                    ? 'succeeded'
                    : String(item.status || 'completed'),
                }
              })
            : rawTasks.map((raw) => {
                const item = asRecord(raw) || {}
                return {
                  index: Number(item.index || 0),
                  agentId: String(item.agent_id || ''),
                  task: String(item.task || ''),
                  status: 'running',
                }
              })
        cb.onSubagentFanout?.({
          phase,
          toolCallId: String(data.tool_call_id || ''),
          tasks,
          success: phase === 'aggregated' ? Boolean(data.success) : undefined,
          summary: phase === 'aggregated' ? String(data.summary || '') : undefined,
        })
        break
      }
      case 'tool_result':
        cb.onToolResult?.({
          tool_call_id: (data.tool_call_id as string) || '',
          tool_name: (data.tool_name as string) || '',
          success: Boolean(data.success),
          result: data.result,
          ui_payload: (data.ui_payload as Record<string, unknown>) || undefined,
          mcp_server: typeof data.mcp_server === 'string' ? data.mcp_server : undefined,
          checkpoint_id: typeof data.checkpoint_id === 'string' ? data.checkpoint_id : undefined,
        })
        break
      case 'web_search_results':
        cb.onWebSearchResults?.(
          (Array.isArray(data.sources) ? data.sources : [])
            .filter((source): source is Record<string, unknown> => !!source && typeof source === 'object')
            .filter((source) => typeof source.title === 'string' && typeof source.url === 'string')
            .map((source) => ({
              title: source.title as string,
              url: source.url as string,
              snippet: typeof source.snippet === 'string' ? source.snippet : '',
              publishedAt: typeof source.publishedAt === 'string' ? source.publishedAt : null,
            })),
        )
        break
      case 'handoff':
        cb.onHandoff?.({
          source_agent_id: (data.source_agent_id as string) || '',
          source_agent_name: typeof data.source_agent_name === 'string' ? data.source_agent_name : undefined,
          target_agent_id: (data.target_agent_id as string) || '',
          target_agent_name: typeof data.target_agent_name === 'string' ? data.target_agent_name : undefined,
          reason: (data.reason as string) || '',
          handoff_summary: typeof data.handoff_summary === 'string' ? data.handoff_summary : undefined,
          user_intent: typeof data.user_intent === 'string' ? data.user_intent : undefined,
          artifacts: Array.isArray(data.artifacts) ? data.artifacts.filter((item): item is string => typeof item === 'string') : [],
          constraints: Array.isArray(data.constraints) ? data.constraints.filter((item): item is string => typeof item === 'string') : [],
          hop_index: Number(data.hop_index) || 1,
        })
        break
      case 'agentteams_case':
        cb.onAgentTeamsCase?.({
          phase: data.phase === 'status_changed' ? 'status_changed' : 'created',
          case_id: (data.case_id as string) || '',
          title: (data.title as string) || '协作 Case',
          status: (data.status as string) || 'received',
          next_actor: (data.next_actor as string) || '协作团队',
          case_url: (data.case_url as string) || '',
          session_id: typeof data.session_id === 'string' ? data.session_id : undefined,
          message_id: typeof data.message_id === 'string' ? data.message_id : undefined,
        })
        break
      case 'tool_output':
        cb.onToolOutput?.(
          (data.tool as string) || '',
          data.stream === 'stderr' ? 'stderr' : 'stdout',
          (data.data as string) || '',
          (data.tool_call_id as string) || undefined,
        )
        break
      case 'skill':
        {
          const phase = data.phase === 'completed' || data.phase === 'failed' ? data.phase : 'invoked'
          cb.onSkill?.({
            phase,
            tool_call_id: (data.tool_call_id as string) || '',
            message_id: typeof data.message_id === 'string' ? data.message_id : undefined,
            skill_id: (data.skill_id as string) || '',
            name: (data.name as string) || '',
            version: (data.version as string) || '',
            source: (data.source as string) || '',
            icon: (data.icon as string) || '🧩',
            agent: typeof data.agent === 'string' ? data.agent : undefined,
            duration_ms: typeof data.duration_ms === 'number' ? data.duration_ms : undefined,
            summary: typeof data.summary === 'string' ? data.summary : undefined,
            error: typeof data.error === 'string' ? data.error : undefined,
          })
        }
        break
      case 'plan':
        cb.onPlan?.((Array.isArray(data.steps) ? data.steps : []) as StudioPlanStep[])
        break
      case 'approval_request':
        cb.onApprovalRequest?.({
          approval_id: (data.approval_id as string) || '',
          tool_call_id: (data.tool_call_id as string) || '',
          tool_name: (data.tool_name as string) || '',
          arguments: (data.arguments as Record<string, unknown>) || {},
          risk_hint: (data.risk_hint as string) || undefined,
          timeout_seconds: (data.timeout_seconds as number) || undefined,
          approval_kind: data.approval_kind === 'plan' ? 'plan' : 'tool',
        })
        break
      case 'approval_resolved':
        cb.onApprovalResolved?.({
          approval_id: (data.approval_id as string) || '',
          tool_call_id: (data.tool_call_id as string) || '',
          action: ((data.action as string) || 'approved') as ApprovalAction,
        })
        break
      case 'loop_guard_triggered':
        cb.onLoopGuardTriggered?.({
          reason: ((data.reason as string) || 'max_tool_calls_per_turn') as LoopGuardTriggeredEvent['reason'],
          tool_calls: Number(data.tool_calls || 0),
          consecutive_failures: Number(data.consecutive_failures || 0),
          tool_name: typeof data.tool_name === 'string' ? data.tool_name : undefined,
          error_type: typeof data.error_type === 'string' ? data.error_type : undefined,
          downgraded_to_supervised: Boolean(data.downgraded_to_supervised),
        })
        break
      case 'ask_request':
        {
          const planConfirmation = normalizePlanConfirmation(data)
          const rawQuestions = Array.isArray(data.questions) ? data.questions : []
          const questions = rawQuestions
            .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
            .map((item) => ({
              question: typeof item.question === 'string' ? item.question : '',
              options: Array.isArray(item.options) ? (item.options as string[]) : undefined,
            }))
          // 兼容旧后端：无 questions 数组时退回平铺的 question/options
          if (!questions.length) {
            const single = (data.question as string) || content
            if (single) {
              questions.push({
                question: single,
                options: Array.isArray(data.options) ? (data.options as string[]) : undefined,
              })
            }
          }
          // 兜底一个空问题：卡片渲染自由输入，保证用户总能回复、已回答摘要不会空白
          if (!questions.length) {
            questions.push({ question: '', options: undefined })
          }
          cb.onAskRequest?.({
            tool_call_id: (data.tool_call_id as string) || '',
            kind: planConfirmation ? 'plan_confirmation' : 'questions',
            questions,
            planConfirmation,
          })
        }
        break
      case 'route': {
        const transition = asRecord(data.transition)
        cb.onRoute?.({
          agent_id: (data.agent_id as string) || '',
          name: (data.name as string) || '',
          avatar: (data.avatar as string) || '',
          color: (data.color as string) || '',
          reason: (data.reason as string) || '',
          intent: typeof data.intent === 'string' ? data.intent : undefined,
          confidence: typeof data.confidence === 'number' ? data.confidence : undefined,
          transition: transition
            ? {
                visible: Boolean(transition.visible),
                stage:
                  transition.stage === 'execution_ready'
                    ? 'execution_ready'
                    : 'specialist_intake',
                title: String(transition.title || '已匹配专项专家'),
                message: String(transition.message || ''),
                next_step: String(transition.next_step || '专项 Agent 进行任务 intake'),
                requires_execution_confirmation: Boolean(transition.requires_execution_confirmation),
                auto_start: Boolean(transition.auto_start),
              }
            : undefined,
        })
        break
      }
      case 'round_limit':
        cb.onRoundLimit?.({
          sessionId: sessionId || '',
          messageId: messageId || '',
          maxRounds: Number(data.max_rounds) || 0,
          canExtend: Boolean(data.can_extend),
        })
        break
      case 'context_compressed':
        cb.onContextCompressed?.(Number(data.estimated_tokens_before) || 0)
        break
      case 'consultation':
        cb.onConsultation?.({
          experts: Array.isArray(data.experts)
            ? data.experts
                .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
                .map((item) => ({
                  agent_id: typeof item.agent_id === 'string' ? item.agent_id : '',
                  name: typeof item.name === 'string' ? item.name : '专家',
                  opinion: typeof item.opinion === 'string' ? item.opinion : '',
                }))
            : [],
          consultation_id: typeof data.consultation_id === 'string' ? data.consultation_id : undefined,
          consultation_summary: typeof data.consultation_summary === 'string' ? data.consultation_summary : undefined,
          case_available: typeof data.case_available === 'boolean' ? data.case_available : undefined,
        })
        break
      case 'collaboration_route':
        cb.onCollaborationRoute?.({
          intent: ((data.intent as CollaborationRouteEvent['intent']) || 'chat'),
          label: (data.label as string) || '协作路径',
          reason: (data.reason as string) || '',
          confidence: Number(data.confidence) || 0,
          available: Boolean(data.available),
          degraded: Boolean(data.degraded),
          message: (data.message as string) || '',
        })
        break
      case 'error':
        cb.onError?.(content || '生成失败')
        break
      case 'done':
        {
          if (sessionId && messageId) cb.onSessionCreated?.(sessionId, messageId)
          const usage = data.usage as TokenUsage | undefined
          const finishReason = data.finish_reason as string | undefined
          cb.onDone?.(
            sessionId || '',
            messageId || '',
            usage,
            finishReason,
            content,
            reasoning,
          )
        }
        break
    }
  }

  function abortStream(): void {
    abortController.value?.abort()
    isStreaming.value = false
    isPaused.value = false
  }

  /** 暂停流式输出：中断连接但保留已输出文本，标记为暂停态 */
  function pauseStream(): void {
    abortController.value?.abort()
    isStreaming.value = false
    isPaused.value = true
  }

  /** 重置暂停状态（重新生成前调用） */
  function resetPause(): void {
    isPaused.value = false
  }

  return { isStreaming, isPaused, streamChat, abortStream, pauseStream, resetPause }
}
