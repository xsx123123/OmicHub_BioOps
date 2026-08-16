/**
 * 全局上传 store —— 跨页面持久化的分块上传队列
 *
 * 把原先散落在 ChunkUploader 组件内的 queue/controllers 状态上提到 Pinia，
 * 这样上传弹窗最小化为右下悬浮球后，上传任务仍持续；切页也不中断。
 * 组件（ChunkUploader / UploadFloatingBall）只做展示，统一消费本 store。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useChunkUpload } from '@/composables/useChunkUpload'
import type { UploadMergeResponse, UploadQueueItem } from '@/types'

interface UploadController {
  pause: () => void
  resume: () => void
  cancel: () => Promise<void>
  run: () => void
}

/** 生成唯一 id（兼容无 crypto.randomUUID 的环境） */
function genId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `up_${Date.now()}_${Math.random().toString(36).slice(2)}`
}

export const useUploadStore = defineStore('upload', () => {
  const queue = ref<UploadQueueItem[]>([])
  const uploaders = ref<Record<string, UploadController>>({})
  const modalOpen = ref(false)
  const minimized = ref(false)
  const targetDirectory = ref('')
  /** 每次完成自增 —— FilesView watch 它来刷新文件列表/配额 */
  const completedSeq = ref(0)

  const { uploadFile } = useChunkUpload({
    onProgress: (item) => {
      const idx = queue.value.findIndex((q) => q.id === item.id)
      if (idx >= 0) queue.value[idx] = { ...item }
    },
    onCompleted: (item, _resp: UploadMergeResponse) => {
      completedSeq.value += 1
    },
    onError: () => {
      /* 状态已写入 queue 项，UI 自行展示错误 */
    },
  })

  /** 是否有活跃任务（未结束） */
  const hasActive = computed(() =>
    queue.value.some((q) =>
      ['pending', 'uploading', 'merging', 'paused'].includes(q.status),
    ),
  )

  const activeCount = computed(
    () => queue.value.filter((q) => ['uploading', 'merging', 'pending', 'paused'].includes(q.status)).length,
  )

  /** 整体进度：按已完成分片占总分片比例加权 */
  const overallProgress = computed(() => {
    const items = queue.value.filter((q) => q.status !== 'cancelled')
    if (!items.length) return 0
    const sum = items.reduce((acc, q) => acc + q.progress, 0)
    return Math.round(sum / items.length)
  })

  function open(directory?: string) {
    if (directory !== undefined) targetDirectory.value = directory
    minimized.value = false
    modalOpen.value = true
  }

  function minimize() {
    minimized.value = true
    modalOpen.value = false
  }

  function close() {
    // 仅在没有活跃上传时允许真正关闭
    if (!hasActive.value) {
      modalOpen.value = false
      minimized.value = false
      queue.value = []
      Object.keys(uploaders.value).forEach((k) => delete uploaders.value[k])
    } else {
      // 有活跃任务则转为最小化
      minimize()
    }
  }

  function addFile(file: File) {
    const item: UploadQueueItem = {
      id: genId(),
      file,
      uploadId: null,
      status: 'pending',
      progress: 0,
      uploadedChunks: 0,
      totalChunks: Math.max(1, Math.ceil(file.size / (5 * 1024 * 1024))),
      speed: 0,
      error: '',
    }
    queue.value.push(item)
    const controller = uploadFile(item, targetDirectory.value || '')
    uploaders.value[item.id] = controller
    controller.run()
  }

  function pause(id: string) {
    uploaders.value[id]?.pause()
  }
  function resume(id: string) {
    uploaders.value[id]?.resume()
  }
  async function cancel(id: string) {
    await uploaders.value[id]?.cancel()
    queue.value = queue.value.filter((q) => q.id !== id)
    delete uploaders.value[id]
  }

  function removeCompleted() {
    const keep = queue.value.filter((q) => q.status !== 'completed' && q.status !== 'cancelled')
    queue.value
      .filter((q) => !keep.includes(q))
      .forEach((q) => delete uploaders.value[q.id])
    queue.value = keep
  }

  return {
    queue,
    modalOpen,
    minimized,
    targetDirectory,
    completedSeq,
    hasActive,
    activeCount,
    overallProgress,
    open,
    minimize,
    close,
    addFile,
    pause,
    resume,
    cancel,
    removeCompleted,
  }
})
