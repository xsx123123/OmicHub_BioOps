<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { ChevronDownOutline } from '@vicons/ionicons5'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import KimiMessageItem from './KimiMessageItem.vue'
import StudioTaskUnderstanding from '@/components/studio/StudioTaskUnderstanding.vue'
import type { StudioTaskUnderstanding as TaskUnderstanding } from '@/utils/studioPresentation'
import type { ChatMessage, CollaborationRouteInfo, CopyMode } from './types'

interface Props {
  messages: ChatMessage[]
  isTyping?: boolean
  streamingContent?: string
  streamingThought?: string
  modelName?: string
  userName?: string
  userAvatar?: string
  agentName?: string
  agentAvatar?: string
  agentColor?: string
  sessionId?: string
  targetMessageId?: string
  taskUnderstanding?: TaskUnderstanding | null
  /** 建议追问 Chips 总开关（默认关闭；开启后由本列表决定哪条 assistant 消息展示 chips） */
  suggestionsEnabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isTyping: false,
  streamingContent: '',
  streamingThought: '',
  modelName: 'AI 助手',
  userName: '我',
  userAvatar: '',
  agentName: 'CygnusX AI',
  agentAvatar: '🤖',
  agentColor: '#4f8ef7',
  sessionId: '',
  targetMessageId: '',
  taskUnderstanding: null,
  suggestionsEnabled: false,
})

const firstUserMessageIndex = computed(() => props.messages.findIndex((message) => message.role === 'user'))

const emit = defineEmits<{
  feedback: [messageId: string, type: 'like' | 'dislike']
  copy: [mode: CopyMode]
  regenerate: [messageId: string]
  retryWithModel: [messageId: string]
  translate: [messageId: string]
  delete: [messageId: string]
  edit: [messageId: string]
  confirmTool: [toolName: string, args: Record<string, unknown>]
  openToolPage: [route: string, args: Record<string, unknown>]
  createCaseFromConsultation: [summary: string, consultationId?: string]
  correctCollaborationRoute: [route: CollaborationRouteInfo]
  suggestionSend: [prompt: string]
  suggestionPrefill: [prompt: string]
}>()

interface ScrollerExpose {
  /** DynamicScroller 内置的贴底逻辑会等待异步高度测量完成。 */
  scrollToBottom: () => void
  scrollToItem?: (index: number) => void
}

const scrollerRef = ref<InstanceType<typeof DynamicScroller> & ScrollerExpose>()
/** 用户是否已上翻离开底部（true 时暂停自动跟随，并显示"回到底部"悬浮按钮） */
const showScrollToBottom = ref(false)
/** 暂停吸底期间是否有新内容到达（悬浮按钮上的红点提示） */
const hasNewWhileAway = ref(false)

/** 距底多少像素内视为"接近底部"，自动跟随流式输出 */
const NEAR_BOTTOM_THRESHOLD = 100

const streamingMessageId = computed(() => {
  const lastMsg = props.messages[props.messages.length - 1]
  if (lastMsg?.role === 'assistant' && props.isTyping && !lastMsg.senderAgent) {
    return lastMsg.id
  }
  return ''
})

/**
 * 建议追问 Chips 的宿主消息：仅"最后一条消息是已完成的 assistant 回复且当前无流式输出"时返回其 id。
 * 用户发送新消息（最后一条变为 user）或新回复开始流式输出时自动变为空串，
 * 旧 chips 随之消失；新回复完成后指向新消息，chips 被新一组替换。
 */
const suggestionMessageId = computed(() => {
  if (!props.suggestionsEnabled || props.isTyping) return ''
  const lastMsg = props.messages[props.messages.length - 1]
  if (!lastMsg || lastMsg.role !== 'assistant') return ''
  if (lastMsg.status && lastMsg.status !== 'complete') return ''
  return lastMsg.id
})

function getScrollerEl(): HTMLElement | undefined {
  return scrollerRef.value?.$el as HTMLElement | undefined
}

/** 仅用于用户主动点击“回到底部”的平滑滚动。 */
let scrollAnim: number | null = null
/** 流式吸底合并到每个绘制帧一次，避免 token、列表测量和滚动动画互相争抢。 */
let followFrame: number | null = null

function cancelScrollAnim() {
  if (scrollAnim !== null) {
    cancelAnimationFrame(scrollAnim)
    scrollAnim = null
  }
}

function cancelFollowFrame() {
  if (followFrame !== null) {
    cancelAnimationFrame(followFrame)
    followFrame = null
  }
}

/**
 * 自动跟随到底部。
 * 流式 token、Markdown 重排和 DynamicScroller 高度测量会在同一帧连续触发；
 * 统一合并到下一绘制帧后一次贴底，避免缓动 scrollTop 与列表校正互相拉扯。
 *
 * 注意不能只直接写 scroller.scrollTop。DynamicScroller 的消息项（工具卡、思考
 * 区、Markdown）会在本帧之后才由 ResizeObserver 回填实际高度；直接写入会贴到
 * "旧的" scrollHeight，随后列表校正高度时就表现为新内容没有自动下滑。
 * DynamicScroller.scrollToBottom() 会持续等待这些未定高度完成，正是这里需要的
 * 语义。
 * force=true（点击"回到底部" / 新审批 / 澄清事件）时取消缓动并立即贴底。
 */
function scrollToBottom(force = false) {
  if (!force && showScrollToBottom.value) {
    // 用户上滑暂停吸底期间有新内容到达：标记红点，不打断阅读位置
    hasNewWhileAway.value = true
    return
  }
  const el = getScrollerEl()
  if (!el) return
  if (force) {
    showScrollToBottom.value = false
    hasNewWhileAway.value = false
    cancelScrollAnim()
    cancelFollowFrame()
    scrollerRef.value?.scrollToBottom()
    return
  }
  if (followFrame !== null) return
  followFrame = requestAnimationFrame(() => {
    followFrame = null
    if (!getScrollerEl() || showScrollToBottom.value) return
    scrollerRef.value?.scrollToBottom()
  })
}

/** easeOutCubic 平滑滚动；每帧重读 scrollHeight，自动追上新增内容高度。 */
function smoothScrollTo(el: HTMLElement, target: number, duration: number) {
  cancelScrollAnim()
  const start = el.scrollTop
  const delta = target - start
  if (delta <= 0) return // 已在底部或目标更小，无需移动
  const startTime = performance.now()
  const step = (now: number) => {
    const t = Math.min(1, (now - startTime) / duration)
    const eased = 1 - Math.pow(1 - t, 3)
    // 重读 scrollHeight：流式内容在动画期间仍在增长，目标随之上移，避免"跟不上"
    const currentTarget = el.scrollHeight - el.clientHeight
    el.scrollTop = start + (currentTarget - start) * eased
    if (t < 1) {
      scrollAnim = requestAnimationFrame(step)
    } else {
      scrollAnim = null
    }
  }
  scrollAnim = requestAnimationFrame(step)
}

function scrollToMessage(messageId: string) {
  const index = props.messages.findIndex((m) => m.id === messageId)
  if (index < 0) return
  scrollerRef.value?.scrollToItem?.(index)
}

/** 点击"回到底部"：平滑滚动回底部（scroll-behavior: smooth 由缓动动画实现），并恢复自动吸底。 */
function scrollBackToBottom() {
  const el = getScrollerEl()
  if (!el) return
  showScrollToBottom.value = false
  hasNewWhileAway.value = false
  smoothScrollTo(el, el.scrollHeight, 400)
}

function handleScroll() {
  const el = getScrollerEl()
  if (!el) return
  const { scrollTop, scrollHeight, clientHeight } = el
  const awayFromBottom = scrollHeight - scrollTop - clientHeight > NEAR_BOTTOM_THRESHOLD
  showScrollToBottom.value = awayFromBottom
  // 用户自行滚回底部附近：清除新内容提示，恢复自动跟随
  if (!awayFromBottom) hasNewWhileAway.value = false
}

/**
 * 工具卡、Markdown 图片和 CodeMirror 等内容的高度可在 Vue 更新之后继续变化。
 * DynamicScrollerItem 在真实尺寸变化时发出 resize；再次走同一个跟随调度，保证
 * 已贴底的会话会继续贴底，同时仍会尊重用户主动上滑后的暂停状态。
 */
function handleItemResize() {
  scrollToBottom()
}

defineExpose({ scrollToBottom, scrollToMessage })

watch(
  () => props.messages.length,
  () => {
    nextTick(() => scrollToBottom())
  },
)

/**
 * 末尾内容体量：流式 token 与工具执行输出（sandbox stdout 等）都是原地追加，
 * messages.length 与 streamingContent 均不变，但列表持续变高。
 * 汇总各消息 toolCalls[].output 与末尾消息正文体量，任何增长都驱动一次吸底。
 * 只读取 length 字段，依赖精确、逐 chunk 重算开销可忽略。
 */
const tailVolume = computed(() => {
  let volume = 0
  const last = props.messages[props.messages.length - 1]
  if (last) volume += (last.content?.length || 0) + (last.thought?.length || 0)
  for (const message of props.messages) {
    for (const tc of message.toolCalls || []) {
      volume += tc.output?.length || 0
    }
  }
  return volume
})

watch(tailVolume, () => {
  nextTick(() => scrollToBottom())
})

/**
 * 工具/审批/技能卡首次出现或切换状态时，正文和 stdout 的长度可能都不变，原来的
 * tailVolume 不会触发贴底。这里保留影响卡片布局的轻量指纹，而不是 stringify 整个
 * result/uiPayload（结果可能很大），确保实时执行流中每个新卡片也会跟随到底部。
 */
const layoutFingerprint = computed(() => props.messages.map((message) => {
  const tools = (message.toolCalls || []).map((tool) => [
    tool.id,
    tool.status,
    tool.output?.length || 0,
    Object.keys(tool.arguments || {}).join(','),
    Object.keys((tool.result && typeof tool.result === 'object' ? tool.result : {}) as Record<string, unknown>).join(','),
    Object.keys(tool.uiPayload || {}).join(','),
    tool.approval?.status || '',
    tool.approval?.approval_id || '',
  ].join(':')).join('|')
  const skills = (message.skillInvocations || [])
    .map((skill) => `${skill.id}:${skill.status}:${skill.count}:${skill.summary || ''}:${skill.error || ''}`)
    .join('|')
  return [
    message.id,
    message.status || '',
    message.content.length,
    message.thought?.length || 0,
    tools,
    skills,
    message.timeline?.length || 0,
    message.charts?.length || 0,
    message.askRequest?.answered === false ? 'ask-pending' : '',
    message.overdriveApproval?.status || '',
    message.overdriveProgress?.phase || '',
  ].join('~')
}).join('\n'))

watch(layoutFingerprint, () => {
  nextTick(() => scrollToBottom())
})

watch(
  () => [props.streamingContent, props.streamingThought],
  () => {
    nextTick(() => scrollToBottom())
  },
)

watch(
  () => [props.targetMessageId, props.messages.length] as const,
  ([messageId]) => {
    if (!messageId) return
    nextTick(() => scrollToMessage(messageId))
  },
)

onMounted(() => {
  const el = scrollerRef.value?.$el as HTMLElement | undefined
  el?.addEventListener('scroll', handleScroll)
  scrollToBottom()
})

onUnmounted(() => {
  cancelScrollAnim()
  cancelFollowFrame()
  const el = scrollerRef.value?.$el as HTMLElement | undefined
  el?.removeEventListener('scroll', handleScroll)
})
</script>

<template>
  <div class="kimi-message-list">
    <DynamicScroller
      ref="scrollerRef"
      :items="messages"
      :min-item-size="80"
      key-field="id"
      class="message-scroller"
    >
      <template #default="{ item, index, active }">
        <DynamicScrollerItem
          :item="item"
          :active="active"
          :emit-resize="true"
          :size-dependencies="[
            item.content,
            item.thought,
            JSON.stringify(item.tokens),
            JSON.stringify(item.toolCalls),
            JSON.stringify(item.charts),
            JSON.stringify(item.routedAgent),
            JSON.stringify(item.collaborationRoute),
            JSON.stringify(item.askRequest),
            JSON.stringify(item.overdriveArtifacts),
            index === firstUserMessageIndex ? JSON.stringify(taskUnderstanding) : '',
            item.id === suggestionMessageId ? 'with-suggestion-chips' : '',
          ]"
          :data-index="index"
          :class="{ 'message-target': targetMessageId === item.id }"
          @resize="handleItemResize"
        >
          <KimiMessageItem
            :message="item"
            :is-streaming="item.id === streamingMessageId"
            :streaming-content="streamingContent"
            :streaming-thought="streamingThought"
            :model-name="modelName"
            :user-name="userName"
            :user-avatar="userAvatar"
            :agent-name="agentName"
            :agent-avatar="agentAvatar"
            :agent-color="agentColor"
            :session-id="sessionId"
            :suggestions-enabled="suggestionsEnabled"
            :show-suggestions="item.id === suggestionMessageId"
            @feedback="(id, type) => emit('feedback', id, type)"
            @copy="(mode) => emit('copy', mode)"
            @regenerate="(id) => emit('regenerate', id)"
            @retry-with-model="(id) => emit('retryWithModel', id)"
            @translate="(id) => emit('translate', id)"
            @delete="(id) => emit('delete', id)"
            @edit="(id) => emit('edit', id)"
            @confirm-tool="(toolName, args) => emit('confirmTool', toolName, args)"
            @open-tool-page="(route, args) => emit('openToolPage', route, args)"
            @create-case-from-consultation="(summary, consultationId) => emit('createCaseFromConsultation', summary, consultationId)"
            @correct-collaboration-route="(route) => emit('correctCollaborationRoute', route)"
            @suggestion-send="(prompt) => emit('suggestionSend', prompt)"
            @suggestion-prefill="(prompt) => emit('suggestionPrefill', prompt)"
          />
          <StudioTaskUnderstanding
            v-if="index === firstUserMessageIndex && taskUnderstanding"
            :understanding="taskUnderstanding"
          />
        </DynamicScrollerItem>
      </template>

    </DynamicScroller>

    <transition name="fade">
      <n-button
        v-if="showScrollToBottom"
        circle
        class="scroll-to-bottom"
        :title="hasNewWhileAway ? '有新消息，回到底部' : '回到底部'"
        @click="scrollBackToBottom"
      >
        <template #icon>
          <n-icon><ChevronDownOutline /></n-icon>
        </template>
        <span v-if="hasNewWhileAway" class="new-message-dot" aria-label="有新消息" />
      </n-button>
    </transition>
  </div>
</template>

<style scoped lang="scss">
.kimi-message-list {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;

  .message-scroller {
    height: 100%;
    padding: 16px 0;
    /* 预留滚动条位置：流式期间内容高度反复跨过"出现滚动条"临界值时，
       容器宽度不再变化，消除整列内容的水平抖动 */
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    scrollbar-color: rgba(46, 91, 255, 0.2) transparent;
    /* 由组件统一控制吸底，禁止浏览器滚动锚定与虚拟列表高度修正重复补偿。 */
    overflow-anchor: none;
  }

  .message-scroller::-webkit-scrollbar {
    width: 6px;
  }

  .message-scroller::-webkit-scrollbar-track {
    background: transparent;
  }

  .message-scroller::-webkit-scrollbar-thumb {
    background: rgba(46, 91, 255, 0.2);
    border-radius: 999px;
  }

  .message-scroller::-webkit-scrollbar-thumb:hover {
    background: rgba(46, 91, 255, 0.35);
  }

  :deep(.vue-recycle-scroller__item-wrapper) {
    padding: 0 24px;
    max-width: var(--chat-content-max-width, 860px);
    margin: 0 auto;
  }

  :deep(.vue-recycle-scroller__item-view) {
    /* 默认库样式会为所有消息长期创建 transform 合成层；流式滚动时容易造成文字栅格反复重采样。 */
    will-change: auto;
  }

  :deep(.message-target) {
    animation: messagePulse 1.4s ease;
  }

  /* typing-indicator 跳动点已移除 */

  .scroll-to-bottom {
    position: absolute;
    bottom: 20px;
    right: 40px;
    width: 36px;
    height: 36px;
    background: var(--bg-card);
    border: 1px solid rgba(46, 91, 255, 0.08);
    box-shadow: 0 2px 8px rgba(30, 50, 100, 0.12);
    color: var(--stardust-blue);
    overflow: visible;
  }

  .scroll-to-bottom:hover {
    background: var(--stardust-bg-soft);
    color: var(--stardust-blue);
  }

  /* 暂停吸底期间有新内容到达的红点提示 */
  .new-message-dot {
    position: absolute;
    top: -2px;
    right: -2px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #f5222d;
    border: 2px solid var(--bg-card, #fff);
    box-shadow: 0 1px 3px rgba(245, 34, 45, 0.4);
    pointer-events: none;
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes typingBounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-6px);
  }
}

@keyframes messagePulse {
  0%, 100% { background: transparent; }
  18%, 70% { background: color-mix(in srgb, var(--brand-primary-light, #EEF1FF) 70%, transparent); }
}
</style>
