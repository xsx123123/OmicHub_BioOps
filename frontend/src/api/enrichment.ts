import apiClient from '@/api/client'
import type { EnrichmentExample, EnrichmentTask, SpeciesOption } from '@/types/enrichment'

/**
 * 获取 YAML 中 enabled=true 的物种列表
 */
export async function fetchSpeciesOptions(): Promise<SpeciesOption[]> {
  const { data } = await apiClient.get<{ data: SpeciesOption[] }>('/enrichment/species')
  return data.data
}

/** 获取 COP1/HY5 1576 基因与对应的真实 R 富集示例。 */
export async function fetchEnrichmentExample(): Promise<EnrichmentExample> {
  const { data } = await apiClient.get<EnrichmentExample>('/enrichment/examples/cop1-hy5-dependent')
  return data
}

/**
 * 提交富集分析任务
 */
export async function submitEnrichment(payload: FormData): Promise<EnrichmentTask> {
  const { data } = await apiClient.post<EnrichmentTask>('/enrichment/submit', payload, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
  return data
}

/** 查询已投递的富集 Celery 任务，完成时带回 Plotly 与表格结果。 */
export async function fetchEnrichmentTask(taskId: string): Promise<EnrichmentTask> {
  const { data } = await apiClient.get<EnrichmentTask>(`/enrichment/tasks/${taskId}`)
  return data
}

/** 获取当前登录用户最近的富集分析历史。 */
export async function fetchEnrichmentHistory(limit = 50): Promise<EnrichmentTask[]> {
  const { data } = await apiClient.get<{ data: EnrichmentTask[] }>('/enrichment/tasks', { params: { limit } })
  return data.data
}

/** 下载 R/clusterProfiler 容器生成的原始结果 CSV。 */
export async function downloadEnrichmentResult(task: EnrichmentTask): Promise<void> {
  const response = await apiClient.get<Blob>(`/enrichment/tasks/${task.task_id}/download`, { responseType: 'blob' })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const basicName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  const filename = encodedName ? decodeURIComponent(encodedName) : basicName || `${task.project_name || 'enrichment'}_result.csv`
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
