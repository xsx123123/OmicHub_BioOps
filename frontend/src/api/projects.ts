/**
 * 项目 API
 *
 * 对应后端 /api/v1/projects 路由：
 * 项目列表/详情，以及「按项目浏览历史分析」的总览聚合端点
 * （GET /projects/{id}/overview：元数据 + 项目会话 + runs 目录历史分析）。
 */
import apiClient from './client'

export interface ProjectItem {
  id: string
  name: string
  slug: string
  description: string
  /** 客户名称（并行开发字段，可能缺省） */
  customer?: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectSessionItem {
  id: string
  title: string
  agent_id: string | null
  status: string
  /** chat=AI 对话；studio=工作台；agentteams=AgentTeams 协作会话（跳转使用 room_id/case_id） */
  mode: string
  message_count: number
  last_message_at: string | null
  created_at: string | null
  updated_at: string | null
  /** AgentTeams 协作会话对应的协作房间（可空；后端契约新增字段） */
  room_id?: string | null
  /** AgentTeams 协作会话对应的 Case（可空；后端契约新增字段） */
  case_id?: string | null
}

/** 会话状态过滤：active=活跃（默认）、archived=已归档、deleted=回收站 */
export type ProjectSessionStatus = 'active' | 'archived' | 'deleted'

export interface ProjectRunItem {
  name: string
  timestamp: string | null
  has_agents_md: boolean
  has_readme: boolean
  has_environment: boolean
  file_count: number
  total_size_bytes: number
}

export interface ProjectOverview {
  project: ProjectItem
  sessions: {
    total: number
    limit: number
    offset: number
    items: ProjectSessionItem[]
  }
  runs: ProjectRunItem[]
}

export const projectsApi = {
  /** 当前用户的项目列表（后端首次访问会从磁盘回填历史项目） */
  async listProjects(): Promise<ProjectItem[]> {
    const res = await apiClient.get<ProjectItem[]>('/projects')
    return res.data || []
  },

  /** 创建项目（后端自动生成 slug 并同步创建目录；409 表示重名冲突） */
  async createProject(payload: {
    name: string
    description?: string
    customer?: string
  }): Promise<ProjectItem> {
    const res = await apiClient.post<ProjectItem>('/projects', payload)
    return res.data
  },

  /** 单个项目详情 */
  async getProject(projectId: string): Promise<ProjectItem> {
    const res = await apiClient.get<ProjectItem>(`/projects/${projectId}`)
    return res.data
  },

  /**
   * 项目级设置（WP3 任务 3 可选项）：如"项目内新会话默认开启科研模式"。
   * 后端端点可能稍后到位，调用方必须容忍失败并回滚 UI。
   */
  async updateProjectSettings(
    projectId: string,
    settings: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const res = await apiClient.patch<Record<string, unknown>>(`/projects/${projectId}`, { settings })
    return res.data
  },

  /** 项目总览：元数据 + 历史会话（分页，可按状态过滤）+ 历史分析 run 目录 */
  async getProjectOverview(
    projectId: string,
    params?: {
      session_limit?: number
      session_offset?: number
      session_status?: ProjectSessionStatus
    },
  ): Promise<ProjectOverview> {
    const res = await apiClient.get<ProjectOverview>(`/projects/${projectId}/overview`, {
      params,
    })
    return res.data
  },
}
