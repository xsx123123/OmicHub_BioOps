/**
 * 下载进度轮询 composable — 定时拉取 EBIDownload 逐 run 进度
 *
 * 用法：
 *   const { progress, startPolling, stopPolling } = useDownloadProgress(taskId)
 *   startPolling()  // 开始每 3s 轮询
 *   stopPolling()   // 停止
 */
import { ref } from 'vue'
import type { Ref } from 'vue'
import apiClient from '@/api/client'
import type { DownloadProgressResponse } from '@/types/download'

export function useDownloadProgress(taskId: Ref<string>) {
  const progress = ref<DownloadProgressResponse | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function fetchProgress() {
    if (!taskId.value) return
    try {
      const res = await apiClient.get<DownloadProgressResponse>(
        `/downloads/${taskId.value}/progress`,
      )
      progress.value = res.data
    } catch {
      // 轮询失败不清空已有数据
    } finally {
      loading.value = false
    }
  }

  function startPolling(intervalMs = 3000) {
    if (timer) return
    fetchProgress()
    timer = setInterval(fetchProgress, intervalMs)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  return { progress, loading, fetchProgress, startPolling, stopPolling }
}
