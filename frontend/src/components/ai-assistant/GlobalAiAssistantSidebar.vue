<script setup lang="ts">
/**
 * 全局 AI 助手侧边栏
 *
 * 默认吸附在屏幕右边缘（收起为纵向标签，悬停滑出），点击展开右侧浮层面板；
 * 关闭面板后图标按同一路径收回右边缘。流式输出复用 /api/v1/chat/stream。
 * 样式遵循 ARCHITECTURE_DESIN/frontend.md：只消费语义令牌，动效 220ms 弹簧、可打断。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon, NInput, NSelect, NTooltip } from 'naive-ui'
import {
  AddOutline, AlertCircleOutline, CloseOutline, SendOutline, SparklesOutline, StopOutline,
} from '@vicons/ionicons5'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { useAiAssistantSidebarStore } from '@/stores/aiAssistantSidebar'

const store = useAiAssistantSidebarStore()
const route = useRoute()

// 这些页面已有完整 AI 工作区，不再叠加侧边栏
const HIDDEN_EXACT = ['/ai']
const HIDDEN_PREFIXES = ['/studio', '/agent-teams/room', '/agent-teams/cases']

const hidden = computed(() => {
  const path = route.path
  return HIDDEN_EXACT.includes(path) || HIDDEN_PREFIXES.some((p) => path.startsWith(p))
})

const visible = computed(() => !hidden.value)

// 进入 AI 工作区页面时自动收起，避免与页面内聊天重复
watch(
  () => route.path,
  () => {
    if (!hidden.value) return
    if (store.open) store.open = false
    hintVisible.value = false
  },
)

watch(
  () => store.open,
  (open) => {
    if (open && visible.value) void store.ensureModels()
  },
)

// ===== 首次使用提示气泡（只出现一次） =====
const HINT_KEY = 'cygnusx:ai-sidebar-hint-seen'
const hintVisible = ref(false)
let hintTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  if (localStorage.getItem(HINT_KEY)) return
  hintTimer = setTimeout(() => {
    if (!store.open && visible.value) hintVisible.value = true
  }, 1500)
})

onBeforeUnmount(() => {
  if (hintTimer) clearTimeout(hintTimer)
})

function dismissHint() {
  if (!hintVisible.value) return
  hintVisible.value = false
  localStorage.setItem(HINT_KEY, '1')
}

const inputValue = ref('')
const listEl = ref<HTMLElement | null>(null)

const modelOptions = computed(() =>
  store.models.map((m) => ({
    value: m.id,
    label: m.name === m.model ? m.name : `${m.name}（${m.model}）`,
  })),
)

const suggestions = [
  'OmicHub 支持哪些生信分析流程？',
  '帮我解释当前页面的功能',
  '如何上传和管理我的数据文件？',
]

async function scrollToBottom() {
  await nextTick()
  const el = listEl.value
  if (el) el.scrollTop = el.scrollHeight
}

// 新消息追加与流式输出期间持续滚到底部
watch(
  () => store.messages.map((m) => m.content.length + m.reasoning.length).join(','),
  () => void scrollToBottom(),
)

function openSidebar() {
  dismissHint()
  store.open = true
  void scrollToBottom()
}

function onSend() {
  const text = inputValue.value
  if (!text.trim() || store.isStreaming) return
  inputValue.value = ''
  void store.sendMessage(text, buildPageContext())
}

function onEnter(e: KeyboardEvent) {
  if (e.shiftKey) return
  e.preventDefault()
  onSend()
}

function quickSend(text: string) {
  if (store.isStreaming || !store.modelId) return
  void store.sendMessage(text, buildPageContext())
}

// ===== 当前页面上下文：随消息发给后端注入系统提示词，让 Agent 知道"当前页面"指哪里 =====
function buildPageContext(): string {
  const title = (route.meta?.title as string | undefined) || document.title || '未命名页面'
  const parts = [`页面名称：${title}`, `访问路径：${route.fullPath}`]
  const params = Object.entries(route.params).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1] !== '',
  )
  if (params.length) {
    parts.push(`页面参数：${params.map(([key, value]) => `${key}=${value}`).join('，')}`)
  }
  return parts.join('；')
}

// ===== 知识库引用标记：[[citation:kb-xxx]] → 小徽章（sanitize 前注入 HTML） =====
const CITATION_RE = /\[\[citation:([^\][\s]+)\]\]/g

function citeTransform(html: string): string {
  return html.replace(CITATION_RE, (_all, rawId: string) => {
    // id 只允许字母数字与连字符，防止注入属性（DOMPurify 会再兜一层）
    const id = String(rawId).replace(/[^A-Za-z0-9-]/g, '')
    const label = id.replace(/^kb-/, '').slice(0, 6)
    return `<span class="ai-cite" title="知识库来源：${id}">[${label}]</span>`
  })
}

// ===== 错误展示：把后端透传的长 JSON 错误压成一行摘要 + 可折叠详情 =====
function errorSummary(error: string): string {
  const match = error.match(/^请求失败（模型: ([^)]+)）: (\{[\s\S]*\})$/)
  if (match) {
    try {
      const payload = JSON.parse(match[2]) as { error?: { message?: string }; message?: string }
      const message = payload?.error?.message || payload?.message
      if (message) return `模型 ${match[1]} 请求失败：${message.slice(0, 140)}`
    } catch {
      // 非 JSON 详情，走通用截断
    }
  }
  return error.length > 160 ? `${error.slice(0, 160)}…` : error
}
</script>

<template>
  <div v-if="visible">
    <!-- 首次使用提示气泡 -->
    <Transition name="ai-hint">
      <div v-if="hintVisible && !store.open" class="ai-hint" role="status">
        <NIcon :size="16" class="ai-hint__icon"><SparklesOutline /></NIcon>
        <span class="ai-hint__text">AI 助手 · 随时提问</span>
        <button class="ai-hint__close" aria-label="关闭提示" @click.stop="dismissHint">
          <NIcon :size="12"><CloseOutline /></NIcon>
        </button>
      </div>
    </Transition>

    <!-- 吸附右边缘的入口标签（默认半隐藏，悬停滑出） -->
    <NTooltip placement="left" trigger="hover">
      <template #trigger>
        <button
          v-show="!store.open"
          class="ai-dock-tab"
          aria-label="打开 AI 助手"
          @click="openSidebar"
        >
          <NIcon :size="15" class="ai-dock-tab__icon"><SparklesOutline /></NIcon>
        </button>
      </template>
      AI 助手
    </NTooltip>

    <!-- 侧边栏浮层面板 -->
    <Transition name="ai-panel">
      <aside v-if="store.open" class="ai-sidebar" aria-label="AI 助手面板">
        <header class="ai-sidebar__header">
          <span class="ai-sidebar__logo" aria-hidden="true"><NIcon :size="16"><SparklesOutline /></NIcon></span>
          <div class="ai-sidebar__title">
            <span class="ai-sidebar__name">AI 助手</span>
            <span class="ai-sidebar__sub">通用助手 · 随时提问，跨页面陪伴</span>
          </div>
          <NTooltip trigger="hover">
            <template #trigger>
              <NButton text size="small" aria-label="新对话" @click="store.newChat()">
                <NIcon :size="18"><AddOutline /></NIcon>
              </NButton>
            </template>
            新对话
          </NTooltip>
          <NTooltip trigger="hover">
            <template #trigger>
              <NButton text size="small" aria-label="收起" @click="store.open = false">
                <NIcon :size="18"><CloseOutline /></NIcon>
              </NButton>
            </template>
            收起
          </NTooltip>
        </header>

        <div ref="listEl" class="ai-sidebar__messages">
          <!-- 空状态：欢迎语 + 快捷提问 -->
          <div v-if="!store.messages.length" class="ai-empty">
            <span class="ai-empty__icon" aria-hidden="true"><NIcon :size="26"><SparklesOutline /></NIcon></span>
            <p class="ai-empty__title">有什么可以帮你？</p>
            <p class="ai-empty__desc">我可以回答平台使用、生信分析等问题，对话内容会跨页面保留。</p>
            <div class="ai-empty__chips">
              <button
                v-for="s in suggestions"
                :key="s"
                class="ai-chip"
                :disabled="store.isStreaming"
                @click="quickSend(s)"
              >
                {{ s }}
              </button>
            </div>
          </div>

          <!-- 消息列表 -->
          <template v-else>
            <div
              v-for="m in store.messages"
              :key="m.id"
              class="ai-msg"
              :class="m.role === 'user' ? 'ai-msg--user' : 'ai-msg--assistant'"
            >
              <div class="ai-msg__bubble">
                <template v-if="m.role === 'user'">{{ m.content }}</template>
                <template v-else>
                  <details v-if="m.reasoning" class="ai-msg__reasoning">
                    <summary>思考过程</summary>
                    <p>{{ m.reasoning }}</p>
                  </details>
                  <MarkdownRenderer v-if="m.content" :content="m.content" :transform="citeTransform" />
                  <span v-else-if="m.status === 'streaming'" class="ai-msg__cursor">正在思考…</span>
                  <div v-if="m.status === 'error'" class="ai-msg__error">
                    <span class="ai-msg__error-line">
                      <NIcon :size="14" aria-hidden="true"><AlertCircleOutline /></NIcon>
                      {{ errorSummary(m.error || '生成失败，请重试') }}
                    </span>
                    <details
                      v-if="(m.error || '').length > errorSummary(m.error || '').length + 8"
                      class="ai-msg__error-detail"
                    >
                      <summary>查看详情</summary>
                      <pre>{{ m.error }}</pre>
                    </details>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </div>

        <footer class="ai-sidebar__footer">
          <div v-if="store.loadError" class="ai-sidebar__load-error">{{ store.loadError }}</div>
          <div v-if="modelOptions.length > 1" class="ai-sidebar__model-row">
            <NSelect
              v-model:value="store.modelId"
              :options="modelOptions"
              size="tiny"
              :disabled="store.isStreaming"
              aria-label="选择模型"
            />
          </div>
          <div class="ai-sidebar__input-row">
            <NInput
              v-model:value="inputValue"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 6 }"
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              @keydown="onEnter"
            />
            <NButton
              v-if="store.isStreaming"
              size="small"
              circle
              secondary
              type="error"
              aria-label="停止生成"
              @click="store.stopStreaming()"
            >
              <NIcon :size="16"><StopOutline /></NIcon>
            </NButton>
            <NButton
              v-else
              size="small"
              circle
              type="primary"
              :disabled="!inputValue.trim() || !store.modelId"
              aria-label="发送"
              @click="onSend"
            >
              <NIcon :size="16"><SendOutline /></NIcon>
            </NButton>
          </div>
        </footer>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
/* ===== 吸附右边缘的入口标签 =====
   默认向屏幕外收回只露出窄边条，半透明降低存在感；悬停/聚焦滑出并恢复不透明。
   （§1 空间一致：从右出、从右收；§6.3 减少动态下关闭俏皮动画） */
.ai-dock-tab {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%) translateX(10px);
  width: 30px;
  height: 56px;
  padding: 0;
  border: 1px solid var(--neutral-border);
  border-right: none;
  border-radius: 10px 0 0 10px;
  color: var(--arco-primary);
  background: var(--neutral-card);
  background: color-mix(in srgb, var(--neutral-card) 55%, transparent);
  opacity: 0.65;
  box-shadow: var(--shadow-card);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 1900;
  transition: transform var(--motion-standard) var(--motion-spring),
    opacity var(--motion-quick) ease-out,
    box-shadow var(--motion-quick) ease-out,
    background-color var(--motion-quick) ease-out;
}
.ai-dock-tab:hover,
.ai-dock-tab:focus-visible {
  transform: translateY(-50%) translateX(0);
  opacity: 1;
  background: var(--neutral-card);
  box-shadow: var(--shadow-card-hover);
}
.ai-dock-tab:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 3px;
}
/* 俏皮动画：悬停时星芒图标轻轻摇摆 */
@keyframes ai-dock-wiggle {
  0%, 100% { transform: rotate(0deg) scale(1); }
  30% { transform: rotate(-14deg) scale(1.18); }
  65% { transform: rotate(10deg) scale(1.1); }
}
.ai-dock-tab:hover .ai-dock-tab__icon,
.ai-dock-tab:focus-visible .ai-dock-tab__icon {
  animation: ai-dock-wiggle 0.9s ease-in-out infinite;
}

/* ===== 首次提示气泡 ===== */
.ai-hint {
  position: fixed;
  right: 42px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 12px;
  border: 1px solid var(--neutral-border);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
  z-index: 1899;
}
/* 指向右缘标签的小箭头 */
.ai-hint::after {
  content: '';
  position: absolute;
  right: -5px;
  top: 50%;
  width: 10px;
  height: 10px;
  transform: translateY(-50%) rotate(45deg);
  background: var(--neutral-card);
  border-top: 1px solid var(--neutral-border);
  border-right: 1px solid var(--neutral-border);
}
.ai-hint__icon {
  color: var(--arco-primary);
  flex-shrink: 0;
}
.ai-hint__text {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1);
  white-space: nowrap;
}
.ai-hint__close {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--neutral-text-3);
  cursor: pointer;
  transition: color var(--motion-quick) ease-out,
    background var(--motion-quick) ease-out;
}
.ai-hint__close:hover {
  color: var(--neutral-text-1);
  background: var(--neutral-hover);
}
.ai-hint__close:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 2px;
}
.ai-hint-enter-active,
.ai-hint-leave-active {
  transition: opacity var(--motion-standard) var(--motion-spring),
    transform var(--motion-standard) var(--motion-spring);
}
.ai-hint-enter-from,
.ai-hint-leave-to {
  opacity: 0;
  transform: translateY(-50%) translateX(12px);
}

/* ===== 浮层面板（半透明偏移面板，不强制遮罩，§4.2.5） ===== */
.ai-sidebar {
  position: fixed;
  top: 72px;
  right: 16px;
  bottom: 16px;
  width: 400px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column;
  /* 玻璃浮层（§4.2.5 并行非阻塞面板），底色由令牌派生，不写死白色 */
  background: var(--neutral-card);
  background: color-mix(in srgb, var(--neutral-card) 88%, transparent);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid var(--neutral-border);
  border-radius: 16px;
  box-shadow: var(--shadow-dropdown);
  overflow: hidden;
  z-index: 1800;
}
:root[data-theme="dark"] .ai-sidebar {
  background: var(--surface-elevated);
  border-color: var(--border-default);
}

.ai-panel-enter-active,
.ai-panel-leave-active {
  transition: transform var(--motion-standard) var(--motion-spring),
    opacity var(--motion-standard) var(--motion-spring);
}
.ai-panel-enter-from,
.ai-panel-leave-to {
  transform: translateX(24px);
  opacity: 0;
}

.ai-sidebar__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--neutral-border);
  flex-shrink: 0;
}
.ai-sidebar__logo {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--text-on-primary, #fff);
  background: var(--arco-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ai-sidebar__title {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ai-sidebar__name {
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
  color: var(--neutral-text-1);
}
.ai-sidebar__sub {
  font-size: 12px;
  line-height: 18px;
  color: var(--neutral-text-3);
}

.ai-sidebar__messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: transparent;
}

/* ===== 空状态 ===== */
.ai-empty {
  margin: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 0 12px;
}
.ai-empty__icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  color: var(--arco-primary);
  background: var(--arco-primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}
.ai-empty__title {
  margin: 0;
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
  color: var(--neutral-text-1);
}
.ai-empty__desc {
  margin: 4px 0 16px;
  font-size: 12px;
  line-height: 18px;
  color: var(--neutral-text-3);
}
.ai-empty__chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.ai-chip {
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
  background: var(--neutral-card);
  color: var(--neutral-text-2);
  font-size: 13px;
  line-height: 20px;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--motion-quick) ease-out,
    color var(--motion-quick) ease-out,
    box-shadow var(--motion-quick) ease-out;
}
.ai-chip:hover:not(:disabled) {
  border-color: var(--arco-primary);
  color: var(--arco-primary);
}
.ai-chip:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 2px;
}
.ai-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 消息气泡 ===== */
.ai-msg {
  display: flex;
}
.ai-msg--user {
  justify-content: flex-end;
}
.ai-msg__bubble {
  max-width: 88%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 20px;
  word-break: break-word;
  white-space: pre-wrap;
}
.ai-msg--user .ai-msg__bubble {
  background: var(--arco-primary);
  color: var(--text-on-primary, #fff);
  border-bottom-right-radius: 4px;
}
.ai-msg--assistant .ai-msg__bubble {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  color: var(--neutral-text-1);
  border-bottom-left-radius: 4px;
}

.ai-msg__reasoning {
  margin-bottom: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--neutral-hover);
  font-size: 12px;
  line-height: 18px;
  color: var(--neutral-text-3);
}
.ai-msg__reasoning summary {
  cursor: pointer;
  font-weight: 500;
}
.ai-msg__reasoning p {
  margin: 4px 0 0;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}

.ai-msg__cursor {
  color: var(--neutral-text-3);
  animation: ai-blink 1.2s ease-in-out infinite;
}
@keyframes ai-blink {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
}

/* ===== 消息内 Markdown 排版（§3.4：小正文 13px/20px，间距走 4/8/12 阶梯） ===== */
/* 关键修复：气泡的 white-space: pre-wrap 会继承进 v-html，
   markdown 块级元素之间的换行文本节点被渲染成额外空行（"段间大空白"的根因），
   这里在 markdown 容器内还原为 normal。 */
.ai-msg__bubble :deep(.md-body) {
  font-size: 13px;
  line-height: 1.6;
  white-space: normal;
}
.ai-msg__bubble :deep(.md-body > :first-child) {
  margin-top: 0;
}
.ai-msg__bubble :deep(.md-body > :last-child) {
  margin-bottom: 0;
}
.ai-msg__bubble :deep(.md-body p) {
  margin: 8px 0;
}
.ai-msg__bubble :deep(.md-body h1) {
  font-size: 16px;
  line-height: 24px;
  font-weight: 600;
  margin: 12px 0 8px;
}
.ai-msg__bubble :deep(.md-body h2) {
  font-size: 15px;
  line-height: 22px;
  font-weight: 600;
  margin: 12px 0 8px;
}
.ai-msg__bubble :deep(.md-body h3) {
  font-size: 14px;
  line-height: 22px;
  font-weight: 600;
  margin: 12px 0 8px;
}
.ai-msg__bubble :deep(.md-body h4),
.ai-msg__bubble :deep(.md-body h5),
.ai-msg__bubble :deep(.md-body h6) {
  font-size: 13px;
  line-height: 20px;
  font-weight: 600;
  margin: 8px 0 4px;
}
.ai-msg__bubble :deep(.md-body ul),
.ai-msg__bubble :deep(.md-body ol) {
  margin: 8px 0;
  padding-left: 1.2em;
}
.ai-msg__bubble :deep(.md-body blockquote) {
  margin: 8px 0;
}
.ai-msg__bubble :deep(.md-body pre.hljs) {
  margin: 8px 0;
  padding: 10px 12px;
}
.ai-msg__bubble :deep(.md-body table) {
  margin: 8px 0;
  font-size: 12px;
  display: block;
  overflow-x: auto;
}
.ai-msg__bubble :deep(.md-body th),
.ai-msg__bubble :deep(.md-body td) {
  padding: 5px 8px;
}
/* 知识库引用徽章：替代裸 [[citation:kb-xxx]] 文本 */
.ai-msg__bubble :deep(.ai-cite) {
  font-style: normal;
  font-size: 11px;
  line-height: 1;
  color: var(--arco-primary);
  background: var(--arco-primary-light);
  border-radius: 4px;
  padding: 2px 4px;
  margin: 0 1px;
  white-space: nowrap;
  cursor: help;
  vertical-align: 1px;
}

.ai-msg__error {
  margin-top: 4px;
  font-size: 12px;
  line-height: 18px;
  color: var(--arco-danger);
}
.ai-msg__error-line {
  display: inline-flex;
  align-items: flex-start;
  gap: 4px;
}
.ai-msg__error-detail {
  margin-top: 4px;
}
.ai-msg__error-detail summary {
  cursor: pointer;
  color: var(--neutral-text-3);
}
.ai-msg__error-detail pre {
  margin: 4px 0 0;
  padding: 8px 10px;
  max-height: 180px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--neutral-hover);
  border-radius: 6px;
  color: var(--neutral-text-2);
}

/* ===== 输入区 ===== */
.ai-sidebar__footer {
  padding: 12px;
  border-top: 1px solid var(--neutral-border);
  flex-shrink: 0;
}
.ai-sidebar__load-error {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--arco-danger);
}
.ai-sidebar__model-row {
  margin-bottom: 8px;
}
.ai-sidebar__model-row :deep(.n-select) {
  width: 100%;
}
.ai-sidebar__input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.ai-sidebar__input-row :deep(.n-input) {
  flex: 1;
}

@media (max-width: 480px) {
  .ai-sidebar {
    top: 64px;
    right: 8px;
    bottom: 8px;
    width: calc(100vw - 16px);
  }
}

/* ===== 减少动态 / 减少透明度回退（§6.3、§7.2） ===== */
@media (prefers-reduced-motion: reduce) {
  .ai-dock-tab,
  .ai-hint__close,
  .ai-chip,
  .ai-panel-enter-active,
  .ai-panel-leave-active,
  .ai-hint-enter-active,
  .ai-hint-leave-active {
    transition: none;
  }
  .ai-msg__cursor {
    animation: none;
    opacity: 1;
  }
  .ai-dock-tab .ai-dock-tab__icon {
    animation: none;
  }
}
@media (prefers-reduced-transparency: reduce) {
  .ai-sidebar,
  .ai-dock-tab {
    background: var(--neutral-card);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    opacity: 1;
  }
}
</style>
