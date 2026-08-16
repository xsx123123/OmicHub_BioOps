<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NPopconfirm,
  NProgress,
  NSpin,
  NTag,
  NTooltip,
  useMessage,
} from 'naive-ui'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import {
  AddOutline,
  CaretDownOutline,
  CaretUpOutline,
  CloseOutline,
  FileTrayOutline,
  MenuOutline,
  RefreshOutline,
  SearchOutline,
  SettingsOutline,
  SparklesOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import {
  agentTeamsApi,
  type AgentTeamsCase,
  type AgentTeamsCaseStatus,
  type AgentTeamsContextRef,
  type AgentTeamsEvent,
} from '@/api/agentTeams'
import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import MessageArtifactGallery from '@/components/ai-chat/MessageArtifactGallery.vue'
import AgentTeamsSettingsDrawer from '@/components/agent-teams/AgentTeamsSettingsDrawer.vue'
import type { FileAttachment } from '@/components/ai-chat/types'
import { useAgentTeamsOnboardingStore } from '@/stores/agentTeamsOnboarding'
import { useAgentTeamsPreferencesStore } from '@/stores/agentTeamsPreferences'
import { mergeAgentTeamsEvents, shouldPollAgentTeamsCase } from '@/utils/agentTeamsState'
import {
  agentTeamsCaseCategory,
  agentTeamsCaseStageMap,
  agentTeamsFailedStatuses,
  canSendRoomMessage,
  formatAgentTeamsStatus,
  type AgentTeamsCaseCategory,
  type AgentTeamsCaseStage,
} from '@/utils/agentTeamsStatus'
import {
  buildRoomCreateIntent,
  formatDuration,
  formatHardGate,
  formatMentions,
  groupRoomMessages,
  isContentTruncated,
  projectCaseEvents,
  resolveElementRoomUrl,
  resolveManagerTyping,
  shouldStartNewRoomCase,
  type RoomRoleMetadata,
  type RoomWorkerBlock,
  type RoomWorkerStep,
} from '@/utils/agentTeamsRoom'

const POLLING_INTERVAL_MS = 20_000
const SSE_RETRY_INITIAL_MS = 1_000
const SSE_RETRY_MAX_MS = 30_000
const LOCAL_TYPING_TTL_MS = 60_000

const message = useMessage()
const loading = ref(false)
const available = ref(true)
const cases = ref<AgentTeamsCase[]>([])
const selectedCaseId = ref('')
const detail = ref<AgentTeamsCase | null>(null)
const events = ref<AgentTeamsEvent[]>([])
const eventCursor = ref<string | null>(null)
const roleMetadata = ref<RoomRoleMetadata>({})
const eventStreamHealthy = ref(false)
const listRef = ref<HTMLElement | null>(null)
const searchQuery = ref('')
const statusFilter = ref<'all' | AgentTeamsCaseCategory>('all')
const submitVisible = ref(false)
const submitting = ref(false)
const approvalConfirmed = ref(false)
const submitTaskName = ref('')
const rejectVisible = ref(false)
const rejectReason = ref('')
const rejecting = ref(false)
const reviseVisible = ref(false)
const revising = ref(false)
const reviseForm = ref({ reason: '', parameters: '{}' })
const retrying = ref(false)
const deletingCaseId = ref('')
const draftMessage = ref('')
const sendingMessage = ref(false)
const roomViewMode = ref<'stream' | 'element'>('stream')
const settingsVisible = ref(false)
const localTypingUntil = ref<number>(0)
const seenEventIds = ref<Set<string>>(new Set())
const expandedStepIds = ref<Set<string>>(new Set())
let pollingTimer: ReturnType<typeof setInterval> | null = null
let eventStreamAbort: AbortController | null = null
let eventStreamRetryTimer: number | null = null
let eventStreamFailures = 0

const sortedCases = computed(() => [...cases.value].sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
const effectiveRoleMetadata = computed<RoomRoleMetadata>(() => {
  const labels = { ...(roleMetadata.value.role_labels || {}) }
  labels['bioops-manager'] = {
    agent_id: labels['bioops-manager']?.agent_id || 'bioops-manager',
    name: roomPreferences.managerLabel,
    avatar: labels['bioops-manager']?.avatar || '🧭',
    color: labels['bioops-manager']?.color || '#4f8ef7',
    role: 'manager',
  }
  for (const [role, label] of Object.entries(labels)) {
    if (label.role === 'manager' || role === 'bioops-manager') {
      labels[role] = { ...label, name: roomPreferences.managerLabel }
    }
  }
  return { ...roleMetadata.value, role_labels: labels }
})
const roomMessages = computed(() => projectCaseEvents(events.value, effectiveRoleMetadata.value))
const visibleMessages = computed(() => roomMessages.value.filter((item) => !item.collapsed))
const collapsedMessages = computed(() => roomMessages.value.filter((item) => item.collapsed))
const roomBlocks = computed(() => groupRoomMessages(visibleMessages.value))
const backendTyping = computed(() => resolveManagerTyping(events.value))
const managerTyping = computed(() => backendTyping.value || localTypingUntil.value > Date.now())
const eventTimes = computed(() => new Map(events.value.map((event) => [event.event_id, event.recorded_at])))
const canApprove = computed(() => detail.value?.status === 'approval_pending')
const canRetry = computed(() => detail.value?.status === 'execution_failed')

// ===== 人工审批卡片（§9.2）：内嵌消息流末尾，终态由 detail.status 单一来源派生，
// 历史重载依赖落库的 planning.frozen 证据事件 + 当前状态，二者俱备才渲染，不伪造 =====
const approvalFrozenEvent = computed(() => {
  for (let index = events.value.length - 1; index >= 0; index -= 1) {
    if (events.value[index].event_type === 'planning.frozen') return events.value[index]
  }
  return null
})

interface RoomApprovalCard {
  state: 'pending' | 'retry' | 'approved' | 'rejected' | 'returned'
  title: string
  summary: string
  impact: string
  /** 终态文案（文本 + 状态色双表达，§5.5）；pending / retry 为空 */
  terminalText: string
  time: string
}

const approvalCard = computed<RoomApprovalCard | null>(() => {
  const current = detail.value
  if (!current) return null
  const status = current.status
  const frozenAt = formatMessageTime(approvalFrozenEvent.value?.event_id ?? '')
  if (status === 'approval_pending') {
    return {
      state: 'pending',
      title: '人工审批请求',
      summary: current.intent,
      impact: '计划已冻结，确认后才会启动真实计算；执行与结果将记录在当前 Case。',
      terminalText: '',
      time: frozenAt,
    }
  }
  if (status === 'execution_failed') {
    return {
      state: 'retry',
      title: '执行失败',
      summary: '任务证据已保留，可按冻结计划重试。',
      impact: '',
      terminalText: '',
      time: '',
    }
  }
  if (!approvalFrozenEvent.value) return null
  if (status === 'cancelled') {
    // Bridge 侧驳回与用户取消均收敛为 cancelled（case.cancelled 事件），文案如实并列表述
    return { state: 'rejected', title: '人工审批', summary: '', impact: '', terminalText: '已驳回或已取消', time: frozenAt }
  }
  if (status === 'waiting_for_correction') {
    return { state: 'returned', title: '人工审批', summary: '', impact: '', terminalText: '已退回修正', time: frozenAt }
  }
  return { state: 'approved', title: '人工审批', summary: '', impact: '', terminalText: '已通过人工审批', time: frozenAt }
})

// 消息流滚动：新消息到达且用户停留在底部时自动滚底；用户上翻时暂停并显示「回到底部」
const listAtBottom = ref(true)

function handleListScroll() {
  const el = listRef.value
  if (!el) return
  listAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}

function scrollListToBottom() {
  listAtBottom.value = true
  listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
}
const roomInputEnabled = computed(() => !selectedCaseId.value || canSendRoomMessage(detail.value?.status))
const roomInputPlaceholder = computed(() => {
  if (!selectedCaseId.value) return '输入需求创建协作房间，@ 引用工作区文件'
  return roomInputEnabled.value ? '发送到协作房间，@ 引用工作区文件…' : 'Case 加载中，暂无法发言'
})

// ===== 输入区：复用平台共享 KimiChatInput（roomMode 纯消息场景），提交只接现有 sendRoomMessage =====
const composerRef = ref<InstanceType<typeof KimiChatInput> | null>(null)

/** 左栏空状态 / 快捷胶囊的下一步引导：聚焦底部输入框 */
function focusComposer() {
  composerRef.value?.focus()
}

/** KimiChatInput 的附件 → Case context_refs（上传文件 / workspace 文件均映射为 file id + 相对路径） */
function refsFromAttachments(attachments?: FileAttachment[]): AgentTeamsContextRef[] {
  return (attachments ?? [])
    .filter((item) => item.type !== 'directory' && !!item.file_id)
    .map((item) => {
      const fileId = item.file_id!
      const id = fileId.startsWith('file://') ? fileId.slice('file://'.length) : fileId
      return { kind: 'file' as const, id, location: item.name }
    })
}

function handleComposerSend(content: string, options: { attachments?: FileAttachment[] }) {
  void sendRoomMessage(content, refsFromAttachments(options.attachments))
}

// ===== 右侧空状态快捷胶囊：复用现有逻辑（填充输入框 / 切换状态筛选），不新增业务流程 =====
interface RoomQuickAction {
  key: string
  label: string
  fill?: string
  filter?: 'all' | AgentTeamsCaseCategory
}

const roomQuickActions: RoomQuickAction[] = [
  { key: 'qc', label: '创建一个数据质控团队', fill: '创建一个数据质控团队：' },
  { key: 'report', label: '让 Manager 汇报进行中的任务', fill: '让 Manager 汇报进行中的任务' },
  { key: 'about', label: '了解 Manager 能做什么', fill: '介绍一下 Manager 能做什么' },
]

function applyRoomQuickAction(action: RoomQuickAction) {
  if (action.filter) {
    statusFilter.value = action.filter
    return
  }
  draftMessage.value = action.fill ?? ''
  nextTick(() => composerRef.value?.focus())
}

// ===== 窄屏（≤1024px）左栏收纳为可折叠抽屉（规范 §7.1）：默认收起，进入 Case 后自动收起 =====
const isNarrowViewport = ref(false)
const sidebarOpen = ref(false)
const sidebarRef = ref<HTMLElement | null>(null)
const sidebarToggleRef = ref<InstanceType<typeof NButton> | null>(null)
let narrowMedia: MediaQueryList | null = null

function syncViewportMode() {
  isNarrowViewport.value = narrowMedia?.matches ?? false
  if (!isNarrowViewport.value) sidebarOpen.value = false
}

function openSidebar() {
  sidebarOpen.value = true
  // 焦点管理：展开后焦点进入抽屉内的搜索框
  void nextTick(() => sidebarRef.value?.querySelector<HTMLElement>('input')?.focus())
}

function closeSidebar() {
  if (!sidebarOpen.value) return
  sidebarOpen.value = false
  // 焦点交还展开按钮
  const toggleEl = sidebarToggleRef.value?.$el as HTMLElement | undefined
  toggleEl?.focus()
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeSidebar()
}
// Matrix 房间已建（room.created 携带 Gateway 下发的 Element 深链）时才提供 Element 嵌入入口。
const elementRoomUrl = computed(() => resolveElementRoomUrl(events.value))

const FILTER_CHIPS: Array<{ key: 'all' | AgentTeamsCaseCategory; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'approval', label: '待审批' },
  { key: 'done', label: '已完成' },
  { key: 'failed', label: '失败' },
]

const categoryCounts = computed(() => {
  const counts: Record<'all' | AgentTeamsCaseCategory, number> = { all: cases.value.length, active: 0, approval: 0, done: 0, failed: 0 }
  for (const item of cases.value) counts[agentTeamsCaseCategory(item.status)] += 1
  return counts
})

const filterChips = computed(() => FILTER_CHIPS.map((chip) => ({ ...chip, count: categoryCounts.value[chip.key] })))

const filteredCases = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return sortedCases.value.filter((item) => {
    if (statusFilter.value !== 'all' && agentTeamsCaseCategory(item.status) !== statusFilter.value) return false
    if (keyword && !item.intent.toLowerCase().includes(keyword)) return false
    return true
  })
})

const STAGE_SEQUENCE: Array<{ key: AgentTeamsCaseStage; label: string }> = [
  { key: 'plan', label: '计划' },
  { key: 'approval', label: '审批' },
  { key: 'execution', label: '执行' },
  { key: 'quality', label: '质控' },
  { key: 'delivery', label: '交付' },
]

const stageView = computed(() => {
  const status = detail.value?.status
  if (!status) return null
  const cancelled = status === 'cancelled'
  const currentIndex = STAGE_SEQUENCE.findIndex((stage) => stage.key === agentTeamsCaseStageMap[status])
  const failed = agentTeamsFailedStatuses.has(status)
  return STAGE_SEQUENCE.map((stage, index) => {
    let state: 'done' | 'current' | 'failed' | 'todo'
    if (cancelled || index > currentIndex) state = 'todo'
    else if (index < currentIndex || status === 'closed') state = 'done'
    else state = failed ? 'failed' : 'current'
    return { ...stage, index, state }
  })
})

const caseTitle = computed(() => {
  if (detail.value) return detail.value.display_title || detail.value.intent
  const selected = cases.value.find((item) => item.case_id === selectedCaseId.value)
  return selected?.display_title || selected?.intent || ''
})

const requesterName = computed(() => {
  const value = detail.value
  if (!value) return ''
  return value.requester_nickname || value.requester_username || value.requester_ref || ''
})

const tagType = (status: AgentTeamsCaseStatus) => {
  if (['closed', 'delivery_ready'].includes(status)) return 'success'
  if (['preflight_blocked', 'quality_blocked', 'execution_failed'].includes(status)) return 'error'
  if (['approval_pending', 'waiting_for_correction', 'remediation_pending'].includes(status)) return 'warning'
  return 'info'
}

function formatMessageTime(eventId: string): string {
  const raw = eventTimes.value.get(eventId)
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function formatDateTime(raw?: string): string {
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { hour12: false })
}

// 房间列表相对时间：复用项目既有 date-fns + zhCN 方案（与 ProfileView / MemoryView 同约定）
function formatRelativeTime(raw?: string): string {
  if (!raw) return ''
  const date = parseISO(raw)
  if (Number.isNaN(date.getTime()) || date.getTime() > Date.now()) return ''
  return formatDistanceToNow(date, { locale: zhCN, addSuffix: true })
}

const ROOM_CATEGORY_LABELS: Record<AgentTeamsCaseCategory, string> = {
  active: '进行中',
  approval: '待审批',
  done: '已完成',
  failed: '失败',
}

/** 房间列表项头像：房间意图首字符徽标（数据模型无房间头像字段，见 P5 缺口清单） */
function caseAvatarLetter(item: AgentTeamsCase): string {
  return (item.display_title || item.intent).trim().charAt(0) || '协'
}

/** 任务进展卡片进度：已完结步骤占比（running 视为未完结），无步骤时模板不渲染 */
function workerStepProgress(block: RoomWorkerBlock): number {
  if (!block.steps.length) return 0
  const settled = block.steps.filter((step) => step.tool.status !== 'running').length
  return Math.round((settled / block.steps.length) * 100)
}

function toggleStepDetail(stepId: string) {
  const next = new Set(expandedStepIds.value)
  if (next.has(stepId)) next.delete(stepId)
  else next.add(stepId)
  expandedStepIds.value = next
}

function isStepExpanded(stepId: string): boolean {
  return expandedStepIds.value.has(stepId)
}

/** action 消息中的按钮统一路由到现有操作。 */
function handleRoomAction(action: string) {
  if (action === 'retry') void retryFailedCase()
  else if (action === 'revise') reviseVisible.value = true
  else if (action === 'cancel') {
    rejectReason.value = '用户终止 Case'
    void confirmReject()
  }
}

/** 「继续生成」入口：项目当前无显式续写接口，按钮仅作提示，由 SSE/轮询自动补全。 */
function handleContinueGeneration() {
  message.info('请稍候，系统会自动续写。')
}

function mergeEvents(incoming: AgentTeamsEvent[]) {
  const uniqueIncoming = incoming.filter((event) => {
    if (seenEventIds.value.has(event.event_id)) return false
    seenEventIds.value.add(event.event_id)
    return true
  })
  if (!uniqueIncoming.length) return
  events.value = mergeAgentTeamsEvents(events.value, uniqueIncoming)
  if (uniqueIncoming.some((event) => event.event_type === 'room.agent_message')) {
    localTypingUntil.value = 0
  }
}

async function loadCases(selectFirst = false) {
  loading.value = true
  try {
    // 优先加载 Case 列表，状态探测在后台完成，避免 Bridge /healthz 延迟阻塞首屏渲染。
    // 若 Bridge 不可用，列表请求本身也会失败，后台探测仅用于降级提示与可用性标识。
    const listPromise = agentTeamsApi.listCases({ limit: 50 }).catch(() => null)
    void agentTeamsApi
      .status()
      .then((state) => {
        available.value = state.available
        if (!state.available) cases.value = []
      })
      .catch(() => { available.value = false })

    const result = await listPromise
    if (!result) {
      message.error('无法获取协作 Case 列表。')
      return
    }
    cases.value = result.items
    if (selectFirst && result.items.length && !selectedCaseId.value) {
      // 不阻塞列表渲染：详情与事件流异步填充
      void selectCase(sortedCases.value[0].case_id)
    }
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '无法获取协作 Case 列表。')
  } finally {
    loading.value = false
  }
}

async function refreshDetail(options: { resetEvents?: boolean; background?: boolean } = {}) {
  if (!selectedCaseId.value) return
  try {
    const cursor = options.resetEvents ? undefined : eventCursor.value ?? undefined
    const [caseData, eventData] = await Promise.all([
      agentTeamsApi.getCase(selectedCaseId.value),
      agentTeamsApi.getEvents(selectedCaseId.value, { cursor, limit: 100 }),
    ])
    detail.value = caseData
    if (options.resetEvents) {
      events.value = eventData.events
      seenEventIds.value = new Set(eventData.events.map((event) => event.event_id))
    } else {
      mergeEvents(eventData.events)
    }
    eventCursor.value = eventData.next_cursor ?? (events.value.at(-1)?.event_id ?? null)
  } catch (cause) {
    if (!options.background) message.error('无法获取协作 Case 详情。')
  }
}

async function selectCase(caseId: string) {
  if (!caseId || caseId === selectedCaseId.value) return
  // 窄屏抽屉模式下进入 Case 后收起左栏
  if (isNarrowViewport.value) sidebarOpen.value = false
  stopEventStream()
  selectedCaseId.value = caseId
  detail.value = null
  events.value = []
  eventCursor.value = null
  localTypingUntil.value = 0
  seenEventIds.value = new Set()
  expandedStepIds.value = new Set()
  roomViewMode.value = 'stream'
  await refreshDetail({ resetEvents: true })
  void startEventStream()
}

async function sendRoomMessage(content: string, contextRefs: AgentTeamsContextRef[] = []) {
  if (!content || !roomInputEnabled.value || sendingMessage.value) return
  const caseId = selectedCaseId.value
  if (
    roomPreferences.settings.autoSplitNewTasks
    && caseId
    && detail.value
    && shouldStartNewRoomCase(detail.value.intent, content, contextRefs)
  ) {
    sendingMessage.value = true
    try {
      message.info('检测到新的系统发育树任务，正在创建独立协作 Case。')
      await createCaseFromDraft(content, contextRefs)
    } catch (cause: any) {
      draftMessage.value = content
      message.error(cause?.response?.data?.detail || '新建系统发育树 Case 失败，请稍后重试。')
    } finally {
      sendingMessage.value = false
    }
    return
  }
  const optimisticEventId = `local-user-message-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  sendingMessage.value = true
  try {
    if (!caseId) {
      await createCaseFromDraft(content, contextRefs)
      return
    }
    mergeEvents([{
      event_id: optimisticEventId,
      recorded_at: new Date().toISOString(),
      case_id: caseId,
      actor: 'current-user',
      event_type: 'room.user_message',
      payload: {
        summary: content.slice(0, 80),
        payload: { actor: 'current-user', content, context_refs: contextRefs },
        optimistic: true,
      },
    }])
    draftMessage.value = ''
    const result = await agentTeamsApi.postCaseMessage(caseId, content, contextRefs)
    const serverEventId = typeof result.event_id === 'string' ? result.event_id : ''
    if (selectedCaseId.value === caseId && serverEventId) {
      const serverEventArrived = events.value.some((event) => event.event_id === serverEventId)
      events.value = serverEventArrived
        ? events.value.filter((event) => event.event_id !== optimisticEventId)
        : events.value.map((event) =>
          event.event_id === optimisticEventId
            ? { ...event, event_id: serverEventId, payload: { ...event.payload, optimistic: true } }
            : event,
        )
    }
    // 用户消息落盘后给出本地“正在输入”提示，覆盖后端 typing 事件未到达或延迟的场景。
    localTypingUntil.value = Date.now() + LOCAL_TYPING_TTL_MS
    // 发言经审计事件回投房间；事件流不可用时立即拉一次，不等轮询。
    if (!eventStreamHealthy.value) await refreshDetail({ background: true })
  } catch (cause: any) {
    if (selectedCaseId.value === caseId) {
      events.value = events.value.filter((event) => event.event_id !== optimisticEventId)
    }
    // 失败兜底：KimiChatInput 在 emit 时已清空自身草稿，这里恢复原文避免用户丢稿
    draftMessage.value = content
    message.error(cause?.response?.data?.detail || '发送失败，请稍后重试。')
  } finally {
    sendingMessage.value = false
  }
}

// 聊天式创建：未选中 Case 时首条消息即意图——创建通用 Case 后原文发到房间，
// 触发既有 Manager 响应链路；@ 引用的文件作为 context_refs 随创建与首条发言落审计，
// 无显式引用时上下文由后端注入发起人工作区只读引用。
async function createCaseFromDraft(content: string, contextRefs: AgentTeamsContextRef[] = []) {
  const created = await agentTeamsApi.createCase({
    intent: buildRoomCreateIntent(content),
    context_refs: contextRefs.length ? contextRefs : undefined,
  })
  draftMessage.value = ''
  message.success('协作 Case 已创建，计划冻结后将自动确认执行。')
  selectedCaseId.value = ''
  await loadCases()
  await selectCase(created.case_id)
  // 创建后立刻显示用户首条消息（乐观更新），避免 SSE 尚未连接或回投延迟时页面空白。
  const optimisticEventId = `local-user-message-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  mergeEvents([{
    event_id: optimisticEventId,
    recorded_at: new Date().toISOString(),
    case_id: created.case_id,
    actor: 'current-user',
    event_type: 'room.user_message',
    payload: {
      summary: content.slice(0, 80),
      payload: { actor: 'current-user', content, context_refs: contextRefs },
      optimistic: true,
    },
  }])
  try {
    const result = await agentTeamsApi.postCaseMessage(created.case_id, content, contextRefs)
    const serverEventId = typeof result.event_id === 'string' ? result.event_id : ''
    if (serverEventId) {
      const serverEventArrived = events.value.some((event) => event.event_id === serverEventId)
      events.value = serverEventArrived
        ? events.value.filter((event) => event.event_id !== optimisticEventId)
        : events.value.map((event) =>
          event.event_id === optimisticEventId
            ? { ...event, event_id: serverEventId, payload: { ...event.payload, optimistic: true } }
            : event,
        )
    }
    // 用户消息落盘后给出本地“正在输入”提示，覆盖后端 typing 事件未到达或延迟的场景。
    localTypingUntil.value = Date.now() + LOCAL_TYPING_TTL_MS
    // 事件流未就绪时立即拉取一次，确保用户消息与 Manager 回复尽快出现。
    if (!eventStreamHealthy.value) await refreshDetail({ resetEvents: true })
  } catch (cause: any) {
    events.value = events.value.filter((event) => event.event_id !== optimisticEventId)
    localTypingUntil.value = 0
    message.error(cause?.response?.data?.detail || '发送失败，请稍后重试。')
  }
  if (roomPreferences.settings.showOnboarding) {
    onboardingCaseId.value = created.case_id
    onboarding.begin()
  }
  void nextTick(() => scrollListToBottom())
}

// ===== Manager onboarding（§9.3）：新房间顶部的一次性初始化，不写入后端事件 =====
const onboarding = useAgentTeamsOnboardingStore()
const roomPreferences = useAgentTeamsPreferencesStore()
/** onboarding 只出现在创建它的房间 */
const onboardingCaseId = ref('')
const showOnboarding = computed(
  () => onboarding.phase === 'asking' && !!onboardingCaseId.value && onboardingCaseId.value === selectedCaseId.value,
)

function answerOnboarding(value: string) {
  const stepKey = onboarding.currentStep?.key
  onboarding.answerCurrent(value)
  if (stepKey) roomPreferences.applyOnboardingAnswer(stepKey, value)
  if (onboarding.phase === 'done') void roomPreferences.save().catch(() => undefined)
  void nextTick(() => scrollListToBottom())
}

function skipOnboardingStep() {
  onboarding.skipCurrent()
}

function syncIfVisible() {
  if (shouldPollAgentTeamsCase(document.visibilityState) && !eventStreamHealthy.value) {
    void refreshDetail({ background: true })
  }
}

function startPolling() {
  stopPolling()
  pollingTimer = setInterval(syncIfVisible, POLLING_INTERVAL_MS)
  document.addEventListener('visibilitychange', syncIfVisible)
}

function stopPolling() {
  if (pollingTimer) clearInterval(pollingTimer)
  pollingTimer = null
  document.removeEventListener('visibilitychange', syncIfVisible)
}

function stopEventStream() {
  eventStreamAbort?.abort()
  eventStreamAbort = null
  if (eventStreamRetryTimer) clearTimeout(eventStreamRetryTimer)
  eventStreamRetryTimer = null
  eventStreamHealthy.value = false
  eventStreamFailures = 0
}

async function startEventStream() {
  if (!selectedCaseId.value) return
  stopEventStream()
  const controller = new AbortController()
  eventStreamAbort = controller
  try {
    const token = localStorage.getItem('access_token')
    const params = new URLSearchParams()
    if (eventCursor.value) params.set('cursor', eventCursor.value)
    const response = await fetch(`/api/v1/agent-teams/cases/${selectedCaseId.value}/events/stream?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`SSE 请求失败（${response.status}）`)
    eventStreamHealthy.value = true
    eventStreamFailures = 0
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const event = JSON.parse(line.slice(5).trim()) as AgentTeamsEvent
          mergeEvents([event])
          eventCursor.value = event.event_id || eventCursor.value
          if (event.event_type === 'case.state_changed') void refreshDetail({ background: true })
        } catch {
          // 忽略畸形事件，轮询兜底
        }
      }
    }
  } catch (cause) {
    if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
      console.warn('团队协作室事件流连接异常，将继续使用轮询同步。', cause)
    }
  } finally {
    if (eventStreamAbort === controller) {
      eventStreamAbort = null
      eventStreamHealthy.value = false
      if (!controller.signal.aborted) {
        const delay = Math.min(SSE_RETRY_MAX_MS, SSE_RETRY_INITIAL_MS * 2 ** Math.min(eventStreamFailures, 5))
        eventStreamFailures += 1
        eventStreamRetryTimer = window.setTimeout(() => {
          eventStreamRetryTimer = null
          void startEventStream()
        }, delay)
      }
    }
  }
}

// 「新房间」：回到未选中空态并聚焦输入框，下一条消息即新 Case 的意图
async function startNewRoom() {
  stopEventStream()
  selectedCaseId.value = ''
  detail.value = null
  events.value = []
  eventCursor.value = null
  localTypingUntil.value = 0
  seenEventIds.value = new Set()
  expandedStepIds.value = new Set()
  roomViewMode.value = 'stream'
  await nextTick()
  composerRef.value?.focus()
}

async function confirmSubmit() {
  if (!detail.value) return
  const taskName = submitTaskName.value.trim()
  if (!taskName) { message.warning('请填写任务名称。'); return }
  if (!approvalConfirmed.value) { message.warning('请先确认本次真实计算的审批范围。'); return }
  submitting.value = true
  try {
    await agentTeamsApi.submitCase(detail.value.case_id, { task_name: taskName })
    submitVisible.value = false
    message.success('已通过 Workflow Operator 提交 OmicHub 任务。')
    // 审批操作后同时刷新详情与列表：审批卡片终态与左栏待审批计数同源派生（§13）
    await Promise.all([refreshDetail({ resetEvents: true }), loadCases()])
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '任务提交失败，未确认前请勿重复操作。')
  } finally {
    submitting.value = false
  }
}

async function confirmReject() {
  if (!detail.value) return
  if (!rejectReason.value.trim()) { message.warning('请填写驳回原因。'); return }
  rejecting.value = true
  try {
    await agentTeamsApi.rejectCase(detail.value.case_id, { reason: rejectReason.value.trim() })
    rejectVisible.value = false
    message.success('已驳回该 Case。')
    await Promise.all([refreshDetail({ resetEvents: true }), loadCases()])
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '驳回失败。')
  } finally {
    rejecting.value = false
  }
}

async function confirmRevise() {
  if (!detail.value?.plan_hash) return
  let parameters: Record<string, unknown>
  try {
    parameters = JSON.parse(reviseForm.value.parameters || '{}')
  } catch {
    message.warning('参数修订必须是有效 JSON。')
    return
  }
  revising.value = true
  try {
    await agentTeamsApi.revisePlan(detail.value.case_id, {
      expected_plan_hash: detail.value.plan_hash,
      parameters,
      reason: reviseForm.value.reason.trim() || '房间内发起计划修订',
    })
    reviseVisible.value = false
    message.success('计划修订已提交。')
    await refreshDetail({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '计划修订失败。')
  } finally {
    revising.value = false
  }
}

async function retryFailedCase() {
  if (!detail.value || retrying.value) return
  retrying.value = true
  try {
    const queued = await agentTeamsApi.retryCase(detail.value.case_id)
    message.success(`重试已排队：${queued.work_item_id}`)
    await refreshDetail({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '重试排队失败。')
  } finally {
    retrying.value = false
  }
}

// 删除协作房间：Bridge 侧先取消未结束的 Case 再移除记录；删除当前房间时同时清理详情与事件流
async function deleteRoomCase(item: AgentTeamsCase) {
  if (deletingCaseId.value) return
  deletingCaseId.value = item.case_id
  try {
    await agentTeamsApi.deleteCase(item.case_id)
    message.success('协作房间已删除。')
    if (selectedCaseId.value === item.case_id) {
      stopEventStream()
      selectedCaseId.value = ''
      detail.value = null
      events.value = []
      eventCursor.value = null
    }
    cases.value = cases.value.filter((entry) => entry.case_id !== item.case_id)
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '删除协作房间失败，请稍后重试。')
  } finally {
    deletingCaseId.value = ''
  }
}

watch(visibleMessages, async () => {
  await nextTick()
  if (listAtBottom.value) listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
})

onMounted(() => {
  roomPreferences.hydrateFromUser()
  // 首屏骨架立即渲染；角色元数据与 Case 列表并行加载、各自填充，互不阻塞
  void agentTeamsApi
    .getRoleLabels()
    .then((metadata) => { roleMetadata.value = metadata })
    .catch(() => { roleMetadata.value = {} })
  void loadCases(true)
  startPolling()
  narrowMedia = window.matchMedia('(max-width: 1024px)')
  syncViewportMode()
  narrowMedia.addEventListener('change', syncViewportMode)
  document.addEventListener('keydown', handleGlobalKeydown)
})
onBeforeUnmount(() => {
  stopPolling()
  stopEventStream()
  narrowMedia?.removeEventListener('change', syncViewportMode)
  document.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <main class="room-page">
    <NAlert v-if="!loading && !available" type="info" title="AgentTeams 尚未接通" :show-icon="true">
      配置 AgentTeams Bridge 后，这里会显示真实的团队协作房间。
    </NAlert>
    <div v-else class="room-layout">
      <div v-if="isNarrowViewport" class="room-topbar">
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton ref="sidebarToggleRef" tertiary size="small" aria-label="展开房间列表" @click="openSidebar">
              <template #icon><NIcon><MenuOutline /></NIcon></template>房间列表
            </NButton>
          </template>
          展开房间列表
        </NTooltip>
      </div>
      <aside
        ref="sidebarRef"
        class="room-sidebar"
        :class="{ 'is-open': sidebarOpen }"
        :inert="isNarrowViewport && !sidebarOpen"
      >
        <div class="room-sidebar__toolbar">
          <span class="room-sidebar__heading">协作室</span>
          <div class="room-sidebar__actions">
            <NTooltip trigger="hover">
              <template #trigger>
                <NButton tertiary circle size="small" aria-label="团队协作室设置" @click="settingsVisible = true">
                  <template #icon><NIcon><SettingsOutline /></NIcon></template>
                </NButton>
              </template>
              团队协作室设置
            </NTooltip>
            <NTooltip trigger="hover">
              <template #trigger>
                <NButton tertiary circle size="small" :loading="loading" aria-label="刷新协作室列表" @click="loadCases()">
                  <template #icon><NIcon><RefreshOutline /></NIcon></template>
                </NButton>
              </template>
              刷新列表
            </NTooltip>
            <NButton type="primary" size="small" @click="startNewRoom">
              <template #icon><NIcon><AddOutline /></NIcon></template>新房间
            </NButton>
            <NTooltip v-if="isNarrowViewport" trigger="hover">
              <template #trigger>
                <NButton tertiary circle size="small" aria-label="收起房间列表" @click="closeSidebar">
                  <template #icon><NIcon><CloseOutline /></NIcon></template>
                </NButton>
              </template>
              收起房间列表
            </NTooltip>
          </div>
        </div>
        <div class="room-sidebar__tools">
          <NInput v-model:value="searchQuery" size="small" clearable placeholder="搜索 Case 目标">
            <template #prefix><NIcon><SearchOutline /></NIcon></template>
          </NInput>
          <div class="omichub-segmented-toggle room-filter-chips" role="group" aria-label="按状态筛选 Case">
            <button
              v-for="chip in filterChips"
              :key="chip.key"
              type="button"
              :class="{ active: statusFilter === chip.key }"
              :aria-pressed="statusFilter === chip.key"
              @click="statusFilter = chip.key"
            ><span class="room-filter-chips__label">{{ chip.label }}</span><span class="room-filter-chips__count">{{ chip.count }}</span></button>
          </div>
        </div>
        <NSpin :show="loading" class="room-sidebar__spin">
          <div class="room-sidebar__list" role="listbox" aria-label="协作房间列表">
            <template v-if="loading && !sortedCases.length">
              <div v-for="index in 4" :key="`skeleton-${index}`" class="case-entry case-entry--skeleton" aria-hidden="true">
                <span class="case-entry__skeleton-line case-entry__skeleton-line--title"></span>
                <span class="case-entry__skeleton-line case-entry__skeleton-line--meta"></span>
              </div>
            </template>
            <NEmpty v-else-if="!filteredCases.length" size="small" class="room-sidebar__empty">
              <template #icon><NIcon :size="36" aria-hidden="true"><FileTrayOutline /></NIcon></template>
              <template #default>
                <p class="room-sidebar__empty-title">{{ sortedCases.length ? '没有匹配的 Case' : '还没有协作房间' }}</p>
                <p v-if="!sortedCases.length" class="room-sidebar__empty-desc">在下方输入需求，回车即可创建第一个协作 Case</p>
              </template>
              <template v-if="!sortedCases.length" #extra>
                <NButton text type="primary" size="small" @click="focusComposer">去下方输入需求</NButton>
              </template>
            </NEmpty>
            <button
              v-for="item in filteredCases"
              :key="item.case_id"
              type="button"
              class="case-entry omichub-selectable-card"
              :class="{ active: item.case_id === selectedCaseId }"
              role="option"
              :aria-selected="item.case_id === selectedCaseId"
              @click="selectCase(item.case_id)"
            >
              <span class="case-entry__avatar" aria-hidden="true">{{ caseAvatarLetter(item) }}</span>
              <span class="case-entry__body">
                <span class="case-entry__intent" :title="item.intent">{{ item.display_title || item.intent }}</span>
                <!-- 缺口：Case 数据模型无最后一条消息预览字段，有数据前不渲染预览行 -->
              </span>
              <span class="case-entry__side">
                <NTooltip trigger="hover">
                  <template #trigger>
                    <span
                      class="case-entry__status-dot"
                      :class="`is-${agentTeamsCaseCategory(item.status)}`"
                      :aria-label="`状态：${ROOM_CATEGORY_LABELS[agentTeamsCaseCategory(item.status)]}`"
                    ></span>
                  </template>
                  {{ ROOM_CATEGORY_LABELS[agentTeamsCaseCategory(item.status)] }} · {{ formatAgentTeamsStatus(item.status) }}
                </NTooltip>
                <span class="case-entry__time">{{ formatRelativeTime(item.updated_at) }}</span>
                <NPopconfirm
                  positive-text="删除"
                  negative-text="取消"
                  :positive-button-props="{ type: 'error', size: 'small', loading: deletingCaseId === item.case_id }"
                  :negative-button-props="{ size: 'small' }"
                  @positive-click="deleteRoomCase(item)"
                >
                  <template #trigger>
                    <span
                      class="case-entry__delete"
                      role="button"
                      :aria-label="`删除房间：${item.display_title || item.intent}`"
                      @click.stop
                    ><NIcon :size="13" aria-hidden="true"><TrashOutline /></NIcon></span>
                  </template>
                  删除该协作房间？未结束的 Case 会先取消，审计记录将一并移除。
                </NPopconfirm>
              </span>
            </button>
          </div>
        </NSpin>
      </aside>
      <div
        v-if="isNarrowViewport && sidebarOpen"
        class="room-sidebar-backdrop"
        aria-hidden="true"
        @click="closeSidebar"
      ></div>

      <section class="room-main" :class="{ 'room-main--empty': !selectedCaseId }">
        <div v-if="!selectedCaseId" class="room-guide">
          <span class="room-guide__logo" aria-hidden="true"><NIcon :size="34"><SparklesOutline /></NIcon></span>
          <h1 class="room-guide__title">和你的 AI 管家聊聊</h1>
          <p class="room-guide__lead">描述你的分析问题，Manager 会分解任务、组建 Worker 团队协作完成，关键步骤由你审批把关；也可以从左侧选择已有房间继续协作。</p>
          <p class="room-guide__note">流程型分析（真实计算）请在 AI 工作台发起，需人工审批。</p>
          <div class="room-guide__actions" role="group" aria-label="快捷操作">
            <button
              v-for="action in roomQuickActions"
              :key="action.key"
              type="button"
              class="room-guide__pill"
              @click="applyRoomQuickAction(action)"
            >{{ action.label }}</button>
          </div>
        </div>
        <template v-else>
          <header class="case-header">
            <div class="case-header__info">
              <h2 class="case-header__title">{{ caseTitle }}</h2>
              <p class="case-header__meta">
                <span v-if="requesterName">发起人 {{ requesterName }}</span>
                <span>创建于 {{ formatDateTime(detail?.created_at) }}</span>
                <span>更新于 {{ formatDateTime(detail?.updated_at) }}</span>
              </p>
            </div>
            <div v-if="stageView" class="case-stage" aria-label="Case 状态进度">
              <template v-for="(stage, index) in stageView" :key="stage.key">
                <span v-if="index > 0" class="case-stage__link" :class="{ 'is-done': stageView[index - 1].state === 'done' }" aria-hidden="true"></span>
                <span class="case-stage__node" :class="`is-${stage.state}`">
                  <span class="case-stage__dot" aria-hidden="true">{{ stage.state === 'done' ? '✓' : stage.state === 'failed' ? '!' : index + 1 }}</span>
                  <span class="case-stage__label">{{ stage.label }}</span>
                </span>
              </template>
              <NTag v-if="detail" :type="tagType(detail.status)" :bordered="false" size="small" round class="case-stage__tag">
                {{ formatAgentTeamsStatus(detail.status) }}
              </NTag>
            </div>
            <div v-if="elementRoomUrl" class="room-view-switch" role="group" aria-label="房间视图切换">
              <button
                type="button"
                class="room-view-switch__btn"
                :class="{ 'is-active': roomViewMode === 'stream' }"
                :aria-pressed="roomViewMode === 'stream'"
                @click="roomViewMode = 'stream'"
              >消息流</button>
              <button
                type="button"
                class="room-view-switch__btn"
                :class="{ 'is-active': roomViewMode === 'element' }"
                :aria-pressed="roomViewMode === 'element'"
                @click="roomViewMode = 'element'"
              >Element 视图</button>
            </div>
          </header>

          <div v-if="roomViewMode === 'element' && elementRoomUrl" class="room-element">
            <div class="room-element__toolbar">
              <span class="room-element__hint">Element 直接连接 Matrix 房间，需使用 Matrix 账号登录后方可发言。</span>
              <NButton size="small" tertiary tag="a" :href="elementRoomUrl" target="_blank" rel="noopener noreferrer">
                在新标签页打开
              </NButton>
            </div>
            <iframe
              class="room-element__frame"
              :src="elementRoomUrl"
              title="Element Matrix 房间"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"
              referrerpolicy="no-referrer"
            ></iframe>
          </div>

          <template v-if="roomViewMode === 'stream' || !elementRoomUrl">
          <div class="room-messages-wrap">
          <div ref="listRef" class="room-messages" @scroll.passive="handleListScroll">
            <div class="room-stream">
              <NEmpty v-if="!showOnboarding && !roomBlocks.length && !collapsedMessages.length" size="small" description="暂未产生协作事件" />

              <!-- 新 Case 的一次性初始化：固定在消息区顶部，完成或跳过后立即退出消息流。 -->
              <div v-if="showOnboarding" class="speech onboarding" aria-live="polite">
                <span class="room-avatar onboarding__avatar" aria-hidden="true">{{ roomPreferences.managerLabel.charAt(0) }}</span>
                <div class="speech__main">
                  <div class="speech__head">
                    <span class="speech__name onboarding__name">{{ roomPreferences.managerLabel }}</span>
                    <span class="speech__role"> · 管家</span>
                  </div>
                  <div class="speech__bubble">{{ onboarding.currentStep?.question(roomPreferences.managerLabel) }}</div>
                  <div class="onboarding__chips" role="group" aria-label="快捷回复">
                    <button
                      v-for="option in onboarding.currentStep?.options || []"
                      :key="option.value"
                      type="button"
                      class="room-guide__pill"
                      @click="answerOnboarding(option.value)"
                    >{{ option.label }}</button>
                    <button type="button" class="onboarding__skip" @click="skipOnboardingStep">跳过此步</button>
                    <button type="button" class="onboarding__skip" @click="onboarding.dismiss()">稍后再说</button>
                  </div>
                </div>
              </div>

              <template v-for="block in roomBlocks" :key="block.type === 'worker' ? block.key : block.message.id">
                <div v-if="block.type === 'timeline'" class="tl-node">
                  <span class="tl-node__rail" aria-hidden="true"><span class="tl-node__dot"></span></span>
                  <div class="tl-node__body">
                    <span class="tl-node__text">{{ block.message.content }}</span>
                    <time class="tl-node__time">{{ formatMessageTime(block.message.id) }}</time>
                  </div>
                </div>

                <div v-else-if="block.type === 'speech'" class="speech" :class="{ 'speech--user': block.message.isUser }">
                  <span class="room-avatar" :style="{ background: block.message.sender.color }">{{ block.message.sender.avatar }}</span>
                  <div class="speech__main">
                    <div class="speech__head">
                      <span class="speech__name" :style="{ color: block.message.sender.color }">{{ block.message.sender.name }}</span>
                      <span v-if="block.message.sender.role === 'manager' && !block.message.isUser" class="speech__role"> · 管家</span>
                      <time class="speech__time">{{ formatMessageTime(block.message.id) }}</time>
                    </div>
                    <div v-if="block.message.managerReport" class="speech__bubble manager-report">
                      <div v-if="block.message.managerReport.hardGate" class="manager-report__hardgate">
                        ⚠ {{ formatHardGate(block.message.managerReport.hardGate) }}
                      </div>
                      <div v-if="block.message.managerReport.conclusion" class="manager-report__conclusion">
                        <MarkdownRenderer :content="block.message.managerReport.conclusion" />
                      </div>
                      <div v-if="block.message.managerReport.recommendations.length" class="manager-report__section">
                        <span class="manager-report__label">建议</span>
                        <ul class="manager-report__list">
                          <li v-for="(item, index) in block.message.managerReport.recommendations" :key="`rec-${index}`">{{ item }}</li>
                        </ul>
                      </div>
                      <div v-if="block.message.managerReport.risks.length" class="manager-report__section">
                        <span class="manager-report__label manager-report__label--risk">风险</span>
                        <ul class="manager-report__list">
                          <li v-for="(item, index) in block.message.managerReport.risks" :key="`risk-${index}`">{{ item }}</li>
                        </ul>
                      </div>
                      <div v-if="block.message.managerReport.evidenceRefs.length" class="manager-report__section">
                        <span class="manager-report__label manager-report__label--evidence">证据</span>
                        <ul class="manager-report__list manager-report__list--evidence">
                          <li v-for="(item, index) in block.message.managerReport.evidenceRefs" :key="`ev-${index}`">{{ item }}</li>
                        </ul>
                      </div>
                      <details v-if="block.message.managerReport.proposedSubmission" class="manager-report__submission">
                        <summary class="manager-report__label manager-report__label--submission">执行工单</summary>
                        <pre class="manager-report__json">{{ JSON.stringify(block.message.managerReport.proposedSubmission, null, 2) }}</pre>
                      </details>
                    </div>
                    <div v-else class="speech__bubble">
                      <MarkdownRenderer v-if="!block.message.isUser" :content="block.message.content" />
                      <span v-else class="speech__mentions" v-html="formatMentions(block.message.content)" />
                    </div>
                    <div v-if="!block.message.isUser && isContentTruncated(block.message.content)" class="speech__continue">
                      <NButton text size="tiny" @click="handleContinueGeneration">继续生成</NButton>
                    </div>
                    <MessageArtifactGallery :artifacts="block.message.artifacts" />
                  </div>
                </div>

                <div v-else-if="block.type === 'action'" class="room-action">
                  <span class="room-action__sender">{{ block.message.sender.avatar }} {{ block.message.sender.name }}</span>
                  <span class="room-action__text">{{ block.message.content }}</span>
                  <details v-if="block.message.technicalDetail" class="room-action__detail">
                    <summary>技术详情</summary>
                    <code class="room-action__detail-code">{{ block.message.technicalDetail }}</code>
                  </details>
                  <div v-if="block.message.actions?.length" class="room-action__actions">
                    <NButton
                      v-for="item in block.message.actions"
                      :key="item.action"
                      size="small"
                      :type="item.action === 'cancel' ? 'error' : item.action === 'retry' ? 'primary' : 'default'"
                      @click="handleRoomAction(item.action)"
                    >{{ item.label }}</NButton>
                  </div>
                </div>

                <section
                  v-else
                  class="worker-card"
                  :class="{ 'is-active': block.active, 'is-failed': block.failed, 'is-interrupted': block.interrupted }"
                  :style="{ borderLeftColor: block.sender.color }"
                >
                  <header class="worker-card__head">
                    <span class="room-avatar room-avatar--sm" :style="{ background: block.sender.color }">{{ block.sender.avatar }}</span>
                    <span class="worker-card__heading">
                      <span class="worker-card__name" :style="{ color: block.sender.color }">{{ block.sender.name }}</span>
                      <span v-if="block.intro" class="worker-card__objective" :title="block.intro.content">{{ block.intro.content }}</span>
                    </span>
                    <span class="worker-card__state">{{ block.interrupted ? '已中断/重新排队' : block.failed ? '执行失败' : block.active ? '进行中' : '已完成' }}</span>
                    <time class="worker-card__time">{{ formatMessageTime(block.body?.id || block.intro?.id || block.key) }}</time>
                  </header>
                  <div v-if="block.steps.length && block.active" class="worker-card__progress worker-card__progress--indeterminate" aria-hidden="true">
                    <div class="worker-card__progress-bar"></div>
                  </div>
                  <NProgress
                    v-else-if="block.steps.length"
                    type="line"
                    :percentage="workerStepProgress(block)"
                    :show-indicator="false"
                    :height="4"
                    rail-color="var(--neutral-border)"
                    :color="block.failed ? 'var(--arco-danger)' : 'var(--arco-primary)'"
                    aria-hidden="true"
                  />
                  <ul v-if="block.steps.length || block.extraProgress.length" class="worker-card__steps">
                    <li v-for="step in block.steps" :key="step.id" class="worker-step" :class="`is-${step.tool.status}`">
                      <span class="worker-step__dot" aria-hidden="true"></span>
                      <button
                        v-if="step.count > 1"
                        type="button"
                        class="worker-step__expand"
                        :aria-label="isStepExpanded(step.id) ? '收起明细' : '展开明细'"
                        @click="toggleStepDetail(step.id)"
                      >
                        <NIcon v-if="isStepExpanded(step.id)" :size="12"><CaretUpOutline /></NIcon>
                        <NIcon v-else :size="12"><CaretDownOutline /></NIcon>
                      </button>
                      <span class="worker-step__name">{{ step.count > 1 ? `${step.tool.name} ×${step.count}` : step.tool.name }}</span>
                      <NTag
                        size="tiny"
                        :bordered="false"
                        round
                        :type="step.tool.status === 'running' ? 'primary' : step.tool.status === 'failed' ? 'error' : 'success'"
                      >{{ step.tool.status === 'running' ? '正在调用' : step.tool.status === 'failed' ? '调用失败' : '调用完成' }}</NTag>
                      <span v-if="step.tool.durationMs !== undefined" class="worker-step__duration">{{ formatDuration(step.tool.durationMs) }}</span>
                      <ul v-if="step.count > 1 && isStepExpanded(step.id)" class="worker-step__details">
                        <li v-for="detail in step.details" :key="detail.id" class="worker-step__detail">
                          <span class="worker-step__detail-name">{{ detail.tool.name }}</span>
                          <NTag
                            size="tiny"
                            :bordered="false"
                            round
                            :type="detail.tool.status === 'running' ? 'primary' : detail.tool.status === 'failed' ? 'error' : 'success'"
                          >{{ detail.tool.status === 'running' ? '正在调用' : detail.tool.status === 'failed' ? '调用失败' : '调用完成' }}</NTag>
                          <span v-if="detail.tool.durationMs !== undefined" class="worker-step__duration">{{ formatDuration(detail.tool.durationMs) }}</span>
                        </li>
                      </ul>
                    </li>
                    <li v-for="item in block.extraProgress" :key="item.id" class="worker-step is-plain">{{ item.content }}</li>
                  </ul>
                  <div v-if="block.body" class="worker-card__body"><MarkdownRenderer :content="block.body.content" /></div>
                  <MessageArtifactGallery v-if="block.body" :artifacts="block.body.artifacts" />
                </section>
              </template>

              <section v-if="approvalCard" class="room-approval-card" :class="`is-${approvalCard.state}`" aria-live="polite">
                <header class="room-approval-card__head">
                  <span class="room-approval-card__title">人工审批</span>
                  <span v-if="approvalCard.terminalText" class="room-approval-card__terminal">{{ approvalCard.terminalText }}</span>
                  <time v-if="approvalCard.time" class="room-approval-card__time">{{ approvalCard.time }}</time>
                </header>
                <p v-if="approvalCard.summary" class="room-approval-card__summary">{{ approvalCard.summary }}</p>
                <p v-if="approvalCard.impact" class="room-approval-card__impact">{{ approvalCard.impact }}</p>
                <div v-if="approvalCard.state === 'pending'" class="room-approval-card__actions">
                  <NButton
                    type="primary"
                    size="small"
                    @click="submitTaskName = (detail?.intent || '').slice(0, 128); approvalConfirmed = false; submitVisible = true"
                  >通过并提交计算</NButton>
                  <NButton secondary size="small" @click="reviseVisible = true">修改计划</NButton>
                  <NPopconfirm @positive-click="rejectReason = ''; rejectVisible = true">
                    <template #trigger>
                      <NButton tertiary type="error" size="small">驳回</NButton>
                    </template>
                    确认驳回该 Case？驳回后还需填写驳回原因。
                  </NPopconfirm>
                </div>
                <div v-else-if="approvalCard.state === 'retry'" class="room-approval-card__actions">
                  <NButton type="primary" size="small" :loading="retrying" @click="retryFailedCase">按冻结计划重试</NButton>
                </div>
              </section>

              <details v-if="collapsedMessages.length" class="room-collapsed" :open="roomPreferences.settings.expandTechnicalEvents">
                <summary>底层任务事件（{{ collapsedMessages.length }} 条，默认收起）</summary>
                <div v-for="item in collapsedMessages" :key="item.id" class="room-collapsed__line">
                  <span>{{ item.content }}</span>
                  <time class="tl-node__time">{{ formatMessageTime(item.id) }}</time>
                </div>
              </details>

              <div v-if="managerTyping" class="room-typing" role="status" aria-live="polite">
                <span class="room-typing__dots" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="room-typing__label">{{ roomPreferences.managerLabel }} 正在输入…</span>
              </div>

            </div>
          </div>
          <NButton v-if="!listAtBottom" class="room-scroll-bottom" size="small" secondary round @click="scrollListToBottom">回到底部</NButton>
          </div>
          </template>
        </template>

        <KimiChatInput
          v-if="!selectedCaseId || roomViewMode === 'stream' || !elementRoomUrl"
          ref="composerRef"
          v-model="draftMessage"
          room-mode
          class="room-composer"
          :placeholder="roomInputPlaceholder"
          :disabled="!roomInputEnabled || sendingMessage"
          :send-loading="sendingMessage"

          :maxlength="4000"
          @send="handleComposerSend"
        />
      </section>
    </div>

    <NModal v-model:show="submitVisible" preset="card" title="人工确认并提交计算任务" :style="{ width: 'min(92vw, 560px)' }" :mask-closable="!submitting">
      <NForm label-placement="top" @submit.prevent="confirmSubmit">
        <NFormItem label="任务名称" required><NInput v-model:value="submitTaskName" /></NFormItem>
        <NCheckbox v-model:checked="approvalConfirmed">
          我确认提交本次真实计算；浏览器不会修改已预检通过的输入，执行与结果将记录在当前 Case。
        </NCheckbox>
        <div class="room-modal-actions">
          <NButton :disabled="submitting" @click="submitVisible = false">取消</NButton>
          <NButton type="primary" attr-type="submit" :disabled="!approvalConfirmed" :loading="submitting">确认并提交</NButton>
        </div>
      </NForm>
    </NModal>

    <NModal v-model:show="rejectVisible" preset="card" title="驳回协作 Case" :style="{ width: 'min(92vw, 480px)' }" :mask-closable="!rejecting">
      <NForm label-placement="top" @submit.prevent="confirmReject">
        <NFormItem label="驳回原因" required><NInput v-model:value="rejectReason" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" /></NFormItem>
        <div class="room-modal-actions">
          <NButton :disabled="rejecting" @click="rejectVisible = false">取消</NButton>
          <NButton type="error" attr-type="submit" :loading="rejecting">确认驳回</NButton>
        </div>
      </NForm>
    </NModal>

    <NModal v-model:show="reviseVisible" preset="card" title="修订执行计划" :style="{ width: 'min(92vw, 560px)' }" :mask-closable="!revising">
      <NForm label-placement="top" @submit.prevent="confirmRevise">
        <NFormItem label="修订原因"><NInput v-model:value="reviseForm.reason" type="textarea" :autosize="{ minRows: 2, maxRows: 3 }" /></NFormItem>
        <NFormItem label="参数修订 JSON"><NInput v-model:value="reviseForm.parameters" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" /></NFormItem>
        <div class="room-modal-actions">
          <NButton :disabled="revising" @click="reviseVisible = false">取消</NButton>
          <NButton type="primary" attr-type="submit" :loading="revising">提交修订</NButton>
        </div>
      </NForm>
    </NModal>
    <AgentTeamsSettingsDrawer v-model:show="settingsVisible" />
  </main>
</template>

<style scoped>
/* ===== 页面骨架：Surface Base 页面底 + 左右两张 Surface Card（§3.3 / §4.2） ===== */
.room-page { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: var(--space-md); padding: var(--page-padding, 32px); background: var(--neutral-bg); /* §3.3.5：非 .kimi-layout 作用域，必须为 KimiChatInput 补齐输入区语义变量 */ --chat-input-bg: var(--neutral-card); --chat-input-border: var(--neutral-border); }
.room-topbar { display: flex; align-items: center; }
.room-layout { display: grid; grid-template-columns: minmax(280px, 320px) minmax(0, 1fr); gap: var(--space-xl); flex: 1; min-height: 0; }

/* ===== 左栏：协作室切换器（工具行 + 搜索 + 过滤 chips + Case 列表，Surface Card 材质） ===== */
.room-sidebar { display: flex; min-height: 0; flex-direction: column; gap: var(--space-lg); overflow: hidden; padding: var(--space-2xl); border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); }
.room-sidebar__toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-sm); }
.room-sidebar__heading { color: var(--neutral-text-1); font-size: var(--font-section-size); font-weight: var(--font-section-weight); line-height: var(--font-section-height); letter-spacing: var(--font-section-spacing); }
.room-sidebar__actions { display: flex; align-items: center; gap: var(--space-xs); }
.room-sidebar__tools { display: grid; gap: var(--space-sm); }
/* 复用全局 .omichub-segmented-toggle 胶囊分段切换器；本处仅做容器级布局覆盖：禁止折行，溢出时容器自身横向滚动 */
.room-filter-chips { display: flex; max-width: 100%; flex-wrap: nowrap; align-self: stretch; overflow: hidden auto; scrollbar-width: none; }
.room-filter-chips::-webkit-scrollbar { display: none; }
.room-filter-chips button { display: inline-flex; align-items: center; gap: var(--space-xs); white-space: nowrap; }
.room-filter-chips__count { color: var(--neutral-text-3); }
.room-filter-chips button:hover .room-filter-chips__count { color: var(--neutral-text-1); }
.room-filter-chips button.active .room-filter-chips__count { color: var(--text-on-primary); }
/* 左栏空状态：中性收件箱图标 + 两级文案 + 下一步引导 */
.room-sidebar__empty { padding: var(--space-xl) 0; }
.room-sidebar__empty-title { margin: 0; color: var(--neutral-text-2); font-size: var(--font-small-size); line-height: var(--font-small-height); }
.room-sidebar__empty-desc { margin: var(--space-xs) 0 0; color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
.room-sidebar__spin { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.room-sidebar__spin :deep(.n-spin-content) { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.room-sidebar__list { flex: 1; min-height: 0; display: grid; gap: var(--space-sm); align-content: start; overflow-y: auto; padding-right: 2px; }
/* 6px 低对比度滚动条（§3.3.2） */
.room-sidebar__list::-webkit-scrollbar, .room-messages::-webkit-scrollbar { width: 6px; }
.room-sidebar__list::-webkit-scrollbar-thumb, .room-messages::-webkit-scrollbar-thumb { border-radius: 999px; background: var(--scrollbar-thumb); }
.room-sidebar__list::-webkit-scrollbar-thumb:hover, .room-messages::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-thumb-hover); }

/* Case 列表项：可选择卡片协议（§5.2）——左缘 4px 状态线由全局 .omichub-selectable-card::before 提供，
   hover 低强调预览 / 选中连续主色内描边在此以本地规则落齐，避免注入顺序导致被基础背景覆盖 */
.case-entry { display: flex; align-items: center; gap: var(--space-md); padding: var(--space-md) var(--space-md) var(--space-md) var(--space-xl); border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); text-align: left; cursor: pointer; transition: border-color var(--motion-quick) ease-out, box-shadow var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out; }
.case-entry:not(.active):hover { border-color: color-mix(in srgb, var(--arco-primary) 14%, var(--neutral-border)); background-color: color-mix(in srgb, var(--arco-primary) 4%, var(--neutral-card)); }
.case-entry:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: 3px; }
.case-entry.active { border-color: color-mix(in srgb, var(--arco-primary) 20%, var(--neutral-border)); background-color: color-mix(in srgb, var(--arco-primary) 7%, var(--neutral-card)); box-shadow: inset 0 0 0 1px var(--arco-primary); }
:root[data-theme='dark'] .case-entry:not(.active):hover { border-color: var(--border-default); background-color: var(--surface-highlight); }
:root[data-theme='dark'] .case-entry.active { border-color: var(--border-focus); background-color: var(--surface-highlight); }
/* 房间徽标：意图首字符圆角方块，品牌浅底；选中态反转为实心主色 */
.case-entry__avatar { display: inline-flex; flex: 0 0 40px; width: 40px; height: 40px; align-items: center; justify-content: center; border-radius: var(--radius-card); background: var(--arco-primary-light); color: var(--arco-primary); font-size: var(--font-card-title-size); font-weight: 600; transition: background-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out; }
.case-entry.active .case-entry__avatar { background: var(--arco-primary); color: var(--text-on-primary); }
.case-entry__body { display: grid; flex: 1; min-width: 0; gap: var(--space-xs); }
.case-entry__intent { overflow: hidden; color: var(--neutral-text-1); font-size: var(--font-body-size); font-weight: 500; line-height: var(--font-body-height); text-overflow: ellipsis; white-space: nowrap; }
.case-entry__side { display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: var(--space-xs); }
.case-entry__time { overflow: hidden; color: var(--neutral-text-3); font-size: var(--font-caption-size); text-overflow: ellipsis; white-space: nowrap; }
.case-entry__status-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; }
.case-entry__status-dot.is-active { background: var(--arco-primary); animation: room-status-pulse 2.4s ease-in-out infinite; }
.case-entry__status-dot.is-approval { background: var(--arco-warning); }
.case-entry__status-dot.is-done { background: var(--arco-success); }
.case-entry__status-dot.is-failed { background: var(--arco-danger); }
/* 删除入口：悬停/聚焦列表项时显现，避免常态视觉噪音 */
.case-entry__delete { display: none; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 6px; color: var(--neutral-text-3); cursor: pointer; transition: color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out; }
.case-entry:hover .case-entry__delete, .case-entry:focus-within .case-entry__delete { display: inline-flex; }
.case-entry__delete:hover { background: var(--neutral-hover); color: var(--arco-danger); }
@keyframes room-status-pulse { 0% { box-shadow: 0 0 0 0 var(--arco-primary-light); } 70% { box-shadow: 0 0 0 4px var(--arco-primary-light); } 100% { box-shadow: 0 0 0 0 var(--arco-primary-light); } }
/* 列表首载骨架屏：布局先行，数据到达后原位填充 */
.case-entry--skeleton { flex-direction: column; align-items: stretch; cursor: default; }
.case-entry--skeleton:hover { border-color: var(--neutral-border); background: var(--neutral-card); }
.case-entry__skeleton-line { display: block; height: 12px; border-radius: 6px; background: var(--neutral-hover); animation: room-pulse 1.6s ease-in-out infinite; }
.case-entry__skeleton-line--title { width: 72%; }
.case-entry__skeleton-line--meta { width: 44%; height: 10px; }

/* ===== 右栏主体：与左栏同规格 Surface Card，内部滚动 ===== */
.room-main { display: flex; min-height: 0; flex-direction: column; overflow: hidden; border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); }
/* 空状态：不撑整屏大卡片，引导内容列直接落在页面背景 --neutral-bg 上 */
.room-main--empty { border-color: transparent; background: transparent; box-shadow: none; }
.room-guide { display: flex; flex: 1; min-height: 0; flex-direction: column; align-items: center; justify-content: center; width: min(100%, 720px); margin-inline: auto; padding: var(--space-2xl); text-align: center; }
/* 空状态品牌徽标：72px 品牌浅底圆角方块承载 34px 图标（§35.4 克制欢迎区） */
.room-guide__logo { display: inline-flex; width: 72px; height: 72px; align-items: center; justify-content: center; border-radius: var(--radius-lg); background: var(--arco-primary-light); color: var(--arco-primary); }
.room-guide__title { margin: var(--space-lg) 0 0; color: var(--neutral-text-1); font-size: var(--font-display-size); font-weight: var(--font-display-weight); line-height: var(--font-display-height); letter-spacing: var(--font-display-spacing); }
.room-guide__lead { margin: var(--space-md) 0 0; max-width: 560px; color: var(--neutral-text-2); font-size: var(--font-body-size); line-height: var(--font-body-height); }
.room-guide__note { margin: var(--space-sm) 0 0; max-width: 560px; color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
.room-guide__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-sm); margin-top: var(--space-2xl); }
.room-guide__pill { padding: var(--space-sm) var(--space-lg); border: 1px solid var(--neutral-border); border-radius: 999px; background: var(--neutral-card); color: var(--neutral-text-2); font-size: var(--font-small-size); line-height: var(--font-small-height); cursor: pointer; transition: background-color var(--motion-quick) ease-out, border-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out; }
.room-guide__pill:hover { border-color: var(--arco-primary); background: var(--arco-primary-light); color: var(--arco-primary); }
.room-guide__pill:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: 3px; }

/* ===== 顶部 Case 状态条：标题（卡片标题层级）+ 胶囊步骤条 ===== */
.case-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md) var(--space-xl); flex-wrap: wrap; padding: var(--space-lg) var(--space-2xl); border-bottom: 1px solid var(--neutral-border); }
.case-header__info { min-width: 0; }
.case-header__title { margin: 0; overflow: hidden; color: var(--neutral-text-1); font-size: var(--font-card-title-size); font-weight: 600; line-height: var(--font-card-title-height); text-overflow: ellipsis; white-space: nowrap; }
.case-header__meta { display: flex; flex-wrap: wrap; gap: var(--space-xs) var(--space-lg); margin: var(--space-xs) 0 0; color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
/* 步骤条：胶囊容器承载 计划→审批→执行→质控→交付，当前/已完成/失败/未到达四态语义色 */
.case-stage { display: flex; align-items: center; gap: var(--space-xs); padding: var(--space-xs) var(--space-md); border: 1px solid var(--neutral-border); border-radius: 999px; background: var(--neutral-fill-2); }
.case-stage__node { display: inline-flex; align-items: center; gap: var(--space-xs); }
.case-stage__dot { display: inline-flex; width: 20px; height: 20px; align-items: center; justify-content: center; border: 1px solid var(--neutral-border); border-radius: 50%; background: var(--neutral-card); color: var(--neutral-text-3); font-size: 11px; font-weight: 600; }
.case-stage__label { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.case-stage__node.is-done .case-stage__dot { border-color: transparent; background: var(--arco-success); color: var(--text-on-primary); }
.case-stage__node.is-done .case-stage__label { color: var(--neutral-text-2); }
.case-stage__node.is-current .case-stage__dot { border-color: transparent; background: var(--arco-primary); box-shadow: 0 0 0 3px var(--arco-primary-light); color: var(--text-on-primary); }
.case-stage__node.is-current .case-stage__label { color: var(--neutral-text-1); font-weight: 600; }
.case-stage__node.is-failed .case-stage__dot { border-color: transparent; background: var(--arco-danger); color: var(--text-on-primary); }
.case-stage__node.is-failed .case-stage__label { color: var(--arco-danger); font-weight: 600; }
.case-stage__link { width: var(--space-lg); height: 2px; border-radius: 999px; background: var(--neutral-border); }
.case-stage__link.is-done { background: var(--arco-success); }
.case-stage__tag { margin-left: var(--space-xs); }

/* ===== 人工审批卡片：内嵌消息流末尾，Surface Card + 左缘 3px 状态线区分待审批/重试/终态（§9.2） ===== */
.room-approval-card { width: 100%; max-width: 1120px; box-sizing: border-box; padding: var(--space-lg) var(--space-xl); border: 1px solid var(--neutral-border); border-left: 3px solid var(--arco-warning); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); }
.room-approval-card.is-retry, .room-approval-card.is-rejected { border-left-color: var(--arco-danger); }
.room-approval-card.is-approved { border-left-color: var(--arco-success); }
.room-approval-card.is-returned { border-left-color: var(--arco-warning); }
.room-approval-card__head { display: flex; align-items: baseline; gap: var(--space-sm); }
.room-approval-card__title { color: var(--neutral-text-1); font-size: var(--font-body-size); font-weight: 600; }
/* 终态文案：文本 + 状态色双表达（§5.5） */
.room-approval-card.is-approved .room-approval-card__terminal { color: var(--arco-success); }
.room-approval-card.is-rejected .room-approval-card__terminal { color: var(--arco-danger); }
.room-approval-card.is-returned .room-approval-card__terminal { color: var(--arco-warning); }
.room-approval-card__terminal { font-size: var(--font-caption-size); font-weight: 500; }
.room-approval-card__time { margin-left: auto; color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-approval-card__summary { margin: var(--space-xs) 0 0; color: var(--neutral-text-2); font-size: var(--font-small-size); line-height: var(--font-small-height); }
.room-approval-card__impact { margin: var(--space-xs) 0 0; color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
.room-approval-card__actions { display: flex; gap: var(--space-sm); margin-top: var(--space-md); }

/* ===== 消息流：贴左对齐、放宽上限；scrollbar-gutter 预留滚动条位置消除水平抖动（迁移自 KimiMessageList） ===== */
.room-messages-wrap { position: relative; display: flex; flex: 1; min-height: 240px; flex-direction: column; }
.room-messages { flex: 1; min-height: 0; overflow-y: auto; padding: var(--space-xl) var(--space-2xl) var(--space-2xl); scrollbar-gutter: stable; }
.room-scroll-bottom { position: absolute; right: var(--space-lg); bottom: var(--space-lg); z-index: 5; border: 1px solid var(--neutral-border); box-shadow: var(--shadow-card); }
.room-stream { display: grid; width: min(100%, 1200px); gap: var(--space-xl); align-content: start; }

/* system 时间轴节点：细轨 + 空心节点圆点，12px 正文 / 11px 时间 */
.tl-node { display: flex; gap: var(--space-md); }
.tl-node__rail { position: relative; width: 11px; flex: 0 0 11px; }
.tl-node__rail::before { position: absolute; top: 0; bottom: calc(-1 * var(--space-xl)); left: 50%; width: 1px; background: var(--neutral-border); content: ''; transform: translateX(-50%); }
.tl-node:last-child .tl-node__rail::before { display: none; }
.tl-node__dot { position: absolute; top: 5px; left: 50%; width: 9px; height: 9px; border: 2px solid var(--neutral-border); border-radius: 50%; background: var(--neutral-card); box-shadow: 0 0 0 3px var(--neutral-card); transform: translateX(-50%); }
.tl-node__body { display: flex; min-width: 0; align-items: baseline; gap: var(--space-md); padding-bottom: 2px; }
.tl-node__text { color: var(--neutral-text-2); font-size: var(--font-caption-size); line-height: 1.6; }
.tl-node__time { flex: 0 0 auto; color: var(--neutral-text-3); font-size: 11px; }

/* 成员发言气泡（manager / 孤立 worker 发言）：布局迁移自 KimiMessageItem——
   头像 + 13px/600 角色名 + 12px 时间戳头部行，气泡正文 14px/1.7；
   AI 气泡用 Elevated 表面 + 细边框（深色下 --neutral-fill-2 即 Surface Elevated），
   用户气泡右对齐实心主色，气泡最大宽度 720px（§18.1） */
.speech { display: flex; gap: var(--space-md); }
.speech--user { flex-direction: row-reverse; }
.room-avatar { display: inline-flex; width: 32px; height: 32px; flex: 0 0 32px; align-items: center; justify-content: center; border-radius: 50%; color: var(--text-on-primary); font-size: 15px; }
.room-avatar--sm { width: 26px; height: 26px; flex-basis: 26px; font-size: 13px; }
.speech__main { display: grid; min-width: 0; max-width: min(720px, 82%); gap: var(--space-xs); }
.speech__head { display: flex; align-items: baseline; gap: var(--space-sm); }
.speech--user .speech__head { flex-direction: row-reverse; }
.speech__name { font-size: var(--font-small-size); font-weight: 600; }
.speech__role { color: var(--neutral-text-3); font-size: var(--font-caption-size); font-weight: 400; }
.speech__time { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.speech__bubble { padding: var(--space-md) var(--space-lg); border: 1px solid var(--neutral-border); border-radius: 4px var(--radius-card) var(--radius-card) var(--radius-card); background: var(--neutral-fill-2); color: var(--neutral-text-1); font-size: var(--font-body-size); line-height: 1.7; word-break: break-all; overflow-wrap: anywhere; white-space: pre-wrap; }
.speech--user .speech__bubble { max-width: 75%; border-color: transparent; border-radius: var(--radius-card) 4px var(--radius-card) var(--radius-card); background: var(--arco-primary); color: var(--text-on-primary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.speech__bubble .mention-chip { display: inline-block; padding: 0 4px; border-radius: 4px; background: var(--arco-primary-light); color: var(--arco-primary); font-weight: 600; }
.speech--user .speech__bubble .mention-chip { background: rgba(255,255,255,0.2); color: #fff; }
.speech__continue { display: flex; justify-content: flex-end; margin-top: var(--space-xs); }
/* AI 输出经 MarkdownRenderer 渲染：white-space 重置为 normal，避免容器 pre-wrap 继承后
   把 markdown-it 输出的标签换行显示成多余空行 */
.speech__bubble :deep(.md-body),
.worker-card__body :deep(.md-body),
.manager-report__conclusion :deep(.md-body) { font-size: var(--font-body-size); white-space: normal; }
.speech__bubble :deep(.md-body > :first-child),
.worker-card__body :deep(.md-body > :first-child),
.manager-report__conclusion :deep(.md-body > :first-child) { margin-top: 0; }
.speech__bubble :deep(.md-body > :last-child),
.worker-card__body :deep(.md-body > :last-child),
.manager-report__conclusion :deep(.md-body > :last-child) { margin-bottom: 0; }

/* Manager onboarding（§9.3）：品牌色头像 + 快捷回复胶囊，复用空状态胶囊规范 */
.onboarding__avatar { background: var(--arco-primary); }
.onboarding__name { color: var(--arco-primary); }
.onboarding__chips { display: flex; flex-wrap: wrap; gap: var(--space-sm); margin-top: var(--space-xs); }
.onboarding__skip { padding: var(--space-sm) var(--space-xs); border: none; background: transparent; color: var(--neutral-text-3); font-size: var(--font-small-size); line-height: var(--font-small-height); cursor: pointer; transition: color var(--motion-quick) ease-out; }
.onboarding__skip:hover { color: var(--neutral-text-1); }
.onboarding__skip:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: 3px; border-radius: 4px; }

/* Manager 结构化报告（解析自 JSON 信封，风格沿用普通气泡） */
.manager-report { white-space: normal; display: grid; gap: var(--space-sm); }
.manager-report__hardgate { padding: var(--space-sm) var(--space-md); border-left: 3px solid var(--arco-warning); border-radius: var(--radius-sm); background: var(--arco-warning-light); color: var(--arco-warning); font-weight: 600; font-size: var(--font-caption-size); }
.manager-report__conclusion { margin: 0; white-space: pre-wrap; }
.manager-report__section { display: grid; gap: var(--space-xs); }
.manager-report__label { display: inline-flex; align-items: center; align-self: start; padding: 1px 8px; border-radius: 9999px; background: var(--arco-primary-light); color: var(--arco-primary); font-size: 11px; font-weight: 600; }
.manager-report__label--risk { background: var(--arco-danger-light); color: var(--arco-danger); }
.manager-report__label--evidence { background: var(--neutral-border); color: var(--neutral-text-3); }
.manager-report__list { margin: 0; padding-left: var(--space-xl); display: grid; gap: 3px; }
.manager-report__list--evidence { color: var(--neutral-text-3); font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace; font-size: var(--font-caption-size); }
.manager-report__submission { margin: 0; }
.manager-report__label--submission { cursor: pointer; background: var(--arco-success-light); color: var(--arco-success); }
.manager-report__json { margin: var(--space-xs) 0 0; padding: var(--space-sm) var(--space-md); border-radius: var(--radius-sm); background: var(--neutral-fill-2); color: var(--neutral-text-2); font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace; font-size: var(--font-caption-size); white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; }

/* worker 工具进度卡片：与发言气泡共享 Elevated 表面与圆角语言，
   仅保留 3px 左侧成员色条作身份标识（动态成员色经 inline style 覆盖 border-left-color） */
.worker-card { display: grid; gap: var(--space-sm); width: 100%; max-width: 1120px; box-sizing: border-box; padding: var(--space-md) var(--space-lg); border: 1px solid var(--neutral-border); border-left: 3px solid var(--neutral-border); border-radius: 4px var(--radius-card) var(--radius-card) var(--radius-card); background: var(--neutral-fill-2); }
.worker-card__head { display: flex; align-items: center; gap: var(--space-sm); }
.worker-card__heading { display: flex; flex: 1; min-width: 0; align-items: baseline; gap: var(--space-sm); }
.worker-card__name { font-size: var(--font-small-size); font-weight: 600; }
.worker-card__state { padding: 2px 8px; border-radius: 9999px; color: var(--arco-success); background: var(--arco-success-light); font-size: 11px; }
.worker-card.is-active .worker-card__state { color: var(--arco-primary); background: var(--arco-primary-light); }
.worker-card.is-failed .worker-card__state { color: var(--arco-danger); background: var(--arco-danger-light); }
.worker-card.is-interrupted .worker-card__state { color: var(--arco-warning); background: var(--arco-warning-light); }
.worker-card__time { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
/* 目标说明收进头部同行，单行省略，全文经 title 悬浮查看 */
.worker-card__objective { margin: 0; min-width: 0; overflow: hidden; color: var(--neutral-text-2); font-size: var(--font-caption-size); text-overflow: ellipsis; white-space: nowrap; }
.worker-card__progress { width: 100%; height: 4px; border-radius: 999px; background: var(--neutral-border); overflow: hidden; }
.worker-card__progress--indeterminate .worker-card__progress-bar { width: 40%; height: 100%; border-radius: 999px; background: var(--arco-primary); animation: worker-progress-indeterminate 1.2s ease-in-out infinite; }
@keyframes worker-progress-indeterminate { 0% { transform: translateX(-100%); opacity: 0.6; } 50% { opacity: 1; } 100% { transform: translateX(250%); opacity: 0.6; } }
@media (prefers-reduced-motion: reduce) { .worker-card__progress--indeterminate .worker-card__progress-bar { animation: none; transform: translateX(0); width: 100%; opacity: 0.5; } }
.worker-card__steps { display: grid; gap: var(--space-xs); margin: 0; padding: var(--space-sm) 0 0; border-top: 1px dashed var(--neutral-border); list-style: none; }
.worker-step { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-sm); color: var(--neutral-text-2); font-size: var(--font-caption-size); }
.worker-step__dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--neutral-text-3); }
.worker-step.is-running .worker-step__dot { background: var(--arco-primary); animation: room-pulse 1.6s ease-in-out infinite; }
.worker-step.is-ok .worker-step__dot { background: var(--arco-success); }
.worker-step.is-failed .worker-step__dot { background: var(--arco-danger); }
.worker-step__expand { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; padding: 0; border: none; border-radius: 4px; background: transparent; color: var(--neutral-text-3); cursor: pointer; transition: background-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out; }
.worker-step__expand:hover { background: var(--neutral-hover); color: var(--neutral-text-1); }
.worker-step__name { color: var(--neutral-text-1); font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace; font-size: var(--font-caption-size); }
.worker-step__duration { margin-left: auto; color: var(--neutral-text-3); font-size: 11px; }
.worker-step__details { width: 100%; margin: var(--space-xs) 0 0; padding: var(--space-xs) 0 var(--space-xs) var(--space-xl); border-left: 2px solid var(--neutral-border); list-style: none; }
.worker-step__detail { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-xs) 0; }
.worker-step__detail-name { color: var(--neutral-text-2); font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace; font-size: var(--font-caption-size); }
.worker-card__body { margin: 0; padding-top: var(--space-sm); border-top: 1px solid var(--neutral-border); color: var(--neutral-text-1); font-size: var(--font-body-size); line-height: 1.6; overflow-wrap: anywhere; white-space: pre-wrap; }

/* 失败 / 人工复核动作 */
.room-action { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-sm); padding: var(--space-sm) var(--space-lg); border-left: 3px solid var(--arco-danger); border-radius: var(--radius-sm); background: var(--arco-danger-light); color: var(--neutral-text-1); font-size: var(--font-small-size); line-height: 1.55; }
.room-action__sender { flex: 0 0 auto; font-size: var(--font-caption-size); font-weight: 600; }
.room-action__text { flex: 1 1 auto; min-width: 0; }
.room-action__detail { width: 100%; margin-top: var(--space-xs); }
.room-action__detail summary { cursor: pointer; user-select: none; color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-action__detail-code { display: block; margin-top: var(--space-xs); padding: var(--space-sm); border-radius: var(--radius-sm); background: var(--neutral-card); color: var(--neutral-text-2); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--font-caption-size); line-height: 1.5; white-space: pre-wrap; word-break: break-all; }
.room-action__actions { display: flex; flex-wrap: wrap; gap: var(--space-sm); width: 100%; margin-top: var(--space-sm); }

/* 收起的底层事件 */
.room-collapsed { padding: var(--space-sm) var(--space-md); border: 1px dashed var(--neutral-border); border-radius: 10px; color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-collapsed summary { cursor: pointer; user-select: none; }
.room-collapsed__line { display: flex; align-items: baseline; gap: var(--space-md); padding: var(--space-xs) 0 var(--space-xs) var(--space-sm); }

/* 底部发言输入区：复用 KimiChatInput 默认样式（§3.3.5），页面级只保留布局尺寸——
   与右侧引导内容列等宽（720px 居中列，两侧各留 16px gutter），底部外边距与左栏卡片内边距同为 24px，
   保证输入框底缘与左侧协作室侧边栏底缘对齐；
   卡片背景/边框/圆角/工具行/发送按钮全部由组件默认样式与语义令牌提供，禁止页面级另写表面色与阴影 */
.room-composer { flex-shrink: 0; width: min(calc(100% - var(--space-3xl)), 720px); margin: var(--space-lg) auto var(--space-2xl); }

/* Manager 正在输入指示 */
.room-typing { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-sm) var(--space-md); color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-typing__dots { display: inline-flex; gap: 4px; }
.room-typing__dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--arco-primary); animation: room-pulse 1.6s ease-in-out infinite; }
.room-typing__dots i:nth-child(2) { animation-delay: 0.2s; }
.room-typing__dots i:nth-child(3) { animation-delay: 0.4s; }

/* 消息流 / Element 视图切换：胶囊分段样式，与全局 .omichub-segmented-toggle 同语言 */
.room-view-switch { display: inline-flex; gap: 2px; margin-left: var(--space-md); padding: 2px; border: 1px solid var(--neutral-border); border-radius: 999px; background: var(--neutral-fill-2); }
.room-view-switch__btn { padding: var(--space-xs) var(--space-md); border: none; border-radius: 999px; background: transparent; color: var(--neutral-text-2); font-size: var(--font-caption-size); line-height: 1.7; cursor: pointer; transition: background-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out; }
.room-view-switch__btn:hover { color: var(--neutral-text-1); }
.room-view-switch__btn:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: -2px; }
.room-view-switch__btn.is-active { background: var(--arco-primary); color: var(--text-on-primary); }
.room-element { display: flex; flex: 1; min-height: 0; flex-direction: column; }
.room-element__toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); padding: var(--space-sm) var(--space-2xl); border-bottom: 1px solid var(--neutral-border); }
.room-element__hint { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-element__frame { flex: 1; min-height: 320px; width: 100%; border: none; background: var(--neutral-card); }

.room-modal-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); margin-top: var(--space-xl); }

@keyframes room-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .worker-step.is-running .worker-step__dot { animation: none; } }
/* 减少动态：状态点用静态弱晕染替代脉冲动画（§6.3） */
@media (prefers-reduced-motion: reduce) { .case-entry__status-dot.is-active { animation: none; box-shadow: 0 0 0 3px var(--arco-primary-light); } }
@media (prefers-reduced-motion: reduce) { .room-typing__dots i { animation: none; } }

/* ≤1024px：左栏收纳为可折叠抽屉（默认收起，进入 Case 后自动收起；Esc / 遮罩点击关闭） */
@media (max-width: 1024px) {
  .room-layout { grid-template-columns: minmax(0, 1fr); }
  .room-sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 210; width: min(320px, 84vw); border-radius: 0; box-shadow: var(--shadow-dropdown); transform: translateX(-100%); transition: transform var(--motion-standard) var(--motion-spring); }
  .room-sidebar.is-open { transform: translateX(0); }
  .room-sidebar-backdrop { position: fixed; inset: 0; z-index: 200; background: rgba(0, 0, 0, 0.32); }
}

/* reduced-motion 下抽屉取消位移过渡（置于 1024px 规则之后，确保覆盖生效） */
@media (prefers-reduced-motion: reduce) {
  .room-sidebar { transition: none; }
}

/* ≤768px：页面内边距降至 16px（规范 §7.1），消息区同步收窄 */
@media (max-width: 768px) {
  .room-page { padding: var(--space-lg); }
  .room-messages { padding: var(--space-lg) var(--space-lg) var(--space-xl); }
  .case-header { padding: var(--space-md) var(--space-lg); }
}

/* ≤640px：左栏头部操作区允许换行；快捷胶囊组换行由 .room-guide__actions 的 flex-wrap 承担 */
@media (max-width: 640px) {
  .room-sidebar__toolbar { flex-wrap: wrap; }
}
</style>
