/**
 * 全局 AI 助手侧边栏 Store
 *
 * 悬浮于全站（AI 助手 / AI 工作台 / 协作室页面除外）的快捷问答侧边栏，
 * 复用 /api/v1/chat/stream，但使用独立的平台服务助手提示词，不进入 /ai 页的
 * Agent 路由、专家协作或工具执行链路；模型可由用户在输入区上方切换。
 * 会话与消息持久化到 localStorage，用于当前页面会话的恢复与发送过程中的状态保存；
 * 页面路由切换时由侧栏组件主动清空上下文。
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

// 侧栏本来就使用独立于 AI 工作区的本地命名空间，保持 key 兼容已有侧栏历史。
const STORAGE_KEY = 'ai_assistant_sidebar_state'
const PLATFORM_ASSISTANT_PROMPT = `你是 OmicHub 平台服务助手，负责帮助用户理解和使用当前平台。

你的职责是：
- 介绍平台页面、功能入口、常见操作和术语；
- 根据用户当前页面上下文，给出清晰、可执行的导航或操作建议；
- 用户询问具体生信分析时，说明平台可以从哪里进入相关分析，并建议用户前往 AI 助手或对应专家智能体，不直接承担分析任务；
- 不调用工具、不执行文件或数据分析、不虚构平台不存在的功能；不确定时明确说明并建议联系管理员。

回答简洁、友好，优先给出下一步操作。`
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
        systemPrompt: PLATFORM_ASSISTANT_PROMPT,
        pageContext,
        sessionId: sessionId.value || undefined,
        autoApprove: false,
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
