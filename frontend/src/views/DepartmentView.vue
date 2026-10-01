<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NAvatar, NEmpty, NSpin, NTooltip } from 'naive-ui'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import KimiChatInput from '@/components/ai-chat/KimiChatInput.vue'
import { useMasRoomStore } from '@/stores/masRoom'

const PAGE_TITLE = '生物信息部门'
const DEFAULT_ROOM = 'bioinfo-dept'

const store = useMasRoomStore()

const draft = ref('')
const timelineRef = ref<HTMLElement | null>(null)
const autoScroll = ref(true)

const composerPlaceholder = computed(() =>
  store.runActive ? '部门正在处理中，可继续补充说明…' : '向生物信息部门提出你的科学问题…',
)

const timelineMessages = computed(() =>
  store.messages.map((m) => ({
    ...m,
    member: store.members.find((a) => a.agent_id === m.agent_id) || null,
    isUser: m.role === 'user',
    isTrace: m.role === 'mas_trace',
    isPlan: m.role === 'plan_card',
  })),
)

async function handleSend(content: string) {
  const text = (content || '').trim()
  if (!text || store.sending) return
  await store.sendMessage(DEFAULT_ROOM, text)
  scrollToBottom()
}

function handleScroll() {
  const el = timelineRef.value
  if (!el) return
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom() {
  if (!autoScroll.value) return
  void nextTick(() => {
    const el = timelineRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

watch(
  () => store.messages.length,
  () => scrollToBottom(),
)

onMounted(async () => {
  document.title = `${PAGE_TITLE} - CygnusX`
  await Promise.allSettled([store.loadMessages(DEFAULT_ROOM), store.loadMembers()])
  scrollToBottom()
  store.connectStream(DEFAULT_ROOM)
})

onBeforeUnmount(() => {
  store.disconnectStream()
})
</script>

<template>
  <main class="room-page">
    <NAlert
      v-if="!store.connected"
      type="warning"
      :bordered="false"
      class="room-stream-alert"
      title="实时连接未连接"
      :show-icon="true"
    >
      页面会继续使用事件轮询；若持续出现，请检查网络。
    </NAlert>
    <div class="room-layout">
      <!-- 左栏：部门成员 Surface Card -->
      <aside class="room-sidebar" aria-label="部门成员">
        <div class="room-sidebar__toolbar">
          <span class="room-sidebar__heading">部门成员</span>
          <span class="room-sidebar__count">{{ store.members.length }} 人</span>
        </div>
        <NSpin v-if="store.loading" class="room-sidebar__spin" />
        <div v-else-if="store.members.length === 0" class="room-sidebar__empty">
          <p class="room-sidebar__empty-title">暂无部门成员</p>
          <p class="room-sidebar__empty-desc">生物信息相关 Agent 将在这里出现</p>
        </div>
        <ul v-else class="room-sidebar__list">
          <li v-for="member in store.members" :key="member.agent_id" class="member-entry">
            <span
              class="member-entry__avatar"
              :style="{ backgroundColor: member.color, color: '#fff' }"
            >
              {{ member.avatar }}
            </span>
            <div class="member-entry__body">
              <div class="member-entry__name">{{ member.name }}</div>
              <NTooltip v-if="member.description" placement="right">
                <template #trigger>
                  <div class="member-entry__desc">{{ member.description }}</div>
                </template>
                <span>{{ member.description }}</span>
              </NTooltip>
            </div>
          </li>
        </ul>
      </aside>

      <!-- 右栏：消息主卡 -->
      <section class="room-main">
        <!-- 空状态引导（§35.4 克制欢迎区） -->
        <div v-if="store.loading === false && timelineMessages.length === 0" class="room-guide">
          <span class="room-guide__logo">🧬</span>
          <h1 class="room-guide__title">生物信息部门</h1>
          <p class="room-guide__lead">
            提出你的科学问题，部门成员将共同讨论并执行：Supervisor 组织专员分析，关键节点由你判断。
          </p>
          <div class="room-guide__actions">
            <button type="button" class="room-guide__pill" @click="draft = '帮我检查这批 RNA-seq 数据的质量'">
              检查 RNA-seq 数据质量
            </button>
            <button
              type="button"
              class="room-guide__pill"
              @click="draft = '帮我设计一个差异分析流程并执行'"
            >
              设计差异分析流程
            </button>
          </div>
        </div>

        <!-- 消息时间线 -->
        <div v-else ref="timelineRef" class="room-messages" @scroll="handleScroll">
          <div class="room-stream">
            <template v-for="msg in timelineMessages" :key="msg.id">
              <!-- 派工轨迹 / 计划卡：时间轴节点 -->
              <div v-if="msg.isTrace || msg.isPlan" class="tl-node">
                <div class="tl-node__rail">
                  <span class="tl-node__dot" :class="{ 'tl-node__dot--plan': msg.isPlan }"></span>
                </div>
                <div class="tl-node__body">
                  <span class="tl-node__badge" :class="{ 'tl-node__badge--plan': msg.isPlan }">
                    {{ msg.isPlan ? '计划' : '轨迹' }}
                  </span>
                  <span class="tl-node__text">{{ msg.content }}</span>
                  <span class="tl-node__time">{{ formatTime(msg.created_at) }}</span>
                </div>
              </div>
              <!-- 用户消息：右侧 -->
              <div v-else-if="msg.isUser" class="speech speech--user">
                <div class="speech__main">
                  <div class="speech__head">
                    <span class="speech__name">我</span>
                    <span class="speech__time">{{ formatTime(msg.created_at) }}</span>
                  </div>
                  <div class="speech__bubble">{{ msg.content }}</div>
                </div>
              </div>
              <!-- Agent 消息：左侧带头像（团队感） -->
              <div v-else class="speech">
                <NAvatar
                  v-if="msg.member"
                  class="room-avatar"
                  :style="{ backgroundColor: msg.member.color, color: '#fff' }"
                  :size="32"
                  round
                >
                  {{ msg.member.avatar }}
                </NAvatar>
                <span v-else class="room-avatar room-avatar--fallback">🤖</span>
                <div class="speech__main">
                  <div class="speech__head">
                    <span class="speech__name">{{ msg.member?.name || '部门助手' }}</span>
                    <span class="speech__time">{{ formatTime(msg.created_at) }}</span>
                  </div>
                  <div class="speech__bubble speech__bubble--agent">
                    <MarkdownRenderer :content="msg.content" />
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 底部输入区：复用平台共享 KimiChatInput -->
        <div class="room-composer">
          <KimiChatInput
            v-model="draft"
            room-mode
            :placeholder="composerPlaceholder"
            :disabled="store.sending"
            :send-loading="store.sending"
            :room-mention-agents="store.members"
            hint="Enter 发送，Shift+Enter 换行"
            @send="handleSend"
          />
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
/* ===== 页面骨架：Surface Base 页面底 + 左右两张 Surface Card（§3.3 / §4.2，迁移自团队协作室） ===== */
.room-page {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--page-padding, 32px);
  background: var(--neutral-bg);
  /* §3.3.5：非 .kimi-layout 作用域，必须为 KimiChatInput 补齐输入区语义变量 */
  --chat-input-bg: var(--neutral-card);
  --chat-input-border: var(--neutral-border);
}

.room-stream-alert {
  grid-column: 1 / -1;
}

.room-layout {
  display: grid;
  grid-template-areas: 'sidebar main';
  grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
  gap: var(--space-xl);
  flex: 1;
  min-height: 0;
}

/* ===== 左栏：部门成员 Surface Card ===== */
.room-sidebar {
  grid-area: sidebar;
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-lg);
  overflow: hidden;
  padding: var(--space-2xl);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
}

.room-sidebar__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.room-sidebar__heading {
  color: var(--neutral-text-1);
  font-size: var(--font-section-size);
  font-weight: var(--font-section-weight);
  line-height: var(--font-section-height);
  letter-spacing: var(--font-section-spacing);
}

.room-sidebar__count {
  color: var(--neutral-text-3);
  font-size: var(--font-caption-size);
}

.room-sidebar__empty {
  padding: var(--space-xl) 0;
}

.room-sidebar__empty-title {
  margin: 0;
  color: var(--neutral-text-2);
  font-size: var(--font-small-size);
  line-height: var(--font-small-height);
}

.room-sidebar__empty-desc {
  margin: var(--space-xs) 0 0;
  color: var(--neutral-text-3);
  font-size: var(--font-caption-size);
  line-height: var(--font-caption-height);
}

.room-sidebar__spin {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.room-sidebar__spin :deep(.n-spin-content) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.room-sidebar__list {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: var(--space-sm);
  align-content: start;
  overflow-y: auto;
  padding-right: 2px;
  margin: 0;
  padding-left: 0;
  padding-bottom: 0;
  list-style: none;
}

.room-sidebar__list::-webkit-scrollbar,
.room-messages::-webkit-scrollbar {
  width: 6px;
}

.room-sidebar__list::-webkit-scrollbar-thumb,
.room-messages::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: var(--scrollbar-thumb);
}

.room-sidebar__list::-webkit-scrollbar-thumb:hover,
.room-messages::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 成员列表项：品牌色头像徽标 + 名字 + 描述（§5.4） */
.member-entry {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  transition: border-color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out;
}

.member-entry:hover {
  border-color: color-mix(in srgb, var(--arco-primary) 14%, var(--neutral-border));
  background-color: color-mix(in srgb, var(--arco-primary) 4%, var(--neutral-card));
}

:root[data-theme='dark'] .member-entry:hover {
  border-color: var(--border-default);
  background-color: var(--surface-highlight);
}

.member-entry__avatar {
  display: inline-flex;
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-card);
  font-size: 20px;
}

.member-entry__body {
  display: grid;
  flex: 1;
  min-width: 0;
  gap: 2px;
}

.member-entry__name {
  overflow: hidden;
  color: var(--neutral-text-1);
  font-size: var(--font-body-size);
  font-weight: 500;
  line-height: var(--font-body-height);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-entry__desc {
  overflow: hidden;
  color: var(--neutral-text-3);
  font-size: var(--font-caption-size);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 右栏主体：与左栏同规格 Surface Card ===== */
.room-main {
  grid-area: main;
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
}

/* 空状态引导 */
.room-guide {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: min(100%, 720px);
  margin-inline: auto;
  padding: var(--space-2xl);
  text-align: center;
}

.room-guide__logo {
  display: inline-flex;
  width: 72px;
  height: 72px;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  font-size: 34px;
}

.room-guide__title {
  margin: var(--space-lg) 0 0;
  color: var(--neutral-text-1);
  font-size: var(--font-display-size);
  font-weight: var(--font-display-weight);
  line-height: var(--font-display-height);
  letter-spacing: var(--font-display-spacing);
}

.room-guide__lead {
  margin: var(--space-md) 0 0;
  max-width: 560px;
  color: var(--neutral-text-2);
  font-size: var(--font-body-size);
  line-height: var(--font-body-height);
}

.room-guide__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-sm);
  margin-top: var(--space-2xl);
}

.room-guide__pill {
  padding: var(--space-sm) var(--space-lg);
  border: 1px solid var(--neutral-border);
  border-radius: 999px;
  background: var(--neutral-card);
  color: var(--neutral-text-2);
  font-size: var(--font-small-size);
  line-height: var(--font-small-height);
  cursor: pointer;
  transition: background-color var(--motion-quick) ease-out, border-color var(--motion-quick) ease-out, color var(--motion-quick) ease-out;
}

.room-guide__pill:hover {
  border-color: var(--arco-primary);
  background: var(--arco-primary-light);
  color: var(--arco-primary);
}

.room-guide__pill:focus-visible {
  outline: 2px solid var(--arco-primary);
  outline-offset: 3px;
}

/* ===== 消息流：占满主卡可用宽度，scrollbar-gutter 消除水平抖动 ===== */
.room-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-xl) var(--space-2xl) var(--space-2xl);
  scrollbar-gutter: stable;
  scroll-padding-top: var(--space-xl);
}

.room-stream {
  display: grid;
  width: 100%;
  gap: var(--space-xl);
  align-content: start;
}

/* system 时间轴节点（轨迹/计划）：细轨 + 空心节点，12px 正文 / 11px 时间 */
.tl-node {
  display: flex;
  gap: var(--space-md);
}

.tl-node__rail {
  position: relative;
  width: 11px;
  flex: 0 0 11px;
}

.tl-node__rail::before {
  position: absolute;
  top: 0;
  bottom: calc(-1 * var(--space-xl));
  left: 50%;
  width: 1px;
  background: var(--neutral-border);
  content: '';
  transform: translateX(-50%);
}

.tl-node:last-child .tl-node__rail::before {
  display: none;
}

.tl-node__dot {
  position: absolute;
  top: 5px;
  left: 50%;
  width: 9px;
  height: 9px;
  border: 2px solid var(--neutral-border);
  border-radius: 50%;
  background: var(--neutral-card);
  box-shadow: 0 0 0 3px var(--neutral-card);
  transform: translateX(-50%);
}

.tl-node__dot--plan {
  border-color: var(--arco-primary);
}

.tl-node__body {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: var(--space-md);
  padding-bottom: 2px;
}

.tl-node__badge {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: 9999px;
  background: var(--neutral-border);
  color: var(--neutral-text-3);
  font-size: 11px;
  font-weight: 600;
}

.tl-node__badge--plan {
  background: var(--arco-primary-light);
  color: var(--arco-primary);
}

.tl-node__text {
  color: var(--neutral-text-2);
  font-size: var(--font-caption-size);
  line-height: 1.6;
}

.tl-node__time {
  flex: 0 0 auto;
  color: var(--neutral-text-3);
  font-size: 11px;
}

/* ===== 成员发言气泡（迁移自 KimiMessageItem / 团队协作室 .speech） ===== */
.speech {
  display: flex;
  gap: var(--space-md);
}

.speech--user {
  flex-direction: row-reverse;
}

.room-avatar {
  display: inline-flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: var(--text-on-primary);
  font-size: 15px;
}

.room-avatar--fallback {
  background: var(--neutral-fill-2);
  color: var(--neutral-text-2);
}

.speech__main {
  display: grid;
  min-width: 0;
  gap: var(--space-xs);
}

.speech--user .speech__main {
  width: min(720px, calc(100% - 32px - var(--space-md)));
  max-width: min(720px, calc(100% - 32px - var(--space-md)));
}

/* Agent 回复列宽钉在消息区的一半：宽屏下长回复不再铺满整行 */
.speech:not(.speech--user) .speech__main {
  width: max(50%, min(480px, calc(100% - 32px - var(--space-md))));
  max-width: calc(100% - 32px - var(--space-md));
  box-sizing: border-box;
}

.speech__head {
  display: flex;
  align-items: baseline;
  gap: var(--space-sm);
}

.speech--user .speech__head {
  flex-direction: row-reverse;
}

.speech__name {
  font-size: var(--font-small-size);
  font-weight: 600;
}

.speech__time {
  color: var(--neutral-text-3);
  font-size: var(--font-caption-size);
}

.speech__bubble {
  padding: var(--space-md) var(--space-lg);
  border: 1px solid var(--neutral-border);
  border-radius: 4px var(--radius-card) var(--radius-card) var(--radius-card);
  background: var(--neutral-fill-2);
  color: var(--neutral-text-1);
  font-size: var(--font-body-size);
  line-height: 1.7;
  word-break: break-all;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.speech--user .speech__bubble {
  justify-self: end;
  max-width: 75%;
  border-color: transparent;
  border-radius: var(--radius-card) 4px var(--radius-card) var(--radius-card);
  background: var(--arco-primary);
  color: var(--text-on-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* AI 输出经 MarkdownRenderer 渲染：white-space 重置为 normal */
.speech__bubble :deep(.md-body) {
  font-size: var(--font-body-size);
  white-space: normal;
}

.speech__bubble :deep(.md-body > :first-child) {
  margin-top: 0;
}

.speech__bubble :deep(.md-body > :last-child) {
  margin-bottom: 0;
}

/* ===== 底部输入区：复用 KimiChatInput（roomMode），不跟随整列铺满 ===== */
.room-composer {
  flex-shrink: 0;
  width: min(calc(100% - var(--space-3xl)), 1500px);
  margin: var(--space-lg) auto var(--space-2xl);
}

/* ≤1024px：左栏收纳为顶部横条 */
@media (max-width: 1024px) {
  .room-layout {
    grid-template-areas: 'main';
    grid-template-columns: minmax(0, 1fr);
  }

  .room-sidebar {
    grid-area: auto;
    max-height: 180px;
  }
}

/* ≤768px：页面内边距降至 16px，消息区同步收窄 */
@media (max-width: 768px) {
  .room-page {
    padding: var(--space-lg);
  }

  .room-messages {
    padding: var(--space-lg) var(--space-lg) var(--space-xl);
  }
}

@media (prefers-reduced-motion: reduce) {
  .member-entry,
  .room-guide__pill {
    transition: none;
  }
}
</style>
