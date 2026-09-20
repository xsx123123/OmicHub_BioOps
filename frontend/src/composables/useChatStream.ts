/**
 * useChatStream — SSE 流式聊天 Composable
 *
 * 基于 fetch + ReadableStream 解析 Server-Sent Events，
 * 不使用 axios（axios 不支持 ReadableStream 流式读取）。
 * JWT Token 从 localStorage 获取，与 apiClient 保持一致。
 */

import { ref } from 'vue'

export interface ChatStreamOptions {
  messages: { role: string; content: string }[]
  modelId: string
  /** 传入则走 Agent 调度中枢（如通用助手 agent-general），否则按 modelId 直连模型 */
  agentId?: string
  /** 用户当前页面上下文（名称/路径/参数），后端注入系统提示词 */
  pageContext?: string
  sessionId?: string
  assistantId?: string
  systemPrompt?: string
  temperature?: number
  maxTokens?: number
}

export interface StreamCallbacks {
  onText?: (text: string, isReasoning?: boolean) => void
  onSessionCreated?: (sessionId: string, messageId: string) => void
  onError?: (error: string) => void
  onDone?: (sessionId: string, messageId: string) => void
}

export function useChatStream() {
  const isStreaming = ref(false)
  const abortController = ref<AbortController | null>(null)

  async function streamChat(options: ChatStreamOptions, callbacks: StreamCallbacks): Promise<void> {
    if (isStreaming.value) return
    isStreaming.value = true

    abortController.value = new AbortController()

    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          messages: options.messages,
          model_id: options.modelId,
          agent_id: options.agentId,
          page_context: options.pageContext,
          session_id: options.sessionId,
          assistant_id: options.assistantId,
          system_prompt: options.systemPrompt,
          temperature: options.temperature,
          max_tokens: options.maxTokens,
        }),
        signal: abortController.value.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        callbacks.onError?.(`请求失败 (${response.status}): ${errorText}`)
        return
      }

      if (!response.body) {
        callbacks.onError?.('浏览器不支持流式响应')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      // 是否已收到 done/error 终态事件；Agent 链路可能以 agent_turn_failed 等事件收尾后关闭流
      let terminalSeen = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue

          const data = trimmed.slice(6)
          try {
            const parsed = JSON.parse(data)
            if (handleStreamEvent(parsed, callbacks)) terminalSeen = true
          } catch {
            // 忽略不完整的 JSON
          }
        }
      }

      // 流已关闭但未收到终态事件：主动收尾，避免消息永远停在"正在思考…"
      if (!terminalSeen) {
        callbacks.onError?.('连接已中断，回答可能不完整，请重试')
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户主动取消，不报错
      } else {
        callbacks.onError?.(err instanceof Error ? err.message : '未知错误')
      }
    } finally {
      isStreaming.value = false
      abortController.value = null
    }
  }

  /** 处理单条 SSE 事件；返回 true 表示该事件是 done/error 终态 */
  function handleStreamEvent(data: Record<string, unknown>, callbacks: StreamCallbacks): boolean {
    const type = data.type as string
    const content = (data.content as string) || ''
    const sessionId = data.session_id as string | undefined
    const messageId = data.message_id as string | undefined
    const isReasoning = data.is_reasoning as boolean | undefined

    switch (type) {
      case 'text':
        callbacks.onText?.(content, isReasoning)
        if (sessionId && messageId) {
          callbacks.onSessionCreated?.(sessionId, messageId)
        }
        return false
      case 'error':
        callbacks.onError?.(content)
        return true
      case 'done':
        // Agent 链路的 text 帧不一定带 session_id/message_id，done 帧兜底补发
        if (sessionId && messageId) {
          callbacks.onSessionCreated?.(sessionId, messageId)
          callbacks.onDone?.(sessionId, messageId)
        }
        return true
      default:
        // tool_call / tool_result / web_search / ask_request 等事件侧边栏不渲染，忽略
        return false
    }
  }

  function abortStream(): void {
    abortController.value?.abort()
    isStreaming.value = false
  }

  return {
    isStreaming,
    streamChat,
    abortStream,
  }
}
