/** JBrowse 2 API —— 参考基因组 / 配置 / 扫描 / 上传 / 索引。
 *
 * 所有调用经 apiClient 自动附加 JWT；用户身份由后端 JWT 解析，前端不需传 user_id。
 * 配置 JSON 由前端取回后写入 blob URL 交给 JBrowse 2 iframe（避免 iframe fetch 带 JWT）。
 */
import apiClient from './client'
import type {
  AssemblyDTO,
  AssemblyListResponse,
  BatchUploadResponse,
  ConfigReloadResponse,
  IndexStatusDTO,
  IndexTaskStatusDTO,
  IndexTaskSubmitDTO,
  PresetTracksResponse,
  ScanResponse,
  UploadResultDTO,
} from '@/types/jbrowse'

export const jbrowseApi = {
  /** 列出所有参考基因组 */
  listAssemblies(): Promise<AssemblyListResponse> {
    return apiClient.get('/jbrowse/assemblies').then((r) => r.data)
  },

  /** 获取参考基因组详情 */
  getAssemblyDetail(assemblyId: string): Promise<AssemblyDTO> {
    return apiClient.get(`/jbrowse/assemblies/${assemblyId}`).then((r) => r.data)
  },

  /** 生成 JBrowse 2 浏览器配置 JSON（前端拿到后写入 blob URL 交给 iframe） */
  generateConfig(params: {
    assembly: string
    tracks?: string[]
    region?: string
  }): Promise<Record<string, unknown>> {
    return apiClient
      .get('/jbrowse/config', { params, paramsSerializer: { indexes: null } })
      .then((r) => r.data)
  },

  /** 扫描当前用户目录 */
  scan(): Promise<ScanResponse> {
    return apiClient.get('/jbrowse/scan').then((r) => r.data)
  },

  /** 上传单个轨道文件 */
  upload(
    file: File,
    opts: { assemblyId?: string; autoIndex?: boolean },
    onProgress?: (percent: number) => void,
  ): Promise<UploadResultDTO> {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post('/jbrowse/upload', form, {
        params: {
          assembly_id: opts.assemblyId || undefined,
          auto_index: opts.autoIndex ?? true,
        },
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (onProgress && e.total) {
            onProgress(Math.round((e.loaded * 100) / e.total))
          }
        },
        timeout: 0, // 大文件上传不超时
      })
      .then((r) => r.data)
  },

  /** 批量上传 */
  uploadBatch(
    files: File[],
    opts: { autoIndex?: boolean },
  ): Promise<BatchUploadResponse> {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return apiClient
      .post('/jbrowse/upload/batch', form, {
        params: { auto_index: opts.autoIndex ?? true },
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 0,
      })
      .then((r) => r.data)
  },

  /** 检查文件索引状态 */
  checkIndex(filePath: string): Promise<IndexStatusDTO> {
    return apiClient
      .get('/jbrowse/index/check', { params: { file_path: filePath } })
      .then((r) => r.data)
  },

  /** 创建索引（异步任务） */
  createIndex(filePath: string): Promise<IndexTaskSubmitDTO> {
    return apiClient
      .post('/jbrowse/index/create', null, { params: { file_path: filePath } })
      .then((r) => r.data)
  },

  /** 查询索引任务状态 */
  getIndexStatus(taskId: string): Promise<IndexTaskStatusDTO> {
    return apiClient.get(`/jbrowse/index/status/${taskId}`).then((r) => r.data)
  },

  /** 获取预设轨道 */
  listPresetTracks(assemblyId: string): Promise<PresetTracksResponse> {
    return apiClient.get(`/jbrowse/preset-tracks/${assemblyId}`).then((r) => r.data)
  },

  /** 热重载 YAML 配置（管理员） */
  reloadConfig(): Promise<ConfigReloadResponse> {
    return apiClient.post('/jbrowse/config/reload').then((r) => r.data)
  },
}
