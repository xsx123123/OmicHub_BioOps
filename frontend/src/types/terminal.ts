export type TerminalSessionStatus = 'creating' | 'running' | 'idle' | 'stopping' | 'stopped' | 'error'

export interface TerminalResources {
  memory_mb: number
  cpu_cores: number
  pid_limit: number
}

export interface TerminalRuntimeResources {
  memory_mb: number
  cpu_cores: number
  pid_limit: number
  tmpfs_size_mb: number
}

export interface TerminalRuntimeConfig {
  enabled: boolean
  default_resources: TerminalRuntimeResources
  max_resources: TerminalRuntimeResources
}

export interface TerminalImage {
  id: string
  name: string
  description: string
  image: string
  tags: string[]
  icon: string
  resources: {
    memory_mb: number
    cpu_cores: number
    pid_limit?: number
  }
  env: Array<{ name: string; value: string }>
  enabled: boolean
}

export interface TerminalSession {
  id: string
  user_id: string
  session_id: string
  status: TerminalSessionStatus
  host_port: number | null
  ws_url: string | null
  image_id: string | null
  image_name: string | null
  last_activity: string
  created_at: string
  expires_at: string | null
  resources?: TerminalResources
}

export interface CreateTerminalRequest {
  image_id?: string
  image_tag?: string
  resources?: {
    memory_mb?: number
    cpu_cores?: number
    pid_limit?: number
  }
}
