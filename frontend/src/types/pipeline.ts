export type PipelineType = 'rna_seq' | 'atac_seq'

export type PipelineTaskStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'

export interface PipelineResultMetrics {
  differential_gene_count?: number
  upregulated_count?: number
  downregulated_count?: number
  [key: string]: unknown
}

export interface PipelineArtifact {
  name: string
  path: string
  size: number
  type: string
}

export interface PipelineTask {
  taskId: string
  pipelineType: PipelineType
  status: PipelineTaskStatus
  progress: number
  resultUrl?: string
  reportUrl?: string
  error?: string
  metrics?: PipelineResultMetrics
  artifacts?: PipelineArtifact[]
  preparedParams?: Record<string, unknown>
  polling: boolean
}

export interface PipelineSubmitResult {
  task_id: string
  pipeline_type: PipelineType
  status: string
  progress?: number
  result_url?: string
  prepared_params?: Record<string, unknown>
}
