import { defineStore } from 'pinia'
import { ref } from 'vue'
import { agentTeamsApi, type AgentTeamsCase } from '@/api/agentTeams'

export const useAgentTeamsStore = defineStore('agentTeams', () => {
  const cases = ref<Record<string, AgentTeamsCase>>({})

  async function refreshCase(caseId: string): Promise<AgentTeamsCase> {
    const value = await agentTeamsApi.getCase(caseId)
    cases.value = { ...cases.value, [caseId]: value }
    return value
  }

  async function submitCase(caseId: string, payload: { task_name: string }) {
    return agentTeamsApi.submitCase(caseId, payload)
  }

  async function retryCase(caseId: string) {
    return agentTeamsApi.retryCase(caseId)
  }

  async function rejectCase(caseId: string, payload: { reason: string }): Promise<AgentTeamsCase> {
    const value = await agentTeamsApi.rejectCase(caseId, payload)
    cases.value = { ...cases.value, [caseId]: value }
    return value
  }

  async function cancelCase(caseId: string, payload: { reason: string }): Promise<AgentTeamsCase> {
    const value = await agentTeamsApi.cancelCase(caseId, payload)
    cases.value = { ...cases.value, [caseId]: value }
    return value
  }

  async function revisePlan(caseId: string, payload: { expected_plan_hash: string; parameters: Record<string, unknown>; reason: string }) {
    return agentTeamsApi.revisePlan(caseId, payload)
  }

  return { cases, refreshCase, submitCase, retryCase, rejectCase, cancelCase, revisePlan }
})
