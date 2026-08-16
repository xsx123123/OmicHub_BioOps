import { ref, onScopeDispose } from 'vue'

/**
 * 终端 WebSocket — 双向代理浏览器 ↔ ttyd
 *
 * 连接 /api/v1/terminal/sessions/<session_id>/ws?token=<JWT>
 * 数据为原始文本（非 JSON），直接转发给 xterm.js。
 */
export function useTerminalWebSocket(sessionId: string) {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manualClose = false
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let messageHandler: ((data: string | Uint8Array) => void) | null = null
  let closeHandler: (() => void) | null = null

  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    if (!token) return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/api/v1/terminal/sessions/${sessionId}/ws?token=${token}`
  }

  function connect(onMessage: (data: string | Uint8Array) => void, onClose?: () => void) {
    const url = getWsUrl()
    if (!url || (ws.value && ws.value.readyState === WebSocket.OPEN)) {
      messageHandler = onMessage
      closeHandler = onClose ?? null
      return
    }
    manualClose = false
    messageHandler = onMessage
    closeHandler = onClose ?? null
    ws.value = new WebSocket(url, ['tty'])
    ws.value.binaryType = 'arraybuffer'

    ws.value.onopen = () => {
      connected.value = true
      reconnectAttempts = 0

      heartbeatTimer = setInterval(() => {
        if (ws.value?.readyState === WebSocket.OPEN) {
          ws.value.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    ws.value.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        messageHandler?.(new Uint8Array(event.data))
      } else {
        messageHandler?.(event.data)
      }
    }

    ws.value.onclose = () => {
      connected.value = false
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer)
        heartbeatTimer = null
      }
      closeHandler?.()
      if (!manualClose) scheduleReconnect()
    }

    ws.value.onerror = () => {
      connected.value = false
    }
  }

  function send(data: string) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(data)
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectAttempts++
    if (reconnectAttempts > 5) return
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectTimer = setTimeout(() => {
      if (messageHandler) connect(messageHandler, closeHandler ?? undefined)
    }, delay)
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
  }

  onScopeDispose(() => disconnect())

  return { connected, connect, send, disconnect }
}
