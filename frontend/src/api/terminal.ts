import apiClient from '@/api/client'
import type {
  TerminalSession,
  CreateTerminalRequest,
  TerminalImage,
  TerminalRuntimeConfig,
} from '@/types/terminal'

export async function createTerminalSession(req?: CreateTerminalRequest) {
  const { data } = await apiClient.post<TerminalSession>('/terminal/sessions', req ?? {})
  return data
}

export async function listTerminalSessions() {
  const { data } = await apiClient.get<TerminalSession[]>('/terminal/sessions')
  return data
}

export async function getTerminalSession(sessionId: string) {
  const { data } = await apiClient.get<TerminalSession>(`/terminal/sessions/${sessionId}`)
  return data
}

export async function deleteTerminalSession(sessionId: string) {
  const { data } = await apiClient.delete<{ deleted: boolean }>(`/terminal/sessions/${sessionId}`)
  return data
}

export async function listTerminalImages() {
  const { data } = await apiClient.get<TerminalImage[]>('/terminal/environments')
  return data
}

export async function getTerminalConfig() {
  const { data } = await apiClient.get<TerminalRuntimeConfig>('/terminal/config')
  return data
}
