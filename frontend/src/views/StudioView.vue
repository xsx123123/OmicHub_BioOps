<script setup lang="ts">
/**
 * StudioView — OmicStudio AI 分析工作台（三栏布局，/studio/:sessionId?）
 *
 * 顶栏：会话名 / 绑定智能体徽章 / 模型 / 沙盒状态灯 / 返回与栏位开关
 * 左栏：工作台会话列表 + 工作区文件树（懒加载目录，点击预览）
 * 中栏：对话执行流（复用 agentHub store + KimiMessageList/KimiChatInput，
 *       Studio 代码工具经 provide 上下文渲染为 StudioCodeCard）
 * 右栏：研究结果列表 + 沙盒状态块
 */
import { ref, reactive, computed, watch, onMounted, onUnmounted, provide, nextTick, type Component } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { NButton, NCheckbox, NIcon, NInput, NSelect, NSwitch, NTag, NTooltip, NModal, NSpin, useMessage } from 'naive-ui'
import {
  ArrowBackOutline, RefreshOutline, FileTrayStackedOutline, ShareSocialOutline,
  PrintOutline, CloseCircleOutline, ConstructOutline, ChevronBackOutline, ChevronForwardOutline,
  AnalyticsOutline, ChatbubbleEllipsesOutline, CodeSlashOutline, DocumentTextOutline,
  FlaskOutline, GridOutline, PowerOutline, TimeOutline,
} from '@vicons/ionicons5'
import KimiMessageList from '@/components/ai-chat/KimiMessageList.vue'
import AskUserModal from '@/components/ai-chat/AskUserModal.vue'
import type { CollaborationRouteInfo } from '@/components/ai-chat/types'
import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'
import PendingApprovalBar, {
  type PendingApprovalItem,
  type PendingAskItem,
} from '@/components/ai-chat/PendingApprovalBar.vue'
import FilePickerModal from '@/components/FilePickerModal.vue'
import StudioFileTree from '@/components/studio/StudioFileTree.vue'
import StudioArtifactsPanel from '@/components/studio/StudioArtifactsPanel.vue'
import StudioWorkspaceEditor from '@/components/studio/StudioWorkspaceEditor.vue'
import SessionHistoryDrawer from '@/components/agent-workspace/SessionHistoryDrawer.vue'
import OverdriveToggle from '@/components/agent-workspace/OverdriveToggle.vue'
import { StudioContextKey } from '@/components/studio/context'
import { studioApi, type StudioSessionDTO, type SandboxStatus } from '@/api/studio'
import { shouldApplyServerUi, shouldApplyServerViewMode } from '@/utils/studioViewGuard'
import { useAgentHubStore } from '@/stores/agentHub'
import { useAuthStore } from '@/stores/auth'
import { displayName } from '@/utils/displayName'
import type { ChatMessage, FileAttachment, ToolCall } from '@/components/ai-chat/types'
import type { FilePickerItem } from '@/types'
import {
  inferStudioTaskKind,
  inferStudioTaskStatus,
  parseTaskUnderstanding,
} from '@/utils/studioPresentation'

const route = useRoute()
const router = useRouter()
const store = useAgentHubStore()
const authStore = useAuthStore()
const message = useMessage()

const sessionId = computed(() => (route.params.sessionId as string) || '')

const loading = ref(true)
const studioSessions = ref<StudioSessionDTO[]>([])
const sandboxStatus = ref<SandboxStatus>('absent')
const sandboxMetrics = ref({ cpu_percent: 0, memory_percent: 0, memory_used: 0, memory_limit: 0 })
const workspaceId = ref<string | null>(null)
const shareActive = ref(false)
const shareExpiresAt = ref<string | null>(null)
const input = ref('')

function taskIconComponent(kind: ReturnType<typeof inferStudioTaskKind>): Component {
  if (kind === 'single-cell') return FlaskOutline
  if (kind === 'transcriptomics') return AnalyticsOutline
  return DocumentTextOutline
}
const longRunSeconds = ref(0)
const longRunPlaceholder = computed(() => {
  if (!store.isStreaming) return '输入需求，@ 引用文件、技能或智能体，/ 查看快捷命令'
  if (longRunSeconds.value > 90) return '正在跑长任务，去倒杯咖啡？'
  if (longRunSeconds.value > 30) return '沙盒正在计算，代码和产物会实时同步…'
  return 'AI 正在执行，稍等片刻…'
})
let longRunTimer: ReturnType<typeof setInterval> | null = null
const showFilePicker = ref(false)
const importingFile = ref(false)
const showExtractSkill = ref(false)
const extractingSkill = ref(false)
const extractSkillForm = reactive({
  path: '',
  skill_id: '',
  name: '',
  description: '',
  usage_instructions: '',
  category: 'studio',
  icon: '🧪',
  confirm_no_secrets: false,
})

const fileTreeKey = ref(0)
const artifactsKey = ref(0)

const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
const rightSections = reactive({ artifacts: true, sandbox: true })
const leftWidth = ref(260)
const RIGHT_WIDTH_KEY = 'omichub:studio:right-width-v2'
function loadRightWidth(): number {
  const saved = Number(localStorage.getItem(RIGHT_WIDTH_KEY))
  return Number.isFinite(saved) && saved >= 200 && saved <= 320 ? saved : 232
}
// 右侧状态栏默认收窄到 232px，可拖拽 200~320px 并记忆。
const rightWidth = ref(loadRightWidth())

type StudioViewMode = 'chat' | 'split' | 'code'
const viewMode = ref<StudioViewMode>('chat')
// 用户已手动接管视图：会话内不再接受服务端 view_mode 回写（新会话时重置）。
// 流式期间 PATCH /ui 会被聊天事务行锁阻塞，服务端返回的是旧值，
// 轮询若无条件回写会把用户刚打开的分屏/代码面板打回 chat（问题⑦根因）。
const viewModeTouched = ref(false)
const splitRatio = ref(40)
const chatDrawerOpen = ref(false)
const historyOpen = ref(false)
const workspaceEditorRef = ref<InstanceType<typeof StudioWorkspaceEditor> | null>(null)
const followAi = ref(true)
const terminalCollapsed = ref(false)
const hibernateOnLeave = ref(true)

// ---------- 权限模式（supervised/plan/auto） ----------
const permissionMode = computed(() => store.studioPermissions.mode)
const isAutoMode = computed(() => permissionMode.value === 'auto')
const permissionOptions = [
  { label: '监督', value: 'supervised' },
  { label: '计划', value: 'plan' },
  { label: '放权', value: 'auto' },
]
const switchingPermissions = ref(false)

async function handlePermissionChange(mode: 'supervised' | 'plan' | 'auto') {
  if (switchingPermissions.value) return
  switchingPermissions.value = true
  try {
    await store.setStudioPermissions(mode)
    if (mode === 'auto') {
      message.warning('已切换到放权模式：所有工具将自动执行，不再等待批准')
    } else if (mode === 'plan') {
      message.info('已切换到计划模式：先批准完整计划，再自动执行本轮步骤')
    } else {
      message.success('已切换到监督模式：关键操作需你批准后执行')
    }
  } catch {
    message.error('权限模式切换失败，请重试')
  } finally {
    switchingPermissions.value = false
  }
}

function toggleRightSection(section: keyof typeof rightSections) {
  rightSections[section] = !rightSections[section]
}

function persistUiState() {
  if (!sessionId.value) return
  void studioApi.updateUi(sessionId.value, {
    view_mode: viewMode.value,
    split_ratio: splitRatio.value,
    follow_ai: followAi.value,
    terminal_collapsed: terminalCollapsed.value,
  }).catch(() => {})
}

function modeStorageKey(id = sessionId.value) { return `omichub:studio:${id}:view-mode` }
function handleTerminalCollapsedChanged(collapsed: boolean) {
  terminalCollapsed.value = collapsed
  persistUiState()
}
function setViewMode(mode: StudioViewMode) {
  viewModeTouched.value = true
  viewMode.value = mode
  if (sessionId.value) localStorage.setItem(modeStorageKey(), mode)
  if (mode !== 'code') chatDrawerOpen.value = false
  persistUiState()
}
async function openFileInEditor(path: string, options: { pin?: boolean; externallyChanged?: boolean } = {}) {
  if (viewMode.value === 'chat') setViewMode('split')
  await nextTick()
  await workspaceEditorRef.value?.openFile(path, options.pin, options.externallyChanged)
}
function handleEditorRunStarted(tool: ToolCall) {
  const current = store.currentSession
  if (!current) return
  current.messages.push({
    id: `studio-editor-run-${Date.now()}`,
    role: 'assistant',
    content: '',
    modelName: 'OmicStudio',
    toolCalls: [tool],
    createdAt: new Date().toISOString(),
  })
}

function handleEditorSaved(path: string) {
  const current = store.currentSession
  if (!current) return
  current.messages.push({
    id: `studio-edit-${Date.now()}`,
    role: 'system',
    content: `✏️ 你修改了 ${path}`,
    createdAt: new Date().toISOString(),
  })
}

// ---------- 工作区刷新（工具结果 / 重跑 / 消息流结束后触发） ----------
function refreshWorkspace() {
  fileTreeKey.value += 1
  artifactsKey.value += 1
  refreshStatus()
  refreshStudioSessions()
}
provide(StudioContextKey, { sessionId, refreshWorkspace, openFileInEditor })

async function refreshStatus() {
  if (!sessionId.value) return
  try {
    const detail = await studioApi.getSession(sessionId.value)
    const wasRunning = sandboxStatus.value === 'running'
    sandboxStatus.value = detail.sandbox_status
    sandboxMetrics.value = detail.sandbox_metrics || { cpu_percent: 0, memory_percent: 0, memory_used: 0, memory_limit: 0 }
    workspaceId.value = detail.workspace_id
    if (!wasRunning && detail.sandbox_status === 'running' && store.isStreaming) message.success('沙盒已点火，工作区准备就绪 🚀')
    // 流式进行中服务端的 plan 可能尚未提交（聊天事务末尾才 commit），
    // 此时空值不覆盖面板上的实时计划，避免待办"出现一下就消失"
    if (detail.plan?.steps?.length) store.currentPlan = detail.plan.steps
    else if (!store.isStreaming) store.currentPlan = []
    if (detail.ui) {
      // 流式期间 PATCH /ui 被聊天事务行锁阻塞，GET 拿到的是旧值；
      // 此时一律不用服务端 UI 状态覆盖本地（用户手动操作优先，见 studioViewGuard）。
      if (shouldApplyServerUi(store.isStreaming)) {
        followAi.value = detail.ui.follow_ai
        terminalCollapsed.value = detail.ui.terminal_collapsed
        hibernateOnLeave.value = detail.ui.hibernate_on_leave
        splitRatio.value = detail.ui.split_ratio
        if (shouldApplyServerViewMode(store.isStreaming, viewModeTouched.value, detail.ui.view_mode)) viewMode.value = detail.ui.view_mode
      }
    }
    shareActive.value = detail.share?.active || false
    shareExpiresAt.value = detail.share?.expires_at || null
  } catch {
    // 状态刷新失败不阻塞页面
  }
}

async function refreshStudioSessions() {
  try {
    studioSessions.value = await studioApi.listSessions()
  } catch {
    studioSessions.value = []
  }
}

// ---------- 会话进入 ----------
async function enterSession(id: string) {
  try {
    const detail = await studioApi.getSession(id)
    const wasRunning = sandboxStatus.value === 'running'
    sandboxStatus.value = detail.sandbox_status
    sandboxMetrics.value = detail.sandbox_metrics || { cpu_percent: 0, memory_percent: 0, memory_used: 0, memory_limit: 0 }
    workspaceId.value = detail.workspace_id
    if (!wasRunning && detail.sandbox_status === 'running' && store.isStreaming) message.success('沙盒已点火，工作区准备就绪 🚀')
    // 同 refreshStatus：流式中服务端 plan 未提交时用空值覆盖会清掉面板实时计划
    if (detail.plan?.steps?.length) store.currentPlan = detail.plan.steps
    else if (!store.isStreaming) store.currentPlan = []
    if (detail.ui) {
      // 同 refreshStatus：流式中服务端 UI 状态可能是未提交的旧值，不覆盖本地；
      // 用户手动接管视图后也不再接受服务端 view_mode 回写。
      if (shouldApplyServerUi(store.isStreaming)) {
        followAi.value = detail.ui.follow_ai
        terminalCollapsed.value = detail.ui.terminal_collapsed
        hibernateOnLeave.value = detail.ui.hibernate_on_leave
        splitRatio.value = detail.ui.split_ratio
        if (shouldApplyServerViewMode(store.isStreaming, viewModeTouched.value, detail.ui.view_mode)) viewMode.value = detail.ui.view_mode
      }
    }
    shareActive.value = detail.share?.active || false
    shareExpiresAt.value = detail.share?.expires_at || null
    store.initStudioPermissions(detail.permissions?.mode)
    // 复用 agentHub 会话编排：注入 studio 会话后走统一的 selectSession/sendMessage 路径
    if (!store.sessions.find((s) => s.id === id)) {
      store.sessions.unshift({
        id,
        title: detail.session.title,
        agent_id: detail.session.agent_id || '',
        mode: detail.session.mode,
        messages: [],
        created_at: detail.session.created_at,
        updated_at: detail.session.updated_at,
        model_id: detail.session.model_id || undefined,
        multi_agent: Boolean(detail.session.multi_agent),
        overdrive: Boolean(detail.session.overdrive),
      })
    } else {
      const current = store.sessions.find((s) => s.id === id)
      if (current) {
        current.mode = detail.session.mode
        current.multi_agent = Boolean(detail.session.multi_agent)
        current.overdrive = Boolean(detail.session.overdrive)
      }
    }
    await store.selectSession(id)
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 404) {
      message.error('Studio 会话不存在或无权访问')
      if (studioSessions.value.length) {
        router.replace({ name: 'studio', params: { sessionId: studioSessions.value[0].session_id } })
      } else {
        router.replace({ name: 'studio' })
      }
    } else {
      // 5xx/网络错误多为瞬态故障（如后端重启中）：保留当前路由，提示重试，不误报"会话不存在"
      message.error('工作台加载失败，请稍后重试')
    }
  }
}

watch(
  sessionId,
  async (id) => {
    // 新会话重置"用户已接管视图"标记，恢复服务端同步
    viewModeTouched.value = false
    const savedMode = id ? localStorage.getItem(modeStorageKey(id)) : null
    viewMode.value = savedMode === 'split' || savedMode === 'code' ? savedMode : 'chat'
    loading.value = true
    await refreshStudioSessions()
    if (!id) {
      // /studio 无参：有历史会话则跳到最近一个，否则展示空态引导
      if (studioSessions.value.length) {
        router.replace({ name: 'studio', params: { sessionId: studioSessions.value[0].session_id } })
        return
      }
      loading.value = false
      return
    }
    await enterSession(id)
    loading.value = false
  },
  { immediate: true },
)

let statusTimer: ReturnType<typeof setInterval> | null = null

function handleStudioFileChanged(event: Event) {
  const detail = (event as CustomEvent<{ sessionId: string; path: string }>).detail
  if (!detail || detail.sessionId !== sessionId.value || !detail.path) return
  refreshWorkspace()
  if (followAi.value) {
    void openFileInEditor(detail.path, { pin: true, externallyChanged: true })
  } else {
    void workspaceEditorRef.value?.markFileChanged(detail.path)
  }
}

onMounted(async () => {
  // 智能体徽章 / 模型名 / 发消息均依赖这两项资产
  if (!store.agents.length) await store.fetchAgents(true)
  if (!store.availableModels.length) await store.fetchAvailableModels()
  statusTimer = setInterval(refreshStatus, 10_000)
  longRunTimer = setInterval(() => { if (store.isStreaming) longRunSeconds.value += 1; else longRunSeconds.value = 0 }, 1000)
  window.addEventListener('omichub:studio-file-changed', handleStudioFileChanged)
})

async function hibernateCurrentSandbox(showFeedback = false) {
  const id = sessionId.value
  if (!id || store.isStreaming || !hibernateOnLeave.value) return
  try {
    const result = await studioApi.hibernateSession(id)
    if (result.status === 'hibernated') {
      sandboxStatus.value = 'absent'
      if (showFeedback) message.success('沙盒已休眠，工作区快照已保留')
    }
  } catch {
    if (showFeedback) message.warning('沙盒暂未释放，将由空闲回收任务处理')
  }
}

onBeforeRouteLeave(async () => {
  await hibernateCurrentSandbox(false)
})

onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
  statusTimer = null
  if (longRunTimer) clearInterval(longRunTimer)
  longRunTimer = null
  window.removeEventListener('omichub:studio-file-changed', handleStudioFileChanged)
  void hibernateCurrentSandbox(false)
})

// 消息流结束后刷新文件树 / 产物 / 沙盒状态
watch(
  () => store.isStreaming,
  (cur, prev) => {
    if (prev && !cur) {
      // 流式期间 PATCH /ui 会被行锁阻塞，结束后补写一次让服务端收敛到本地状态
      persistUiState()
      refreshWorkspace()
    }
  },
)

// ---------- 顶栏信息 ----------
const session = computed(() => store.currentSession)
const agent = computed(() => (session.value ? store.getAgent(session.value.agent_id) : null))
const overdriveEnabled = computed({
  get: () => Boolean(session.value?.overdrive),
  set: (value: boolean) => {
    if (session.value) session.value.overdrive = value
  },
})

// ---------- Studio HITL：待审批 / 待澄清浮动条 ----------
const messageListRef = ref<InstanceType<typeof KimiMessageList> | null>(null)

/** 当前会话所有待审批的工具调用（状态源为消息的 tool.approval，此处仅派生） */
const pendingApprovals = computed<PendingApprovalItem[]>(() => {
  const items: PendingApprovalItem[] = []
  for (const msg of session.value?.messages || []) {
    for (const tc of msg.toolCalls || []) {
      if (tc.approval?.status === 'pending') {
        items.push({ approvalId: tc.approval.approval_id, messageId: msg.id, tool: tc })
      }
    }
  }
  return items
})

/** 最近一条待回答的 ask_user 澄清 */
const pendingAsk = computed<PendingAskItem | null>(() => {
  const msgs = session.value?.messages || []
  for (let i = msgs.length - 1; i >= 0; i--) {
    const ask = msgs[i].askRequest
    if (ask && !ask.answered && ask.questions.length) {
      const first = ask.questions[0]
      const summary = ask.questions.length > 1
        ? `${first.question}（共 ${ask.questions.length} 问）`
        : first.question
      return { messageId: msgs[i].id, question: summary, options: first.options }
    }
  }
  return null
})

/** 最近一条待回答 ask_user 的完整请求，供统一确认弹窗复用同一套问题向导。 */
const pendingAskModal = computed(() => {
  const msgs = session.value?.messages || []
  for (let i = msgs.length - 1; i >= 0; i--) {
    const ask = msgs[i].askRequest
    if (ask && !ask.answered && ask.questions.length) {
      return { messageId: msgs[i].id, ask }
    }
  }
  return null
})

const askModalOpen = ref(false)
watch(
  () => pendingAskModal.value?.messageId,
  (messageId, previousMessageId) => {
    if (messageId && messageId !== previousMessageId) askModalOpen.value = true
  },
  { immediate: true },
)

async function handleAskModalSubmit(answers: string[]): Promise<void> {
  try {
    await store.answerAskRequest(answers)
    askModalOpen.value = false
  } catch {
    message.error('确认发送失败，请重试')
  }
}

/** 新审批/澄清到达时跟随滚动到底部；仅在距底 100px 阈值内才自动滚动，
 *  用户上翻阅读时不打断，由"回到底部"红点与输入框上方待回答 pill 提示 */
watch(
  () => pendingApprovals.value.length + (pendingAsk.value ? 1 : 0),
  (count, prev) => {
    if (count > (prev ?? 0)) {
      nextTick(() => messageListRef.value?.scrollToBottom())
    }
  },
)

/** 点击浮动条条目：定位到消息流中的对应内联卡片 */
function locateMessage(messageId: string) {
  messageListRef.value?.scrollToMessage(messageId)
}

const modelName = computed(() => {
  const id = session.value?.model_id
  if (id) {
    const found = store.availableModels.find((m) => m.id === id)
    if (found) return found.name
  }
  return agent.value?.model_engine || '默认模型'
})

const modelOptions = computed(() => store.availableModels.map((model) => ({
  label: model.name,
  value: model.id,
})))

function handleModelSwitch(modelId: string | null) {
  const current = session.value
  if (!current || !modelId || current.model_id === modelId) return
  store.switchSessionModel(current.id, modelId)
  const name = store.availableModels.find((model) => model.id === modelId)?.name || modelId
  message.success(`已切换至 ${name}，后续执行将使用该模型`)
}

function handleRetryWithModel() {
  message.info('请先在顶栏切换模型，再点击“重试”重新执行当前任务')
}

const userDisplayName = computed(() => displayName(authStore.user) || '我')
const userAvatarUrl = computed(() => authStore.user?.avatar_url || '')
const taskUnderstanding = computed(() => parseTaskUnderstanding(session.value?.messages || [], store.isStreaming))

function sessionAgentName(item: StudioSessionDTO): string {
  if (!item.agent_id) return ''
  return store.getAgent(item.agent_id)?.name || '科研智能体'
}

/** 沙盒状态灯：流式执行中按 启动中/运行中 展示，空闲展示真实状态 */
const statusInfo = computed(() => {
  if (store.isStreaming) {
    return sandboxStatus.value === 'running'
      ? { icon: '🟢', label: '运行中' }
      : { icon: '🟡', label: '启动中' }
  }
  switch (sandboxStatus.value) {
    case 'running': return { icon: '🟢', label: '运行中' }
    case 'stopped': return { icon: '⚪', label: '已回收' }
    case 'unavailable': return { icon: '🔴', label: '不可用' }
    default: return { icon: '🌙', label: '已休眠，工作区已保留' }
  }
})

// ---------- 交互 ----------
async function handleSend(
  content: string,
  options: { attachments?: FileAttachment[]; enableWebSearch?: boolean; enableCodeExecution?: boolean } = {},
) {
  if (!content.trim() && !options.attachments?.length) return
  if (store.isStreaming) return
  const currentId = sessionId.value
  const previousArtifactPaths = new Set<string>()
  if (currentId) {
    try {
      const artifacts = await studioApi.listArtifacts(currentId)
      artifacts.forEach((artifact) => previousArtifactPaths.add(artifact.path))
    } catch {
      // 产物列表暂不可用时不阻塞用户发起分析，结束后仍会统一刷新。
    }
  }
  try {
    await store.sendMessage(content, options)
  } finally {
    refreshWorkspace()
    if (currentId) {
      try {
        const artifacts = await studioApi.listArtifacts(currentId)
        const latestReport = artifacts
          .filter((artifact) => !previousArtifactPaths.has(artifact.path))
          .filter((artifact) => /\.(md|markdown)$/i.test(artifact.path))
          .sort((left, right) => right.mtime - left.mtime)[0]
        if (latestReport) await openFileInEditor(latestReport.path, { pin: true })
      } catch {
        // 右栏会保留可重试错误状态；报告自动打开失败不影响本轮对话结果。
      }
    }
  }
  input.value = ''
}

function findSourceUserMessage(messageId: string): ChatMessage | undefined {
  const messages = session.value?.messages || []
  const index = messages.findIndex((item) => item.id === messageId)
  for (let cursor = index >= 0 ? index : messages.length - 1; cursor >= 0; cursor -= 1) {
    const candidate = messages[cursor]
    if (candidate.role === 'user') return candidate
  }
  return undefined
}

async function handleRegenerate(messageId: string) {
  if (store.isStreaming) {
    message.warning('请等待当前回复完成')
    return
  }
  const target = findSourceUserMessage(messageId)
  if (!target) return
  await handleSend(target.content, { attachments: target.attachments })
}

function handleEditMessage(messageId: string) {
  const target = findSourceUserMessage(messageId)
  if (!target) return
  input.value = target.content
  message.info('已填入输入框，修改后发送即可')
}

function handleCopy() {
  message.success('已复制')
}

function handleDeleteMessage(messageId: string) {
  const messages = session.value?.messages
  const index = messages?.findIndex((item) => item.id === messageId) ?? -1
  if (index < 0 || !messages) return
  messages.splice(index, 1)
  message.success('已从当前会话视图删除')
}

function handleCreateCaseFromConsultation(summary: string, consultationId?: string) {
  window.dispatchEvent(new CustomEvent('omichub:agentteams-create', {
    detail: { summary, consultationId },
  }))
}

function handleCorrectCollaborationRoute(route: CollaborationRouteInfo) {
  input.value = `我不想走“${route.label}”这条路径。请改为：`
}

function handleInsertArtifact(path: string) {
  input.value = (input.value ? `${input.value}\n` : '') + `请查看产物文件 ${path}`
  message.info(`已插入引用：${path}`)
}

function handleInsertWorkspaceReference(path: string) {
  input.value = (input.value ? `${input.value}\n` : '') + `请查看工作区文件 ${path}`
  message.info(`已插入工作区引用：${path}`)
}

async function handleImportFiles(items: FilePickerItem[]) {
  if (!sessionId.value || !items.length) return
  importingFile.value = true
  const imported: string[] = []
  try {
    for (const item of items) {
      const result = await studioApi.importDataFile(sessionId.value, {
        file_id: item.id,
        name: item.original_name,
      })
      imported.push(result.sandbox_path)
    }
    if (imported.length) {
      const references = imported.map((path) => `已引入文件：${path}`).join('\n')
      input.value = input.value ? `${input.value}\n${references}` : references
      refreshWorkspace()
      message.success(`已引入 ${imported.length} 个文件`)
    }
  } catch {
    message.error('文件引入失败，请确认文件仍可用')
  } finally {
    importingFile.value = false
  }
}

function openExtractSkill() {
  extractSkillForm.path = previewPath.value && /\.(py|r|R|sh|bash)$/.test(previewPath.value)
    ? previewPath.value
    : ''
  extractSkillForm.confirm_no_secrets = false
  showExtractSkill.value = true
}

async function handleExtractSkill() {
  if (!sessionId.value) return
  if (!extractSkillForm.path || !extractSkillForm.skill_id || !extractSkillForm.name) {
    message.warning('请填写脚本路径、Skill ID 和名称')
    return
  }
  if (!extractSkillForm.confirm_no_secrets) {
    message.warning('请先确认脚本不包含密钥、密码或用户隐私数据')
    return
  }
  extractingSkill.value = true
  try {
    const skill = await studioApi.extractSkill(sessionId.value, { ...extractSkillForm })
    await store.fetchSkills()
    showExtractSkill.value = false
    message.success(`已提炼并启用 Skill：${skill.name}`)
  } catch {
    message.error('Skill 提炼失败，请检查脚本路径、ID 唯一性和敏感信息')
  } finally {
    extractingSkill.value = false
  }
}

async function handleShare() {
  if (!sessionId.value) return
  if (shareActive.value && !window.confirm('创建新分享链接会立即使旧链接失效，是否继续？')) return
  try {
    const share = await studioApi.createShare(sessionId.value)
    const url = `${window.location.origin}${share.share_path}`
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(url)
      message.success('只读分享链接已复制，有效期 7 天')
    } else {
      window.prompt('请复制只读分享链接', url)
    }
    shareActive.value = true
    shareExpiresAt.value = share.expires_at
  } catch {
    message.error('分享链接创建失败')
  }
}

async function handleRevokeShare() {
  if (!sessionId.value || !shareActive.value) return
  if (!window.confirm('撤销后当前分享链接将立即失效，是否继续？')) return
  try {
    await studioApi.revokeShare(sessionId.value)
    shareActive.value = false
    shareExpiresAt.value = null
    message.success('分享链接已撤销')
  } catch {
    message.error('分享链接撤销失败')
  }
}

async function handleExportPdf() {
  if (!sessionId.value) return
  const popup = window.open('', '_blank')
  if (!popup) {
    message.error('浏览器阻止了新窗口，请允许弹窗后重试')
    return
  }
  popup.opener = null
  try {
    const html = await studioApi.exportPrintableReport(sessionId.value)
    popup.document.open()
    popup.document.write(html)
    popup.document.close()
    popup.focus()
  } catch {
    popup.close()
    message.error('报告导出失败')
  }
}


async function handleHibernateClick() {
  await hibernateCurrentSandbox(true)
  await refreshStatus()
}

async function handleBack() {
  await hibernateCurrentSandbox(true)
  store.newChat()
  router.push('/ai')
}

async function goSession(id: string) {
  if (id !== sessionId.value) {
    await hibernateCurrentSandbox(false)
    router.push({ name: 'studio', params: { sessionId: id } })
  }
}

function handleHistorySelect(session: { id: string }, messageId?: string) {
  if (session.id === sessionId.value) return
  router.push({
    name: 'studio',
    params: { sessionId: session.id },
    query: messageId ? { message: messageId } : {},
  })
}

// ---------- 文件预览（按类型分流，未知二进制绝不按文本读取） ----------
type PreviewKind = 'image' | 'table' | 'unsupported'
const showFilePreview = ref(false)
const previewPath = ref('')
const previewLoading = ref(false)
const previewKind = ref<PreviewKind>('unsupported')
const previewUrl = ref('')
const previewHeaders = ref<string[]>([])
const previewRows = ref<string[][]>([])

const editableExtensions = new Set(['py', 'r', 'sh', 'bash', 'js', 'ts', 'vue', 'json', 'yaml', 'yml', 'md', 'txt', 'html', 'css', 'scss', 'toml', 'ini', 'log'])
const imageExtensions = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'])
const tableExtensions = new Set(['csv', 'tsv'])

function parseDelimited(content: string, delimiter: string) {
  const rows = content.split(/\r?\n/).filter(Boolean).slice(0, 51).map((line) => line.split(delimiter))
  previewHeaders.value = rows.shift() || []
  previewRows.value = rows
}

async function handleSelectFile(path: string) {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  if (editableExtensions.has(ext)) {
    await openFileInEditor(path)
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewPath.value = path
  previewLoading.value = true
  previewHeaders.value = []
  previewRows.value = []
  showFilePreview.value = true
  try {
    if (imageExtensions.has(ext)) {
      previewKind.value = 'image'
      previewUrl.value = await studioApi.fetchWorkspaceBlob(sessionId.value, path)
    } else if (tableExtensions.has(ext)) {
      previewKind.value = 'table'
      const result = await studioApi.readFile(sessionId.value, path, 0, 51)
      parseDelimited(result.content, ext === 'tsv' ? '\t' : ',')
    } else {
      previewKind.value = 'unsupported'
    }
  } catch {
    previewKind.value = 'unsupported'
  } finally {
    previewLoading.value = false
  }
}

function closePreviewUrl() {
  if (previewUrl.value) {
    window.URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function startSplitResize(event: PointerEvent) {
  const host = (event.currentTarget as HTMLElement).parentElement
  if (!host) return
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  const move = (next: PointerEvent) => {
    const rect = host.getBoundingClientRect()
    splitRatio.value = Math.min(70, Math.max(25, ((next.clientX - rect.left) / rect.width) * 100))
  }
  const up = (next: PointerEvent) => {
    target.releasePointerCapture(next.pointerId)
    persistUiState()
    target.removeEventListener('pointermove', move)
    target.removeEventListener('pointerup', up)
  }
  target.addEventListener('pointermove', move)
  target.addEventListener('pointerup', up)
}

// ---------- 栏宽拖拽（FilesView startResize 模式） ----------
function startResizeLeft(e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = leftWidth.value
  const onMove = (ev: MouseEvent) => {
    leftWidth.value = Math.min(400, Math.max(200, startW + ev.clientX - startX))
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function startResizeRight(e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = rightWidth.value
  const onMove = (ev: MouseEvent) => {
    rightWidth.value = Math.min(320, Math.max(200, startW - (ev.clientX - startX)))
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    localStorage.setItem(RIGHT_WIDTH_KEY, String(rightWidth.value))
  }
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function formatSessionTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
</script>

<template>
  <main class="studio-view" aria-label="OmicStudio 工作台" :aria-busy="loading">
    <!-- 顶栏 -->
    <header class="studio-topbar">
      <div class="bar-left">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text class="back-btn" aria-label="返回 AI 助手" @click="handleBack">
              <n-icon size="18"><ArrowBackOutline /></n-icon>
            </n-button>
          </template>
          返回 AI 助手
        </n-tooltip>
        <div class="agent-identity">
          <span class="agent-primary">{{ agent?.avatar }} {{ agent?.name || '科研智能体' }}</span>
          <span class="model-secondary">Powered by {{ modelName }}</span>
        </div>
        <n-select
          v-if="modelOptions.length"
          :value="session?.model_id || null"
          :options="modelOptions"
          size="tiny"
          class="model-select"
          aria-label="选择工作台模型"
          :disabled="store.isStreaming"
          @update:value="handleModelSwitch"
        />
        <n-tag v-else size="small" round :bordered="false" class="model-tag">{{ modelName }}</n-tag>
      </div>
      <div class="bar-right">
        <OverdriveToggle v-model="overdriveEnabled" :disabled="store.isStreaming" compact />
        <n-tooltip v-if="sessionId" trigger="hover">
          <template #trigger>
            <span class="perm-switch" :class="{ auto: isAutoMode }">
              <span class="perm-label">{{ permissionMode === 'auto' ? '放权' : permissionMode === 'plan' ? '计划' : '监督' }}</span>
              <n-select
                :value="permissionMode"
                :options="permissionOptions"
                size="tiny"
                :loading="switchingPermissions"
                :consistent-menu-width="false"
                style="width: 76px"
                @update:value="handlePermissionChange"
              />
            </span>
          </template>
          {{ permissionMode === 'auto' ? '放权模式：工具自动执行，仍受循环护栏保护' : permissionMode === 'plan' ? '计划模式：先批准完整计划，再自动执行本轮步骤' : '监督模式：关键操作需逐步批准' }}
        </n-tooltip>
        <span class="sandbox-light" :title="`沙盒状态：${statusInfo.label}`">
          <span class="light-icon" :class="{ pulsing: store.isStreaming && sandboxStatus === 'running' }">{{ statusInfo.icon }}</span> {{ statusInfo.label }}
        </span>
        <n-tooltip v-if="authStore.isAdmin" trigger="hover">
          <template #trigger>
            <n-button text @click="openExtractSkill">
              <n-icon size="16"><ConstructOutline /></n-icon>
            </n-button>
          </template>
          将工作区脚本提炼为 Skill
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text @click="handleShare">
              <n-icon size="16"><ShareSocialOutline /></n-icon>
            </n-button>
          </template>
          创建只读分享链接
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text @click="handleExportPdf">
              <n-icon size="16"><PrintOutline /></n-icon>
            </n-button>
          </template>
          打印 / 保存为 PDF
        </n-tooltip>
        <n-tooltip v-if="shareActive" trigger="hover">
          <template #trigger>
            <n-button text type="error" @click="handleRevokeShare">
              <n-icon size="16"><CloseCircleOutline /></n-icon>
            </n-button>
          </template>
          撤销分享{{ shareExpiresAt ? `（有效至 ${new Date(shareExpiresAt).toLocaleString('zh-CN')}）` : '' }}
        </n-tooltip>
        <n-tooltip v-if="sandboxStatus === 'running'" trigger="hover">
          <template #trigger>
            <n-button text @click="handleHibernateClick">
              <n-icon size="16"><PowerOutline /></n-icon>
            </n-button>
          </template>
          释放沙盒（保留工作区快照）
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text @click="refreshWorkspace">
              <n-icon size="16"><RefreshOutline /></n-icon>
            </n-button>
          </template>
          刷新文件与产物
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text @click="leftCollapsed = !leftCollapsed">
              <n-icon size="16">
                <ChevronBackOutline v-if="!leftCollapsed" />
                <ChevronForwardOutline v-else />
              </n-icon>
            </n-button>
          </template>
          {{ leftCollapsed ? '展开左栏' : '收起左栏' }}
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text @click="rightCollapsed = !rightCollapsed">
              <n-icon size="16">
                <ChevronForwardOutline v-if="!rightCollapsed" />
                <ChevronBackOutline v-else />
              </n-icon>
            </n-button>
          </template>
          {{ rightCollapsed ? '展开右栏' : '收起右栏' }}
        </n-tooltip>
      </div>
    </header>

    <!-- 加载中 -->
    <div v-if="loading" class="studio-center" role="status" aria-live="polite">
      <n-spin size="medium" />
      <p class="center-tip">正在进入工作台…</p>
    </div>

    <!-- 空态：无 sessionId 且无历史工作台会话 -->
    <div v-else-if="!sessionId" class="studio-center">
      <div class="empty-icon">📊</div>
      <div class="empty-title">还没有工作台会话</div>
      <div class="empty-desc">工作台会话需要从 AI 助手的智能体发起</div>
      <n-button type="primary" @click="router.push('/ai')">从 AI 助手发起工作台会话</n-button>
    </div>

    <!-- 三栏主体 -->
    <div v-else class="studio-body">
      <!-- 左栏：会话列表 + 文件树 -->
      <aside v-show="!leftCollapsed" class="col-left" :style="{ width: leftWidth + 'px' }">
        <div class="col-block sessions-block">
          <div class="block-header">
            <n-icon size="14"><FileTrayStackedOutline /></n-icon>
            <span>分析任务</span>
            <n-button text size="tiny" class="history-trigger" title="历史会话" @click="historyOpen = true">
              <n-icon><TimeOutline /></n-icon>
            </n-button>
          </div>
          <div class="session-list">
            <div
              v-for="s in studioSessions"
              :key="s.session_id"
              class="session-item task-card"
              :class="{ active: s.session_id === sessionId }"
              @click="goSession(s.session_id)"
            >
              <span class="task-icon" aria-hidden="true">
                <NIcon :component="taskIconComponent(inferStudioTaskKind(s.title))" :size="16" />
              </span>
              <div class="task-card-body">
                <div class="s-title">{{ s.title }}</div>
                <div class="task-meta">
                  <span v-if="sessionAgentName(s)">{{ sessionAgentName(s) }}</span>
                  <span>{{ formatSessionTime(s.updated_at) }}</span>
                </div>
              </div>
              <span
                class="task-status-light"
                :class="`is-${inferStudioTaskStatus(s, sessionId, store.isStreaming)}`"
                :title="inferStudioTaskStatus(s, sessionId, store.isStreaming)"
              />
            </div>
            <div v-if="!studioSessions.length" class="block-empty">暂无工作台会话</div>
          </div>
        </div>

        <div class="col-block files-block">
          <div class="files-scroll">
            <StudioFileTree
              :session-id="sessionId"
              :refresh-key="fileTreeKey"
              @select="handleSelectFile"
              @refresh="refreshWorkspace"
              @import="showFilePicker = true"
              @reference="handleInsertWorkspaceReference"
            />
          </div>
        </div>

        <div class="resize-handle" title="拖拽调整宽度" @mousedown="startResizeLeft" />
      </aside>

      <!-- 中栏：对话 / 分屏 / 代码工作室 -->
      <main class="col-center">
        <div class="studio-modebar" role="tablist" aria-label="工作台视图">
          <button :class="{ active: viewMode === 'chat' }" @click="setViewMode('chat')"><n-icon><ChatbubbleEllipsesOutline /></n-icon>对话</button>
          <button :class="{ active: viewMode === 'split' }" @click="setViewMode('split')"><n-icon><GridOutline /></n-icon>分屏</button>
          <button :class="{ active: viewMode === 'code' }" @click="setViewMode('code')"><n-icon><CodeSlashOutline /></n-icon>代码</button>
          <span class="modebar-divider" />
          <button class="follow-ai-toggle" :class="{ active: followAi }" @click="followAi = !followAi; persistUiState()">✦ 跟随 AI</button>
        </div>
        <div v-if="session" class="studio-workbench" :class="`mode-${viewMode}`">
          <section
            v-show="viewMode !== 'code' || chatDrawerOpen"
            class="chat-pane"
            :class="{ drawer: viewMode === 'code' }"
            :style="viewMode === 'split' ? { width: `${splitRatio}%` } : undefined"
          >
            <div v-if="!session.messages.length" class="studio-chat-empty"><div class="empty-stars">✦ · ˚ ✧</div><strong>把工作台交给星光，把问题交给我们</strong><span>描述一个分析目标，AI 会在沙盒中创建代码、运行并整理产物。</span></div>
            <KimiMessageList
              ref="messageListRef"
              :messages="session.messages"
              :is-typing="store.isStreaming"
              :streaming-content="store.streamingContent"
              :streaming-thought="store.streamingThought"
              :model-name="agent?.name || 'AI 助手'"
              :user-name="userDisplayName"
              :user-avatar="userAvatarUrl"
              :agent-name="agent?.name"
              :agent-avatar="agent?.avatar"
              :agent-color="agent?.color"
              :session-id="sessionId"
              :target-message-id="String(route.query.message || '')"
              :task-understanding="taskUnderstanding"
              :plan-steps="store.currentPlan"
              @copy="handleCopy"
              @feedback="(id, type) => store.submitMessageFeedback(id, type)"
              @regenerate="handleRegenerate"
              @retry-with-model="handleRetryWithModel"
              @delete="handleDeleteMessage"
              @edit="handleEditMessage"
              @create-case-from-consultation="handleCreateCaseFromConsultation"
              @correct-collaboration-route="handleCorrectCollaborationRoute"
            />
            <PendingApprovalBar
              :approvals="pendingApprovals"
              :ask="pendingAsk"
              @locate="locateMessage"
            />
            <AskUserModal
              v-model:show="askModalOpen"
              :ask="pendingAskModal?.ask || null"
              @submit="handleAskModalSubmit"
            />
            <div class="input-area">
              <KimiChatInput
                v-model="input"
                :is-streaming="store.isStreaming"
                :placeholder="longRunPlaceholder"
                show-overdrive-control
                :overdrive-enabled="overdriveEnabled"
                @toggle-overdrive="overdriveEnabled = !overdriveEnabled"
                @send="handleSend"
                @stop="store.stopStreaming"
              />
            </div>
          </section>
          <div v-if="viewMode === 'split'" class="center-splitter" @pointerdown="startSplitResize" />
          <section v-if="viewMode !== 'chat'" class="code-pane" :style="viewMode === 'split' ? { width: `${100 - splitRatio}%` } : undefined">
            <StudioWorkspaceEditor
              ref="workspaceEditorRef"
              :session-id="sessionId"
              :sandbox-status="sandboxStatus"
              :terminal-collapsed="terminalCollapsed"
              @terminal-collapsed-changed="handleTerminalCollapsedChanged"
              @workspace-changed="refreshWorkspace"
              @user-saved="handleEditorSaved"
              @request-file="message.info('请从左侧工作区选择文件')"
              @run-started="handleEditorRunStarted"
            />
          </section>
          <button v-if="viewMode === 'code'" class="chat-fab" :class="{ open: chatDrawerOpen }" @click="chatDrawerOpen = !chatDrawerOpen">
            <n-icon><ChatbubbleEllipsesOutline /></n-icon><span v-if="store.isStreaming" class="unread-dot" />
          </button>
        </div>
      </main>

      <!-- 右栏：研究结果 + 沙盒状态 -->
      <aside v-show="!rightCollapsed" class="col-right" :style="{ width: rightWidth + 'px' }">
        <div class="resize-handle right" title="拖拽调整宽度" @mousedown="startResizeRight" />

        <div class="col-block artifacts-block">
          <button class="block-header accordion-header" @click="toggleRightSection('artifacts')"><span>研究结果</span><span class="accordion-chevron" :class="{ open: rightSections.artifacts }">⌄</span></button>
          <div v-show="rightSections.artifacts" class="block-scroll">
            <StudioArtifactsPanel
              :session-id="sessionId"
              :refresh-key="artifactsKey"
              @insert="handleInsertArtifact"
              @open="openFileInEditor"
            />
          </div>
        </div>

        <div class="col-block sandbox-block">
          <button class="block-header accordion-header" @click="toggleRightSection('sandbox')"><span>沙盒状态</span><span class="accordion-chevron" :class="{ open: rightSections.sandbox }">⌄</span></button>
          <div v-show="rightSections.sandbox" class="sandbox-info">
            <div class="info-row">
              <span class="info-label">状态</span>
              <span>{{ statusInfo.icon }} {{ statusInfo.label }}</span>
            </div>
            <div v-if="sandboxStatus !== 'running' && sandboxStatus !== 'unavailable'" class="snapshot-note">工作区快照保留中 · 下次运行自动恢复</div>
            <div class="metric-row"><div><span>CPU</span><b>{{ sandboxMetrics.cpu_percent.toFixed(1) }}%</b></div><div class="metric-track"><i :style="{ width: `${Math.min(100, sandboxMetrics.cpu_percent)}%` }" /></div></div>
            <div class="metric-row"><div><span>内存</span><b>{{ sandboxMetrics.memory_percent.toFixed(1) }}%</b></div><div class="metric-track"><i :style="{ width: `${Math.min(100, sandboxMetrics.memory_percent)}%` }" /></div></div>
            <div class="info-row">
              <span class="info-label">工作区</span>
              <span class="info-mono">/workspace</span>
            </div>
            <div class="info-row">
              <span class="info-label">会话 ID</span>
              <span class="info-mono">{{ (workspaceId || sessionId).slice(0, 8) }}</span>
            </div>
            <div class="retention-note">
              离开工作台后释放计算容器；工作区保留 7 天。已登记到结果报告中心的产物独立保存，不随工作区清理。
            </div>
          </div>
        </div>
      </aside>
    </div>

    <FilePickerModal
      v-model:show="showFilePicker"
      multiple
      @select="handleImportFiles"
    />

    <SessionHistoryDrawer v-model:show="historyOpen" mode="studio" @select="handleHistorySelect" />

    <n-modal
      v-model:show="showExtractSkill"
      preset="card"
      title="提炼为 Skill"
      style="max-width: 620px"
    >
      <div class="extract-skill-form">
        <label>脚本路径<n-input v-model:value="extractSkillForm.path" placeholder="例如 scripts/volcano.py" /></label>
        <div class="extract-grid">
          <label>Skill ID<n-input v-model:value="extractSkillForm.skill_id" placeholder="volcano-plot" /></label>
          <label>名称<n-input v-model:value="extractSkillForm.name" placeholder="火山图绘制" /></label>
        </div>
        <label>描述<n-input v-model:value="extractSkillForm.description" type="textarea" :rows="2" /></label>
        <label>使用说明<n-input v-model:value="extractSkillForm.usage_instructions" type="textarea" :rows="4" /></label>
        <n-checkbox v-model:checked="extractSkillForm.confirm_no_secrets">
          我已检查脚本，不包含 API Key、密码、访问令牌或用户隐私数据
        </n-checkbox>
        <div class="extract-actions">
          <n-button @click="showExtractSkill = false">取消</n-button>
          <n-button type="primary" :loading="extractingSkill" @click="handleExtractSkill">创建并启用 Skill</n-button>
        </div>
      </div>
    </n-modal>

    <!-- 工作区图片 / 表格 / 不支持类型预览 -->
    <n-modal
      v-model:show="showFilePreview"
      preset="card"
      :title="previewPath"
      style="width: min(1040px, 94vw); max-width: 1040px"
      @after-leave="closePreviewUrl"
    >
      <div class="preview-wrap">
        <n-spin v-if="previewLoading" size="medium" />
        <img v-else-if="previewKind === 'image' && previewUrl" :src="previewUrl" :alt="previewPath" class="workspace-image-preview">
        <div v-else-if="previewKind === 'table'" class="workspace-table-wrap">
          <table><thead><tr><th v-for="(header, index) in previewHeaders" :key="index">{{ header }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in previewRows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody></table>
          <small>仅展示前 50 行</small>
        </div>
        <div v-else class="unsupported-preview">
          <div class="unsupported-icon">◇</div><h3>暂不支持预览此文件</h3><p>为避免二进制乱码，OmicStudio 不会把未知格式强制按文本读取。</p>
          <n-button type="primary" secondary @click="studioApi.downloadWorkspaceFile(sessionId, previewPath)">下载文件</n-button>
        </div>
      </div>
    </n-modal>
  </main>
</template>

<style scoped lang="scss">
.studio-view {
  --chat-bg: var(--surface-base, var(--neutral-bg));
  --chat-surface: var(--surface-card, var(--neutral-card));
  --chat-surface-hover: var(--surface-highlight, var(--neutral-hover));
  --chat-sidebar-bg: var(--surface-card, var(--neutral-card));
  --chat-border: var(--border-subtle, var(--neutral-border));
  --chat-user-bubble: var(--surface-highlight, var(--neutral-hover));
  --chat-user-text: var(--text-primary, var(--neutral-text-1));
  --chat-ai-card: var(--surface-elevated, var(--neutral-card));
  --chat-input-bg: var(--neutral-card);
  --chat-input-border: var(--neutral-border);
  --chat-nav-bg: var(--surface-card, var(--neutral-card));

  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--chat-bg);
  color: var(--chat-text-primary, inherit);
}

/* ---------- 顶栏 ---------- */
.studio-topbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--chat-border);
  background: var(--chat-nav-bg, var(--chat-bg));
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.agent-identity { display: flex; min-width: 0; flex-direction: column; line-height: 1.2; }
.agent-primary { max-width: 260px; overflow: hidden; color: var(--text-primary, var(--chat-text-primary)); font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.model-secondary { margin-top: 2px; color: var(--text-tertiary, var(--chat-text-muted)); font-size: 10px; }
.agent-tag,
.model-tag {
  flex-shrink: 0;
}
.model-select {
  width: 150px;
  flex-shrink: 0;
}
.bar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.sandbox-light {
  font-size: 12px;
  color: var(--chat-text-secondary, #666);
  margin-right: 6px;
  white-space: nowrap;
}
/* 流式执行期间绿点轻微脉动，与对话内的运行指示呼应（问题⑤） */
.sandbox-light .light-icon.pulsing {
  display: inline-block;
  animation: sandbox-light-pulse 1.4s ease-in-out infinite;
}
@keyframes sandbox-light-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
@media (prefers-reduced-motion: reduce) {
  .sandbox-light .light-icon.pulsing { animation: none; }
}

/* 权限模式开关（auto 放权模式警示色） */
.perm-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 8px;
  padding: 3px 10px;
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 999px;
  cursor: pointer;
}
.perm-label {
  font-size: 12px;
  color: var(--chat-text-secondary, #666);
  white-space: nowrap;
}
.perm-switch.auto {
  border-color: rgba(240, 100, 32, 0.6);
  background: rgba(240, 100, 32, 0.08);
}
.perm-switch.auto .perm-label {
  color: #e06420;
  font-weight: 600;
}

/* ---------- 居中态 ---------- */
.studio-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.center-tip {
  font-size: 13px;
  color: var(--chat-text-muted, #999);
}
.empty-icon { font-size: 44px; }
.empty-title { font-size: 16px; font-weight: 600; }
.empty-desc { font-size: 13px; color: var(--chat-text-muted, #999); margin-bottom: 8px; }

/* ---------- 三栏 ---------- */
.studio-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.col-left {
  position: relative;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--chat-border);
  background: var(--chat-sidebar-bg, var(--chat-bg));
  min-height: 0;
}
.col-right {
  position: relative;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--chat-border);
  background: var(--chat-sidebar-bg, var(--chat-bg));
  min-height: 0;
  overflow-y: auto;
}

.resize-handle {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
}
.resize-handle.right {
  right: auto;
  left: -3px;
}
.resize-handle:hover {
  background: rgba(79, 142, 247, 0.25);
}

.col-block {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-bottom: 1px solid var(--chat-border, #eee);
}
.sessions-block {
  max-height: 40%;
}
.files-block {
  flex: 1;
  border-bottom: none;
}
.block-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--chat-text-muted, #888);
  flex-shrink: 0;
}
.history-trigger { margin-left: auto; color: var(--studio-primary); }
.session-list {
  overflow-y: auto;
  padding: 0 8px 8px;
}
.session-item {
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.task-card { display: grid; grid-template-columns: 30px minmax(0, 1fr) 10px; align-items: center; gap: 8px; min-height: 52px; border: 1px solid transparent; border-radius: 12px; }
.task-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 10px; color: var(--studio-primary); background: var(--surface-highlight, var(--chat-surface-hover)); }
.task-card-body { min-width: 0; }
.task-meta { display: flex; gap: 6px; margin-top: 3px; color: var(--text-tertiary, var(--chat-text-muted)); font-size: 10px; }
.task-meta span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta span + span::before { margin-right: 6px; content: '·'; }
.task-status-light { width: 8px; height: 8px; border-radius: 50%; background: var(--text-tertiary, var(--chat-text-muted)); }
.task-status-light.is-completed { background: var(--success-color, var(--brand-primary)); }
.task-status-light.is-running { background: var(--brand-primary, var(--stardust-blue)); box-shadow: 0 0 0 4px var(--brand-primary-light, var(--chat-surface-hover)); animation: task-status-pulse 1.6s ease-in-out infinite; }
.task-status-light.is-waiting { background: var(--warning-color, var(--text-tertiary)); }
.session-item:hover {
  background: var(--chat-surface-hover, rgba(0, 0, 0, 0.04));
}
.session-item.active {
  background: rgba(79, 142, 247, 0.12);
}
.session-item.active .s-title {
  color: var(--chat-accent, #4f8ef7);
}
.s-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.s-time {
  font-size: 11px;
  color: var(--chat-text-muted, #aaa);
}
.block-empty {
  font-size: 12px;
  color: var(--chat-text-muted, #aaa);
  padding: 8px 10px;
}
.files-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.block-footer {
  flex-shrink: 0;
  padding: 8px 10px;
  border-top: 1px solid var(--chat-border, #eee);
}
.import-btn-wrap {
  display: block;
}

/* ---------- 中栏 ---------- */
.col-center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.input-area {
  flex-shrink: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--chat-border);
}
@keyframes task-status-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }

/* ---------- 右栏块 ---------- */
.artifacts-block {
  max-height: 55%;
}
.block-scroll {
  overflow-y: auto;
  padding: 0 10px 10px;
}
.sandbox-block {
  flex-shrink: 0;
  border-bottom: none;
  margin-top: auto;
}
.sandbox-info {
  padding: 0 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.info-label {
  color: var(--chat-text-muted, #999);
}
.info-mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
}
.retention-note {
  padding: 9px 10px;
  border: 1px solid var(--border-subtle, var(--chat-border));
  border-radius: 8px;
  color: var(--text-tertiary, var(--chat-text-muted));
  background: var(--surface-highlight, var(--chat-surface-hover));
  font-size: 11px;
  line-height: 1.55;
}

/* ---------- 文件预览 ---------- */
.extract-skill-form {
  display: grid;
  gap: 14px;
}
.extract-skill-form label {
  display: grid;
  gap: 6px;
  color: var(--chat-text-secondary);
  font-size: 13px;
}
.extract-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.extract-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.editor-toolbar {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.editor-meta,
.editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dirty-state { color: #f59e0b; font-size: 12px; }
.saved-state { color: #22c55e; font-size: 12px; }
.shortcut-tip { color: var(--chat-text-muted, #999); font-size: 11px; }
.workspace-editor {
  width: 100%;
  height: min(62vh, 620px);
  min-height: 360px;
}
.editor-output {
  width: 100%;
  margin-top: 10px;
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 8px;
  overflow: hidden;
}
.output-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  color: var(--chat-text-secondary);
  font-size: 12px;
  background: var(--chat-surface-hover, #f7f8fa);
}
.editor-output pre {
  margin: 0;
  padding: 10px;
  max-height: 200px;
  overflow: auto;
  background: #1e2127;
  color: #d7dae0;
  font: 12px/1.6 'JetBrains Mono', 'Fira Code', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.preview-wrap {
  min-height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.file-preview {
  width: 100%;
  margin: 0;
  padding: 12px;
  max-height: 60vh;
  overflow: auto;
  background: var(--chat-surface-hover, #f7f8fa);
  border-radius: 8px;
  font-size: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.truncated-tip {
  align-self: flex-end;
  margin-top: 6px;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}

@media (max-width: 900px) {
  .bar-title { max-width: 160px; }
  .model-tag,
  .model-select { display: none; }
}

/* ---------- Studio Apple surface overrides ---------- */
.studio-topbar { border-bottom-color: var(--studio-border, #e8e8f2); background: color-mix(in srgb, var(--studio-card) 88%, transparent); backdrop-filter: blur(20px) saturate(1.15); }
.studio-view { --chat-input-bg: var(--neutral-card); --chat-input-border: var(--neutral-border); background: var(--studio-bg, #f7f7fb); color: var(--studio-text, #2b2b3d); }
.studio-modebar { flex-shrink:0; display:flex; align-items:center; justify-content:center; gap:2px; padding:7px 10px; border-bottom:1px solid var(--studio-border,#e8e8f2); background:color-mix(in srgb, var(--studio-card) 82%, transparent); backdrop-filter:blur(18px); }
.studio-modebar button { display:flex; align-items:center; gap:5px; padding:6px 13px; border:0; border-radius:8px; color:var(--studio-text-sub,#8a8aa3); background:transparent; font-size:12px; cursor:pointer; transition:background .16s ease,color .16s ease,transform .1s ease; }
.modebar-divider{width:1px;height:18px;margin:0 5px;background:var(--studio-border,#e8e8f2)}.studio-modebar button:hover,.studio-modebar button.active { color:var(--studio-primary,#6c5ce7); background:var(--studio-primary-soft,#f0edff); }.studio-modebar button.active { font-weight:600; }.studio-modebar button:active { transform:scale(.97); }
.studio-workbench { position:relative; flex:1; min-height:0; display:flex; overflow:hidden; }.chat-pane,.code-pane { min-width:0; min-height:0; display:flex; flex-direction:column; overflow:hidden; }.chat-pane { flex:1; }.code-pane { flex:1; border-left:1px solid var(--studio-border,#e8e8f2); }.mode-chat .chat-pane { width:100%; }.mode-code .code-pane { width:100%; border-left:0; }.center-splitter { flex:0 0 5px; margin-left:-2px; margin-right:-2px; z-index:4; cursor:col-resize; background:transparent; touch-action:none; }.center-splitter:hover { background:var(--studio-primary,#6c5ce7); }
.chat-pane.drawer { position:absolute; right:16px; bottom:16px; z-index:8; width:min(460px,calc(100% - 32px)); height:min(70%,620px); border:1px solid var(--studio-border,#e8e8f2); border-radius:16px; background:rgba(255,255,255,.94); box-shadow:0 18px 50px rgba(43,43,61,.16); }.chat-fab { position:absolute; right:20px; bottom:20px; z-index:9; display:grid; place-items:center; width:44px; height:44px; border:0; border-radius:50%; color:#fff; background:var(--studio-primary,#6c5ce7); box-shadow:0 8px 22px rgba(108,92,231,.28); cursor:pointer; }.chat-fab.open { opacity:0; pointer-events:none; }.unread-dot { position:absolute; top:2px; right:2px; width:9px; height:9px; border:2px solid #fff; border-radius:50%; background:#e45470; }
.col-left,.col-right { background:color-mix(in srgb, var(--studio-card) 82%, transparent); border-color:var(--studio-border,#e8e8f2); }.session-item:hover { background:var(--studio-primary-soft,#f0edff); }.session-item.active { position:relative; background:var(--studio-primary-soft,#f0edff); }.session-item.active::before { position:absolute; inset:7px auto 7px 0; width:3px; border-radius:0 2px 2px 0; background:var(--studio-primary); content:''; }.session-item.active .s-title { color:var(--studio-primary,#6c5ce7); }.resize-handle:hover { background:rgba(76,111,255,.26); }
.plan-item.is-done { color:var(--studio-text-sub,#8a8aa3); background:rgba(108,92,231,.06); opacity:.78; }.plan-item.is-done .plan-title { text-decoration:line-through; text-decoration-thickness:1px; }.plan-item.is-done .plan-status { color:var(--studio-primary,#6c5ce7); font-weight:700; }.plan-item.is-in_progress { color:var(--studio-primary,#6c5ce7); background:var(--studio-primary-soft,#f0edff); }
.workspace-image-preview { max-width:100%; max-height:70vh; object-fit:contain; border-radius:12px; box-shadow:0 12px 36px rgba(43,43,61,.12); }.workspace-table-wrap { width:100%; max-height:65vh; overflow:auto; }.workspace-table-wrap table { width:100%; border-collapse:collapse; font-size:12px; }.workspace-table-wrap th,.workspace-table-wrap td { padding:7px 9px; border-bottom:1px solid var(--studio-border,#e8e8f2); text-align:left; white-space:nowrap; }.workspace-table-wrap th { position:sticky; top:0; background:var(--studio-primary-soft,#f0edff); }.workspace-table-wrap small { display:block; margin-top:8px; color:var(--studio-text-sub,#8a8aa3); }.unsupported-preview { display:grid; justify-items:center; gap:8px; padding:46px 20px; text-align:center; }.unsupported-preview h3 { margin:0; }.unsupported-preview p { max-width:460px; margin:0 0 10px; color:var(--studio-text-sub,#8a8aa3); font-size:12px; }.unsupported-icon { color:var(--studio-primary,#6c5ce7); font-size:42px; }
@media (prefers-reduced-motion: reduce) { .studio-modebar button,.node-caret { transition:none !important; }.task-status-light.is-running { animation:none; } }

.accordion-header { width:100%; border:0; background:transparent; text-align:left; cursor:pointer; }.accordion-header:hover { background:var(--studio-primary-soft,#f0edff); }.accordion-chevron { margin-left:auto; color:var(--studio-text-sub,#8a8aa3); transition:transform .18s ease; }.accordion-chevron.open { transform:rotate(180deg); }
.studio-view :deep(.kimi-message-item.user .message-content.user-bubble) { max-width:78%; padding:10px 14px; color:var(--user-bubble-text,#2b2b3d); background:var(--user-bubble-bg,#eeeaff); border:1px solid var(--user-bubble-border,#ddd7ff); border-radius:16px 16px 5px 16px; box-shadow:0 3px 12px rgba(108,92,231,.08); }
:root[data-theme="dark"] .studio-view :deep(.kimi-message-item.user .message-content.user-bubble) { --user-bubble-bg:#2a2545; --user-bubble-border:#4a4278; --user-bubble-text:#e0ddf0; box-shadow:0 3px 12px rgba(108,92,231,.18); }
.studio-view :deep(.kimi-message-item.assistant .message-content.ai-card) { border-color:var(--studio-border,#e8e8f2); box-shadow:0 4px 16px rgba(43,43,61,.04); }.studio-view :deep(.ai-name),.studio-view :deep(.meta-item.tokens) { color:var(--studio-primary,#6c5ce7); }
.studio-view :deep(.kimi-chat-input) { border-color:var(--chat-input-border,var(--neutral-border)); border-radius:var(--radius-lg,16px); background:var(--chat-input-bg,var(--neutral-card)); box-shadow:none; }.studio-view :deep(.kimi-chat-input.deep-thinking) { border-color:var(--arco-primary); }.studio-view :deep(.deep-thinking-btn.active) { color:var(--arco-primary)!important; background:var(--arco-primary-light)!important; border-color:color-mix(in srgb, var(--arco-primary) 30%, transparent); border-radius:8px; }.studio-view :deep(.send-btn:hover),.studio-view :deep(.send-btn.active) { background:var(--arco-primary); }

.studio-chat-empty{position:absolute;inset:0;z-index:0;display:grid;place-content:center;justify-items:center;gap:9px;padding:30px;text-align:center;color:var(--studio-text-sub,#8a8aa3);pointer-events:none;background:var(--brand-gradient-soft)}.studio-chat-empty strong{color:var(--studio-text,#2b2b3d);font-weight:600}.studio-chat-empty span{max-width:350px;font-size:12px;line-height:1.6}.empty-stars{color:var(--studio-primary,#6c5ce7);font-size:28px;letter-spacing:10px;opacity:.7}.chat-pane{position:relative}.snapshot-note{margin:2px 0 6px;padding:6px 8px;border-radius:7px;background:var(--studio-primary-soft,#f0edff);color:var(--studio-primary,#6c5ce7);font-size:11px;line-height:1.45}.metric-row{padding:3px 12px 5px;font-size:11px;color:var(--studio-text-sub,#8a8aa3)}.metric-row>div:first-child{display:flex;justify-content:space-between;margin-bottom:4px}.metric-row b{color:var(--studio-text,#2b2b3d);font-weight:600}.metric-track{height:5px;overflow:hidden;border-radius:99px;background:#ecebf3}.metric-track i{display:block;height:100%;border-radius:inherit;background:var(--brand-gradient);transition:width .3s ease}
</style>
