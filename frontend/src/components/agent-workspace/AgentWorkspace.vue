<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AgentSidebar from './AgentSidebar.vue'
import AgentHub from './AgentHub.vue'
import AgentSandbox from './AgentSandbox.vue'
import SessionHistoryDrawer from './SessionHistoryDrawer.vue'
import AppLoading from '@/components/AppLoading.vue'
import { useAgentHubStore, type AgentSession } from '@/stores/agentHub'
import { ArrowForwardOutline, CompassOutline } from '@vicons/ionicons5'
import { NButton, NIcon, NModal } from 'naive-ui'

const store = useAgentHubStore()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const historyOpen = ref(false)
const agentPickerOpen = ref(false)
const agentPickerIntent = ref<'new-chat' | 'agent-center'>('new-chat')
const targetMessageId = ref('')
let agentPickerTrigger: HTMLElement | null = null

const agentPickerCopy = computed(() =>
  agentPickerIntent.value === 'agent-center'
    ? {
        kicker: '智能体中心',
        title: '选择下一位专家',
        description: '当前对话会保留在历史记录中。选择后将开启一段新的专家会话。',
      }
    : {
        kicker: '新建对话',
        title: '选择处理方式',
        description: '默认由星尘 AI 识别任务并分派；熟悉任务时也可以直接指定专家。',
      },
)

/** 统一入口 Agent：星尘 AI 负责理解任务并分派给可用专家。 */
const ROUTER_AGENT_ID = 'agent-router'

/** 首次进入默认恢复最近一次会话；没有历史会话时才新建星尘 AI 调度会话。
 *  “新建对话”入口（startSessionFromAgent）不受影响。 */
function ensureDefaultSession() {
  if (store.currentSession) return
  // 跳过未落库的临时会话（sess-）与工作台会话（工作台会话由 Studio 页面承载）
  const recent = store.sessions.find(
    (s) => !s.id.startsWith('sess-') && s.mode !== 'studio' && !store.studioSessionIds.has(s.id),
  )
  if (recent) {
    void store.selectSession(recent.id)
    return
  }
  const routerAgent =
    store.activeAgents.find((a) => a.id === ROUTER_AGENT_ID) ||
    store.activeAgents.find((a) => a.features?.router) ||
    store.activeAgents.find((a) => a.is_default) ||
    store.activeAgents[0]
  if (routerAgent) store.startSessionFromAgent(routerAgent.id)
}

async function initAssets() {
  loading.value = true
  error.value = ''
  try {
    await store.initAssets()
    ensureDefaultSession()
  } catch (e: any) {
    error.value = e?.message || '加载 Agent 数据失败'
  } finally {
    loading.value = false
  }
}

onMounted(initAssets)

function handleNewChat() {
  agentPickerIntent.value = 'new-chat'
  agentPickerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  agentPickerOpen.value = true
}

function handleOpenAgentCenter() {
  agentPickerIntent.value = 'agent-center'
  agentPickerTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  agentPickerOpen.value = true
}

function handleSelectAgent(agentId: string) {
  agentPickerTrigger = null
  agentPickerOpen.value = false
  store.startSessionFromAgent(agentId)
}

function handleAgentPickerAfterLeave() {
  const trigger = agentPickerTrigger
  agentPickerTrigger = null
  if (trigger?.isConnected) void nextTick(() => trigger.focus())
}

function handleHistorySelect(session: AgentSession, messageId?: string) {
  if (session.mode === 'studio' || store.studioSessionIds.has(session.id)) {
    router.push({ name: 'studio', params: { sessionId: session.id }, query: messageId ? { message: messageId } : {} })
    return
  }
  if (!store.sessions.some((item) => item.id === session.id)) store.sessions.unshift(session)
  targetMessageId.value = messageId || ''
  store.selectSession(session.id)
}
</script>

<template>
  <div class="agent-workspace">
    <AgentSidebar
      @new-chat="handleNewChat"
      @open-history="historyOpen = true"
    />
    <main class="workspace-main">
      <div v-if="loading" class="workspace-center">
        <AppLoading text="加载 AI 助手..." />
      </div>
      <div v-else-if="error" class="workspace-center">
        <p class="text-sm text-gray-500 mb-3">{{ error }}</p>
        <NButton size="small" @click="initAssets">重试</NButton>
      </div>
      <template v-else>
        <AgentSandbox
          v-if="store.currentSession"
          :target-message-id="targetMessageId"
          @open-agent-picker="handleOpenAgentCenter"
        />
        <AgentHub v-else @select="handleSelectAgent" />
      </template>
    </main>
    <SessionHistoryDrawer v-model:show="historyOpen" mode="all" @select="handleHistorySelect" />
    <NModal
      v-model:show="agentPickerOpen"
      class="agent-picker-modal"
      preset="card"
      style="width: min(1080px, calc(100vw - 32px)); max-height: calc(100dvh - 32px)"
      :bordered="false"
      :segmented="false"
      aria-labelledby="agent-picker-title"
      @after-leave="handleAgentPickerAfterLeave"
    >
      <div class="agent-picker-content">
        <header class="agent-picker-header">
          <span class="agent-picker-mark" aria-hidden="true">
            <NIcon :component="CompassOutline" />
          </span>
          <div class="agent-picker-heading">
            <span class="agent-picker-kicker">{{ agentPickerCopy.kicker }}</span>
            <h2 id="agent-picker-title">{{ agentPickerCopy.title }}</h2>
            <p>{{ agentPickerCopy.description }}</p>
          </div>
        </header>
        <button
          class="stardust-route-card"
          type="button"
          aria-label="交给星尘 AI 自动分派"
          @click="handleSelectAgent(ROUTER_AGENT_ID)"
        >
          <span class="route-icon" aria-hidden="true"><NIcon :component="CompassOutline" /></span>
          <span class="route-copy">
            <span class="route-title-row">
              <strong>交给星尘 AI 自动分派</strong>
              <span class="route-recommended">推荐</span>
            </span>
            <span>描述目标、数据或当前问题，由星尘决定接下来由哪位 Agent 继续处理。</span>
          </span>
          <NIcon class="route-action" :component="ArrowForwardOutline" aria-hidden="true" />
        </button>
        <section class="agent-picker-experts" aria-labelledby="agent-picker-experts-title">
          <div class="agent-picker-section-heading">
            <div>
              <strong id="agent-picker-experts-title">直接选择专家</strong>
              <span>根据任务领域快速定位合适的智能体</span>
            </div>
            <span class="agent-picker-section-hint">按领域切换查看</span>
          </div>
          <div class="agent-picker-scroll">
            <AgentHub compact :exclude-agent-ids="[ROUTER_AGENT_ID]" @select="handleSelectAgent" />
          </div>
        </section>
        <footer class="agent-picker-footer">
          <p>选择后会开启新对话，当前会话仍可从历史记录中恢复。</p>
          <NButton quaternary size="small" @click="agentPickerOpen = false">暂不切换</NButton>
        </footer>
      </div>
    </NModal>
  </div>
</template>

<style scoped lang="scss">
.agent-workspace {
  display: flex;
  width: 100%;
  height: 100%;
  background: var(--chat-bg);
  color: var(--chat-text-primary, inherit);
  overflow: hidden;
}

.workspace-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
:deep(.agent-picker-modal.n-card),
:deep(.agent-picker-modal .n-card) {
  max-height: calc(100dvh - 32px);
  overflow: hidden;
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: var(--radius-xl, 20px);
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--arco-primary) 5%, var(--chat-surface, var(--neutral-card))) 0,
      var(--chat-surface, var(--neutral-card)) 148px
    );
  box-shadow: 0 24px 72px color-mix(in srgb, var(--neutral-text-1) 18%, transparent);
}

:deep(.agent-picker-modal .n-card__content),
:deep(.agent-picker-modal.n-card .n-card__content) {
  max-height: calc(100dvh - 32px);
  padding: var(--space-2xl, 24px) var(--space-3xl, 32px) var(--space-xl, 20px);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.agent-picker-content {
  min-height: 0;
}

.agent-picker-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-lg, 16px);
  margin-bottom: var(--space-2xl, 24px);
  padding-right: var(--space-3xl, 32px);
}

.agent-picker-mark {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--arco-primary) 28%, transparent);
  border-radius: 14px;
  color: var(--text-on-primary);
  background: var(--brand-gradient);
  box-shadow: 0 10px 24px color-mix(in srgb, var(--arco-primary) 24%, transparent);
  font-size: 21px;
}

.agent-picker-heading {
  min-width: 0;
}

.agent-picker-kicker {
  display: block;
  margin-bottom: 2px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .1em;
  color: var(--arco-primary);
}

.agent-picker-header h2 {
  margin: 0;
  font-size: 24px;
  line-height: 32px;
  font-weight: 650;
  letter-spacing: -.02em;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.agent-picker-header p {
  max-width: 680px;
  margin: 5px 0 0;
  font-size: 13px;
  line-height: 20px;
  color: var(--chat-text-secondary, var(--neutral-text-2));
}

.stardust-route-card {
  position: relative;
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-lg, 16px);
  padding: 17px 18px;
  border: 1px solid color-mix(in srgb, var(--arco-primary) 38%, var(--chat-border, var(--neutral-border)));
  border-radius: var(--radius-card, 14px);
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: color-mix(in srgb, var(--arco-primary) 6%, var(--chat-surface, var(--neutral-card)));
  box-shadow: inset 3px 0 0 var(--arco-primary);
  transition:
    border-color var(--motion-quick, 140ms) ease-out,
    background-color var(--motion-quick, 140ms) ease-out,
    box-shadow var(--motion-quick, 140ms) ease-out,
    transform var(--motion-quick, 140ms) ease-out;
}

.stardust-route-card:hover {
  border-color: color-mix(in srgb, var(--arco-primary) 66%, var(--chat-border, var(--neutral-border)));
  background: color-mix(in srgb, var(--arco-primary) 9%, var(--chat-surface, var(--neutral-card)));
  box-shadow: inset 3px 0 0 var(--arco-primary), var(--shadow-card);
  transform: translateY(-1px);
}

.stardust-route-card:focus-visible {
  outline: 2px solid var(--border-focus, var(--arco-primary));
  outline-offset: 3px;
}

.route-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  color: var(--text-on-primary);
  background: var(--brand-gradient);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--arco-primary) 22%, transparent);
}

.route-copy {
  display: grid;
  min-width: 0;
  gap: 5px;
}

.route-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.route-copy .route-title-row strong {
  font-size: 14px;
  font-weight: 650;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.route-copy > span:last-child {
  font-size: 12px;
  line-height: 19px;
  color: var(--chat-text-secondary, var(--neutral-text-2));
}

.route-recommended {
  padding: 1px 7px;
  border-radius: 999px;
  color: var(--arco-primary);
  background: color-mix(in srgb, var(--arco-primary) 12%, transparent);
  font-size: 10px;
  font-weight: 700;
  line-height: 18px;
}

.route-action {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--arco-primary);
  font-size: 19px;
}

.agent-picker-experts {
  margin-top: var(--space-2xl, 24px);
}

.agent-picker-section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-lg, 16px);
  margin-bottom: var(--space-md, 12px);
}

.agent-picker-section-heading > div {
  display: grid;
  gap: 2px;
}

.agent-picker-section-heading strong {
  font-size: 14px;
  font-weight: 650;
  color: var(--chat-text-primary, var(--neutral-text-1));
}

.agent-picker-section-heading span {
  font-size: 12px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.agent-picker-section-hint {
  flex: 0 0 auto;
}

.agent-picker-scroll {
  min-height: 0;
}

.agent-picker-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-lg, 16px);
  margin-top: var(--space-xl, 20px);
  padding-top: var(--space-lg, 16px);
  border-top: 1px solid var(--chat-border, var(--neutral-border));
}

.agent-picker-footer p {
  margin: 0;
  color: var(--chat-text-muted, var(--neutral-text-3));
  font-size: 12px;
  line-height: 18px;
}

@media (max-width: 640px) {
  :deep(.agent-picker-modal .n-card__content),
  :deep(.agent-picker-modal.n-card .n-card__content) {
    padding: var(--space-lg, 16px);
  }

  .agent-picker-header {
    gap: var(--space-md, 12px);
    margin-bottom: var(--space-lg, 16px);
    padding-right: var(--space-xl, 20px);
  }

  .agent-picker-mark {
    width: 40px;
    height: 40px;
    border-radius: 12px;
  }

  .agent-picker-header h2 {
    font-size: 20px;
    line-height: 28px;
  }

  .stardust-route-card {
    align-items: flex-start;
    padding: 14px;
  }

  .route-action { display: none; }

  .agent-picker-section-heading {
    align-items: flex-start;
  }

  .agent-picker-section-hint {
    display: none;
  }

  .agent-picker-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .stardust-route-card {
    transition: none;
  }

  .stardust-route-card:hover {
    transform: none;
  }
}

.workspace-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
</style>
