/**
 * 分块上传 composable — 切片 + 并发上传 + 断点续传 + 暂停/继续/取消
 *
 * 流程：
 *   init（秒传/续传判定）→ 并发 chunk（已传分片跳过）→ merge
 * 暂停：取消在途 axios，会话保留在服务端；继续：重新 init 拿已传分片续传。
 */
import SparkMD5 from 'spark-md5'
import apiClient from '@/api/client'
import { getStorageInfo, presignedUpload } from '@/composables/usePresignedUpload'
import type {
  UploadInitResponse,
  UploadMergeResponse,
  UploadQueueItem,
} from '@/types'

export const CHUNK_SIZE = 5 * 1024 * 1024 // 5 MiB
const CONCURRENCY = 3
/** 超过此大小的文件优先尝试预签名直传（S3/cloud 模式） */
const PRESIGNED_THRESHOLD = 100 * 1024 * 1024 // 100 MiB

export interface UseChunkUploadOptions {
  onProgress?: (item: UploadQueueItem) => void
  onCompleted?: (item: UploadQueueItem, resp: UploadMergeResponse) => void
  onError?: (item: UploadQueueItem, message: string) => void
}

/** 计算文件整体 MD5（用于秒传/校验标识） */
async function computeFileMd5(file: File): Promise<string> {
  // 大文件仅取首尾 + 中段采样，避免全量读取阻塞
  const CHUNK = 2 * 1024 * 1024
  const spark = new SparkMD5.ArrayBuffer()
  if (file.size <= CHUNK * 3) {
    spark.append(await file.arrayBuffer())
  } else {
    const head = file.slice(0, CHUNK)
    const mid = file.slice(file.size / 2 - CHUNK / 2, file.size / 2 + CHUNK / 2)
    const tail = file.slice(file.size - CHUNK, file.size)
    spark.append(await head.arrayBuffer())
    spark.append(await mid.arrayBuffer())
    spark.append(await tail.arrayBuffer())
  }
  return spark.end()
}

/** 计算单分片 MD5 */
async function computeChunkMd5(blob: Blob): Promise<string> {
  const spark = new SparkMD5.ArrayBuffer()
  spark.append(await blob.arrayBuffer())
  return spark.end()
}

/** 创建可中断的延迟（用于并发节流） */
function createCancelTokens() {
  const controllers: AbortController[] = []
  const cancelAll = () => {
    controllers.forEach((c) => c.abort())
    controllers.length = 0
  }
  return {
    newToken: () => {
      const c = new AbortController()
      controllers.push(c)
      return c
    },
    cancelAll,
    clear: () => {
      controllers.length = 0
    },
  }
}

export function useChunkUpload(options: UseChunkUploadOptions = {}) {
  /**
   * 上传单个文件（含 init / 并发 chunk / merge）。
   * directory: 上传目标目录（相对 raw/ 子路径，"" = 根）。
   * 返回控制器：{ pause, cancel }。
   */
  function uploadFile(item: UploadQueueItem, directory: string = '') {
    const cancelTokens = createCancelTokens()
    let paused = false

    const run = async () => {
      const { file } = item
      try {
        item.status = 'uploading'
        options.onProgress?.(item)

        const fileMd5 = await computeFileMd5(file)
        const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))

        // cloud/S3 模式下大文件优先走预签名 URL 直传，不经过应用服务器
        if (file.size >= PRESIGNED_THRESHOLD) {
          try {
            const storageInfo = await getStorageInfo()
            if (storageInfo.presigned_url_enabled) {
              item.totalChunks = 1
              const mergeResp = await presignedUpload(file, {
                directory,
                onProgress: (percent) => {
                  item.progress = percent
                  item.speed = 0
                  options.onProgress?.(item)
                },
              })
              item.progress = 100
              item.uploadedChunks = 1
              item.status = 'completed'
              options.onProgress?.(item)
              options.onCompleted?.(item, mergeResp)
              return
            }
          } catch (err: any) {
            // 预签名失败（如本地模式不支持）时回退到常规分块上传，不阻断用户
            const detail = err?.response?.data?.detail || ''
            if (!detail.includes('不支持预签名') && !detail.includes('本地模式')) {
              throw err
            }
          }
        }

        // 1) init
        const initResp = (
          await apiClient.post<UploadInitResponse>('/files/upload/init', {
            file_name: file.name,
            total_size: file.size,
            chunk_size: CHUNK_SIZE,
            total_chunks: totalChunks,
            file_md5: fileMd5,
            directory,
          })
        ).data

        item.uploadId = initResp.upload_id
        item.totalChunks = totalChunks

        // 秒传命中
        if (initResp.completed) {
          item.uploadedChunks = totalChunks
          item.progress = 100
          item.status = 'completed'
          options.onProgress?.(item)
          options.onCompleted?.(item, {
            file_id: initResp.file_id ?? '',
            original_name: file.name,
            size: file.size,
            checksum: fileMd5,
            used_storage: 0,
          })
          return
        }

        // 已传分片集合（断点续传）
        const uploadedSet = new Set<number>()
        if (Array.isArray(initResp.uploaded_chunks)) {
          initResp.uploaded_chunks.forEach((c: any) => {
            uploadedSet.add(typeof c === 'number' ? c : c.index)
          })
        }
        item.uploadedChunks = uploadedSet.size
        item.progress = Math.round((uploadedSet.size / totalChunks) * 100)
        options.onProgress?.(item)

        // 2) 并发上传未完成分片
        const pendingIndexes: number[] = []
        for (let i = 0; i < totalChunks; i++) {
          if (!uploadedSet.has(i)) pendingIndexes.push(i)
        }

        let cursor = 0
        const startTs = Date.now()
        const worker = async () => {
          while (cursor < pendingIndexes.length) {
            if (paused) return
            const idx = pendingIndexes[cursor++]
            const start = idx * CHUNK_SIZE
            const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size))
            const md5 = await computeChunkMd5(blob)
            const form = new FormData()
            form.append('upload_id', initResp.upload_id)
            form.append('index', String(idx))
            form.append('md5', md5)
            form.append('chunk', blob)

            // 429 退避重试：限流时指数退避 + 抖动，避免连环失败。
            // 后端已对上传路径豁免限流，此为多用户并发或网关波动的兜底。
            const MAX_RETRY = 4
            for (let attempt = 0; attempt < MAX_RETRY; attempt++) {
              if (paused) return
              const ctrl = cancelTokens.newToken()
              try {
                await apiClient.post('/files/upload/chunk', form, {
                  signal: ctrl.signal,
                  headers: { 'Content-Type': 'multipart/form-data' },
                })
                break // 成功
              } catch (err: any) {
                const status = err?.response?.status
                const canceled = err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED'
                if (canceled) return // 主动暂停/取消，不重试
                if (status === 429 || (status && status >= 500)) {
                  // 指数退避：0.5s, 1s, 2s, 4s + 抖动
                  const delay = (500 * 2 ** attempt) + Math.random() * 200
                  await new Promise((r) => setTimeout(r, delay))
                  if (attempt === MAX_RETRY - 1) throw err
                  continue
                }
                throw err // 其他错误直接抛出
              }
            }
            uploadedSet.add(idx)
            item.uploadedChunks = uploadedSet.size
            item.progress = Math.round((uploadedSet.size / totalChunks) * 100)
            item.speed = Math.round((uploadedSet.size * CHUNK_SIZE) / Math.max(1, (Date.now() - startTs) / 1000))
            options.onProgress?.(item)
          }
        }

        const workers = Array.from({ length: Math.min(CONCURRENCY, pendingIndexes.length) }, () => worker())
        await Promise.all(workers)

        if (paused) {
          item.status = 'paused'
          options.onProgress?.(item)
          return
        }

        // 3) merge
        if (uploadedSet.size < totalChunks) {
          throw new Error(`分片未传完：${uploadedSet.size}/${totalChunks}`)
        }
        item.status = 'merging'
        options.onProgress?.(item)
        const mergeResp = (
          await apiClient.post<UploadMergeResponse>('/files/upload/merge', {
            upload_id: initResp.upload_id,
          })
        ).data
        item.status = 'completed'
        item.progress = 100
        options.onProgress?.(item)
        options.onCompleted?.(item, mergeResp)
      } catch (err: any) {
        if (paused || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
          item.status = 'paused'
          options.onProgress?.(item)
          return
        }
        const detail = err?.response?.data?.detail || err?.message || '上传失败'
        item.status = 'failed'
        item.error = detail
        options.onError?.(item, detail)
      }
    }

    return {
      pause: () => {
        paused = true
        cancelTokens.cancelAll()
      },
      resume: () => {
        if (paused) {
          paused = false
          cancelTokens.clear()
          run()
        }
      },
      cancel: async () => {
        paused = true
        cancelTokens.cancelAll()
        if (item.uploadId) {
          try {
            await apiClient.delete(`/files/upload/${item.uploadId}`)
          } catch {
            /* ignore */
          }
        }
        item.status = 'cancelled'
        options.onProgress?.(item)
      },
      run,
    }
  }

  return { uploadFile }
}
