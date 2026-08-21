import apiClient from '@/api/client'

export interface SyntenyTask {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  error_message?: string | null
  block_count: number
  max_block_size: number
  chromosome_pairs: string[]
  blocks: Array<{ block_id: string; chromosome_a: string; chromosome_b: string; gene_pairs: number }>
  points: Array<{ query_gene: string; subject_gene: string; chromosome_a: string; chromosome_b: string; x: number; y: number }>
  result_download_url?: string | null
}

export async function downloadSyntenyResult(taskId: string): Promise<void> {
  const response = await apiClient.get<Blob>(`/synteny/tasks/${taskId}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = 'synteny_result.json'
  link.click()
  URL.revokeObjectURL(url)
}

export async function submitSynteny(payload: FormData): Promise<SyntenyTask> {
  const { data } = await apiClient.post<SyntenyTask>('/synteny/submit', payload, { headers: { 'Content-Type': 'multipart/form-data' } })
  return data
}

export async function fetchSyntenyTask(taskId: string): Promise<SyntenyTask> {
  const { data } = await apiClient.get<SyntenyTask>(`/synteny/tasks/${taskId}`)
  return data
}
