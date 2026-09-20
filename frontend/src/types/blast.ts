/**
 * BLAST 工具类型定义
 * 与后端 cygnusx/tools/blast/schema.py 对齐
 */

export type ProgramType = 'blastn' | 'blastp' | 'blastx' | 'tblastn' | 'tblastx'
export type DbType = 'nucl' | 'prot'
export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type BuildStatus = 'pending' | 'building' | 'ready' | 'failed' | 'deprecated'
export type ResultFormat = 'json' | 'xml' | 'text' | 'summary'

export interface BlastDatabase {
  id: string
  name: string
  db_key: string
  db_type: DbType
  source_species?: string
  source_version?: string
  version_group: string
  is_active: boolean
  file_path: string
  file_size_mb: number
  sequence_count: number
  build_status: BuildStatus
  is_public: boolean
  created_at: string
  updated_at?: string
}

export interface BlastHsp {
  query_from: number
  query_to: number
  hit_from: number
  hit_to: number
  identity_percent: number
  evalue: number
  bit_score: number
}

export interface BlastHspDetail {
  hsp_num: number
  bit_score: number
  evalue: number
  query_from: number
  query_to: number
  hit_from: number
  hit_to: number
  identity: number
  align_length: number
  mismatches: number
  gaps: number
  query_seq: string
  hit_seq: string
  midline: string
  identity_percent: number
}

export interface BlastHit {
  query_id: string
  subject_id: string
  identity: number
  align_length: number
  mismatches: number
  gap_opens: number
  q_start: number
  q_end: number
  s_start: number
  s_end: number
  evalue: number
  bit_score: number
  score?: number
  query_seq?: string
  subject_seq?: string
  midline?: string

  // 新增可视化字段
  hit_num: number
  hit_id: string
  hit_def: string
  hit_accession: string
  hit_len: number
  identity_percent: number
  query_coverage: number
  subject_coverage: number
  total_score: number
  best_hsp?: BlastHspDetail
  hsps: BlastHsp[]
}

export interface BlastStatistics {
  hit_count: number
  top_hit_identity?: number
  top_hit_evalue?: number
  db_name: string
  program: string
  query_title: string
}

export interface BlastResult {
  task_id: string
  status: TaskStatus
  hits: BlastHit[]
  statistics: BlastStatistics
  result_path?: string
  xml_url?: string
  json_url?: string
  text_url?: string
  query_len: number
  program: string
  db_name: string
  query_def: string
  db_display_name: string
  query_params: Record<string, unknown>
}

export interface BlastTask {
  task_id: string
  status: TaskStatus
  progress: number
  message: string
  error_message?: string
  result?: BlastResult
  submitted_at?: string
  started_at?: string
  completed_at?: string
  db_id?: string
  query_sequence?: string
  query_title?: string
  program?: ProgramType
  evalue?: number
  max_target_seqs?: number
  word_size?: number
  gapopen?: number
  gapextend?: number
  result_format?: ResultFormat
}

export interface BlastSubmitRequest {
  db_id: string
  project_name: string
  query_sequence?: string
  query_title: string
  program?: ProgramType
  evalue: number
  max_target_seqs: number
  word_size?: number
  gapopen?: number
  gapextend?: number
  result_format?: ResultFormat
}

export interface BlastTaskListItem {
  task_id: string
  /** 所属用户 ID（列表为当前用户视角，用于「所属用户」列展示） */
  user_id?: string
  /** 所属用户名（后端按 user_id 回填，缺失时前端降级展示 user_id） */
  username?: string
  /** 所属用户昵称（设置后优先于 username 展示） */
  nickname?: string | null
  db_id: string
  db_name: string
  program: string
  query_title?: string
  status: TaskStatus
  progress: number
  hit_count?: number
  top_hit_identity?: number
  top_hit_evalue?: number
  submitted_at?: string
  completed_at?: string
  error_message?: string
}

export interface BlastTaskListResponse {
  items: BlastTaskListItem[]
  total: number
  page: number
  page_size: number
}

export interface BlastBuildStatusResponse {
  db_id: string
  build_status: BuildStatus
  progress: number
  sequence_count: number
  file_size_mb: number
  build_log?: string
}

export interface BlastMethodsResponse {
  programs: Array<{ key: string; query_type: string; db_type: string }>
  db_types: string[]
  defaults: Record<string, unknown>
}
