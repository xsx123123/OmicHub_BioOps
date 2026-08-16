/**
 * KEGG / GO 富集分析相关类型定义
 */

/** 物种下拉选项 */
export interface SpeciesOption {
  /** 物种唯一 ID */
  id: string
  /** 展示名称 */
  label: string
  /** KEGG 物种代码，如 hsa、ath */
  kegg_code: string
  /** OrgDB 包名，如 org.Hs.eg.db */
  org_db: string
  /** 基因 ID 类型，如 SYMBOL、TAIR */
  id_type: string
  /** 当前物种已配置的分析类型 */
  analysis_types: string[]
  /** 默认 p-value cutoff */
  default_p_value_cutoff: number
  /** 默认 q-value cutoff */
  default_q_value_cutoff: number
}

/** 单条富集结果 */
export interface EnrichmentRow {
  /** 通路 ID */
  id: string
  /** 通路描述 */
  description: string
  /** GeneRatio */
  gene_ratio: string
  /** pvalue */
  pvalue: number
  /** p.adjust */
  p_adjust: number
  /** q-value */
  q_value: number
  /** 富集基因数 */
  count: number
  /** 注释来源，例如 GO:BP、GO:MF、GO:CC 或 KEGG */
  source: string
}

/** 富集分析接口返回 */
export interface EnrichmentResult {
  /** 任务 ID */
  task_id: string
  /** 旧任务兼容字段；新页面依据 table_data 分别构建 GO / KEGG 图 */
  plotly_json?: Record<string, unknown>
  /** 结果表格 */
  table_data: EnrichmentRow[]
}

/** 富集 Celery 任务状态（完成后 result 才有值） */
export type EnrichmentTaskStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface EnrichmentTask {
  task_id: string
  status: EnrichmentTaskStatus
  progress: number
  message: string
  error_message?: string | null
  result?: EnrichmentResult | null
  project_name: string
  species_id: string
  gene_count: number
  created_at?: string | null
  finished_at?: string | null
}

export interface EnrichmentExample {
  id: string
  title: string
  species_id: string
  gene_count: number
  gene_text: string
  p_value_cutoff: number
  q_value_cutoff: number
  result: EnrichmentResult
}
