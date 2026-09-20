/**
 * DEG 差异表达分析工具类型定义（与后端 src/cygnusx/tools/deg/schema.py 对齐）
 */

/** 分析方法：auto 按重复数自动路由 DESeq2 / edgeR */
export type DegMethod = 'auto' | 'deseq2' | 'edger'

/** 实际执行的引擎 */
export type DegEngine = 'deseq2' | 'edger'

/** GET /deg/defaults 返回的表单默认值 */
export interface DegDefaults {
  method: DegMethod
  lfc: number
  pval: number
  bcv: number
  min_replicates: number
  max_counts_file_size_mb: number
  max_metadata_file_size_mb: number
  max_pairs_file_size_mb: number
  max_annotation_file_size_mb: number
  min_samples: number
  max_samples: number
  max_contrasts: number
  max_genes: number
}

/** 单个比较对的统计汇总行 */
export interface DegContrastStat {
  contrast: string
  control: string
  treat: string
  /** edgeR 引擎记录 edgeR-QLF / edgeR-NoRep；DESeq2 为空 */
  method: string
  dispersion_assumption: string
  n_control: number
  n_treat: number
  up_regulated: number
  down_regulated: number
  total_deg: number
}

/** 差异结果表的一行（Top 基因，全量请下载 CSV） */
export interface DegGeneRow {
  ensembl: string
  symbol: string
  log2_fc: number
  pvalue: number
  padj: number | null
  /** DESeq2 输出 */
  base_mean: number | null
  /** edgeR 输出 */
  log_cpm: number | null
}

/** 单个比较对的结果 */
export interface DegContrastResult {
  name: string
  stat: DegContrastStat
  top_genes: DegGeneRow[]
  /** 全量结果行数 */
  total_genes: number
  deg_csv: string
  volcano_png: string
  volcano_labeled_png: string
}

/** 完成后的分析结果 */
export interface DegResult {
  task_id: string
  engine: DegEngine
  no_replicate_contrasts: string[]
  statistics: DegContrastStat[]
  contrasts: DegContrastResult[]
  pca_png: string
  /** 结果目录可下载文件全名单 */
  artifacts: string[]
  log_file: string
}

export type DegTaskStatus = 'queued' | 'running' | 'completed' | 'failed'

/** DEG 任务状态（完成后 result 才有值） */
export interface DegTask {
  task_id: string
  status: DegTaskStatus
  progress: number
  message: string
  error_message?: string | null
  result?: DegResult | null
  project_name: string
  method_requested: DegMethod
  engine_resolved?: DegEngine | null
  no_replicate_contrasts: string[]
  sample_count: number
  contrast_count: number
  created_at?: string | null
  finished_at?: string | null
}
