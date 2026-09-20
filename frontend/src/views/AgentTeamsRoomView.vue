<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
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
  NDropdown,
  NPopconfirm,
  NProgress,
  NSpin,
  NTag,
  NTooltip,
  useMessage,
} from 'naive-ui'
import { formatRoomFullTime, formatRoomRelativeTime, formatRoomTime } from '@/utils/roomTimeFormat'
import { displayName } from '@/utils/displayName'
import apiClient from '@/api/client'
import {
  AddOutline,
  CaretDownOutline,
  CaretUpOutline,
  ChevronBackOutline,
  CloseOutline,
  FileTrayOutline,
  MenuOutline,
  PencilOutline,
  RefreshOutline,
  SearchOutline,
  SettingsOutline,
  SparklesOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import {
  agentTeamsApi,
  type AgentTeamsEventListResponse,
  type AgentTeamsCase,
  type AgentTeamsCaseStatus,
  type AgentTeamsContextRef,
  type AgentTeamsElementSession,
  type AgentTeamsEvent,
  type AgentTeamsProposalFollowupMode,
  type AgentTeamsRoom,
  type AgentTeamsRoomMember,
  type AgentTeamsRoomEventListResponse,
} from '@/api/agentTeams'
import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import MessageArtifactGallery from '@/components/ai-chat/MessageArtifactGallery.vue'
import AskUserCard from '@/components/ai-chat/AskUserCard.vue'
import RouteDecisionCard from '@/components/agent-teams/RouteDecisionCard.vue'
import RoomRouteTransitionCard from '@/components/agent-teams/RoomRouteTransitionCard.vue'
import RoomProposalCard from '@/components/agent-teams/RoomProposalCard.vue'
import AgentTeamsSettingsDrawer from '@/components/agent-teams/AgentTeamsSettingsDrawer.vue'
import RoomMcpToolCard from '@/components/agent-teams/RoomMcpToolCard.vue'
import type { AskUserObjectReference, FileAttachment } from '@/components/ai-chat/types'
import type { AgentTemplate } from '@/types/agent'
import { useAgentHubStore } from '@/stores/agentHub'
import { useAgentTeamsOnboardingStore } from '@/stores/agentTeamsOnboarding'
import { useAgentTeamsPreferencesStore } from '@/stores/agentTeamsPreferences'
import { mergeAgentTeamsEvents, shouldPollAgentTeamsCase } from '@/utils/agentTeamsState'
import {
  agentTeamsCaseCategory,
  buildAgentTeamsStageView,
  canSendRoomMessage,
  formatAgentTeamsStatus,
  type AgentTeamsCaseCategory,
} from '@/utils/agentTeamsStatus'
import {
  buildCaseProjectName,
  buildRoomCreateIntent,
  formatDuration,
  formatHardGate,
  formatMentions,
  formatRoomAskReply,
  groupRoomMessages,
  projectCaseEvents,
  resolveElementRoomUrl,
  resolveRoomTyping,
  shouldStartNewRoomCase,
  type RoomAskRequest,
  type RoomChangeAssessment,
  type RoomMessage,
  type RoomRoleMetadata,
  type RoomDebugTrace,
  type RoomToolCall,
  type RoomWorkerBlock,
  type RoomWorkerStep,
} from '@/utils/agentTeamsRoom'

const POLLING_INTERVAL_MS = 20_000
const SSE_RETRY_INITIAL_MS = 1_000
const SSE_RETRY_MAX_MS = 30_000
const LOCAL_TYPING_TTL_MS = 60_000
const ROOM_SIDEBAR_COLLAPSED_KEY = 'cygnusx:agentteams-room-sidebar-collapsed'
const ROOM_MODEL_KEY = 'cygnusx:agentteams-room-model'

const message = useMessage()
const route = useRoute()
const agentHubStore = useAgentHubStore()
const loading = ref(false)
const available = ref(true)
const cases = ref<AgentTeamsCase[]>([])
const selectedCaseId = ref('')
const detail = ref<AgentTeamsCase | null>(null)
// 会话-工单解耦：房间是先于 Case 的轻量会话实体；selectedRoomId 非空即「房间模式」，
// 发消息/事件流/SSE 走 /rooms 端点，立项确认后 roomDetail.case_id 绑定 Case。
const rooms = ref<AgentTeamsRoom[]>([])
const selectedRoomId = ref('')
const roomDetail = ref<AgentTeamsRoom | null>(null)
const creatingRoom = ref(false)
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
const deletingRoomId = ref('')
const draftMessage = ref('')
const projectPickerVisible = ref(false)
const projectPickerLoading = ref(false)
const projectPickerSaving = ref(false)
const projectOptions = ref<Array<{ id: string; name: string; slug: string }>>([])
const selectedProjectId = ref('')
const newProjectName = ref('')
const pendingProjectCreate = ref<{ content: string; contextRefs: AgentTeamsContextRef[] } | null>(null)
const sendingMessage = ref(false)
const selectedModelId = ref('')
const changeDecisionPending = ref('')
const roomViewMode = ref<'stream' | 'element'>('stream')
const inviteVisible = ref(false)
const inviteQuery = ref('')
const inviteResults = ref<Array<{ id: string; nickname: string; avatar?: string | null }>>([])
const inviteLoading = ref(false)
const invitingUserId = ref('')
const roomMembers = ref<AgentTeamsRoomMember[]>([])
const memberActionUserId = ref('')
const settingsVisible = ref(false)
const renameVisible = ref(false)
const renameTitle = ref('')
const renamingRoom = ref(false)
const localTypingUntil = ref<number>(0)
const localTypingName = ref<string | null>(null)
let localTypingTimer: number | null = null
/** 响应式时钟：typing 的 TTL 过期判断依赖 Date.now()，computed 不会在时间到时自动重算；
 *  若无新事件到达（typing:false 丢失等），指示器会永久残留。每秒推进一次驱动 TTL 过期收起。 */
const typingNow = ref(Date.now())
let typingNowTimer: ReturnType<typeof setInterval> | null = null
const seenEventIds = ref<Set<string>>(new Set())
const expandedStepIds = ref<Set<string>>(new Set())
const expandedThoughtIds = ref<Set<string>>(new Set())
const debugEnabled = computed(() => roomPreferences.settings.expandTechnicalEvents)
let pollingTimer: ReturnType<typeof setInterval> | null = null
let eventStreamAbort: AbortController | null = null
let eventStreamRetryTimer: number | null = null
/** 连续异常中断次数：仅用于告警门控；正常到期重连不计入。 */
const eventStreamFailures = ref(0)

const modelOptions = computed(() => agentHubStore.availableModels.map((model) => ({
  label: model.name,
  value: model.id,
})))
const modelMenuOptions = computed(() => modelOptions.value.map((option) => ({
  label: option.label,
  key: option.value,
})))
const selectedModelName = computed(() => {
  const model = agentHubStore.availableModels.find((item) => item.id === selectedModelId.value)
  return model?.name || '默认模型'
})

async function loadRoomModels() {
  if (!agentHubStore.availableModels.length) await agentHubStore.fetchAvailableModels()
  const saved = localStorage.getItem(ROOM_MODEL_KEY) || ''
  const available = agentHubStore.availableModels
  const preferred = available.find((model) => model.id === saved)
    || available.find((model) => model.is_default)
    || available[0]
  if (preferred) selectedModelId.value = preferred.id
}

function handleRoomModelSwitch(modelId: string | number) {
  const nextModelId = String(modelId)
  if (!nextModelId || nextModelId === selectedModelId.value) return
  selectedModelId.value = nextModelId
  localStorage.setItem(ROOM_MODEL_KEY, nextModelId)
  const model = agentHubStore.availableModels.find((item) => item.id === nextModelId)
  message.success(`已切换至 ${model?.name || nextModelId}，后续协作室回复将使用该模型`)
}

const sortedCases = computed(() => [...cases.value].sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
const effectiveRoleMetadata = computed<RoomRoleMetadata>(() => {
  const labels = { ...(roleMetadata.value.role_labels || {}) }
  labels['bioops-manager'] = {
    agent_id: labels['bioops-manager']?.agent_id || 'bioops-manager',
    name: roomPreferences.managerLabel,
    avatar: labels['bioops-manager']?.avatar || '🧑‍🔬',
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
const roomMentionAgents = computed<AgentTemplate[]>(() => Object.values(effectiveRoleMetadata.value.role_labels || {})
  .filter((label) => {
    if (label.agent_id === 'bioops-manager' || label.role === 'manager') return true
    const participants = new Set((detail.value?.work_items || []).map((item) => item.target))
    if (!participants.size) return true
    return participants.has(label.agent_id) || Object.entries(effectiveRoleMetadata.value.role_labels || {})
      .some(([role, participant]) => participants.has(role) && participant.agent_id === label.agent_id)
  })
  .map((label) => ({
    id: label.agent_id,
    name: label.name,
    description: `${label.archetype || `${label.role || '领域'} Agent`} · 当前 Case 参与者`,
    avatar: label.avatar,
    color: label.color,
    category: 'analysis',
    model_engine: 'runtime',
    system_prompt: '',
    welcome_message: '',
    mcp_ids: [],
    skill_ids: [],
    features: {},
    is_active: true,
    is_builtin: true,
    is_default: false,
  })))
const roomMessages = computed(() => projectCaseEvents(events.value, effectiveRoleMetadata.value))
const visibleMessages = computed(() => roomMessages.value.filter((item) => !item.collapsed))
const collapsedMessages = computed(() => roomMessages.value.filter((item) => item.collapsed))
const roomBlocks = computed(() => groupRoomMessages(visibleMessages.value))
const backendTyping = computed(() => resolveRoomTyping(events.value, typingNow.value))
const managerTyping = computed(() => backendTyping.value.active || localTypingUntil.value > typingNow.value)
// 正在输入者名字：后端 typing 事件携带 agent_name 时显示真实响应者（如被 @ 的领域 Agent），
// 否则回退到经理显示名；本地乐观态优先用消息中 @ 提及的名字。
const typingAgentName = computed(() => {
  if (backendTyping.value.active) return backendTyping.value.agentName || roomPreferences.managerLabel
  return localTypingName.value || roomPreferences.managerLabel
})
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
  state: 'pending' | 'preparing' | 'retry' | 'approved' | 'rejected' | 'returned'
  title: string
  summary: string
  impact: string
  /** 终态文案（文本 + 状态色双表达，§5.5）；pending / preparing / retry 为空 */
  terminalText: string
  time: string
  /** hover 完整时间（YYYY年M月D日 HH:mm:ss） */
  fullTime: string
}

/** 已越过审批环节的状态：即使历史事件里找不到 approval.resolved，也不得再回退成待审批卡。 */
const APPROVAL_PASSED_STATUSES: ReadonlySet<AgentTeamsCaseStatus> = new Set([
  'approved',
  'executing',
  'quality_running',
  'quality_blocked',
  'remediation_pending',
  'delivery_ready',
  'closed',
])

const approvalCard = computed<RoomApprovalCard | null>(() => {
  const current = detail.value
  if (!current) return null
  const status = current.status
  const frozenAt = formatMessageTime(approvalFrozenEvent.value?.event_id ?? '')
  const frozenAtFull = formatMessageFullTime(approvalFrozenEvent.value?.event_id ?? '')
  if (status === 'approval_pending') {
    return {
      state: 'pending',
      title: '人工审批请求',
      summary: current.intent,
      impact: '计划已冻结，确认后才会启动真实计算；执行与结果将记录在当前 Case。',
      terminalText: '',
      time: frozenAt,
      fullTime: frozenAtFull,
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
      fullTime: '',
    }
  }
  if (!approvalFrozenEvent.value) return null
  const approvalResolved = events.value.some((event) => {
    if (event.event_type !== 'approval.resolved') return false
    const body = event.payload || {}
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : body) as Record<string, unknown>
    return Boolean(inner.approval_id || inner.action)
  })
  if (status === 'cancelled') {
    // Bridge 侧驳回与用户取消均收敛为 cancelled（case.cancelled 事件），文案如实并列表述
    return { state: 'rejected', title: '人工审批', summary: '', impact: '', terminalText: '已驳回或已取消', time: frozenAt, fullTime: frozenAtFull }
  }
  if (status === 'waiting_for_correction') {
    return { state: 'returned', title: '人工审批', summary: '', impact: '', terminalText: '已退回修正', time: frozenAt, fullTime: frozenAtFull }
  }
  if (status === 'planning_failed') {
    return { state: 'rejected', title: '人工审批', summary: '', impact: '', terminalText: '规划失败，请取消后重新创建 Case', time: frozenAt, fullTime: frozenAtFull }
  }
  if (!approvalResolved && !APPROVAL_PASSED_STATUSES.has(status)) {
    // 计划已冻结但尚未进入待审批（预检/状态推进中）：如实说明进度并给出手动同步入口，
    // 不渲染无可操作项的「等待人工确认」卡片把用户卡死。
    return {
      state: 'preparing',
      title: '人工审批',
      summary: current.intent,
      impact: `计划已冻结，当前状态为「${formatAgentTeamsStatus(status)}」，正在完成预检与审批准备；若长时间停留，请刷新同步最新进展。`,
      terminalText: '',
      time: frozenAt,
      fullTime: frozenAtFull,
    }
  }
  return { state: 'approved', title: '人工审批', summary: '', impact: '', terminalText: '已通过人工审批', time: frozenAt, fullTime: frozenAtFull }
})

// 消息流滚动：新消息到达且用户停留在底部时自动滚底；用户上翻时暂停并显示「回到底部」
const listAtBottom = ref(true)
let listScrollFrame = 0

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
  if (isRoomMode.value) return '发送到协作房间，@ 点名 Agent 或引用工作区文件…'
  if (!selectedCaseId.value) return '输入需求创建协作房间，@ 引用工作区文件'
  return roomInputEnabled.value ? '发送到协作房间，@ 点名 Agent 或引用工作区文件…' : 'Case 加载中，暂无法发言'
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
const desktopSidebarCollapsed = ref(loadDesktopSidebarCollapsed())
const sidebarRef = ref<HTMLElement | null>(null)
const sidebarToggleRef = ref<InstanceType<typeof NButton> | null>(null)
let narrowMedia: MediaQueryList | null = null

function loadDesktopSidebarCollapsed(): boolean {
  return localStorage.getItem(ROOM_SIDEBAR_COLLAPSED_KEY) === 'true'
}

function toggleDesktopSidebar() {
  desktopSidebarCollapsed.value = !desktopSidebarCollapsed.value
  localStorage.setItem(ROOM_SIDEBAR_COLLAPSED_KEY, String(desktopSidebarCollapsed.value))
}

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

async function searchInviteUsers() {
  const query = inviteQuery.value.trim()
  if (!query) { inviteResults.value = []; return }
  inviteLoading.value = true
  try {
    inviteResults.value = (await apiClient.get<Array<{ id: string; nickname: string; avatar?: string | null }>>('/users/lookup', { params: { q: query } })).data
  } catch { inviteResults.value = [] }
  finally { inviteLoading.value = false }
}

async function inviteUser(userId: string) {
  if (!selectedRoomId.value) return
  invitingUserId.value = userId
  try {
    await agentTeamsApi.inviteRoomMember(selectedRoomId.value, userId)
    message.success('邀请已发送')
    await loadRoomMembers()
  } catch (cause: any) { message.error(cause?.response?.data?.detail || '发送邀请失败') }
  finally { invitingUserId.value = '' }
}

async function loadRoomMembers() {
  if (!selectedRoomId.value) return
  try {
    roomMembers.value = await agentTeamsApi.listRoomMembers(selectedRoomId.value)
  } catch {
    roomMembers.value = []
  }
}

async function manageRoomMember(member: AgentTeamsRoomMember) {
  if (!selectedRoomId.value || member.role === 'owner') return
  memberActionUserId.value = member.user_id
  try {
    if (member.status === 'pending') {
      await agentTeamsApi.revokeRoomInvitation(selectedRoomId.value, member.user_id)
      message.success('邀请已撤销')
    } else if (member.status === 'declined') {
      await agentTeamsApi.inviteRoomMember(selectedRoomId.value, member.user_id)
      message.success('已重新发送邀请')
    } else {
      await agentTeamsApi.removeRoomMember(selectedRoomId.value, member.user_id)
      message.success('成员已移除')
    }
    await loadRoomMembers()
  } catch (cause: any) { message.error(cause?.response?.data?.detail || '成员操作失败') }
  finally { memberActionUserId.value = '' }
}

async function leaveCurrentRoom() {
  if (!selectedRoomId.value) return
  try {
    await agentTeamsApi.leaveRoom(selectedRoomId.value)
    message.success('已离开协作室')
    selectedRoomId.value = ''
    roomDetail.value = null
    await loadCases()
  } catch (cause: any) { message.error(cause?.response?.data?.detail || '离开协作室失败') }
}

watch(inviteVisible, (visible) => {
  if (visible) void loadRoomMembers()
})
// Matrix 房间已建（room.created 携带 Gateway 下发的 Element 深链）时才提供 Element 嵌入入口。
const elementRoomUrl = computed(() => resolveElementRoomUrl(events.value))

// Element 免登录会话：切到 Element 视图时按需向主后端申请（凭据经跳板页 fragment 注入，
// 不出现在服务器日志）；会话按房间缓存，切换房间时重置。
const elementSession = ref<AgentTeamsElementSession | null>(null)
const elementSessionLoading = ref(false)
const elementSessionError = ref('')

/** 当前会话对应的房间实体 id：房间模式直接用 selectedRoomId；Case 模式找已绑定的房间行。 */
const elementSessionRoomId = computed(
  () =>
    selectedRoomId.value ||
    rooms.value.find((item) => item.case_id && item.case_id === selectedCaseId.value)?.room_id ||
    '',
)

/** 免登录跳板地址：cygnusx-login.html + fragment 凭据；无房间实体（旧 Case）时为空，退回原始深链。 */
const elementShimUrl = computed(() => {
  const session = elementSession.value
  const base = session?.element_base_url?.replace(/\/+$/, '')
  if (!session || !base || !session.matrix_room_id) return ''
  const fragment =
    `hs=${encodeURIComponent(session.homeserver_url)}` +
    `&user_id=${encodeURIComponent(session.user_id)}` +
    `&token=${encodeURIComponent(session.access_token)}` +
    `&device_id=${encodeURIComponent(session.device_id)}` +
    `&room=${encodeURIComponent(session.matrix_room_id)}`
  return `${base}/cygnusx-login.html#${fragment}`
})

async function ensureElementSession(force = false) {
  if (elementSessionLoading.value) return
  if (elementSession.value && !force) return
  const roomId = elementSessionRoomId.value
  if (!roomId) return
  elementSessionLoading.value = true
  elementSessionError.value = ''
  try {
    elementSession.value = await agentTeamsApi.createRoomElementSession(roomId)
  } catch (cause: any) {
    elementSessionError.value = cause?.response?.data?.detail || 'Element 会话建立失败，请重试。'
  } finally {
    elementSessionLoading.value = false
  }
}

watch(roomViewMode, (mode) => {
  if (mode === 'element') void ensureElementSession()
})

const FILTER_CHIPS: Array<{ key: 'all' | AgentTeamsCaseCategory; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'approval', label: '待审批' },
  { key: 'done', label: '已完成' },
  { key: 'failed', label: '失败' },
]

const categoryCounts = computed(() => {
  const counts: Record<'all' | AgentTeamsCaseCategory, number> = { all: sidebarEntries.value.length, active: 0, approval: 0, done: 0, failed: 0 }
  for (const entry of sidebarEntries.value) counts[entry.category] += 1
  return counts
})

const filterChips = computed(() => FILTER_CHIPS.map((chip) => ({ ...chip, count: categoryCounts.value[chip.key] })))

// ===== 左栏统一条目：房间（轻量会话实体）与未绑定房间的旧 Case 房间合并展示 =====
interface RoomSidebarEntry {
  key: string
  kind: 'case' | 'room'
  title: string
  /** hover 完整提示：Case 条目用完整 intent，房间条目同标题。 */
  tooltip: string
  updatedAt: string
  category: AgentTeamsCaseCategory
  caseItem?: AgentTeamsCase
  roomItem?: AgentTeamsRoom
}

/** 已绑定房间的 Case 不再单独出现在左栏（房间条目即其会话入口），避免双重入口。 */
const boundCaseIds = computed(() => new Set(rooms.value.map((room) => room.case_id).filter((id): id is string => !!id)))

function roomEntryCategory(room: AgentTeamsRoom): AgentTeamsCaseCategory {
  if (!room.case_id) return 'active'
  const bound = cases.value.find((item) => item.case_id === room.case_id)
  return bound ? agentTeamsCaseCategory(bound.status) : 'active'
}

const sidebarEntries = computed<RoomSidebarEntry[]>(() => {
  const entries: RoomSidebarEntry[] = []
  for (const room of rooms.value) {
    entries.push({
      key: room.room_id,
      kind: 'room',
      title: room.title || '协作室会话',
      tooltip: room.title || '协作室会话',
      updatedAt: room.updated_at || room.created_at || '',
      category: roomEntryCategory(room),
      roomItem: room,
    })
  }
  for (const item of cases.value) {
    if (boundCaseIds.value.has(item.case_id)) continue
    entries.push({
      key: item.case_id,
      kind: 'case',
      title: item.display_title || item.intent,
      tooltip: item.intent,
      updatedAt: item.updated_at,
      category: agentTeamsCaseCategory(item.status),
      caseItem: item,
    })
  }
  return entries.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
})

const filteredEntries = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  return sidebarEntries.value.filter((entry) => {
    if (statusFilter.value !== 'all' && entry.category !== statusFilter.value) return false
    if (keyword && !entry.title.toLowerCase().includes(keyword)) return false
    return true
  })
})

const collapsedRailEntries = computed(() => sidebarEntries.value.slice(0, 9))

function isEntryActive(entry: RoomSidebarEntry): boolean {
  return entry.kind === 'room'
    ? entry.key === selectedRoomId.value
    : entry.key === selectedCaseId.value
}

function selectEntry(entry: RoomSidebarEntry) {
  if (entry.kind === 'room') void selectRoom(entry.key)
  else void selectCase(entry.key)
}

// 房间模式派生态：房间未绑定 Case 时不渲染五步进度条，由轻量会话头引导文案承接。
const hasActiveRoom = computed(() => !!selectedCaseId.value || !!selectedRoomId.value)
const isRoomMode = computed(() => !!selectedRoomId.value && !selectedCaseId.value)
const isUnboundRoom = computed(() => isRoomMode.value && !roomDetail.value?.case_id)

// 单一事实源：激活步骤由 utils/agentTeamsStatus 的 Case 状态映射派生；
// detail 为空（未立项房间）时返回 null，模板不渲染进度条（§1.7）。
const stageView = computed(() => buildAgentTeamsStageView(detail.value?.status))

const headerTitle = computed(() => {
  if (isRoomMode.value) return roomDetail.value?.title || '协作室会话'
  return caseTitle.value
})

const caseTitle = computed(() => {
  if (detail.value) return detail.value.display_title || detail.value.intent
  const selected = cases.value.find((item) => item.case_id === selectedCaseId.value)
  return selected?.display_title || selected?.intent || ''
})

// 发起人展示名：优先昵称/用户名（§5.4 长标识符不直出）；requester_ref（UUID）只进 Tooltip。
// TODO: Case 数据模型暂无「是否本人」标记，昵称/用户名均缺失时暂以「我」降级。
const requesterDisplayName = computed(() => {
  const value = detail.value
  if (!value) return ''
  return displayName({ nickname: value.requester_nickname, username: value.requester_username }) || '我'
})
const requesterRef = computed(() => detail.value?.requester_ref || '')
const requesterInitial = computed(() => requesterDisplayName.value.trim().charAt(0) || '协')

// 头部元信息收敛为一行：发起人 X · 创建于 T；「更新于」仅在确实晚于创建时间时显示。
const createdAtText = computed(() => formatRoomTime(detail.value?.created_at))
const createdAtFull = computed(() => formatRoomFullTime(detail.value?.created_at))
const updatedAtText = computed(() => {
  const created = Date.parse(detail.value?.created_at || '')
  const updated = Date.parse(detail.value?.updated_at || '')
  if (Number.isNaN(created) || Number.isNaN(updated) || updated <= created) return ''
  return formatRoomTime(detail.value?.updated_at)
})
const updatedAtFull = computed(() => (updatedAtText.value ? formatRoomFullTime(detail.value?.updated_at) : ''))

const tagType = (status: AgentTeamsCaseStatus) => {
  if (['closed', 'delivery_ready'].includes(status)) return 'success'
  if (['preflight_blocked', 'quality_blocked', 'execution_failed', 'planning_failed'].includes(status)) return 'error'
  if (['approval_pending', 'waiting_for_correction', 'remediation_pending'].includes(status)) return 'warning'
  return 'info'
}

// 消息时间戳：全页统一三档规则（utils/roomTimeFormat），此处只做 eventId → recorded_at 查表
function formatMessageTime(eventId: string): string {
  return formatRoomTime(eventTimes.value.get(eventId))
}

/** 消息时间 hover 完整时间（YYYY年M月D日 HH:mm:ss） */
function formatMessageFullTime(eventId: string): string {
  return formatRoomFullTime(eventTimes.value.get(eventId))
}

const ROOM_CATEGORY_LABELS: Record<AgentTeamsCaseCategory, string> = {
  active: '进行中',
  approval: '待审批',
  done: '已完成',
  failed: '失败',
}

/** 任务进展卡片进度：已完结步骤占比（running 视为未完结），无步骤时模板不渲染 */
function workerStepProgress(block: RoomWorkerBlock): number {
  if (!block.steps.length) return 0
  const settled = block.steps.filter((step) => step.tool.status !== 'running').length
  return Math.round((settled / block.steps.length) * 100)
}

function formatDebugTrace(trace: RoomDebugTrace): string {
  return [
    trace.toolCallId ? `tool_call_id: ${trace.toolCallId}` : '',
    trace.round !== undefined ? `round: ${trace.round}` : '',
    trace.executionPath ? `execution_path: ${trace.executionPath}` : '',
    trace.argsSummary ? `参数摘要: ${trace.argsSummary}` : '',
    trace.resultSummary ? `结果摘要: ${trace.resultSummary}` : '',
  ].filter(Boolean).join('\n')
}

/** 发言气泡内联工具卡片的调试信息：有参数/结果摘要时才传，供卡片展开查看。 */
function speechToolDebugTrace(toolCall: RoomToolCall): RoomDebugTrace | undefined {
  if (!toolCall.argsSummary && !toolCall.resultSummary) return undefined
  return {
    toolCallId: toolCall.id,
    argsSummary: toolCall.argsSummary,
    resultSummary: toolCall.resultSummary,
  }
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

function toggleThought(messageId: string) {
  const next = new Set(expandedThoughtIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedThoughtIds.value = next
}

function isThoughtExpanded(messageId: string): boolean {
  return expandedThoughtIds.value.has(messageId)
}

function clearLocalTyping() {
  localTypingUntil.value = 0
  localTypingName.value = null
  if (localTypingTimer !== null) {
    clearTimeout(localTypingTimer)
    localTypingTimer = null
  }
}

/** 从消息内容解析第一个 @ 提及的名字，用于本地乐观"正在输入"态显示真实响应者。 */
function firstMentionName(content: string): string | null {
  return content.match(/@([^\s@，,：:]+)/)?.[1] ?? null
}

function showLocalTyping(name?: string | null) {
  clearLocalTyping()
  localTypingName.value = name ?? null
  localTypingUntil.value = Date.now() + LOCAL_TYPING_TTL_MS
  localTypingTimer = window.setTimeout(clearLocalTyping, LOCAL_TYPING_TTL_MS)
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

/** 该事件到达即代表本地「正在输入」兜底态可以收起（真实回复/流式增量/后端输入结束）。 */
function isTypingStopEvent(event: AgentTeamsEvent): boolean {
  if (event.event_type === 'room.agent_message'
    || event.event_type === 'room.ask_user'
    || event.event_type === 'room.agent_stream') return true
  if (event.event_type !== 'room.typing') return false
  const body = (event.payload || {}) as Record<string, unknown>
  const inner = (body.payload && typeof body.payload === 'object' ? body.payload : body) as Record<string, unknown>
  return inner.typing === false
}

function mergeEvents(incoming: AgentTeamsEvent[]) {
  const uniqueIncoming = incoming.filter((event) => {
    if (seenEventIds.value.has(event.event_id)) return false
    seenEventIds.value.add(event.event_id)
    return true
  })
  if (!uniqueIncoming.length) return
  events.value = mergeAgentTeamsEvents(events.value, uniqueIncoming)
  if (uniqueIncoming.some(isTypingStopEvent)) {
    clearLocalTyping()
  }
}

async function loadCases(selectFirst = false) {
  loading.value = true
  try {
    // 优先加载 Case 列表，状态探测在后台完成，避免 Bridge /healthz 延迟阻塞首屏渲染。
    // 若 Bridge 不可用，列表请求本身也会失败，后台探测仅用于降级提示与可用性标识。
    const listPromise = agentTeamsApi.listCases({ limit: 50 }).catch(() => null)
    // 房间列表（轻量会话实体）并行加载；失败不阻断 Case 列表，房间区留空即可。
    const roomsPromise = agentTeamsApi.listRooms().catch(() => null)
    void agentTeamsApi
      .status()
      .then((state) => {
        available.value = state.available
        if (!state.available) cases.value = []
      })
      .catch(() => { available.value = false })

    const result = await listPromise
    rooms.value = (await roomsPromise)?.items ?? []
    if (!result) {
      message.error('无法获取协作 Case 列表。')
      return
    }
    cases.value = result.items
    if (selectFirst && sidebarEntries.value.length && !selectedCaseId.value && !selectedRoomId.value) {
      // 不阻塞列表渲染：详情与事件流异步填充
      selectEntry(sidebarEntries.value[0])
    }
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '无法获取协作 Case 列表。')
  } finally {
    loading.value = false
  }
}

function handleRoomMembershipChanged() {
  void loadCases()
}

async function refreshDetail(options: { resetEvents?: boolean; background?: boolean } = {}) {
  if (selectedRoomId.value) return refreshRoomDetail(options)
  if (!selectedCaseId.value) return
  try {
    const cursor = options.resetEvents ? undefined : eventCursor.value ?? undefined
    const [caseData, eventData] = await Promise.all([
      agentTeamsApi.getCase(selectedCaseId.value),
      loadCaseEvents(selectedCaseId.value, { cursor, loadAll: !!options.resetEvents }),
    ])
    detail.value = caseData
    if (options.resetEvents) {
      events.value = eventData.events
      seenEventIds.value = new Set(eventData.events.map((event) => event.event_id))
    } else {
      mergeEvents(eventData.events)
    }
    // SSE cursor 必须指向当前已展示的最后一条事件；next_cursor 只表示分页仍有后续历史，
    // 不能直接拿它启动实时流，否则切换房间后会跳过已落库的消息。
    eventCursor.value = events.value.at(-1)?.event_id ?? null
  } catch (cause: any) {
    if (!options.background) {
      const detailMessage = cause?.response?.data?.detail
      const statusCode = cause?.response?.status
      const suffix = statusCode ? `（HTTP ${statusCode}）` : ''
      message.error(detailMessage ? `${detailMessage}${suffix}` : '无法获取协作 Case 详情。')
    }
  }
}

async function loadCaseEvents(
  caseId: string,
  options: { cursor?: string; loadAll: boolean },
): Promise<AgentTeamsEventListResponse> {
  const events: AgentTeamsEvent[] = []
  let cursor = options.cursor
  do {
    const page = await agentTeamsApi.getEvents(caseId, { cursor, limit: 100 })
    events.push(...page.events)
    if (!options.loadAll || !page.next_cursor || !page.events.length) {
      return { events, next_cursor: page.next_cursor }
    }
    cursor = page.next_cursor
  } while (events.length < 5_000)
  return { events, next_cursor: cursor }
}

// ===== 房间模式（会话-工单解耦）：事件拉取/SSE/发言全部走 /rooms 端点 =====
async function loadRoomEvents(
  roomId: string,
  options: { cursor?: string; loadAll: boolean },
): Promise<AgentTeamsRoomEventListResponse> {
  const events: AgentTeamsEvent[] = []
  let cursor = options.cursor
  do {
    const page = await agentTeamsApi.getRoomEvents(roomId, { cursor, limit: 100 })
    events.push(...page.events)
    if (!options.loadAll || !page.next_cursor || !page.events.length) {
      return { events, next_cursor: page.next_cursor }
    }
    cursor = page.next_cursor
  } while (events.length < 5_000)
  return { events, next_cursor: cursor }
}

function upsertRoom(room: AgentTeamsRoom) {
  const index = rooms.value.findIndex((item) => item.room_id === room.room_id)
  if (index >= 0) rooms.value[index] = room
  else rooms.value.push(room)
}

async function refreshRoomDetail(options: { resetEvents?: boolean; background?: boolean } = {}) {
  const roomId = selectedRoomId.value
  if (!roomId) return
  try {
    // 房间事件游标是复合游标（ns:<id>|case:<id>），对前端不透明，原样回传即可。
    const cursor = options.resetEvents ? undefined : eventCursor.value ?? undefined
    const [roomData, eventData] = await Promise.all([
      agentTeamsApi.getRoom(roomId),
      loadRoomEvents(roomId, { cursor, loadAll: !!options.resetEvents }),
    ])
    roomDetail.value = roomData
    upsertRoom(roomData)
    // 立项确认后绑定 Case：拉取 Case 详情驱动五步进度条；未立项保持 null（进度条隐藏）。
    if (roomData.case_id) {
      detail.value = await agentTeamsApi.getCase(roomData.case_id).catch(() => detail.value)
    } else {
      detail.value = null
    }
    if (options.resetEvents) {
      events.value = eventData.events
      seenEventIds.value = new Set(eventData.events.map((event) => event.event_id))
    } else {
      mergeEvents(eventData.events)
    }
    // 复合游标指向两路事件流各自已读位置；SSE 重连沿用该游标，重叠事件靠 event_id 去重。
    eventCursor.value = eventData.next_cursor || eventCursor.value
  } catch (cause: any) {
    if (!options.background) {
      const detailMessage = cause?.response?.data?.detail
      const statusCode = cause?.response?.status
      const suffix = statusCode ? `（HTTP ${statusCode}）` : ''
      message.error(detailMessage ? `${detailMessage}${suffix}` : '无法获取协作房间详情。')
    }
  }
}

async function selectRoom(roomId: string) {
  if (!roomId || roomId === selectedRoomId.value) return
  // 窄屏抽屉模式下进入房间后收起左栏
  if (isNarrowViewport.value) sidebarOpen.value = false
  stopEventStream()
  selectedCaseId.value = ''
  selectedRoomId.value = roomId
  roomDetail.value = rooms.value.find((item) => item.room_id === roomId) || null
  detail.value = null
  events.value = []
  eventCursor.value = null
  elementSession.value = null
  elementSessionError.value = ''
  clearLocalTyping()
  seenEventIds.value = new Set()
  expandedStepIds.value = new Set()
  roomViewMode.value = 'stream'
  await refreshRoomDetail({ resetEvents: true })
  void startEventStream()
}

async function selectCase(caseId: string) {
  if (!caseId || caseId === selectedCaseId.value) return
  // 窄屏抽屉模式下进入 Case 后收起左栏
  if (isNarrowViewport.value) sidebarOpen.value = false
  stopEventStream()
  selectedRoomId.value = ''
  roomDetail.value = null
  selectedCaseId.value = caseId
  detail.value = null
  events.value = []
  eventCursor.value = null
  elementSession.value = null
  elementSessionError.value = ''
  clearLocalTyping()
  seenEventIds.value = new Set()
  expandedStepIds.value = new Set()
  roomViewMode.value = 'stream'
  await refreshDetail({ resetEvents: true })
  void startEventStream()
}

async function sendRoomMessage(content: string, contextRefs: AgentTeamsContextRef[] = []): Promise<boolean> {
  if (!content || !roomInputEnabled.value || sendingMessage.value) return false
  // 房间模式：发言落房间事件流（未立项落房间命名空间，已绑定由后端路由到 Case 流），
  // 不再在首条消息时隐式建 Case——立项由 room.proposal_confirm 卡片确认触发。
  if (isRoomMode.value) return sendRoomNamespaceMessage(content, contextRefs)
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
      return true
    } catch (cause: any) {
      draftMessage.value = content
      message.error(cause?.response?.data?.detail || '新建系统发育树 Case 失败，请稍后重试。')
      return false
    } finally {
      sendingMessage.value = false
    }
  }
  const optimisticEventId = `local-user-message-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const clientMessageId = `room-msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  sendingMessage.value = true
  try {
    if (!caseId) {
      // 空态直接发消息：先建轻量房间实体（不建 Case），再把首条消息发到房间；
      // 立项由后续 room.proposal_confirm 卡片确认触发。建房失败回退旧的聊天式建 Case 路径。
      try {
        const room = await agentTeamsApi.createRoom({
          title: content.trim().replace(/\s+/g, ' ').slice(0, 30),
          origin: 'manual',
        })
        upsertRoom(room)
        await selectRoom(room.room_id)
        return await sendRoomNamespaceMessage(content, contextRefs)
      } catch (roomCause: any) {
        if (selectedRoomId.value) {
          // 房间已建但首条消息发送失败：不再回退建 Case，按发送失败处理（草稿已恢复）。
          message.error(roomCause?.response?.data?.detail || '发送失败，请稍后重试。')
          return false
        }
        await createCaseFromDraft(content, contextRefs)
        return true
      }
    }
    mergeEvents([{
      event_id: optimisticEventId,
      recorded_at: new Date().toISOString(),
      case_id: caseId,
      actor: 'current-user',
      event_type: 'room.user_message',
      payload: {
        summary: content.slice(0, 80),
        payload: {
          actor: 'current-user',
          content,
          context_refs: contextRefs,
          client_message_id: clientMessageId,
        },
        optimistic: true,
      },
    }])
    draftMessage.value = ''
    const result = await agentTeamsApi.postCaseMessage(caseId, content, contextRefs, clientMessageId, selectedModelId.value)
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
    if (result.response_dispatch === 'failed') {
      clearLocalTyping()
      message.warning('消息已记录，但 Manager 回复调度暂不可用，请稍后重试。')
    } else {
      showLocalTyping(firstMentionName(content))
    }
    // 发言经审计事件回投房间；事件流不可用时立即拉一次，不等轮询。
    if (!eventStreamHealthy.value) await refreshDetail({ background: true })
    return true
  } catch (cause: any) {
    if (selectedCaseId.value === caseId) {
      events.value = events.value.filter((event) => event.event_id !== optimisticEventId)
    }
    // 失败兜底：KimiChatInput 在 emit 时已清空自身草稿，这里恢复原文避免用户丢稿
    draftMessage.value = content
    message.error(cause?.response?.data?.detail || '发送失败，请稍后重试。')
    return false
  } finally {
    sendingMessage.value = false
  }
}

/** 房间模式发言：乐观上屏（case_id 为 room-<id> 命名空间）后调 /rooms/{id}/messages。 */
async function sendRoomNamespaceMessage(content: string, contextRefs: AgentTeamsContextRef[] = []): Promise<boolean> {
  const roomId = selectedRoomId.value
  if (!roomId) return false
  const optimisticEventId = `local-user-message-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const clientMessageId = `room-msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  sendingMessage.value = true
  mergeEvents([{
    event_id: optimisticEventId,
    recorded_at: new Date().toISOString(),
    case_id: `room-${roomId}`,
    actor: 'current-user',
    event_type: 'room.user_message',
    payload: {
      summary: content.slice(0, 80),
      payload: {
        actor: 'current-user',
        content,
        context_refs: contextRefs,
        client_message_id: clientMessageId,
      },
      optimistic: true,
    },
  }])
  draftMessage.value = ''
  try {
    const result = await agentTeamsApi.postRoomMessage(roomId, content, contextRefs, clientMessageId, selectedModelId.value)
    const serverEventId = typeof result.event_id === 'string' ? result.event_id : ''
    if (selectedRoomId.value === roomId && serverEventId) {
      const serverEventArrived = events.value.some((event) => event.event_id === serverEventId)
      events.value = serverEventArrived
        ? events.value.filter((event) => event.event_id !== optimisticEventId)
        : events.value.map((event) =>
          event.event_id === optimisticEventId
            ? { ...event, event_id: serverEventId, payload: { ...event.payload, optimistic: true } }
            : event,
        )
    }
    if (result.response_dispatch === 'failed') {
      clearLocalTyping()
      message.warning('消息已记录，但 Manager 回复调度暂不可用，请稍后重试。')
    } else {
      showLocalTyping(firstMentionName(content))
    }
    // 发言经审计事件回投房间；事件流不可用时立即拉一次，不等轮询。
    if (!eventStreamHealthy.value) await refreshRoomDetail({ background: true })
    return true
  } catch (cause: any) {
    if (selectedRoomId.value === roomId) {
      events.value = events.value.filter((event) => event.event_id !== optimisticEventId)
    }
    // 失败兜底：KimiChatInput 在 emit 时已清空自身草稿，这里恢复原文避免用户丢稿
    draftMessage.value = content
    message.error(cause?.response?.data?.detail || '发送失败，请稍后重试。')
    return false
  } finally {
    sendingMessage.value = false
  }
}

// ===== 立项确认卡（room.proposal_confirm）：confirm 建 Case 绑定房间；
// modify 关卡并把原始需求回填输入框；cancel 关卡。followup 卡带 followup_mode。 =====
async function submitProposalDecision(
  proposalMessage: RoomMessage,
  decision: 'confirm' | 'modify' | 'cancel',
  followupMode?: AgentTeamsProposalFollowupMode,
) {
  const proposal = proposalMessage.proposal
  const roomId = selectedRoomId.value
  if (!proposal || proposal.status !== 'pending' || proposal.submitting || !roomId) return
  proposal.submitting = true
  try {
    const result = await agentTeamsApi.confirmRoomProposal(roomId, {
      decision,
      followup_mode: followupMode,
    })
    if (decision === 'modify') {
      proposal.status = 'modify_requested'
      // 修改需求：把原始需求回填输入框，用户改完重新发消息即可触发新的立项卡。
      draftMessage.value = proposal.originContent
      message.info('已回填需求描述，修改后直接发送即可。')
      await nextTick()
      composerRef.value?.focus()
    } else if (decision === 'cancel') {
      proposal.status = 'cancelled'
      message.success('已取消本次立项。')
    } else {
      proposal.status = 'confirmed'
      if (result.status === 'already_bound') {
        message.info('该房间已绑定协作 Case。')
      } else {
        message.success('立项已确认，协作 Case 创建完成。')
      }
    }
    // 重拉房间详情与事件：消费结果事件（case_bound/关卡事件）回投后卡片转为只读结果态，
    // confirm 时同时带出绑定的 Case 详情，驱动五步进度条平滑出现。
    await refreshRoomDetail({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '立项确认失败，请稍后重试。')
  } finally {
    proposal.submitting = false
  }
}

async function submitChangeDecision(
  assessment: RoomChangeAssessment,
  decision: 'resume' | 'replan' | 'branch' | 'cancel',
) {
  const caseId = selectedCaseId.value
  if (!caseId || !assessment.workItemIds.length || changeDecisionPending.value) return
  changeDecisionPending.value = `${assessment.workItemIds.join(',')}:${decision}`
  try {
    await agentTeamsApi.applyChangeDecision(caseId, {
      work_item_ids: assessment.workItemIds,
      decision,
      rationale: `用户在协作室选择：${decision}`,
    })
    message.success(decision === 'cancel' ? '已终止受影响支线。' : '决策已记录，等待 Manager 继续编排。')
    await refreshDetail({ background: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '变更决策提交失败，请稍后重试。')
  } finally {
    changeDecisionPending.value = ''
  }
}

// ===== Manager 澄清卡片（room.ask_user）：答案格式化为带标记的房间发言，
// 复用既有发言链路触发 Manager 响应；投影层据标记把答案回填到卡片。 =====
async function uploadAskObjectFile(file: File): Promise<AgentTeamsContextRef> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await apiClient.post('/files/chat-upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  const id = String(response.data?.id || '').trim()
  if (!id) throw new Error('上传接口未返回文件标识')
  return { kind: 'file', id, location: file.name }
}

async function submitRoomAskAnswers(
  ask: RoomAskRequest | undefined,
  answers: string[],
  objectReference?: AskUserObjectReference,
) {
  if (!ask || ask.answered || ask.submitting || ask.submitted) return
  ask.submitting = true
  try {
    const contextRefs: AgentTeamsContextRef[] = []
    if (ask.objectRequired) {
      if (objectReference?.contextRef) contextRefs.push(objectReference.contextRef)
      else if (objectReference?.file) contextRefs.push(await uploadAskObjectFile(objectReference.file))
      else if (objectReference?.path) {
        const path = objectReference.path.trim()
        if (path) contextRefs.push({ kind: 'workspace', id: path, location: path })
      }
      const discussionOnly = answers.some((answer) => (
        answer.includes('先讨论') || answer.includes('暂不执行')
      ))
      if (!contextRefs.length && !discussionOnly) return
    }
    const accepted = await sendRoomMessage(formatRoomAskReply(ask.questions, answers), contextRefs)
    if (accepted) {
      ask.submitted = true
      ask.answers = answers
    }
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || cause?.message || '文件上传失败，请重试。')
  } finally {
    ask.submitting = false
  }
}

// 聊天式创建：未选中 Case 时首条消息即意图——创建通用 Case 后原文发到房间，
// 触发既有 Manager 响应链路；@ 引用的文件作为 context_refs 随创建与首条发言落审计，
// 无显式引用时上下文由后端注入发起人工作区只读引用。
async function createCaseFromDraft(
  content: string,
  contextRefs: AgentTeamsContextRef[] = [],
  project?: { id?: string; name?: string },
) {
  // 跳过项目选择弹窗：无选定项目时用需求内容自动生成目录名（前 30 字），直接建 Case。
  const resolvedProject: { project_id?: string; project_name?: string } = project?.id
    ? { project_id: project.id }
    : { project_name: project?.name || buildCaseProjectName(content) }
  const created = await agentTeamsApi.createCase({
    intent: buildRoomCreateIntent(content),
    context_refs: contextRefs.length ? contextRefs : undefined,
    ...resolvedProject,
  })
  draftMessage.value = ''
  message.success('协作 Case 已创建，领域助手将先确认方案；真实计算需在审批卡中由你确认。')
  selectedCaseId.value = ''
  await loadCases()
  await selectCase(created.case_id)
  // 创建后立刻显示用户首条消息（乐观更新），避免 SSE 尚未连接或回投延迟时页面空白。
  const optimisticEventId = `local-user-message-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const clientMessageId = `room-msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  mergeEvents([{
    event_id: optimisticEventId,
    recorded_at: new Date().toISOString(),
    case_id: created.case_id,
    actor: 'current-user',
    event_type: 'room.user_message',
    payload: {
      summary: content.slice(0, 80),
      payload: {
        actor: 'current-user',
        content,
        context_refs: contextRefs,
        client_message_id: clientMessageId,
      },
      optimistic: true,
    },
  }])
  try {
    const result = await agentTeamsApi.postCaseMessage(created.case_id, content, contextRefs, clientMessageId)
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
    if (result.response_dispatch === 'failed') {
      clearLocalTyping()
      message.warning('消息已记录，但 Manager 回复调度暂不可用，请稍后重试。')
    } else {
      showLocalTyping(firstMentionName(content))
    }
    // 事件流未就绪时立即拉取一次，确保用户消息与 Manager 回复尽快出现。
    if (!eventStreamHealthy.value) await refreshDetail({ resetEvents: true })
  } catch (cause: any) {
    events.value = events.value.filter((event) => event.event_id !== optimisticEventId)
    clearLocalTyping()
    message.error(cause?.response?.data?.detail || '发送失败，请稍后重试。')
  }
  if (roomPreferences.settings.showOnboarding) {
    onboardingCaseId.value = created.case_id
    onboarding.begin()
  }
  void nextTick(() => scrollListToBottom())
}

async function confirmProjectBinding() {
  if (!pendingProjectCreate.value) return
  const name = newProjectName.value.trim()
  if (!selectedProjectId.value && !name) {
    message.warning('请选择既有项目或填写新项目名称。')
    return
  }
  projectPickerSaving.value = true
  try {
    const pending = pendingProjectCreate.value
    const project = selectedProjectId.value ? { id: selectedProjectId.value } : { name }
    projectPickerVisible.value = false
    pendingProjectCreate.value = null
    selectedProjectId.value = ''
    newProjectName.value = ''
    await createCaseFromDraft(pending.content, pending.contextRefs, project)
  } finally {
    projectPickerSaving.value = false
  }
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
  eventStreamFailures.value = 0
}

async function startEventStream() {
  if (!selectedCaseId.value && !selectedRoomId.value) return
  stopEventStream()
  const controller = new AbortController()
  eventStreamAbort = controller
  const roomMode = !!selectedRoomId.value
  // Bridge 侧 watch_seconds 到期会正常结束流（done），这是设计内心跳式重连，
  // 不算故障：立即重连、不计失败次数，避免告警条每分钟闪一次。
  let streamEndedCleanly = false
  try {
    const token = localStorage.getItem('access_token')
    const params = new URLSearchParams()
    if (eventCursor.value) params.set('cursor', eventCursor.value)
    // 房间模式走聚合事件流（房间命名空间 + 已绑定 Case 两流归并），其余保持 Case 流。
    const streamUrl = roomMode
      ? `/api/v1/agent-teams/rooms/${selectedRoomId.value}/events/stream?${params.toString()}`
      : `/api/v1/agent-teams/cases/${selectedCaseId.value}/events/stream?${params.toString()}`
    const response = await fetch(streamUrl, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`SSE 请求失败（${response.status}）`)
    eventStreamHealthy.value = true
    eventStreamFailures.value = 0
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read()
      if (done) {
        streamEndedCleanly = true
        break
      }
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const event = JSON.parse(line.slice(5).trim()) as AgentTeamsEvent
          mergeEvents([event])
          // Case 流游标即事件 id；房间流是复合游标，只能由 events 分页响应推进，
          // 重连时沿用最近一次分页游标，重叠事件靠 mergeEvents 的 event_id 去重。
          if (!roomMode) eventCursor.value = event.event_id || eventCursor.value
          if (event.event_type === 'case.state_changed' || event.event_type === 'room.case_bound') {
            void refreshDetail({ background: true })
          }
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
        const delay = streamEndedCleanly
          ? 0
          : Math.min(SSE_RETRY_MAX_MS, SSE_RETRY_INITIAL_MS * 2 ** Math.min(eventStreamFailures.value, 5))
        if (!streamEndedCleanly) eventStreamFailures.value += 1
        eventStreamRetryTimer = window.setTimeout(() => {
          eventStreamRetryTimer = null
          void startEventStream()
        }, delay)
      }
    }
  }
}

// 「新房间」：会话-工单解耦后先建轻量房间实体（不建 Case），首条消息只是房间发言；
// 立项由 Manager 的 room.proposal_confirm 卡片确认触发。建房失败时降级为旧的空态草稿模式。
async function startNewRoom() {
  if (creatingRoom.value) return
  creatingRoom.value = true
  try {
    const room = await agentTeamsApi.createRoom({ title: '和你的生物信息团队聊聊', origin: 'manual' })
    upsertRoom(room)
    selectedRoomId.value = ''
    await selectRoom(room.room_id)
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '创建协作房间失败，请稍后重试。')
    // 降级：回到未选中空态，下一条消息仍走旧的聊天式建 Case 路径
    stopEventStream()
    selectedCaseId.value = ''
    selectedRoomId.value = ''
    roomDetail.value = null
    detail.value = null
    events.value = []
    eventCursor.value = null
    clearLocalTyping()
    seenEventIds.value = new Set()
    expandedStepIds.value = new Set()
    roomViewMode.value = 'stream'
  } finally {
    creatingRoom.value = false
    await nextTick()
    composerRef.value?.focus()
  }
}

function openRenameRoom() {
  if (!roomDetail.value || roomDetail.value.role === 'invited') return
  renameTitle.value = roomDetail.value.title
  renameVisible.value = true
}

async function renameCurrentRoom() {
  const roomId = selectedRoomId.value
  const title = renameTitle.value.trim()
  if (!roomId || !title || renamingRoom.value) return
  renamingRoom.value = true
  try {
    const room = await agentTeamsApi.renameRoom(roomId, title)
    roomDetail.value = room
    upsertRoom(room)
    renameVisible.value = false
    message.success('协作室名称已更新')
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '重命名失败，请稍后重试。')
  } finally {
    renamingRoom.value = false
  }
}

// 审批准备中卡片的手动同步：触发 Bridge reconcile 并重拉详情/列表，给滞留状态一个出口。
const approvalRefreshing = ref(false)
async function refreshApprovalState() {
  if (!detail.value || approvalRefreshing.value) return
  approvalRefreshing.value = true
  try {
    await agentTeamsApi.refreshCase(detail.value.case_id)
    await Promise.all([refreshDetail({ resetEvents: true }), loadCases()])
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '状态同步失败，请稍后重试。')
  } finally {
    approvalRefreshing.value = false
  }
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
    message.success('已通过 Workflow Operator 提交 CygnusX 任务。')
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
    const timedOut = cause?.code === 'ECONNABORTED' || /timeout/i.test(String(cause?.message || ''))
    if (timedOut) {
      await loadCases()
      const stillExists = cases.value.some((entry) => entry.case_id === item.case_id)
      if (!stillExists) {
        if (selectedCaseId.value === item.case_id) {
          stopEventStream()
          selectedCaseId.value = ''
          detail.value = null
          events.value = []
          eventCursor.value = null
        }
        message.success('删除请求超时，已完成对账：协作房间已删除。')
        return
      }
      message.warning('删除请求超时，已重新拉取房间列表；当前结果未知，请稍后重试。')
      return
    }
    message.error(cause?.response?.data?.detail || '删除协作房间失败，请稍后重试。')
  } finally {
    deletingCaseId.value = ''
  }
}

// 删除房间实体（轻量会话）：后端清空该窗口全部内容——房间命名空间会话事件流、
// 已绑定 Case（未结束先取消）与审计记录一并移除；删除当前房间时同时清理详情与事件流
async function deleteRoom(item: AgentTeamsRoom) {
  if (deletingRoomId.value) return
  deletingRoomId.value = item.room_id
  try {
    await agentTeamsApi.deleteRoom(item.room_id)
    message.success('协作房间已删除，该聊天窗口的全部内容已清除。')
    if (selectedRoomId.value === item.room_id) {
      stopEventStream()
      selectedRoomId.value = ''
      roomDetail.value = null
      detail.value = null
      events.value = []
      eventCursor.value = null
    }
    rooms.value = rooms.value.filter((entry) => entry.room_id !== item.room_id)
    // 房间已绑定 Case 时后端一并删除，左栏同步移除该 Case（未绑定时 case_id 为空，filter 无影响）
    if (item.case_id) cases.value = cases.value.filter((entry) => entry.case_id !== item.case_id)
  } catch (cause: any) {
    const timedOut = cause?.code === 'ECONNABORTED' || /timeout/i.test(String(cause?.message || ''))
    if (timedOut) {
      await loadCases()
      const stillExists = rooms.value.some((entry) => entry.room_id === item.room_id)
      if (!stillExists) {
        if (selectedRoomId.value === item.room_id) {
          stopEventStream()
          selectedRoomId.value = ''
          roomDetail.value = null
          detail.value = null
          events.value = []
          eventCursor.value = null
        }
        message.success('删除请求超时，已完成对账：协作房间已删除。')
        return
      }
      message.warning('删除请求超时，已重新拉取房间列表；当前结果未知，请稍后重试。')
      return
    }
    message.error(cause?.response?.data?.detail || '删除协作房间失败，请稍后重试。')
  } finally {
    deletingRoomId.value = ''
  }
}

// 左栏删除入口分流：旧 Case 房间走 Case 删除，新房间实体走房间删除
function deleteSidebarEntry(entry: RoomSidebarEntry) {
  if (entry.caseItem) return deleteRoomCase(entry.caseItem)
  if (entry.roomItem) return deleteRoom(entry.roomItem)
}

watch(visibleMessages, async () => {
  await nextTick()
  if (!listAtBottom.value) return
  // 等头部与消息内容完成一帧布局后再滚底：进入房间时头部/卡片异步渲染会改变
  // 滚动高度，按旧高度滚底会导致视口停在半截位置（首条气泡看似被头部裁掉）。
  // 仅调整滚动时机，不改变「停留底部才自动滚底」的既有策略。
  cancelAnimationFrame(listScrollFrame)
  listScrollFrame = requestAnimationFrame(() => {
    listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
  })
})

onMounted(() => {
  roomPreferences.hydrateFromUser()
  void loadRoomModels()
  typingNowTimer = setInterval(() => { typingNow.value = Date.now() }, 1000)
  // 首屏骨架立即渲染；角色元数据与 Case 列表并行加载、各自填充，互不阻塞
  void agentTeamsApi
    .getRoleLabels()
    .then((metadata) => {
      roleMetadata.value = metadata
      roomPreferences.setServerManagerName(metadata.manager?.display_name)
    })
    .catch(() => { roleMetadata.value = {} })
  // 外部入口深链（如项目详情页会话「打开」）：?room=<room_id> 或 ?case=<case_id> 直达目标房间/Case；
  // 带深链时不再自动选中首个会话，列表加载完成后按 query 选中。
  const roomQuery = typeof route.query.room === 'string' ? route.query.room.trim() : ''
  const caseQuery = typeof route.query.case === 'string' ? route.query.case.trim() : ''
  void loadCases(!(roomQuery || caseQuery)).then(() => {
    if (roomQuery) void selectRoom(roomQuery)
    else if (caseQuery) void selectCase(caseQuery)
  })
  startPolling()
  narrowMedia = window.matchMedia('(max-width: 1024px)')
  syncViewportMode()
  narrowMedia.addEventListener('change', syncViewportMode)
  document.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('agentteams-room-membership-changed', handleRoomMembershipChanged)
})
onBeforeUnmount(() => {
  clearLocalTyping()
  if (typingNowTimer !== null) {
    clearInterval(typingNowTimer)
    typingNowTimer = null
  }
  stopPolling()
  stopEventStream()
  cancelAnimationFrame(listScrollFrame)
  narrowMedia?.removeEventListener('change', syncViewportMode)
  document.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('agentteams-room-membership-changed', handleRoomMembershipChanged)
})
</script>

<template>
  <main class="room-page">
    <NAlert v-if="!loading && !available" type="info" title="AgentTeams 尚未接通" :show-icon="true">
      配置 AgentTeams Bridge 后，这里会显示真实的团队协作房间。
    </NAlert>
    <div v-else class="room-layout" :class="{ 'is-sidebar-collapsed': !isNarrowViewport && desktopSidebarCollapsed }">
      <NAlert
        v-if="(selectedCaseId || selectedRoomId) && !eventStreamHealthy && eventStreamFailures >= 2"
        type="warning"
        title="实时事件流未连接"
        :show-icon="true"
        class="room-stream-alert"
      >
        页面会继续使用事件轮询；若持续出现，请检查 Bridge SSE 服务和网络。
      </NAlert>
      <nav
        v-if="!isNarrowViewport"
        class="room-sidebar-rail"
        aria-label="协作房间快捷切换"
        :inert="!desktopSidebarCollapsed"
      >
        <NTooltip trigger="hover" placement="right">
          <template #trigger>
            <NButton
              ref="sidebarToggleRef"
              tertiary
              circle
              size="small"
              aria-label="展开房间列表"
              @click="toggleDesktopSidebar"
            >
              <template #icon><NIcon><MenuOutline /></NIcon></template>
            </NButton>
          </template>
          展开房间列表
        </NTooltip>
        <div class="room-sidebar-rail__divider" aria-hidden="true"></div>
        <div class="room-sidebar-rail__cases" role="listbox" aria-label="最近协作房间">
          <NTooltip v-for="entry in collapsedRailEntries" :key="entry.key" trigger="hover" placement="right">
            <template #trigger>
              <button
                type="button"
                class="room-sidebar-rail__case"
                :class="{ 'is-active': isEntryActive(entry) }"
                role="option"
                :aria-selected="isEntryActive(entry)"
                :aria-label="`切换到房间：${entry.title}`"
                @click="selectEntry(entry)"
              >
                <span class="room-sidebar-rail__avatar" aria-hidden="true">{{ entry.title.trim().charAt(0) || '协' }}</span>
                <span class="room-sidebar-rail__status" :class="`is-${entry.category}`"></span>
              </button>
            </template>
            <span>{{ entry.title }}</span>
            <span> · {{ ROOM_CATEGORY_LABELS[entry.category] }}</span>
          </NTooltip>
          <span v-if="!loading && !collapsedRailEntries.length" class="room-sidebar-rail__empty" aria-label="暂无协作房间">
            <NIcon :size="20"><FileTrayOutline /></NIcon>
          </span>
        </div>
        <NTooltip trigger="hover" placement="right">
          <template #trigger>
            <NButton tertiary circle size="small" aria-label="新建协作房间" @click="startNewRoom">
              <template #icon><NIcon><AddOutline /></NIcon></template>
            </NButton>
          </template>
          新建房间
        </NTooltip>
      </nav>

      <div v-if="isNarrowViewport" class="room-topbar">
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton
              ref="sidebarToggleRef"
              tertiary
              size="small"
              aria-label="展开房间列表"
              @click="openSidebar"
            >
              <template #icon><NIcon><MenuOutline /></NIcon></template>
              <span>房间列表</span>
            </NButton>
          </template>
          展开房间列表
        </NTooltip>
      </div>
      <aside
        ref="sidebarRef"
        class="room-sidebar"
        :class="{ 'is-open': sidebarOpen }"
        :inert="(isNarrowViewport && !sidebarOpen) || (!isNarrowViewport && desktopSidebarCollapsed)"
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
            <NButton type="primary" size="small" :loading="creatingRoom" @click="startNewRoom">
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
            <NTooltip v-else trigger="hover">
              <template #trigger>
                <NButton tertiary circle size="small" aria-label="收起房间列表" @click="toggleDesktopSidebar">
                  <template #icon><NIcon><ChevronBackOutline /></NIcon></template>
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
          <div class="cygnusx-segmented-toggle room-filter-chips" role="group" aria-label="按状态筛选 Case">
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
            <template v-if="loading && !sidebarEntries.length">
              <div v-for="index in 4" :key="`skeleton-${index}`" class="case-entry case-entry--skeleton" aria-hidden="true">
                <span class="case-entry__skeleton-line case-entry__skeleton-line--title"></span>
                <span class="case-entry__skeleton-line case-entry__skeleton-line--meta"></span>
              </div>
            </template>
            <NEmpty v-else-if="!filteredEntries.length" size="small" class="room-sidebar__empty">
              <template #icon><NIcon :size="36" aria-hidden="true"><FileTrayOutline /></NIcon></template>
              <template #default>
                <p class="room-sidebar__empty-title">{{ sidebarEntries.length ? '没有匹配的房间' : '还没有协作房间' }}</p>
                <p v-if="!sidebarEntries.length" class="room-sidebar__empty-desc">在下方输入需求，回车即可开始协作会话</p>
              </template>
              <template v-if="!sidebarEntries.length" #extra>
                <NButton text type="primary" size="small" @click="focusComposer">去下方输入需求</NButton>
              </template>
            </NEmpty>
            <button
              v-for="entry in filteredEntries"
              :key="entry.key"
              type="button"
              class="case-entry cygnusx-selectable-card"
              :class="{ active: isEntryActive(entry) }"
              role="option"
              :aria-selected="isEntryActive(entry)"
              @click="selectEntry(entry)"
            >
              <span class="case-entry__avatar" aria-hidden="true">{{ entry.title.trim().charAt(0) || '协' }}</span>
              <span class="case-entry__body">
                <span class="case-entry__intent" :title="entry.tooltip">{{ entry.title }}</span>
                <!-- 缺口：房间/Case 数据模型无最后一条消息预览字段，有数据前不渲染预览行 -->
              </span>
              <span class="case-entry__side">
                <NTooltip trigger="hover">
                  <template #trigger>
                    <span
                      class="case-entry__status-dot"
                      :class="`is-${entry.category}`"
                      :aria-label="`状态：${ROOM_CATEGORY_LABELS[entry.category]}`"
                    ></span>
                  </template>
                  {{ entry.kind === 'room' && !entry.roomItem?.case_id ? '会话中 · 尚未立项' : `${ROOM_CATEGORY_LABELS[entry.category]}${entry.caseItem ? ` · ${formatAgentTeamsStatus(entry.caseItem.status)}` : ''}` }}
                </NTooltip>
                <span class="case-entry__time" :title="formatRoomFullTime(entry.updatedAt)">{{ formatRoomRelativeTime(entry.updatedAt) }}</span>
                <!-- 删除入口对两类条目开放：旧 Case 房间走 Case 删除，新房间实体走房间删除（后端串联清掉已绑定 Case） -->
                <NPopconfirm
                  positive-text="删除"
                  negative-text="取消"
                  :positive-button-props="{ type: 'error', size: 'small', loading: entry.caseItem ? deletingCaseId === entry.caseItem.case_id : deletingRoomId === entry.roomItem?.room_id }"
                  :negative-button-props="{ size: 'small' }"
                  @positive-click="deleteSidebarEntry(entry)"
                >
                  <template #trigger>
                    <span
                      class="case-entry__delete"
                      role="button"
                      :aria-label="`删除房间：${entry.title}`"
                      @click.stop
                    ><NIcon :size="13" aria-hidden="true"><TrashOutline /></NIcon></span>
                  </template>
                  删除该协作房间？本聊天窗口的所有内容将会被清除（含全部对话记录{{ entry.caseItem || entry.roomItem?.case_id ? '、已绑定 Case 及其审计记录' : '' }}），且不可恢复。
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

      <section class="room-main">
        <div v-if="!hasActiveRoom" class="room-guide">
          <span class="room-guide__logo" aria-hidden="true"><NIcon :size="34"><SparklesOutline /></NIcon></span>
          <h1 class="room-guide__title">和你的生物信息团队聊聊</h1>
          <p class="room-guide__lead">描述你的生物信息分析问题，生物信息部门经理会分解任务，安排合适的专业成员协作完成；关键步骤由你审批把关，也可以从左侧选择已有房间继续协作。</p>
          <p class="room-guide__note">协作室支持流程调用、结果分析与多轮协作；涉及真实计算时，关键步骤需人工审批。</p>
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
              <h2 class="case-header__title">{{ headerTitle }}</h2>
              <!-- 未立项房间：轻量会话头，进度条待立项确认后出现 -->
              <p v-if="isUnboundRoom" class="case-header__meta">
                <span class="case-header__room-hint">尚未立项 · 描述需求即可开始，确认立项后这里会展示协作进度</span>
              </p>
              <p v-else class="case-header__meta">
                <NTooltip v-if="requesterRef" trigger="hover">
                  <template #trigger>
                    <span class="case-header__requester">
                      <span class="case-header__requester-avatar" aria-hidden="true">{{ requesterInitial }}</span>
                      发起人 {{ requesterDisplayName }}
                    </span>
                  </template>
                  发起人 ID：{{ requesterRef }}
                </NTooltip>
                <span v-else-if="requesterDisplayName" class="case-header__requester">
                  <span class="case-header__requester-avatar" aria-hidden="true">{{ requesterInitial }}</span>
                  发起人 {{ requesterDisplayName }}
                </span>
                <span v-if="createdAtText">创建于 <time :title="createdAtFull">{{ createdAtText }}</time></span>
                <span v-if="updatedAtText">更新于 <time :title="updatedAtFull">{{ updatedAtText }}</time></span>
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
            <div class="case-header__actions">
              <NButton
                v-if="selectedRoomId && roomDetail?.role !== 'invited'"
                size="small"
                secondary
                aria-label="重命名协作室"
                @click="openRenameRoom"
              >
                <template #icon><NIcon><PencilOutline /></NIcon></template>
                重命名
              </NButton>
              <div class="room-model-control">
                <span class="room-model-control__label">模型</span>
                <NTooltip trigger="hover">
                  <template #trigger>
                    <NDropdown
                      v-if="modelOptions.length"
                      :options="modelMenuOptions"
                      trigger="click"
                      @select="handleRoomModelSwitch"
                    >
                      <NButton
                        size="small"
                        secondary
                        class="room-model-trigger"
                        aria-label="选择协作室模型"
                        :disabled="sendingMessage"
                      >
                        <span class="room-model-trigger__name">{{ selectedModelName }}</span>
                        <NIcon size="14" aria-hidden="true"><CaretDownOutline /></NIcon>
                      </NButton>
                    </NDropdown>
                    <NTag v-else size="small" round :bordered="false" type="info">{{ selectedModelName }}</NTag>
                  </template>
                  当前模型：{{ selectedModelName }}；切换后仅影响后续回复
                </NTooltip>
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
              <NButton v-if="roomDetail?.role === 'mine' && selectedRoomId" size="small" secondary @click="inviteVisible = true">
                邀请成员
              </NButton>
              <NButton v-else-if="roomDetail?.role === 'invited' && selectedRoomId" size="small" secondary @click="leaveCurrentRoom">
                离开协作室
              </NButton>
            </div>
          </header>

          <div v-if="roomViewMode === 'element' && elementRoomUrl" class="room-element">
            <div class="room-element__toolbar">
              <span class="room-element__hint">
                {{ elementSessionError || (elementSessionRoomId ? 'Element 已使用当前账号免登录，可直接查看与发言。' : 'Element 直接连接 Matrix 房间，需使用 Matrix 账号登录后方可发言。') }}
              </span>
              <div class="room-element__actions">
                <NButton v-if="elementSessionError" size="small" tertiary :loading="elementSessionLoading" @click="ensureElementSession(true)">
                  重试
                </NButton>
                <NButton size="small" tertiary tag="a" :href="elementShimUrl || elementRoomUrl" target="_blank" rel="noopener noreferrer">
                  在新标签页打开
                </NButton>
              </div>
            </div>
            <div v-if="elementSessionLoading" class="room-element__status">正在建立 Element 会话…</div>
            <div v-else-if="elementSessionError" class="room-element__status is-error">{{ elementSessionError }}</div>
            <iframe
              v-else
              :key="elementShimUrl || elementRoomUrl"
              class="room-element__frame"
              :src="elementShimUrl || elementRoomUrl"
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

              <!-- 收起的底层技术事件：固定在消息流顶部，避免压在 Manager 回复后打断对话节奏。 -->
              <details v-if="collapsedMessages.length" class="room-collapsed" :open="roomPreferences.settings.expandTechnicalEvents">
                <summary>底层任务事件（{{ collapsedMessages.length }} 条）</summary>
                <div v-for="item in collapsedMessages" :key="item.id" class="room-collapsed__line">
                  <span>{{ item.content }}</span>
                  <time class="tl-node__time" :title="formatMessageFullTime(item.id)">{{ formatMessageTime(item.id) }}</time>
                </div>
              </details>

              <!-- 新 Case 的一次性初始化：固定在消息区顶部，完成或跳过后立即退出消息流。 -->
              <div v-if="showOnboarding" class="speech onboarding" aria-live="polite">
                <span class="room-avatar onboarding__avatar" aria-hidden="true">{{ roomPreferences.managerLabel.charAt(0) }}</span>
                <div class="speech__main">
                  <div class="speech__head">
                    <span class="speech__name onboarding__name">{{ roomPreferences.managerLabel }}</span>
                    <span v-if="roomPreferences.managerRoleSuffix" class="speech__role"> · {{ roomPreferences.managerRoleSuffix }}</span>
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
                    <time class="tl-node__time" :title="formatMessageFullTime(block.message.id)">{{ formatMessageTime(block.message.id) }}</time>
                  </div>
                </div>

                <div v-else-if="block.type === 'speech'" class="speech" :class="{ 'speech--user': block.message.isUser, 'speech--report': !!block.message.managerReport, 'speech--ask': !!block.message.askRequest, 'speech--handoff': !!block.message.handoff, 'speech--assessment': !!block.message.changeAssessment }">
                  <span class="room-avatar" :style="{ background: block.message.sender.color }">{{ block.message.sender.avatar }}</span>
                  <div class="speech__main">
                    <div class="speech__head">
                      <span class="speech__name" :style="{ color: block.message.sender.color }">{{ block.message.sender.name }}</span>
                      <span v-if="block.message.routedBy === 'manager_triage'" class="speech__route-tag">经理分诊</span>
                      <span v-if="block.message.sender.role === 'manager' && !block.message.isUser && roomPreferences.managerRoleSuffix" class="speech__role"> · {{ roomPreferences.managerRoleSuffix }}</span>
                      <span v-else-if="block.message.sender.archetype && !block.message.isUser" class="speech__role"> · {{ block.message.sender.archetype }}</span>
                      <time class="speech__time" :title="formatMessageFullTime(block.message.id)">{{ formatMessageTime(block.message.id) }}</time>
                    </div>
                    <div
                      v-if="block.message.thought || block.message.streaming"
                      class="room-thought"
                    >
                      <button
                        type="button"
                        class="room-thought__toggle"
                        :aria-expanded="isThoughtExpanded(block.message.id)"
                        @click="toggleThought(block.message.id)"
                      >
                        <span class="room-thought__label">
                          {{ block.message.streaming ? '✨ 思考中…' : '🔍 思考过程' }}
                        </span>
                        <span class="room-thought__arrow" :class="{ 'is-expanded': isThoughtExpanded(block.message.id) }">▾</span>
                      </button>
                      <transition name="room-thought-expand">
                        <div v-show="isThoughtExpanded(block.message.id)" class="room-thought__content">
                          {{ block.message.thought || '模型正在组织回复…' }}
                        </div>
                      </transition>
                    </div>
                    <div v-if="block.message.toolCalls?.length" class="speech__tool-calls">
                      <RoomMcpToolCard
                        v-for="toolCall in block.message.toolCalls"
                        :key="toolCall.id"
                        :tool="{ name: toolCall.name, status: toolCall.status, durationMs: toolCall.durationMs }"
                        :debug-trace="speechToolDebugTrace(toolCall)"
                      />
                    </div>
                    <RoomProposalCard
                      v-if="block.message.proposal"
                      :proposal="block.message.proposal"
                      :role-labels="effectiveRoleMetadata.role_labels || {}"
                      @decision="(payload) => submitProposalDecision(block.message, payload.decision, payload.followupMode)"
                    />
                    <RouteDecisionCard
                      v-if="block.message.routeDecision && !block.message.askRequest"
                      :decision="block.message.routeDecision"
                    />
                    <RoomRouteTransitionCard
                      v-if="block.message.routeTransition"
                      :transition="block.message.routeTransition"
                    />
                    <div v-else-if="block.message.dispatch" class="speech__bubble room-handoff-card room-dispatch-card">
                      <div class="room-handoff-card__title">任务分派</div>
                      <div class="room-dispatch-card__target">分派给 {{ block.message.dispatch.targetName }}</div>
                      <div v-if="block.message.dispatch.skillName" class="room-handoff-card__meta">技能：{{ block.message.dispatch.skillName }}</div>
                      <div v-if="block.message.dispatch.objective" class="room-dispatch-card__objective"><MarkdownRenderer :content="block.message.dispatch.objective" /></div>
                    </div>
                    <div v-else-if="block.message.handoff" class="speech__bubble room-handoff-card">
                      <div class="room-handoff-card__title">已交接给 {{ effectiveRoleMetadata.role_labels?.[block.message.handoff.toAgentId]?.name || 'Manager' }}</div>
                      <div class="room-handoff-card__summary">{{ block.message.content }}</div>
                      <div v-if="block.message.handoff.workItemIds.length" class="room-handoff-card__meta">工作项：{{ block.message.handoff.workItemIds.join('、') }}</div>
                      <div v-if="block.message.handoff.risks.length" class="room-handoff-card__section room-handoff-card__section--risk">风险：{{ block.message.handoff.risks.join('；') }}</div>
                      <div v-if="block.message.handoff.artifactRefs.length" class="room-handoff-card__section">产物：{{ block.message.handoff.artifactRefs.join('、') }}</div>
                    </div>
                    <div v-else-if="block.message.changeAssessment" class="speech__bubble room-assessment-card">
                      <div class="room-assessment-card__title">变更影响评估</div>
                      <MarkdownRenderer :content="block.message.changeAssessment.conclusion || block.message.content" />
                      <div v-if="block.message.changeAssessment.workItemIds.length" class="room-assessment-card__meta">受影响工作项：{{ block.message.changeAssessment.workItemIds.join('、') }}</div>
                      <div v-if="block.message.changeAssessment.risks.length" class="room-assessment-card__section room-assessment-card__section--risk">风险：{{ block.message.changeAssessment.risks.join('；') }}</div>
                      <div v-if="block.message.changeAssessment.decisionOptions.length" class="room-assessment-card__options" aria-label="可选变更决策">
                        <NButton
                          v-for="option in block.message.changeAssessment.decisionOptions"
                          :key="option"
                          size="small"
                          secondary
                          :type="option === 'cancel' ? 'error' : 'default'"
                          :loading="changeDecisionPending === `${block.message.changeAssessment.workItemIds.join(',')}:${option}`"
                          :disabled="!!changeDecisionPending"
                          @click="submitChangeDecision(block.message.changeAssessment, option as 'resume' | 'replan' | 'branch' | 'cancel')"
                        >{{ option === 'resume' ? '继续原计划' : option === 'replan' ? '按建议重规划' : option === 'branch' ? '新建并行支线' : '终止该支线' }}</NButton>
                      </div>
                    </div>
                    <div v-else-if="block.message.managerReport" class="speech__bubble manager-report">
                      <div v-if="block.message.managerReport.hardGate" class="manager-report__hardgate">
                        ⚠ {{ formatHardGate(block.message.managerReport.hardGate) }}
                      </div>
                      <div v-if="block.message.managerReport.conclusion" class="manager-report__conclusion">
                        <MarkdownRenderer :content="block.message.managerReport.conclusion" />
                      </div>
                      <details v-if="block.message.managerReport.recommendations.length" class="manager-report__section manager-report__section--collapsible">
                        <summary class="manager-report__label">建议 <span class="manager-report__count">{{ block.message.managerReport.recommendations.length }}</span></summary>
                        <ul class="manager-report__list">
                          <li v-for="(item, index) in block.message.managerReport.recommendations" :key="`rec-${index}`">{{ item }}</li>
                        </ul>
                      </details>
                      <details v-if="block.message.managerReport.risks.length" class="manager-report__section manager-report__section--collapsible">
                        <summary class="manager-report__label manager-report__label--risk">风险 <span class="manager-report__count">{{ block.message.managerReport.risks.length }}</span></summary>
                        <ul class="manager-report__list">
                          <li v-for="(item, index) in block.message.managerReport.risks" :key="`risk-${index}`">{{ item }}</li>
                        </ul>
                      </details>
                      <details v-if="block.message.managerReport.evidenceRefs.length" class="manager-report__section manager-report__section--collapsible">
                        <summary class="manager-report__label manager-report__label--evidence">证据 <span class="manager-report__count">{{ block.message.managerReport.evidenceRefs.length }}</span></summary>
                        <ul class="manager-report__list manager-report__list--evidence">
                          <li v-for="(item, index) in block.message.managerReport.evidenceRefs" :key="`ev-${index}`">{{ item }}</li>
                        </ul>
                      </details>
                      <details v-if="block.message.managerReport.proposedSubmission" class="manager-report__submission">
                        <summary class="manager-report__label manager-report__label--submission">执行工单</summary>
                        <pre class="manager-report__json">{{ JSON.stringify(block.message.managerReport.proposedSubmission, null, 2) }}</pre>
                      </details>
                    </div>
                    <div v-else-if="!block.message.hideContent" class="speech__bubble" :class="{ 'speech__bubble--streaming': block.message.streaming }">
                      <MarkdownRenderer v-if="!block.message.isUser && block.message.content" :content="block.message.content" />
                      <span v-else class="speech__mentions" v-html="formatMentions(block.message.content)" />
                      <span v-if="block.message.streaming && !block.message.content" class="room-streaming-label">正在生成回复…</span>
                      <span v-if="block.message.streaming && block.message.content" class="room-streaming-caret" aria-label="正在生成"></span>
                    </div>
                    <AskUserCard
                      v-if="block.message.askRequest"
                      :ask="block.message.askRequest"
                      @submit="(answers: string[], objectReference?: AskUserObjectReference) => submitRoomAskAnswers(block.message.askRequest, answers, objectReference)"
                    />
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
                    <time class="worker-card__time" :title="formatMessageFullTime(block.body?.id || block.intro?.id || block.key)">{{ formatMessageTime(block.body?.id || block.intro?.id || block.key) }}</time>
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
                  <div v-if="block.steps.length" class="worker-card__tools">
                    <RoomMcpToolCard
                      v-for="step in block.steps"
                      :key="step.id"
                      :tool="step.tool"
                      :count="step.count"
                      :debug-trace="step.details[0]?.debugTrace"
                    />
                  </div>
                  <ul v-if="block.extraProgress.length" class="worker-card__steps">
                    <li v-for="item in block.extraProgress" :key="item.id" class="worker-step is-plain">
                      <span>{{ item.content }}</span>
                      <details v-if="debugEnabled && item.debugTrace" class="worker-card__debug">
                        <summary>调试详情</summary>
                        <code>{{ formatDebugTrace(item.debugTrace) }}</code>
                      </details>
                    </li>
                  </ul>
                  <div v-if="block.body" class="worker-card__body"><MarkdownRenderer :content="block.body.content" /></div>
                  <MessageArtifactGallery v-if="block.body" :artifacts="block.body.artifacts" />
                </section>
              </template>

              <section v-if="approvalCard" class="room-approval-card" :class="`is-${approvalCard.state}`" aria-live="polite">
                <header class="room-approval-card__head">
                  <span class="room-approval-card__title">人工审批</span>
                  <span v-if="approvalCard.terminalText" class="room-approval-card__terminal">{{ approvalCard.terminalText }}</span>
                  <time v-if="approvalCard.time" class="room-approval-card__time" :title="approvalCard.fullTime">{{ approvalCard.time }}</time>
                </header>
                <p v-if="approvalCard.summary" class="room-approval-card__summary">{{ approvalCard.summary }}</p>
                <p v-if="approvalCard.impact" class="room-approval-card__impact">{{ approvalCard.impact }}</p>
                <div v-if="approvalCard.state === 'pending' && canApprove" class="room-approval-card__actions">
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
                <div v-else-if="approvalCard.state === 'preparing'" class="room-approval-card__actions">
                  <NButton secondary size="small" :loading="approvalRefreshing" @click="refreshApprovalState">刷新状态</NButton>
                </div>
                <div v-else-if="approvalCard.state === 'retry'" class="room-approval-card__actions">
                  <NButton type="primary" size="small" :loading="retrying" @click="retryFailedCase">按冻结计划重试</NButton>
                </div>
              </section>

              <div v-if="managerTyping" class="room-typing" role="status" aria-live="polite">
                <span class="room-typing__dots" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="room-typing__label">{{ typingAgentName }} 正在输入…</span>
              </div>

            </div>
          </div>
          <NButton v-if="!listAtBottom" class="room-scroll-bottom" size="small" secondary round @click="scrollListToBottom">回到底部</NButton>
          </div>
          </template>
        </template>

        <div
          v-if="!hasActiveRoom || roomViewMode === 'stream' || !elementRoomUrl"
          class="room-composer"
        >
          <KimiChatInput
            ref="composerRef"
            v-model="draftMessage"
            room-mode
            :room-mention-agents="roomMentionAgents"
            class="room-composer__input"
            :placeholder="roomInputPlaceholder"
            :disabled="!roomInputEnabled || sendingMessage"
            :send-loading="sendingMessage"
            :maxlength="4000"
            @send="handleComposerSend"
          />
        </div>
      </section>
      <NModal
        v-model:show="renameVisible"
        preset="card"
        title="重命名协作室"
        :style="{ width: 'min(92vw, 440px)' }"
        :mask-closable="!renamingRoom"
      >
        <NInput
          v-model:value="renameTitle"
          maxlength="200"
          show-count
          autofocus
          placeholder="例如：小鼠单细胞质量控制"
          @keyup.enter="renameCurrentRoom"
        />
        <div class="room-modal-actions">
          <NButton secondary :disabled="renamingRoom" @click="renameVisible = false">取消</NButton>
          <NButton type="primary" :loading="renamingRoom" :disabled="!renameTitle.trim()" @click="renameCurrentRoom">保存名称</NButton>
        </div>
      </NModal>
      <NModal v-model:show="inviteVisible" preset="card" title="邀请协作室成员" style="width: min(440px, 92vw)">
        <NInput v-model:value="inviteQuery" clearable placeholder="输入用户名或昵称" @update:value="searchInviteUsers" />
        <NSpin :show="inviteLoading">
          <NEmpty v-if="!inviteResults.length" description="输入关键字搜索用户" style="padding: 28px 0" />
          <div v-else class="invite-results">
            <div v-for="user in inviteResults" :key="user.id" class="invite-result">
              <span>{{ user.nickname }}</span>
              <NButton size="small" type="primary" :loading="invitingUserId === user.id" @click="inviteUser(user.id)">邀请</NButton>
            </div>
          </div>
        </NSpin>
        <div class="room-member-list">
          <strong>当前成员</strong>
          <div v-for="member in roomMembers" :key="member.id" class="invite-result">
            <span>{{ member.user_id }}<small> · {{ member.role === 'owner' ? '房主' : member.status === 'pending' ? '待接受' : member.status === 'declined' ? '已拒绝' : '成员' }}</small></span>
            <NButton
              v-if="member.role !== 'owner'"
              size="small"
              tertiary
              type="error"
              :loading="memberActionUserId === member.user_id"
              @click="manageRoomMember(member)"
            >{{ member.status === 'pending' ? '撤销邀请' : member.status === 'declined' ? '重新邀请' : '移除' }}</NButton>
          </div>
        </div>
      </NModal>
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

    <NModal v-model:show="projectPickerVisible" preset="card" title="为协作 Case 选择项目" :style="{ width: 'min(92vw, 520px)' }" :mask-closable="!projectPickerSaving">
      <NForm label-placement="top" @submit.prevent="confirmProjectBinding">
        <NFormItem label="既有项目">
          <select v-model="selectedProjectId" class="room-project-select" :disabled="projectPickerLoading || projectPickerSaving">
            <option value="">创建新项目</option>
            <option v-for="project in projectOptions" :key="project.id" :value="project.id">{{ project.name }}（{{ project.slug }}）</option>
          </select>
        </NFormItem>
        <NFormItem v-if="!selectedProjectId" label="新项目名称" required>
          <NInput v-model:value="newProjectName" maxlength="200" placeholder="例如：小鼠单细胞 3v3" />
        </NFormItem>
        <p class="room-project-hint">Case 将创建一个 agentteams-case 运行目录，产物会出现在该项目的 output/。</p>
        <div class="room-modal-actions">
          <NButton :disabled="projectPickerSaving" @click="projectPickerVisible = false; pendingProjectCreate = null">取消</NButton>
          <NButton type="primary" attr-type="submit" :loading="projectPickerSaving">继续创建 Case</NButton>
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
.room-layout { position: relative; display: grid; grid-template-areas: 'sidebar main'; grid-template-columns: minmax(280px, 320px) minmax(0, 1fr); gap: var(--space-xl); flex: 1; min-height: 0; transition: grid-template-columns 240ms cubic-bezier(0.2, 0.8, 0.2, 1), gap 240ms cubic-bezier(0.2, 0.8, 0.2, 1); }
/* 事件流告警是 grid 直接子节点但不属于任何命名区域：必须显式占满整行，
   否则会被自动摆进 sidebar 列（收起时仅 72px），文字逐字竖排塌缩。 */
.room-stream-alert { grid-column: 1 / -1; }
.room-layout.is-sidebar-collapsed { grid-template-columns: 72px minmax(0, 1fr); gap: var(--space-md); }
.room-sidebar-rail { grid-area: sidebar; display: flex; min-height: 0; flex-direction: column; align-items: center; gap: var(--space-md); padding: var(--space-md) var(--space-sm); border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); opacity: 0; pointer-events: none; transform: translateX(-8px) scale(0.98); transition: opacity 150ms ease-out, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1); }
.room-layout.is-sidebar-collapsed .room-sidebar-rail { opacity: 1; pointer-events: auto; transform: translateX(0) scale(1); transition-delay: 70ms; }
.room-sidebar-rail__divider { width: 100%; height: 1px; background: var(--neutral-border); }
.room-sidebar-rail__cases { display: grid; width: 100%; min-height: 0; flex: 1; align-content: start; justify-items: center; gap: var(--space-md); overflow-y: auto; padding: var(--space-xs) 0; scrollbar-width: none; }
.room-sidebar-rail__cases::-webkit-scrollbar { display: none; }
.room-sidebar-rail__case { position: relative; display: inline-flex; width: 48px; height: 48px; align-items: center; justify-content: center; padding: 0; border: 1px solid transparent; border-radius: var(--radius-card); background: transparent; cursor: pointer; transition: border-color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out, transform var(--motion-quick) ease-out; }
.room-sidebar-rail__case:hover { background: var(--neutral-hover); transform: translateY(-1px); }
.room-sidebar-rail__case:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: 3px; }
.room-sidebar-rail__case.is-active { border-color: color-mix(in srgb, var(--arco-primary) 42%, var(--neutral-border)); background: var(--arco-primary-light); }
.room-sidebar-rail__avatar { display: inline-flex; width: 40px; height: 40px; align-items: center; justify-content: center; border-radius: var(--radius-card); background: var(--neutral-fill-2); color: var(--neutral-text-2); font-size: var(--font-card-title-size); font-weight: 600; }
.room-sidebar-rail__case.is-active .room-sidebar-rail__avatar { background: var(--arco-primary); color: var(--text-on-primary); }
.room-sidebar-rail__status { position: absolute; right: 1px; bottom: 1px; width: 9px; height: 9px; border: 2px solid var(--neutral-card); border-radius: 50%; background: var(--neutral-text-3); }
.room-sidebar-rail__status.is-active { background: var(--arco-primary); }
.room-sidebar-rail__status.is-approval { background: var(--arco-warning); }
.room-sidebar-rail__status.is-done { background: var(--arco-success); }
.room-sidebar-rail__status.is-failed { background: var(--arco-danger); }
.room-sidebar-rail__empty { display: inline-flex; width: 48px; height: 48px; align-items: center; justify-content: center; border: 1px dashed var(--neutral-border); border-radius: var(--radius-card); color: var(--neutral-text-3); }

/* ===== 左栏：协作室切换器（工具行 + 搜索 + 过滤 chips + Case 列表，Surface Card 材质） ===== */
.room-sidebar { grid-area: sidebar; display: flex; min-height: 0; flex-direction: column; gap: var(--space-lg); overflow: hidden; padding: var(--space-2xl); border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); opacity: 1; transform: translateX(0); transition: opacity 150ms ease-out 70ms, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1) 70ms; }
.room-layout.is-sidebar-collapsed .room-sidebar { opacity: 0; pointer-events: none; transform: translateX(-8px) scale(0.98); transition-delay: 0ms; }
.room-sidebar__toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-sm); }
.room-sidebar__heading { color: var(--neutral-text-1); font-size: var(--font-section-size); font-weight: var(--font-section-weight); line-height: var(--font-section-height); letter-spacing: var(--font-section-spacing); }
.room-sidebar__actions { display: flex; align-items: center; gap: var(--space-xs); }
.room-sidebar__tools { display: grid; gap: var(--space-sm); }
/* 复用全局 .cygnusx-segmented-toggle 胶囊分段切换器；本处仅做容器级布局覆盖：禁止折行，
   溢出时容器自身横向滚动（隐藏滚动条但保持可滚），每枚胶囊不收缩、计数永不被截断（§5.4/§7.1） */
.room-filter-chips { display: flex; max-width: 100%; min-width: 0; flex-wrap: nowrap; align-self: stretch; overflow: hidden auto; scrollbar-width: none; }
.room-filter-chips::-webkit-scrollbar { display: none; }
.room-filter-chips button { display: inline-flex; flex: 0 0 auto; align-items: center; gap: var(--space-xs); white-space: nowrap; }
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

/* Case 列表项：可选择卡片协议（§5.2）——左缘 4px 状态线由全局 .cygnusx-selectable-card::before 提供，
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
.case-entry__side { position: relative; display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: var(--space-xs); }
.case-entry__time { overflow: hidden; color: var(--neutral-text-3); font-size: var(--font-caption-size); text-overflow: ellipsis; white-space: nowrap; transition: opacity var(--motion-quick) ease-out; }
.case-entry__status-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; }
.case-entry__status-dot.is-active { background: var(--arco-primary); animation: room-status-pulse 2.4s ease-in-out infinite; }
.case-entry__status-dot.is-approval { background: var(--arco-warning); }
.case-entry__status-dot.is-done { background: var(--arco-success); }
.case-entry__status-dot.is-failed { background: var(--arco-danger); }
/* 删除入口：悬停/聚焦列表项时原位替换时间戳显现（绝对定位，不占布局空间），避免常态视觉噪音与选中时的布局跳动 */
.case-entry__delete { position: absolute; right: 0; bottom: 0; display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 6px; color: var(--neutral-text-3); cursor: pointer; opacity: 0; visibility: hidden; transition: opacity var(--motion-quick) ease-out, color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out, visibility var(--motion-quick) ease-out; }
.case-entry:hover .case-entry__delete, .case-entry:focus-within .case-entry__delete { opacity: 1; visibility: visible; }
.case-entry:hover .case-entry__time, .case-entry:focus-within .case-entry__time { opacity: 0; }
.case-entry__delete:hover { background: var(--neutral-hover); color: var(--arco-danger); }
@keyframes room-status-pulse { 0% { box-shadow: 0 0 0 0 var(--arco-primary-light); } 70% { box-shadow: 0 0 0 4px var(--arco-primary-light); } 100% { box-shadow: 0 0 0 0 var(--arco-primary-light); } }
/* 列表首载骨架屏：布局先行，数据到达后原位填充 */
.case-entry--skeleton { flex-direction: column; align-items: stretch; cursor: default; }
.case-entry--skeleton:hover { border-color: var(--neutral-border); background: var(--neutral-card); }
.case-entry__skeleton-line { display: block; height: 12px; border-radius: 6px; background: var(--neutral-hover); animation: room-pulse 1.6s ease-in-out infinite; }
.case-entry__skeleton-line--title { width: 72%; }
.case-entry__skeleton-line--meta { width: 44%; height: 10px; }

/* ===== 右栏主体：与左栏同规格 Surface Card，承载欢迎区、会话流与输入区 ===== */
.room-main { grid-area: main; display: flex; min-height: 0; flex-direction: column; overflow: hidden; border: 1px solid var(--neutral-border); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); }
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
.case-header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md) var(--space-xl); flex-wrap: wrap; padding: var(--space-sm) var(--space-2xl); border-bottom: 1px solid var(--neutral-border); }
.case-header__info { min-width: 0; }
.case-header__title { margin: 0; overflow: hidden; color: var(--neutral-text-1); font-size: var(--font-card-title-size); font-weight: 600; line-height: var(--font-card-title-height); text-overflow: ellipsis; white-space: nowrap; }
.case-header__meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs) var(--space-sm); margin: var(--space-xs) 0 0; color: var(--neutral-text-3); font-size: var(--font-caption-size); line-height: var(--font-caption-height); }
/* 元信息单行分隔：发起人 X · 创建于 T（· 更新于 T） */
.case-header__meta > span + span::before { margin-right: var(--space-sm); content: '·'; }
/* 未立项房间的轻量会话头引导语（进度条待立项确认后出现） */
.case-header__room-hint { color: var(--neutral-text-3); }
/* 发起人：沿用左栏房间头像体系（首字符徽标 + 品牌浅底），UUID 不直出（§5.4） */
.case-header__requester { display: inline-flex; align-items: center; gap: var(--space-xs); }
.case-header__requester-avatar { display: inline-flex; width: 20px; height: 20px; flex: 0 0 20px; align-items: center; justify-content: center; border-radius: var(--radius-sm); background: var(--arco-primary-light); color: var(--arco-primary); font-size: var(--font-caption-size); font-weight: 600; }
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
.room-approval-card { width: min(720px, calc(100% - 32px - var(--space-md))); box-sizing: border-box; padding: var(--space-lg) var(--space-xl); border: 1px solid var(--neutral-border); border-left: 3px solid var(--arco-warning); border-radius: var(--radius-card); background: var(--neutral-card); box-shadow: var(--shadow-card); }
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

/* ===== 消息流：占满主卡片可用宽度；具体消息仍由自身上限控制；scrollbar-gutter 预留滚动条位置消除水平抖动（迁移自 KimiMessageList） ===== */
.room-messages-wrap { position: relative; display: flex; flex: 1; min-height: 240px; flex-direction: column; }
.room-messages { flex: 1; min-height: 0; overflow-y: auto; padding: var(--space-xl) var(--space-2xl) var(--space-2xl); scrollbar-gutter: stable; scroll-padding-top: var(--space-xl); }
.room-scroll-bottom { position: absolute; right: var(--space-lg); bottom: var(--space-lg); z-index: 5; border: 1px solid var(--neutral-border); box-shadow: var(--shadow-card); }
.room-stream { display: grid; width: 100%; gap: var(--space-xl); align-content: start; }

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
   用户气泡右对齐实心主色、最大宽度 720px；Agent 回复列宽固定为消息区的一半（§18.1） */
.speech { display: flex; gap: var(--space-md); }
.speech--user { flex-direction: row-reverse; }
.room-avatar { display: inline-flex; width: 32px; height: 32px; flex: 0 0 32px; align-items: center; justify-content: center; border-radius: 50%; color: var(--text-on-primary); font-size: 15px; }
.room-avatar--sm { width: 26px; height: 26px; flex-basis: 26px; font-size: 13px; }
.speech__main { display: grid; min-width: 0; gap: var(--space-xs); }
.speech--user .speech__main { width: min(720px, calc(100% - 32px - var(--space-md))); max-width: min(720px, calc(100% - 32px - var(--space-md))); }
/* Agent 回复列宽钉在消息区的一半：宽屏下长回复不再铺满整行；
   窄屏用 min(480px, 可用宽度) 兜底，避免过窄。报告卡/询问卡等结构化卡片同宽，
   折叠/展开也不会发生宽度跳变。 */
.speech:not(.speech--user) .speech__main { width: max(50%, min(480px, calc(100% - 32px - var(--space-md)))); max-width: calc(100% - 32px - var(--space-md)); box-sizing: border-box; }
.speech__head { display: flex; align-items: baseline; gap: var(--space-sm); }
.speech--user .speech__head { flex-direction: row-reverse; }
.speech__name { font-size: var(--font-small-size); font-weight: 600; }
.speech__role { color: var(--neutral-text-3); font-size: var(--font-caption-size); font-weight: 400; }
.speech__route-tag { align-self: center; padding: 1px 6px; color: var(--arco-primary); background: color-mix(in srgb, var(--arco-primary) 10%, transparent); border-radius: 999px; font-size: 10px; font-weight: 600; line-height: 1.4; }
.speech__time { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.speech__bubble { padding: var(--space-md) var(--space-lg); border: 1px solid var(--neutral-border); border-radius: 4px var(--radius-card) var(--radius-card) var(--radius-card); background: var(--neutral-fill-2); color: var(--neutral-text-1); font-size: var(--font-body-size); line-height: 1.7; word-break: break-all; overflow-wrap: anywhere; white-space: pre-wrap; }
.speech--user .speech__bubble { justify-self: end; max-width: 75%; border-color: transparent; border-radius: var(--radius-card) 4px var(--radius-card) var(--radius-card); background: var(--arco-primary); color: var(--text-on-primary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.speech__bubble .mention-chip { display: inline-block; padding: 0 4px; border-radius: 4px; background: var(--arco-primary-light); color: var(--arco-primary); font-weight: 600; }
.speech--user .speech__bubble .mention-chip { background: rgba(255,255,255,0.2); color: #fff; }
.speech__bubble--streaming { border-color: color-mix(in srgb, var(--arco-primary) 26%, var(--neutral-border)); }
.room-handoff-card, .room-assessment-card { border-color: color-mix(in srgb, var(--arco-primary) 34%, var(--neutral-border)); background: color-mix(in srgb, var(--arco-primary-light) 34%, var(--neutral-fill-2)); }
.room-handoff-card__title, .room-assessment-card__title { margin-bottom: var(--space-xs); color: var(--arco-primary); font-size: var(--font-small-size); font-weight: 700; }
.room-handoff-card__summary, .room-assessment-card__meta, .room-handoff-card__meta { color: var(--neutral-text-2); font-size: var(--font-small-size); }
.room-handoff-card__section, .room-assessment-card__section { margin-top: var(--space-sm); padding-top: var(--space-sm); border-top: 1px solid var(--neutral-border); font-size: var(--font-small-size); }
.room-handoff-card__section--risk, .room-assessment-card__section--risk { color: var(--warning-text, var(--neutral-text-2)); }
.room-dispatch-card__target { color: var(--neutral-text-1); font-size: var(--font-small-size); font-weight: 600; }
.room-dispatch-card__objective { margin-top: var(--space-xs); color: var(--neutral-text-2); font-size: var(--font-small-size); line-height: var(--font-small-height); }
.room-dispatch-card__objective :deep(.md-body) { font-size: var(--font-small-size); white-space: normal; }
.room-assessment-card__options { display: flex; flex-wrap: wrap; gap: var(--space-xs); margin-top: var(--space-md); }
.room-streaming-label { color: var(--neutral-text-3); font-size: var(--font-small-size); }
.room-streaming-caret { display: inline-block; width: 2px; height: 1.1em; margin-left: 3px; vertical-align: -0.16em; background: var(--arco-primary); animation: room-streaming-caret 0.9s step-end infinite; }
@keyframes room-streaming-caret { 50% { opacity: 0; } }
.room-thought { overflow: hidden; border: 1px solid var(--neutral-border); border-radius: var(--radius-sm); background: var(--neutral-fill-1); }
.speech__tool-calls { display: flex; flex-direction: column; gap: var(--space-xs); margin-top: var(--space-xs); margin-bottom: var(--space-xs); }
.room-thought__toggle { display: flex; align-items: center; gap: var(--space-sm); width: 100%; padding: var(--space-sm) var(--space-md); border: 0; background: transparent; color: var(--neutral-text-2); cursor: pointer; font-size: var(--font-caption-size); text-align: left; transition: background-color var(--motion-quick) ease-out; }
.room-thought__toggle:hover { background: var(--neutral-hover); }
.room-thought__toggle:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: -2px; }
.room-thought__label { color: var(--arco-primary); }
.room-thought__arrow { margin-left: auto; color: var(--neutral-text-3); transition: transform var(--motion-quick) ease-out; }
.room-thought__arrow.is-expanded { transform: rotate(180deg); }
.room-thought__content { max-height: 300px; overflow-y: auto; padding: var(--space-sm) var(--space-md); border-top: 1px solid var(--neutral-border); color: var(--neutral-text-2); font-size: var(--font-small-size); font-style: italic; line-height: 1.7; white-space: pre-wrap; }
.room-thought-expand-enter-active, .room-thought-expand-leave-active { transition: opacity var(--motion-quick) ease-out, max-height var(--motion-base) ease-out; }
.room-thought-expand-enter-from, .room-thought-expand-leave-to { max-height: 0; opacity: 0; }
@media (prefers-reduced-motion: reduce) { .room-streaming-caret { animation: none; } .room-thought__arrow, .room-thought-expand-enter-active, .room-thought-expand-leave-active { transition: none; } }
/* Manager 结构化长文（分析方案）与询问工具卡片：列宽与普通 Agent 回复一致，
   统一由 .speech:not(.speech--user) .speech__main 的半宽规则钉住（§18.1.1），
   卡片折叠/展开同宽，不再单独覆盖宽度。 */
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
.manager-report__section--collapsible { gap: var(--space-sm); }
.manager-report__section--collapsible > summary { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; list-style: none; }
.manager-report__section--collapsible > summary::-webkit-details-marker { display: none; }
.manager-report__section--collapsible > summary::before { content: '▸'; color: currentColor; transition: transform var(--motion-quick) ease-out; }
.manager-report__section--collapsible[open] > summary::before { transform: rotate(90deg); }
.manager-report__count { opacity: .7; font-size: 11px; font-weight: 500; }
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
.worker-card { display: grid; gap: var(--space-sm); width: min(720px, calc(100% - 32px - var(--space-md))); box-sizing: border-box; padding: var(--space-md) var(--space-lg); border: 1px solid var(--neutral-border); border-left: 3px solid var(--neutral-border); border-radius: 4px var(--radius-card) var(--radius-card) var(--radius-card); background: var(--neutral-fill-2); }
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
.worker-card__tools { display: grid; gap: var(--space-sm); width: 100%; padding-top: var(--space-sm); border-top: 1px dashed var(--neutral-border); }
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
.worker-card__debug { width: 100%; margin-top: var(--space-xs); color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.worker-card__debug summary { width: fit-content; cursor: pointer; }
.worker-card__debug code { display: block; margin-top: var(--space-xs); overflow-wrap: anywhere; white-space: pre-wrap; }
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

/* 底部发言输入区：不跟随聊天室整列铺满，参考独立聊天输入卡的留白比例；
   表面、蓝色高亮边框、工具行与发送按钮由 KimiChatInput 的 roomMode 样式提供。 */
.room-composer { flex-shrink: 0; width: min(calc(100% - var(--space-3xl)), 1500px); margin: var(--space-lg) auto var(--space-2xl); }
.room-composer__input { width: 100%; }
.case-header__actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-sm); min-width: 0; margin-left: auto; }
.room-model-control { display: inline-flex; align-items: center; gap: var(--space-xs); min-width: 0; padding: 2px 4px 2px var(--space-sm); border: 1px solid var(--neutral-border); border-radius: var(--radius-sm); background: var(--neutral-fill-2); }
.room-model-control__label { flex: 0 0 auto; color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-model-trigger { max-width: min(220px, 24vw); min-width: 150px; justify-content: space-between; }
.room-model-trigger__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Manager 正在输入指示 */
.room-typing { display: flex; align-items: center; gap: var(--space-sm); padding: var(--space-sm) var(--space-md); color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-typing__dots { display: inline-flex; gap: 4px; }
.room-typing__dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--arco-primary); animation: room-pulse 1.6s ease-in-out infinite; }
.room-typing__dots i:nth-child(2) { animation-delay: 0.2s; }
.room-typing__dots i:nth-child(3) { animation-delay: 0.4s; }

/* 消息流 / Element 视图切换：胶囊分段样式，与全局 .cygnusx-segmented-toggle 同语言 */
.room-view-switch { display: inline-flex; gap: 2px; padding: 2px; border: 1px solid var(--neutral-border); border-radius: 999px; background: var(--neutral-fill-2); }
.room-view-switch__btn { padding: var(--space-xs) var(--space-md); border: none; border-radius: 999px; background: transparent; color: var(--neutral-text-2); font-size: var(--font-caption-size); line-height: 1.7; cursor: pointer; transition: background-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out; }
.room-view-switch__btn:hover { color: var(--neutral-text-1); }
.room-view-switch__btn:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: -2px; }
.room-view-switch__btn.is-active { background: var(--arco-primary); color: var(--text-on-primary); }
.room-element { display: flex; flex: 1; min-height: 0; flex-direction: column; }
.room-element__toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); padding: var(--space-sm) var(--space-2xl); border-bottom: 1px solid var(--neutral-border); }
.room-element__hint { color: var(--neutral-text-3); font-size: var(--font-caption-size); }
.room-element__actions { display: flex; align-items: center; gap: var(--space-sm); flex-shrink: 0; }
.room-element__status { flex: 1; min-height: 320px; display: flex; align-items: center; justify-content: center; color: var(--neutral-text-3); font-size: var(--font-caption-size); background: var(--neutral-card); }
.room-element__status.is-error { color: var(--arco-danger); }
.room-element__frame { flex: 1; min-height: 320px; width: 100%; border: none; background: var(--neutral-card); }

.room-modal-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); margin-top: var(--space-xl); }
.invite-results { display: grid; gap: var(--space-sm); margin-top: var(--space-md); }
.invite-result { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); padding: var(--space-sm); border: 1px solid var(--neutral-border); border-radius: var(--radius-sm); }
.invite-result small { color: var(--text-color-3); }
.room-member-list { display: grid; gap: var(--space-sm); margin-top: var(--space-lg); }

@keyframes room-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .worker-step.is-running .worker-step__dot { animation: none; } }
/* 减少动态：状态点用静态弱晕染替代脉冲动画（§6.3） */
@media (prefers-reduced-motion: reduce) { .case-entry__status-dot.is-active { animation: none; box-shadow: 0 0 0 3px var(--arco-primary-light); } }
@media (prefers-reduced-motion: reduce) { .case-entry__delete, .case-entry__time { transition: none; } }
@media (prefers-reduced-motion: reduce) { .room-typing__dots i { animation: none; } }

/* ≤1024px：左栏收纳为可折叠抽屉（默认收起，进入 Case 后自动收起；Esc / 遮罩点击关闭） */
@media (max-width: 1024px) {
  .room-layout { grid-template-areas: 'topbar' 'main'; grid-template-columns: minmax(0, 1fr); }
  .room-topbar { grid-area: topbar; }
  .room-sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 210; width: min(320px, 84vw); border-radius: 0; box-shadow: var(--shadow-dropdown); transform: translateX(-100%); transition: transform var(--motion-standard) var(--motion-spring); }
  .room-sidebar.is-open { transform: translateX(0); }
  .room-sidebar-backdrop { position: fixed; inset: 0; z-index: 200; background: rgba(0, 0, 0, 0.32); }
}

/* reduced-motion 下抽屉取消位移过渡（置于 1024px 规则之后，确保覆盖生效） */
@media (prefers-reduced-motion: reduce) {
  .room-sidebar, .room-layout, .room-sidebar-rail, .room-sidebar-rail__case { transition: none; }
  .room-sidebar-rail__case:hover { transform: none; }
}

/* ≤768px：页面内边距降至 16px（规范 §7.1），消息区同步收窄 */
@media (max-width: 768px) {
  .room-page { padding: var(--space-lg); }
  .room-messages { padding: var(--space-lg) var(--space-lg) var(--space-xl); }
  .case-header { padding: var(--space-md) var(--space-lg); }
  .case-header__actions { width: 100%; justify-content: flex-start; margin-left: 0; }
}

/* ≤640px：左栏头部操作区允许换行；快捷胶囊组换行由 .room-guide__actions 的 flex-wrap 承担 */
@media (max-width: 640px) {
  .room-sidebar__toolbar { flex-wrap: wrap; }
  .case-header__actions { align-items: stretch; flex-wrap: wrap; }
  .room-model-control { flex: 1 1 180px; justify-content: space-between; }
  .room-model-trigger { max-width: min(220px, 58vw); }
}
</style>
