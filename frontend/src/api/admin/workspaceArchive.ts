import apiClient from '../client'

/** 工作区归档管理总览（GET /admin/workspace-archive/overview） */
export interface WorkspaceArchiveOverview {
  archive_total_bytes: number
  archive_total_packages: number
  workspace_total_bytes: number
  active_days: number
  dormant_days: number
  archive_retention_days: number
  quota: {
    workspace_gb: number
    archive_gb: number
  }
  expiring_soon: Array<{
    package_id: string
    session_id: string
    username: string
    expires_at: string
  }>
  per_user: Array<{
    user_id: string
    username: string
    workspace_bytes: number
    archive_bytes: number
    package_count: number
    session_count: number
  }>
}

/** 归档配额/休眠策略配置（PUT /admin/workspace-archive/config） */
export interface WorkspaceArchiveConfig {
  workspace_gb?: number
  archive_gb?: number
  active_days?: number
  dormant_days?: number
  archive_retention_days?: number
}

export const adminWorkspaceArchiveApi = {
  /** 总览：平台/工作区容量、配置、到期提醒、每用户排行 */
  async getOverview(): Promise<WorkspaceArchiveOverview> {
    const res = await apiClient.get<WorkspaceArchiveOverview>('/admin/workspace-archive/overview')
    return res.data
  },

  /** 强制指定会话工作区进入休眠归档 */
  async dormantSession(sessionId: string): Promise<void> {
    await apiClient.post(`/admin/workspace-archive/sessions/${sessionId}/dormant`)
  },

  /** 删除指定归档包 */
  async deletePackage(packageId: string): Promise<void> {
    await apiClient.delete(`/admin/workspace-archive/packages/${packageId}`)
  },

  /** 更新配额/休眠策略配置，返回已生效配置 */
  async updateConfig(config: WorkspaceArchiveConfig): Promise<WorkspaceArchiveConfig> {
    const res = await apiClient.put<WorkspaceArchiveConfig>('/admin/workspace-archive/config', config)
    return res.data
  },
}
