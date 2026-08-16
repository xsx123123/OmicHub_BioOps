import apiClient from '@/api/client'
import type {
  PhyloMethodsResponse,
  PhyloResult,
  PhyloSubmitRequest,
  PhyloTaskResponse,
  PhyloUploadResponse,
  PhyloValidateResponse,
} from '@/types/phylo'

export async function uploadSequenceFile(file: File): Promise<PhyloUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await apiClient.post<PhyloUploadResponse>('/phylogenetic-tree/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function submitTreeBuild(request: PhyloSubmitRequest): Promise<PhyloTaskResponse> {
  const { data } = await apiClient.post<PhyloTaskResponse>('/phylogenetic-tree/submit', request)
  return data
}

export async function getTaskStatus(taskId: string): Promise<PhyloTaskResponse> {
  const { data } = await apiClient.get<PhyloTaskResponse>(`/phylogenetic-tree/tasks/${taskId}/status`)
  return data
}

export async function getTaskResult(taskId: string): Promise<PhyloResult> {
  const { data } = await apiClient.get<PhyloResult>(`/phylogenetic-tree/tasks/${taskId}/result`)
  return data
}

export async function cancelTask(taskId: string): Promise<PhyloTaskResponse> {
  const { data } = await apiClient.delete<PhyloTaskResponse>(`/phylogenetic-tree/tasks/${taskId}/cancel`)
  return data
}

export async function downloadTreeResult(taskId: string, format: string): Promise<string> {
  const { data } = await apiClient.get<string>(`/phylogenetic-tree/download/${taskId}/${format}`, {
    responseType: 'text',
  })
  return data
}

export async function fetchPhyloMethods(): Promise<PhyloMethodsResponse> {
  const { data } = await apiClient.get<PhyloMethodsResponse>('/phylogenetic-tree/methods')
  return data
}

export async function validatePhyloParams(
  request: Omit<PhyloSubmitRequest, 'file_id' | 'project_name' | 'sequence_type' | 'advanced_params'>,
): Promise<PhyloValidateResponse> {
  const { data } = await apiClient.post<PhyloValidateResponse>('/phylogenetic-tree/validate', request)
  return data
}

export async function fetchExampleNewick(): Promise<string> {
  // 使用仓库内置示例 Newick，避免启动时依赖后端
  const { data } = await apiClient.get<string>('/docs-static/26.7.11/Kimi_Agent_系统发育树工具架构/example.nwk', {
    responseType: 'text',
  })
  return data
}
