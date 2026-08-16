/**
 * useLangGraphStream
 * ==================
 * LangGraph SSE 流式适配组合式函数。
 *
 * 兼容 OmicHub 现有的 useAgentChatStream.ts，新增:
 *   - HITL 中断处理 (hitl_request → 弹窗 → hitl_resume)
 *   - 检查点状态查询
 *   - 线程级取消
 *
 * 事件类型 (兼容现有 + 新增):
 *   text, tool_call, tool_result, status, done, error
 *   hitl_request, hitl_resumed (新增)
 */

import { ref, reactive } from 'vue'

// ── 类型定义 ──

interface HITLPayload {
  interrupt_for: 'param_confirm' | 'task_submit' | 'result_review' | 'error_recovery'
  title: string
  description: string
  payload: Record<string, any>
  timeout_seconds: number
}

interface HITLRequest {
  id: string
  hitl_type: string
  title: string
  description: string
  payload: Record<string, any>
  thread_id: string
  remaining_seconds: number
}

interface StreamOptions {
  agentId: string
  sessionId: string
  message: string
  threadId?: string
  onHITL?: (request: HITLRequest) => void
  onText?: (text: string) => void
  onToolCall?: (toolName: string, input: any) => void
  onToolResult?: (toolName: string, result: string, success: boolean) => void
  onDone?: (response: string, metadata?: any) => void
  onError?: (message: string) => void
  onStatus?: (phase: string, detail: string) => void
}

interface StreamState {
  isStreaming: boolean
  isHITLPending: boolean
  currentThreadId: string
  currentHITLRequest: HITLRequest | null
  error: string | null
  metadata: {
    roundCount: number
    totalTokens: number
    toolCallsCount: number
  }
}

// ── 组合式函数 ──

export function useLangGraphStream() {
  const state = reactive<StreamState>({
    isStreaming: false,
    isHITLPending: false,
    currentThreadId: '',
    currentHITLRequest: null,
    error: null,
    metadata: {
      roundCount: 0,
      totalTokens: 0,
      toolCallsCount: 0,
    },
  })

  const abortController = ref<AbortController | null>(null)

  // ── 核心流式方法 ──

  async function startStream(options: StreamOptions): Promise<void> {
    if (state.isStreaming) {
      console.warn('[LangGraph] 已有流在运行')
      return
    }

    state.isStreaming = true
    state.error = null
    abortController.value = new AbortController()

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: options.agentId,
          session_id: options.sessionId,
          message: options.message,
          thread_id: options.threadId || state.currentThreadId || undefined,
        }),
        signal: abortController.value.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('无法获取响应流')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const chunk of lines) {
          if (!chunk.trim()) continue
          const event = parseSSEChunk(chunk)
          if (event) {
            handleEvent(event, options)
          }
        }
      }

      // 处理剩余缓冲
      if (buffer.trim()) {
        const event = parseSSEChunk(buffer)
        if (event) handleEvent(event, options)
      }

    } catch (err: any) {
      if (err.name === 'AbortError') {
        console.log('[LangGraph] 流已取消')
      } else {
        state.error = err.message
        options.onError?.(err.message)
      }
    } finally {
      state.isStreaming = false
      abortController.value = null
    }
  }

  // ── HITL 恢复 ──

  async function resumeHITL(
    requestId: string,
    action: 'confirm' | 'modify' | 'reject' | 'defer',
    humanInput: Record<string, any> = {},
    comment?: string,
  ): Promise<boolean> {
    try {
      const response = await fetch('/api/v1/agent/hitl/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: requestId,
          action,
          human_input: humanInput,
          comment,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const result = await response.json()

      if (result.success) {
        state.isHITLPending = false
        state.currentHITLRequest = null

        // confirm/modify 后继续监听流
        if (action === 'confirm' || action === 'modify') {
          // 流的后续事件会自动到达（SSE 连接保持）
        }
      }

      return result.success
    } catch (err: any) {
      state.error = err.message
      return false
    }
  }

  // ── 取消执行 ──

  async function cancelStream(): Promise<void> {
    // 1. 中断 fetch
    abortController.value?.abort()

    // 2. 通知后端取消
    if (state.currentThreadId) {
      try {
        await fetch('/api/v1/agent/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ thread_id: state.currentThreadId }),
        })
      } catch (e) {
        // 忽略
      }
    }

    state.isStreaming = false
    state.isHITLPending = false
  }

  // ── 查询待处理 HITL ──

  async function fetchPendingHITL(sessionId: string): Promise<HITLRequest[]> {
    try {
      const response = await fetch(
        `/api/v1/agent/hitl/pending?session_id=${encodeURIComponent(sessionId)}`,
      )
      if (!response.ok) return []
      return await response.json()
    } catch {
      return []
    }
  }

  // ── 内部方法 ──

  function parseSSEChunk(chunk: string): { type: string; data: any } | null {
    const lines = chunk.split('\n')
    let eventType = 'message'
    let dataStr = ''

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataStr = line.slice(6).trim()
      }
    }

    if (!dataStr) return null

    try {
      return { type: eventType, data: JSON.parse(dataStr) }
    } catch {
      return { type: eventType, data: dataStr }
    }
  }

  function handleEvent(
    event: { type: string; data: any },
    options: StreamOptions,
  ): void {
    const { type, data } = event

    switch (type) {
      case 'text':
        options.onText?.(data.content || '')
        break

      case 'tool_call':
        options.onToolCall?.(data.tool_name, data.tool_input)
        break

      case 'tool_result':
        options.onToolResult?.(data.tool_name, data.result, data.success)
        state.metadata.toolCallsCount++
        break

      case 'hitl_request': {
        const payload: HITLPayload = data.payload
        const hitlRequest: HITLRequest = {
          id: data.payload?.id || `hitl_${Date.now()}`,
          hitl_type: payload.interrupt_for,
          title: payload.title,
          description: payload.description,
          payload: payload.payload,
          thread_id: data.thread_id,
          remaining_seconds: payload.timeout_seconds,
        }
        state.isHITLPending = true
        state.currentHITLRequest = hitlRequest
        options.onHITL?.(hitlRequest)
        break
      }

      case 'hitl_resumed':
        state.isHITLPending = false
        state.currentHITLRequest = null
        break

      case 'status':
        options.onStatus?.(data.phase, data.detail || '')
        if (data.phase === 'task_submitted') {
          // 任务已提交，可更新 UI
        }
        break

      case 'done':
        state.isStreaming = false
        state.metadata = {
          ...state.metadata,
          ...((data.metadata as any) || {}),
        }
        options.onDone?.(data.content || '', data.metadata)
        break

      case 'error':
        state.error = data.message
        state.isStreaming = false
        options.onError?.(data.message)
        break

      default:
        console.log('[LangGraph] 未知事件类型:', type, data)
    }

    // 更新 thread_id
    if (data.thread_id) {
      state.currentThreadId = data.thread_id
    }
  }

  // ── 返回 ──

  return {
    state,
    startStream,
    resumeHITL,
    cancelStream,
    fetchPendingHITL,
  }
}
