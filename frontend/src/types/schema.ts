export type ParameterType =
  | 'string'
  | 'int'
  | 'float'
  | 'select'
  | 'file'
  | 'boolean'
  | 'group'
  | 'section'

export type ConditionOperator =
  | 'eq'
  | 'ne'
  | 'gt'
  | 'lt'
  | 'gte'
  | 'lte'
  | 'in'
  | 'not_in'
  | 'contains'
  | 'exists'
  | 'regex'

export interface ConditionRule {
  field?: string
  operator?: ConditionOperator
  value?: unknown
  and_rules?: ConditionRule[]
  or_rules?: ConditionRule[]
}

export interface SelectOption {
  label: string
  value: unknown
  help_text?: string
}

export interface StringConfig {
  min_length?: number
  max_length?: number
  regex_pattern?: string
  multiline?: boolean
  rows?: number
}

export interface NumberConfig {
  min?: number
  max?: number
  step?: number
  use_slider?: boolean
  slider_marks?: Record<string, string>
  precision?: number
}

export interface SelectConfig {
  options: SelectOption[]
  multi?: boolean
  allow_clear?: boolean
  searchable?: boolean
}

export interface FileConfig {
  accept?: string
  max_size?: number
  multiple?: boolean
  directory?: boolean
  show_file_list?: boolean
}

export interface GroupConfig {
  min_items?: number
  max_items?: number
  item_label?: string
  add_button_text?: string
  parameters: Parameter[]
}

export interface SectionConfig {
  title?: string
  default_expanded?: boolean
  description?: string
  parameters: Parameter[]
}

export interface ParameterUIHint {
  group?: string | null
  order?: number | null
  span?: 1 | 2 | null
  widget?: string | null
  placeholder?: string | null
  subgroup?: string | null
  exclusive?: boolean
  show_when?: Record<string, unknown> | null
  linked_group_column?: string | null
}

export interface Parameter {
  name: string
  label: string
  type: ParameterType
  required?: boolean
  default?: unknown
  help_text?: string
  placeholder?: string
  order?: number
  condition?: ConditionRule
  string_config?: StringConfig
  number_config?: NumberConfig
  select_config?: SelectConfig
  file_config?: FileConfig
  group_config?: GroupConfig
  section_config?: SectionConfig
  ui?: ParameterUIHint | null
}

export interface SampleSheetColumn {
  name: string
  required?: boolean
  type?: 'string' | 'int' | 'float' | 'boolean'
  description?: string
  example?: string | null
  unique?: boolean
  allowed_values?: string[] | null
}

export interface ValidationRule {
  type: 'unique_combination' | 'mutual_exclusive' | 'regex'
  columns: string[]
  message?: string
  regex_pattern?: string | null
}

export interface SampleSheetUIConfig {
  import?: string[]
  group_column?: string | null
}

export interface SampleSheetConfig {
  columns: SampleSheetColumn[]
  validation_rules?: ValidationRule[]
  ui?: SampleSheetUIConfig | null
}

export interface ExecutionConfig {
  engine: 'snakemake' | 'nextflow'
  snakefile: string
  conda_env?: string | null
  default_resources?: {
    cores?: number
    memory?: string
    time?: string
  }
  sample_sheet_format?: 'csv' | 'excel' | 'json'
  extra_args?: string[]
}

export interface FlowGroupDefinition {
  id: string
  title: string
  desc?: string
  collapsible?: boolean
  collapsed?: boolean
}

export interface FlowMeta {
  id: string
  name: string
  category: string
  version: string
  description: string
  author?: string | null
  tags?: string[]
  icon?: string | null
  color?: string | null
  docs_url?: string | null
  github_url?: string | null
}

export interface FlowConfig {
  meta: FlowMeta
  parameters: Parameter[]
  execution: ExecutionConfig
  groups?: FlowGroupDefinition[] | null
  sample_sheet?: SampleSheetConfig | null
}

export type FormValues = Record<string, unknown>
