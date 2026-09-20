/**
 * 系统发育树工具类型定义
 * 与后端 cygnusx/tools/phylogenetic_tree/schema.py 对齐
 */

export type AlignmentTool = 'mafft' | 'clustalo' | 'muscle5' | 'prealigned'
export type TreeMethod = 'nj' | 'upgma' | 'fasttree' | 'iqtree' | 'mrbayes'
export type SubstitutionModel = string
export type BootstrapType = 'standard' | 'ultrafast'
export type TreeLayout = 'rectangular' | 'circular' | 'radial'
export type TaskStatus = 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED'
export type SequenceType = 'auto' | 'dna' | 'protein'

export interface TreeStatistics {
  sequence_count: number
  total_branches: number
  total_tree_length: number
  mean_branch_length: number
  tree_height: number
  min_bootstrap: number
  max_bootstrap: number
  avg_bootstrap: number
  has_bootstrap_support: boolean
}

export interface PhyloUploadResponse {
  file_id: string
  file_path: string
  filename: string
  format: string
  sequence_count?: number
  sequence_type?: string
  total_length?: number
  is_aligned?: boolean
}

export interface PhyloSubmitRequest {
  file_id: string
  project_name: string
  alignment_tool: AlignmentTool
  alignment_mode: string
  tree_method: TreeMethod
  substitution_model: SubstitutionModel
  bootstrap_enabled: boolean
  bootstrap_type: BootstrapType
  bootstrap_replicates: number
  sequence_type: SequenceType
  advanced_params: string
}

export interface PhyloTaskResponse {
  task_id: string
  status: TaskStatus
  phase?: string
  progress: number
  message: string
  result?: PhyloResult
}

export interface PhyloResult {
  task_id: string
  status: string
  output_files: Record<string, string>
  statistics: TreeStatistics
  execution_time: number
  phases_completed: string[]
}

export interface PhyloMethodsResponse {
  alignment_tools: PhyloMethodOption[]
  tree_methods: PhyloMethodOption[]
  substitution_models: Record<string, string[]>
  bootstrap_types: PhyloMethodOption[]
  presets: Record<string, Partial<PhyloSubmitRequest>>
}

export interface PhyloMethodOption {
  key: string
  label: string
  description?: string
  supports_bootstrap?: boolean
}

export interface PhyloValidateResponse {
  valid: boolean
  message?: string
}

export interface VizConfig {
  layout: TreeLayout
  isRooted: boolean
  showLabels: boolean
  showBootstrap: boolean
  showScaleBar: boolean
  alignTips: boolean
  branchWidth: number
  fontSize: number
}

export interface SequenceRow {
  id: string
  length: number
}
