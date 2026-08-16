import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

export type AgentTeamsCommunicationStyle = 'professional' | 'friendly' | 'concise'
export type AgentTeamsAutonomy = 'cautious' | 'autonomous'
export type AgentTeamsLanguage = 'zh-CN' | 'en-US'

export interface AgentTeamsPreferences {
  managerName: string
  communicationStyle: AgentTeamsCommunicationStyle
  autonomy: AgentTeamsAutonomy
  language: AgentTeamsLanguage
  showOnboarding: boolean
  autoSplitNewTasks: boolean
  expandTechnicalEvents: boolean
}

export const DEFAULT_AGENT_TEAMS_PREFERENCES: AgentTeamsPreferences = {
  managerName: 'Manager',
  communicationStyle: 'professional',
  autonomy: 'autonomous',
  language: 'zh-CN',
  showOnboarding: true,
  autoSplitNewTasks: true,
  expandTechnicalEvents: false,
}

function normalizePreferences(value: unknown): AgentTeamsPreferences {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const managerName = typeof source.managerName === 'string' && source.managerName.trim()
    ? source.managerName.trim().slice(0, 24)
    : DEFAULT_AGENT_TEAMS_PREFERENCES.managerName
  return {
    managerName,
    communicationStyle: ['professional', 'friendly', 'concise'].includes(String(source.communicationStyle))
      ? source.communicationStyle as AgentTeamsCommunicationStyle
      : DEFAULT_AGENT_TEAMS_PREFERENCES.communicationStyle,
    autonomy: ['cautious', 'autonomous'].includes(String(source.autonomy))
      ? source.autonomy as AgentTeamsAutonomy
      : DEFAULT_AGENT_TEAMS_PREFERENCES.autonomy,
    language: ['zh-CN', 'en-US'].includes(String(source.language))
      ? source.language as AgentTeamsLanguage
      : DEFAULT_AGENT_TEAMS_PREFERENCES.language,
    showOnboarding: typeof source.showOnboarding === 'boolean'
      ? source.showOnboarding
      : DEFAULT_AGENT_TEAMS_PREFERENCES.showOnboarding,
    autoSplitNewTasks: typeof source.autoSplitNewTasks === 'boolean'
      ? source.autoSplitNewTasks
      : DEFAULT_AGENT_TEAMS_PREFERENCES.autoSplitNewTasks,
    expandTechnicalEvents: typeof source.expandTechnicalEvents === 'boolean'
      ? source.expandTechnicalEvents
      : DEFAULT_AGENT_TEAMS_PREFERENCES.expandTechnicalEvents,
  }
}

export const useAgentTeamsPreferencesStore = defineStore('agentTeamsPreferences', () => {
  const authStore = useAuthStore()
  const settings = ref<AgentTeamsPreferences>({ ...DEFAULT_AGENT_TEAMS_PREFERENCES })
  const saving = ref(false)
  const loaded = ref(false)

  const managerLabel = computed(() => settings.value.managerName || 'Manager')

  function hydrateFromUser() {
    const root = authStore.user?.preferences
    const saved = root && typeof root === 'object' ? (root as Record<string, unknown>).agentteams : undefined
    settings.value = normalizePreferences(saved)
    loaded.value = true
  }

  async function save(next: AgentTeamsPreferences = settings.value) {
    if (!authStore.user) throw new Error('用户信息尚未加载')
    const normalized = normalizePreferences(next)
    saving.value = true
    try {
      await apiClient.put(`/users/${authStore.user.id}`, {
        preferences: {
          ...(authStore.user.preferences || {}),
          agentteams: normalized,
        },
      })
      await authStore.fetchUser()
      hydrateFromUser()
    } finally {
      saving.value = false
    }
  }

  function resetLocal() {
    settings.value = { ...DEFAULT_AGENT_TEAMS_PREFERENCES }
  }

  function applyOnboardingAnswer(key: string, value: string) {
    if (key === 'name') settings.value.managerName = value
    if (key === 'style') {
      settings.value.communicationStyle = value === '亲切友好' ? 'friendly' : value === '极简高效' ? 'concise' : 'professional'
    }
    if (key === 'autonomy') settings.value.autonomy = value.startsWith('谨慎') ? 'cautious' : 'autonomous'
    if (key === 'language') settings.value.language = value === 'English' ? 'en-US' : 'zh-CN'
  }

  return { settings, saving, loaded, managerLabel, hydrateFromUser, save, resetLocal, applyOnboardingAnswer }
})
