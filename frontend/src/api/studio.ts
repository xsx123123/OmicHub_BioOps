/**
 * OmicStudio AI 分析工作台 API
 *
 * 对应后端 /api/v1/studio 路由（P0-2）：
 * 会话创建/列表/详情、工作区文件、产物清单与下载。
 * 聊天流复用 POST /chat/stream（见 useAgentChatStream），
 * 代码重跑 SSE 见 @/composables/useStudioRunStream。
 */
import apiClient from './client'

function triggerBlobDownload(url: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()

  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

/** Studio 会话（后端 ChatSessionDTO，mode="studio"） */
export interface StudioSessionDTO {
  session_id: string
  title: string
  agent_id: string | null
  model_id: string
  message_count: number
  status: string
  mode: 'studio'
  created_at: string
  updated_at: string
  last_message_at: string | null
  multi_agent?: boolean
  overdrive?: boolean
}

export type SandboxStatus = 'running' | 'stopped' | 'absent' | 'unavailable'

export interface WorkspaceEntry {
  name: string
  type: 'file' | 'dir'
  size: number
  mtime: number
}

export interface StudioCapabilityAuditEvent {
  action: 'list' | 'load' | string
  kind: 'skill' | 'mcp' | null
  capability_id: string | null
  success: boolean
  at: string
}

export interface StudioCapabilitiesState {
  loaded_skill_ids: string[]
  loaded_mcp_ids: string[]
  audit: StudioCapabilityAuditEvent[]
}


export interface ExtractStudioSkillPayload {
  path: string
  skill_id: string
  name: string
  description: string
  usage_instructions: string
  category: string
  icon: string
  confirm_no_secrets: boolean
}

export interface ExtractedSkill {
  id: string
  skill_id: string
  name: string
  description: string
  category: string
  is_active: boolean
}

export interface StudioShareResponse {
  token: string
  share_path: string
  expires_at: string
}

export interface StudioShareStatus {
  active: boolean
  expires_at: string | null
  shared_at: string | null
}

export interface SharedStudioMessage {
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface SharedStudioSession {
  title: string
  agent_id: string | null
  created_at: string
  updated_at: string
  expires_at: string
  messages: SharedStudioMessage[]
  artifacts: StudioArtifact[]
}

/** Studio 会话级权限模式（supervised=关键操作需用户批准；auto=放权自动执行） */
export type StudioPermissionMode = 'supervised' | 'auto'

export interface StudioPermissions {
  mode: StudioPermissionMode
}

/** 待审批的工具审批记录（GET /studio/approvals，对应 Redis 中的 pending 记录） */
export interface StudioPendingApproval {
  approval_id: string
  session_id: string
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  risk_hint: string
  status: 'pending'
  /** 剩余可审批秒数（Redis TTL） */
  expires_in: number
}

export interface StudioSessionDetail {
  session: StudioSessionDTO
  sandbox_status: SandboxStatus
  permissions?: StudioPermissions
  workspace_id: string | null
  files: WorkspaceEntry[]
  plan: StudioPlan | null
  capabilities: StudioCapabilitiesState | null
  sandbox_metrics: {
    cpu_percent: number
    memory_percent: number
    memory_used: number
    memory_limit: number
  }
  ui: {
    view_mode: 'chat' | 'split' | 'code'
    split_ratio: number
    follow_ai: boolean
    terminal_collapsed: boolean
    hibernate_on_leave: boolean
  }
  share: StudioShareStatus | null
}

export type StudioPlanStatus = 'pending' | 'in_progress' | 'done'

export interface StudioPlanStep {
  title: string
  status: StudioPlanStatus
}

export interface StudioPlan {
  steps: StudioPlanStep[]
}

export interface StudioArtifact {
  path: string
  size: number
  mtime: number
  download_url?: string
}

export interface StudioRunArtifact {
  path: string
  size: number
  mtime: number
}

export interface StudioImportResult {
  sandbox_path: string
  name: string
  size: number
  file_type: string
  input_files: string[]
}

export interface StudioFileEditResult {
  path: string
  diff: string
  size: number
}

export interface StudioArtifactRegistration {
  report_id: string
  title: string
  version: number
  parent_id: string | null
  file: Record<string, unknown>
}

/** 产物下载地址（需携带 JWT，前端统一走 blob 下载，见 downloadArtifact） */
export function artifactDownloadUrl(sessionId: string, path: string): string {
  return `/api/v1/studio/sessions/${sessionId}/artifacts/download?path=${encodeURIComponent(path)}`
}

export const studioApi = {
  /** 创建 Studio 会话（mode="studio"，workspace_id = session id） */
  async createSession(payload: {
    agent_id: string
    title?: string
    model_id?: string
  }): Promise<StudioSessionDTO> {
    const res = await apiClient.post<StudioSessionDTO>('/studio/sessions', payload)
    return res.data
  },

  /** 将普通聊天会话升级为 Studio 工作台（保留历史消息），可选重绑定 Agent */
  async promoteSession(sessionId: string, agentId?: string): Promise<StudioSessionDTO> {
    const res = await apiClient.post<StudioSessionDTO>(
      `/studio/sessions/${sessionId}/promote`,
      agentId ? { agent_id: agentId } : {},
    )
    return res.data
  },

  /** 从结果报告创建 Studio 会话并注入来源上下文 */
  async createSessionFromReport(payload: {
    report_id: string
    agent_id: string
  }): Promise<StudioSessionDTO> {
    const res = await apiClient.post<StudioSessionDTO>('/studio/sessions/from-report', payload)
    return res.data
  },

  /** 当前用户的 Studio 会话列表（按更新时间倒序） */
  async listSessions(): Promise<StudioSessionDTO[]> {
    const res = await apiClient.get<StudioSessionDTO[]>('/studio/sessions')
    return res.data || []
  },

  /** 会话详情 + 沙盒状态 + 工作区根目录条目 */
  async getSession(sessionId: string): Promise<StudioSessionDetail> {
    const res = await apiClient.get<StudioSessionDetail>(`/studio/sessions/${sessionId}`)
    return res.data
  },

  /** 更新会话级权限模式（supervised/auto，P1 HITL） */
  async updatePermissions(
    sessionId: string,
    mode: StudioPermissionMode,
  ): Promise<StudioPermissions> {
    const res = await apiClient.post<StudioPermissions>(
      `/studio/sessions/${sessionId}/permissions`,
      { mode },
    )
    // 后端返回 {permissions: {mode}} 或直接 {mode}，两种封装都兼容
    const data = res.data as StudioPermissions & { permissions?: StudioPermissions }
    return data.permissions || data
  },

  /** 列出指定会话仍处于 pending 的工具审批（刷新/断流重进会话时重建审批卡） */
  async listPendingApprovals(sessionId: string): Promise<StudioPendingApproval[]> {
    const res = await apiClient.get<{ approvals: StudioPendingApproval[] }>(
      '/studio/approvals',
      { params: { session_id: sessionId } },
    )
    return res.data?.approvals || []
  },

  /** 批准待审批的工具调用；带 modifiedArgs 即"编辑后批准" */
  async approveApproval(
    approvalId: string,
    modifiedArgs?: Record<string, unknown>,
  ): Promise<void> {
    await apiClient.post(`/studio/approvals/${approvalId}/approve`, {
      ...(modifiedArgs ? { modified_args: modifiedArgs } : {}),
    })
  },

  /** 退回待审批的工具调用（理由回灌 LLM 让其修改后重试） */
  async rejectApproval(approvalId: string, reason?: string): Promise<void> {
    await apiClient.post(`/studio/approvals/${approvalId}/reject`, {
      ...(reason ? { reason } : {}),
    })
  },

  async updateUi(
    sessionId: string,
    payload: { view_mode?: 'chat' | 'split' | 'code'; split_ratio?: number; follow_ai?: boolean; terminal_collapsed?: boolean },
  ): Promise<void> {
    await apiClient.patch(`/studio/sessions/${sessionId}/ui`, payload)
  },

  /** 释放沙盒容器但保留工作区；下一次执行会自动重建并挂回原目录。 */
  async hibernateSession(
    sessionId: string,
  ): Promise<{ status: 'hibernated' | 'busy' | 'absent' | 'unavailable'; workspace_preserved: boolean }> {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/studio/sessions/${sessionId}/sandbox/hibernate`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      keepalive: true,
    })
    if (!response.ok) throw new Error(`沙盒休眠失败 (${response.status})`)
    return response.json()
  },

  /** 创建或轮换只读分享令牌 */
  async createShare(sessionId: string, expiresHours = 168): Promise<StudioShareResponse> {
    const res = await apiClient.post<StudioShareResponse>(`/studio/sessions/${sessionId}/share`, {
      expires_hours: expiresHours,
    })
    return res.data
  },

  async getShareStatus(sessionId: string): Promise<StudioShareStatus> {
    const res = await apiClient.get<StudioShareStatus>(`/studio/sessions/${sessionId}/share`)
    return res.data
  },

  async revokeShare(sessionId: string): Promise<void> {
    await apiClient.delete(`/studio/sessions/${sessionId}/share`)
  },

  async exportPrintableReport(sessionId: string): Promise<string> {
    const res = await apiClient.get<string>(`/studio/sessions/${sessionId}/export`, {
      responseType: 'text',
    })
    return res.data
  },

  async getSharedSession(token: string): Promise<SharedStudioSession> {
    const res = await apiClient.get<SharedStudioSession>(`/studio/shared/${token}`)
    return res.data
  },

  sharedArtifactUrl(token: string, path: string): string {
    return `/api/v1/studio/shared/${encodeURIComponent(token)}/artifacts?path=${encodeURIComponent(path)}`
  },

  async extractSkill(
    sessionId: string,
    payload: ExtractStudioSkillPayload,
  ): Promise<ExtractedSkill> {
    const res = await apiClient.post<ExtractedSkill>(
      `/studio/sessions/${sessionId}/skills/extract`,
      payload,
    )
    return res.data
  },

  /** 完整保存工作区文本文件（编辑器 Ctrl/Cmd+S） */
  async writeFile(
    sessionId: string,
    payload: { path: string; content: string },
  ): Promise<{ path: string; size: number }> {
    const res = await apiClient.put<{ path: string; size: number }>(
      `/studio/sessions/${sessionId}/files/write`,
      payload,
    )
    return res.data
  },

  async makeDirectory(sessionId: string, path: string): Promise<void> {
    await apiClient.post(`/studio/sessions/${sessionId}/files/mkdir`, { path })
  },
  async renameFile(sessionId: string, path: string, newPath: string): Promise<void> {
    await apiClient.post(`/studio/sessions/${sessionId}/files/rename`, { path, new_path: newPath })
  },
  async deleteFile(sessionId: string, path: string): Promise<void> {
    await apiClient.delete(`/studio/sessions/${sessionId}/files/delete`, { params: { path } })
  },

  /** 精确编辑工作区文件（拒绝 workspace_edit 时交换 old/new 回滚） */
  async editFile(
    sessionId: string,
    payload: { path: string; old_string: string; new_string: string },
  ): Promise<StudioFileEditResult> {
    const res = await apiClient.post<StudioFileEditResult>(
      `/studio/sessions/${sessionId}/files/edit`,
      payload,
    )
    return res.data
  },

  /** 工作区目录列表（path 相对 /workspace） */
  async listFiles(
    sessionId: string,
    path = '',
  ): Promise<{ path: string; entries: WorkspaceEntry[] }> {
    const res = await apiClient.get<{ path: string; entries: WorkspaceEntry[] }>(
      `/studio/sessions/${sessionId}/files`,
      { params: { path } },
    )
    return res.data
  },

  /** 以 blob 方式读取任意受路径守卫保护的工作区文件（图片/二进制预览）。 */
  async fetchWorkspaceBlob(sessionId: string, path: string): Promise<string> {
    const res = await apiClient.get(`/studio/sessions/${sessionId}/files/download`, {
      params: { path },
      responseType: 'blob',
    })
    return URL.createObjectURL(res.data as Blob)
  },

  async downloadWorkspaceFile(sessionId: string, path: string): Promise<void> {
    const url = await studioApi.fetchWorkspaceBlob(sessionId, path)
    triggerBlobDownload(url, path.split('/').pop() || 'workspace-file')
  },

  /** 分页读取工作区文件 */
  async readFile(
    sessionId: string,
    path: string,
    offset = 0,
    limit = 200,
  ): Promise<{ content: string; total_lines: number; truncated: boolean }> {
    const res = await apiClient.get<{ content: string; total_lines: number; truncated: boolean }>(
      `/studio/sessions/${sessionId}/files/read`,
      { params: { path, offset, limit } },
    )
    return res.data
  },

  /** 将数据管理文件以只读软链引入 /workspace/input */
  async importDataFile(
    sessionId: string,
    payload: { file_id: string; name?: string },
  ): Promise<StudioImportResult> {
    const res = await apiClient.post<StudioImportResult>(
      `/studio/sessions/${sessionId}/import`,
      payload,
    )
    return res.data
  },

  /** 读取产物文本预览，实际复用工作区分页读取守卫 */
  async readArtifactText(
    sessionId: string,
    path: string,
    limit = 500,
  ): Promise<{ content: string; total_lines: number; truncated: boolean }> {
    return studioApi.readFile(sessionId, path, 0, limit)
  },

  /** 产物清单（/workspace/output） */
  async listArtifacts(sessionId: string): Promise<StudioArtifact[]> {
    const res = await apiClient.get<{ artifacts: StudioArtifact[] }>(
      `/studio/sessions/${sessionId}/artifacts`,
    )
    return res.data?.artifacts || []
  },

  /** 将 output/ 产物登记到报告中心；来源报告会话自动挂接版本树 */
  async registerArtifact(
    sessionId: string,
    payload: { path: string; title: string; type?: string; description?: string },
  ): Promise<StudioArtifactRegistration> {
    const res = await apiClient.post<StudioArtifactRegistration>(
      `/studio/sessions/${sessionId}/artifacts/register`,
      payload,
    )
    return res.data
  },

  /** 以 blob 方式拉取产物（携带 JWT），返回 Object URL，调用方负责 revoke */
  async fetchArtifactBlob(sessionId: string, path: string): Promise<string> {
    const res = await apiClient.get(`/studio/sessions/${sessionId}/artifacts/download`, {
      params: { path },
      responseType: 'blob',
    })
    return URL.createObjectURL(res.data as Blob)
  },

  /** 触发浏览器下载产物 */
  async downloadArtifact(sessionId: string, path: string): Promise<void> {
    const url = await studioApi.fetchArtifactBlob(sessionId, path)
    triggerBlobDownload(url, path.split('/').pop() || 'artifact')
  },
}
