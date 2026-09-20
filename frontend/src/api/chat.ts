import apiClient from './client'
import type { PlanDecisionAction } from '@/components/ai-chat/types'
import type { ResearchModeSettings } from '@/types/chat'

export interface OverdriveApprovalRecord {
  approval_id: string
  run_id?: string
  tool_name: string
  arguments: Record<string, unknown>
  status: 'pending' | 'executing' | 'completed' | 'rejected' | 'failed'
  result?: Record<string, unknown>
  error?: string
  reason?: string
}

export interface ActiveOverdriveRunSnapshot {
  run_id: string
  status: string
  plan?: Record<string, unknown>
  tasks?: Array<Record<string, unknown>>
  assistant_instances?: Array<Record<string, unknown>>
  artifact_index?: Array<Record<string, unknown>>
  event_cursor?: number
}

export const chatApi = {
  async controlOverdriveRun(
    sessionId: string,
    runId: string,
    action: 'pause' | 'resume' | 'terminate',
  ): Promise<Record<string, unknown>> {
    const commandId = globalThis.crypto?.randomUUID?.()
      || `control-${runId}-${action}-${Date.now()}`
    const response = await apiClient.post(
      `/chat/sessions/${sessionId}/overdrive-runs/${runId}/control`,
      { command_id: commandId, action },
    )
    return response.data
  },
  async getActiveOverdriveRun(sessionId: string): Promise<ActiveOverdriveRunSnapshot | null> {
    const response = await apiClient.get<{ run?: ActiveOverdriveRunSnapshot | null }>(
      `/chat/sessions/${sessionId}/overdrive-runs/active`,
    )
    return response.data.run || null
  },
  async getLatestOverdriveRun(sessionId: string): Promise<ActiveOverdriveRunSnapshot | null> {
    const response = await apiClient.get<{ run?: ActiveOverdriveRunSnapshot | null }>(
      `/chat/sessions/${sessionId}/overdrive-runs/latest`,
    )
    return response.data.run || null
  },
  async getOverdrivePlan(sessionId: string, runId: string): Promise<string> {
    const response = await apiClient.get(
      `/chat/sessions/${sessionId}/overdrive-runs/${runId}/plan`,
      { responseType: 'text' },
    )
    return typeof response.data === 'string'
      ? response.data
      : String((response.data as Record<string, unknown>)?.content || '')
  },
  async downloadOverdriveArtifact(sessionId: string, runId: string, path: string): Promise<Blob> {
    const response = await apiClient.get(
      `/chat/sessions/${sessionId}/overdrive-runs/${runId}/artifacts`,
      { params: { path }, responseType: 'blob' },
    )
    return response.data as Blob
  },
  async decideOverdrivePlan(
    sessionId: string,
    runId: string,
    payload: {
      action: PlanDecisionAction
      planVersion: number
      planHash: string
      feedback?: string
      commandId: string
    },
  ): Promise<Record<string, unknown>> {
    const response = await apiClient.post(
      `/chat/sessions/${sessionId}/overdrive-runs/${runId}/plan-decision`,
      {
        action: payload.action,
        plan_version: payload.planVersion,
        plan_hash: payload.planHash,
        feedback: payload.feedback || '',
        command_id: payload.commandId,
      },
    )
    return response.data
  },
  async decideOverdriveBranchApproval(
    sessionId: string,
    runId: string,
    approvalId: string,
    action: 'approve' | 'reject',
    reason = '',
  ): Promise<Record<string, unknown>> {
    const commandId = globalThis.crypto?.randomUUID?.()
      || `approval-${runId}-${approvalId}-${action}-${Date.now()}`
    const response = await apiClient.post(
      `/chat/sessions/${sessionId}/overdrive-runs/${runId}/approvals/${approvalId}/decision`,
      { command_id: commandId, action, reason },
    )
    return response.data
  },
  async controlOverdrive(
    sessionId: string,
    action: 'pause' | 'resume' | 'skip' | 'terminate' | 'directive',
    options: { taskId?: string; directive?: string } = {},
  ): Promise<Record<string, unknown>> {
    const response = await apiClient.post(`/chat/sessions/${sessionId}/overdrive/control`, {
      action,
      task_id: options.taskId,
      directive: options.directive,
    })
    return response.data
  },
  async approveOverdriveApproval(sessionId: string, approvalId: string): Promise<OverdriveApprovalRecord> {
    const response = await apiClient.post(
      `/chat/sessions/${sessionId}/overdrive-approvals/${approvalId}/approve`,
    )
    return response.data
  },
  async rejectOverdriveApproval(
    sessionId: string,
    approvalId: string,
    reason?: string,
  ): Promise<OverdriveApprovalRecord> {
    const response = await apiClient.post(
      `/chat/sessions/${sessionId}/overdrive-approvals/${approvalId}/reject`,
      { reason },
    )
    return response.data
  },
  async renameSession(
    sessionId: string,
    title: string,
  ): Promise<{ session_id: string; title: string; title_locked?: boolean }> {
    const response = await apiClient.patch(`/chat/sessions/${sessionId}`, { title })
    return response.data
  },
  /**
   * 人类（JWT 会话）批准一次待确认的工具/流程调用。
   * 优先用服务端确认卡下发的人类通道 URL（tool-invocations 或 tool-confirmations），
   * 缺省时回退到通用工具批准端点。apiClient 的 baseURL 已含 /api/v1，需剥离前缀。
   */
  async approveToolConfirmation(
    confirmationId: string,
    actionUrl?: string,
  ): Promise<Record<string, unknown>> {
    const path = (actionUrl || `/api/v1/ai/tool-invocations/${confirmationId}/approve`)
      .replace(/^\/api\/v1/, '')
    const response = await apiClient.post(path)
    return response.data
  },
  async rejectToolConfirmation(
    confirmationId: string,
    reason?: string,
    actionUrl?: string,
  ): Promise<Record<string, unknown>> {
    const path = (actionUrl || `/api/v1/ai/tool-invocations/${confirmationId}/reject`)
      .replace(/^\/api\/v1/, '')
    const response = await apiClient.post(path, null, { params: { reason } })
    return response.data
  },
  async deleteSession(sessionId: string): Promise<void> {
    await apiClient.delete(`/chat/sessions/${sessionId}`)
  },
  /**
   * 科研模式设置（WP3 任务 3）：PUT 后 200 回显生效值。
   * 后端未上线时调用会失败，调用方负责回滚 UI 状态。
   */
  async updateResearchMode(
    sessionId: string,
    settings: ResearchModeSettings,
  ): Promise<ResearchModeSettings> {
    const response = await apiClient.put<ResearchModeSettings>(
      `/chat/sessions/${sessionId}/research-mode`,
      settings,
    )
    return response.data
  },
  /** 会话生命周期：active → archived（归档后可从活跃列表隐藏） */
  async archiveSession(sessionId: string): Promise<void> {
    await apiClient.post(`/chat/sessions/${sessionId}/archive`)
  },
  /** 会话生命周期：archived → active */
  async unarchiveSession(sessionId: string): Promise<void> {
    await apiClient.post(`/chat/sessions/${sessionId}/unarchive`)
  },
  /** 会话生命周期：deleted → active（回收站恢复） */
  async restoreSession(sessionId: string): Promise<void> {
    await apiClient.post(`/chat/sessions/${sessionId}/restore`)
  },
  async submitMessageFeedback(
    sessionId: string,
    messageId: string,
    rating: 'like' | 'dislike' | 'none',
    comment?: string,
  ): Promise<{ feedback: { rating: string } | null }> {
    const response = await apiClient.put(
      `/chat/sessions/${sessionId}/messages/${messageId}/feedback`,
      { rating, comment },
    )
    return response.data
  },
  async getSessionFeedbacks(sessionId: string): Promise<Record<string, 'like' | 'dislike'>> {
    const response = await apiClient.get(`/chat/sessions/${sessionId}/feedbacks`)
    return response.data
  },
}
