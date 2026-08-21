import apiClient from '@/api/client'

export type AgentTeamsCaseStatus =
  | 'queued' | 'received' | 'planning_running' | 'preflight_running' | 'preflight_blocked' | 'waiting_for_correction'
  | 'approval_pending' | 'approved' | 'executing' | 'execution_failed' | 'quality_running'
  | 'quality_blocked' | 'remediation_pending' | 'delivery_ready' | 'closed' | 'cancelled'

export interface AgentTeamsCase {
  case_id: string
  /** 从完整 intent 派生的稳定短标题；intent 仍是完整 Case 目标。 */
  display_title?: string
  project_ref?: { kind: string; id: string; location?: string | null } | null
  context_refs: Array<{ kind: string; id: string; location?: string | null }>
  intent: string
  requester_ref: string
  /** 后端按 requester_ref 回填的用户名；昵称存在时由前端优先显示。 */
  requester_username?: string | null
  requester_nickname?: string | null
  team_id: string
  origin_consultation_id?: string | null
  consultation_summary?: string | null
  status: AgentTeamsCaseStatus
  omic_task_ids: string[]
  work_items: AgentTeamsWorkItem[]
  quality_decision?: string | null
  manifest_uri?: string | null
  plan_hash?: string | null
  plan_version?: number
  proposed_submission?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AgentTeamsWorkItem {
  work_item_id: string
  parent_work_item_id?: string | null
  target: string
  objective: string
  skill_name: string
  /** 对齐 Bridge models.py 的 9 态；in_progress 为旧别名保留。 */
  status: 'pending' | 'claimed' | 'running' | 'awaiting_approval' | 'in_progress' | 'completed' | 'blocked' | 'failed' | 'cancelled'
  summary?: string | null
  updated_at: string
}

export interface AgentTeamsEvent {
  event_id: string
  recorded_at: string
  case_id: string
  actor: string
  event_type: string
  payload: Record<string, unknown>
}

export interface AgentTeamsCaseCreateRequest {
  session_id?: string
  project_id?: string
  project_name?: string
  context_refs?: Array<{ kind: 'workspace' | 'file' | 'project'; id: string; location?: string; meta?: Record<string, unknown> }>
  intent: string
  flow_id?: string
  sample_sheet?: Array<Record<string, unknown>>
  comparisons?: Array<Record<string, unknown>>
  origin_consultation_id?: string
  consultation_summary?: string
}

export interface AgentTeamsCaseSubmitRequest {
  task_name: string
}

export interface AgentTeamsCaseRetryResponse {
  case_id: string
  work_item_id: string
  approval_id: string
  status: 'queued' | 'idempotent_replay'
  expires_at: string
}

export interface AgentTeamsCaseConfirmRequest {
  session_id: string
  objective: string
  project_id: string
  flow_id: string
  sample_context_refs?: Array<{ kind: 'workspace' | 'file'; id: string; location?: string }>
  origin_consultation_id?: string
  consultation_summary?: string
  confirmation_key: string
  confirmation_token: string
}

export interface AgentTeamsCaseRejectRequest {
  reason: string
}

export interface AgentTeamsQualityGateRequest {
  task_id?: string
  decision: 'passed' | 'blocked' | 'manual_review'
  rule_version: string
  summary: string
  evidence_refs?: string[]
}

/** 房间 @ 引用的上下文（kind 与后端 AgentTeamsContextRef 对齐）。 */
export type AgentTeamsContextRef = {
  kind: 'workspace' | 'file' | 'project'
  id: string
  location?: string
  meta?: Record<string, unknown>
}

export interface AgentTeamsPlanRevisionRequest {
  expected_plan_hash: string
  parameters: Record<string, unknown>
  reason: string
  override_revision_limit?: boolean
}

export interface AgentTeamsPlanRevisionResponse {
  case_id: string
  previous_plan_hash: string
  plan_hash: string
  previous_plan_version: number
  plan_version: number
  revision_count: number
  changed_parameter_keys: string[]
  replay_work_item_ids: string[]
  status: AgentTeamsCaseStatus
}

export interface AgentTeamsCaseListParams {
  status?: AgentTeamsCaseStatus
  project_id?: string
  cursor?: string
  limit?: number
}

export interface AgentTeamsCaseListResponse {
  items: AgentTeamsCase[]
  total: number
  next_cursor?: string | null
}

export interface AgentTeamsEventListResponse {
  events: AgentTeamsEvent[]
  next_cursor?: string | null
}

/** 协作室房间（轻量会话实体，会话-工单解耦）：先于 Case 存在，立项确认后才绑定 case_id。 */
export interface AgentTeamsRoom {
  room_id: string
  title: string
  status: string
  origin: string
  /** 立项确认后回写的绑定 Case；未立项为 null。 */
  case_id: string | null
  matrix_room_provisioned: boolean
  /** 当前是否存在待消费的立项确认卡。 */
  has_pending_proposal: boolean
  created_at: string | null
  updated_at: string | null
}

export interface AgentTeamsRoomCreateRequest {
  title?: string
  origin?: string
}

export interface AgentTeamsRoomListResponse {
  items: AgentTeamsRoom[]
  total: number
}

export type AgentTeamsProposalDecision = 'confirm' | 'modify' | 'cancel'
export type AgentTeamsProposalFollowupMode = 'continue' | 'new'

export interface AgentTeamsProposalConfirmRequest {
  /** 可选的二次校验 nonce（B1：token 不再经事件流分发；不带则凭 owner+pending 消费）。 */
  confirm_token?: string
  decision: AgentTeamsProposalDecision
  /** followup 卡（Case 终态后再立项）专用：基于上一 Case 继续 / 新建工单。 */
  followup_mode?: AgentTeamsProposalFollowupMode
  note?: string
}

export interface AgentTeamsProposalConfirmResponse {
  status: 'confirmed' | 'already_bound' | 'modify_requested' | 'cancelled'
  case_id?: string
  source_case_id?: string | null
  idempotent_replay?: boolean
}

/** 房间聚合事件响应：复合游标 `ns:<id>|case:<id>`，对前端不透明、原样回传即可。 */
export interface AgentTeamsRoomEventListResponse extends AgentTeamsEventListResponse {
  room_id?: string
  case_id?: string | null
}

export interface AgentTeamsRoleLabel {
  agent_id: string
  name: string
  avatar: string
  color: string
  role: string
  /** 人格副标题（features.persona.archetype）；未配置时为空。 */
  archetype?: string
}

export interface AgentTeamsRoleLabelsResponse {
  role_labels: Record<string, AgentTeamsRoleLabel>
  role_agent_map: Record<string, string>
  /** 协作室 Manager 展示身份（后端 agent YAML 的 name 为唯一权威来源）。 */
  manager?: {
    agent_id: string
    display_name: string
  }
}

export interface AgentTeamsBridgeStatus {
  available: boolean
  enabled: boolean
  configured: boolean
  connected: boolean
  configuration_source: 'database' | 'environment'
  reason: 'disabled' | 'incomplete_configuration' | 'bridge_unreachable' | null
}

export interface AgentTeamsCapabilityCheck {
  flow_id: string | null
  available: boolean
  reason?: string
  stages: Array<{
    stage: string
    agent_id: string
    execution_mode?: string
    available: boolean
    identity_configured: boolean
    worker_online: boolean
    reason: string
  }>
}

export interface AgentTeamsResponseTimingSummary {
  case_id: string
  sample_count: number
  p95_duration_ms: number
  stage_p95_ms: Record<string, number>
  latest_duration_ms: number
}

export const agentTeamsApi = {
  async status(): Promise<AgentTeamsBridgeStatus> {
    return (await apiClient.get('/agent-teams/status')).data
  },
  async getRoleLabels(): Promise<AgentTeamsRoleLabelsResponse> {
    return (await apiClient.get<AgentTeamsRoleLabelsResponse>('/agent-teams/role-labels')).data
  },
  async listCases(params: AgentTeamsCaseListParams = {}): Promise<AgentTeamsCaseListResponse> {
    return (await apiClient.get<AgentTeamsCaseListResponse>('/agent-teams/cases', { params })).data
  },
  async createCase(payload: AgentTeamsCaseCreateRequest): Promise<AgentTeamsCase> {
    return (await apiClient.post<AgentTeamsCase>('/agent-teams/cases', payload)).data
  },
  async confirmCase(payload: AgentTeamsCaseConfirmRequest): Promise<{ case_card: Record<string, unknown> }> {
    return (await apiClient.post('/agent-teams/cases/confirm', payload)).data
  },
  async getCase(caseId: string): Promise<AgentTeamsCase> {
    return (await apiClient.get<AgentTeamsCase>(`/agent-teams/cases/${caseId}`)).data
  },
  async getCapabilityCheck(caseId: string): Promise<AgentTeamsCapabilityCheck> {
    return (await apiClient.get<AgentTeamsCapabilityCheck>(`/agent-teams/cases/${caseId}/capability-check`)).data
  },
  async getResponseTiming(caseId: string): Promise<AgentTeamsResponseTimingSummary> {
    return (await apiClient.get<AgentTeamsResponseTimingSummary>(`/agent-teams/cases/${caseId}/response-timing`)).data
  },
  async refreshCase(caseId: string): Promise<AgentTeamsCase> {
    return (await apiClient.post<AgentTeamsCase>(`/agent-teams/cases/${caseId}/refresh`)).data
  },
  async retryCase(caseId: string): Promise<AgentTeamsCaseRetryResponse> {
    return (await apiClient.post<AgentTeamsCaseRetryResponse>(`/agent-teams/cases/${caseId}/retry`)).data
  },
  async submitCase(caseId: string, payload: AgentTeamsCaseSubmitRequest): Promise<{ omic_task_id?: string; status: string }> {
    return (await apiClient.post(`/agent-teams/cases/${caseId}/submit`, payload)).data
  },
  async submitQualityGate(caseId: string, payload: AgentTeamsQualityGateRequest): Promise<{ case_id: string; task_id: string; decision: string; summary: string }> {
    return (await apiClient.post(`/agent-teams/cases/${caseId}/quality-gate`, payload)).data
  },
  async rejectCase(caseId: string, payload: AgentTeamsCaseRejectRequest): Promise<AgentTeamsCase> {
    return (await apiClient.post<AgentTeamsCase>(`/agent-teams/cases/${caseId}/reject`, payload)).data
  },
  async cancelCase(caseId: string, payload: AgentTeamsCaseRejectRequest): Promise<AgentTeamsCase> {
    return (await apiClient.post<AgentTeamsCase>(`/agent-teams/cases/${caseId}/cancel`, payload)).data
  },
  async deleteCase(caseId: string): Promise<Record<string, unknown>> {
    return (await apiClient.delete(`/agent-teams/cases/${caseId}`, { timeout: 70000 })).data
  },
  async postCaseMessage(
    caseId: string,
    content: string,
    contextRefs: AgentTeamsContextRef[] = [],
    clientMessageId?: string,
  ): Promise<Record<string, unknown>> {
    return (await apiClient.post(`/agent-teams/cases/${caseId}/messages`, {
      content,
      context_refs: contextRefs,
      client_message_id: clientMessageId,
    })).data
  },
  async applyChangeDecision(
    caseId: string,
    payload: { work_item_ids: string[]; decision: 'resume' | 'replan' | 'branch' | 'cancel'; rationale?: string },
  ): Promise<Record<string, unknown>> {
    return (await apiClient.post(`/agent-teams/cases/${caseId}/change-decisions`, payload)).data
  },
  async revisePlan(caseId: string, payload: AgentTeamsPlanRevisionRequest): Promise<AgentTeamsPlanRevisionResponse> {
    return (await apiClient.post<AgentTeamsPlanRevisionResponse>(`/agent-teams/cases/${caseId}/plan/revise`, payload)).data
  },
  async getManifest(caseId: string): Promise<Record<string, unknown>> {
    return (await apiClient.get<Record<string, unknown>>(`/agent-teams/cases/${caseId}/manifest`)).data
  },
  async getEvents(
    caseId: string,
    params: { cursor?: string; limit?: number } = {},
  ): Promise<AgentTeamsEventListResponse> {
    return (await apiClient.get<AgentTeamsEventListResponse>(
      `/agent-teams/cases/${caseId}/events`,
      { params },
    )).data
  },
  async createRoom(payload: AgentTeamsRoomCreateRequest = {}): Promise<AgentTeamsRoom> {
    return (await apiClient.post<AgentTeamsRoom>('/agent-teams/rooms', payload)).data
  },
  async listRooms(): Promise<AgentTeamsRoomListResponse> {
    return (await apiClient.get<AgentTeamsRoomListResponse>('/agent-teams/rooms')).data
  },
  async getRoom(roomId: string): Promise<AgentTeamsRoom> {
    return (await apiClient.get<AgentTeamsRoom>(`/agent-teams/rooms/${roomId}`)).data
  },
  async postRoomMessage(
    roomId: string,
    content: string,
    contextRefs: AgentTeamsContextRef[] = [],
    clientMessageId?: string,
  ): Promise<Record<string, unknown>> {
    return (await apiClient.post(`/agent-teams/rooms/${roomId}/messages`, {
      content,
      context_refs: contextRefs,
      client_message_id: clientMessageId,
    })).data
  },
  async confirmRoomProposal(
    roomId: string,
    payload: AgentTeamsProposalConfirmRequest,
  ): Promise<AgentTeamsProposalConfirmResponse> {
    return (await apiClient.post<AgentTeamsProposalConfirmResponse>(
      `/agent-teams/rooms/${roomId}/confirm-proposal`,
      payload,
    )).data
  },
  async getRoomEvents(
    roomId: string,
    params: { cursor?: string; limit?: number } = {},
  ): Promise<AgentTeamsRoomEventListResponse> {
    return (await apiClient.get<AgentTeamsRoomEventListResponse>(
      `/agent-teams/rooms/${roomId}/events`,
      { params },
    )).data
  },
}
