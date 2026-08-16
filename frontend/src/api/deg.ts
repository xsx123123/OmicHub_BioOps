import apiClient from '@/api/client'
import type { DegDefaults, DegTask } from '@/types/deg'

/** 获取 DEG 工具表单默认值（外置 YAML 热重载）。 */
export async function fetchDegDefaults(): Promise<DegDefaults> {
  const { data } = await apiClient.get<DegDefaults>('/deg/defaults')
  return data
}

/** 获取示例输入文本（counts/metadata/pairs/annotation）。 */
export async function fetchDegExamples(): Promise<Record<string, string>> {
  const { data } = await apiClient.get<Record<string, string>>('/deg/examples')
  return data
}

/** 提交 DEG 分析任务（multipart：三个必选文件 + 可选注释 + 参数）。 */
export async function submitDeg(payload: FormData): Promise<DegTask> {
  const { data } = await apiClient.post<DegTask>('/deg/submit', payload, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
  return data
}

/** 查询 DEG Celery 任务，完成时带回统计表 / Top 基因 / 产物名单。 */
export async function fetchDegTask(taskId: string): Promise<DegTask> {
  const { data } = await apiClient.get<DegTask>(`/deg/tasks/${taskId}`)
  return data
}

/** 获取当前登录用户最近的 DEG 分析历史。 */
export async function fetchDegHistory(limit = 50): Promise<DegTask[]> {
  const { data } = await apiClient.get<{ data: DegTask[] }>('/deg/tasks', { params: { limit } })
  return data.data
}

/**
 * 下载结果产物（CSV/PNG/PDF/日志）。
 * 走鉴权 apiClient 拿 blob，再触发浏览器下载。
 */
export async function downloadDegArtifact(task: DegTask, filename: string): Promise<void> {
  const response = await apiClient.get<Blob>(
    `/deg/tasks/${task.task_id}/artifacts/${encodeURIComponent(filename)}`,
    { responseType: 'blob' },
  )
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/** 获取产物 Blob URL（用于 <img> 展示 PNG；浏览器原生 src 无法带鉴权头）。 */
export async function fetchDegArtifactUrl(taskId: string, filename: string): Promise<string> {
  const response = await apiClient.get<Blob>(
    `/deg/tasks/${taskId}/artifacts/${encodeURIComponent(filename)}`,
    { responseType: 'blob' },
  )
  return URL.createObjectURL(response.data)
}
