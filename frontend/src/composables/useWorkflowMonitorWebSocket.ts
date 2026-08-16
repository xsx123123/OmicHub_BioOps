import { onScopeDispose } from 'vue'
import { useWorkflowMonitorStore } from '@/stores/workflowMonitor'
import type { WorkflowMonitorWsMessage } from '@/types/workflowMonitor'

export function useWorkflowMonitorWebSocket() {
  const store = useWorkflowMonitorStore()
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manualClose = false

  function getWsUrl(): string {
    const token = localStorage.getItem('access_token')
    if (!token) return ''
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/api/v1/workflow-monitor/ws?token=${token}`
  }

  function connect() {
    const url = getWsUrl()
    if (!url || (ws && ws.readyState === WebSocket.OPEN)) return

    manualClose = false
    ws = new WebSocket(url)

    ws.onopen = () => {
      store.connected = true
      reconnectAttempts = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WorkflowMonitorWsMessage
        if (data.type === 'event') store.applyEvent(data.event)
        else if (data.type === 'task_snapshot') store.applyTaskSnapshot(data.task)
        else if (data.type === 'summary') store.applySummary(data.summary)
      } catch {
        // Ignore non-JSON messages.
      }
    }

    ws.onclose = (event) => {
      store.connected = false
      if (!manualClose && event.code !== 1008) scheduleReconnect()
    }

    ws.onerror = () => {
      store.connected = false
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectAttempts += 1
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectTimer = setTimeout(() => connect(), delay)
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    store.connected = false
  }

  onScopeDispose(disconnect)

  return { connect, disconnect }
}
