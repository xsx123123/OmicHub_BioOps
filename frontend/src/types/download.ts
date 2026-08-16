/** 数据下载相关类型 */

/**
 * 高级选项（对应 EBIDownload CLI 的 Filters / Cleanup 能力）
 * - 四个正则数组：filter-sample / filter-run / exclude-sample / exclude-run
 * - 两个无参 flag：cleanup-sra / pe-only
 */
export interface AdvancedDownloadOptions {
  /** --filter-sample 包含规则（正则），仅保留匹配的 sample */
  filter_sample: string[]
  /** --filter-run 包含规则（正则），仅保留匹配的 run */
  filter_run: string[]
  /** --exclude-sample 排除规则（正则），剔除匹配的 sample */
  exclude_sample: string[]
  /** --exclude-run 排除规则（正则），剔除匹配的 run */
  exclude_run: string[]
  /** --cleanup-sra 转换 FASTQ 后自动删除中间 .sra 文件（默认 true，节省磁盘） */
  cleanup_sra: boolean
  /** --pe-only 仅下载双端数据（默认 false） */
  pe_only: boolean
}

/** 高级选项默认值 */
export function createDefaultAdvancedOptions(): AdvancedDownloadOptions {
  return {
    filter_sample: [],
    filter_run: [],
    exclude_sample: [],
    exclude_run: [],
    cleanup_sra: true,
    pe_only: false,
  }
}

export interface DownloadRequest {
  source?: 'sra' | 'cloud_storage' | 'direct_link'
  accession?: string
  download_method?: 'aws' | 'aspera' | 'ftp'
  multithreads?: number
  aws_threads?: number
  cloud_provider?: 'aliyun' | 'volc' | 'huawei'
  object_uri?: string
  links?: string[]
  download_threads?: number
  overwrite_policy?: 'auto_rename' | 'overwrite' | 'skip'
  recursive?: boolean
  target_directory?: string
  /** 高级选项；后端暂未消费，预留字段，便于后续 CLI 透传 */
  advanced?: AdvancedDownloadOptions
  /** 模拟下载，不实际下载文件（测试用，仅 SRA 下载支持） */
  dry_run?: boolean
}

/** 单阶段进度 */
export interface StageProgress {
  bytes_done: number
  bytes_total: number
  weight: number
  percent: number
}

/** 单个 run（SRR）的三阶段进度 */
export interface RunProgress {
  run_id: string
  stage: 'pending' | 'downloading' | 'extracting' | 'compressing' | 'completed' | 'failed'
  overall_percent: number
  download: StageProgress
  extraction: StageProgress
  compression: StageProgress
}

/** 下载进度 API 响应 */
export interface DownloadProgressResponse {
  task_id: string
  runs: Record<string, RunProgress>
  overall_percent: number
  source: 'progress_api' | 'unavailable'
}
