<script setup lang="ts">
/**
 * [LEGACY] Model-first 旧版布局
 *
 * 当前 `/ai` 路由不再直接挂载该组件，已切到 Agent-first 的 AgentWorkspace。
 * 保留原因：
 *   1. 底层聊天组件（KimiMessageList / KimiChatInput / KimiMessageItem）仍被 AgentSandbox 复用；
 *   2. 便于未来需要切回模型优先模式或做 A/B 对比时快速恢复。
 *
 * 未来去留：当 Agent-first 模式完全覆盖模型优先能力后，可删除 legacy/ 目录
 * 及 chatSession / chatAssistant 等模型优先 Store。
 */
import { ref, computed, onMounted } from 'vue'
import { useMagicKeys, whenever } from '@vueuse/core'
import { useRouter } from 'vue-router'
import { NAlert, useMessage } from 'naive-ui'
import KimiSidebar from './KimiSidebar.vue'
import KimiEmptyState from './KimiEmptyState.vue'
import KimiMessageList from '../KimiMessageList.vue'
import KimiChatInput from '../KimiChatInput.vue'
import ModelNavBar from './ModelNavBar.vue'
import apiClient from '@/api/client'
import { chatApi } from '@/api/chat'
import { displayName } from '@/utils/displayName'
import { useChatSessionStore } from '@/stores/chatSession'
import { useChatAssistantStore } from '@/stores/chatAssistant'
import { useChatStore } from '@/stores/chat'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import type { ChatMessage, ChatSession, SendOptions, CopyMode } from '../types'

const chatSessionStore = useChatSessionStore()
const chatAssistantStore = useChatAssistantStore()
const chatStore = useChatStore()
const themeStore = useThemeStore()
const authStore = useAuthStore()
const router = useRouter()
const message = useMessage()

const inputMessage = ref('')
const aiConfigured = ref(true)

const userInfo = computed(() => ({
  id: String(authStore.user?.id ?? ''),
  name: displayName(authStore.user) || '用户',
  avatar: '',
  role: authStore.user?.role === 'admin' ? '管理员' : '普通用户',
  roleTag: authStore.user?.role === 'admin' ? 'Admin' : 'User',
}))

// chatSessionStore.sessions -> KimiSidebar 需要的 ChatSession[]
const sessions = computed<ChatSession[]>(() =>
  chatSessionStore.sessions.map((s) => ({
    id: s.session_id,
    title: s.title,
    messages: [],
    createdAt: s.created_at,
    updatedAt: s.updated_at,
    model: s.model_id,
  }))
)

const currentSessionId = computed(() => chatSessionStore.currentSessionId)

// chatSessionStore.messages -> KimiMessageList 需要的 ChatMessage[]
const messages = computed<ChatMessage[]>(() => {
  // 依赖流式内容，确保 SSE 推流时能实时触发重新渲染
  const _ = chatSessionStore.streamingContent + chatSessionStore.streamingReasoning
  return chatSessionStore.messages.map((m) => ({
    id: m.message_id,
    role: m.role as ChatMessage['role'],
    content: m.content,
    thought: m.reasoning,
    createdAt: m.created_at,
  }))
})

const isEmpty = computed(
  () => !chatSessionStore.currentSessionId || messages.value.length === 0,
)

// 当前模型名称（供消息引用格式使用）
const currentModelName = computed(() => chatSessionStore.selectedModel?.name ?? 'AI 助手')

const streamingContent = computed(() => {
  // 依赖流式内容，确保 SSE 推流时 streamingContent 能实时更新
  const _ = chatSessionStore.streamingContent
  const msgs = chatSessionStore.messages
  const last = msgs[msgs.length - 1]
  return last?.role === 'assistant' && last.status === 'streaming' ? last.content : ''
})

const streamingReasoning = computed(() => {
  // 依赖流式思考内容，确保 reasoning 能实时更新
  const _ = chatSessionStore.streamingReasoning
  const msgs = chatSessionStore.messages
  const last = msgs[msgs.length - 1]
  return last?.role === 'assistant' && last.status === 'streaming' ? last.reasoning : ''
})

const showConfigWarning = computed(() => !aiConfigured.value)
const showStreamError = computed(() => !!chatSessionStore.streamError)

const { Meta_K, Ctrl_K } = useMagicKeys()
whenever(Meta_K, () => newSession())
whenever(Ctrl_K, () => newSession())

// ===== 操作 =====
async function newSession() {
  chatSessionStore.clearDisplayMessages()
  chatSessionStore.currentSessionId = ''
  inputMessage.value = ''
}

async function selectSession(id: string) {
  await chatSessionStore.selectSession(id)
  inputMessage.value = ''
}

async function deleteSession(id: string) {
  await chatSessionStore.deleteSession(id)
}

async function handleSend(content: string, _options: SendOptions) {
  if (!content.trim() || chatSessionStore.isStreaming) return

  // 确保有选中的模型
  if (!chatSessionStore.selectedModelId) {
    await chatSessionStore.fetchModels()
  }
  if (!chatSessionStore.selectedModelId) {
    message.error('请先在模型配置中选择一个可用的 AI 模型')
    return
  }

  // 如果没有会话，先创建一个
  if (!chatSessionStore.currentSessionId) {
    const sid = await chatSessionStore.createSession(
      chatSessionStore.selectedModelId,
      chatAssistantStore.currentAssistantId || undefined,
    )
    if (!sid) {
      message.error('创建会话失败')
      return
    }
  }

  inputMessage.value = ''
  await chatSessionStore.sendMessage(content, {
    assistantId: chatAssistantStore.currentAssistantId || undefined,
    // [极简测试] 临时禁用助手系统提示词
    // systemPrompt: chatAssistantStore.currentAssistant?.system_prompt,
    temperature: chatStore.conversationSettings.temperature,
    maxTokens: chatStore.conversationSettings.maxTokens,
    contextLength: chatStore.conversationSettings.contextLength,
  })

  if (chatSessionStore.streamError) {
    message.error(chatSessionStore.streamError)
  }
}

function handleSendPrompt(prompt: string) {
  handleSend(prompt, { agentMode: chatStore.agentMode, model: chatSessionStore.selectedModelId, plugins: [] })
}

function handleUploadFile(_file: File) {
  message.info('文件上传功能开发中')
}

function handleToggleWebSearch() {
  message.info('联网搜索功能开发中')
}

function handleTriggerSandbox() {
  message.info('代码执行请在生成代码后点击代码块“运行”按钮')
}

function handleNavigate(path: string) {
  router.push(path).catch(() => {
    /* 忽略重复导航 */
  })
}

function handleFeedback(id: string, type: 'like' | 'dislike') {
  message.success(type === 'like' ? '感谢反馈' : '会继续改进')
  const sessionId = chatSessionStore.currentSessionId
  if (!sessionId || id.startsWith('temp_')) return
  chatApi.submitMessageFeedback(sessionId, id, type).catch(() => {
    /* 反馈提交失败不打断交互 */
  })
}

function handleCopy(_mode: CopyMode) {
  message.success('已复制')
}

async function handleRegenerate(id: string) {
  if (chatSessionStore.isStreaming) {
    message.warning('请等待当前回复完成')
    return
  }
  message.info('重新生成中...')
  await chatSessionStore.regenerateMessage(id)
}

function handleRetryWithModel(_id: string) {
  message.info('换模型重试功能开发中')
}

function handleTranslate(_id: string) {
  message.info('翻译功能开发中')
}

function handleDeleteMessage(id: string) {
  chatSessionStore.removeDisplayMessage(id)
}

function handleEditMessage(id: string) {
  const target = chatSessionStore.messages.find((item) => item.message_id === id)
  if (!target || target.role !== 'user') return
  inputMessage.value = target.content
  message.info('已填入输入框，修改后发送即可')
}

// ===== 生命周期 =====
onMounted(async () => {
  await Promise.all([
    chatSessionStore.fetchModels(),
    chatSessionStore.fetchSessions(),
    chatAssistantStore.fetchAssistants(),
  ])
  apiClient
    .get<{ configured: boolean }>('/ai/status')
    .then((res) => {
      aiConfigured.value = res.data.configured
    })
    .catch(() => {
      aiConfigured.value = false
    })
})
</script>

<template>
  <div class="kimi-layout" :data-theme="themeStore.theme">
    <KimiSidebar
      :sessions="sessions"
      :current-session-id="currentSessionId"
      :user-info="userInfo"
      :collapsed="chatStore.sidebarCollapsed"
      @new-session="newSession"
      @select-session="selectSession"
      @delete-session="deleteSession"
      @toggle-collapse="chatStore.sidebarCollapsed = !chatStore.sidebarCollapsed"
      @navigate="handleNavigate"
    />

    <main class="kimi-main">
      <n-alert
        v-if="showConfigWarning"
        type="warning"
        :show-icon="true"
        class="config-alert"
      >
        AI 服务未配置：请在后端 .env 中设置 KIMI_API_KEY / OPENAI_API_KEY，或由管理员在"系统设置 → AI 模型配置"中添加 Provider。
      </n-alert>

      <div class="main-content-area">
        <KimiEmptyState
          v-if="isEmpty"
          logo-text="OMIC HUB"
          :quick-prompts="chatStore.quickPrompts"
          @send-prompt="handleSendPrompt"
          @upload-file="handleUploadFile"
        />

        <template v-else>
          <ModelNavBar />

          <KimiMessageList
            :messages="messages"
            :is-typing="chatSessionStore.isStreaming"
            :streaming-content="streamingContent"
            :streaming-thought="streamingReasoning"
            :model-name="currentModelName"
            :session-id="currentSessionId"
            @feedback="handleFeedback"
            @copy="handleCopy"
            @regenerate="handleRegenerate"
            @retry-with-model="handleRetryWithModel"
            @translate="handleTranslate"
            @delete="handleDeleteMessage"
            @edit="handleEditMessage"
          />

          <n-alert
            v-if="showStreamError"
            type="error"
            :show-icon="true"
            closable
            class="conn-alert"
            @close="chatSessionStore.streamError = ''"
          >
            {{ chatSessionStore.streamError }}
          </n-alert>
        </template>
      </div>

      <div class="input-area-wrapper">
        <KimiChatInput
          v-model="inputMessage"
          :is-streaming="chatSessionStore.isStreaming"
          @send="(content) => handleSend(content, { agentMode: chatStore.agentMode, model: chatSessionStore.selectedModelId, plugins: [] })"
          @stop="chatSessionStore.stopStreaming"
          @upload-file="handleUploadFile"
          @toggle-web-search="handleToggleWebSearch"
          @trigger-sandbox="handleTriggerSandbox"
        />
      </div>
    </main>
  </div>
</template>

<style scoped lang="scss">
.kimi-layout {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  background: var(--chat-bg);
  color: var(--chat-text-primary);
  overflow: hidden;
}

.kimi-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.config-alert {
  border-radius: 0;
  flex-shrink: 0;
}

.conn-alert {
  border-radius: 0;
  flex-shrink: 0;
}

.main-content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.session-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--chat-border);
}

.input-area-wrapper {
  flex-shrink: 0;
  padding: 16px 24px;
  border-top: 1px solid var(--chat-border);
  background: var(--chat-bg);
}
</style>
