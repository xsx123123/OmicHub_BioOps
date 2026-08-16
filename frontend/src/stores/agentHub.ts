/**
 * 多智能体协作平台 Store — 真实后端联动版
 *
 * 资产（Agent / MCP / Skill）从后端 API 加载；会话客户端管理 + welcome_message 首屏；
 * 发消息走 Agent 调度中枢 SSE 流式（agent_id → 后端组装模型/系统词/MCP 工具 → 流式回）。
 *
 * 消息结构复用 @/components/ai-chat/types 的 ChatMessage，便于直接喂给
 * KimiMessageList / KimiChatInput 等已解耦的聊天组件。
 *
 * TODO: 在 Agent-first 架构稳定后，chatSession / chatAssistant 等模型优先 Store 应废弃，
 * chatStore 中与 UI 相关的设置（sidebarCollapsed / deepThinking / conversationSettings）
 * 可进一步收敛到独立的 uiSettingsStore，会话与智能体逻辑保留在 agentHub。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { isToday, isYesterday, parseISO } from 'date-fns'
import type {
  AgentCategory,
  AgentTemplate,
  McpLogEntry,
  McpService,
  McpTool,
  McpVersion,
  SkillItem,
  SkillVersion,
} from '@/types/agent'
import type {
  AliyunMarketStatus,
  SkillImportPreview,
  SkillInvocationRecord,
  SkillInvocationStat,
  SkillMarketplaceItem,
  SkillReference,
  SkillUpdateCheck,
  SkillVersionDetail,
} from '@/types/skill'
import type {
  AgentTeamsCaseCardPayload,
  ChatMessage,
  CollaborationRouteInfo,
  PlanConfirmation,
  PlanDecisionAction,
  ToolCall,
  FileAttachment,
  ChartData,
} from '@/components/ai-chat/types'
import { agentTeamsApi } from '@/api/agentTeams'
import { agentApi, adminAgentApi } from '@/api/agent'
import { chatApi } from '@/api/chat'
import apiClient from '@/api/client'
import { reportChatDiagnostic } from '@/utils/chatDiagnostics'
import {
  normalizePlanConfirmation,
  useAgentChatStream,
  type StudioPlanStep,
  type TokenUsage,
} from '@/composables/useAgentChatStream'
import { studioApi, type StudioPermissionMode } from '@/api/studio'
import { useChatStore } from '@/stores/chat'
import { sortPersistedChatMessages } from '@/utils/chatMessageOrder'
import { resolveRoleIdentity } from '@/utils/roleIdentity'
import type {
  PipelineSubmitResult,
  PipelineTask,
  PipelineTaskStatus,
  PipelineType,
} from '@/types/pipeline'

const STUDIO_OUTPUT_CAP = 20_000

function toMcpService(mcp: any): McpService {
  return {
    id: String(mcp.id),
    name: mcp.name,
    description: mcp.description ?? '',
    status: mcp.status === 'online' ? 'online' : 'offline',
    transport: mcp.transport ?? 'builtin',
    command: mcp.command ?? '',
    args: mcp.args ?? [],
    url: mcp.url ?? '',
    env: mcp.env ?? {},
    registry: mcp.registry ?? 'default',
    working_dir: mcp.working_dir ?? '',
    version: mcp.version ?? '',
    is_enabled: mcp.is_enabled ?? true,
    tools: mcp.tools ?? [],
    timeout: mcp.timeout ?? 30,
    auto_restart: mcp.auto_restart ?? true,
    tool_count: mcp.tool_count ?? 0,
    is_preset: !!mcp.is_preset,
  }
}

function appendBoundedStudioOutput(current: string, data: string): string {
  const combined = current + data
  if (combined.length <= STUDIO_OUTPUT_CAP) return combined
  return `…\n${combined.slice(-(STUDIO_OUTPUT_CAP - 2))}`
}

/** 移除会话内的「连接中断，自动重试中」临时提示（流结束/失败后清理，避免污染上下文） */
function cleanupStreamRetryNotices(session: { messages: ChatMessage[] }): void {
  session.messages = session.messages.filter((m) => !m.id.startsWith('stream-retry-'))
}

export const CATEGORY_LABELS: Record<AgentCategory, string> = {
  general: '通用',
  analysis: '分析',
  code: '编程',
  visualization: '可视化',
}

/** 前台会话（客户端管理，绑定 Agent） */
export interface AgentSession {
  id: string
  title: string
  title_locked?: boolean
  agent_id: string
  mode?: 'chat' | 'studio'
  messages: ChatMessage[]
  created_at: string
  updated_at: string
  /** 当前会话使用的模型配置 ID（覆盖 Agent 默认模型） */
  model_id?: string
  mcp_mode?: 'off' | 'auto' | 'manual'
  extra_mcp_servers?: string[]
  /** 当前会话启用 AgentTeams multi-agent 协作运行时 */
  multi_agent?: boolean
  overdrive?: boolean
}

/** 可用模型选项（来自 /api/v1/chat/models） */
export interface AvailableModel {
  id: string
  name: string
  model: string
  provider_type: string
  is_default: boolean
  temperature?: number
  max_tokens?: number
}

export const useAgentHubStore = defineStore('agentHub', () => {
  // ========== State ==========
  const mcps = ref<McpService[]>([])
  const skills = ref<SkillItem[]>([])
  const agents = ref<AgentTemplate[]>([])
  const sessions = ref<AgentSession[]>([])
  const currentSessionId = ref<string>('')

  const isStreaming = ref(false)
  const streamingContent = ref('')
  const streamingThought = ref('')
  /** 工具调用轮次触顶时置位，聊天界面据此弹窗询问是否以扩展上限（1000 轮）继续 */
  const roundLimitPrompt = ref<{ sessionId: string; maxRounds: number } | null>(null)
  /** 上下文超窗触发历史压缩时置位（值为压缩前估算 token），聊天界面据此提示 */
  const contextCompressedNotice = ref<number | null>(null)
  /** 路由/交接命中 default_mode=studio 的 Agent 时置位，聊天界面据此自动跳转 AI 工作台 */
  const studioRedirect = ref<{ agentId: string; agentName: string } | null>(null)

  /** 目标 Agent 声明默认工作台模式且当前是普通聊天会话时，发起工作台跳转 */
  function maybeRedirectToStudio(agentId: string, agentName: string): void {
    const session = currentSession.value
    if (!session || session.mode === 'studio') return
    if (studioSessionIds.value.has(session.id)) return
    if (studioRedirect.value?.agentId === agentId) return
    const target = getAgent(agentId)
    if ((target?.features as any)?.studio?.default_mode === 'studio') {
      studioRedirect.value = { agentId, agentName }
    }
  }

  function clearStudioRedirect(): void {
    studioRedirect.value = null
  }
  const availableModels = ref<AvailableModel[]>([])
  const pipelineTasks = ref<Record<string, PipelineTask>>({})
  const pipelinePollTimers = new Map<string, ReturnType<typeof setTimeout>>()

  /** Studio（工作台）会话 ID 集合：供会话列表打 📊 角标（后端 ChatSessionDTO 无 mode 字段，前端绕道获取） */
  const studioSessionIds = ref<Set<string>>(new Set())
  const currentPlan = ref<StudioPlanStep[]>([])
  /** 当前 Studio 会话的权限模式（supervised=关键操作需批准；auto=放权自动执行） */
  const studioPermissions = ref<{ mode: StudioPermissionMode }>({ mode: 'supervised' })

  const { streamChat, abortStream, isPaused, pauseStream, resetPause } = useAgentChatStream()

  /**
   * 临时会话 ID 解析锁。
   * Agent 工作流先创建客户端临时 `sess-` ID，等待 SSE 返回真实 session_id 后回填。
   * 该锁保证在回填完成前，后续消息不会携带临时 ID 重复触发后端创建多个会话。
   */
  let pendingSessionIdResolver: (() => void) | null = null
  let pendingSessionIdPromise: Promise<void> | null = null
  let agentTeamsEventAbort: AbortController | null = null
  let agentTeamsEventGeneration = 0
  const agentTeamsEventCursors = new Map<string, string>()
  const agentTeamsSeenEventKeys = new Map<string, Set<string>>()
  let overdriveEventAbort: AbortController | null = null
  let overdriveEventSessionId = ''
  let overdriveEventRunId = ''
  /** 每个 run 已投影到 UI 的最后事件序号；重放与重连都经过同一闸门。 */
  const overdriveEventCursors = new Map<string, number>()

  type AgentTeamsCaseStreamEvent = AgentTeamsCaseCardPayload & {
    type: 'agentteams_case'
    phase: 'status_changed'
    session_id?: string
    message_id?: string
  }

  function applyAgentTeamsCaseEvent(event: AgentTeamsCaseStreamEvent) {
    const session = event.session_id
      ? sessions.value.find((item) => item.id === event.session_id)
      : currentSession.value
    if (!session || !event.case_id) return
    const card: AgentTeamsCaseCardPayload = {
      case_id: event.case_id,
      title: event.title || '协作 Case',
      status: event.status || 'received',
      next_actor: event.next_actor || '协作团队',
      case_url: event.case_url || `/agent-teams/cases/${event.case_id}`,
      updated_at: new Date().toISOString(),
    }
    const existing = session.messages.find((message) => message.id === event.message_id)
    if (existing) return
    session.messages.push({
      id: event.message_id || `agentteams-${event.case_id}-${event.status}-${Date.now()}`,
      role: 'system',
      content: `协作 Case「${card.title}」状态更新为「${card.status}」，下一步请由 ${card.next_actor} 处理。`,
      agentTeamsCases: [card],
      createdAt: new Date().toISOString(),
    })
    session.updated_at = new Date().toISOString()
  }

  function stopAgentTeamsCaseEvents() {
    agentTeamsEventGeneration += 1
    agentTeamsEventAbort?.abort()
    agentTeamsEventAbort = null
  }

  type RoomSpeechStreamEvent = {
    type: 'room_speech'
    content: string
    sender: {
      agent_id?: string
      name?: string
      avatar?: string
      color?: string
      role?: 'manager' | 'worker'
    }
    round?: number
    session_id?: string
    message_id?: string
  }

  function applyCaseRoomEvent(event: Record<string, any>, expectedSessionId?: string) {
    const eventSessionId = typeof event.session_id === 'string' ? event.session_id : ''
    if (expectedSessionId && eventSessionId && eventSessionId !== expectedSessionId) return
    const session = event.session_id
      ? sessions.value.find((item) => item.id === event.session_id)
      : expectedSessionId
        ? sessions.value.find((item) => item.id === expectedSessionId)
        : currentSession.value
    if (!session) return
    const runId = typeof event.run_id === 'string' ? event.run_id : ''
    const sequence = Number(event.sequence)
    if (runId && Number.isFinite(sequence) && sequence > 0) {
      const cursor = overdriveEventCursors.get(runId) || 0
      if (sequence <= cursor) return
      overdriveEventCursors.set(runId, sequence)
    }
    if (event.type === 'ask_request' && event.kind === 'plan_confirmation') {
      const planConfirmation = normalizePlanConfirmation(event)
      if (!planConfirmation) return
      const id = `plan-confirmation-${planConfirmation.runId}`
      const existing = session.messages.find((message) =>
        message.askRequest?.planConfirmation?.runId === planConfirmation.runId)
      if (existing) {
        const previous = existing.askRequest?.planConfirmation
        // Event replay starts from a durable cursor and can include the already
        // decided snapshot.  Never resurrect an approved/revision-requested
        // version as a pending card; only a strictly newer frozen plan may
        // replace it.
        if (previous
          && (planConfirmation.planVersion < previous.planVersion
            || (planConfirmation.planVersion === previous.planVersion
              && previous.status !== 'pending'))) return
        existing.askRequest = { kind: 'plan_confirmation', questions: [], planConfirmation, answered: false }
      } else {
        session.messages.push({
          id,
          role: 'system',
          content: '',
          askRequest: { kind: 'plan_confirmation', questions: [], planConfirmation, answered: false },
          createdAt: new Date().toISOString(),
        })
      }
      session.updated_at = new Date().toISOString()
      return
    }
    if (event.type === 'ask_request') {
      const questions = Array.isArray(event.questions) ? event.questions : []
      if (!questions.length) return
      const id = event.message_id || `overdrive-ask-${event.run_id || 'active'}`
      const askRequest: NonNullable<ChatMessage['askRequest']> = {
        kind: 'questions',
        questions: questions.map((question: any) => ({
          question: String(question?.question || question || '请补充必要信息'),
          options: Array.isArray(question?.options) ? question.options.map(String) : [],
        })),
        answered: false,
      }
      const existing = session.messages.find((message) => message.id === id)
      if (existing) existing.askRequest = askRequest
      else session.messages.push({
        id,
        role: 'system',
        content: '',
        askRequest,
        createdAt: new Date().toISOString(),
      })
      session.updated_at = new Date().toISOString()
      return
    }
    if (event.type === 'room_speech') {
      applyRoomSpeechEvent(event as RoomSpeechStreamEvent)
      return
    }
    if (event.type === 'overdrive_progress') {
      const id = runId ? `overdrive-progress-${runId}` : `case-progress-${event.case_id || 'active'}`
      let existing = session.messages.find((message) =>
        message.id === id || (runId && message.overdriveProgress?.runId === runId))
      if (!existing && runId) {
        // 首轮 SSE 可能先创建了没有 run_id 的兼容进度卡；一旦收到持久化事件，
        // 将它升级为 run 级确定性 id，避免同一 run 出现两张进度卡。
        existing = [...session.messages].reverse().find((message) =>
          message.role === 'system' && message.overdriveProgress && !message.overdriveProgress.runId)
        if (existing) existing.id = id
      }
      const progress: NonNullable<ChatMessage['overdriveProgress']> = {
        runId: typeof event.run_id === 'string' ? event.run_id : undefined,
        caseId: typeof event.case_id === 'string' ? event.case_id : undefined,
        phase: event.phase || 'worker_running',
        label: event.label || '协作 Case 推进中',
        completed: Number(event.completed ?? 0),
        total: Number(event.total ?? 0),
        wave: typeof event.wave === 'number' ? event.wave : undefined,
        waveTotal: typeof event.waveTotal === 'number' ? event.waveTotal : undefined,
        waveMode: event.waveMode === 'parallel' ? 'parallel' : event.waveMode === 'serial' ? 'serial' : undefined,
        planningOnly: Boolean((event as any).planning_only) || undefined,
        readonly: Boolean(event.readonly) || ['completed', 'failed', 'terminated'].includes(event.phase),
        warning: typeof event.warning === 'string' ? event.warning : undefined,
        stalledTaskIds: Array.isArray(event.stalledTaskIds) ? event.stalledTaskIds.map(String) : undefined,
        activities: Array.isArray(event.activities) ? event.activities : undefined,
        tasks: Array.isArray(event.tasks) ? event.tasks : [],
        artifacts: Array.isArray(event.artifacts)
          ? event.artifacts.map((artifact: any) => ({
            path: String(artifact?.path || ''),
            kind: typeof artifact?.kind === 'string' ? artifact.kind : undefined,
            status: typeof artifact?.status === 'string' ? artifact.status : undefined,
            source: typeof artifact?.source === 'string' ? artifact.source : undefined,
            qualityStatus: typeof artifact?.quality_status === 'string'
              ? artifact.quality_status
              : undefined,
            downloadUrl: typeof artifact?.download_url === 'string' ? artifact.download_url : undefined,
            previewUrl: typeof artifact?.preview_url === 'string' ? artifact.preview_url : undefined,
          })).filter((artifact: { path: string }) => artifact.path)
          : [],
      }
      if (existing) existing.overdriveProgress = progress
      else session.messages.push({ id, role: 'system', content: progress.label, overdriveProgress: progress, createdAt: new Date().toISOString() })
      if (progress.phase === 'terminated' && runId) {
        const planMessage = [...session.messages].reverse().find(
          (message) => message.askRequest?.planConfirmation?.runId === runId,
        )
        const plan = planMessage?.askRequest?.planConfirmation
        if (plan && ['pending', 'submitting'].includes(plan.status)) {
          plan.status = 'cancelled'
          if (planMessage?.askRequest) planMessage.askRequest.answered = true
        }
      }
      session.updated_at = new Date().toISOString()
      return
    }
    if (event.type === 'overdrive_approval_request' && event.approval) {
      const approval = event.approval
      const id = `case-approval-${approval.approval_id}`
      const existing = session.messages.find((message) => message.id === id)
      const nextApproval: NonNullable<ChatMessage['overdriveApproval']> = {
        approvalId: String(approval.approval_id || ''),
        runId: typeof approval.run_id === 'string' ? approval.run_id : undefined,
        caseId: String(approval.case_id || event.case_id || ''),
        toolName: String(approval.tool_name || 'submit_task'),
        arguments: approval.arguments || {},
        status: approval.status || 'pending',
        result: approval.result,
        error: approval.error,
        reason: approval.reason,
      }
      if (existing) {
        existing.overdriveApproval = nextApproval
        session.updated_at = new Date().toISOString()
        return
      }
      session.messages.push({
        id,
        role: 'system',
        content: '协作 Case 等待你的审批',
        overdriveApproval: nextApproval,
        createdAt: new Date().toISOString(),
      })
      session.updated_at = new Date().toISOString()
      return
    }
    if (event.type === 'mode_changed' && event.mode === 'overdrive') {
      session.overdrive = Boolean(event.enabled)
      session.messages.push({
        id: `case-mode-${Date.now()}`,
        role: 'system',
        content: event.enabled ? '协作 Case 已进入团队协作模式。' : '协作 Case 已完成，恢复普通对话。',
        createdAt: new Date().toISOString(),
      })
      session.updated_at = new Date().toISOString()
    }
  }

  function applyRoomSpeechEvent(event: RoomSpeechStreamEvent) {
    const session = event.session_id
      ? sessions.value.find((item) => item.id === event.session_id)
      : currentSession.value
    if (!session || !event.content) return
    const id = event.message_id || `case-room-${Date.now()}`
    if (session.messages.some((message) => message.id === id || message.backendMessageId === id)) return
    const agentId = event.sender.agent_id || 'external'
    const identity = resolveRoleIdentity(agentId, {
      name: event.sender.name,
      avatar: event.sender.avatar,
      color: event.sender.color,
      role: event.sender.role,
    })
    session.messages.push({
      id,
      backendMessageId: event.message_id,
      role: 'assistant',
      content: event.content,
      status: 'complete',
      senderAgent: {
        id: agentId,
        name: identity.name,
        avatar: identity.avatar,
        color: identity.color,
        role: identity.role,
        round: event.round,
      },
      createdAt: new Date().toISOString(),
    })
    session.updated_at = new Date().toISOString()
  }

  function stopOverdriveEvents() {
    overdriveEventAbort?.abort()
    overdriveEventAbort = null
    overdriveEventSessionId = ''
    overdriveEventRunId = ''
  }

  async function replayActiveOverdriveEvents(
    sessionId: string,
    runId: string,
    afterSequence = 0,
  ): Promise<{ cursor: number; status?: string; ok: boolean }> {
    try {
      const response = await apiClient.get(
        `/chat/sessions/${sessionId}/overdrive-runs/${runId}/events`,
        { params: { after_sequence: afterSequence } },
      )
      const projected = Array.isArray(response.data?.projected_events)
        ? response.data.projected_events
        : []
      for (const event of projected) applyCaseRoomEvent(event, sessionId)
      return {
        cursor: Number(response.data?.event_cursor) || afterSequence,
        status: typeof response.data?.run?.status === 'string' ? response.data.run.status : undefined,
        ok: true,
      }
    } catch {
      // 主历史加载不应被增量事件恢复失败阻塞；长连接/下一次刷新仍可重试。
      return { cursor: afterSequence, ok: false }
    }
  }

  async function startOverdriveEvents(sessionId: string, runId: string, afterSequence = 0) {
    stopOverdriveEvents()
    let cursor = Math.max(0, afterSequence)
    let reconnects = 0
    const terminalStatuses = new Set(['COMPLETED', 'CANCELLED', 'TERMINATED', 'FAILED'])
    while (currentSessionId.value === sessionId) {
      const controller = new AbortController()
      overdriveEventAbort = controller
      overdriveEventSessionId = sessionId
      overdriveEventRunId = runId
      const connectionStartCursor = cursor
      try {
        const token = localStorage.getItem('access_token')
        const response = await fetch(
          `/api/v1/chat/sessions/${sessionId}/overdrive-runs/${runId}/stream?after_sequence=${cursor}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal },
        )
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const consumeLine = (line: string) => {
          if (!line.startsWith('data:')) return
          const raw = line.slice(5).trim()
          if (!raw || raw === '[DONE]') return
          try {
            const event = JSON.parse(raw) as Record<string, any>
            if (typeof event.run_id === 'string' && event.run_id !== runId) return
            applyCaseRoomEvent(event, sessionId)
            const sequence = Number(event.sequence)
            if (Number.isFinite(sequence) && sequence > cursor) cursor = sequence
          } catch {
            // 单条损坏事件不终止可恢复流。
          }
        }
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) consumeLine(line)
        }
        if (buffer.trim()) consumeLine(buffer)
      } catch (error) {
        if (controller.signal.aborted || currentSessionId.value !== sessionId) return
        if (reconnects >= 5) {
          console.warn('超频后台事件连接多次中断，等待用户重新进入会话恢复', error)
          return
        }
      } finally {
        if (overdriveEventAbort === controller) overdriveEventAbort = null
      }

      if (controller.signal.aborted || currentSessionId.value !== sessionId) return
      // 无论是服务端正常结束还是代理断开，都以 DB 游标做一次边界重放：
      // 它既补上最后一个没有换行符的事件，也给出最新 run 状态，避免在终态重连。
      const boundary = await replayActiveOverdriveEvents(sessionId, runId, cursor)
      cursor = Math.max(cursor, boundary.cursor)
      if (terminalStatuses.has(boundary.status || '')) return
      if (cursor > connectionStartCursor) reconnects = 0
      else reconnects += 1
      if (reconnects >= 5) {
        console.warn('超频后台事件连接多次无新事件，等待用户重新进入会话恢复')
        return
      }
      await new Promise((resolve) => setTimeout(resolve, Math.min(5000, 500 * 2 ** reconnects)))
    }
  }

  async function recoverOverdriveRun(sessionId: string): Promise<void> {
    if (!sessionId || sessionId.startsWith('sess-') || currentSessionId.value !== sessionId) return
    try {
      const activeRun = await chatApi.getActiveOverdriveRun(sessionId)
      const recoverableRun = activeRun || await chatApi.getLatestOverdriveRun(sessionId)
      if (!recoverableRun || currentSessionId.value !== sessionId) {
        const knownRunId = [...(currentSession.value?.messages || [])].reverse()
          .map((message) => message.askRequest?.planConfirmation?.runId || message.overdriveProgress?.runId)
          .find((runId): runId is string => Boolean(runId))
        if (knownRunId && currentSessionId.value === sessionId) {
          await replayActiveOverdriveEvents(sessionId, knownRunId, 0)
        }
        return
      }
      const activeRunId = recoverableRun.run_id
      if (recoverableRun.status === 'AWAITING_PLAN_CONFIRMATION' && recoverableRun.plan) {
        applyCaseRoomEvent({
          type: 'ask_request',
          kind: 'plan_confirmation',
          run_id: activeRunId,
          session_id: sessionId,
          plan_path: recoverableRun.plan.path,
          plan_version: recoverableRun.plan.version,
          plan_hash: recoverableRun.plan.hash,
          summary: recoverableRun.plan.summary,
          actions: recoverableRun.plan.actions,
        }, sessionId)
      }
      const snapshotPhase: Record<string, string> = {
        SERIAL_PREFLIGHT: 'serial_preflight',
        RECRUITING: 'recruiting',
        RUNNING: 'worker_running',
        WAITING_FOR_RESULTS: 'worker_running',
        AWAITING_USER_INPUT: 'awaiting_input',
        AWAITING_APPROVAL: 'awaiting_approval',
        PAUSED: 'paused',
      }
      if (snapshotPhase[recoverableRun.status]) {
        const snapshotTasks = Array.isArray(recoverableRun.tasks) ? recoverableRun.tasks : []
        const snapshotLabel = recoverableRun.status === 'SERIAL_PREFLIGHT'
          ? '计划已确认，等待 analysis Worker 接管'
          : `超频任务正在后台推进（${recoverableRun.status}）`
        applyCaseRoomEvent({
          type: 'overdrive_progress',
          run_id: activeRunId,
          session_id: sessionId,
          phase: snapshotPhase[recoverableRun.status],
          label: snapshotLabel,
          completed: snapshotTasks.filter((task) =>
            ['succeeded', 'failed', 'skipped', 'cancelled'].includes(String(task.status || ''))).length,
          total: snapshotTasks.length,
          tasks: snapshotTasks.map((task) => ({
            taskId: String(task.task_id || ''),
            agentId: String(task.agent_id || ''),
            status: String(task.status || 'pending'),
            errorSummary: typeof task.error_summary === 'string' ? task.error_summary : undefined,
          })),
          artifacts: Array.isArray(recoverableRun.artifact_index) ? recoverableRun.artifact_index : [],
        }, sessionId)
      }
      if (overdriveEventSessionId === sessionId
        && overdriveEventRunId === activeRunId
        && overdriveEventAbort) return
      const snapshotCursor = Number(recoverableRun.event_cursor || 0)
      const boundary = await replayActiveOverdriveEvents(sessionId, activeRunId, 0)
      if (currentSessionId.value !== sessionId) return
      const cursor = boundary.ok ? Math.max(snapshotCursor, boundary.cursor) : 0
      const status = boundary.status || recoverableRun.status
      if (activeRun && !['COMPLETED', 'CANCELLED', 'TERMINATED', 'FAILED'].includes(status)) {
        void startOverdriveEvents(sessionId, activeRunId, cursor)
      }
    } catch (error) {
      console.warn('恢复超频历史卡片失败，将在下次进入会话时重试', error)
      // 恢复失败不阻塞聊天；下次选择该会话时会重新从 DB 游标重放。
    }
  }

  async function startAgentTeamsCaseEvents(sessionId: string) {
    if (!sessionId || sessionId.startsWith('sess-')) return
    stopAgentTeamsCaseEvents()
    const generation = agentTeamsEventGeneration
    let reconnects = 0
    while (currentSessionId.value === sessionId && generation === agentTeamsEventGeneration) {
      const controller = new AbortController()
      agentTeamsEventAbort = controller
      try {
        const token = localStorage.getItem('access_token')
        const cursor = agentTeamsEventCursors.get(sessionId)
        const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
        const response = await fetch(`/api/v1/chat/sessions/${sessionId}/agentteams-events${query}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        })
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
        reconnects = 0
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const consumeLine = (line: string) => {
          if (!line.startsWith('data:')) return
          try {
            const event = JSON.parse(line.slice(5).trim()) as AgentTeamsCaseStreamEvent & { event_cursor?: string; idempotency_key?: string }
            const eventKey = event.idempotency_key || event.event_cursor
            const seen = agentTeamsSeenEventKeys.get(sessionId) || new Set<string>()
            if (eventKey && seen.has(eventKey)) return
            if (eventKey) {
              seen.add(eventKey)
              if (seen.size > 500) seen.delete(seen.values().next().value as string)
              agentTeamsSeenEventKeys.set(sessionId, seen)
            }
            if (event.event_cursor) agentTeamsEventCursors.set(sessionId, event.event_cursor)
            if (event.type === 'agentteams_case' && event.phase === 'status_changed') applyAgentTeamsCaseEvent(event)
            else applyCaseRoomEvent(event as Record<string, any>, sessionId)
          } catch {
            // 忽略单条不可解析事件，长连接保持可用。
          }
        }
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) consumeLine(line)
        }
        if (buffer.trim()) consumeLine(buffer)
      } catch (error) {
        if (controller.signal.aborted || generation !== agentTeamsEventGeneration) return
        console.warn('AgentTeams Case 状态事件连接异常', error)
      } finally {
        if (agentTeamsEventAbort === controller) agentTeamsEventAbort = null
      }
      if (generation !== agentTeamsEventGeneration || currentSessionId.value !== sessionId) return
      const delay = Math.min(30_000, 1_000 * 2 ** Math.min(reconnects, 5))
      reconnects += 1
      await new Promise((resolve) => setTimeout(resolve, delay))
    }
  }

  function createSessionIdLock(): Promise<void> {
    if (!pendingSessionIdPromise) {
      pendingSessionIdPromise = new Promise((resolve) => {
        pendingSessionIdResolver = resolve
      })
    }
    return pendingSessionIdPromise
  }

  function releaseSessionIdLock() {
    pendingSessionIdResolver?.()
    pendingSessionIdResolver = null
    pendingSessionIdPromise = null
  }

  async function invokePipelineTool(
    toolName: string,
    arguments_: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await apiClient.post(`/mcp/pipelines/tools/${toolName}/invoke`, {
      tool_name: toolName,
      arguments: arguments_,
    })
    const envelope = response.data as {
      success?: boolean
      error?: string
      result?: Record<string, unknown>
    }
    if (!envelope.success) throw new Error(envelope.error || `${toolName} 调用失败`)
    const result = envelope.result || {}
    return (result.llm_payload as Record<string, unknown>) || result
  }

  function upsertPipelineTask(
    taskId: string,
    pipelineType: PipelineType,
    patch: Partial<PipelineTask> = {},
  ): PipelineTask {
    const current = pipelineTasks.value[taskId]
    const task: PipelineTask = {
      ...current,
      ...patch,
      taskId,
      pipelineType,
      status: patch.status || current?.status || 'queued',
      progress: patch.progress ?? current?.progress ?? 0,
      polling: patch.polling ?? current?.polling ?? false,
    }
    pipelineTasks.value[taskId] = task
    return task
  }

  function stopPipelinePolling(taskId: string): void {
    const timer = pipelinePollTimers.get(taskId)
    if (timer) clearTimeout(timer)
    pipelinePollTimers.delete(taskId)
    const task = pipelineTasks.value[taskId]
    if (task) task.polling = false
  }

  async function loadPipelineResults(task: PipelineTask): Promise<void> {
    const data = await invokePipelineTool(`${task.pipelineType}_results`, {
      task_id: task.taskId,
      result_types: ['summary', 'artifacts'],
    })
    upsertPipelineTask(task.taskId, task.pipelineType, {
      reportUrl: data.report_url as string | undefined,
      metrics: (data.metrics as PipelineTask['metrics']) || {},
      artifacts: (data.artifacts as PipelineTask['artifacts']) || [],
    })
  }

  async function pollPipelineTask(taskId: string): Promise<void> {
    const task = pipelineTasks.value[taskId]
    if (!task || task.polling) return
    task.polling = true
    try {
      const data = await invokePipelineTool(`${task.pipelineType}_status`, { task_id: taskId })
      const status = String(data.status || 'running').toLowerCase() as PipelineTaskStatus
      const progressValue = Number(data.progress || 0)
      upsertPipelineTask(taskId, task.pipelineType, {
        status,
        progress: progressValue <= 1 ? progressValue * 100 : progressValue,
        resultUrl: data.result_url as string | undefined,
        error: (data.error_summary as string | undefined) || undefined,
        polling: false,
      })
      if (status === 'success') {
        await loadPipelineResults(pipelineTasks.value[taskId])
        stopPipelinePolling(taskId)
        return
      }
      if (['failed', 'cancelled'].includes(status)) {
        stopPipelinePolling(taskId)
        return
      }
    } catch (error) {
      upsertPipelineTask(taskId, task.pipelineType, {
        error: error instanceof Error ? error.message : '任务状态获取失败',
        polling: false,
      })
    }
    pipelinePollTimers.set(taskId, setTimeout(() => pollPipelineTask(taskId), 2500))
  }

  async function submitPipelineTask(
    pipelineType: PipelineType,
    preparedParams: Record<string, unknown>,
  ): Promise<PipelineTask> {
    const data = (await invokePipelineTool(`${pipelineType}_submit`, {
      prepared_params: preparedParams,
    })) as unknown as PipelineSubmitResult
    const task = upsertPipelineTask(data.task_id, pipelineType, {
      status: String(data.status || 'queued').toLowerCase() as PipelineTaskStatus,
      progress: Number(data.progress || 0),
      resultUrl: data.result_url,
      preparedParams,
    })
    void pollPipelineTask(task.taskId)
    return task
  }

  function trackPipelineTask(
    taskId: string,
    pipelineType: PipelineType,
    initial?: Partial<PipelineTask>,
  ): PipelineTask {
    const existing = pipelineTasks.value[taskId]
    const task = upsertPipelineTask(
      taskId,
      pipelineType,
      existing
        ? { preparedParams: existing.preparedParams || initial?.preparedParams }
        : initial,
    )
    if (!['success', 'failed', 'cancelled'].includes(task.status)) void pollPipelineTask(taskId)
    return task
  }

  async function retryPipelineTask(taskId: string): Promise<PipelineTask> {
    const task = pipelineTasks.value[taskId]
    if (!task?.preparedParams) throw new Error('缺少原始预检参数，无法直接重试')
    return submitPipelineTask(task.pipelineType, task.preparedParams)
  }

  // ========== Getters ==========
  const activeAgents = computed(() => agents.value.filter((a) => a.is_active))

  function getAgent(id: string): AgentTemplate | undefined {
    return agents.value.find((a) => a.id === id)
  }

  function mcpsByIds(ids: string[]): McpService[] {
    return ids.map((id) => mcps.value.find((m) => m.id === id)).filter(Boolean) as McpService[]
  }

  function skillsByIds(ids: string[]): SkillItem[] {
    return ids.map((id) => skills.value.find((s) => s.id === id)).filter(Boolean) as SkillItem[]
  }

  const currentSession = computed(
    () => sessions.value.find((s) => s.id === currentSessionId.value) || null,
  )

  const currentAgent = computed(() =>
    currentSession.value ? getAgent(currentSession.value.agent_id) : null,
  )

  /** 当前实际应答的智能体：统一入口会话里路由徽标记录的专家优先，
   *  否则回落到会话归属 Agent。能力抽屉等"展示当前 Agent 配置"的 UI 应使用它，
   *  避免入口 Agent（如 router）掩盖实际应答专家的 skill/mcp 挂载。 */
  const effectiveAgent = computed(() => {
    const msgs = currentSession.value?.messages ?? []
    for (let i = msgs.length - 1; i >= 0; i--) {
      const ra = msgs[i].routedAgent
      if (ra?.agentId) {
        const target = getAgent(ra.agentId)
        if (target) return target
      }
    }
    return currentAgent.value
  })

  /** 按 今天 / 昨天 / 更早 分组的历史会话 */
  const groupedSessions = computed(() => {
    const fit = (fn: (d: Date) => boolean) =>
      sessions.value.filter((s) => {
        try { return fn(parseISO(s.updated_at)) } catch { return false }
      })
    const groups: { label: string; sessions: AgentSession[] }[] = []
    const today = fit(isToday)
    const yesterday = fit(isYesterday)
    const older = fit((d) => !isToday(d) && !isYesterday(d))
    if (today.length) groups.push({ label: '今天', sessions: today })
    if (yesterday.length) groups.push({ label: '昨天', sessions: yesterday })
    if (older.length) groups.push({ label: '更早', sessions: older })
    return groups
  })

  // ========== 资产加载 ==========

  /** 加载启用中的 Agent 列表（前台集市） */
  async function fetchAgents(activeOnly = true): Promise<void> {
    try {
      agents.value = activeOnly ? await agentApi.list() : await adminAgentApi.list()
    } catch (e) {
      console.error('加载 Agent 列表失败:', e)
    }
  }

  /** 加载 MCP 服务列表（供表单 transfer / 能力预览） */
  async function fetchMcps(): Promise<void> {
    try {
      const res = await apiClient.get<any[]>('/mcp/servers')
      mcps.value = (res.data || []).map(toMcpService)
    } catch (e) {
      console.error('加载 MCP 列表失败:', e)
    }
  }

  /** 普通用户能力配置使用的 MCP 列表，仅包含管理员启用且可安全展示的字段。 */
  async function fetchUserSelectableMcps(): Promise<void> {
    try {
      mcps.value = (await agentApi.listSelectableMcps()).map(toMcpService)
    } catch (e) {
      console.error('加载可选择 MCP 列表失败:', e)
    }
  }

  /** 加载技能列表（供表单 transfer / 能力预览）
   *  all=false 走公开 /chat/skills（仅启用）；all=true 走 /admin/skills（含停用）
   */
  async function fetchSkills(all = false): Promise<void> {
    try {
      const url = all ? '/admin/skills' : '/chat/skills'
      const res = await apiClient.get<any[]>(url)
      skills.value = (res.data || []).map((s) => ({
        id: s.skill_id ?? String(s.id),
        name: s.name,
        description: s.description ?? '',
        icon: s.icon ?? '🔧',
        category: s.category ?? '通用',
        source: s.is_builtin ? 'builtin' : (s.source_type ?? 'json'),
        source_url: s.source_ref ?? undefined,
        version: s.version ?? undefined,
        author: s.author ?? undefined,
        has_scripts: !!s.has_scripts,
        is_active: s.is_active ?? true,
      }))
    } catch (e) {
      console.error('加载技能列表失败:', e)
    }
  }

  /** 加载可用模型列表（供会话内模型切换） */
  async function fetchAvailableModels(): Promise<void> {
    try {
      const res = await apiClient.get<AvailableModel[]>('/chat/models')
      availableModels.value = (res.data || []).map((m) => ({
        id: String(m.id),
        name: m.name,
        model: m.model,
        provider_type: m.provider_type,
        is_default: m.is_default,
        temperature: m.temperature,
        max_tokens: m.max_tokens,
      }))
    } catch (e) {
      console.error('加载模型列表失败:', e)
    }
  }

  /** 加载当前用户的历史会话列表（Agent-first 模式只保留绑定 agent_id 的会话） */
  async function fetchSessions(): Promise<void> {
    try {
      const res = await apiClient.get<Array<{
        session_id: string
        title: string
        title_locked?: boolean
        agent_id: string | null
        model_id: string
        mode?: 'chat' | 'studio'
        mcp_mode?: 'off' | 'auto' | 'manual'
        extra_mcp_servers?: string[]
        multi_agent?: boolean
        overdrive?: boolean
        created_at: string
        updated_at: string
      }>>('/chat/sessions')
      const loaded = (res.data || [])
        .filter((s) => s.agent_id)
        .map((s) => ({
          id: s.session_id,
          title: s.title,
          title_locked: s.title_locked ?? false,
          agent_id: s.agent_id as string,
          mode: s.mode || 'chat',
          messages: [] as ChatMessage[],
          created_at: s.created_at,
          updated_at: s.updated_at,
          model_id: s.model_id || undefined,
          mcp_mode: s.mcp_mode || 'auto',
          extra_mcp_servers: s.extra_mcp_servers || [],
          multi_agent: Boolean(s.multi_agent),
          overdrive: Boolean(s.overdrive),
        }))
      // 合并正在流式中的临时会话，避免刷新时丢失
      const tempSessions = sessions.value.filter((s) => s.id.startsWith('sess-'))
      sessions.value = [...tempSessions, ...loaded]
    } catch (e) {
      console.error('加载会话列表失败:', e)
    }
  }

  /** 拉取当前用户的 Studio 会话 ID 集合（供 /ai 会话列表打角标；失败静默，不阻塞主流程） */
  async function fetchStudioSessionIds(): Promise<void> {
    try {
      const res = await apiClient.get<Array<{ session_id: string }>>('/studio/sessions')
      studioSessionIds.value = new Set((res.data || []).map((s) => s.session_id))
    } catch (e) {
      console.error('加载 Studio 会话列表失败:', e)
    }
  }

  /** 新建 Studio 会话后登记 ID，无需整表刷新 */
  function markStudioSession(id: string): void {
    studioSessionIds.value = new Set([...studioSessionIds.value, id])
  }

  /** 一次性初始化全部资产（前台页面挂载时调用） */
  async function initAssets(): Promise<void> {
    await Promise.all([
      fetchAgents(true), fetchUserSelectableMcps(), fetchSkills(false), fetchAvailableModels(), fetchSessions(),
      fetchStudioSessionIds(),
    ])
  }

  // ========== 资产 Actions（后台 CRUD，调真实 API） ==========

  /** 切换 MCP 启用状态 */
  async function toggleMcpStatus(id: string) {
    const m = mcps.value.find((x) => x.id === id)
    if (!m) return
    const newEnabled = !m.is_enabled
    try {
      await apiClient.put(`/mcp/servers/${id}`, { is_enabled: newEnabled })
      m.is_enabled = newEnabled
    } catch {
      // keep original
    }
  }

  async function addMcpServer(data: {
    name: string
    description?: string
    transport: string
    command?: string
    args?: string[]
    url?: string
    env?: Record<string, string>
    registry?: string
    working_dir?: string
    timeout?: number
  }): Promise<McpService> {
    const res = await apiClient.post<McpService>('/mcp/servers', data)
    await fetchMcps()
    const id = String(res.data?.id || '')
    const created = mcps.value.find((server) => server.id === id)
      || mcps.value.find((server) => server.name === data.name)
    if (!created) throw new Error('MCP 创建成功但未能读取服务信息')
    return created
  }

  async function updateMcpServer(id: string, data: Record<string, unknown>): Promise<void> {
    await apiClient.put(`/mcp/servers/${id}`, data)
    await fetchMcps()
  }

  /** MCP 服务版本历史（created_at 倒序） */
  async function fetchMcpVersions(id: string): Promise<McpVersion[]> {
    const res = await apiClient.get<McpVersion[]>(`/mcp/servers/${id}/versions`)
    return res.data || []
  }

  /** 回滚 MCP 服务到指定版本快照 */
  async function rollbackMcpServer(id: string, version: string): Promise<void> {
    await apiClient.post(`/mcp/servers/${id}/rollback`, { version })
    await fetchMcps()
  }

  /** 实验 MCP 转正为正式池（Admin），返回 {id, name, pool, current_version} */
  async function promoteMcpServer(id: string): Promise<{ id: string; name: string; pool: string; current_version: string }> {
    const res = await apiClient.post<{ id: string; name: string; pool: string; current_version: string }>(
      `/mcp-builder/servers/${id}/promote`,
    )
    await fetchMcps()
    return res.data
  }

  /** 热加载内置 MCP 预设工具清单（Admin，免重启容器） */
  async function syncMcpPresets(): Promise<void> {
    await apiClient.post('/mcp/presets/reload')
    await fetchMcps()
  }

  async function fetchMcpLogs(id: string, tail = 100): Promise<McpLogEntry[]> {
    const res = await apiClient.get(`/mcp/servers/${id}/logs`, { params: { tail } })
    return (res.data || []).map((log: any) => ({
      timestamp: log.timestamp,
      level: log.level,
      message: log.message,
      source: log.source,
    }))
  }

  async function removeMcpServer(id: string): Promise<void> {
    await apiClient.delete(`/mcp/servers/${id}`)
    mcps.value = mcps.value.filter((m) => m.id !== id)
    agents.value.forEach((a) => {
      a.mcp_ids = a.mcp_ids.filter((mid) => mid !== id)
    })
  }

  async function testMcpServer(id: string): Promise<{ success: boolean; tool_count: number; error?: string }> {
    const res = await apiClient.post(`/mcp/servers/${id}/test`)
    return res.data
  }

  async function fetchMcpTools(id: string): Promise<McpTool[]> {
    const res = await apiClient.get<any[]>(`/mcp/servers/${id}/tools`)
    return (res.data || []).map((t: any) => ({
      name: t.name,
      description: t.description ?? '',
      input_schema: t.input_schema ?? {},
    }))
  }

  async function upsertAgent(dto: Partial<AgentTemplate> & { id?: string }): Promise<AgentTemplate | null> {
    let saved: AgentTemplate
    if (dto.id && agents.value.some((a) => a.id === dto.id)) {
      saved = await adminAgentApi.update(dto.id, dto)
    } else {
      saved = await adminAgentApi.create(dto)
    }
    await fetchAgents(false)
    return saved
  }

  async function toggleAgent(id: string): Promise<void> {
    await adminAgentApi.toggle(id)
    await fetchAgents(false)
  }

  async function deleteAgent(id: string): Promise<void> {
    await adminAgentApi.remove(id)
    await fetchAgents(false)
  }

  async function setDefaultAgent(id: string): Promise<void> {
    await adminAgentApi.setDefault(id)
    await fetchAgents(false)
  }

  // ========== 技能管理（后台 CRUD + SKILL.md 五入口导入，调 /admin/skills） ==========

  /** 入口一：GitHub 仓库/子目录 URL → 解析预览（不入库） */
  async function previewSkillFromGithub(url: string): Promise<SkillImportPreview> {
    const res = await apiClient.post<SkillImportPreview>('/admin/skills/import/github', { url })
    return res.data
  }

  /** 入口二：本地 zip 上传 → 解析预览（不入库） */
  async function previewSkillFromZip(file: File): Promise<SkillImportPreview> {
    const form = new FormData()
    form.append('file', file)
    const res = await apiClient.post<SkillImportPreview>('/admin/skills/import/zip', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  }

  /** 入口三：独立 Markdown 指令文件 → 解析预览（自动生成标准 SKILL.md） */
  async function previewSkillFromMarkdown(file: File): Promise<SkillImportPreview> {
    const form = new FormData()
    form.append('file', file)
    const res = await apiClient.post<SkillImportPreview>('/admin/skills/import/markdown', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  }

  /** 入口四：JSON 粘贴（兼容旧格式）→ 解析预览（不入库） */
  async function previewSkillFromJson(text: string): Promise<SkillImportPreview> {
    const res = await apiClient.post<SkillImportPreview>('/admin/skills/import/json', { text })
    return res.data
  }

  /** 预览确认后入库 */
  async function confirmSkillImport(preview: SkillImportPreview, overwrite = false): Promise<void> {
    await apiClient.post('/admin/skills/import/confirm', { preview, overwrite })
    await fetchSkills(true)
  }

  /** 入口四：技能市场列表（随仓库发布的内置技能） */
  async function fetchSkillMarketplace(): Promise<SkillMarketplaceItem[]> {
    const res = await apiClient.get<SkillMarketplaceItem[]>('/admin/skills/marketplace')
    return res.data || []
  }

  /** 一键安装市场技能 */
  async function installMarketplaceSkill(skillId: string, overwrite = false): Promise<void> {
    await apiClient.post(`/admin/skills/marketplace/${skillId}/install`, null, {
      params: { overwrite },
    })
    await fetchSkills(true)
  }

  /** 阿里云官方技能源：同步状态（不触网） */
  async function fetchAliyunMarketStatus(): Promise<AliyunMarketStatus> {
    const res = await apiClient.get<AliyunMarketStatus>('/admin/skills/marketplace/aliyun/status')
    return res.data
  }

  /** 阿里云官方技能源：通过 AgentExplorer OpenAPI 拉取目录（未配置凭证时回退 GitHub） */
  async function syncAliyunMarket(force = false): Promise<AliyunMarketStatus> {
    const res = await apiClient.post<AliyunMarketStatus>(
      '/admin/skills/marketplace/aliyun/sync',
      null,
      { params: { force } },
    )
    return res.data
  }

  /** 一键安装阿里云官方技能（走统一预览校验入库） */
  async function installAliyunMarketSkill(skillId: string, overwrite = false): Promise<void> {
    await apiClient.post(`/admin/skills/marketplace/aliyun/${skillId}/install`, null, {
      params: { overwrite },
    })
    await fetchSkills(true)
  }

  /** 检查上游更新（GitHub 来源） */
  async function checkSkillUpdate(skillId: string): Promise<SkillUpdateCheck> {
    const res = await apiClient.post<SkillUpdateCheck>(`/admin/skills/${skillId}/check-update`)
    return res.data
  }

  /** 技能调用聚合统计（资源中心技能卡片"最近调用 · 累计 N 次"） */
  async function fetchSkillInvocationStats(): Promise<SkillInvocationStat[]> {
    const res = await apiClient.get<SkillInvocationStat[]>('/admin/skills/invocation-stats')
    return res.data || []
  }

  /** 某技能的最近调用记录（倒序） */
  async function fetchSkillInvocations(skillId: string, limit = 20): Promise<SkillInvocationRecord[]> {
    const res = await apiClient.get<SkillInvocationRecord[]>(
      `/admin/skills/${skillId}/invocations`,
      { params: { limit } },
    )
    return res.data || []
  }

  /** 技能版本历史（revision 倒序） */
  async function fetchSkillVersions(skillId: string): Promise<SkillVersion[]> {
    const res = await apiClient.get<SkillVersion[]>(`/admin/skills/${skillId}/versions`)
    return res.data || []
  }

  /** 回滚技能到指定 revision */
  async function rollbackSkill(skillId: string, revision: number): Promise<void> {
    await apiClient.post(`/admin/skills/${skillId}/rollback`, { revision })
    await fetchSkills(true)
  }

  async function toggleSkill(id: string): Promise<void> {
    try {
      await apiClient.post(`/admin/skills/${id}/toggle`)
      await fetchSkills(true)
    } catch (e) {
      console.error('切换技能状态失败:', e)
    }
  }

  /** 删除技能。被助手引用时后端返回 400，需 force=true 二次确认；错误上抛由组件处理。 */
  async function deleteSkill(id: string, force = false): Promise<void> {
    await apiClient.delete(`/admin/skills/${id}`, { params: { force } })
    await fetchSkills(true)
    // 同步解绑 Agent 上的引用（前端缓存）
    agents.value.forEach((a) => (a.skill_ids = a.skill_ids.filter((x) => x !== id)))
  }

  /** 版本快照详情（含正文，供 diff 查看） */
  async function fetchSkillVersionDetail(skillId: string, revision: number): Promise<SkillVersionDetail> {
    const res = await apiClient.get<SkillVersionDetail>(`/admin/skills/${skillId}/versions/${revision}`)
    return res.data
  }

  /** 引用该技能的助手列表（删除保护） */
  async function fetchSkillReferences(skillId: string): Promise<SkillReference[]> {
    const res = await apiClient.get<SkillReference[]>(`/admin/skills/${skillId}/references`)
    return res.data || []
  }

  // ========== 会话编排 ==========

  function startSessionFromAgent(agentId: string): AgentSession | null {
    // 切换/新建会话时先中断当前流，避免资源浪费
    stopStreaming()
    const agent = getAgent(agentId)
    if (!agent) return null
    const now = new Date().toISOString()
    const session: AgentSession = {
      id: `sess-${Date.now()}`,
      title: agent.name,
      title_locked: false,
      agent_id: agentId,
      mode: agent.features?.studio?.default_mode === 'studio' ? 'studio' : 'chat',
      messages: [],
      created_at: now,
      updated_at: now,
      model_id: agent.model_id || undefined,
      mcp_mode: 'auto',
      extra_mcp_servers: [],
      multi_agent: false,
      overdrive: false,
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    return session
  }

  function shouldSubscribeToAgentTeamsEvents(session: AgentSession | undefined): boolean {
    return Boolean(
      session?.multi_agent
      || session?.overdrive
      || session?.messages.some((message) => message.agentTeamsCases?.length),
    )
  }

  function syncAgentTeamsEventSubscriptions(session: AgentSession | undefined): void {
    if (session?.id && overdriveEventSessionId && overdriveEventSessionId !== session.id) {
      stopOverdriveEvents()
    }
    if (!session || !shouldSubscribeToAgentTeamsEvents(session)) {
      stopAgentTeamsCaseEvents()
      stopOverdriveEvents()
      return
    }
    void startAgentTeamsCaseEvents(session.id)
  }

  async function selectSession(id: string) {
    if (currentSessionId.value !== id) {
      stopStreaming()
      currentPlan.value = []
    }
    currentSessionId.value = id
    const session = sessions.value.find((s) => s.id === id)
    if (session && session.messages.length === 0 && !session.id.startsWith('sess-')) {
      await loadSessionMessages(id)
    }
    syncAgentTeamsEventSubscriptions(session)
    if (session && !session.id.startsWith('sess-')) void recoverOverdriveRun(session.id)
    // Studio 会话：同步权限模式（非 studio 会话保持默认 supervised，不在此展示开关）
    if (studioSessionIds.value.has(id)) {
      studioApi.getSession(id)
        .then((detail) => initStudioPermissions(detail.permissions?.mode))
        .catch(() => {})
    }
  }

  function newChat() {
    stopStreaming()
    stopAgentTeamsCaseEvents()
    stopOverdriveEvents()
    currentSessionId.value = ''
  }

  async function deleteSession(id: string) {
    if (currentSessionId.value === id) stopStreaming()
    if (currentSessionId.value === id) {
      stopAgentTeamsCaseEvents()
      stopOverdriveEvents()
    }
    if (!id.startsWith('sess-')) {
      try {
        await apiClient.delete(`/chat/sessions/${id}`)
      } catch (e) {
        console.error('删除会话失败:', e)
        return
      }
    }
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentSessionId.value === id) currentSessionId.value = ''
  }

  async function renameSession(id: string, title: string) {
    const s = sessions.value.find((x) => x.id === id)
    const cleaned = title.trim()
    if (!s || !cleaned) return
    if (id.startsWith('sess-')) {
      s.title = cleaned
      s.title_locked = true
      return
    }
    const previous = s.title
    s.title = cleaned
    s.title_locked = true
    try {
      const res = await apiClient.patch<{
        session_id: string
        title: string
        title_locked?: boolean
      }>(`/chat/sessions/${id}`, { title: cleaned })
      s.title = res.data.title
      s.title_locked = res.data.title_locked ?? true
    } catch (e) {
      s.title = previous
      console.error('重命名会话失败:', e)
      throw e
    }
  }

  async function generateSessionTitle(id: string): Promise<void> {
    if (!id || id.startsWith('sess-')) return
    const session = sessions.value.find((s) => s.id === id)
    if (!session || session.title_locked) return
    try {
      const res = await apiClient.post<{ title: string }>(`/chat/sessions/${id}/generate-title`)
      if (res.data?.title) session.title = res.data.title
    } catch (e) {
      console.error('生成会话标题失败:', e)
      // 首轮 LLM 失败时把“生成中...”占位回退，避免历史列表标题卡在占位文案
      if (session.title === '生成中...') session.title = '新对话'
    }
  }

  async function searchSessions(keyword: string): Promise<{
    title_matches: AgentSession[]
      content_matches: Array<{ session_id: string; title: string; title_locked: boolean; agent_id: string | null; model_id: string; mode: 'chat' | 'studio'; message_id: string; snippet: string; created_at: string; updated_at: string }>
  }> {
    const res = await apiClient.get('/chat/sessions/search', { params: { keyword } })
    const title_matches = (res.data?.title_matches || [])
      .filter((s: any) => s.agent_id)
      .map((s: any) => ({
        id: s.session_id,
        title: s.title,
        title_locked: s.title_locked ?? false,
        agent_id: s.agent_id,
        mode: s.mode || 'chat',
        messages: [] as ChatMessage[],
        created_at: s.created_at,
        updated_at: s.updated_at,
        model_id: s.model_id || undefined,
      }))
    return {
      title_matches,
      content_matches: (res.data?.content_matches || []).map((m: any) => ({
        session_id: m.session_id,
        title: m.title,
        title_locked: m.title_locked ?? false,
        agent_id: m.agent_id,
        model_id: m.model_id,
        mode: m.mode || 'chat',
        message_id: m.message_id,
        snippet: m.snippet,
        created_at: m.created_at,
        updated_at: m.updated_at,
      })),
    }
  }

  /** 切换指定会话当前使用的模型 */
  function switchSessionModel(id: string, modelId: string) {
    const s = sessions.value.find((x) => x.id === id)
    if (s) s.model_id = modelId
  }

  /** 从后端加载指定会话的历史消息（含 token）并替换当前客户端消息 */
  async function loadSessionMessages(sessionId: string): Promise<void> {
    try {
      const res = await apiClient.get<Array<{
        message_id: string
        role: string
        content: string
        metadata_json?: Record<string, unknown>
        created_at: string
        tokens?: { input: number; output: number; total: number }
      }>>(`/chat/sessions/${sessionId}/messages`)
      const session = sessions.value.find((s) => s.id === sessionId)
      if (!session) return
      const existingIds = new Set(session.messages.map((m) => m.id))
      let restoredPlan: StudioPlanStep[] = []
      const loaded = sortPersistedChatMessages(res.data || []).map((m) => {
        const msg: ChatMessage = {
          id: m.message_id,
          role: m.role as 'user' | 'assistant' | 'system',
          content: m.content,
          createdAt: m.created_at,
          modelName: (m.metadata_json?.model as string) || undefined,
          // usage is response metadata; keep it off user/system messages even if an old
          // backend row contains a stale tokens payload.
          tokens: m.role === 'assistant' ? (m.tokens || { input: 0, output: 0, total: 0 }) : undefined,
        }
        const attachments = m.metadata_json?.attachments
        if (Array.isArray(attachments)) {
          msg.attachments = attachments
            .filter((attachment): attachment is Record<string, unknown> => !!attachment && typeof attachment === 'object')
            .map((attachment) => ({
              name: typeof attachment.name === 'string' ? attachment.name : '附件',
              size: Number(attachment.size) || 0,
              type: attachment.type === 'directory'
                ? 'directory'
                : typeof attachment.mime_type === 'string' && attachment.mime_type
                  ? attachment.mime_type
                  : typeof attachment.type === 'string'
                    ? attachment.type
                    : 'application/octet-stream',
              url: typeof attachment.url === 'string' ? attachment.url : undefined,
              file_id: typeof attachment.file_id === 'string' ? attachment.file_id : undefined,
              source: attachment.source === 'workspace' ? 'workspace' : 'upload',
              recursive: attachment.recursive === true,
            }))
        }
        // 智能路由：恢复本条消息的专家徽标
        const routedAgent = m.metadata_json?.routed_agent as
          | {
              agent_id?: string
              name?: string
              avatar?: string
              color?: string
              reason?: string
              intent?: string
              confidence?: number
              transition?: {
                visible?: boolean
                stage?: string
                title?: string
                message?: string
                next_step?: string
                requires_execution_confirmation?: boolean
                auto_start?: boolean
              }
            }
          | undefined
        if (routedAgent?.name) {
          msg.routedAgent = {
            agentId: routedAgent.agent_id || '',
            name: routedAgent.name,
            avatar: routedAgent.avatar || '',
            color: routedAgent.color || '',
            reason: routedAgent.reason || '',
            intent: routedAgent.intent,
            confidence: routedAgent.confidence,
            transition: routedAgent.transition
              ? {
                  visible: Boolean(routedAgent.transition.visible),
                  stage:
                    routedAgent.transition.stage === 'execution_ready'
                      ? 'execution_ready'
                      : 'specialist_intake',
                  title: routedAgent.transition.title || '已匹配专项专家',
                  message: routedAgent.transition.message || '',
                  nextStep: routedAgent.transition.next_step || '专项 Agent 进行任务 intake',
                  requiresExecutionConfirmation: Boolean(
                    routedAgent.transition.requires_execution_confirmation,
                  ),
                  autoStart: Boolean(routedAgent.transition.auto_start),
                }
              : undefined,
          }
        }
        const senderAgent = m.metadata_json?.senderAgent
        if (senderAgent && typeof senderAgent === 'object') {
          const sender = senderAgent as Record<string, unknown>
          if (typeof sender.name === 'string') {
            msg.senderAgent = {
              id: typeof sender.agent_id === 'string' ? sender.agent_id : '',
              name: sender.name,
              avatar: typeof sender.avatar === 'string' ? sender.avatar : undefined,
              color: typeof sender.color === 'string' ? sender.color : undefined,
              role: sender.role === 'worker' ? 'worker' : 'manager',
              round: Number(m.metadata_json?.overdriveRound) || undefined,
            }
          }
        }
        if (m.role === 'assistant' && typeof m.metadata_json?.thought === 'string') {
          msg.thought = m.metadata_json.thought
        }
        if (m.role === 'assistant' && typeof m.metadata_json?.summary === 'string') {
          msg.overdriveSummary = m.metadata_json.summary
        }
        if (m.role === 'assistant' && m.metadata_json?.artifacts && typeof m.metadata_json.artifacts === 'object') {
          msg.overdriveArtifacts = m.metadata_json.artifacts as Record<string, string>
        }
        if (m.role === 'assistant' && typeof m.metadata_json?.taskStatus === 'string') {
          msg.overdriveTaskStatus = m.metadata_json.taskStatus
        }
        if (m.role === 'assistant' && typeof m.metadata_json?.errorSummary === 'string') {
          msg.overdriveErrorSummary = m.metadata_json.errorSummary
        }
        const collaborationRoute = m.metadata_json?.collaboration_route
        if (collaborationRoute && typeof collaborationRoute === 'object') {
          const item = collaborationRoute as Record<string, unknown>
          const intent = item.intent
          if (typeof intent === 'string' && ['transfer', 'fanout', 'consult', 'case', 'dag', 'chat'].includes(intent)) {
            msg.collaborationRoute = {
              intent: intent as CollaborationRouteInfo['intent'],
              label: typeof item.label === 'string' ? item.label : '协作路径',
              reason: typeof item.reason === 'string' ? item.reason : '',
              confidence: Number(item.confidence) || 0,
              available: Boolean(item.available),
              degraded: Boolean(item.degraded),
              message: typeof item.message === 'string' ? item.message : '',
            }
          }
        }
        const consultation = m.metadata_json?.consultation
        if (consultation && typeof consultation === 'object') {
          const item = consultation as Record<string, unknown>
          const experts = Array.isArray(item.experts)
            ? item.experts
              .filter((expert): expert is Record<string, unknown> => !!expert && typeof expert === 'object')
              .map((expert) => ({
                agent_id: typeof expert.agent_id === 'string' ? expert.agent_id : '',
                name: typeof expert.name === 'string' ? expert.name : '专家',
                opinion: typeof expert.opinion === 'string' ? expert.opinion : '',
              }))
            : []
          if (experts.length) {
            msg.consultation = {
              experts,
              consultationId: typeof item.consultation_id === 'string' ? item.consultation_id : undefined,
              consultationSummary: typeof item.consultation_summary === 'string' ? item.consultation_summary : undefined,
              caseAvailable: typeof item.case_available === 'boolean' ? item.case_available : undefined,
            }
          }
        }
        const webSources = m.metadata_json?.web_sources
        if (Array.isArray(webSources)) {
          msg.webSources = webSources
            .filter((source): source is Record<string, unknown> => !!source && typeof source === 'object')
            .filter((source) => typeof source.title === 'string' && typeof source.url === 'string')
            .map((source) => ({
              title: source.title as string,
              url: source.url as string,
              snippet: typeof source.snippet === 'string' ? source.snippet : '',
              publishedAt: typeof source.publishedAt === 'string' ? source.publishedAt : null,
            }))
        }
        const agentTeamsCases = m.metadata_json?.agentteams_cases
        if (Array.isArray(agentTeamsCases)) {
          msg.agentTeamsCases = agentTeamsCases
            .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
            .filter((item) => typeof item.case_id === 'string' && typeof item.status === 'string')
            .map((item) => ({
              case_id: item.case_id as string,
              title: typeof item.title === 'string' ? item.title : '协作 Case',
              status: item.status as string,
              next_actor: typeof item.next_actor === 'string' ? item.next_actor : '协作团队',
              case_url: typeof item.case_url === 'string' ? item.case_url : '',
              updated_at: typeof item.updated_at === 'string' ? item.updated_at : undefined,
            }))
        }
        if (m.role === 'system' && m.metadata_json?.type === 'agentteams_case') {
          const caseId = m.metadata_json.case_id
          const status = m.metadata_json.status
          if (typeof caseId === 'string' && typeof status === 'string') {
            msg.agentTeamsCases = [{
              case_id: caseId,
              title: '协作 Case 状态更新',
              status,
              next_actor: typeof m.metadata_json.next_actor === 'string'
                ? m.metadata_json.next_actor
                : '协作团队',
              case_url: typeof m.metadata_json.case_url === 'string' ? m.metadata_json.case_url : '',
              updated_at: m.created_at,
            }]
          }
        }
        // Studio 会话：历史消息随 metadata_json.tool_invocations 落库，
        // 重载时重建工具调用卡片（代码卡片凭 arguments + ui_payload 渲染）
        const invocations = m.metadata_json?.tool_invocations
        if (Array.isArray(invocations) && invocations.length) {
          msg.toolCalls = invocations.map((t) => {
            const inv = t as Record<string, unknown>
            const uiPayload = (inv.ui_payload as Record<string, unknown> | undefined) || undefined
            if (inv.tool_name === 'update_plan' && Array.isArray(uiPayload?.steps)) {
              restoredPlan = uiPayload.steps as StudioPlanStep[]
            }
            const so = typeof uiPayload?.stdout === 'string' ? uiPayload.stdout : ''
            const se = typeof uiPayload?.stderr === 'string' ? uiPayload.stderr : ''
            const tc: ToolCall = {
              id: (inv.tool_call_id as string) || `tc-${m.message_id}`,
              name: (inv.tool_name as string) || '',
              arguments: (inv.arguments as Record<string, unknown>) || {},
              result: inv.result,
              uiPayload,
              // 后端落库的 mcp_server 与流式事件一致；旧数据无此字段时回退 studio
              // （旧版本仅 Studio 工具落库 tool_invocations）
              mcpServer: (inv.mcp_server as string) || 'studio',
              status: inv.success ? 'success' : 'error',
            }
            if (so || se) tc.output = so + se
            return tc
          })

          // ask_user 的澄清事件不会单独作为消息落库；历史重载时从工具结果
          // 还原为 AskUserCard，避免重新打开会话后退化成普通 MCP 工具卡片。
          const askTool = msg.toolCalls.find((tool) => tool.name === 'ask_user')
          if (askTool) {
            const result = askTool.result && typeof askTool.result === 'object'
              ? askTool.result as Record<string, unknown>
              : undefined
            const payload = askTool.uiPayload
              || (result?.ui_payload as Record<string, unknown> | undefined)
              || (result?.uiPayload as Record<string, unknown> | undefined)
              || result
            const rawQuestions = Array.isArray(payload?.questions) ? payload.questions : []
            const questions = rawQuestions
              .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
              .map((item) => ({
                question: typeof item.question === 'string' ? item.question : '',
                options: Array.isArray(item.options)
                  ? item.options.filter((option): option is string => typeof option === 'string')
                  : undefined,
              }))
            if (questions.length) {
              msg.askRequest = { questions, answered: false }
            }
          }
        }
        // 交错时间线：后端按发生顺序落库的 text/tool 段，重载后保持交错布局
        const timeline = m.metadata_json?.timeline
        if (Array.isArray(timeline) && timeline.length) {
          msg.timeline = timeline
            .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
            .map((s) => ({
              kind: s.kind === 'tool' ? ('tool' as const) : ('text' as const),
              text: typeof s.text === 'string' ? s.text : undefined,
              toolCallId:
                typeof s.tool_call_id === 'string' && s.tool_call_id ? s.tool_call_id : undefined,
            }))
        }
        return msg
      })
      // 历史消息没有单独的 answered 字段：如果澄清卡片后已经出现用户消息，
      // 说明用户已提交答案，恢复为可展开的已回答摘要而不是再次要求输入。
      loaded.forEach((message, index) => {
        if (!message.askRequest || message.askRequest.answered) return
        const answered = loaded.slice(index + 1).some((candidate) => candidate.role === 'user')
        if (answered) message.askRequest.answered = true
      })
      // 保留当前正在流式中的占位消息，避免闪烁
      const streamingPlaceholders = session.messages.filter(
        (m) => m.role === 'assistant' && m.content === '' && !existingIds.has(m.id),
      )
      session.messages = [...loaded, ...streamingPlaceholders]
      // 恢复历史 AI 回复的点赞/点踩状态（失败不阻塞历史加载）
      try {
        const feedbackMap = await chatApi.getSessionFeedbacks(sessionId)
        for (const msg of session.messages) {
          if (msg.role === 'assistant') msg.feedback = feedbackMap[msg.id] || undefined
        }
      } catch {
        /* 反馈状态恢复失败不影响历史消息展示 */
      }
      // 恢复历史中最近一次 update_plan 的待办计划（流式进行中不覆盖实时计划）
      if (!isStreaming.value) {
        currentPlan.value = restoredPlan
      }
      // Studio 会话：审批提示是瞬态 SSE 事件，不落库；刷新/断流重进时从 Redis
      // 拉取仍 pending 的审批，把对应工具卡恢复成待审批态（ApprovalCard 接管交互）
      if (studioSessionIds.value.has(sessionId)) {
        try {
          const pendingApprovals = await studioApi.listPendingApprovals(sessionId)
          for (const approval of pendingApprovals) {
            const tc = session.messages
              .flatMap((m) => m.toolCalls || [])
              .find((t) => t.id === approval.tool_call_id)
            if (!tc || tc.approval) continue
            tc.status = 'awaiting_approval'
            tc.approval = {
              approval_id: approval.approval_id,
              status: 'pending',
              risk_hint: approval.risk_hint,
              timeout_seconds: approval.expires_in,
            }
            // 审批记录里的 arguments 可能比落库的 tool_invocations 更全，以其为准补齐
            tc.arguments = { ...tc.arguments, ...approval.arguments }
          }
        } catch (e) {
          console.error('恢复待审批状态失败:', e)
        }
      }
      if (currentSessionId.value === sessionId) await recoverOverdriveRun(sessionId)
    } catch (e) {
      console.error('加载会话历史消息失败:', e)
    }
  }

  /** 点赞/点踩 AI 消息：再次点击同一评价即撤销；乐观更新 UI，失败回滚 */
  async function submitMessageFeedback(
    messageId: string,
    rating: 'like' | 'dislike',
  ): Promise<void> {
    const session = sessions.value.find((s) =>
      s.messages.some((m) => m.id === messageId || m.backendMessageId === messageId),
    )
    if (!session || session.id.startsWith('sess-')) return
    const message = session.messages.find(
      (m) => m.id === messageId || m.backendMessageId === messageId,
    )
    if (!message) return
    const backendMessageId = message.backendMessageId || message.id
    const next = message.feedback === rating ? undefined : rating
    const prev = message.feedback
    message.feedback = next
    try {
      await chatApi.submitMessageFeedback(session.id, backendMessageId, next ?? 'none')
    } catch (e) {
      message.feedback = prev
      console.error('提交消息反馈失败:', e)
    }
  }

  // 超频/多智能体房间发言：后端一次性给出整段内容，前端按打字机节奏渐进展示，
  // 让 Manager/专家发言与普通助手回复一样具备流式动画。
  const roomSpeechTimers = new Set<number>()
  const roomSpeechFullText = new Map<string, string>()
  const roomSpeechLiveMessages = new Map<string, ChatMessage>()
  const roomSpeechMessages = new Map<string, ChatMessage>()
  function finalizeRoomSpeeches() {
    for (const timer of roomSpeechTimers) window.clearInterval(timer)
    roomSpeechTimers.clear()
    const session = currentSession.value
    if (session) {
      for (const m of session.messages) {
        if (m.role === 'assistant' && m.senderAgent && m.status === 'streaming') {
          m.content = roomSpeechFullText.get(m.id) ?? m.content
          m.status = 'complete'
        }
      }
    }
    roomSpeechFullText.clear()
    roomSpeechLiveMessages.clear()
    roomSpeechMessages.clear()
  }

  /** 发送消息（真实 SSE 流式，走 Agent 调度中枢） */
  async function sendMessage(
    content: string,
    options: {
      attachments?: FileAttachment[]
      enableWebSearch?: boolean
      enableCodeExecution?: boolean
      /** @ 显式指定的智能体：本条消息转交该专家回答 */
      explicitAgentId?: string
      /** @ 挂载到本次对话的技能名 */
      skillNames?: string[]
      mcpMode?: 'off' | 'auto' | 'manual'
      extraMcpServers?: string[]
      multiAgent?: boolean
      overdrive?: boolean
      /** 当前用户消息的受控操作元数据。 */
      messageMetadata?: Record<string, unknown>
      /** 工具轮次触顶后用户确认继续：本次请求上限扩展到 1000 轮 */
      extendMaxRounds?: boolean
    } = {},
  ): Promise<void> {
    const session = currentSession.value
    if (!session || isStreaming.value || !content.trim()) return
    // @ 显式指定的智能体优先，否则回落到会话绑定的智能体
    const agent = getAgent(options.explicitAgentId || session.agent_id) || getAgent(session.agent_id)
    if (!agent) return
    // 临时会话尚未在后端落库时，@Agent 会决定该会话的实际绑定对象。
    // 必须同步本地绑定，否则首轮后端创建的是显式 Agent 会话，第二轮却会按旧 Agent 发请求，
    // 触发“会话绑定的 Agent 与当前请求不一致”。
    if (options.explicitAgentId && session.id.startsWith('sess-')) {
      session.agent_id = agent.id
      session.model_id = agent.model_id || undefined
    }
    if (options.mcpMode) session.mcp_mode = options.mcpMode
    if (options.extraMcpServers) session.extra_mcp_servers = [...options.extraMcpServers]
    if (options.multiAgent !== undefined) session.multi_agent = options.multiAgent
    if (options.overdrive !== undefined) session.overdrive = options.overdrive

    // 若当前临时会话 ID 正在解析为真实 ID，排队等待，防止创建重复会话
    if (session.id.startsWith('sess-') && pendingSessionIdPromise) {
      await pendingSessionIdPromise
    }

    const chatStore = useChatStore()
    const now = new Date().toISOString()

    // 用户消息
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      metadata: options.messageMetadata,
      createdAt: now,
    }
    if (options.attachments?.length) {
      userMsg.attachments = options.attachments.map((a) => ({
        name: a.name,
        size: a.size,
        type: a.type,
        url: a.url,
        file_id: a.file_id,
        source: a.source,
        recursive: a.recursive,
      }))
    }
    session.messages.push(userMsg)

    const effectiveOverdrive = options.overdrive ?? session.overdrive ?? false
    // 助手占位消息（流式填充；超频发言由 room_speech 逐条创建）
    const aiId = `msg-ai-${Date.now()}`
    const aiMsgSeed: ChatMessage = {
      id: aiId,
      role: 'assistant',
      content: '',
      status: 'streaming',
      modelName: agent.model_engine || agent.name,
      toolCalls: [],
      timeline: [],
      createdAt: new Date().toISOString(),
      tokens: { input: 0, output: 0, total: 0 },
    }
    if (!effectiveOverdrive) session.messages.push(aiMsgSeed)
    // 必须使用响应式数组返回的代理对象继续写入。
    // 若继续修改 push 前的普通对象，message_id/content/thought 的流式更新不会触发 Vue，
    // 会出现 Token 已更新但正文气泡保持空白，刷新后才显示的现象。
    const aiMsg = effectiveOverdrive ? aiMsgSeed : session.messages[session.messages.length - 1]!

    // 标题随对话演进刷新：首轮必算，之后每满 3 条用户消息重算一次，以捕捉后续多轮里
    // 用户真正关心的基因/流程/文件等细节；锁定或超过 12 轮后停止，避免无谓的 LLM 调用。
    // 仅首轮显示“生成中...”占位，刷新轮静默替换，避免已成型标题闪烁成占位文案。
    const userCount = session.messages.filter((m) => m.role === 'user').length
    const isFirstTurn = userCount === 1
    const shouldGenerateTitle =
      !session.title_locked && userCount <= 12 && (isFirstTurn || userCount % 3 === 0)
    if (isFirstTurn) session.title = '生成中...'

    // 构建送后端的上下文（含历史，排除当前 AI 占位）
    const ctxLen = chatStore.conversationSettings.contextLength ?? 20
    const apiMessages = session.messages
      .filter((m) => m.id !== aiId && m.role !== 'assistant' || (m.role === 'assistant' && m.content.length > 0))
      .slice(-ctxLen)
      .map((m) => ({ role: m.role, content: m.content, metadata: m.metadata }))

    // @ 挂载技能：在最后一条用户消息注入显式技能上下文，使模型优先运用对应能力
    if (options.skillNames?.length) {
      const lastUser = [...apiMessages].reverse().find((m) => m.role === 'user')
      if (lastUser) {
        lastUser.content += `\n\n[用户为本次对话挂载技能：${options.skillNames.join('、')}，请优先运用相关能力作答。]`
      }
    }

    // 当前消息的附件（仅最后一条用户消息需要）
    const apiAttachments = options.attachments?.map((a) => ({
      type: (a.type === 'directory' ? 'directory' : a.type.startsWith('image/') ? 'image' : 'file') as 'image' | 'file' | 'directory',
      url: a.url || '',
      name: a.name,
      mime_type: a.type,
      file_id: a.file_id,
      source: a.source,
      recursive: a.recursive === true,
    })) || []

    isStreaming.value = true
    streamingContent.value = ''
    streamingThought.value = ''

    // 是否已有真实后端 session_id（首次为空，后端创建后回填）
    let backendSessionId: string | undefined
    if (session.id.startsWith('sess-') === false) backendSessionId = session.id

    // 新会话首次发消息时加锁，直到 onSessionCreated 回填真实 ID
    if (session.id.startsWith('sess-')) createSessionIdLock()

    await streamChat(
      {
        agentId: agent.id,
        messages: apiMessages,
        sessionId: backendSessionId,
        mode: session.mode,
        modelId: session.model_id,
        temperature: chatStore.conversationSettings.temperature,
        maxTokens: chatStore.conversationSettings.maxTokens,
        deepThinking: chatStore.deepThinking,
        attachments: apiAttachments,
        enableWebSearch: options.enableWebSearch ?? chatStore.enableWebSearch,
        enableCodeExecution: options.enableCodeExecution ?? false,
        mcpMode: options.mcpMode ?? session.mcp_mode ?? 'auto',
        extraMcpServers: options.extraMcpServers ?? session.extra_mcp_servers ?? [],
        multiAgent: options.multiAgent ?? session.multi_agent ?? false,
        overdrive: effectiveOverdrive,
        extendMaxRounds: options.extendMaxRounds ?? false,
      },
      {
        onText: (text, isReasoning) => {
          if (effectiveOverdrive) return
          if (isReasoning) {
            streamingThought.value += text
            aiMsg.thought = streamingThought.value
          } else {
            streamingContent.value += text
            aiMsg.content = streamingContent.value
            // 交错时间线：连续正文并入上一个 text 段；工具调用之后另起新段
            const segs = aiMsg.timeline
            const last = segs?.[segs.length - 1]
            if (last?.kind === 'text') {
              last.text = (last.text || '') + text
            } else {
              segs?.push({ kind: 'text', text })
            }
          }
          session.updated_at = new Date().toISOString()
        },
        onSessionCreated: (sessionId, messageId) => {
          // 首个文本块只回填后端 ID。不要在流式过程中加载历史消息：
          // 此时后端助手行仍是 streaming/0 token，会替换正在更新的 aiMsg。
          if (session.id.startsWith('sess-')) {
            session.id = sessionId
            session.agent_id = agent.id
            currentSessionId.value = sessionId
            syncAgentTeamsEventSubscriptions(session)
            if (messageId) aiMsg.backendMessageId = messageId
            releaseSessionIdLock()
          }
        },
        onModeChanged: (enabled, degraded) => {
          session.overdrive = enabled
          if (enabled) {
            const placeholderIndex = session.messages.findIndex((message) => message.id === aiId && !message.content)
            if (placeholderIndex >= 0) session.messages.splice(placeholderIndex, 1)
          }
          const progressMessage: ChatMessage = {
            id: `mode-overdrive-${Date.now()}`,
            role: 'system',
            content: degraded
              ? '协作服务出现可恢复降级，已继续使用 OmicHub 内置协作。'
              : enabled
                ? '已进入超频模式：Manager 将组织专家协作。'
                : '已退出超频模式：恢复普通对话。',
            createdAt: new Date().toISOString(),
          }
          if (enabled) {
            progressMessage.overdriveProgress = {
              phase: 'workers_starting',
              label: '正在准备协作环境',
              completed: 0,
              total: 0,
            }
          }
          session.messages.push(progressMessage)
        },
        onStudioPromoted: (event) => {
          session.mode = 'studio'
          if (event.sessionId) markStudioSession(event.sessionId)
          studioRedirect.value = {
            agentId: event.agentId || agent.id,
            agentName: event.agentName || agent.name,
          }
        },
        onOverdriveProgress: (event) => {
          const progressMessage = [...session.messages].reverse().find(
            (item) => item.role === 'system' && item.overdriveProgress,
          )
          const currentProgress = progressMessage?.overdriveProgress
          if (!progressMessage || !currentProgress) return
          progressMessage.overdriveProgress = {
            ...currentProgress,
            runId: event.runId ?? currentProgress.runId,
            phase: event.phase,
            label: event.label,
            completed: event.total ? event.completed : currentProgress.completed,
            total: event.total || currentProgress.total,
            wave: event.wave ?? currentProgress.wave,
            waveTotal: event.waveTotal ?? currentProgress.waveTotal,
            waveMode: event.waveMode ?? currentProgress.waveMode,
            fallback: event.fallback ?? currentProgress.fallback,
            warning: event.warning ?? currentProgress.warning,
            activities: event.activities?.length ? event.activities : currentProgress.activities,
            tasks: event.tasks?.length ? event.tasks : currentProgress.tasks,
            stalledTaskIds: event.stalledTaskId
              ? [...new Set([...(currentProgress.stalledTaskIds || []), event.stalledTaskId])]
              : currentProgress.stalledTaskIds,
          }
          progressMessage.content = event.label
          session.updated_at = new Date().toISOString()
        },
        onSubagentFanout: (event) => {
          // 对话内并行子 Agent：复用超频泳道结构展示，按 tool_call_id 归属独立卡片。
          const cardId = `fanout-${event.toolCallId || 'anon'}`
          let card = session.messages.find((item) => item.id === cardId)
          const tasks = event.tasks.map((task) => ({
            taskId: String(task.index),
            agentId: task.agentId,
            status: task.status,
          }))
          if (event.phase === 'started') {
            if (!card) {
              const created: ChatMessage = {
                id: cardId,
                role: 'system',
                content: `并行专家协作中（${tasks.length} 位专家）`,
                createdAt: new Date().toISOString(),
                overdriveProgress: {
                  phase: 'worker_running',
                  label: `并行专家协作中（${tasks.length} 位专家）`,
                  completed: 0,
                  total: tasks.length,
                  waveMode: 'parallel',
                  readonly: true,
                  tasks,
                },
              }
              session.messages.push(created)
            }
          } else if (card?.overdriveProgress) {
            const completed = tasks.filter((task) => task.status === 'succeeded' || task.status === 'success').length
            card.overdriveProgress = {
              ...card.overdriveProgress,
              phase: 'completed',
              label: event.summary || '并行专家协作完成',
              completed,
              total: tasks.length || card.overdriveProgress.total,
              tasks: tasks.length ? tasks : card.overdriveProgress.tasks,
            }
            card.content = event.summary || card.content
          }
          session.updated_at = new Date().toISOString()
        },
        onRoomSpeechDelta: (event) => {
          const workerKey = event.workerKey || `worker-${event.sender.agent_id}`
          let message = roomSpeechLiveMessages.get(workerKey)
          if (!message) {
            const liveMessage: ChatMessage = {
              id: `room-live-${workerKey}-${Date.now()}`,
              role: 'assistant',
              content: '',
              status: 'streaming',
              createdAt: new Date().toISOString(),
              senderAgent: {
                id: event.sender.agent_id,
                name: event.sender.name,
                avatar: event.sender.avatar,
                color: event.sender.color,
                role: event.sender.role,
                round: event.round,
              },
            }
            session.messages.push(liveMessage)
            message = session.messages[session.messages.length - 1]!
            roomSpeechLiveMessages.set(workerKey, message)
          }
          if (event.isReasoning) {
            message.thought = `${message.thought || ''}${event.content || ''}`
          } else {
            message.content += event.content || ''
          }
          message.status = 'streaming'
          session.updated_at = new Date().toISOString()
        },
        onRoomSpeech: (event) => {
          const fullContent = event.content || ''
          const workerKey = event.workerKey || `worker-${event.sender.agent_id}`
          const liveMessage = roomSpeechLiveMessages.get(workerKey)
          if (liveMessage) {
            liveMessage.backendMessageId = event.messageId
            liveMessage.content = fullContent || liveMessage.content
            liveMessage.thought = event.thought || liveMessage.thought
            liveMessage.status = 'complete'
            liveMessage.overdriveSummary = event.summary
            liveMessage.overdriveArtifacts = event.artifacts
            liveMessage.overdriveTaskStatus = event.taskStatus
            liveMessage.overdriveErrorSummary = event.errorSummary
            roomSpeechLiveMessages.delete(workerKey)
            roomSpeechMessages.set(workerKey, liveMessage)
            return
          }
          const message: ChatMessage = {
            id: event.messageId || `room-${Date.now()}-${event.sender.agent_id}`,
            backendMessageId: event.messageId,
            role: 'assistant',
            content: '',
            thought: event.thought,
            status: fullContent ? 'streaming' : 'complete',
            createdAt: new Date().toISOString(),
            senderAgent: {
              id: event.sender.agent_id,
              name: event.sender.name,
              avatar: event.sender.avatar,
              color: event.sender.color,
              role: event.sender.role,
              round: event.round,
            },
            overdriveSummary: event.summary,
            overdriveArtifacts: event.artifacts,
            overdriveTaskStatus: event.taskStatus,
            overdriveErrorSummary: event.errorSummary,
          }
          session.messages.push(message)
          if (!fullContent) return
          // 必须使用响应式数组返回的代理对象继续写入，否则流式更新不触发 Vue
          const proxy = session.messages[session.messages.length - 1]!
          roomSpeechMessages.set(workerKey, proxy)
          if (event.sender.role === 'worker') {
            proxy.content = fullContent
            proxy.status = 'complete'
            return
          }
          roomSpeechFullText.set(proxy.id, fullContent)
          // 播放节奏随长度缩放（约 60 字/秒，1.2s–12s 收敛）：
          // 旧实现任意长度都 ~1.5s 播完，长报告读起来像一次性弹出；
          // 短发言保留下限，避免一闪而过。
          const TICK_MS = 25
          const duration = Math.min(12000, Math.max(1200, (fullContent.length / 60) * 1000))
          const step = Math.max(1, Math.ceil(fullContent.length / (duration / TICK_MS)))
          const timer = window.setInterval(() => {
            const shown = proxy.content.length
            if (shown + step >= fullContent.length) {
              proxy.content = fullContent
              proxy.status = 'complete'
              window.clearInterval(timer)
              roomSpeechTimers.delete(timer)
              roomSpeechFullText.delete(proxy.id)
            } else {
              proxy.content = fullContent.slice(0, shown + step)
            }
          }, 25)
          roomSpeechTimers.add(timer)
        },
        onOverdriveApproval: (event) => {
          const target = (event.workerKey ? roomSpeechMessages.get(event.workerKey) : undefined)
            || [...session.messages].reverse().find((message) => (
              message.role === 'assistant'
              && message.senderAgent?.id === event.agentId
            ))
          if (!target) return
          target.overdriveApproval = {
            approvalId: event.approval.approval_id,
            runId: event.approval.run_id,
            toolName: event.approval.tool_name,
            arguments: event.approval.arguments,
            status: event.approval.status,
            result: event.approval.result,
            error: event.approval.error,
            reason: event.approval.reason,
            caseId: event.approval.case_id,
          }
        },
        onToolCall: (event) => {
          const toolMessage = effectiveOverdrive
            ? [...session.messages].reverse().find((item) => item.role === 'assistant' && item.senderAgent)
              || aiMsg
            : aiMsg
          if (!toolMessage.toolCalls) toolMessage.toolCalls = []
          const toolCallId = event.tool_call_id || `tc-${Date.now()}`
          toolMessage.toolCalls.push({
            id: toolCallId,
            name: event.tool_name,
            arguments: event.arguments,
            status: 'running',
            mcpServer: event.mcp_server,
            purpose: event.purpose,
          })
          // 交错时间线：记录这次工具调用的位置，正文段在其后另起
          toolMessage.timeline ||= []
          toolMessage.timeline.push({ kind: 'tool', toolCallId })
        },
        onToolResult: (event) => {
          const toolMessage = effectiveOverdrive
            ? [...session.messages].reverse().find((item) => item.role === 'assistant' && item.senderAgent)
              || aiMsg
            : aiMsg
          const tc = (toolMessage.toolCalls || []).find((t) => t.id === event.tool_call_id)
          if (tc) {
            tc.result = event.result
            // 兼容：event.ui_payload 缺失但 event.result 里包着 ui_payload 的情况
            let uiPayload = event.ui_payload
            if (!uiPayload && event.result && typeof event.result === 'object') {
              const r = event.result as Record<string, unknown>
              uiPayload = (r.ui_payload as Record<string, unknown> | undefined)
                || (r.uiPayload as Record<string, unknown> | undefined)
            }
            tc.uiPayload = uiPayload
            // 研究源超时是降级而非失败(规划会继续),单独标记避免误导。
            const resultStatus = String(
              (event.result as Record<string, unknown> | undefined)?.status
              ?? uiPayload?.status
              ?? '',
            )
            tc.status = event.success ? 'success' : resultStatus === 'timed_out' ? 'timed_out' : 'error'
            tc.mcpServer = event.mcp_server
            // Studio 工具：未走 tool_output 流时，用 ui_payload 的 stdout/stderr 回填输出区
            if (!tc.output && uiPayload) {
              const so = typeof uiPayload.stdout === 'string' ? uiPayload.stdout : ''
              const se = typeof uiPayload.stderr === 'string' ? uiPayload.stderr : ''
              if (so || se) tc.output = appendBoundedStudioOutput('', so + se)
            }
            if (event.success && (tc.name === 'workspace_write' || tc.name === 'workspace_edit')) {
              const changedPath = String(tc.arguments.path || uiPayload?.path || '')
              if (changedPath) {
                window.dispatchEvent(new CustomEvent('omichub:studio-file-changed', {
                  detail: { sessionId: session.id, path: changedPath, tool: tc.name },
                }))
              }
            }
          }
        },
        onSkill: (event) => {
          // Skill 调用可视化：同一消息内同技能多次调用合并为一张卡片（计数），不刷屏
          if (!event.skill_id) return
          const cards = aiMsg.skillInvocations || (aiMsg.skillInvocations = [])
          let card = cards.find((c) => c.skill_id === event.skill_id)
          if (event.phase === 'invoked') {
            if (card) {
              card.count += 1
              card.status = 'running'
              card.error = undefined
              card.ts = Date.now()
            } else {
              card = {
                id: `skill-${event.skill_id}-${Date.now()}`,
                skill_id: event.skill_id,
                name: event.name || event.skill_id,
                icon: event.icon || '🧩',
                version: event.version || '',
                source: event.source || '',
                agent: event.agent,
                status: 'running',
                count: 1,
                ts: Date.now(),
              }
              cards.push(card)
              // 交错时间线：技能卡片渲染在发生位置的正文之后
              aiMsg.timeline?.push({ kind: 'skill', skillCardId: card.id })
              // 首次调用通知：宿主组件监听后按 localStorage 去重弹轻提示
              window.dispatchEvent(new CustomEvent('omichub:skill-invoked', {
                detail: { skill_id: event.skill_id, name: card.name, version: card.version },
              }))
            }
          } else if (card) {
            card.status = event.phase === 'completed' ? 'success' : 'error'
            card.duration_ms = event.duration_ms
            card.summary = event.summary
            card.error = event.error
          } else {
            // 漏掉 invoked（如断线重连）也要补一张结果卡片
            cards.push({
              id: `skill-${event.skill_id}-${Date.now()}`,
              skill_id: event.skill_id,
              name: event.name || event.skill_id,
              icon: event.icon || '🧩',
              version: event.version || '',
              source: event.source || '',
              agent: event.agent,
              status: event.phase === 'completed' ? 'success' : 'error',
              duration_ms: event.duration_ms,
              summary: event.summary,
              error: event.error,
              count: 1,
              ts: Date.now(),
            })
          }
        },
        onAgentTeamsCase: (event) => {
          if (!event.case_id) return
          const cards = aiMsg.agentTeamsCases || (aiMsg.agentTeamsCases = [])
          const index = cards.findIndex((card) => card.case_id === event.case_id)
          const card = {
            case_id: event.case_id,
            title: event.title,
            status: event.status,
            next_actor: event.next_actor,
            case_url: event.case_url,
          }
          if (index >= 0) cards[index] = card
          else cards.push(card)
          session.multi_agent = true
          syncAgentTeamsEventSubscriptions(session)
        },
        onWebSearchResults: (sources) => {
          aiMsg.webSources = sources
        },
        onPlan: (steps) => {
          currentPlan.value = steps
        },
        onRoundLimit: (event) => {
          if (event.canExtend) {
            roundLimitPrompt.value = { sessionId: event.sessionId, maxRounds: event.maxRounds }
          }
        },
        onContextCompressed: (estimatedTokens) => {
          contextCompressedNotice.value = estimatedTokens
        },
        onApprovalRequest: (event) => {
          // 找到对应工具卡片：置 awaiting_approval 并保存审批信息（卡片由 ApprovalCard 接管交互）
          const tc = (aiMsg.toolCalls || []).find((t) => t.id === event.tool_call_id)
          if (!tc) return
          tc.status = 'awaiting_approval'
          tc.approval = {
            approval_id: event.approval_id,
            status: 'pending',
            risk_hint: event.risk_hint,
            timeout_seconds: event.timeout_seconds,
          }
          // 审批事件的 arguments 可能比 tool_call 事件更全，以其为准补齐
          tc.arguments = { ...tc.arguments, ...event.arguments }
        },
        onApprovalResolved: (event) => {
          const tc = (aiMsg.toolCalls || []).find((t) => t.id === event.tool_call_id)
          if (!tc?.approval) return
          tc.approval.status = event.action
          if (event.action === 'approved' || event.action === 'edited') {
            // 批准后工具照常执行，回到 running 等待 tool_output/tool_result
            tc.status = 'running'
          } else {
            // rejected/timeout：后端会以 rejected tool_result 收尾；先落定终态
            tc.status = 'error'
          }
        },
        onAskRequest: (event) => {
          const target = effectiveOverdrive
            ? [...session.messages].reverse().find((message) => message.role === 'assistant' && message.senderAgent)
            : aiMsg
          if (!target) return
          target.askRequest = {
            kind: event.kind,
            questions: event.questions || [],
            planConfirmation: event.planConfirmation,
            answered: false,
          }
        },
        onRoute: (event) => {
          // 智能路由：记录本条消息实际由哪位专家回答（气泡头部徽标）
          aiMsg.routedAgent = {
            agentId: event.agent_id,
            name: event.name,
            avatar: event.avatar,
            color: event.color,
            reason: event.reason,
            intent: event.intent,
            confidence: event.confidence,
            transition: event.transition
              ? {
                  visible: event.transition.visible,
                  stage: event.transition.stage,
                  title: event.transition.title,
                  message: event.transition.message,
                  nextStep: event.transition.next_step,
                  requiresExecutionConfirmation: event.transition.requires_execution_confirmation,
                  autoStart: event.transition.auto_start,
                }
              : undefined,
          }
          if (event.transition?.auto_start) {
            maybeRedirectToStudio(event.agent_id, event.name)
          }
        },
        onHandoff: (event) => {
          // 交接后会话绑定目标 Agent，下一轮消息直接由目标继续；当前消息的工具卡保留完整交接摘要。
          session.agent_id = event.target_agent_id
          const target = getAgent(event.target_agent_id)
          if (target) {
            aiMsg.routedAgent = {
              agentId: target.id,
              name: target.name,
              avatar: target.avatar,
              color: target.color,
              reason: event.reason,
            }
            maybeRedirectToStudio(target.id, target.name)
          }
          const sourceName = event.source_agent_name || getAgent(event.source_agent_id)?.name || event.source_agent_id
          const targetName = event.target_agent_name || target?.name || event.target_agent_id
          session.messages.push({
            id: `handoff-${session.id}-${event.hop_index}-${Date.now()}`,
            role: 'system',
            content: `${sourceName} → ${targetName}（原因：${event.reason || '继续处理当前任务'}）`,
            createdAt: new Date().toISOString(),
          })
          session.updated_at = new Date().toISOString()
        },
        onConsultation: (event) => {
          aiMsg.consultation = {
            experts: event.experts,
            consultationId: event.consultation_id,
            consultationSummary: event.consultation_summary,
            caseAvailable: event.case_available,
          }
        },
        onCollaborationRoute: (event) => {
          aiMsg.collaborationRoute = event
        },
        onToolOutput: (tool, _stream, data, toolCallId) => {
          // 优先按 tool_call_id 精确匹配；无 id（旧事件）时回退为最后一个同名 running 工具
          const toolMessage = effectiveOverdrive
            ? [...session.messages].reverse().find((item) => item.role === 'assistant' && item.senderAgent)
              || aiMsg
            : aiMsg
          const tcs = toolMessage.toolCalls || []
          const tc = toolCallId
            ? tcs.find((t) => t.id === toolCallId)
            : [...tcs].reverse().find((t) => t.status === 'running' && (!tool || t.name === tool))
          if (tc) tc.output = appendBoundedStudioOutput(tc.output || '', data)
        },
        onRetry: (attempt, maxAttempts) => {
          // 连接中断后自动重试的进度提示（不打断对话，仅插入一条系统消息）
          if (!session.overdrive && !effectiveOverdrive) {
            session.messages.push({
              id: `stream-retry-${Date.now()}-${attempt}`,
              role: 'system',
              content: `服务短暂波动，正在自动恢复（第 ${attempt}/${maxAttempts} 次）…`,
              createdAt: new Date().toISOString(),
            })
          }
        },
        onError: (error) => {
          cleanupStreamRetryNotices(session)
          if (session.overdrive || effectiveOverdrive) {
            finalizeRoomSpeeches()
            session.messages.push({ id: `room-error-${Date.now()}`, role: 'system', content: `超频模式执行失败: ${error}`, createdAt: new Date().toISOString() })
            isStreaming.value = false
            releaseSessionIdLock()
            return
          }
          aiMsg.content = streamingContent.value || `生成失败: ${error}`
          aiMsg.thought = streamingThought.value || undefined
          aiMsg.status = 'error'
          aiMsg.toolCalls = (aiMsg.toolCalls || []).map((t) =>
            t.status === 'running' ? { ...t, status: 'error' as const } : t,
          )
          isStreaming.value = false
          streamingContent.value = ''
          streamingThought.value = ''
          releaseSessionIdLock()
        },
        onDone: (_, messageId, usage, finishReason, finalContent, finalReasoning) => {
          cleanupStreamRetryNotices(session)
          if (session.overdrive || effectiveOverdrive) {
            finalizeRoomSpeeches()
            isStreaming.value = false
            releaseSessionIdLock()
            return
          }
          if (!streamingContent.value && finalContent) {
            streamingContent.value = finalContent
          }
          if (!streamingThought.value && finalReasoning) {
            streamingThought.value = finalReasoning
          }
          aiMsg.content = streamingContent.value || aiMsg.content
          aiMsg.thought = streamingThought.value || undefined
          if (finishReason) aiMsg.finishReason = finishReason
          if (usage) {
            const input = usage.prompt_tokens ?? usage.input_tokens ?? usage.input ?? 0
            const output = usage.completion_tokens ?? usage.output_tokens ?? usage.output ?? 0
            const total = usage.total_tokens ?? usage.total ?? input + output
            // 以服务端返回的 assistant message_id 定位，避免流期间对象被替换后写入旧引用。
            const targetId = messageId || aiMsg.backendMessageId || aiMsg.id
            const target = session.messages.find(
              (item) => (item.id === targetId || item.backendMessageId === targetId) && item.role === 'assistant',
            )
            ;(target || aiMsg).tokens = { input, output, total }
          }
          if (finishReason === 'length' && aiMsg.content.trim()) {
            aiMsg.content += '\n\n---\n⚠️ *回答因达到最大长度限制而截断，可尝试缩短提问或分步追问。*'
          }
          if (!aiMsg.content.trim() && !aiMsg.toolCalls?.length) {
            aiMsg.status = aiMsg.thought ? 'empty' : 'error'
            reportChatDiagnostic({
              phase: 'stream-empty',
              messageId: aiMsg.backendMessageId || aiMsg.id,
              sessionId: session.id,
              rawResponseSummary: {
                usage,
                finishReason,
                hasThought: Boolean(aiMsg.thought?.trim()),
              },
            })
            if (!aiMsg.thought) {
              aiMsg.content = '当前模型响应为空，请重新发送'
            }
          }
          if (aiMsg.status !== 'error' && aiMsg.status !== 'empty') aiMsg.status = 'complete'
          isStreaming.value = false
          streamingContent.value = ''
          streamingThought.value = ''
          releaseSessionIdLock()
        },
      },
    )

    if (shouldGenerateTitle && !isStreaming.value) {
      void generateSessionTitle(session.id)
    }

    // 兜底：若流异常中断未触发 onDone/onError（极罕见，onDone 已有内部兜底）
    if (isStreaming.value) {
      finalizeRoomSpeeches()
      cleanupStreamRetryNotices(session)
      if (!session.overdrive) {
        aiMsg.content = streamingContent.value || aiMsg.content
        aiMsg.thought = streamingThought.value || undefined
        if (!aiMsg.content.trim() && !aiMsg.toolCalls?.length) {
          aiMsg.status = aiMsg.thought ? 'empty' : 'error'
          if (!aiMsg.thought) {
            aiMsg.content = '当前模型响应为空，请重新发送'
          }
        }
      }
      isStreaming.value = false
      streamingContent.value = ''
      streamingThought.value = ''
      releaseSessionIdLock()
    }
  }

  function stopStreaming() {
    abortStream()
    finalizeRoomSpeeches()
    const session = currentSession.value
    if (session) {
      const last = session.messages[session.messages.length - 1]
      if (last && last.role === 'assistant') {
        last.content = streamingContent.value || last.content || '（已停止）'
        last.thought = streamingThought.value || undefined
        // 流在 AbortError 后不会再触发 onDone；主动收束消息状态，
        // 避免消息卡片一直保留为 streaming 状态。
        last.status = 'complete'
      }
    }
    isStreaming.value = false
    streamingContent.value = ''
    streamingThought.value = ''
    releaseSessionIdLock()
  }

  /** 暂停流式输出：保留已输出文本，标记暂停态供 UI 显示继续/重新生成按钮 */
  function pauseStreaming() {
    pauseStream()
    const session = currentSession.value
    if (session) {
      const last = session.messages[session.messages.length - 1]
      if (last && last.role === 'assistant') {
        last.content = streamingContent.value || last.content
        last.thought = streamingThought.value || undefined
        last.status = 'streaming'
      }
    }
    releaseSessionIdLock()
  }

  // ========== Studio HITL：审批 / 澄清 / 权限模式 ==========

  /** 在所有会话消息中定位待审批的工具卡片（审批仅内存态，限定当前会话即可） */
  function findApprovalTool(approvalId: string): ToolCall | null {
    const session = currentSession.value
    if (!session) return null
    for (const msg of session.messages) {
      const tc = (msg.toolCalls || []).find((t) => t.approval?.approval_id === approvalId)
      if (tc) return tc
    }
    return null
  }

  /** 批准待审批工具；带 modifiedArgs 即"编辑后批准"（乐观更新，后端决议经 approval_resolved 回写） */
  async function approveToolCall(
    approvalId: string,
    modifiedArgs?: Record<string, unknown>,
  ): Promise<void> {
    if (!isStreaming.value) {
      throw new Error('APPROVAL_STREAM_INACTIVE')
    }
    const tc = findApprovalTool(approvalId)
    if (tc?.approval && tc.approval.status === 'pending') {
      tc.approval.status = modifiedArgs ? 'edited' : 'approved'
      tc.status = 'running'
    }
    try {
      await studioApi.approveApproval(approvalId, modifiedArgs)
    } catch (e) {
      if (tc?.approval) {
        tc.approval.status = 'pending'
        tc.status = 'awaiting_approval'
      }
      throw e
    }
  }

  /** 退回待审批工具（理由回灌 LLM 让其修改后重试） */
  async function rejectToolCall(approvalId: string, reason?: string): Promise<void> {
    if (!isStreaming.value) {
      throw new Error('APPROVAL_STREAM_INACTIVE')
    }
    const tc = findApprovalTool(approvalId)
    if (tc?.approval && tc.approval.status === 'pending') {
      tc.approval.status = 'rejected'
      tc.status = 'error'
    }
    try {
      await studioApi.rejectApproval(approvalId, reason)
    } catch (e) {
      if (tc?.approval) {
        tc.approval.status = 'pending'
        tc.status = 'awaiting_approval'
      }
      throw e
    }
  }

  function findOverdriveApproval(approvalId: string): ChatMessage['overdriveApproval'] | null {
    const session = currentSession.value
    if (!session) return null
    for (const message of session.messages) {
      if (message.overdriveApproval?.approvalId === approvalId) return message.overdriveApproval
    }
    return null
  }

  async function approveOverdriveApproval(approvalId: string): Promise<void> {
    const sessionId = currentSessionId.value
    const approval = findOverdriveApproval(approvalId)
    if (!sessionId || !approval || approval.status !== 'pending') return
    approval.status = 'executing'
    try {
      if (approval.runId) {
        const resolved = await chatApi.decideOverdriveBranchApproval(
          sessionId, approval.runId, approvalId, 'approve',
        )
        approval.status = String(resolved.status) === 'queued' ? 'completed' : 'failed'
        return
      }
      if (approval.caseId) {
        const resolved = await agentTeamsApi.submitCase(approval.caseId, { task_name: approval.toolName || 'OmicHub 分析任务' })
        Object.assign(approval, { status: resolved.status === 'submitted' ? 'completed' : 'executing' })
        return
      }
      const resolved = await chatApi.approveOverdriveApproval(sessionId, approvalId)
      Object.assign(approval, {
        approvalId: resolved.approval_id,
        toolName: resolved.tool_name,
        arguments: resolved.arguments,
        status: resolved.status,
        result: resolved.result,
        error: resolved.error,
        reason: resolved.reason,
      })
    } catch (error) {
      approval.status = 'pending'
      throw error
    }
  }

  async function rejectOverdriveApproval(approvalId: string, reason?: string): Promise<void> {
    const sessionId = currentSessionId.value
    const approval = findOverdriveApproval(approvalId)
    if (!sessionId || !approval || approval.status !== 'pending') return
    approval.status = 'rejected'
    try {
      if (approval.runId) {
        await chatApi.decideOverdriveBranchApproval(
          sessionId, approval.runId, approvalId, 'reject', reason || '',
        )
        return
      }
      if (approval.caseId) return
      const resolved = await chatApi.rejectOverdriveApproval(sessionId, approvalId, reason)
      Object.assign(approval, {
        approvalId: resolved.approval_id,
        toolName: resolved.tool_name,
        arguments: resolved.arguments,
        status: resolved.status,
        result: resolved.result,
        error: resolved.error,
        reason: resolved.reason,
      })
    } catch (error) {
      approval.status = 'pending'
      throw error
    }
  }

  /**
   * 回答 ask_user 澄清：把按问题顺序收集的答案拼成结构化文本，作为下一条用户消息发送。
   * 空串答案视为跳过（由 AI 自行决定）。
   */
  async function answerAskRequest(answers: string[]): Promise<void> {
    const session = currentSession.value
    let target: ChatMessage['askRequest'] | null = null
    let originalRequest = ''
    if (session) {
      for (let i = session.messages.length - 1; i >= 0; i--) {
        const msg = session.messages[i]
        if (msg.askRequest && !msg.askRequest.answered) {
          msg.askRequest.answered = true
          msg.askRequest.answers = answers
          target = msg.askRequest
          originalRequest = session.messages
            .slice(0, i)
            .reverse()
            .find((item) => item.role === 'user')
            ?.content
            .trim() || ''
          break
        }
      }
    }
    const questions = target?.questions || []
    const text = questions.length
      ? questions
          .map((q, i) => {
            const answer = (answers[i] || '').trim()
            return q.question
              ? `${q.question}\n回答：${answer || '无偏好，由你决定'}`
              : answer || '无偏好，由你决定'
          })
          .join('\n\n')
          .trim()
      : (answers[0] || '').trim()
    if (!text) return
    const followUp = originalRequest
      ? `原始任务：${originalRequest}\n\n补充信息：\n${text}`
      : text
    await sendMessage(followUp)
  }

  function findPlanConfirmation(runId: string): PlanConfirmation | null {
    const session = currentSession.value
    if (!session) return null
    for (let index = session.messages.length - 1; index >= 0; index -= 1) {
      const plan = session.messages[index].askRequest?.planConfirmation
      if (plan?.runId === runId) return plan
    }
    return null
  }

  function findOverdriveProgress(runId: string): NonNullable<ChatMessage['overdriveProgress']> | null {
    const session = currentSession.value
    if (!session) return null
    for (let index = session.messages.length - 1; index >= 0; index -= 1) {
      const progress = session.messages[index].overdriveProgress
      if (progress?.runId === runId) return progress
    }
    return null
  }

  async function decideOverdrivePlan(
    runId: string,
    action: PlanDecisionAction,
    feedback = '',
  ): Promise<void> {
    const sessionId = currentSessionId.value
    const plan = findPlanConfirmation(runId)
    if (!sessionId || !plan || !plan.actions.includes(action) || plan.status !== 'pending') return
    const request = sessionId.startsWith('sess-')
      ? null
      : chatApi.decideOverdrivePlan(sessionId, runId, {
          action,
          planVersion: plan.planVersion,
          planHash: plan.planHash,
          feedback: feedback.trim(),
          commandId: globalThis.crypto?.randomUUID?.()
            || `plan-${runId}-${plan.planVersion}-${Date.now()}`,
        })
    if (!request) throw new Error('会话尚未完成初始化，请稍后重试')
    plan.status = 'submitting'
    plan.error = undefined
    try {
      await request
      plan.feedback = feedback.trim() || undefined
      plan.status = action === 'approve'
        ? 'approved'
        : action === 'revise'
          ? 'revision_requested'
          : 'cancelled'
      const ask = currentSession.value?.messages.find(
        (message) => message.askRequest?.planConfirmation === plan,
      )?.askRequest
      if (ask) ask.answered = true
      if (action === 'cancel') {
        const progress = findOverdriveProgress(runId)
        if (progress) {
          progress.phase = 'terminated'
          progress.label = '用户已取消本轮超频协作，计划不会执行'
          progress.completed = 0
          progress.total = 0
          progress.tasks = []
          progress.readonly = true
          progress.warning = '计划快照已保留，但专家协作与结论交付均未开始。'
        }
      }
      // Plan approval/revision transitions immediately leave the synchronous chat
      // stream. Start the durable event subscription here so a newly frozen
      // revision and its confirmation card appear without requiring a refresh.
      if (action !== 'cancel') void recoverOverdriveRun(sessionId)
    } catch (error) {
      plan.status = 'pending'
      plan.error = error instanceof Error ? error.message : '计划决策提交失败'
      throw error
    }
  }

  /** 进入会话时按后端 detail.permissions 初始化（默认 supervised） */
  function initStudioPermissions(mode?: StudioPermissionMode): void {
    studioPermissions.value = { mode: mode || 'supervised' }
  }

  /** 切换当前 Studio 会话权限模式（调 API 后更新本地态） */
  async function setStudioPermissions(mode: StudioPermissionMode): Promise<void> {
    const sessionId = currentSessionId.value
    if (!sessionId || sessionId.startsWith('sess-')) return
    const prev = studioPermissions.value.mode
    studioPermissions.value = { mode }
    try {
      const saved = await studioApi.updatePermissions(sessionId, mode)
      studioPermissions.value = { mode: saved.mode || mode }
    } catch (e) {
      studioPermissions.value = { mode: prev }
      throw e
    }
  }

  return {
    // state
    mcps, skills, agents, sessions, currentSessionId,
    isStreaming, isPaused, streamingContent, streamingThought, availableModels, pipelineTasks,
    roundLimitPrompt,
    contextCompressedNotice,
    studioRedirect,
    maybeRedirectToStudio,
    clearStudioRedirect,
    studioSessionIds, currentPlan, studioPermissions,
    // getters
    activeAgents, currentSession, currentAgent, effectiveAgent, groupedSessions,
    // lookups
    getAgent, mcpsByIds, skillsByIds,
    // asset actions
    fetchAgents, fetchMcps, fetchUserSelectableMcps, fetchSkills, initAssets, fetchAvailableModels, fetchSessions,
    fetchStudioSessionIds, markStudioSession,
    toggleMcpStatus, addMcpServer, updateMcpServer, removeMcpServer, testMcpServer, fetchMcpTools, fetchMcpLogs,
    fetchMcpVersions, rollbackMcpServer, promoteMcpServer, syncMcpPresets,
    upsertAgent, toggleAgent, deleteAgent, setDefaultAgent,
    previewSkillFromGithub, previewSkillFromZip, previewSkillFromMarkdown, previewSkillFromJson, confirmSkillImport,
    fetchSkillMarketplace, installMarketplaceSkill, checkSkillUpdate,
    fetchAliyunMarketStatus, syncAliyunMarket, installAliyunMarketSkill,
    fetchSkillInvocationStats, fetchSkillInvocations,
    fetchSkillVersions, rollbackSkill, fetchSkillVersionDetail, fetchSkillReferences,
    toggleSkill, deleteSkill,
    // session actions
    startSessionFromAgent, selectSession, newChat, deleteSession, renameSession, generateSessionTitle,
    searchSessions, switchSessionModel, loadSessionMessages, sendMessage, stopStreaming, pauseStreaming,
    submitMessageFeedback,
    approveToolCall, rejectToolCall, approveOverdriveApproval, rejectOverdriveApproval, answerAskRequest,
    decideOverdrivePlan,
    initStudioPermissions, setStudioPermissions,
    invokePipelineTool, submitPipelineTask, trackPipelineTask, pollPipelineTask,
    retryPipelineTask, stopPipelinePolling,
  }
})
