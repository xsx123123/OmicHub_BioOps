import { ref, onScopeDispose } from 'vue'
import type { SandboxEvent } from '@/types'

/**
 * 沙盒代码执行 WebSocket — 流式 stdout/stderr + 图表
 *
 * 连接 /api/v1/sandbox/sessions/<id>/ws?token=<JWT>，发送 {type:'execute',code}。
 */
export function useSandboxWebSocket(sessionId: string) {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manualClose = false
  let eventHandler: ((e: SandboxEvent) => void) | null = null

  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    if (!token) return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/api/v1/sandbox/sessions/${sessionId}/ws?token=${token}`
  }

  function connect(onEvent: (e: SandboxEvent) => void) {
    const url = getWsUrl()
    if (!url || (ws.value && ws.value.readyState === WebSocket.OPEN)) {
      eventHandler = onEvent
      return
    }
    manualClose = false
    eventHandler = onEvent
    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
    }

    ws.value.onmessage = (event) => {
      try {
        const data: SandboxEvent = JSON.parse(event.data)
        eventHandler?.(data)
      } catch {
        // 忽略
      }
    }

    ws.value.onclose = () => {
      connected.value = false
      if (!manualClose) scheduleReconnect()
    }

    ws.value.onerror = () => {
      connected.value = false
    }
  }

  function execute(code: string, timeout = 0) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ type: 'execute', code, timeout }))
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
  }

  onScopeDispose(() => disconnect())

  return { connected, connect, execute, disconnect }
}
