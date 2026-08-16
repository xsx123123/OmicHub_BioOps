import { ref, onScopeDispose } from 'vue'
import { useCookieStore } from '@/stores/cookie'

interface BalanceUpdate {
  user_id: string
  balance: number
  frozen_balance: number
  available_balance: number
  txn_type: string
  amount: number
  description: string
}

/**
 * 饼干余额 WebSocket — 实时推送余额变更
 *
 * 连接 /api/v1/cookies/ws?token=<JWT>，交易完成后推送余额更新。
 * 自动重连（指数退避），组件卸载时自动断开。
 */
export function useCookieWebSocket() {
  const ws = ref<WebSocket | null>(null)
  const connected = ref(false)
  const lastUpdate = ref<BalanceUpdate | null>(null)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manualClose = false

  const cookieStore = useCookieStore()

  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    if (!token) return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/api/v1/cookies/ws?token=${token}`
  }

  function connect() {
    const url = getWsUrl()
    if (!url || (ws.value && ws.value.readyState === WebSocket.OPEN)) return

    manualClose = false
    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
    }

    ws.value.onmessage = (event) => {
      try {
        const data: BalanceUpdate = JSON.parse(event.data)
        lastUpdate.value = data
        cookieStore.updateBalanceFromWebSocket({
          balance: data.balance,
          frozen_balance: data.frozen_balance,
        })
      } catch {
        // 忽略非 JSON 消息
      }
    }

    ws.value.onclose = () => {
      connected.value = false
      if (!manualClose) {
        scheduleReconnect()
      }
    }

    ws.value.onerror = () => {
      connected.value = false
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectAttempts++
    // 指数退避：1s, 2s, 4s, 8s, 最大 30s
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectTimer = setTimeout(() => connect(), delay)
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

  onScopeDispose(() => {
    disconnect()
  })

  return { connected, lastUpdate, connect, disconnect }
}
