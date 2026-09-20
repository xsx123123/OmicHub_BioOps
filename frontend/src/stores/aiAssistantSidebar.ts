/**
 * 全局 AI 助手侧边栏 Store
 *
 * 悬浮于全站（AI 助手 / AI 工作台 / 协作室页面除外）的快捷问答侧边栏，
 * 复用 /api/v1/chat/stream，走平台通用助手 Agent 链路（agent_id=agent-general，
 * 与 /ai 页同一 Agent 调度中枢），模型可由用户在输入区上方切换。
 * 会话与消息持久化到 localStorage，刷新页面后上下文保留。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'
import { useChatStream } from '@/composables/useChatStream'
import type { ChatModelOption } from '@/types/chat'

export interface SidebarMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  status: 'complete' | 'streaming' | 'error'
  error?: string
  created_at: string
}

const STORAGE_KEY = 'ai_assistant_sidebar_state'
/** 平台通用助手（data/ai/general.yaml），侧边栏与其共用同一 Agent 链路 */
const SIDEBAR_AGENT_ID = 'agent-general'
/** 持久化与发送上下文各自保留的消息条数上限 */
const MAX_PERSISTED_MESSAGES = 40
const CONTEXT_LENGTH = 20

interface PersistedState {
  sessionId: string
  modelId?: string
  messages: SidebarMessage[]
}

function loadPersisted(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as PersistedState
    if (!parsed || typeof parsed.sessionId !== 'string' || !Array.isArray(parsed.messages)) {
      return null
    }
    if (typeof parsed.modelId !== 'string') delete parsed.modelId
    // 刷新恢复时把未完成的流式消息收口为 complete，避免出现「永远转圈」的脏状态
    for (const m of parsed.messages) {
      if (m.status === 'streaming') m.status = 'complete'
    }
    return parsed
  } catch {
    return null
  }
}

export const useAiAssistantSidebarStore = defineStore('aiAssistantSidebar', () => {
  // ========== State ==========
  const open = ref(false)
  const messages = ref<SidebarMessage[]>([])
  const sessionId = ref('')
  const models = ref<ChatModelOption[]>([])
  const modelId = ref('')
  const modelsLoaded = ref(false)
  const loadError = ref('')

  const persisted = loadPersisted()
  if (persisted) {
    messages.value = persisted.messages.slice(-MAX_PERSISTED_MESSAGES)
    sessionId.value = persisted.sessionId
    if (persisted.modelId) modelId.value = persisted.modelId
  }

  const { streamChat, abortStream, isStreaming } = useChatStream()

  // ========== Actions ==========

  function persist() {
    try {
      const snapshot: PersistedState = {
        sessionId: sessionId.value,
        modelId: modelId.value,
        messages: messages.value
          .filter((m) => m.status !== 'streaming')
          .slice(-MAX_PERSISTED_MESSAGES),
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
    } catch {
      // localStorage 不可用时静默失败
    }
  }

  /** 加载可用模型列表（幂等，只拉一次） */
  async function ensureModels() {
    if (modelsLoaded.value) return
    try {
      const res = await apiClient.get<ChatModelOption[]>('/chat/models')
      models.value = res.data
      if (!modelId.value) {
        const defaultModel = models.value.find((m) => m.is_default) || models.value[0]
        modelId.value = defaultModel?.id || ''
      }
      loadError.value = models.value.length ? '' : '暂无可用的 AI 模型，请联系管理员配置'
    } catch (e) {
      loadError.value = '加载模型列表失败，请稍后重试'
      console.error('侧边栏 AI 助手加载模型失败:', e)
    } finally {
      modelsLoaded.value = true
    }
  }

  async function sendMessage(content: string, pageContext?: string) {
    const text = content.trim()
    if (!text || isStreaming.value) return
    await ensureModels()
    if (!modelId.value) return

    const userMsg: SidebarMessage = {
      id: `sb_u_${Date.now()}`,
      role: 'user',
      content: text,
      reasoning: '',
      status: 'complete',
      created_at: new Date().toISOString(),
    }
    const aiMsg: SidebarMessage = {
      id: `sb_a_${Date.now()}`,
      role: 'assistant',
      content: '',
      reasoning: '',
      status: 'streaming',
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMsg, aiMsg)

    // 后端不从 DB 重建上下文，历史由客户端全量携带；
    // 用对象引用排除 aiMsg 占位，保证最新用户输入必在上下文末尾。
    const apiMessages = messages.value
      .filter((m) => m !== aiMsg && m.status !== 'error' && m.content.length > 0)
      .slice(-CONTEXT_LENGTH)
      .map((m) => ({ role: m.role, content: m.content }))

    await streamChat(
      {
        messages: apiMessages,
        modelId: modelId.value,
        agentId: SIDEBAR_AGENT_ID,
        pageContext,
        sessionId: sessionId.value || undefined,
      },
      {
        onText: (chunk, isReasoning) => {
          if (isReasoning) {
            aiMsg.reasoning += chunk
          } else {
            aiMsg.content += chunk
          }
        },
        onSessionCreated: (sid, messageId) => {
          if (!sessionId.value) sessionId.value = sid
          aiMsg.id = messageId
        },
        onError: (error) => {
          aiMsg.status = 'error'
          aiMsg.error = error
          persist()
        },
        onDone: () => {
          aiMsg.status = 'complete'
          persist()
        },
      },
    )
  }

  /** 停止当前流式输出 */
  function stopStreaming() {
    abortStream()
    const last = messages.value[messages.value.length - 1]
    if (last && last.status === 'streaming') {
      last.status = 'complete'
      persist()
    }
  }

  /** 开启新对话：清空本地上下文（历史会话仍保留在会话列表中） */
  function newChat() {
    abortStream()
    messages.value = []
    sessionId.value = ''
    persist()
  }

  return {
    open,
    messages,
    sessionId,
    models,
    modelId,
    modelsLoaded,
    loadError,
    isStreaming,
    ensureModels,
    sendMessage,
    stopStreaming,
    newChat,
  }
})
