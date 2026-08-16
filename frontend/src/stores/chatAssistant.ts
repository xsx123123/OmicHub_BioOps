/**
 * 聊天助手 Store — Cherry Studio 架构
 *
 * 管理内置助手列表（RNA-seq 分析师、单细胞分析师等）。
 *
 * @deprecated 该 Store 仅服务于旧版 Model-first 布局（KimiLayout.vue）。
 * 当前 `/ai` 路由主推 Agent-first 模式，助手概念已下沉到后端的 Agent 配置。
 * 未来若彻底放弃模型优先模式，可连同 chatSession 一起移除。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import type { ChatAssistantDTO } from '@/types/chat'

export const useChatAssistantStore = defineStore('chatAssistant', () => {
  // ========== State ==========
  const assistants = ref<ChatAssistantDTO[]>([])
  const currentAssistantId = ref<string>('general')
  const loading = ref(false)

  // ========== Getters ==========
  const currentAssistant = computed(
    () => assistants.value.find((a) => a.assistant_id === currentAssistantId.value) || null,
  )

  const groupedAssistants = computed(() => {
    const groups: Record<string, ChatAssistantDTO[]> = {}
    for (const a of assistants.value) {
      if (!groups[a.category]) groups[a.category] = []
      groups[a.category].push(a)
    }
    return groups
  })

  const categoryLabels: Record<string, string> = {
    general: '通用',
    analysis: '分析',
    code: '编程',
    visualization: '可视化',
  }

  // ========== Actions ==========
  async function fetchAssistants() {
    loading.value = true
    try {
      const res = await apiClient.get<ChatAssistantDTO[]>('/chat/assistants')
      assistants.value = res.data
      // 如果没有选中的助手，默认选 general
      if (!currentAssistantId.value && assistants.value.length > 0) {
        const general = assistants.value.find((a) => a.assistant_id === 'general')
        currentAssistantId.value = general?.assistant_id || assistants.value[0].assistant_id
      }
    } finally {
      loading.value = false
    }
  }

  function selectAssistant(assistantId: string) {
    currentAssistantId.value = assistantId
  }

  async function createAssistant(data: {
    assistant_id: string
    name: string
    description: string
    system_prompt: string
    icon?: string
    color?: string
    category?: string
    default_temperature?: number
    default_max_tokens?: number
  }): Promise<ChatAssistantDTO | null> {
    try {
      const res = await apiClient.post<ChatAssistantDTO>('/chat/assistants', data)
      assistants.value.push(res.data)
      return res.data
    } catch (e) {
      console.error('创建助手失败:', e)
      return null
    }
  }

  return {
    // State
    assistants,
    currentAssistantId,
    loading,
    categoryLabels,
    // Getters
    currentAssistant,
    groupedAssistants,
    // Actions
    fetchAssistants,
    selectAssistant,
    createAssistant,
  }
})
