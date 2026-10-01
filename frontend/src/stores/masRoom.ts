import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'

/**
 * 生物信息部门（MAS 房间）Pinia store：
 * 消息列表 + SSE 消费（fetch-stream，断线按平台惯例指数退避重连）+ 计划卡片状态。
 */
export interface MasRoomMessage {
  id: string
  room_id: string
  run_id: string | null
  agent_id: string | null
  role: 'user' | 'assistant' | 'mas_trace' | 'plan_card'
  content: string
  metadata: Record<string, unknown>
  created_at: string | null
}

import type { AgentCategory } from '@/types/agent'

export interface MasMember {
  agent_id: string
  name: string
  description: string
  avatar: string
  color: string
  category: AgentCategory
  // KimiChatInput roomMentionAgents 需要 AgentTemplate 完整结构；
  // 成员列表只消费 avatar/name/description/agent_id，其余字段以必需形态声明（store map 时填充）
  id: string
  model_engine: string
  system_prompt: string
  welcome_message: string
  mcp_ids: string[]
  skill_ids: string[]
  features: Record<string, unknown>
  temperature: number
  max_tokens: number
  model_name?: string
  model_id?: string
  is_active: boolean
  is_builtin: boolean
  is_default: boolean
  [key: string]: unknown
}

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
const RECONNECT_MAX_TRIES = 5

export const useMasRoomStore = defineStore('masRoom', () => {
  const DEFAULT_ROOM = 'bioinfo-dept'

  const messages = shallowRef<MasRoomMessage[]>([])
  const members = ref<MasMember[]>([])
  const loading = ref(false)
  const sending = ref(false)
  const connected = ref(false)
  const runActive = ref(false)
  const activePlan = ref<Record<string, unknown> | null>(null)

  let abortController: AbortController | null = null
  let reconnectTries = 0
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let stopRequested = false

  async function loadMembers() {
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/agents', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!response.ok) return
      const list = (await response.json()) as Array<Record<string, unknown>>
      // 部门名册：生物信息相关类别（analysis/visualization/exploration）
      const deptCategories = ['analysis', 'visualization', 'exploration']
      members.value = list
        .filter((a) => deptCategories.includes(String(a.category || '')))
        .map((a) => ({
          agent_id: String(a.agent_id || ''),
          name: String(a.name || ''),
          description: String(a.description || ''),
          avatar: String(a.avatar || '🤖'),
          color: String(a.color || '#4f8ef7'),
          category: (a.category as AgentCategory) || 'analysis',
          // AgentTemplate 必需字段（API 原始对象透传；缺失时以默认值兜底，仅类型兼容用）
          id: String(a.id || a.agent_id || ''),
          model_engine: String(a.model_engine || ''),
          system_prompt: String(a.system_prompt || ''),
          welcome_message: String(a.welcome_message || ''),
          mcp_ids: (a.mcp_ids as string[]) || [],
          skill_ids: (a.skill_ids as string[]) || [],
          features: (a.features as Record<string, unknown>) || {},
          temperature: Number(a.temperature ?? 0.7),
          max_tokens: Number(a.max_tokens ?? 65536),
          model_name: a.model_name ? String(a.model_name) : undefined,
          model_id: a.model_id ? String(a.model_id) : undefined,
          is_active: Boolean(a.is_active ?? true),
          is_builtin: Boolean(a.is_builtin ?? false),
          is_default: Boolean(a.is_default ?? false),
        }))
    } catch {
      // 成员列表加载失败不阻塞消息区
    }
  }

  async function loadMessages(roomId: string = DEFAULT_ROOM) {
    loading.value = true
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(`/api/v1/mas/rooms/${roomId}/messages?limit=100`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!response.ok) return
      const body = (await response.json()) as { messages: MasRoomMessage[] }
      messages.value = body.messages || []
    } catch {
      // 保留已有消息
    } finally {
      loading.value = false
    }
  }

  async function sendMessage(roomId: string, content: string) {
    if (sending.value) return
    sending.value = true
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(`/api/v1/mas/rooms/${roomId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content }),
      })
      if (response.ok) {
        const item = (await response.json()) as MasRoomMessage
        appendMessage(item)
      }
    } catch {
      // 失败由组件层提示
    } finally {
      sending.value = false
    }
  }

  function appendMessage(item: MasRoomMessage) {
    if (messages.value.some((m) => m.id === item.id)) return
    messages.value = [...messages.value, item]
    if (item.role === 'plan_card') {
      activePlan.value = item.metadata || {}
    }
  }

  function handleEvent(event: Record<string, unknown>) {
    const type = String(event.type || '')
    if (type === 'room_message') {
      appendMessage(event as unknown as MasRoomMessage)
      return
    }
    if (type === 'mas_trace') {
      appendMessage(event as unknown as MasRoomMessage)
      return
    }
    if (type === 'plan_card') {
      appendMessage(event as unknown as MasRoomMessage)
      activePlan.value = (event.metadata as Record<string, unknown>) || {}
      return
    }
    if (type === 'run_started') {
      runActive.value = true
      return
    }
    if (type === 'done' || type === 'error') {
      runActive.value = false
      if (type === 'done') activePlan.value = null
      return
    }
    console.warn('[masRoom] unknown event type:', type)
  }

  async function connectStream(roomId: string = DEFAULT_ROOM) {
    stopRequested = false
    reconnectTries = 0
    await connectOnce(roomId)
  }

  async function connectOnce(roomId: string) {
    abortController = new AbortController()
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(`/api/v1/mas/rooms/${roomId}/stream`, {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: abortController.signal,
      })
      if (!response.ok || !response.body) {
        connected.value = false
        scheduleReconnect(roomId)
        return
      }
      connected.value = true
      reconnectTries = 0
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
          if (!line.startsWith('data:')) continue
          try {
            const parsed = JSON.parse(line.slice(5).trim()) as Record<string, unknown>
            handleEvent(parsed)
          } catch (error) {
            console.warn('[masRoom] stream parse error:', error)
          }
        }
      }
      connected.value = false
      if (!stopRequested) scheduleReconnect(roomId)
    } catch (error) {
      connected.value = false
      const isAbort = error instanceof DOMException && error.name === 'AbortError'
      if (!isAbort && !stopRequested) scheduleReconnect(roomId)
    } finally {
      abortController = null
    }
  }

  function scheduleReconnect(roomId: string) {
    if (reconnectTries >= RECONNECT_MAX_TRIES) return
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectTries, RECONNECT_MAX_MS)
    reconnectTries += 1
    reconnectTimer = setTimeout(() => {
      void connectOnce(roomId)
    }, delay)
  }

  function disconnectStream() {
    stopRequested = true
    abortController?.abort()
    abortController = null
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    connected.value = false
  }

  return {
    messages,
    members,
    loading,
    sending,
    connected,
    runActive,
    activePlan,
    loadMembers,
    loadMessages,
    sendMessage,
    connectStream,
    disconnectStream,
  }
})
