/**
 * 预签名 URL 直传（cloud / S3 模式大文件上传）。
 *
 * 流程：
 *   1. 向后端申请预创建记录 + 直传 URL
 *   2. 客户端直传对象存储（不经过应用服务器）
 *   3. 通知后端确认元数据并激活记录
 *
 * 该 composable 与分块上传互补：本地模式后端会返回 400，调用方应回退到分块上传。
 */
import axios from 'axios'
import apiClient from '@/api/client'
import type { UploadMergeResponse } from '@/types'

export interface PresignedUploadInitResponse {
  upload_url: string
  file_id: string
  storage_path: string
}

export interface StorageInfo {
  deployment_mode: 'local' | 'cloud'
  storage_type: 'local' | 's3'
  sandbox_mount_strategy: 'bind_mount' | 'scratch_volume'
  scratch_volume_enabled: boolean
  presigned_url_enabled: boolean
  product_recycle_policy: 'keep' | 'archive' | 'delete'
  data_materialization_enabled: boolean
  presigned_upload_threshold_bytes: number
}

let storageInfoCache: StorageInfo | null = null
let storageInfoPromise: Promise<StorageInfo> | null = null

export async function getStorageInfo(): Promise<StorageInfo> {
  if (storageInfoCache) return storageInfoCache
  if (storageInfoPromise) return storageInfoPromise

  storageInfoPromise = apiClient
    .get<StorageInfo>('/files/storage-info')
    .then((resp) => {
      const info = resp.data as StorageInfo
      storageInfoCache = info
      return info
    })
    .catch((): StorageInfo => {
      // 接口不可用时保守按本地模式处理，避免阻断上传
      return {
        deployment_mode: 'local',
        storage_type: 'local',
        sandbox_mount_strategy: 'bind_mount',
        scratch_volume_enabled: false,
        presigned_url_enabled: false,
        product_recycle_policy: 'keep',
        data_materialization_enabled: false,
        presigned_upload_threshold_bytes: 100 * 1024 * 1024,
      }
    })
  return storageInfoPromise
}

export function clearStorageInfoCache(): void {
  storageInfoCache = null
  storageInfoPromise = null
}

export interface PresignedUploadOptions {
  directory?: string
  fileType?: string
  onProgress?: (percent: number) => void
}

/**
 * 使用预签名 URL 上传单个文件。
 * @returns 与分块上传 merge 后等价的响应结构
 */
export async function presignedUpload(
  file: File,
  options: PresignedUploadOptions = {},
): Promise<UploadMergeResponse> {
  const directory = options.directory ?? ''
  const fileType = options.fileType ?? 'other'

  const initResp = await apiClient.post<PresignedUploadInitResponse>('/files/presigned-upload', {
    original_name: file.name,
    directory,
    size: file.size,
    file_type: fileType,
  })

  const { upload_url, file_id } = initResp.data

  // 直传对象存储：使用独立 axios 实例，避免 apiClient 的 30s 超时限制大文件
  await axios.put(upload_url, file, {
    timeout: 0,
    onUploadProgress: (event) => {
      if (event.total && event.total > 0) {
        options.onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
    },
  })

  // 通知后端激活记录
  await apiClient.post(`/files/${file_id}/presigned-complete`, { checksum: '' })

  return {
    file_id,
    original_name: file.name,
    size: file.size,
    checksum: '',
    used_storage: 0,
  }
}
