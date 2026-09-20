<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{
  connected: [value: boolean]
  commandExit: [commandId: string, exitCode: number]
  output: [data: string]
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let socket: WebSocket | null = null
let resizeObserver: ResizeObserver | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0
let disposed = false
let pendingInput: string[] = []

function websocketUrl(): string {
  const token = localStorage.getItem('access_token') || ''
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1/studio/sessions/${props.sessionId}/terminal?token=${encodeURIComponent(token)}`
}

function send(data: string) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(data)
  else pendingInput.push(data)
}

function sendResize() {
  if (!terminal) return
  send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
}

function fit() {
  if (!terminal || !fitAddon) return
  fitAddon.fit()
  sendResize()
}

function scheduleReconnect() {
  if (disposed || reconnectAttempts >= 5) return
  reconnectAttempts += 1
  reconnectTimer = window.setTimeout(connect, Math.min(1000 * 2 ** reconnectAttempts, 15000))
}

function connect() {
  if (disposed || !props.sessionId) return
  socket?.close()
  socket = new WebSocket(websocketUrl())
  socket.binaryType = 'arraybuffer'
  socket.onopen = () => {
    reconnectAttempts = 0
    emit('connected', true)
    sendResize()
    for (const data of pendingInput.splice(0)) socket?.send(data)
    terminal?.focus()
  }
  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      const bytes = new Uint8Array(event.data)
      terminal?.write(bytes)
      emit('output', new TextDecoder().decode(bytes))
    } else {
      const data = String(event.data)
      terminal?.write(data)
      emit('output', data)
    }
  }
  socket.onerror = () => emit('connected', false)
  socket.onclose = () => {
    emit('connected', false)
    if (!disposed) {
      terminal?.write('\r\n\x1b[33m[Studio 终端连接已断开，正在重连…]\x1b[0m\r\n')
      scheduleReconnect()
    }
  }
}

function runCommand(command: string): string {
  const commandId = `run-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
  send(`${command}; __cygnusx_exit=$?; printf '\\033]633;CygnusXExit;${commandId};%s\\007' "$__cygnusx_exit"\r`)
  terminal?.focus()
  return commandId
}

function interrupt() {
  send('\x03')
  terminal?.focus()
}

function clear() {
  terminal?.clear()
}

onMounted(async () => {
  terminal = new Terminal({
    fontFamily: 'JetBrains Mono, Fira Code, SFMono-Regular, Menlo, monospace',
    fontSize: 12,
    lineHeight: 1.25,
    cursorBlink: true,
    cursorStyle: 'block',
    scrollback: 10000,
    convertEol: false,
    macOptionIsMeta: true,
    theme: {
      background: '#1b1b2e',
      foreground: '#d7d6e8',
      cursor: '#f8f8f2',
      selectionBackground: '#454267',
      black: '#1b1b2e',
      red: '#ff6b6b',
      green: '#83e1a9',
      yellow: '#f8d57e',
      blue: '#82aaff',
      magenta: '#c792ea',
      cyan: '#89ddff',
      white: '#f1f1f5',
    },
  })
  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(new WebLinksAddon())
  terminal.parser.registerOscHandler(633, (data) => {
    const match = /^CygnusXExit;([^;]+);(-?\d+)$/.exec(data)
    if (!match) return false
    emit('commandExit', match[1], Number(match[2]))
    return true
  })
  terminal.onData(send)
  if (containerRef.value) terminal.open(containerRef.value)
  await nextTick()
  fit()
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(fit)
    resizeObserver.observe(containerRef.value)
  }
  connect()
})

watch(() => props.sessionId, () => {
  pendingInput = []
  terminal?.reset()
  connect()
})

onBeforeUnmount(() => {
  disposed = true
  if (reconnectTimer) clearTimeout(reconnectTimer)
  resizeObserver?.disconnect()
  socket?.close()
  terminal?.dispose()
})

defineExpose({ runCommand, interrupt, clear, focus: () => terminal?.focus(), fit })
</script>

<template>
  <div ref="containerRef" class="studio-xterm" />
</template>

<style scoped>
.studio-xterm {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 7px 10px 4px;
  background: #1b1b2e;
}
.studio-xterm :deep(.xterm) { height: 100%; }
.studio-xterm :deep(.xterm-viewport) { overflow-y: auto; }
.studio-xterm :deep(.xterm-screen) { padding-bottom: 4px; }
</style>
