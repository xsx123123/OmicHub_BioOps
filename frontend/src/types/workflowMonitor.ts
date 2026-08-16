export interface MonitorTemplateListItem {
  id: string
  name: string
  version: string
  scope: 'user' | 'admin' | string
  description?: string
}

export interface MonitorFilter {
  key: string
  label: string
  type: 'select' | 'flow_select' | 'search' | string
  default?: unknown
  placeholder?: string
  options?: Array<{ label: string; value: string }>
}

export interface MonitorWidgetLayout {
  x: number
  y: number
  w: number
  h: number
}

export interface MonitorTableColumn {
  key: string
  label: string
  width?: number
  renderer?: 'status_badge' | 'progress_bar' | 'relative_time' | string
  action?: 'open_task' | 'open_report' | 'open_logs' | string
}

export interface MonitorWidget {
  id: string
  type: 'metric' | 'task_table' | 'event_stream' | 'error_list' | 'rule_timeline' | 'worker_status' | string
  title: string
  data_source: 'summary' | 'tasks' | 'events' | 'errors' | 'task_events' | 'workers' | string
  query?: Record<string, unknown>
  style?: Record<string, unknown>
  layout: Record<string, MonitorWidgetLayout>
  columns?: MonitorTableColumn[]
  options?: Record<string, unknown>
  visible?: { roles?: string[] }
}

export interface MonitorTemplate {
  id: string
  name: string
  version: string
  description?: string
  scope: 'user' | 'admin' | string
  refresh?: {
    mode?: 'websocket' | 'polling' | string
    fallback_interval_seconds?: number
  }
  permissions?: Record<string, unknown>
  filters: MonitorFilter[]
  layout: Record<string, unknown>
  widgets: MonitorWidget[]
}

export interface WorkflowMonitorSummary {
  running_count: number
  failed_today: number
  avg_running_progress: number
  stale_task_count: number
  warning_count_10m: number
  error_count_10m: number
  total: number
}

export interface WorkflowTaskSnapshot {
  id: string
  name: string
  flow_id: string
  user_id: string
  username?: string | null
  nickname?: string | null
  status: 'pending' | 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | string
  progress: number
  progress_percent: number
  progress_details?: string
  current_rule?: string
  current_job_id?: number | null
  last_event_at?: string | null
  last_error?: string
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface WorkflowEvent {
  schema_version?: string
  task_id: string
  flow_id?: string | null
  user_id?: string | null
  project_name?: string | null
  timestamp?: string | null
  timestamp_ns?: string | null
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical' | string
  source: string
  message: string
  caller?: string | null
  snakemake?: {
    rule?: string | null
    job_id?: number | null
    event_type?: string | null
    shell_command?: string | null
    progress_percent?: number | null
    progress_details?: string | null
  }
  runtime?: Record<string, unknown>
  raw?: Record<string, unknown>
}

export interface WorkflowOverviewResponse {
  summary: WorkflowMonitorSummary
  tasks: WorkflowTaskSnapshot[]
  events: WorkflowEvent[]
  errors: WorkflowEvent[]
}

export type WorkflowMonitorWsMessage =
  | { type: 'event'; event: WorkflowEvent }
  | { type: 'task_snapshot'; task: WorkflowTaskSnapshot }
  | { type: 'summary'; summary: WorkflowMonitorSummary }
  | { type: 'error'; detail: string }
  | { type: 'pong' }
