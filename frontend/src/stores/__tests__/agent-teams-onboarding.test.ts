import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentTeamsOnboardingStore } from '@/stores/agentTeamsOnboarding'

describe('agentTeamsOnboarding', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts with the opening question and disappears after the final answer', () => {
    const store = useAgentTeamsOnboardingStore()
    store.begin()

    expect(store.phase).toBe('asking')
    expect(store.currentStep?.key).toBe('name')
    expect(store.currentStep?.question(store.managerName)).toContain('先认识一下')

    store.answerCurrent('Manager')
    store.answerCurrent('极简高效')
    store.answerCurrent('自主模式')
    store.answerCurrent('中文')

    expect(store.phase).toBe('done')
    expect(store.currentStep).toBeNull()
    expect('closingMessage' in store).toBe(false)
  })

  it('dismisses without leaving a persistent summary message', () => {
    const store = useAgentTeamsOnboardingStore()
    store.begin()
    store.dismiss()

    expect(store.phase).toBe('done')
    expect(store.currentStep).toBeNull()
  })
})
