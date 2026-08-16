import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import type { Conversation, ConversationDetail, AIMessage } from '@/types'

export const useAIStore = defineStore('ai', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversation = ref<ConversationDetail | null>(null)
  const loading = ref(false)
  const streaming = ref(false)

  const messages = computed<AIMessage[]>(() => currentConversation.value?.messages ?? [])

  async function fetchConversations() {
    loading.value = true
    try {
      const res = await apiClient.get<Conversation[]>('/ai/conversations')
      conversations.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function createConversation(title = '新对话'): Promise<Conversation> {
    const res = await apiClient.post<Conversation>('/ai/conversations', { title })
    conversations.value.unshift(res.data)
    // 创建后立即切换到新会话，避免 UI 仍停留在旧会话
    currentConversation.value = { ...res.data, messages: [] }
    return res.data
  }

  async function selectConversation(id: string) {
    const res = await apiClient.get<ConversationDetail>(`/ai/conversations/${id}`)
    currentConversation.value = res.data
    return res.data
  }

  function appendMessage(msg: AIMessage) {
    if (!currentConversation.value) return
    currentConversation.value.messages.push(msg)
    currentConversation.value.message_count = currentConversation.value.messages.length
  }

  /** 流式更新最后一条助手消息内容（打字机效果） */
  function appendAssistantToken(token: string) {
    if (!currentConversation.value) return
    const msgs = currentConversation.value.messages
    const last = msgs[msgs.length - 1]
    if (last && last.role === 'assistant' && !last.tool_call_id) {
      last.content += token
    } else {
      msgs.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: token,
        timestamp: new Date().toISOString(),
      })
    }
  }

  function startStreamingAssistant() {
    // 占位一条空助手消息，供 token 累加
    if (!currentConversation.value) return
    currentConversation.value.messages.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    })
    streaming.value = true
  }

  function finishStreaming() {
    streaming.value = false
  }

  async function deleteConversation(id: string) {
    await apiClient.delete(`/ai/conversations/${id}`)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversation.value?.id === id) currentConversation.value = null
  }

  return {
    conversations,
    currentConversation,
    messages,
    loading,
    streaming,
    fetchConversations,
    createConversation,
    selectConversation,
    appendMessage,
    appendAssistantToken,
    startStreamingAssistant,
    finishStreaming,
    deleteConversation,
  }
})
