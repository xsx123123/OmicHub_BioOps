import apiClient from '@/api/client'
import type {
  BlastBuildStatusResponse,
  BlastDatabase,
  BlastMethodsResponse,
  BlastResult,
  BlastSubmitRequest,
  BlastTask,
  BlastTaskListResponse,
} from '@/types/blast'

export interface BlastDatabaseCreateRequest {
  name: string
  db_key: string
  db_type: 'nucl' | 'prot'
  source_species?: string
  source_version?: string
  version_group?: string
  is_public?: boolean
}

export async function fetchBlastDatabases(dbType?: string): Promise<BlastDatabase[]> {
  const { data } = await apiClient.get<BlastDatabase[]>('/blast/databases', {
    params: dbType ? { db_type: dbType } : undefined,
  })
  return data
}

export async function fetchBlastMethods(): Promise<BlastMethodsResponse> {
  const { data } = await apiClient.get<BlastMethodsResponse>('/blast/methods')
  return data
}

export async function submitBlastTask(request: BlastSubmitRequest): Promise<BlastTask> {
  const { data } = await apiClient.post<BlastTask>('/blast/submit', request)
  return data
}

export async function fetchBlastTaskStatus(taskId: string): Promise<BlastTask> {
  const { data } = await apiClient.get<BlastTask>(`/blast/tasks/${taskId}`)
  return data
}

export async function fetchBlastResult(taskId: string, format = 'json'): Promise<BlastResult> {
  const { data } = await apiClient.get<BlastResult>(`/blast/results/${taskId}`, {
    params: { format },
  })
  return data
}

export interface BlastTaskEvent {
  task_id: string
  status: BlastTask['status']
  progress: number
  message: string
  error_message?: string
  timestamp?: string
}

export async function streamBlastTaskEvents(
  taskId: string,
  onEvent: (event: BlastTaskEvent) => void | Promise<void>,
  signal: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(`/api/v1/blast/tasks/${taskId}/events`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`SSE connection failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (data) await onEvent(JSON.parse(data) as BlastTaskEvent)
    }
  }
}

export async function cancelBlastTask(taskId: string): Promise<BlastTask> {
  const { data } = await apiClient.post<BlastTask>(`/blast/tasks/${taskId}/cancel`)
  return data
}

export async function fetchBlastTasks(
  status?: string,
  page = 1,
  pageSize = 20,
  search?: string,
): Promise<BlastTaskListResponse> {
  const { data } = await apiClient.get<BlastTaskListResponse>('/blast/tasks', {
    params: { status, search, page, page_size: pageSize },
  })
  return data
}

export function getBlastDownloadUrl(taskId: string, format: 'xml' | 'json' | 'text'): string {
  return `/blast/download/${taskId}/${format}`
}

export async function downloadBlastResult(
  taskId: string,
  format: 'xml' | 'json' | 'text',
  filename?: string,
): Promise<void> {
  const response = await apiClient.get(getBlastDownloadUrl(taskId, format), {
    responseType: 'blob',
  })
  const blob = new Blob([response.data], {
    type: format === 'xml' ? 'application/xml' : format === 'json' ? 'application/json' : 'text/plain',
  })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || `${taskId}.${format}`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

// Admin APIs
export async function fetchAdminBlastDatabases(): Promise<BlastDatabase[]> {
  const { data } = await apiClient.get<BlastDatabase[]>('/blast/admin/databases')
  return data
}

export interface BlastDatabaseUploadInitResponse {
  upload_id: string
  chunk_size_bytes: number
  total_chunks: number
}

const CHUNKED_UPLOAD_THRESHOLD = 32 * 1024 * 1024

export async function createBlastDatabase(
  request: BlastDatabaseCreateRequest,
  fastaFile: File,
  onUploadProgress?: (percent: number) => void,
): Promise<BlastDatabase> {
  if (fastaFile.size > CHUNKED_UPLOAD_THRESHOLD) {
    const { data: upload } = await apiClient.post<BlastDatabaseUploadInitResponse>(
      '/blast/admin/database-uploads',
      {
        ...request,
        filename: fastaFile.name,
        total_size: fastaFile.size,
      },
    )

    for (let chunkIndex = 0; chunkIndex < upload.total_chunks; chunkIndex += 1) {
      const start = chunkIndex * upload.chunk_size_bytes
      const end = Math.min(start + upload.chunk_size_bytes, fastaFile.size)
      const formData = new FormData()
      formData.append('chunk', fastaFile.slice(start, end), `${fastaFile.name}.part-${chunkIndex}`)
      await apiClient.put(
        `/blast/admin/database-uploads/${upload.upload_id}/chunks/${chunkIndex}`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          onUploadProgress: (event) => {
            if (!onUploadProgress) return
            const chunkFraction = event.total ? event.loaded / event.total : 0
            onUploadProgress(
              Math.min(99, Math.round(((chunkIndex + chunkFraction) / upload.total_chunks) * 100)),
            )
          },
        },
      )
    }

    const { data } = await apiClient.post<BlastDatabase>(
      `/blast/admin/database-uploads/${upload.upload_id}/complete`,
    )
    onUploadProgress?.(100)
    return data
  }

  const formData = new FormData()
  formData.append('name', request.name)
  formData.append('db_key', request.db_key)
  formData.append('db_type', request.db_type)
  if (request.source_species) formData.append('source_species', request.source_species)
  if (request.source_version) formData.append('source_version', request.source_version)
  if (request.version_group) formData.append('version_group', request.version_group)
  formData.append('is_public', String(request.is_public !== false))
  formData.append('fasta_file', fastaFile)
  const { data } = await apiClient.post<BlastDatabase>('/blast/admin/databases', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onUploadProgress
      ? (progressEvent) => {
          const total = progressEvent.total || progressEvent.event?.target?.response?.length || 0
          if (total > 0) {
            onUploadProgress(Math.round((progressEvent.loaded * 100) / total))
          }
        }
      : undefined,
  })
  return data
}


export async function fetchBlastDatabaseBuildStatus(dbId: string): Promise<BlastBuildStatusResponse> {
  const { data } = await apiClient.get<BlastBuildStatusResponse>(`/blast/admin/databases/${dbId}/build-status`)
  return data
}

export async function rebuildBlastDatabase(dbId: string): Promise<BlastBuildStatusResponse> {
  const { data } = await apiClient.post<BlastBuildStatusResponse>(`/blast/admin/databases/${dbId}/rebuild`)
  return data
}

export async function activateBlastDatabase(dbId: string): Promise<BlastDatabase> {
  const { data } = await apiClient.post<BlastDatabase>(`/blast/admin/databases/${dbId}/activate`)
  return data
}

export async function deleteBlastDatabase(dbId: string, hardDelete = false): Promise<{ db_id: string; deleted: boolean }> {
  const { data } = await apiClient.delete(`/blast/admin/databases/${dbId}`, {
    params: { hard_delete: hardDelete },
  })
  return data
}

export async function syncBlastDatabasesFromYaml(): Promise<BlastDatabase[]> {
  const { data } = await apiClient.post<BlastDatabase[]>('/blast/admin/databases/sync-from-yaml')
  return data
}

export async function fetchAdminBlastTasks(
  status?: string,
  userId?: string,
  page = 1,
  pageSize = 50,
): Promise<BlastTaskListResponse> {
  const { data } = await apiClient.get<BlastTaskListResponse>('/blast/admin/tasks', {
    params: { status, user_id: userId, page, page_size: pageSize },
  })
  return data
}

export interface BlastStorageStats {
  total_tasks: number
  completed_tasks: number
  cleaned_tasks: number
  storage_mb: number
  result_dir: string
}

export async function fetchBlastStorageStats(): Promise<BlastStorageStats> {
  const { data } = await apiClient.get<BlastStorageStats>('/blast/admin/storage-stats')
  return data
}

export async function cleanupOldBlastTasks(days = 7): Promise<{ message: string; cutoff_date: string; deleted_count: number }> {
  const { data } = await apiClient.post('/blast/admin/cleanup/old', null, {
    params: { days },
  })
  return data
}

export async function cleanupAllBlastTasks(): Promise<{ message: string; deleted_count: number }> {
  const { data } = await apiClient.post('/blast/admin/cleanup/all', null, {
    params: { confirm: true },
  })
  return data
}
