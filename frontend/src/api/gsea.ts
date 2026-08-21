import apiClient from '@/api/client'

export interface GseaTask {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  error_message?: string | null
  top_terms: Array<{ id: string; description: string; nes: number; p_adjust: number; qvalue?: number | null }>
  running_score: Array<{ rank: number; score: number }>
  result_download_url?: string | null
}

export async function downloadGseaResult(taskId: string): Promise<void> {
  const response = await apiClient.get<Blob>(`/gsea/tasks/${taskId}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = 'gsea_result.csv'
  link.click()
  URL.revokeObjectURL(url)
}

export async function submitGsea(payload: FormData): Promise<GseaTask> {
  const { data } = await apiClient.post<GseaTask>('/gsea/submit', payload, { headers: { 'Content-Type': 'multipart/form-data' } })
  return data
}

export async function fetchGseaTask(taskId: string): Promise<GseaTask> {
  const { data } = await apiClient.get<GseaTask>(`/gsea/tasks/${taskId}`)
  return data
}
