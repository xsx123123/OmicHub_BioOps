import { defineStore } from 'pinia'
import { ref } from 'vue'
import apiClient from '@/api/client'
import type { SandboxSession } from '@/types'

export const useSandboxStore = defineStore('sandbox', () => {
  const sessions = ref<SandboxSession[]>([])
  const currentSession = ref<SandboxSession | null>(null)
  const loading = ref(false)

  async function fetchSessions() {
    loading.value = true
    try {
      const res = await apiClient.get<SandboxSession[]>('/sandbox/sessions')
      sessions.value = res.data
    } finally {
      loading.value = false
    }
  }

  async function createSession(language = 'python'): Promise<SandboxSession> {
    const res = await apiClient.post<SandboxSession>('/sandbox/sessions', { language })
    sessions.value.unshift(res.data)
    currentSession.value = res.data
    return res.data
  }

  async function deleteSession(id: string) {
    await apiClient.delete(`/sandbox/sessions/${id}`)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentSession.value?.id === id) currentSession.value = null
  }

  return {
    sessions,
    currentSession,
    loading,
    fetchSessions,
    createSession,
    deleteSession,
  }
})
