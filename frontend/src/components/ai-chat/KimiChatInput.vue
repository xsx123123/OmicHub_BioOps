<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NForm, NFormItem, NIcon, NTooltip, NPopover, NInput, NModal, useDialog, useMessage, NTag } from 'naive-ui'
import {
  ArrowUpOutline,
  AttachOutline,
  GlobeOutline,
  TerminalOutline,
  SparklesOutline,
  TrashOutline,
  PlayOutline,
  RefreshOutline,
  PersonOutline,
  ExtensionPuzzleOutline,
  DocumentTextOutline,
  FolderOpenOutline,
  HammerOutline,
  ChatbubbleEllipsesOutline,
  CompassOutline,
  PlayCircleOutline,
  SearchCircleOutline,
  ShieldCheckmarkOutline,
  LockOpenOutline,
  KeyOutline,
  FlagOutline,
  CloseOutline,
  DesktopOutline,
  CubeOutline,
} from '@vicons/ionicons5'
import SlashCommandMenu from './SlashCommandMenu.vue'
import MentionMenu from './MentionMenu.vue'
import GoalStatusCard from './GoalStatusCard.vue'
import { readActiveMentionQuery } from './mentionQuery'
import { pushRecent, recentRank } from './recentItems'
import { formatMentions } from '@/utils/agentTeamsRoom'
import { DATA_MANAGEMENT_UPLOAD_HINT, requiresDataManagementUpload } from './attachmentPolicy'
import { clipboardAttachmentFiles } from './clipboardAttachments'
import {
  STAR_MODE_COMMANDS,
  STAR_MODE_LABELS,
  STAR_PERMISSION_COMMANDS,
  STAR_PERMISSION_LABELS,
  hasStarModeCommand,
  hasStarPermissionCommand,
  parseGoalRuntimeCommand,
  resolveStarCommandContext,
  type GoalRuntimeCommand,
  type StarAgentMode,
  type StarPermission,
} from './commandState'
import McpSelectionMenu from './McpSelectionMenu.vue'
import { useChatStore } from '@/stores/chat'
import { useAgentHubStore } from '@/stores/agentHub'
import { useAuthStore } from '@/stores/auth'
import { useModulesStore } from '@/stores/modules'
import { useGoalRuntimeStore } from '@/stores/goalRuntime'
import apiClient from '@/api/client'
import { agentTeamsApi } from '@/api/agentTeams'
import type { DataFile } from '@/types'
import type { AgentTemplate, SkillItem } from '@/types/agent'
import type { FileAttachment, MentionDirectory, MentionItem } from './types'

/** 工具行项目显隐配置；未指定时由 roomMode 推导默认值 */
export interface ToolbarConfig {
  attach?: boolean
  workspaceReference?: boolean
  webSearch?: boolean
  terminal?: boolean
  mcp?: boolean
  deepThinking?: boolean
  /** 沙箱运行时选择器 */
  runtime?: boolean
  workbench?: boolean
  clear?: boolean
  send?: boolean
}

interface Props {
  modelValue: string
  placeholder?: string
  disabled?: boolean
  /** 是否正在流式输出 */
  isStreaming?: boolean
  /** 是否已暂停 */
  isPaused?: boolean
  /** 是否显示会话级超频模式开关 */
  showOverdriveControl?: boolean
  /** 当前超频模式状态 */
  overdriveEnabled?: boolean
  /** 是否显示进入工作台的入口 */
  showWorkbenchControl?: boolean
  /** 工作台会话正在创建中 */
  workbenchLoading?: boolean
  /** 协作室等纯消息场景：关闭 slash/Goal 命令与 Agent 会话专属工具，@ 面板仅保留文件条目 */
  roomMode?: boolean
  /** 协作室当前 Case 可被 @ 点名的领域 Agent。 */
  roomMentionAgents?: AgentTemplate[]
  /** 工具行提示文案（如 "Enter 发送 · Shift+Enter 换行"），不传则不显示；P7 后渲染在输入卡片下方右侧 */
  hint?: string
  /** 提交中：发送按钮 loading 并禁用 */
  sendLoading?: boolean
  /** 输入长度上限，透传给内部 textarea；不传则不限制 */
  maxlength?: number
  /** 工具行显隐配置；未传时按 roomMode 推导：协作室默认只保留附件、@引用、清空、发送，避免死按钮 */
  toolbarConfig?: ToolbarConfig
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  placeholder: '输入需求，@ 引用文件、技能或智能体，/ 查看快捷命令',
  disabled: false,
  isStreaming: false,
  isPaused: false,
  showOverdriveControl: false,
  overdriveEnabled: false,
  showWorkbenchControl: false,
  workbenchLoading: false,
  roomMode: false,
  roomMentionAgents: () => [],
  hint: '',
  sendLoading: false,
  toolbarConfig: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: [
    content: string,
    options: {
      attachments?: FileAttachment[]
      enableWebSearch?: boolean
      enableCodeExecution?: boolean
      /** @ 显式指定的智能体（本条消息转交给该专家回答） */
      explicitAgentId?: string
      /** @ 挂载到本次对话的技能名 */
      skillNames?: string[]
      mcpMode?: 'off' | 'auto' | 'manual'
      extraMcpServers?: string[]
      messageMetadata?: Record<string, unknown>
    },
  ]
  triggerSandbox: []
  stop: []
  pause: []
  resume: []
  regenerate: []
  toggleOverdrive: []
  enterWorkbench: []
}>()

const chatStore = useChatStore()
const agentHub = useAgentHubStore()
const authStore = useAuthStore()
const modulesStore = useModulesStore()
const goalRuntime = useGoalRuntimeStore()
const message = useMessage()
const dialog = useDialog()
const router = useRouter()

/** 工具行显隐：外部传了 toolbarConfig 则完全以外部为准；否则按 roomMode 推导默认值 */
const defaultToolbarConfig = computed<ToolbarConfig>(() => {
  if (props.roomMode) {
    return {
      attach: true,
      workspaceReference: true,
      webSearch: false,
      terminal: false,
      mcp: false,
      deepThinking: false,
      runtime: false,
      workbench: false,
      clear: true,
      send: true,
    }
  }
  return {
    attach: true,
    workspaceReference: true,
    webSearch: true,
    terminal: true,
    mcp: true,
    deepThinking: true,
    runtime: true,
    workbench: props.showWorkbenchControl,
    clear: true,
    send: true,
  }
})

const toolbar = computed<ToolbarConfig>(() => ({
  ...defaultToolbarConfig.value,
  ...props.toolbarConfig,
}))

/** 沙箱运行时选择器：数据源为 agentHub.runtimeProfiles；接口不可用时为空数组，选择器隐藏降级 */
const runtimeProfiles = computed(() => agentHub.runtimeProfiles)
const showRuntimeMenu = ref(false)
/** 当前会话已固定沙箱运行时（studio 会话创建时确定，之后不可变） */
const runtimeLocked = computed(() => agentHub.currentSession?.mode === 'studio')
const selectedRuntimeId = computed(() => agentHub.currentSession?.runtime_profile || '')
const selectedRuntime = computed(
  () => runtimeProfiles.value.find((profile) => profile.id === selectedRuntimeId.value) || null,
)
const showRuntimeSelector = computed(
  () => Boolean(toolbar.value.runtime && agentHub.currentSession && runtimeProfiles.value.length),
)

function selectRuntime(id: string) {
  if (agentHub.currentSession) agentHub.currentSession.runtime_profile = id || null
  showRuntimeMenu.value = false
}

/** 中部能力胶囊区域是否还需要渲染 */
const showToolbarCenter = computed(
  () =>
    toolbar.value.webSearch ||
    toolbar.value.terminal ||
    toolbar.value.mcp ||
    toolbar.value.deepThinking ||
    showRuntimeSelector.value ||
    toolbar.value.workbench,
)

const inputWrapperRef = ref<HTMLElement>()
const composerShellRef = ref<HTMLElement>()
const fileInputRef = ref<HTMLInputElement>()
const isComposing = ref(false)
/** IME 候选确认（compositionend）时间戳：Chrome/macOS 等场景下确认候选词后
 *  会再派发一次 isComposing=false 的真实 Enter keydown，仅靠 isComposing 守卫
 *  拦不住，会把候选确认误判为"发送"；这里记录时间戳做短窗口抑制。 */
const lastCompositionEndTime = ref(0)
const showSlashMenu = ref(false)
const slashQuery = ref('')
const slashMenuRef = ref<InstanceType<typeof SlashCommandMenu>>()
const showClearConfirm = ref(false)
const attachments = ref<FileAttachment[]>([])
const uploading = ref(false)
const isDraggingOver = ref(false)
let dragCounter = 0
const enableCodeExecution = ref(false)
const starMode = ref<StarAgentMode>('chat')
const starPermission = ref<StarPermission>('safe')
const starModeExplicit = ref(false)
const starPermissionExplicit = ref(false)
const starContext = computed(() => resolveStarCommandContext(localValue.value, {
  mode: starMode.value,
  permission: starPermission.value,
}))
const starModeLabel = computed(() => STAR_MODE_LABELS[starContext.value.mode])
const starPermissionLabel = computed(() => STAR_PERMISSION_LABELS[starContext.value.permission])
const starModeIcon = computed(() => ({
  chat: ChatbubbleEllipsesOutline,
  plan: CompassOutline,
  run: PlayCircleOutline,
  research: SearchCircleOutline,
})[starContext.value.mode])
const starPermissionIcon = computed(() => ({
  safe: ShieldCheckmarkOutline,
  read: LockOpenOutline,
  analysis: CompassOutline,
  full: KeyOutline,
})[starContext.value.permission])
const showStarMode = computed(() => starModeExplicit.value || hasStarModeCommand(localValue.value))
const showStarPermission = computed(() => starPermissionExplicit.value || hasStarPermissionCommand(localValue.value))
const showStarContext = computed(() => showStarMode.value || showStarPermission.value || Boolean(starContext.value.goal))

// ===== ask_user 待回答联动：输入框提示条 + 待回答 pill =====
// 状态源为消息的 askRequest（agentHub store），此处仅派生展示，不回写。
/** 未回答的 ask_user 问题总数（排除计划确认卡片，仅统计 AskUserCard 呈现的问题类澄清） */
const pendingAskQuestions = computed(() => {
  let count = 0
  for (const msg of agentHub.currentSession?.messages || []) {
    const ask = msg.askRequest
    if (ask && !ask.answered && (ask.questions?.length ?? 0) > 0) {
      count += ask.questions.length
    }
  }
  return count
})
const hasPendingAsk = computed(() => pendingAskQuestions.value > 0)

/** 待回答 pill：仅当存在未回答澄清且卡片不在消息列表视口内时显示 */
const askPillVisible = ref(false)
let askScrollEl: HTMLElement | null = null

/** 从组件根部向上查找同视图内的消息滚动容器（.message-scroller） */
function findAskScroller(): HTMLElement | null {
  let node = composerShellRef.value?.parentElement ?? null
  while (node) {
    const el = node.querySelector<HTMLElement>('.message-scroller')
    if (el) return el
    node = node.parentElement
  }
  return null
}

/** 最近一张未回答的 AskUserCard（虚拟列表未挂载时返回 null） */
function findPendingAskCard(scroller: HTMLElement): HTMLElement | null {
  const cards = scroller.querySelectorAll<HTMLElement>('.ask-user-card:not(.answered)')
  return cards.length ? cards[cards.length - 1] : null
}

function updateAskPill() {
  const scroller = findAskScroller()
  if (!scroller || !hasPendingAsk.value) {
    askPillVisible.value = false
    return
  }
  const card = findPendingAskCard(scroller)
  if (card) {
    const cardRect = card.getBoundingClientRect()
    const viewRect = scroller.getBoundingClientRect()
    // 卡片任一像素进入视口即视为可见，不再提示
    askPillVisible.value = cardRect.bottom <= viewRect.top || cardRect.top >= viewRect.bottom
  } else {
    // 卡片被虚拟列表回收（距底较远）：按距底 100px 阈值兜底
    askPillVisible.value =
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > 100
  }
}

function bindAskScroller() {
  const scroller = findAskScroller()
  if (scroller === askScrollEl) return
  askScrollEl?.removeEventListener('scroll', updateAskPill)
  askScrollEl = scroller
  askScrollEl?.addEventListener('scroll', updateAskPill, { passive: true })
}

/** 点击 pill：平滑滚动到最近一张待回答卡片 */
function scrollToPendingAsk() {
  const scroller = findAskScroller()
  if (!scroller) return
  const card = findPendingAskCard(scroller)
  if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' })
  else scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' })
  askPillVisible.value = false
}

watch(hasPendingAsk, async (pending) => {
  if (pending) {
    await nextTick()
    bindAskScroller()
    updateAskPill()
  } else {
    askPillVisible.value = false
  }
})
const goalSessionId = computed(() => agentHub.currentSession?.id || '')
const activeGoal = computed(() => goalRuntime.goalForSession(goalSessionId.value))
const activeGoalEvents = computed(() => goalRuntime.eventsForGoal(activeGoal.value?.id))
const goalLoading = computed(() => Boolean(goalRuntime.loadingBySession[goalSessionId.value]))
const goalError = computed(() => goalRuntime.errorBySession[goalSessionId.value] || '')

function getTextareaElement() {
  return inputWrapperRef.value?.querySelector<HTMLTextAreaElement>('textarea')
}

/** 供页面侧在快捷任务预填后聚焦输入框 */
function focus() {
  getTextareaElement()?.focus()
}

/** 预填文案后聚焦并把光标置于文末（建议追问 Chips 的 prefill 行为使用） */
function focusWithCursorAtEnd() {
  const el = getTextareaElement()
  if (!el) return
  el.focus()
  const end = el.value.length
  el.setSelectionRange(end, end)
}

/** 读取当前草稿附件（进入工作台携带草稿时使用，返回副本不清空） */
function getDraftAttachments(): FileAttachment[] {
  return attachments.value.map((a) => ({ ...a }))
}

/** 恢复草稿附件（工作台进入后回填草稿时使用，整体替换） */
function setDraftAttachments(items: FileAttachment[]) {
  attachments.value = (items || []).map((a) => ({ ...a }))
}
defineExpose({ focus, focusWithCursorAtEnd, getDraftAttachments, setDraftAttachments })

const agentTeamsCaseVisible = ref(false)
const agentTeamsCaseSubmitting = ref(false)
const agentTeamsCaseForm = ref({ objective: '', project_id: '', flow_id: '' })

function openAgentTeamsCaseModal(detail?: { summary?: string; consultationId?: string }) {
  agentTeamsCaseForm.value = {
    objective: detail?.summary || localValue.value.trim(),
    project_id: '',
    flow_id: '',
  }
  pendingConsultation.value = detail || null
  agentTeamsCaseVisible.value = true
}

const pendingConsultation = ref<{ summary?: string; consultationId?: string } | null>(null)

async function submitAgentTeamsCase() {
  const sessionId = agentHub.currentSessionId
  const form = agentTeamsCaseForm.value
  if (!sessionId || sessionId.startsWith('sess-')) {
    message.warning('请等待会话初始化完成后再创建协作 Case')
    return
  }
  if (!form.objective.trim() || !form.project_id.trim() || !form.flow_id.trim()) {
    message.warning('请完整填写交付目标、项目 ID 和流程 ID')
    return
  }
  agentTeamsCaseSubmitting.value = true
  try {
    const created = await agentTeamsApi.createCase({
      session_id: sessionId,
      intent: form.objective.trim(),
      project_id: form.project_id.trim(),
      flow_id: form.flow_id.trim(),
      origin_consultation_id: pendingConsultation.value?.consultationId,
      consultation_summary: pendingConsultation.value?.summary,
    })
    agentTeamsCaseVisible.value = false
    message.success(`协作 Case 已创建：${created.case_id}`)
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '协作 Case 创建失败')
  } finally {
    agentTeamsCaseSubmitting.value = false
  }
}

function handleAgentTeamsCreateEvent(event: Event) {
  const detail = (event as CustomEvent<{ summary?: string; consultationId?: string }>).detail
  openAgentTeamsCaseModal(detail)
}

// ===== @ 引用状态 =====
const showMentionMenu = ref(false)
const mentionQuery = ref('')
const mentionActiveIndex = ref(0)
const workspaceFiles = ref<DataFile[]>([])
const workspaceDirectories = ref<MentionDirectory[]>([])
const workspaceSynced = ref(false)
const workspaceSyncAttempted = ref(false)
const mentionLoading = ref(false)
const mentionState = ref<'idle' | 'loading' | 'error' | 'empty' | 'forbidden'>('idle')
/** @ 显式指定的智能体（随下一条消息发送） */
const pendingAgent = ref<AgentTemplate | null>(null)
/** @ 挂载的技能（随下一条消息发送） */
const pendingSkills = ref<SkillItem[]>([])
type McpMode = 'off' | 'auto' | 'manual'
const showMcpMenu = ref(false)
const mcpMenuRef = ref<InstanceType<typeof McpSelectionMenu>>()
const mcpMode = ref<McpMode>('auto')
const extraMcpServers = ref<string[]>([])
const defaultMcpIds = computed(() => new Set(agentHub.currentAgent?.mcp_ids || []))
const extraMcpCount = computed(() => extraMcpServers.value.filter((id) => !defaultMcpIds.value.has(id)).length)
const mcpButtonActive = computed(() => mcpMode.value !== 'auto')
const agentTeamsLocked = computed(() => modulesStore.isModuleLocked(
  'agent_teams', authStore.user?.disabled_modules || [],
))

function syncMcpSelection() {
  mcpMode.value = agentHub.currentSession?.mcp_mode || 'auto'
  extraMcpServers.value = [...(agentHub.currentSession?.extra_mcp_servers || [])]
}

function handleMcpSelection(selection: { mode: McpMode; extraServers: string[] }) {
  mcpMode.value = selection.mode
  extraMcpServers.value = [...selection.extraServers]
  const session = agentHub.currentSession
  if (session) {
    session.mcp_mode = mcpMode.value
    session.extra_mcp_servers = [...extraMcpServers.value]
  }
}

const localValue = ref(props.modelValue)
const highlightRef = ref<HTMLDivElement | null>(null)
const hasMentionMarkup = computed(() => /@\S+/.test(localValue.value))
const inputHighlightHtml = computed(() => formatMentions(localValue.value))

function syncHighlightScroll() {
  const textarea = getTextareaElement()
  const highlight = highlightRef.value
  if (!textarea || !highlight) return
  highlight.scrollTop = textarea.scrollTop
  highlight.scrollLeft = textarea.scrollLeft
}

watch(localValue, (val) => {
  emit('update:modelValue', val)
  nextTick(syncHighlightScroll)
})

watch(
  () => props.modelValue,
  (val) => {
    if (val !== localValue.value) {
      localValue.value = val
    }
  }
)

watch(localValue, () => {
  detectSlashCommand()
  detectMention()
})

const canSend = computed(
  () =>
    localValue.value.trim().length > 0 ||
    attachments.value.length > 0 ||
    pendingAgent.value !== null ||
    pendingSkills.value.length > 0,
)

const canClear = computed(
  () =>
    localValue.value.trim().length > 0 ||
    attachments.value.length > 0 ||
    pendingAgent.value !== null ||
    pendingSkills.value.length > 0,
)

function handleCompositionEnd() {
  isComposing.value = false
  lastCompositionEndTime.value = Date.now()
}

function handleKeydown(e: KeyboardEvent) {
  if (isComposing.value || e.isComposing) return
  // compositionend 刚结束后的短窗口内忽略 Enter，拦住 IME 确认候选词后的幽灵 Enter
  if (e.key === 'Enter' && Date.now() - lastCompositionEndTime.value < 200) return
  if (showMcpMenu.value && e.key === 'Escape') {
    e.preventDefault()
    showMcpMenu.value = false
    return
  }
  if (showMcpMenu.value && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault()
    mcpMenuRef.value?.moveSelection(e.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (showMcpMenu.value && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    mcpMenuRef.value?.selectCurrent()
    return
  }
  if (showSlashMenu.value && !props.roomMode) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      slashMenuRef.value?.moveSelection(e.key === 'ArrowDown' ? 1 : -1)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      slashMenuRef.value?.selectCurrent()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      showSlashMenu.value = false
      return
    }
  }

  // @ 补全面板打开时，优先接管方向键 / Enter / Esc
  if (showMentionMenu.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionActiveIndex.value = (mentionActiveIndex.value + 1) % Math.max(mentionItems.value.length, 1)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      mentionActiveIndex.value =
        (mentionActiveIndex.value - 1 + mentionItems.value.length) % Math.max(mentionItems.value.length, 1)
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const item = mentionItems.value[mentionActiveIndex.value]
      if (item) selectMention(item)
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      showMentionMenu.value = false
      return
    }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (canSend.value && !props.disabled) {
      handleSend()
    }
  }
  if (e.key === 'Escape') {
    showSlashMenu.value = false
  }
  if (!props.roomMode && e.key === '/' && localValue.value === '') {
    nextTick(() => {
      showSlashMenu.value = true
      slashQuery.value = ''
    })
  }
}

function detectSlashCommand() {
  if (props.roomMode) {
    showSlashMenu.value = false
    return
  }
  const text = localValue.value
  const lastLine = text.split('\n').pop() || ''

  if (lastLine.startsWith('/')) {
    showSlashMenu.value = true
    slashQuery.value = lastLine.slice(1)
  } else {
    showSlashMenu.value = false
  }
}

// ===== @ 引用：检测 / 数据 / 选择 =====

/** 提取光标处活跃的 @ 查询词；不在 @ 上下文中返回 null */
function readMentionQuery(): string | null {
  const el = getTextareaElement()
  const text = localValue.value
  const caret = el?.selectionStart ?? text.length
  const before = text.slice(0, caret)
  const committedLabels = [
    ...attachments.value.filter((attachment) => attachment.source === 'workspace').map((attachment) => attachment.name),
    ...(pendingAgent.value ? [pendingAgent.value.name] : []),
    ...pendingSkills.value.map((skill) => skill.name),
  ]
  // 已选择的引用以空格作为提交边界，避免其后的正文再次打开面板；
  // 尚未选择时仍允许目录与文件名包含空格，例如 @docs/report copy.csv。
  return readActiveMentionQuery(before, committedLabels)
}

function detectMention() {
  const q = readMentionQuery()
  if (q === null) {
    showMentionMenu.value = false
    return
  }
  // 与 slash 菜单互斥
  showSlashMenu.value = false
  showMentionMenu.value = true
  mentionQuery.value = q
  mentionActiveIndex.value = 0
  if (workspaceSynced.value || workspaceSyncAttempted.value) searchWorkspaceFiles(q)
  else syncAndSearchWorkspaceFiles(q)
  ensureMentionData()
}

/** 首次打开 @ 面板时加载工作区文件与智能体 / 技能资产；roomMode 下 @ 仅文件，无需拉取资产 */
async function ensureMentionData() {
  if (props.roomMode) return
  if (!agentHub.agents.length) agentHub.fetchAgents()
  if (!agentHub.skills.length) agentHub.fetchSkills()
}

let mentionSearchRequest = 0
let workspaceSyncPromise: Promise<void> | null = null

async function syncAndSearchWorkspaceFiles(query: string) {
  if (!workspaceSyncPromise) {
    workspaceSyncAttempted.value = true
    workspaceSyncPromise = apiClient.post('/files/sync')
      .then(() => { workspaceSynced.value = true })
      .catch((error) => {
        console.warn('同步工作区文件索引失败，将使用现有索引:', error)
      })
      .finally(() => { workspaceSyncPromise = null })
  }
  await workspaceSyncPromise
  await searchWorkspaceFiles(query)
}

async function searchWorkspaceFiles(query = mentionQuery.value) {
  const requestId = ++mentionSearchRequest
  mentionLoading.value = true
  mentionState.value = 'loading'
  try {
    const res = await apiClient.get<{ items: DataFile[]; directories: MentionDirectory[]; total: number }>('/files/search', {
      params: { q: query, root: '', limit: 50 },
    })
    if (requestId !== mentionSearchRequest) return
    workspaceFiles.value = res.data.items || []
    workspaceDirectories.value = res.data.directories || []
    mentionState.value = workspaceFiles.value.length || workspaceDirectories.value.length ? 'idle' : 'empty'
  } catch (e) {
    if (requestId !== mentionSearchRequest) return
    mentionState.value = (e as { response?: { status?: number } })?.response?.status === 403 ? 'forbidden' : 'error'
    console.error('搜索工作区文件失败:', e)
  } finally {
    if (requestId === mentionSearchRequest) mentionLoading.value = false
  }
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

function normalizedMentionQuery(query: string): string {
  return normalizePath(query)
}

/** 按文件名与路径模糊匹配；`@/` 中的斜杠表示路径分隔符。 */
function fuzzyMatch(text: string, q: string): boolean {
  const normalizedQuery = normalizedMentionQuery(q).toLowerCase()
  if (!normalizedQuery) return true
  return normalizePath(text).toLowerCase().includes(normalizedQuery)
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * 友好名称：主行禁止裸显 UUID。
 * 名称本身是 UUID 时，回退到路径末段；末段仍是 UUID 时用类型/占位名。
 * 返回 [展示名, uuid 或 null]。
 */
function friendlyName(raw: string, fallbackPath: string, typeHint: string): [string, string | null] {
  const uuid = UUID_RE.test(raw) ? raw : null
  if (!uuid) return [raw, null]
  const segments = normalizePath(fallbackPath).split('/').filter(Boolean)
  const last = segments[segments.length - 1] || ''
  if (last && !UUID_RE.test(last)) return [last, uuid]
  return [`${typeHint}-${uuid.slice(0, 8)}`, uuid]
}

/**
 * @ 面板条目：仅"上下文引用"类（文件夹 / 文件）。
 * Agent / Skill 属于"能力调用"，改由 / 面板分组承载（Part C 语义拆分）。
 */
const mentionItems = computed<MentionItem[]>(() => {
  const q = mentionQuery.value
  const agents: MentionItem[] = props.roomMode
    ? props.roomMentionAgents.map((agent) => ({
      kind: 'agent' as const,
      key: `room-agent-${agent.id}`,
      name: agent.name,
      description: agent.description || '当前协作 Case 的领域 Agent',
      agent,
    }))
    : []
  // roomMode 下目录引用无法映射为 Case context_refs，因此只保留文件与 Agent。
  const directories: MentionItem[] = props.roomMode ? [] : workspaceDirectories.value
    .filter((directory) => fuzzyMatch(directory.path, q))
    .slice(0, 20)
    .map((directory) => {
      const [name, uuid] = friendlyName(directory.name || '', directory.path, '未命名目录')
      return {
        kind: 'directory' as const,
        key: `directory-${directory.id}`,
        name,
        description: `${normalizePath(directory.path)}/`,
        uuid: uuid ?? undefined,
        directory,
      }
    })
  const files: MentionItem[] = workspaceFiles.value
    .filter((f) => fuzzyMatch(f.path || `${f.directory ? `${f.directory}/` : ''}${f.original_name}`, q))
    .slice(0, 30)
    .map((f) => {
      const fullPath = f.path || `${f.directory ? `${f.directory}/` : ''}${f.original_name}`
      const [name] = friendlyName(f.original_name || '', fullPath, f.file_type || 'file')
      return {
        kind: 'file' as const,
        key: `file-${f.id}`,
        name,
        description: `${fullPath} · ${formatBytes(f.size)}`,
        uuid: f.id,
        file: f,
      }
    })

  const items = [...agents, ...directories, ...files]
  const normalizedQuery = normalizedMentionQuery(q).toLowerCase()
  // 排序：类型分组（Agent → 目录 → 文件）→ 查询相关度 → 最近使用置顶 → 名称
  const groupRank = (item: MentionItem) =>
    item.kind === 'agent' ? 0 : item.kind === 'directory' ? 1 : 2
  return items.sort((left, right) => {
    const relevance = (item: MentionItem) => {
      if (!normalizedQuery) return 0
      const text = `${item.name} ${item.description}`.toLowerCase()
      return text.startsWith(normalizedQuery) ? 0 : text.includes(normalizedQuery) ? 1 : 2
    }
    return (
      groupRank(left) - groupRank(right) ||
      relevance(left) - relevance(right) ||
      recentRank('mention', left.key) - recentRank('mention', right.key) ||
      left.name.localeCompare(right.name, 'zh')
    )
  })
})

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${size}B`
}

/** 把光标处活跃的 @查询词 替换为 @名称 + 空格，返回是否替换成功 */
function replaceMentionToken(name: string, appendSpace = true): void {
  const el = getTextareaElement()
  const text = localValue.value
  const caret = el?.selectionStart ?? text.length
  const before = text.slice(0, caret).replace(/@([^@\n]*)$/, `@${name}${appendSpace ? ' ' : ''}`)
  localValue.value = before + text.slice(caret)
  nextTick(() => {
    if (el) {
      const pos = before.length
      el.focus()
      el.setSelectionRange(pos, pos)
    }
  })
}

function selectMention(item: MentionItem) {
  if (item.kind === 'directory' && item.directory) {
    pushRecent('mention', item.key)
    replaceMentionToken(`${normalizePath(item.directory.path)}/`, false)
    nextTick(() => detectMention())
    return
  } else if (item.kind === 'file' && item.file) {
    pushRecent('mention', item.key)
    const f = item.file
    const relativePath = normalizePath(f.path || `${f.directory ? `${f.directory}/` : ''}${f.original_name}`)
    const fileId = props.roomMode ? relativePath : `file://${f.id}`
    // 去重：已引用则不重复添加
    if (!attachments.value.some((a) => a.file_id === fileId)) {
      attachments.value.push({
        name: relativePath || f.original_name,
        size: f.size,
        type: 'application/octet-stream',
        url: `/api/v1/files/${f.id}/download`,
        file_id: fileId,
        source: 'workspace',
      })
    }
    replaceMentionToken(relativePath || f.original_name)
  } else if (item.kind === 'agent' && item.agent) {
    pendingAgent.value = item.agent
    replaceMentionToken(item.agent.name)
  } else if (item.kind === 'skill' && item.skill) {
    if (!pendingSkills.value.some((s) => s.id === item.skill!.id)) {
      pendingSkills.value.push(item.skill)
    }
    replaceMentionToken(item.skill.name)
  }
  showMentionMenu.value = false
}

function referenceDirectory(item: MentionItem) {
  if (item.kind !== 'directory' || !item.directory?.id) return
  pushRecent('mention', item.key)
  const directory = item.directory
  const fileId = `directory://${directory.id}`
  if (!attachments.value.some((attachment) => attachment.file_id === fileId)) {
    attachments.value.push({
      name: `${normalizePath(directory.path)}/`,
      size: 0,
      type: 'directory',
      file_id: fileId,
      source: 'workspace',
      recursive: true,
    })
  }
  replaceMentionToken(`${normalizePath(directory.path)}/`, true)
  showMentionMenu.value = false
}

function removePendingAgent() {
  pendingAgent.value = null
}

function removePendingSkill(idx: number) {
  pendingSkills.value.splice(idx, 1)
}

function handleSlashSelect(command: string) {
  pushRecent('slash', command)
  const skillName = command.startsWith('/skill:') ? command.slice('/skill:'.length).trim() : ''
  if (skillName) {
    const skill = agentHub.skills.find(
      (item) => item.id === skillName || item.name === skillName,
    )
    if (skill && !pendingSkills.value.some((item) => item.id === skill.id)) {
      pendingSkills.value.push(skill)
    }
  }
  if (STAR_MODE_COMMANDS[command]) {
    starMode.value = STAR_MODE_COMMANDS[command]
    starModeExplicit.value = true
  }
  if (STAR_PERMISSION_COMMANDS[command]) {
    starPermission.value = STAR_PERMISSION_COMMANDS[command]
    starPermissionExplicit.value = true
  }
  const text = localValue.value
  const lines = text.split('\n')
  lines[lines.length - 1] = command + ' '
  localValue.value = lines.join('\n')
  showSlashMenu.value = false
  nextTick(() => getTextareaElement()?.focus())
}

/**
 * / 面板选中智能体：插入与手动 @ 完全一致的 mention 标签。
 * 与 selectMention 的 agent 分支同款状态（pendingAgent）+ 同款 `@名称 ` 文本，
 * 保证标签渲染与提交数据结构不变；替换的是行首 `/查询词`（而非 @ 查询词）。
 */
function handleSlashSelectAgent(agent: AgentTemplate) {
  pushRecent('slash', `agent-${agent.id}`)
  pendingAgent.value = agent
  const el = getTextareaElement()
  const text = localValue.value
  const caret = el?.selectionStart ?? text.length
  const beforeCaret = text.slice(0, caret)
  const replaced = beforeCaret.replace(
    /(^|\n)\/[^\n]*$/,
    (match, prefix: string) => `${prefix}@${agent.name} `,
  )
  localValue.value = replaced + text.slice(caret)
  showSlashMenu.value = false
  nextTick(() => {
    if (el) {
      el.focus()
      el.setSelectionRange(replaced.length, replaced.length)
    }
  })
}

async function handleGoalCommand(command: GoalRuntimeCommand): Promise<void> {
  const session = agentHub.currentSession
  if (!session || session.id.startsWith('sess-')) {
    message.warning('请先发送一条普通消息创建会话，再启动持久 Goal')
    return
  }
  try {
    if (command.action === 'start') {
      if (!command.objective) {
        message.warning('请在 /goal start 后填写明确目标')
        return
      }
      await goalRuntime.startGoal(session.id, command.objective, session.agent_id)
      message.success('持久 Goal 已启动，将在后台安全推进')
    } else if (command.action === 'status') {
      const goal = await goalRuntime.loadActiveGoal(session.id)
      message.info(goal ? `当前 Goal：${goal.status}` : '当前会话没有进行中的 Goal')
    } else {
      await goalRuntime.controlGoal(session.id, command.action)
      message.success(command.action === 'pause' ? 'Goal 已暂停' : command.action === 'resume' ? 'Goal 已恢复' : 'Goal 已取消')
    }
    localValue.value = ''
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
    message.error(detail || (error as Error).message || 'Goal 操作失败')
  }
}

function refreshGoalStatus(): void {
  if (!goalSessionId.value || goalSessionId.value.startsWith('sess-')) return
  void goalRuntime.loadActiveGoal(goalSessionId.value).catch(() => undefined)
}

function handleGoalControl(action: 'pause' | 'resume' | 'cancel'): void {
  void handleGoalCommand({ action })
}

/** 发送/清空后把自适应高度收回单行：naive-ui textarea 的高度由隐藏 mirror 驱动，
 *  受控清空（程序置空而非逐字删除）时可能错过重算；这里派发一次 input 事件，
 *  走 naive-ui 自己的 handleInput → syncMirror 路径强制重排，并兜底清掉内联高度。 */
function resetTextareaHeight() {
  void nextTick(() => {
    const textarea = getTextareaElement()
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function handleSend() {
  const content = localValue.value.trim()
  const hasPayload =
    content.length > 0 ||
    attachments.value.length > 0 ||
    pendingAgent.value !== null ||
    pendingSkills.value.length > 0
  if (!hasPayload || props.disabled) return

  const goalCommand = props.roomMode ? null : parseGoalRuntimeCommand(content)
  if (goalCommand) {
    await handleGoalCommand(goalCommand)
    return
  }

  emit('send', content, {
    attachments: attachments.value.length ? [...attachments.value] : undefined,
    enableWebSearch: chatStore.enableWebSearch,
    enableCodeExecution: enableCodeExecution.value,
    explicitAgentId: pendingAgent.value?.id,
    skillNames: pendingSkills.value.length ? pendingSkills.value.map((s) => s.name) : undefined,
    mcpMode: mcpMode.value,
    extraMcpServers: mcpMode.value === 'manual' ? [...extraMcpServers.value] : [],
    messageMetadata: showStarContext.value ? {
      star_command: {
        mode: starContext.value.mode,
        permission: starContext.value.permission,
        ...(starContext.value.goal ? { goal: starContext.value.goal } : {}),
      },
    } : undefined,
  })
  localValue.value = ''
  attachments.value = []
  pendingAgent.value = null
  pendingSkills.value = []
  starMode.value = 'chat'
  starPermission.value = 'safe'
  starModeExplicit.value = false
  starPermissionExplicit.value = false
  showMentionMenu.value = false
  showMcpMenu.value = false
  resetTextareaHeight()
  nextTick(() => getTextareaElement()?.focus())
}

function handleStop() {
  emit('stop')
}

function handleResume() {
  emit('resume')
}

function handleRegenerate() {
  emit('regenerate')
}

let blurTimer: ReturnType<typeof setTimeout> | null = null

function handleBlur(e: FocusEvent) {
  const nextTarget = e.relatedTarget as Node | null
  if (nextTarget && (e.currentTarget as HTMLElement).closest('.kimi-chat-input')?.contains(nextTarget)) {
    return
  }
  if (blurTimer) clearTimeout(blurTimer)
  blurTimer = setTimeout(() => {
    showSlashMenu.value = false
    showMentionMenu.value = false
  }, 200)
}

function handleAttach() {
  fileInputRef.value?.click()
}

function promptDataManagementUpload(files: File[]): void {
  const names = files.slice(0, 3).map((file) => file.name).join('、')
  const remaining = files.length > 3 ? ` 等 ${files.length} 个文件` : ''
  dialog.warning({
    title: '请在文件管理中上传',
    content: `${names}${remaining} 需要通过文件管理上传。${DATA_MANAGEMENT_UPLOAD_HINT}`,
    positiveText: '前往文件管理',
    negativeText: '留在当前页',
    onPositiveClick: () => router.push({ name: 'files' }),
  })
}

async function uploadFiles(selectedFiles: File[]) {
  if (!selectedFiles.length) return
  const dataManagementFiles = selectedFiles.filter((file) => requiresDataManagementUpload(file.name))
  const chatFiles = selectedFiles.filter((file) => !requiresDataManagementUpload(file.name))

  if (dataManagementFiles.length) promptDataManagementUpload(dataManagementFiles)
  if (!chatFiles.length) return

  uploading.value = true
  for (const file of chatFiles) {
    const formData = new FormData()
    formData.append('file', file)
    // 带上当前会话 ID，后端会把会话短标记写入上传文件名，便于按会话检索；
    // 仅真实后端会话 ID 才传（sess- 开头的是尚未落库的临时 ID，无检索意义）
    const sid = agentHub.currentSessionId
    if (sid && !sid.startsWith('sess-')) formData.append('session_id', sid)
    try {
      const res = await apiClient.post('/files/chat-upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      attachments.value.push({
        name: file.name,
        size: file.size,
        type: file.type || 'application/octet-stream',
        url: res.data.url,
        file_id: res.data.id,
      })
    } catch (err: any) {
      message.error(`上传 ${file.name} 失败: ${err?.response?.data?.detail || err.message}`)
    }
  }
  uploading.value = false
}

function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  void uploadFiles(Array.from(input.files ?? []))
  input.value = ''
}

function handlePaste(e: ClipboardEvent) {
  if (props.disabled) return
  const pastedFiles = clipboardAttachmentFiles(e.clipboardData)
  if (!pastedFiles.length) return

  e.preventDefault()
  message.info(`正在上传剪贴板中的 ${pastedFiles.length} 个文件`)
  void uploadFiles(pastedFiles)
}

function isFileDragEvent(e: DragEvent): boolean {
  if (!e.dataTransfer) return false
  // 只要包含文件类型即视为文件拖拽；文本/链接拖拽不触发上传
  return Array.from(e.dataTransfer.types).includes('Files')
}

function handleDragEnter(e: DragEvent) {
  if (props.disabled || !isFileDragEvent(e)) return
  e.preventDefault()
  dragCounter += 1
  isDraggingOver.value = true
}

function handleDragOver(e: DragEvent) {
  if (props.disabled || !isFileDragEvent(e)) return
  e.preventDefault()
  e.dataTransfer!.dropEffect = 'copy'
}

function handleDragLeave(e: DragEvent) {
  if (props.disabled || !isFileDragEvent(e)) return
  e.preventDefault()
  dragCounter -= 1
  if (dragCounter <= 0) {
    dragCounter = 0
    isDraggingOver.value = false
  }
}

async function handleDrop(e: DragEvent) {
  if (props.disabled || !isFileDragEvent(e)) return
  e.preventDefault()
  dragCounter = 0
  isDraggingOver.value = false
  await uploadFiles(Array.from(e.dataTransfer?.files ?? []))
}

function removeAttachment(idx: number) {
  attachments.value.splice(idx, 1)
}

async function handleWebSearchToggle() {
  if (chatStore.enableWebSearch) {
    chatStore.toggleWebSearch()
    return
  }
  try {
    const { data } = await apiClient.get<{ available: boolean }>('/chat/web-search/availability')
    if (data.available) {
      chatStore.toggleWebSearch()
      return
    }
  } catch {
    // 配置检查失败时保守地阻止开关，避免用户以为已经联网。
  }
  message.warning('请先到 AI 配置中心 · 资源中心 · 联网搜索 配置服务商')
  void router.push('/admin/ai-config/resources')
}

function handleWorkspaceReference() {
  const textarea = getTextareaElement()
  const caret = textarea?.selectionStart ?? localValue.value.length
  const before = localValue.value.slice(0, caret)
  const after = localValue.value.slice(caret)
  const prefix = before && !/\s$/.test(before) ? ' ' : ''
  const nextValue = `${before}${prefix}@${after}`

  localValue.value = nextValue
  nextTick(() => {
    const nextCaret = caret + prefix.length + 1
    textarea?.focus()
    textarea?.setSelectionRange(nextCaret, nextCaret)
  })
}

function handleClearConfirm() {
  localValue.value = ''
  attachments.value = []
  pendingAgent.value = null
  pendingSkills.value = []
  showClearConfirm.value = false
  resetTextareaHeight()
  nextTick(() => getTextareaElement()?.focus())
}

onMounted(() => {
  void modulesStore.ensureLoaded()
  void agentHub.fetchRuntimeProfiles()
  syncMcpSelection()
  refreshGoalStatus()
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  window.addEventListener('cygnusx:agentteams-create', handleAgentTeamsCreateEvent)
  getTextareaElement()?.addEventListener('scroll', syncHighlightScroll, { passive: true })
  nextTick(() => {
    bindAskScroller()
    updateAskPill()
  })
})

onUnmounted(() => {
  if (blurTimer) clearTimeout(blurTimer)
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  window.removeEventListener('cygnusx:agentteams-create', handleAgentTeamsCreateEvent)
  getTextareaElement()?.removeEventListener('scroll', syncHighlightScroll)
  askScrollEl?.removeEventListener('scroll', updateAskPill)
  askScrollEl = null
  if (goalSessionId.value) goalRuntime.disposeSession(goalSessionId.value)
})

function handleDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Element | null
  if (showMcpMenu.value && target && !target.closest('.mcp-selection-menu') && !target.closest('.mcp-toolbar-trigger')) {
    showMcpMenu.value = false
  }
}

watch(() => agentHub.currentSessionId, syncMcpSelection)
watch(() => agentHub.currentSessionId, refreshGoalStatus)
</script>

<template>
  <div ref="composerShellRef" class="ai-composer-shell">
    <Transition name="ask-pill">
      <button
        v-if="askPillVisible"
        type="button"
        class="ask-pending-pill"
        @click="scrollToPendingAsk"
      >
        有 {{ pendingAskQuestions }} 个待回答的问题 ↓
      </button>
    </Transition>
    <GoalStatusCard
      v-if="activeGoal"
      class="goal-status-dock"
      :goal="activeGoal"
      :events="activeGoalEvents"
      :loading="goalLoading"
      :error="goalError"
      @pause="handleGoalControl('pause')"
      @resume="handleGoalControl('resume')"
      @cancel="handleGoalControl('cancel')"
      @refresh="refreshGoalStatus"
    />
    <div
      class="kimi-chat-input"
      :class="{
        disabled,
        'room-mode': roomMode,
        'popup-open': showSlashMenu || showMentionMenu || showMcpMenu,
        'drag-over': isDraggingOver,
      }"
      @dragenter="handleDragEnter"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <!-- ask_user 待回答常驻提示条：不改 placeholder，回答/跳过后自动消失 -->
      <div v-if="hasPendingAsk" class="ask-waiting-bar" role="status">AI 正在等待你的回答</div>

      <Transition name="composer-menu" appear>
        <SlashCommandMenu
          v-if="showSlashMenu"
          ref="slashMenuRef"
          :query="slashQuery"
          :agents="agentHub.activeAgents"
          :skills="agentHub.skills"
          @select="handleSlashSelect"
          @select-agent="handleSlashSelectAgent"
          @close="showSlashMenu = false"
        />
      </Transition>

      <Transition name="composer-menu" appear>
        <McpSelectionMenu
          v-if="showMcpMenu"
          ref="mcpMenuRef"
          :mode="mcpMode"
          :extra-servers="extraMcpServers"
          @update="handleMcpSelection"
          @close="showMcpMenu = false"
        />
      </Transition>

      <Transition name="composer-menu" appear>
        <MentionMenu
          v-if="showMentionMenu"
          :items="mentionItems"
          :active-index="mentionActiveIndex"
          :loading="mentionLoading"
          :state="mentionState"
          :query="mentionQuery"
          @select="selectMention"
          @reference-directory="referenceDirectory"
          @hover="mentionActiveIndex = $event"
          @retry="searchWorkspaceFiles"
          @close="showMentionMenu = false"
        />
      </Transition>

      <Transition name="drag-overlay" appear>
        <div
          v-if="isDraggingOver"
          class="drag-drop-overlay"
          aria-hidden="true"
        >
          <div class="drag-drop-hint">
            <n-icon size="28"><AttachOutline /></n-icon>
            <span>释放以上传文件</span>
            <small>图片可直接识别，PDF、文本和树文件可读取内容</small>
          </div>
        </div>
      </Transition>

      <div v-if="attachments.length || pendingAgent || pendingSkills.length || showStarContext" class="ref-bar">
        <NTag
          v-if="showStarMode"
          size="small"
          :bordered="false"
          class="star-context-tag star-context-tag--mode"
          :title="`当前模式：${starModeLabel}`"
        >
          <template #icon><NIcon><component :is="starModeIcon" /></NIcon></template>
          {{ starModeLabel }}
        </NTag>

        <NTag
          v-if="showStarPermission"
          size="small"
          :bordered="false"
          class="star-context-tag star-context-tag--permission"
          :title="`当前权限：${starPermissionLabel}`"
        >
          <template #icon><NIcon><component :is="starPermissionIcon" /></NIcon></template>
          {{ starPermissionLabel }}
        </NTag>

        <NTag
          v-if="starContext.goal"
          size="small"
          :bordered="false"
          class="star-context-tag star-context-tag--goal"
          :title="`当前目标：${starContext.goal}`"
        >
          <template #icon><NIcon><FlagOutline /></NIcon></template>
          {{ starContext.goal }}
        </NTag>

        <NTag
          v-if="pendingAgent && !roomMode"
          size="small"
          round
          closable
          class="ref-chip ref-agent"
          :title="pendingAgent.name"
          @close="removePendingAgent"
        >
          <template #icon><n-icon><PersonOutline /></n-icon></template>
          {{ pendingAgent.name }}
        </NTag>

        <NTag
          v-for="(sk, idx) in pendingSkills"
          :key="`skill-${sk.id}`"
          size="small"
          round
          closable
          class="ref-chip ref-skill"
          :title="sk.name"
          @close="removePendingSkill(idx)"
        >
          <template #icon><n-icon><ExtensionPuzzleOutline /></n-icon></template>
          {{ sk.name }}
        </NTag>

        <n-tooltip
          v-for="(att, idx) in attachments"
          :key="att.file_id || att.url || `att-${att.name}-${idx}`"
          trigger="hover"
        >
          <template #trigger>
            <div
              class="attachment-chip"
              :class="{
                'ref-file': att.source === 'workspace' && att.type !== 'directory',
                'ref-directory': att.type === 'directory',
              }"
            >
              <n-icon size="14" aria-hidden="true">
                <component :is="att.type === 'directory' ? FolderOpenOutline : DocumentTextOutline" />
              </n-icon>
              <span class="attachment-name">{{ att.name }}</span>
              <span v-if="att.type === 'directory'" class="attachment-status">只读 · 递归</span>
              <button
                type="button"
                class="attachment-remove"
                :aria-label="`移除附件 ${att.name}`"
                @click.stop="removeAttachment(idx)"
              >
                <n-icon size="14"><CloseOutline /></n-icon>
              </button>
            </div>
          </template>
          {{ att.name }}；点击右侧 × 可单独移除
        </n-tooltip>
      </div>

      <div
        ref="inputWrapperRef"
        class="input-wrapper"
        :class="{ 'is-composing': isComposing, 'has-highlight': hasMentionMarkup }"
      >
        <div
          v-if="hasMentionMarkup"
          ref="highlightRef"
          class="input-highlight"
          aria-hidden="true"
          v-html="inputHighlightHtml"
        />
        <n-input
          v-model:value="localValue"
          type="textarea"
          class="chat-textarea"
          :placeholder="placeholder"
          :disabled="disabled"
          :bordered="false"
          :maxlength="maxlength"
          :autosize="{ minRows: 1, maxRows: 8 }"
          @blur="handleBlur"
          @keydown="handleKeydown"
          @paste.capture="handlePaste"
          @compositionstart="isComposing = true"
          @compositionend="handleCompositionEnd"
        />
      </div>

      <input
        ref="fileInputRef"
        type="file"
        multiple
        accept=".png,.jpg,.jpeg,.gif,.svg,.webp,.bmp,.ico,.pdf,.txt,.md,.doc,.docx,.csv,.tsv,.json,.yaml,.yml,.fastq,.fq,.fasta,.fa,.fna,.faa,.ffn,.bam,.cram,.sam,.vcf,.gff,.gff3,.gtf,.bed,.h5ad,.rds,.qs,.gz,.zip,.tar,.bz2,.xz,.nwk,.newick,.nhx,.nh,.tree,.tre,.trees,.dnd,.nex,.nexus,.iqtree,.treefile,.contree,.bionj,.mldist,.ufboot,.log,.aln,.phy,.phylip,.sto"
        style="display: none"
        @change="handleFileChange"
      />

      <div class="input-toolbar" role="group" aria-label="消息操作">
        <div class="toolbar-left" aria-label="上下文操作">
          <n-tooltip v-if="toolbar.attach" trigger="hover">
            <template #trigger>
              <n-button text class="toolbar-btn" :loading="uploading" aria-label="添加附件" @click="handleAttach">
                <n-icon size="18"><AttachOutline /></n-icon>
              </n-button>
            </template>
            添加附件；也可直接粘贴或拖入文件。图片可直接识别，PDF、文本和树文件可读取内容
          </n-tooltip>
          <n-tooltip v-if="toolbar.workspaceReference" trigger="hover">
            <template #trigger>
              <n-button text class="toolbar-btn" aria-label="引用工作区文件" @click="handleWorkspaceReference">
                <n-icon size="18"><DocumentTextOutline /></n-icon>
              </n-button>
            </template>
            引用工作区文件
          </n-tooltip>
        </div>

        <div v-if="showToolbarCenter" class="toolbar-center" aria-label="工具和消息模式">
          <n-tooltip v-if="toolbar.webSearch" trigger="hover">
            <template #trigger>
              <n-button
                text
                class="toolbar-btn"
                :class="{ active: chatStore.enableWebSearch }"
                :aria-label="chatStore.enableWebSearch ? '关闭联网搜索' : '开启联网搜索'"
                :aria-pressed="chatStore.enableWebSearch"
                @click="handleWebSearchToggle"
              >
                <n-icon size="18"><GlobeOutline /></n-icon>
              </n-button>
            </template>
            {{ chatStore.enableWebSearch ? '关闭联网搜索' : '开启联网搜索' }}
          </n-tooltip>
          <n-tooltip v-if="toolbar.terminal" trigger="hover">
            <template #trigger>
              <n-button
                text
                class="toolbar-btn"
                :class="{ active: enableCodeExecution }"
                :aria-label="enableCodeExecution ? '关闭终端执行' : '开启终端执行'"
                :aria-pressed="enableCodeExecution"
                @click="enableCodeExecution = !enableCodeExecution"
              >
                <n-icon size="18"><TerminalOutline /></n-icon>
              </n-button>
            </template>
            {{ enableCodeExecution ? '关闭终端执行' : '开启终端执行' }}
          </n-tooltip>
          <n-tooltip v-if="toolbar.mcp" trigger="hover">
            <template #trigger>
              <n-button
                text
                class="toolbar-btn mcp-toolbar-trigger"
                :class="{ active: mcpButtonActive }"
                :aria-label="`选择工具：${mcpMode === 'off' ? '关闭' : mcpMode === 'manual' ? '手动选择' : '自动'}`"
                :aria-pressed="mcpButtonActive"
                @click="showMcpMenu = !showMcpMenu"
              >
                <span class="mcp-button-icon">
                  <n-icon size="18"><HammerOutline /></n-icon>
                  <span v-if="mcpMode === 'manual' && extraMcpCount" class="mcp-count-badge">+{{ extraMcpCount }}</span>
                </span>
              </n-button>
            </template>
            MCP 工具：{{ mcpMode === 'off' ? '关闭' : mcpMode === 'manual' ? '手动选择' : '自动' }}
          </n-tooltip>
          <n-tooltip v-if="toolbar.deepThinking" trigger="hover">
            <template #trigger>
              <n-button
                text
                class="toolbar-btn"
                :class="{ active: chatStore.deepThinking }"
                :aria-label="chatStore.deepThinking ? '关闭深度思考' : '开启深度思考'"
                :aria-pressed="chatStore.deepThinking"
                @click="chatStore.toggleDeepThinking()"
              >
                <n-icon size="18"><SparklesOutline /></n-icon>
                <span class="btn-label">深度思考</span>
              </n-button>
            </template>
            {{ chatStore.deepThinking ? '关闭深度思考' : '开启深度思考' }}
          </n-tooltip>
          <n-popover
            v-if="showRuntimeSelector"
            v-model:show="showRuntimeMenu"
            trigger="click"
            placement="top"
            :width="240"
          >
            <template #trigger>
              <n-tooltip trigger="hover" :disabled="showRuntimeMenu">
                <template #trigger>
                  <n-button
                    text
                    class="toolbar-btn runtime-btn"
                    :class="{ active: Boolean(selectedRuntime) }"
                    :disabled="runtimeLocked"
                    :aria-label="selectedRuntime ? `沙箱运行时：${selectedRuntime.name}` : '选择沙箱运行时'"
                    :aria-pressed="Boolean(selectedRuntime)"
                  >
                    <n-icon size="18"><CubeOutline /></n-icon>
                    <span v-if="selectedRuntime" class="btn-label">{{ selectedRuntime.name }}</span>
                  </n-button>
                </template>
                {{ runtimeLocked
                  ? '当前会话的沙箱运行时已在创建时固定，请新建会话切换'
                  : selectedRuntime
                    ? `沙箱运行时：${selectedRuntime.name}，下一条消息将进入沙箱模式`
                    : '选择沙箱运行时（默认跟随 Agent）' }}
              </n-tooltip>
            </template>
            <div class="runtime-menu" role="menu" aria-label="沙箱运行时">
              <button
                type="button"
                class="runtime-option"
                :class="{ active: !selectedRuntimeId }"
                role="menuitemradio"
                :aria-checked="!selectedRuntimeId"
                @click="selectRuntime('')"
              >
                跟随 Agent 默认
              </button>
              <n-tooltip
                v-for="profile in runtimeProfiles"
                :key="profile.id"
                trigger="hover"
                placement="right"
              >
                <template #trigger>
                  <button
                    type="button"
                    class="runtime-option"
                    :class="{ active: selectedRuntimeId === profile.id }"
                    role="menuitemradio"
                    :aria-checked="selectedRuntimeId === profile.id"
                    @click="selectRuntime(profile.id)"
                  >
                    {{ profile.name }}
                  </button>
                </template>
                <div class="runtime-tip">
                  <div v-if="profile.description">{{ profile.description }}</div>
                  <div class="runtime-tip-image">镜像：{{ profile.image }}</div>
                </div>
              </n-tooltip>
            </div>
          </n-popover>
          <n-tooltip v-if="toolbar.workbench" trigger="hover">
            <template #trigger>
              <n-button
                text
                class="toolbar-btn workbench-btn"
                :loading="props.workbenchLoading"
                aria-label="进入 AI 工作台"
                @click="emit('enterWorkbench')"
              >
                <n-icon size="18"><DesktopOutline /></n-icon>
                <span class="btn-label">进入工作台</span>
              </n-button>
            </template>
            切换到 AI 工作台以执行代码、运行脚本并保存产物；当前对话历史会一并带过去
          </n-tooltip>
          <!-- 工作台入口之后的外挂区域（如项目选择器），由调用方按需注入 -->
          <slot name="after-workbench" />
        </div>

        <div class="toolbar-right">
          <n-popover v-if="toolbar.clear && canClear" v-model:show="showClearConfirm" trigger="click" placement="top-end" :width="200">
            <template #trigger>
              <n-tooltip trigger="hover">
                <template #trigger>
                  <n-button text class="toolbar-btn clear-btn" aria-label="清空输入">
                    <n-icon size="18"><TrashOutline /></n-icon>
                  </n-button>
                </template>
                清空输入
              </n-tooltip>
            </template>
            <div class="clear-confirm">
              <p>确认清空输入、附件和引用内容？</p>
              <div>
                <n-button size="small" @click="showClearConfirm = false">取消</n-button>
                <n-button size="small" type="error" @click="handleClearConfirm">确认清空</n-button>
              </div>
            </div>
          </n-popover>

          <template v-if="toolbar.send">
            <n-tooltip v-if="isStreaming" trigger="hover">
              <template #trigger>
                <n-button circle class="send-btn stop-btn" aria-label="停止生成" @click="handleStop">
                  <span class="stop-square" aria-hidden="true" />
                </n-button>
              </template>
              停止生成
            </n-tooltip>

            <template v-else-if="isPaused">
              <n-tooltip trigger="hover">
                <template #trigger>
                  <n-button circle class="send-btn resume-btn" aria-label="继续生成" @click="handleResume">
                    <template #icon><n-icon size="18"><PlayOutline /></n-icon></template>
                  </n-button>
                </template>
                继续生成
              </n-tooltip>
              <n-tooltip trigger="hover">
                <template #trigger>
                  <n-button circle class="send-btn regenerate-btn" aria-label="重新生成" @click="handleRegenerate">
                    <template #icon><n-icon size="18"><RefreshOutline /></n-icon></template>
                  </n-button>
                </template>
                重新生成
              </n-tooltip>
            </template>

            <n-tooltip v-else trigger="hover">
              <template #trigger>
                <n-button
                  circle
                  class="send-btn"
                  :class="{ active: canSend }"
                  :type="canSend ? 'primary' : 'default'"
                  :disabled="!canSend || disabled || sendLoading"
                  :loading="sendLoading"
                  aria-label="发送消息"
                  @click="handleSend"
                >
                  <template #icon><n-icon size="18"><ArrowUpOutline /></n-icon></template>
                </n-button>
              </template>
              发送消息（Enter）
            </n-tooltip>
          </template>
        </div>
      </div>
    </div>
    <p v-if="props.hint" class="input-hint-below">{{ props.hint }}</p>
    <p v-if="isPaused" class="ai-composer__disclaimer">
      <span class="paused-hint" role="status">生成已暂停。</span>
    </p>
  </div>
  <NModal v-model:show="agentTeamsCaseVisible" preset="card" title="创建协作 Case" :style="{ width: 'min(92vw, 560px)' }" :mask-closable="!agentTeamsCaseSubmitting">
    <NForm label-placement="top" @submit.prevent="submitAgentTeamsCase">
      <NFormItem label="交付目标" required>
        <NInput v-model:value="agentTeamsCaseForm.objective" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" maxlength="500" show-count />
      </NFormItem>
      <NFormItem label="项目 ID" required><NInput v-model:value="agentTeamsCaseForm.project_id" /></NFormItem>
      <NFormItem label="流程 ID" required><NInput v-model:value="agentTeamsCaseForm.flow_id" placeholder="例如 rna_seq 或 treeplot" /></NFormItem>
      <div class="agentteams-case-actions">
        <NButton :disabled="agentTeamsCaseSubmitting" @click="agentTeamsCaseVisible = false">取消</NButton>
        <NButton type="primary" attr-type="submit" :loading="agentTeamsCaseSubmitting">确认并创建</NButton>
      </div>
    </NForm>
  </NModal>
</template>

<style scoped lang="scss">
.ai-composer-shell {
  width: 100%;
  min-width: 0;
}

/* 待回答 pill：毛玻璃轻量提示，点击平滑滚动到待回答卡片 */
.ask-pending-pill {
  display: block;
  margin: 0 auto var(--space-sm);
  padding: 6px 14px;
  font-size: 12px;
  line-height: 18px;
  color: var(--chat-accent, var(--arco-primary));
  background: color-mix(in srgb, var(--chat-ai-card, var(--neutral-card)) 82%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 45%, transparent);
  border-radius: 999px;
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));
  cursor: pointer;
  user-select: none;
  transition: border-color 0.15s ease, background-color 0.15s ease;

  &:hover {
    border-color: var(--chat-accent, var(--arco-primary));
    background: color-mix(in srgb, var(--chat-ai-card, var(--neutral-card)) 92%, transparent);
  }
}

.ask-pill-enter-active,
.ask-pill-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.ask-pill-enter-from,
.ask-pill-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

/* 输入框容器顶部的常驻细条提示（与 pill 同视觉体系） */
.ask-waiting-bar {
  margin-bottom: var(--space-sm);
  padding: 4px 10px;
  font-size: 12px;
  line-height: 18px;
  color: var(--chat-text-secondary, var(--neutral-text-2));
  background: color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 20%, transparent);
  border-radius: 6px;
  user-select: none;
}
.agentteams-case-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); }

.input-hint-below {
  margin: var(--space-xs) 0 0;
  color: var(--neutral-text-3);
  font-size: 12px;
  line-height: 18px;
  text-align: right;
  user-select: none;
}

.goal-status-dock {
  margin-bottom: var(--space-md, 16px);
}

.drag-overlay-enter-active,
.drag-overlay-leave-active {
  transition: opacity 160ms ease-out;
}

.drag-overlay-enter-from,
.drag-overlay-leave-to {
  opacity: 0;
}

.kimi-chat-input {
  position: relative;
  min-width: 0;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-lg);
  box-shadow: none;
  padding: var(--space-md) var(--space-lg);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;

  &.room-mode {
    padding: var(--space-md) var(--space-lg) var(--space-sm);
    border-color: color-mix(in srgb, var(--arco-primary) 32%, var(--neutral-border));
    border-radius: 20px;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 10%, transparent);
  }

  &:focus-within {
    border-color: var(--arco-primary);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 18%, transparent);
  }

  &.room-mode:focus-within {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--arco-primary) 18%, transparent);
  }

  &.disabled {
    opacity: 0.72;
  }

  .input-wrapper {
    position: relative;
    min-height: 0;
  }

  &.room-mode {
    .input-wrapper {
      padding: 2px 4px 0;
    }

    .input-highlight {
      /* inset:0 对齐的是 wrapper 的 padding box，不含上面的 padding；
         textarea 在内容盒里（右移 4px、下移 2px），不收进内容盒就会与
         透明文字错位形成重影。 */
      inset: 2px 4px 0;
    }

    .input-highlight,
    .chat-textarea :deep(.n-input__textarea-el) {
      min-height: 56px;
      padding-top: 8px;
      padding-bottom: 8px;
      line-height: 24px;
    }

    .ref-bar {
      max-height: 84px;
      overflow-y: auto;
      padding: 2px 0;
      scrollbar-width: thin;
    }

    .input-toolbar {
      margin-top: var(--space-xs);
      padding-top: var(--space-sm);
    }
  }

  .input-highlight {
    position: absolute;
    inset: 0;
    /* 必须与下方 textarea(.n-input__textarea-el) 排版完全一致，否则透明文字的光标
       会与可见高亮文字错位。textarea 的 padding 已在组件样式里显式锁为 6.5px 0
       （不依赖 naive-ui 主题变量），这里保持同值。 */
    padding: 6.5px 0;
    pointer-events: none;
    color: var(--chat-text-primary, var(--neutral-text-1));
    font-family: inherit;
    font-size: 15px;
    line-height: 24px;
    letter-spacing: normal;
    white-space: pre-wrap;
    /* word-break 必须与 naive-ui textarea-el 的 break-word 一致，
       否则长 token（如 @长名称 / 文件路径）折行点不同，mention 之后整段错位。 */
    word-break: break-word;
    overflow-wrap: break-word;
    overflow: hidden;
    z-index: 0;
  }

  /* mention 高亮只允许不影响文字量度的样式：inline-block/padding/font-weight
     会改变字形宽度，mention 之后的字符与透明 textarea 文字错位（视觉重影）。 */
  .input-highlight :deep(.mention-chip) {
    border-radius: 4px;
    background: var(--arco-primary-light);
    color: var(--arco-primary);
  }

  /* IME 组合期间：naive-ui 在 composition 中不更新 v-model，overlay 拿不到正在输入的
     拼音/候选文本；而 textarea 文字是透明的，导致组合文本不可见、光标看似漂移。
     组合期间临时隐藏 overlay 并让 textarea 文字可见，结束后恢复高亮层。 */
  .input-wrapper.is-composing .input-highlight {
    visibility: hidden;
  }

  .input-wrapper.is-composing .chat-textarea :deep(.n-input__textarea-el) {
    color: var(--chat-text-primary, var(--neutral-text-1));
  }

  &.popup-open {
    border-radius: var(--radius-lg);
  }

  &.popup-open :deep(.slash-command-menu),
  &.popup-open :deep(.mention-menu),
  &.popup-open :deep(.mcp-selection-menu) {
    position: relative;
    left: auto;
    right: auto;
    bottom: auto;
    width: calc(100% + (var(--space-lg) * 2));
    margin: calc(var(--space-md) * -1) calc(var(--space-lg) * -1) var(--space-md);
    border: none;
    border-bottom: 1px solid var(--neutral-border);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    box-shadow: none;
  }

  :deep(.composer-menu-enter-active),
  :deep(.composer-menu-leave-active) {
    transition: opacity 180ms ease-out, transform 180ms ease-out;
    transform-origin: bottom;
  }

  :deep(.composer-menu-enter-from),
  :deep(.composer-menu-leave-to) {
    opacity: 0;
    transform: translateY(8px);
  }

  &.drag-over {
    border-color: var(--arco-primary);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 18%, transparent);
  }

  .drag-drop-overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-lg);
    background: color-mix(in srgb, var(--neutral-card) 86%, transparent);
    backdrop-filter: blur(2px);
  }

  .drag-drop-hint {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-xs);
    padding: var(--space-md) var(--space-xl);
    color: var(--arco-primary);
    font-size: 14px;
    font-weight: 500;
    border: 2px dashed var(--arco-primary);
    border-radius: var(--radius-lg);
    background: color-mix(in srgb, var(--arco-primary) 8%, transparent);

    small {
      color: var(--neutral-text-2);
      font-size: 12px;
      font-weight: 400;
    }
  }

  .ref-bar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-bottom: var(--space-sm);

    .ref-chip {
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .attachment-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-width: 0;
      max-width: 280px;
      height: 28px;
      padding: 0 4px 0 9px;
      color: var(--neutral-text-2);
      font-size: 12px;
      line-height: 1;
      border: 1px solid var(--neutral-border);
      border-radius: 999px;
      background: var(--neutral-fill-2);
    }

    .attachment-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .attachment-remove {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      padding: 0;
      color: var(--neutral-text-3);
      border: 0;
      border-radius: 50%;
      background: transparent;
      cursor: pointer;
      transition: color var(--motion-quick, 140ms) ease-out, background-color var(--motion-quick, 140ms) ease-out;

      &:hover {
        color: var(--arco-danger);
        background: color-mix(in srgb, var(--arco-danger) 10%, transparent);
      }

      &:focus-visible {
        outline: 2px solid var(--arco-primary);
        outline-offset: 1px;
      }
    }

    .ref-file {
      color: var(--arco-primary);
      background: var(--arco-primary-light);
    }

    .ref-directory {
      color: var(--chat-text-primary);
      background: var(--icon-cyan-bg);
    }

    .attachment-status {
      color: var(--chat-text-secondary);
      font-size: 11px;
    }

    .ref-agent {
      color: var(--neutral-text-1);
      background: var(--neutral-hover);
    }

    .ref-skill {
      color: var(--neutral-text-1);
      background: var(--neutral-hover);
    }

    .star-context-tag {
      max-width: 240px;
      color: var(--neutral-text-2);
      background: var(--neutral-hover);
      border-radius: var(--radius-sm);
      font-size: 12px;
      font-weight: 500;
    }

    .star-context-tag--mode {
      color: var(--brand-primary);
      background: var(--brand-primary-light);
    }

    .star-context-tag--permission {
      color: var(--neutral-text-1);
      background: var(--surface-highlight);
    }

    .star-context-tag--goal {
      max-width: min(360px, 100%);
      color: var(--neutral-text-2);
      background: transparent;
      box-shadow: inset 0 0 0 1px var(--neutral-border);
    }
  }

  .chat-textarea {
    position: relative;
    width: 100%;
    background: transparent;
    z-index: 1;

    :deep(.n-input) {
      color: var(--chat-text-primary, var(--neutral-text-1));
      background: transparent;
    }

    :deep(.n-input__textarea) {
      background: transparent;
    }

    :deep(.n-input-wrapper) {
      padding: 0;
      background: transparent;
      border: 0;
      box-shadow: none;
    }

    :deep(.n-input-wrapper:hover),
    :deep(.n-input.n-input--focus .n-input-wrapper) {
      box-shadow: none;
    }

    :deep(.n-input__textarea-el) {
      max-height: 200px;
      /* 显式锁死内边距，与 .input-highlight 完全一致：naive-ui 默认
         padding-top/bottom 来自主题变量 --n-padding-vertical（按 14px 字号
         算出 5.8px），而 overlay 是 6.5px，依赖它会产生纵向重影。 */
      padding: 6.5px 0;
      color: var(--chat-text-primary, var(--neutral-text-1));
      caret-color: var(--chat-text-primary, var(--neutral-text-1));
      background: transparent;
      font-family: inherit;
      font-size: 15px;
      line-height: 24px;
      resize: none;
    }

    .input-wrapper.has-highlight .chat-textarea :deep(.n-input__textarea-el) {
      color: transparent;
    }

    :deep(.n-input__textarea-el::placeholder) {
      color: var(--chat-text-muted, var(--neutral-text-3));
    }
  }

  .input-toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-xs) var(--space-sm);
    border-top: 1px solid var(--neutral-border);
    padding-top: var(--space-sm);

    .toolbar-left,
    .toolbar-center,
    .toolbar-right {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: var(--space-xs);
    }

    .toolbar-center { flex: 1 1 auto; }
    .toolbar-right { margin-left: auto; flex: 0 0 auto; }

    .toolbar-btn {
      min-width: 40px;
      min-height: 40px;
      padding: 0 10px;
      color: var(--neutral-text-2);
      background: transparent;
      border: 1px solid transparent;
      border-radius: 8px;
      box-shadow: none;
      transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease;

      &:hover {
        color: var(--neutral-text-1);
        background: var(--neutral-hover);
      }

      &.active {
        color: var(--arco-primary);
        background: var(--arco-primary-light);
        border-color: color-mix(in srgb, var(--arco-primary) 30%, transparent);
      }

      .btn-label {
        margin-left: var(--space-xs);
        font-size: 13px;
      }

      &.clear-btn:hover {
        color: var(--arco-danger);
      }
    }

    .mcp-toolbar-trigger {
      position: relative;
    }

    .mcp-button-icon {
      position: relative;
      display: inline-flex;
    }

    .mcp-count-badge {
      position: absolute;
      top: -8px;
      right: -10px;
      min-width: 15px;
      padding: 0 3px;
      color: var(--text-on-primary);
      background: var(--arco-primary);
      border-radius: 8px;
      font-size: 9px;
      line-height: 15px;
      text-align: center;
    }

    .send-btn {
      width: 40px;
      height: 40px;
      color: var(--neutral-text-3);
      background: var(--neutral-hover);
      border: 1px solid var(--neutral-border);
      box-shadow: none;
      transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease;

      &:hover,
      &.active {
        color: var(--text-on-primary);
        background: var(--arco-primary);
        border-color: var(--arco-primary);
        box-shadow: none;
      }

      &:disabled {
        color: var(--neutral-text-3);
        background: var(--neutral-hover);
        border-color: var(--neutral-border);
        opacity: 1;
        cursor: not-allowed;
      }

      &.stop-btn {
        color: var(--text-on-primary);
        background: var(--arco-primary);
        border-color: var(--arco-primary);
      }

      .stop-square {
        display: block;
        width: 11px;
        height: 11px;
        background: var(--text-on-primary);
        border-radius: 2px;
      }

      &.resume-btn {
        color: var(--text-on-primary);
        background: var(--arco-success);
        border-color: var(--arco-success);
      }

      &.regenerate-btn {
        color: var(--neutral-text-2);
        background: var(--neutral-hover);

        &:hover {
          color: var(--text-on-primary);
          background: var(--arco-primary);
          border-color: var(--arco-primary);
        }
      }
    }
  }

}

.clear-confirm {
  text-align: center;

  p { margin: 0 0 var(--space-sm); font-size: 13px; }
  div { display: flex; justify-content: center; gap: var(--space-sm); }
}

.runtime-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;

  .runtime-option {
    width: 100%;
    padding: 6px 10px;
    color: var(--neutral-text-2);
    font-size: 13px;
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 150ms ease, color 150ms ease;

    &:hover {
      color: var(--neutral-text-1);
      background: var(--neutral-hover);
    }

    &.active {
      color: var(--arco-primary);
      background: var(--arco-primary-light);
      font-weight: 500;
    }
  }
}

.runtime-tip {
  max-width: 260px;
  font-size: 12px;
  line-height: 18px;

  .runtime-tip-image {
    margin-top: 4px;
    opacity: 0.75;
    word-break: break-all;
  }
}

.ai-composer__disclaimer {
  margin: var(--space-xs) 0 0;
  color: var(--neutral-text-3);
  font-size: 12px;
  line-height: 18px;
  text-align: center;
}

.paused-hint {
  margin-right: var(--space-xs);
  color: var(--arco-primary);
  font-weight: 500;
}

@media (max-width: 640px) {
  .kimi-chat-input { padding: var(--space-sm) var(--space-md); }
  .input-toolbar { align-items: flex-start; }
  .toolbar-center { flex-basis: 100%; order: 3; }
  .toolbar-right { margin-left: auto; }
  .toolbar-btn .btn-label { display: none; }
  .ref-bar .ref-chip { max-width: min(220px, calc(100vw - 112px)); }
}

@media (prefers-reduced-motion: reduce) {
  .kimi-chat-input,
  .input-toolbar .toolbar-btn,
  .input-toolbar .send-btn,
  .ask-pending-pill,
  .ask-pill-enter-active,
  .ask-pill-leave-active,
  :deep(.composer-menu-enter-active),
  :deep(.composer-menu-leave-active) {
    transition: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .kimi-chat-input:focus-within {
    border-width: 2px;
    box-shadow: none;
  }
}

@media (prefers-contrast: more) {
  .kimi-chat-input { border-width: 2px; }
  .kimi-chat-input:focus-within { border-width: 3px; box-shadow: none; }
}

</style>
