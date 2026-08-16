/**
 * UI / 设置 Store
 *
 * 目前承载：
 * - 旧版 Model-first 的 localStorage 会话、模型收藏、可用模型/插件列表
 * - 当前 Agent-first 模式仍使用的 deepThinking 开关
 * - 通用对话设置（temperature / maxTokens / contextLength）
 *
 * TODO: 在 Agent-first 架构稳定后，建议将 UI 状态（sidebarCollapsed、deepThinking、
 * conversationSettings、主题无关的界面偏好）剥离到独立的 uiSettingsStore；
 * 与模型优先相关的会话/模型/助手状态随旧布局一并移除，降低状态同步的认知负担。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { isToday, isYesterday, parseISO } from 'date-fns'
import apiClient from '@/api/client'
import type { ChatSession, ChatMessage, UserInfo, ModelOption, PluginOption, ConversationSettings } from '@/components/ai-chat/types'

const FAVORITE_MODELS_KEY = 'chat-favorite-models'
const CONVERSATION_SETTINGS_KEY = 'chat-conversation-settings'
const DEEP_THINKING_KEY = 'chat-deep-thinking'
const WEB_SEARCH_KEY = 'chat-web-search'

const DEFAULT_CONVERSATION_SETTINGS: ConversationSettings = {
  temperature: 0.7,
  maxTokens: 2048,
  contextLength: 20,
}

function loadBoolean(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === 'true'
  } catch {
    return fallback
  }
}

function loadConversationSettings(): ConversationSettings {
  try {
    const v = localStorage.getItem(CONVERSATION_SETTINGS_KEY)
    if (!v) return { ...DEFAULT_CONVERSATION_SETTINGS }
    return { ...DEFAULT_CONVERSATION_SETTINGS, ...JSON.parse(v) }
  } catch {
    return { ...DEFAULT_CONVERSATION_SETTINGS }
  }
}

function loadFavoriteModels(): string[] {
  try {
    const v = localStorage.getItem(FAVORITE_MODELS_KEY)
    return v ? (JSON.parse(v) as string[]) : []
  } catch {
    return []
  }
}

export const useChatStore = defineStore('chat', () => {
  // ========== State ==========
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string>('')
  const isTyping = ref(false)
  const streamingContent = ref('')
  const streamingThought = ref('')
  const sidebarCollapsed = ref(false)
  const agentMode = ref(false)
  const selectedModel = ref('kimi-k2')

  // 深度思考模式（前端状态，透传至 sendMessage，后端可暂忽略）
  const deepThinking = ref<boolean>(loadBoolean(DEEP_THINKING_KEY, false))

  // 联网搜索开关
  const enableWebSearch = ref<boolean>(loadBoolean(WEB_SEARCH_KEY, false))

  // 对话级设置（温度 / 最大输出 / 上下文长度）
  const conversationSettings = ref<ConversationSettings>(
    loadConversationSettings(),
  )

  // 收藏的模型 id 列表（localStorage 持久化）
  const favoriteModels = ref<string[]>(loadFavoriteModels())

  const currentUser = ref<UserInfo>({
    id: '',
    name: '',
    avatar: '',
    role: '',
    roleTag: '',
  })

  const availableModels = ref<ModelOption[]>([
    { id: 'kimi-k2', name: 'K2.6 快速', description: 'Kimi 最新模型', provider: 'kimi' },
    { id: 'qwen-plus', name: 'Qwen3 Plus', description: '通义千问模型', provider: 'aliyun' },
    { id: 'qwen-max', name: 'Qwen3 Max', description: '通义千问最强', provider: 'aliyun' },
    { id: 'deepseek-chat', name: 'DeepSeek-V3', description: '深度求索', provider: 'deepseek' },
    { id: 'gpt-4o', name: 'GPT-4o', description: 'OpenAI', provider: 'openai' },
  ])

  const availablePlugins = ref<PluginOption[]>([
    { id: 'pubmed', name: 'PubMed 搜索', description: '搜索生物医学文献', icon: '🔬' },
    { id: 'kegg', name: 'KEGG 通路', description: '查询通路信息', icon: '🧬' },
    { id: 'go', name: 'GO 富集', description: '基因功能富集分析', icon: '📊' },
    { id: 'code', name: '代码执行', description: '执行 Python/R 代码', icon: '💻' },
    { id: 'chart', name: '图表生成', description: '生成数据可视化图表', icon: '📈' },
  ])

  const quickPrompts = ref([
    { icon: '🔬', text: '帮我分析 RNA-seq 差异表达基因', category: 'analysis' },
    { icon: '📊', text: '绘制 UMAP 降维可视化图', category: 'visualization' },
    { icon: '🧬', text: '查询 GO 富集分析结果', category: 'analysis' },
    { icon: '📁', text: '列出我最近的分析任务', category: 'task' },
    { icon: '📎', text: '使用插件搜索 PubMed 文献', category: 'search' },
  ])

  // ========== Getters ==========
  const currentSession = computed<ChatSession | undefined>(() => {
    return sessions.value.find((s) => s.id === currentSessionId.value)
  })

  const todaySessions = computed(() => {
    return sessions.value.filter((s) => {
      try {
        return isToday(parseISO(s.updatedAt))
      } catch {
        return false
      }
    })
  })

  const yesterdaySessions = computed(() => {
    return sessions.value.filter((s) => {
      try {
        return isYesterday(parseISO(s.updatedAt))
      } catch {
        return false
      }
    })
  })

  const olderSessions = computed(() => {
    return sessions.value.filter((s) => {
      try {
        const d = parseISO(s.updatedAt)
        return !isToday(d) && !isYesterday(d)
      } catch {
        return false
      }
    })
  })

  const messageCount = computed(() => {
    return currentSession.value?.messages.length || 0
  })

  // ========== Actions ==========

  // 会话管理
  function createSession(title?: string): ChatSession {
    const session: ChatSession = {
      id: `session_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`,
      title: title || '新对话',
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      model: selectedModel.value,
    }
    sessions.value.unshift(session)
    currentSessionId.value = session.id
    saveToLocalStorage()
    return session
  }

  function selectSession(sessionId: string) {
    currentSessionId.value = sessionId
  }

  function deleteSession(sessionId: string) {
    const idx = sessions.value.findIndex((s) => s.id === sessionId)
    if (idx > -1) {
      sessions.value.splice(idx, 1)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = sessions.value[0]?.id || ''
      }
      saveToLocalStorage()
    }
  }

  function updateSessionTitle(sessionId: string, title: string) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      session.title = title
      session.updatedAt = new Date().toISOString()
      saveToLocalStorage()
    }
  }

  // 消息 CRUD
  function addMessage(sessionId: string, message: ChatMessage) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      session.messages.push(message)
      session.updatedAt = new Date().toISOString()

      // 自动更新标题（第一条用户消息后）
      if (session.messages.length === 1 && message.role === 'user') {
        const autoTitle = message.content.slice(0, 30) + (message.content.length > 30 ? '...' : '')
        session.title = autoTitle
      }

      saveToLocalStorage()
    }
  }

  function updateMessage(sessionId: string, messageId: string, updates: Partial<ChatMessage>) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      const message = session.messages.find((m) => m.id === messageId)
      if (message) {
        Object.assign(message, updates)
        saveToLocalStorage()
      }
    }
  }

  function deleteMessage(sessionId: string, messageId: string) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      const idx = session.messages.findIndex((m) => m.id === messageId)
      if (idx > -1) {
        session.messages.splice(idx, 1)
        saveToLocalStorage()
      }
    }
  }

  function clearMessages(sessionId: string) {
    const session = sessions.value.find((s) => s.id === sessionId)
    if (session) {
      session.messages = []
      session.updatedAt = new Date().toISOString()
      saveToLocalStorage()
    }
  }

  // 流式输出控制
  function startStreaming() {
    isTyping.value = true
    streamingContent.value = ''
    streamingThought.value = ''
  }

  function appendStreamContent(content: string) {
    streamingContent.value += content
  }

  function appendStreamThought(thought: string) {
    streamingThought.value += thought
  }

  function finishStreaming() {
    isTyping.value = false
    streamingContent.value = ''
    streamingThought.value = ''
  }

  // 设置
  function selectModel(modelId: string) {
    selectedModel.value = modelId
    if (currentSession.value) {
      currentSession.value.model = modelId
    }
  }

  // 深度思考
  function setDeepThinking(enabled: boolean) {
    deepThinking.value = enabled
    try {
      localStorage.setItem(DEEP_THINKING_KEY, String(enabled))
    } catch {
      /* 静默 */
    }
  }

  function toggleDeepThinking() {
    setDeepThinking(!deepThinking.value)
  }

  // 联网搜索
  function setWebSearch(enabled: boolean) {
    enableWebSearch.value = enabled
    try {
      localStorage.setItem(WEB_SEARCH_KEY, String(enabled))
    } catch {
      /* 静默 */
    }
  }

  function toggleWebSearch() {
    setWebSearch(!enableWebSearch.value)
  }

  // 对话级设置
  function updateConversationSettings(patch: Partial<ConversationSettings>) {
    conversationSettings.value = { ...conversationSettings.value, ...patch }
    try {
      localStorage.setItem(CONVERSATION_SETTINGS_KEY, JSON.stringify(conversationSettings.value))
    } catch {
      /* 静默 */
    }
  }

  function resetConversationSettings() {
    conversationSettings.value = { ...DEFAULT_CONVERSATION_SETTINGS }
    try {
      localStorage.setItem(CONVERSATION_SETTINGS_KEY, JSON.stringify(conversationSettings.value))
    } catch {
      /* 静默 */
    }
  }

  // 模型收藏
  function isFavorite(modelId: string) {
    return favoriteModels.value.includes(modelId)
  }

  function toggleFavorite(modelId: string) {
    const idx = favoriteModels.value.indexOf(modelId)
    if (idx > -1) {
      favoriteModels.value.splice(idx, 1)
    } else {
      favoriteModels.value.push(modelId)
    }
    try {
      localStorage.setItem(FAVORITE_MODELS_KEY, JSON.stringify(favoriteModels.value))
    } catch {
      /* 静默 */
    }
  }

  // 持久化
  function saveToLocalStorage() {
    try {
      localStorage.setItem('chat-sessions', JSON.stringify(sessions.value))
    } catch (e) {
      console.warn('Failed to save sessions:', e)
    }
  }

  function loadFromLocalStorage() {
    try {
      const saved = localStorage.getItem('chat-sessions')
      if (saved) {
        sessions.value = JSON.parse(saved)
      }
    } catch (e) {
      console.warn('Failed to load sessions:', e)
    }
  }

  // 初始化
  function initStore(user?: UserInfo) {
    if (user) currentUser.value = user
    loadFromLocalStorage()
    if (!sessions.value.length) {
      createSession()
    } else if (!currentSessionId.value) {
      currentSessionId.value = sessions.value[0].id
    }
    fetchPlugins()
  }

  async function fetchPlugins() {
    try {
      const res = await apiClient.get<Array<{ skill_id: string; name: string; description: string; icon: string }>>('/chat/skills')
      availablePlugins.value = res.data.map((s) => ({
        id: s.skill_id,
        name: s.name,
        description: s.description,
        icon: s.icon,
      }))
    } catch {
      /* 静默失败，保留默认 */
    }
  }

  return {
    // State
    sessions,
    currentSessionId,
    isTyping,
    streamingContent,
    streamingThought,
    sidebarCollapsed,
    agentMode,
    selectedModel,
    deepThinking,
    enableWebSearch,
    conversationSettings,
    favoriteModels,
    currentUser,
    availableModels,
    availablePlugins,
    quickPrompts,
    // Getters
    currentSession,
    todaySessions,
    yesterdaySessions,
    olderSessions,
    messageCount,
    // Actions
    createSession,
    selectSession,
    deleteSession,
    updateSessionTitle,
    addMessage,
    updateMessage,
    deleteMessage,
    clearMessages,
    startStreaming,
    appendStreamContent,
    appendStreamThought,
    finishStreaming,
    selectModel,
    setDeepThinking,
    toggleDeepThinking,
    setWebSearch,
    toggleWebSearch,
    updateConversationSettings,
    resetConversationSettings,
    isFavorite,
    toggleFavorite,
    initStore,
    fetchPlugins,
    saveToLocalStorage,
    loadFromLocalStorage,
  }
})
