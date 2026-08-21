// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({ put: vi.fn() }))
vi.mock('@/api/client', () => ({ default: apiMocks }))

import { useAuthStore } from '@/stores/auth'
import {
  DEFAULT_AGENT_TEAMS_PREFERENCES,
  useAgentTeamsPreferencesStore,
} from '@/stores/agentTeamsPreferences'

describe('agentTeamsPreferences', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('hydrates saved global collaboration preferences', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'user-1', username: 'demo', email: 'demo@example.com', role: 'user', status: 'active',
      created_at: '', updated_at: '',
      preferences: { agentteams: { managerName: '小 O', communicationStyle: 'concise', showOnboarding: false } },
    }
    const store = useAgentTeamsPreferencesStore()
    store.hydrateFromUser()

    expect(store.settings.managerName).toBe('小 O')
    expect(store.settings.communicationStyle).toBe('concise')
    expect(store.settings.showOnboarding).toBe(false)
    expect(store.settings.autoSplitNewTasks).toBe(DEFAULT_AGENT_TEAMS_PREFERENCES.autoSplitNewTasks)
  })

  it('persists settings under the agentteams preference namespace', async () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'user-1', username: 'demo', email: 'demo@example.com', role: 'user', status: 'active',
      created_at: '', updated_at: '', preferences: { profile: { theme: 'dark' } },
    }
    vi.spyOn(auth, 'fetchUser').mockResolvedValue()
    apiMocks.put.mockResolvedValue({ data: {} })
    const store = useAgentTeamsPreferencesStore()

    await store.save({
      ...DEFAULT_AGENT_TEAMS_PREFERENCES,
      managerName: '管家',
      communicationStyle: 'friendly',
    })

    expect(apiMocks.put).toHaveBeenCalledWith('/users/user-1', {
      preferences: {
        profile: { theme: 'dark' },
        agentteams: expect.objectContaining({ managerName: '管家', communicationStyle: 'friendly' }),
      },
    })
  })

  it('defaults managerName to null so the backend display_name passes through', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'user-1', username: 'demo', email: 'demo@example.com', role: 'user', status: 'active',
      created_at: '', updated_at: '', preferences: {},
    }
    const store = useAgentTeamsPreferencesStore()
    store.hydrateFromUser()

    expect(store.settings.managerName).toBeNull()
    store.setServerManagerName('生物信息部门经理')
    // 无用户覆盖 → 透传后端值；后缀与称呼同源，相同则不重复展示。
    expect(store.managerLabel).toBe('生物信息部门经理')
    expect(store.managerRoleSuffix).toBe('')
  })

  it('treats the legacy default name as no override during migration', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'user-1', username: 'demo', email: 'demo@example.com', role: 'user', status: 'active',
      created_at: '', updated_at: '',
      preferences: { agentteams: { managerName: 'Manager' } },
    }
    const store = useAgentTeamsPreferencesStore()
    store.hydrateFromUser()
    store.setServerManagerName('生物信息部门经理')

    expect(store.settings.managerName).toBeNull()
    expect(store.managerLabel).toBe('生物信息部门经理')
  })

  it('user override wins over the backend display_name and keeps the role suffix', () => {
    const auth = useAuthStore()
    auth.user = {
      id: 'user-1', username: 'demo', email: 'demo@example.com', role: 'user', status: 'active',
      created_at: '', updated_at: '',
      preferences: { agentteams: { managerName: '小 O' } },
    }
    const store = useAgentTeamsPreferencesStore()
    store.hydrateFromUser()
    store.setServerManagerName('生物信息部门经理')

    expect(store.managerLabel).toBe('小 O')
    expect(store.managerRoleSuffix).toBe('生物信息部门经理')
  })

  it('falls back to the local default when neither override nor backend value exists', () => {
    const store = useAgentTeamsPreferencesStore()
    expect(store.managerLabel).toBe('Manager')
    expect(store.managerRoleSuffix).toBe('')
  })
})
