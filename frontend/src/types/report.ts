export type ReportStatus = 'generating' | 'completed' | 'failed' | 'expired'

export interface ReportFile {
  id: string
  report_id: string
  name: string
  type: 'html' | 'pdf' | 'png' | 'zip' | 'csv'
  size: number
  path: string
  is_primary: boolean
  created_at: string
}

export interface Report {
  id: string
  task_id: string
  user_id: string
  flow_id: string
  flow_name: string
  flow_version: string
  flow_icon: string
  title: string
  description: string
  status: ReportStatus
  sample_count: number
  duration: number
  created_at: string
  completed_at: string | null
  is_read: boolean
  is_starred: boolean
  files: ReportFile[]
}

export interface ReportFilter {
  keyword?: string
  flow_id?: string
  status?: ReportStatus | ''
  date_range?: '7d' | '30d' | '90d' | ''
  is_starred?: boolean
  page?: number
  page_size?: number
}

export interface ReportListResponse {
  items: Report[]
  total: number
}

export interface ReportStats {
  total: number
  starred: number
  generating: number
  today: number
}
