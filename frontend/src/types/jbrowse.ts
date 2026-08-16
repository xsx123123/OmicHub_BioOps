/** JBrowse 2 前端类型 —— 与后端 application/schemas/jbrowse.py 对齐。 */

export interface AssemblyDataFileDTO {
  path: string
  index_path?: string | null
  db_path?: string | null
  format?: string | null
  build_required: boolean
  build_tool?: string | null
  build_status: string
  size?: string | null
}

export interface AssemblyDTO {
  id: string
  name: string
  species?: string | null
  common_name?: string | null
  taxonomy_id?: string | null
  version_id?: string | null
  version_name?: string | null
  assembly_name?: string | null
  category?: string | null
  icon?: string | null
  is_default: boolean
  status: string
  release_date?: string | null
  description?: string | null
  stats: Record<string, unknown>
  data_files: Record<string, AssemblyDataFileDTO>
  fasta_exists: boolean
  fai_exists: boolean
  aliases: string[]
}

export interface AssemblyListResponse {
  assemblies: AssemblyDTO[]
}

export interface PresetTrackDTO {
  name: string
  file: string
  type: string
  color?: string | null
  file_exists: boolean
}

export interface PresetTracksResponse {
  assembly_id: string
  tracks: PresetTrackDTO[]
}

export interface ScannedFileDTO {
  path: string
  name: string
  type: string
  size: number
  size_human: string
  modified: string
  indexed: boolean
  index_file?: string | null
  can_load: boolean
  /** 前端追加：是否被选中加入轨道 */
  selected?: boolean
}

export interface ScanResponse {
  user_id: string
  scan_time: string
  total_files: number
  indexed_count: number
  files: ScannedFileDTO[]
}

export interface UploadResultDTO {
  filename: string
  saved_path: string
  size: number
  size_human: string
  user_id: string
  assembly_id?: string | null
  index_task_id?: string | null
  index_status?: string | null
}

export interface BatchUploadItemDTO {
  filename: string
  saved_path?: string | null
  success: boolean
  index_task_id?: string | null
  error?: string | null
}

export interface BatchUploadResponse {
  total: number
  success: number
  failed: number
  results: BatchUploadItemDTO[]
}

export interface IndexStatusDTO {
  file: string
  index_status: {
    indexed: boolean
    reason?: string
    index_file?: string | null
    expected_index?: string
  }
}

export interface IndexTaskSubmitDTO {
  message: string
  task_id: string
  file: string
  status: string
}

export interface IndexTaskStatusDTO {
  task_id: string
  status: string
  ready: boolean
  successful?: boolean | null
  result?: unknown
  error?: string | null
}

export interface ConfigReloadResponse {
  message: string
  assemblies_count: number
  preset_tracks_count: number
  auto_scan_enabled: boolean
}

/** 已选轨道（前端展示用） */
export interface SelectedTrack {
  path: string
  name: string
  indexed: boolean
}
