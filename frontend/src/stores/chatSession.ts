/**
 * 聊天会话 Store — Cherry Studio 架构
 *
 * 管理会话列表、消息历史、SSE 流式聊天编排。
 * 替代旧 chat.ts（基于 localStorage 的 WebSocket 系统）。
 *
 * @deprecated 该 Store 仅服务于旧版 Model-first 布局（KimiLayout.vue）。
 * 当前 `/ai` 路由主推 Agent-first 模式，由 agentHub Store 负责会话与 SSE 编排。
 * 未来若彻底放弃模型优先模式，可连同 chatAssistant 一起移除。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import { useChatStream } from '@/composables/useChatStream'
import type { ChatSessionDTO, ChatMessageDTO, ChatModelOption, DisplayMessage } from '@/types/chat'
import { sortPersistedChatMessages } from '@/utils/chatMessageOrder'
import { filterUserVisibleMessages } from '@/utils/userVisibleMessage'

export const useChatSessionStore = defineStore('chatSession', () => {
  // ========== State ==========
  const sessions = ref<ChatSessionDTO[]>([])
  const currentSessionId = ref<string>('')
  const messages = ref<DisplayMessage[]>([])
  const models = ref<ChatModelOption[]>([])
  const selectedModelId = ref<string>('')
  const loadingSessions = ref(false)
  const loadingMessages = ref(false)

  // 流式状态
  const streamingContent = ref('')
  const streamingReasoning = ref('')
  const isStreaming = ref(false)
  const streamError = ref('')

  const { streamChat, abortStream, isStreaming: streamActive } = useChatStream()

  // ========== Getters ==========
  const currentSession = computed(() =>
    sessions.value.find((s) => s.session_id === currentSessionId.value),
  )

  const selectedModel = computed(() =>
    models.value.find((m) => m.id === selectedModelId.value),
  )

  // ========== Actions ==========

  /** 加载可用模型列表 */
  async function fetchModels() {
    try {
      const res = await apiClient.get<ChatModelOption[]>('/chat/models')
      models.value = res.data
      if (!selectedModelId.value) {
        const defaultModel = models.value.find((m) => m.is_default) || models.value[0]
        if (defaultModel) selectedModelId.value = defaultModel.id
      }
    } catch (e) {
      console.error('加载模型列表失败:', e)
    }
  }

  /** 加载会话列表 */
  async function fetchSessions() {
    loadingSessions.value = true
    try {
      const res = await apiClient.get<ChatSessionDTO[]>('/chat/sessions')
      sessions.value = res.data
    } finally {
      loadingSessions.value = false
    }
  }

  /** 选择会话并加载消息 */
  async function selectSession(sessionId: string) {
    currentSessionId.value = sessionId
    loadingMessages.value = true
    try {
      const res = await apiClient.get<ChatMessageDTO[]>(`/chat/sessions/${sessionId}/messages`)
      messages.value = sortPersistedChatMessages(filterUserVisibleMessages(res.data)).map((m) => ({
        message_id: m.message_id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        reasoning: '',
        status: m.status as 'complete' | 'streaming' | 'error',
        error: typeof m.metadata_json?.error === 'string' ? m.metadata_json.error : undefined,
        created_at: m.created_at,
      }))
    } finally {
      loadingMessages.value = false
    }
  }

  /** 创建新会话（projectId 为后端必填的项目边界，调用方需先让用户选择项目） */
  async function createSession(modelId: string, assistantId?: string, projectId?: string): Promise<string | null> {
    try {
      const res = await apiClient.post<ChatSessionDTO>('/chat/sessions', {
        model_id: modelId,
        assistant_id: assistantId,
        title: '新对话',
        project_id: projectId || undefined,
      })
      sessions.value.unshift(res.data)
      currentSessionId.value = res.data.session_id
      messages.value = []
      return res.data.session_id
    } catch (e) {
      console.error('创建会话失败:', e)
      return null
    }
  }

  /** 更新会话标题 */
  async function updateSessionTitle(sessionId: string, title: string) {
    try {
      await apiClient.put(`/chat/sessions/${sessionId}/title`, null, {
        params: { title },
      })
      const session = sessions.value.find((s) => s.session_id === sessionId)
      if (session) session.title = title
    } catch (e) {
      console.error('更新标题失败:', e)
    }
  }

  /** 删除会话 */
  async function deleteSession(sessionId: string) {
    try {
      await apiClient.delete(`/chat/sessions/${sessionId}`)
      sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = ''
        messages.value = []
      }
    } catch (e) {
      console.error('删除会话失败:', e)
    }
  }

  /** 发送消息（SSE 流式） */
  async function sendMessage(
    content: string,
    options?: {
      assistantId?: string
      systemPrompt?: string
      temperature?: number
      maxTokens?: number
      contextLength?: number
    },
  ) {
    if (!content.trim() || !selectedModelId.value) return
    if (isStreaming.value) return

    streamError.value = ''
    streamingContent.value = ''
    streamingReasoning.value = ''

    // 添加用户消息到显示列表
    const userMsg: DisplayMessage = {
      message_id: `temp_${Date.now()}`,
      role: 'user',
      content: content.trim(),
      reasoning: '',
      status: 'complete',
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMsg)

    // 添加 AI 占位消息
    const aiMsg: DisplayMessage = {
      message_id: `temp_ai_${Date.now()}`,
      role: 'assistant',
      content: '',
      reasoning: '',
      status: 'streaming',
      created_at: new Date().toISOString(),
    }
    messages.value.push(aiMsg)

    isStreaming.value = true

    // 构建发送给后端的消息列表（含历史上下文，排除当前 AI 占位 aiMsg）
    // 注意：不能用“先 push 再 pop()”的方式剔除 aiMsg——空内容占位会被
    // content.length 过滤掉，pop() 反而误删了刚加入的最新用户消息。
    // 这里用对象引用直接排除 aiMsg，确保本次用户输入必在上下文末尾。
    const ctxLen = options?.contextLength ?? 20
    const apiMessages = messages.value
      .filter((m) => m !== aiMsg && m.status !== 'error' && m.content.length > 0)
      .slice(-ctxLen)
      .map((m) => ({ role: m.role, content: m.content }))

    await streamChat(
      {
        messages: apiMessages,
        modelId: selectedModelId.value,
        sessionId: currentSessionId.value || undefined,
        assistantId: options?.assistantId,
        // [极简测试] 临时禁用前端传入的系统提示词
        // systemPrompt: options?.systemPrompt,
        temperature: options?.temperature,
        maxTokens: options?.maxTokens,
      },
      {
        onText: (text, isReasoning) => {
          if (isReasoning) {
            streamingReasoning.value += text
            aiMsg.reasoning = streamingReasoning.value
          } else {
            streamingContent.value += text
            aiMsg.content = streamingContent.value
          }
        },
        onSessionCreated: (sessionId, messageId) => {
          if (!currentSessionId.value) {
            currentSessionId.value = sessionId
            aiMsg.message_id = messageId
            // 刷新会话列表
            fetchSessions()
          } else {
            aiMsg.message_id = messageId
          }
        },
        onError: (error) => {
          streamError.value = error
          aiMsg.status = 'error'
          aiMsg.content = streamingContent.value
          aiMsg.error = error
        },
        onDone: (_sessionId, _messageId) => {
          aiMsg.status = 'complete'
          // 自动生成标题（第一条消息后）
          const session = sessions.value.find((s) => s.session_id === currentSessionId.value)
          if (session && session.title === '新对话') {
            const autoTitle = content.trim().slice(0, 30) + (content.trim().length > 30 ? '...' : '')
            updateSessionTitle(currentSessionId.value, autoTitle)
          }
        },
      },
    )

    isStreaming.value = false
  }

  /** 停止流式输出 */
  function stopStreaming() {
    abortStream()
    isStreaming.value = false
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg && lastMsg.status === 'streaming') {
      lastMsg.status = 'complete'
    }
  }

  /** 删除单条显示消息（仅前端显示层，不删数据库） */
  function removeDisplayMessage(messageId: string) {
    messages.value = messages.value.filter((m) => m.message_id !== messageId)
  }

  /**
   * 重新生成指定 AI 回复：
   * 定位该 assistant 消息及其前一条 user 消息，一并移除后以原用户输入重发。
   * 仅对显示层操作；若该消息非最后一条，后续消息保留（上下文以新回复衔接）。
   */
  async function regenerateMessage(messageId: string) {
    if (isStreaming.value) return
    const idx = messages.value.findIndex((m) => m.message_id === messageId)
    if (idx < 0) return

    // 向前查找最近的 user 消息
    let userIdx = -1
    for (let i = idx - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userIdx = i
        break
      }
    }
    if (userIdx < 0) return

    const userContent = messages.value[userIdx].content
    // 移除 [userIdx, idx] 区间（旧 user + 旧 assistant）
    messages.value.splice(userIdx, idx - userIdx + 1)
    await sendMessage(userContent)
  }

  /** 清空当前会话消息（仅前端，不删数据库） */
  function clearDisplayMessages() {
    messages.value = []
  }

  return {
    // State
    sessions,
    currentSessionId,
    messages,
    models,
    selectedModelId,
    loadingSessions,
    loadingMessages,
    streamingContent,
    streamingReasoning,
    isStreaming,
    streamError,
    // Getters
    currentSession,
    selectedModel,
    // Actions
    fetchModels,
    fetchSessions,
    selectSession,
    createSession,
    updateSessionTitle,
    deleteSession,
    sendMessage,
    stopStreaming,
    clearDisplayMessages,
    removeDisplayMessage,
    regenerateMessage,
  }
})
