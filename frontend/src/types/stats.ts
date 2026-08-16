/** 仪表板统计相关响应类型 */

export interface StatsOverview {
  /** 运行中任务数 */
  running: number
  /** 总任务数 */
  total: number
  /** 数据样本数（与「数据管理」登记的样本同源） */
  samples: number
}

export interface TrendPoint {
  /** 日期 MM/DD */
  date: string
  /** 当日任务数 */
  tasks: number
  /** 当日样本数 */
  samples: number
}

export interface GuideStep {
  number: number
  title: string
  done: boolean
}

export interface UserProgress {
  steps: GuideStep[]
  /** 当前应完成的步骤编号（全部完成则为 null） */
  current: number | null
}

/** 全平台各状态任务数：{ running: n, success: n, ... } */
export type AdminStatus = Record<string, number>

export interface FlowUsage {
  flow_id: string
  name: string
  count: number
}

export interface AdminUserStats {
  total_users: number
  active_users_7d: number
}

export interface FailedTask {
  id: string
  name: string
  flow_id: string
  user_id: string
  error_message: string
  created_at: string | null
}

/** 全局磁盘容量（data_root 所在挂载盘） */
export interface StorageGlobalUsage {
  /** 总容量（字节） */
  total: number
  /** 已用空间（字节） */
  used: number
  /** 剩余空间（字节） */
  free: number
  /** 已用百分比（0-100） */
  used_percent: number
}

/** 单个用户的空间占用 */
export interface UserStorageUsage {
  /** 用户 ID（users/ 下的目录名） */
  user_id: string
  /** 用户名（库中查不到时回退为目录名） */
  username: string
  /** 昵称（空则前端降级用 username） */
  nickname?: string | null
  /** 占用磁盘空间（字节） */
  size: number
  /** 占所有用户占用总和的百分比（0-100） */
  percent: number
}

/** 存储监控聚合响应 */
export interface StorageUsage {
  /** 本次统计的数据根目录 */
  data_root: string
  /** 全局磁盘容量 */
  global_usage: StorageGlobalUsage
  /** 占用最多的前 N 个用户（降序） */
  users: UserStorageUsage[]
  /** 扫描到的用户目录总数 */
  users_total: number
}

export interface StudioUsageSummary {
  sessions: number
  messages: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  sandbox_runs: number
  sandbox_successes: number
  sandbox_failures: number
  sandbox_success_rate: number
  sandbox_duration_ms: number
  long_tasks: number
  artifacts: number
}

export interface StudioUsageQuota {
  storage_used: number
  storage_quota: number
  storage_available: number
  storage_used_percent: number
}

export interface StudioUsageCookie {
  /** 饼干转换比例：每 1K tokens 消耗的饼干数 */
  rate_per_1k_tokens: number
  /** 本周期 token 折算的饼干消耗 */
  cost: number
}

export interface StudioUsageDay {
  date: string
  sessions: number
  messages: number
  total_tokens: number
  sandbox_runs: number
  sandbox_duration_ms: number
}

export interface StudioUsage {
  period_days: number
  from: string
  to: string
  summary: StudioUsageSummary
  quota: StudioUsageQuota
  cookie: StudioUsageCookie
  daily: StudioUsageDay[]
}

export interface AiTokenUsageRecord {
  time: string | null
  session_id: string
  title: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cookie_cost: number
}

export interface AiTokenUsageDay {
  date: string
  messages: number
  total_tokens: number
  cookie_cost: number
}

export interface AiTokenUsage {
  period_days: number
  rate_per_1k_tokens: number
  summary: {
    messages: number
    sessions: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
    cookie_cost: number
  }
  daily: AiTokenUsageDay[]
  records: AiTokenUsageRecord[]
}
