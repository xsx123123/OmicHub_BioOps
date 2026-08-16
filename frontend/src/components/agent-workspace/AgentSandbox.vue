<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NIcon, NPopconfirm, NSelect, NTag, NTooltip, useMessage, useDialog } from 'naive-ui'
import {
  ArrowBackOutline,
  BulbOutline,
  FlashOutline,
  FolderOpenOutline,
  FlaskOutline,
  GridOutline,
  DocumentTextOutline,
  AnalyticsOutline,
} from '@vicons/ionicons5'
import KimiMessageList from '@/components/ai-chat/KimiMessageList.vue'
import OverdriveProgressCard from '@/components/ai-chat/OverdriveProgressCard.vue'
import {
  activeOverdriveProgress as selectActiveOverdriveProgress,
  conversationMessagesWithoutProgress,
  latestOverdriveProgress as selectLatestOverdriveProgress,
} from '@/components/ai-chat/overdriveUi'
import type { CollaborationRouteInfo } from '@/components/ai-chat/types'
import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'
import AgentCapabilityDrawer from './AgentCapabilityDrawer.vue'
import ShaniaChatBackground from './ShaniaChatBackground.vue'
import StardustHero from './StardustHero.vue'
import { useAgentHubStore } from '@/stores/agentHub'
import { useAuthStore } from '@/stores/auth'
import { studioApi } from '@/api/studio'
import type { ChatMessage, FileAttachment } from '@/components/ai-chat/types'
import { displayName } from '@/utils/displayName'
import { parseTaskUnderstanding } from '@/utils/studioPresentation'

const store = useAgentHubStore()
const authStore = useAuthStore()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const emit = defineEmits<{
  openAgentPicker: []
}>()

// 工具调用轮次触顶时，弹窗询问是否以扩展上限（1000 轮）继续执行
watch(
  () => store.roundLimitPrompt,
  (prompt) => {
    if (!prompt) return
    store.roundLimitPrompt = null
    dialog.warning({
      title: '工具调用轮次已达上限',
      content: `本次任务已连续调用工具 ${prompt.maxRounds} 轮仍未完成，已暂停。是否以扩展上限（1000 轮）继续执行？`,
      positiveText: '继续（扩展到 1000 轮）',
      negativeText: '不继续',
      onPositiveClick: () => {
        void store.sendMessage('请继续完成刚才未完成的任务', { extendMaxRounds: true })
      },
    })
  },
)

// 上下文超窗触发历史压缩时，轻提示用户早期对话已被压缩为摘要
watch(
  () => store.contextCompressedNotice,
  (tokens) => {
    if (tokens == null) return
    store.contextCompressedNotice = null
    const approx = tokens >= 10000 ? `${Math.round(tokens / 10000)}万` : String(tokens)
    message.info(`对话历史较长（约 ${approx} tokens），已将早期内容压缩为摘要后继续`)
  },
)

// 仅在星尘 AI 的后端路由/交接事件命中工作台 Agent 后，才进入 AI 工作台。
watch(
  () => store.studioRedirect,
  async (target) => {
    if (!target) return
    store.studioRedirect = null    // 等当前流式回答结束再跳转，避免打断正在输出的内容
    while (store.isStreaming) {
      await new Promise((resolve) => setTimeout(resolve, 300))
    }
    try {
      // 优先把当前会话就地升级为工作台（历史消息完整保留）；
      // 会话尚未落库（sess- 临时 ID）或升级失败时，回退为新建工作台会话
      const sid = store.currentSessionId
      let sessionId = ''
      if (sid && !sid.startsWith('sess-')) {
        try {
          const promoted = await studioApi.promoteSession(sid, target.agentId)
          sessionId = promoted.session_id
          // 后端已把会话重绑定到工作台 Agent，本地会话同步绑定，
          // 否则下一轮请求仍按旧 Agent 发送，触发"会话绑定的 Agent 与当前请求不一致"
          if (store.currentSession && store.currentSession.id === sessionId) {
            store.currentSession.agent_id = promoted.agent_id || target.agentId
          }
        } catch {
          sessionId = ''
        }
      }
      if (!sessionId) {
        const created = await studioApi.createSession({ agent_id: target.agentId })
        sessionId = created.session_id
      }
      store.markStudioSession(sessionId)
      message.info(`已为「${target.agentName}」开启 AI 工作台，对话历史已带过去，可继续`)
      router.push({ name: 'studio', params: { sessionId } })
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '进入工作台失败')
    }
  },
)

defineProps<{ targetMessageId?: string }>()

const input = ref('')
const showCap = ref(false)
const modelSwitchNotice = ref('')
const creatingStudio = ref(false)
let noticeTimer: ReturnType<typeof setTimeout> | null = null

const agent = computed(() => store.currentAgent)
const session = computed(() => store.currentSession)
const overdriveEnabled = computed({
  get: () => Boolean(session.value?.overdrive),
  set: (value: boolean) => {
    if (session.value) session.value.overdrive = value
  },
})
const engineLabel = computed(() => agent.value?.model_engine || '')
const agentDisplayName = computed(() => agent.value?.features?.router ? '星尘 AI' : agent.value?.name || '星尘 AI')
const greetingUserName = computed(() => displayName(authStore.user))
/** 快捷任务：结构化配置驱动，语义图标 + 动词文案 + 真实 behavior（fontend.md §35.6 / §36.3）。
 *  当前统一 behavior=prefill：预填输入框由用户确认发送，不自动提交。 */
const quickActions: Array<{
  id: string
  title: string
  description: string
  icon: Component
  behavior: 'prefill'
  prompt: string
}> = [
  { id: 'files', title: '浏览工作区文件', description: '快速了解当前可用的数据资产', icon: FolderOpenOutline, behavior: 'prefill', prompt: '帮我看看工作区里有哪些数据文件' },
  { id: 'deg', title: '进行差异表达分析', description: '从 RNA-seq 结果找到关键变化', icon: FlaskOutline, behavior: 'prefill', prompt: 'RNA-seq 差异表达分析怎么开始' },
  { id: 'heatmap', title: '绘制相关性热图', description: '探索样本之间的整体关系', icon: GridOutline, behavior: 'prefill', prompt: '画一个样本间相关性热图' },
  { id: 'report', title: '生成分析报告', description: '整理一份可复现的分析记录', icon: DocumentTextOutline, behavior: 'prefill', prompt: '生成一份可复现的分析报告模板' },
  { id: 'single-cell', title: '帮我进行单细胞分析', description: '从单细胞数据开始细胞群体与 marker 分析', icon: FlaskOutline, behavior: 'prefill', prompt: '帮我进行单细胞分析' },
  { id: 'rna-seq', title: '帮我进行 RNA-seq 分析', description: '从 RNA-seq 数据开始质量控制与差异分析', icon: AnalyticsOutline, behavior: 'prefill', prompt: '帮我进行 RNA-seq 分析' },
]

/** 空会话（无消息）与活跃会话双布局（fontend.md §35.3） */
const isEmpty = computed(() => (session.value?.messages.length ?? 0) === 0)
const conversationMessages = computed(() =>
  conversationMessagesWithoutProgress(session.value?.messages || []),
)
/** 超频规划开始前先明确解析到的任务，保持与 AI 工作台一致的首屏认知反馈。 */
const overdriveTaskUnderstanding = computed(() => {
  if (!session.value?.overdrive) return null
  return parseTaskUnderstanding(session.value.messages || [], store.isStreaming, '超频协作任务')
})
const activeOverdriveProgress = computed(() =>
  selectActiveOverdriveProgress(session.value?.messages || []),
)
const latestProgress = computed(() =>
  selectLatestOverdriveProgress(session.value?.messages || []),
)
/** 用户手动收起完成态卡片后不再常驻；新一轮协作开始时自动恢复展示 */
const progressDockDismissed = ref(false)
watch(activeOverdriveProgress, (active) => {
  if (active) progressDockDismissed.value = false
})
/** 进行中展示活跃进度；协作结束后保留完成态卡片（控件由卡片自身隐藏），不直接丢弃菜单 */
const dockedOverdriveProgress = computed(() => {
  if (activeOverdriveProgress.value) return activeOverdriveProgress.value
  if (progressDockDismissed.value) return null
  const latest = latestProgress.value
  return latest && latest.phase === 'completed' ? latest : null
})
const composerRef = ref<InstanceType<typeof KimiChatInput>>()
const recentSessions = computed(() =>
  store.sessions
    .filter((item) => item.id !== session.value?.id && !item.id.startsWith('sess-'))
    .slice(0, 4),
)

function formatRelativeTime(value: string): string {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime())
  const minutes = Math.floor(elapsed / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(value))
}

function recentSessionState(item: typeof recentSessions.value[number]): string {
  if (item.id === session.value?.id && store.isStreaming) return '运行中'
  return item.mode === 'studio' || store.studioSessionIds.has(item.id) ? '工作台会话' : '已完成'
}

function openRecentSession(sessionId: string) {
  void store.selectSession(sessionId)
}

async function deleteRecentSession(sessionId: string) {
  await store.deleteSession(sessionId)
  if (!store.currentSession) store.newChat()
}

function handleQuickAction(action: (typeof quickActions)[number]) {
  input.value = action.prompt
  nextTick(() => composerRef.value?.focus())
}

const userDisplayName = computed(() => displayName(authStore.user) || '我')
const userAvatarUrl = computed(() => authStore.user?.avatar_url || '')

/** 首次调用某技能的轻提示（localStorage 去重，全生命周期只弹一次，可关=不再提示同技能） */
const SKILL_NOTICE_KEY = 'omichub-notified-skills'
function handleSkillInvokedNotice(e: Event) {
  const detail = (e as CustomEvent<{ skill_id: string; name: string; version?: string }>).detail
  if (!detail?.skill_id) return
  try {
    const seen: string[] = JSON.parse(localStorage.getItem(SKILL_NOTICE_KEY) || '[]')
    if (seen.includes(detail.skill_id)) return
    seen.push(detail.skill_id)
    localStorage.setItem(SKILL_NOTICE_KEY, JSON.stringify(seen.slice(-200)))
  } catch {
    /* localStorage 不可用时每次都会提示，不影响功能 */
  }
  message.info(
    `Agent 正在使用技能「${detail.name}」${detail.version ? ` v${detail.version}` : ''}`,
  )
}

onMounted(() => {
  window.addEventListener('omichub:skill-invoked', handleSkillInvokedNotice)
})

onUnmounted(() => {
  window.removeEventListener('omichub:skill-invoked', handleSkillInvokedNotice)
})

const modelOptions = computed(() =>
  store.availableModels.map((m) => ({
    label: m.name,
    value: m.id,
  })),
)

const currentModelId = computed(() => session.value?.model_id || agent.value?.model_id || '')

const isCurrentModelValid = computed(() =>
  !currentModelId.value || modelOptions.value.some((o) => o.value === currentModelId.value),
)

const selectOptions = computed(() => {
  const opts: Array<{ label: string; value: string; disabled?: boolean }> = [...modelOptions.value]
  if (!isCurrentModelValid.value && currentModelId.value) {
    opts.unshift({ label: '当前模型已失效', value: currentModelId.value, disabled: true })
  }
  return opts
})

const currentModelName = computed(() => {
  const id = currentModelId.value
  if (!id) return engineLabel.value
  const found = store.availableModels.find((m) => m.id === id)
  return found?.name || engineLabel.value || '默认模型'
})

const inputPlaceholder = computed(() => {
  return '输入需求，@ 引用文件、技能或智能体，/ 查看快捷命令'
})

function handleModelSwitch(modelId: string) {
  if (!session.value || modelId === currentModelId.value) return
  store.switchSessionModel(session.value.id, modelId)
  const name = store.availableModels.find((m) => m.id === modelId)?.name || modelId
  modelSwitchNotice.value = `已切换至 ${name}，后续回复将使用该模型`
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => {
    modelSwitchNotice.value = ''
  }, 3000)
}

watch(
  () => agent.value?.id,
  () => {
    modelSwitchNotice.value = ''
  },
)

function handleSend(
  content: string,
  options: {
    attachments?: FileAttachment[]
    enableWebSearch?: boolean
    enableCodeExecution?: boolean
    explicitAgentId?: string
    skillNames?: string[]
  } = {},
) {
  if (!content.trim() && !options.attachments?.length) return
  if (store.isStreaming) return
  void store.sendMessage(content, options)
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
  await store.sendMessage(target.content, { attachments: target.attachments })
}

function handleRetryWithModel() {
  message.info('请使用页面顶部的模型选择器切换模型后，再点击重试')
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

function handleConfirmTool(toolName: string, args: Record<string, unknown>) {
  const content = toolName === 'create_agentteams_case'
    ? `我确认创建协作 Case。请仅使用以下已确认参数再次调用 ${toolName}，并携带 _confirmed: true：\n${JSON.stringify(args, null, 2)}`
    : `确认执行 ${toolName}`
  store.sendMessage(content, {})
}

function handleCreateCaseFromConsultation(summary: string, consultationId?: string) {
  window.dispatchEvent(new CustomEvent('omichub:agentteams-create', {
    detail: { summary, consultationId },
  }))
}

function handleCorrectCollaborationRoute(route: CollaborationRouteInfo) {
  input.value = `我不想走“${route.label}”这条路径。请改为：`
}

function handleOpenToolPage(route: string, _args: Record<string, unknown>) {
  // open_page 工具直接跳转前端路由
  if (route.startsWith('/')) {
    // router.push(route)  // AgentSandbox 未引入 router，交由父层或 window 跳转
    window.location.href = route
  }
}

function handleBack() {
  emit('openAgentPicker')
}

/** 以当前智能体发起 Studio 工作台会话并跳转 /studio/:sessionId */
async function handleEnterStudio() {
  if (!agent.value || creatingStudio.value) return
  creatingStudio.value = true
  try {
    const sid = store.currentSessionId
    let sessionId = ''
    if (sid && !sid.startsWith('sess-')) {
      try {
        const promoted = await studioApi.promoteSession(sid, agent.value.id)
        sessionId = promoted.session_id
        if (store.currentSession && store.currentSession.id === sessionId) {
          store.currentSession.agent_id = promoted.agent_id || agent.value.id
        }
      } catch {
        sessionId = ''
      }
    }
    if (!sessionId) {
      const created = await studioApi.createSession({ agent_id: agent.value.id })
      sessionId = created.session_id
    }
    store.markStudioSession(sessionId)
    message.info('已进入 AI 工作台，对话历史已带过去，可继续')
    router.push({ name: 'studio', params: { sessionId } })
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '创建工作台会话失败')
  } finally {
    creatingStudio.value = false
  }
}

onUnmounted(() => {
  if (noticeTimer) clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="agent-sandbox" :class="{ 'is-empty': isEmpty }" v-if="agent && session">
    <ShaniaChatBackground v-if="agent.id === 'shania'" />
    <!-- 首页（空会话）不渲染上边栏，进入聊天态后才显示返回/模型选择等控件 -->
    <header v-if="!isEmpty" class="sandbox-header">
      <div class="header-left">
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton text class="back-btn" aria-label="打开智能体中心" @click="handleBack">
              <NIcon size="18"><ArrowBackOutline /></NIcon>
            </NButton>
          </template>
          打开智能体中心
        </NTooltip>
        <div class="agent-identity">
          <div class="id-avatar">✦</div>
          <div class="id-meta">
            <h1 class="id-name">{{ agentDisplayName }}</h1>
            <div class="agent-status" aria-live="polite">{{ store.isStreaming ? '正在处理请求' : '助手已就绪' }}</div>
          </div>
        </div>
      </div>
      <div class="header-right">
        <div class="model-selector">
          <n-select
            v-if="modelOptions.length"
            :value="currentModelId"
            :options="selectOptions"
            :consistent-menu-width="false"
            :disabled="store.isStreaming"
            size="small"
            style="width: 160px"
            @update:value="handleModelSwitch"
          >
            <template #arrow>
              <n-icon size="14"><FlashOutline /></n-icon>
            </template>
          </n-select>
          <n-tag v-else size="small" round :bordered="false" type="info">{{ engineLabel }}</n-tag>
          <transition name="fade">
            <span v-if="modelSwitchNotice" class="model-switch-notice">{{ modelSwitchNotice }}</span>
          </transition>
        </div>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton class="capability-btn" size="small" quaternary aria-label="查看智能体能力" @click="showCap = true">
              <template #icon><NIcon><BulbOutline /></NIcon></template>
              查看该智能体能力
            </NButton>
          </template>
          查看智能体能力
        </NTooltip>
      </div>
    </header>

    <div class="sandbox-body">
      <div class="chat-content-wrapper">
        <!-- 空会话首页：星星+AI 动画 hero + 打招呼文案 → 输入区 → 快捷任务芯片（fontend.md §35.3.1） -->
        <StardustHero
          v-if="isEmpty"
          :title="agentDisplayName"
          :user-name="greetingUserName"
        />

        <!-- 活跃会话：消息列表（内部滚动 + 底部吸附输入区 §35.3.2） -->
        <KimiMessageList
          v-if="!isEmpty"
          :messages="conversationMessages"
          :is-typing="store.isStreaming"
          :streaming-content="store.streamingContent"
          :streaming-thought="store.streamingThought"
          :model-name="agentDisplayName"
          :user-name="userDisplayName"
          :user-avatar="userAvatarUrl"
          :session-id="session.id"
          :target-message-id="targetMessageId"
          :task-understanding="overdriveTaskUnderstanding"
          @copy="handleCopy"
          @feedback="(id, type) => store.submitMessageFeedback(id, type)"
          @regenerate="handleRegenerate"
          @retry-with-model="handleRetryWithModel"
          @delete="handleDeleteMessage"
          @edit="handleEditMessage"
          @confirm-tool="handleConfirmTool"
          @open-tool-page="handleOpenToolPage"
          @create-case-from-consultation="handleCreateCaseFromConsultation"
          @correct-collaboration-route="handleCorrectCollaborationRoute"
        />

        <transition name="progress-dock">
          <div v-if="dockedOverdriveProgress" class="overdrive-progress-dock">
            <OverdriveProgressCard :progress="dockedOverdriveProgress" compact />
            <button
              v-if="dockedOverdriveProgress.phase === 'completed'"
              type="button"
              class="overdrive-progress-dock__dismiss"
              aria-label="收起协作面板"
              title="收起协作面板"
              @click="progressDockDismissed = true"
            >
              ×
            </button>
          </div>
        </transition>

        <!-- 输入区：单实例避免草稿/附件丢失；空会话在说明下方、活跃会话底部吸附（fontend.md §35.3） -->
        <div class="composer-slot">
          <KimiChatInput
            ref="composerRef"
            v-model="input"
            :is-streaming="store.isStreaming"
            :show-overdrive-control="true"
            :overdrive-enabled="overdriveEnabled"
            :show-workbench-control="true"
            :workbench-loading="creatingStudio"
            :placeholder="inputPlaceholder"
            @send="handleSend"
            @stop="store.stopStreaming"
            @toggle-overdrive="overdriveEnabled = !overdriveEnabled"
            @enter-workbench="handleEnterStudio"
          />
        </div>

        <!-- 快捷任务：语义图标 + 动词文案 + 预填行为，首页以居中芯片呈现（fontend.md §35.6） -->
        <section v-if="isEmpty" class="quick-actions" aria-label="快捷任务">
          <button
            v-for="action in quickActions"
            :key="action.id"
            type="button"
            class="quick-chip"
            :title="action.description"
            @click="handleQuickAction(action)"
          >
            <NIcon :size="15" aria-hidden="true"><component :is="action.icon" /></NIcon>
            <span>{{ action.title }}</span>
          </button>
        </section>

        <section v-if="isEmpty" class="recent-context" aria-labelledby="recent-context-title">
          <div class="recent-context-heading">
            <h2 id="recent-context-title">最近会话</h2>
            <span v-if="recentSessions.length">继续上次的分析</span>
          </div>
          <div v-if="recentSessions.length" class="recent-session-list">
            <article v-for="item in recentSessions" :key="item.id" class="recent-session-item">
              <button
                type="button"
                class="recent-session-main"
                :title="item.title"
                @click="openRecentSession(item.id)"
              >
                <span class="recent-session-title">{{ item.title }}</span>
                <span class="recent-session-meta">
                  <span>{{ store.getAgent(item.agent_id)?.name || '智能助手' }}</span>
                  <span aria-hidden="true">·</span>
                  <span>{{ formatRelativeTime(item.updated_at) }}</span>
                </span>
              </button>
              <span class="recent-session-state">{{ recentSessionState(item) }}</span>
              <NPopconfirm
                positive-text="删除"
                negative-text="取消"
                @positive-click="deleteRecentSession(item.id)"
              >
                <template #trigger>
                  <NButton text size="tiny" class="recent-session-delete" :aria-label="`删除会话：${item.title}`">
                    删除
                  </NButton>
                </template>
                删除此会话后无法恢复，确定继续吗？
              </NPopconfirm>
            </article>
          </div>
          <p v-else class="recent-context-empty">还没有历史会话；你可以从上方输入需求或选择快捷任务开始。</p>
        </section>
      </div>
    </div>

    <AgentCapabilityDrawer v-model:show="showCap" />
  </div>
</template>

<style scoped lang="scss">
.agent-sandbox {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  --chat-content-max-width: 1120px;
  background:
    radial-gradient(circle at 12% 0%, rgba(46, 91, 255, 0.08), transparent 32%),
    radial-gradient(circle at 88% 8%, rgba(123, 77, 255, 0.07), transparent 30%),
    linear-gradient(180deg, #f4f6ff 0%, #fafbff 40%, #fff 100%);
}

.agent-sandbox::before {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  content: '';
  opacity: 0.32;
  background-image: radial-gradient(rgba(46, 91, 255, 0.16) 0.7px, transparent 0.7px);
  background-size: 18px 18px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent 55%);
}

.sandbox-header {
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 12px 20px;
  border-bottom: 1px solid var(--stardust-border-soft);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
}
.header-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.back-btn { flex-shrink: 0; color: var(--stardust-text-secondary); }
.back-btn:hover { color: var(--stardust-blue); background: var(--stardust-bg-soft); }
.agent-identity { display: flex; align-items: center; gap: 12px; min-width: 0; }
.id-avatar {
  width: 38px; height: 38px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;
  color: #fff;
  background: var(--agent-hero-gradient);
  box-shadow: 0 2px 8px rgba(79, 109, 245, 0.35);
}
.id-meta { min-width: 0; }
.id-name { margin: 0; font-size: 16px; line-height: 24px; font-weight: 600; color: var(--chat-text-primary, #1A1D33); }
.agent-status { margin-top: 2px; color: var(--success-color, #18a058); font-size: 12px; line-height: 16px; }
.header-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
/* 工作台模式归为页面操作组，用次要弱化按钮，不与发送按钮竞争主层级（fontend.md §35.8.3） */
.capability-btn {
  color: var(--stardust-blue);
  border: 1px solid #d4dbf5;
  border-radius: 8px;
}
.capability-btn:hover { color: var(--stardust-blue); border-color: var(--stardust-blue); background: var(--stardust-bg-soft); }
.model-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}
.model-selector :deep(.n-base-selection) {
  border: none;
  border-radius: 16px;
  background: #f2f3f8;
  box-shadow: none;
}
.model-selector :deep(.n-base-selection:hover) { box-shadow: 0 4px 12px rgba(30, 50, 100, 0.1); }
.model-switch-notice {
  font-size: 12px;
  color: var(--chat-accent, #4f8ef7);
  white-space: nowrap;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 内容层显式提升，确保位于点阵 ::before 与 ShaniaChatBackground 装饰层之上。
   注意：不能用 `.agent-sandbox > *` 通配提升，否则会把绝对定位的装饰背景
   一并改成 position: relative 拉进文档流，撑出顶部空白并顶高 header。 */
.sandbox-body { position: relative; z-index: 1; flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.sandbox-body > .chat-content-wrapper {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 快捷任务：居中胶囊芯片行；描述收进 title 提示，保持首页轻量（fontend.md §35.6） */
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 18px;
  animation: home-rise 480ms 180ms cubic-bezier(0.22, 0.8, 0.36, 1) both;
}
.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border: 1px solid var(--stardust-border-soft, var(--neutral-border));
  border-radius: 999px;
  background: var(--chat-surface, var(--bg-card));
  color: var(--text-secondary, var(--chat-text-muted, var(--neutral-text-3)));
  font-size: 13px;
  line-height: 20px;
  cursor: pointer;
  transition: box-shadow 200ms ease, transform 200ms ease, border-color 200ms ease, color 200ms ease;
}
.quick-chip:hover {
  transform: translateY(-1px);
  color: var(--stardust-blue, #4c6fff);
  border-color: color-mix(in srgb, var(--stardust-blue, #4c6fff) 35%, transparent);
  box-shadow: 0 8px 24px rgba(30, 111, 255, 0.10);
}
.quick-chip:focus-visible {
  outline: 2px solid var(--arco-primary, var(--stardust-blue));
  outline-offset: 3px;
}
@keyframes home-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: none; }
}

.recent-context { margin-top: 32px; animation: home-rise 480ms 240ms cubic-bezier(0.22, 0.8, 0.36, 1) both; }
.recent-context-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.recent-context-heading h2 { margin: 0; color: var(--chat-text-primary, var(--neutral-text-1)); font-size: 15px; line-height: 22px; font-weight: 600; }
.recent-context-heading span { color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 12px; }
.recent-session-list { display: grid; grid-template-columns: 1fr; gap: 10px; }
.recent-session-item { display: flex; align-items: center; gap: 10px; min-height: 72px; padding: 10px 12px 10px 14px; border: 1px solid var(--stardust-border-soft, var(--neutral-border)); border-radius: 12px; background: var(--chat-surface, var(--neutral-card)); }
.recent-session-main { display: flex; flex: 1; min-width: 0; flex-direction: column; align-items: flex-start; gap: 5px; border: 0; padding: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.recent-session-main:focus-visible { outline: 2px solid var(--arco-primary, var(--stardust-blue)); outline-offset: 3px; border-radius: 4px; }
.recent-session-title { width: 100%; overflow: hidden; color: var(--chat-text-primary, var(--neutral-text-1)); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.recent-session-meta { display: flex; min-width: 0; gap: 5px; overflow: hidden; color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 12px; white-space: nowrap; }
.recent-session-meta span:first-child { overflow: hidden; text-overflow: ellipsis; }
.recent-session-state { flex: 0 0 auto; color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 11px; white-space: nowrap; }
.recent-session-delete { flex: 0 0 auto; color: var(--chat-text-muted, var(--neutral-text-3)); }
.recent-session-delete:hover { color: var(--error-color, #d03050); }
.recent-context-empty { margin: 0; padding: 14px 16px; border: 1px dashed var(--stardust-border-soft, var(--neutral-border)); border-radius: 12px; color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 13px; line-height: 20px; }

.overdrive-progress-dock {
  position: relative;
  z-index: 3;
  display: flex;
  flex-shrink: 0;
  justify-content: center;
  padding: 10px 24px 0;
  background: linear-gradient(180deg, transparent, rgba(255, 255, 255, 0.76) 38%);
  pointer-events: none;
}

.overdrive-progress-dock :deep(.overdrive-progress-card) {
  pointer-events: auto;
}

/* 完成态卡片的收起按钮：贴在卡片右上角，不打断卡片自身布局 */
.overdrive-progress-dock__dismiss {
  position: absolute;
  top: 14px;
  right: 34px;
  z-index: 1;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: color-mix(in srgb, var(--chat-text-primary) 8%, transparent);
  color: var(--chat-text-muted);
  font-size: 14px;
  line-height: 22px;
  cursor: pointer;
  pointer-events: auto;
}

.overdrive-progress-dock__dismiss:hover {
  background: color-mix(in srgb, var(--chat-text-primary) 14%, transparent);
  color: var(--chat-text-primary);
}

.progress-dock-enter-active,
.progress-dock-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.progress-dock-enter-from,
.progress-dock-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* 输入区：活跃会话底部吸附；空会话在说明下方、无边框底色（fontend.md §35.3） */
.composer-slot {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  padding: 14px 24px;
  border-top: 1px solid var(--stardust-border-soft);
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(10px);
}
.is-empty .composer-slot {
  padding: 20px 0 0;
  border-top: none;
  background: transparent;
  backdrop-filter: none;
}
.chat-content-wrapper {
  max-width: 1120px;
  margin: 0 auto;
  width: 100%;
}

/* 空会话首屏：居中内容列 + 顶部留白托出 hero，wrapper 整体滚动（fontend.md §35.3.1） */
.is-empty .chat-content-wrapper {
  max-width: 1120px;
  display: block;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
  padding: clamp(28px, 7vh, 84px) 24px 40px;
}
.is-empty .chat-content-wrapper::-webkit-scrollbar { width: 0; height: 0; }

@media (max-width: 768px) {
  .sandbox-header { padding-inline: 16px; }
  .header-right { gap: 6px; }
  .model-selector :deep(.n-base-selection) { min-width: 124px; }
  .is-empty .chat-content-wrapper { padding: 24px 16px 32px; }
  .overdrive-progress-dock { padding-inline: 16px; }
}

@media (max-width: 640px) {
  .header-right .n-button__content { font-size: 12px; }
  .capability-btn { min-width: 40px; padding-inline: 8px; }
  .model-switch-notice { display: none; }
  .agent-status { display: none; }
  .recent-context-heading span, .recent-session-state { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .quick-chip,
  .quick-chip:hover { transform: none; transition: none; }
  .quick-actions, .recent-context { animation: none; }
  .progress-dock-enter-active,
  .progress-dock-leave-active { transition: none; }
}

@media (prefers-reduced-transparency: reduce) {
  .sandbox-header, .composer-slot { background: var(--bg-card); backdrop-filter: none; }
}

:root[data-theme="dark"] .agent-sandbox {
  background: radial-gradient(circle at 12% 0%, rgba(118, 145, 255, 0.12), transparent 32%), var(--chat-bg);
}
:root[data-theme="dark"] .sandbox-header,
:root[data-theme="dark"] .composer-slot {
  background: transparent;
  border-top-color: transparent;
  backdrop-filter: none;
}
:root[data-theme="dark"] .overdrive-progress-dock { background: transparent; }
:root[data-theme="dark"] .is-empty .composer-slot { background: transparent; }
:root[data-theme="dark"] .quick-chip { background: var(--chat-surface, var(--neutral-card)); border-color: var(--neutral-border, #2a3040); }
:root[data-theme="dark"] .model-selector :deep(.n-base-selection) { background: rgba(255, 255, 255, 0.08); }
:root[data-theme="dark"] .capability-btn { border-color: rgba(118, 145, 255, 0.35); }
</style>
