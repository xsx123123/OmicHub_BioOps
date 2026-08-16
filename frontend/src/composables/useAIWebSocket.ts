import { ref, onScopeDispose } from 'vue'
import type { AIEvent } from '@/types'

interface PendingMessage {
  type: 'chat'
  conversation_id: string
  content: string
  assistant_id?: string
}

/**
 * AI 对话 WebSocket — 流式响应 + Tool Use
 *
 * 连接 /api/v1/ai/ws?token=<JWT>，发送 {type:'chat',...}，接收流式事件。
 * 自动重连（指数退避），组件卸载时自动断开。
 * 连接未就绪时发送的消息会进入队列，在 onopen 后按序发出。
 */
export function useAIWebSocket() {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  const lastError = ref<string | null>(null)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manualClose = false
  let eventHandler: ((e: AIEvent) => void) | null = null
  const pendingMessages = ref<PendingMessage[]>([])

  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    if (!token) return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/api/v1/ai/ws?token=${token}`
  }

  function flushPendingMessages() {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return
    while (pendingMessages.value.length) {
      const msg = pendingMessages.value.shift()
      if (msg) ws.value.send(JSON.stringify(msg))
    }
  }

  function connect(onEvent: (e: AIEvent) => void) {
    const url = getWsUrl()
    if (!url) {
      eventHandler = onEvent
      lastError.value = '未登录，无法连接 AI 服务'
      return
    }
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      eventHandler = onEvent
      return
    }
    manualClose = false
    eventHandler = onEvent
    lastError.value = null
    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
      lastError.value = null
      flushPendingMessages()
    }

    ws.value.onmessage = (event) => {
      try {
        const data: AIEvent = JSON.parse(event.data)
        if (data.type === 'error') {
          lastError.value = data.detail
        }
        eventHandler?.(data)
      } catch {
        // 忽略非 JSON
      }
    }

    ws.value.onclose = () => {
      connected.value = false
      if (!manualClose) scheduleReconnect()
    }

    ws.value.onerror = () => {
      connected.value = false
      lastError.value = 'AI 服务连接失败，请检查网络或点击重连'
    }
  }

  function sendChat(conversationId: string, content: string, assistantId?: string) {
    const msg: PendingMessage = {
      type: 'chat',
      conversation_id: conversationId,
      content,
      ...(assistantId ? { assistant_id: assistantId } : {}),
    }
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(msg))
    } else {
      pendingMessages.value.push(msg)
      if (!ws.value || ws.value.readyState === WebSocket.CLOSED) {
        if (eventHandler) connect(eventHandler)
      }
    }
  }

  function ping() {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'ping' }))
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectAttempts++
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectTimer = setTimeout(() => {
      if (eventHandler) connect(eventHandler)
    }, delay)
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
    pendingMessages.value = []
  }

  onScopeDispose(() => disconnect())

  return { connected, lastError, connect, sendChat, ping, disconnect }
}
