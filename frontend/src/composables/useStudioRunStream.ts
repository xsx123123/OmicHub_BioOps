/**
 * useStudioRunStream — Studio 代码重跑 SSE Composable
 *
 * POST /studio/sessions/{id}/run，fetch + ReadableStream 解析 `data: {json}` 行。
 * 事件（与 /chat/stream 同构）：
 *  - {"type":"tool_output","tool":"sandbox_execute","stream":"stdout|stderr","data":"..."}
 *  - {"type":"tool_result","tool_name":"sandbox_execute","success":bool,
 *     "result":{...},"ui_payload":{language,exit_code,duration_ms,stdout,stderr,artifacts}}
 */
import { ref } from 'vue'

export interface StudioRunOptions {
  sessionId: string
  code: string
  language?: 'python' | 'r' | 'bash'
  /** 超时秒数，缺省用沙盒默认（600s） */
  timeout?: number
}

export interface StudioRunUiPayload {
  language?: string
  exit_code?: number
  duration_ms?: number
  stdout?: string
  stderr?: string
  artifacts?: { path: string; size: number; mtime: number }[]
}

export interface StudioRunCallbacks {
  /** stdout/stderr 增量输出 */
  onOutput?: (stream: 'stdout' | 'stderr', data: string) => void
  /** 执行结束（成功或失败均会触发，success 标识退出状态） */
  onResult?: (payload: { success: boolean; result: unknown; uiPayload?: StudioRunUiPayload }) => void
  onError?: (error: string) => void
  /** 流结束（无论成功与否，finally 前最后触发一次） */
  onDone?: () => void
}

export function useStudioRunStream() {
  const isRunning = ref(false)
  const abortController = ref<AbortController | null>(null)

  async function run(options: StudioRunOptions, callbacks: StudioRunCallbacks): Promise<void> {
    if (isRunning.value) return
    isRunning.value = true
    abortController.value = new AbortController()

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(`/api/v1/studio/sessions/${options.sessionId}/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          code: options.code,
          language: options.language || 'python',
          ...(options.timeout != null ? { timeout: options.timeout } : {}),
        }),
        signal: abortController.value.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        callbacks.onError?.(`执行请求失败 (${response.status}): ${errorText}`)
        return
      }
      if (!response.body) {
        callbacks.onError?.('浏览器不支持流式响应')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue
          try {
            const parsed = JSON.parse(trimmed.slice(6)) as Record<string, unknown>
            if (parsed.type === 'tool_output') {
              callbacks.onOutput?.(
                parsed.stream === 'stderr' ? 'stderr' : 'stdout',
                (parsed.data as string) || '',
              )
            } else if (parsed.type === 'tool_result') {
              callbacks.onResult?.({
                success: Boolean(parsed.success),
                result: parsed.result,
                uiPayload: (parsed.ui_payload as StudioRunUiPayload) || undefined,
              })
            } else if (parsed.type === 'error') {
              callbacks.onError?.((parsed.content as string) || '执行失败')
            }
          } catch {
            /* 忽略不完整 JSON */
          }
        }
      }
      callbacks.onDone?.()
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户主动取消
      } else {
        callbacks.onError?.(err instanceof Error ? err.message : '未知错误')
      }
    } finally {
      isRunning.value = false
      abortController.value = null
    }
  }

  function abort(): void {
    abortController.value?.abort()
    isRunning.value = false
  }

  return { isRunning, run, abort }
}
