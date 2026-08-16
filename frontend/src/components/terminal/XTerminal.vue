<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { useDialog } from 'naive-ui'
import { useTerminalWebSocket } from '@/composables/useTerminalWebSocket'
import { TerminalLineBuffer, isDangerousDeleteCommand } from '@/utils/terminalDeleteGuard'

const props = defineProps<{
  sessionId: string
}>()

const emit = defineEmits<{
  connectionChange: [connected: boolean]
}>()

const containerRef = ref<HTMLDivElement>()
const dialog = useDialog()

let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let resizeObserver: ResizeObserver | null = null
// 删除操作守护：行缓冲 + 回车拦截，确认弹窗期间吞掉终端输入
const lineGuard = new TerminalLineBuffer()
let pendingDeleteConfirm = false

const { connected, connect, send, disconnect } = useTerminalWebSocket(props.sessionId)

/** 回车命中删除类命令时拦截，二次确认后再决定是否执行 */
function confirmDeleteCommand(command: string) {
  pendingDeleteConfirm = true
  const shown = command.length > 120 ? `${command.slice(0, 117)}...` : command
  dialog.warning({
    title: '检测到删除操作',
    content: `即将执行删除命令：“${shown}”。沙盒挂载的 workspace 等目录与平台数据实时同步，删除后无法恢复，请确认目标路径无误。`,
    positiveText: '确认执行',
    negativeText: '取消',
    maskClosable: false,
    closeOnEsc: false,
    positiveButtonProps: { type: 'error' },
    onPositiveClick: () => {
      pendingDeleteConfirm = false
      send('\r')
    },
    onNegativeClick: () => {
      pendingDeleteConfirm = false
      lineGuard.reset()
      // 清除 shell 行内已回显的命令，避免残留误触执行
      send('\x15')
    },
  })
}

onMounted(() => {
  term = new Terminal({
    fontFamily: 'JetBrains Mono, Fira Code, monospace',
    fontSize: 14,
    theme: {
      background: '#1e1e1e',
      foreground: '#d4d4d4',
      cursor: '#d4d4d4',
      selectionBackground: '#264f78',
      black: '#000000',
      red: '#cd3131',
      green: '#0dbc79',
      yellow: '#e5e510',
      blue: '#2472c8',
      magenta: '#bc3fbc',
      cyan: '#11a8cd',
      white: '#e5e5e5',
    },
    cursorBlink: true,
    cursorStyle: 'block',
    scrollback: 10000,
    macOptionIsMeta: true,
  })

  fitAddon = new FitAddon()
  const webLinksAddon = new WebLinksAddon()

  term.loadAddon(fitAddon)
  term.loadAddon(webLinksAddon)

  if (containerRef.value) {
    term.open(containerRef.value)
    fitAddon.fit()
  }

  term.onData((data) => {
    // 确认弹窗打开期间吞掉输入，避免破坏 shell 行状态
    if (pendingDeleteConfirm) return
    const { submitted } = lineGuard.feed(data)
    if (submitted !== null && isDangerousDeleteCommand(submitted)) {
      confirmDeleteCommand(submitted.trim())
      return // 拦截回车，不发送给后端
    }
    send(data)
  })

  const handleResize = () => {
    if (fitAddon && term) {
      fitAddon.fit()
      send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    }
  }
  window.addEventListener('resize', handleResize)

  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (fitAddon) fitAddon.fit()
    })
    resizeObserver.observe(containerRef.value)
  }

  connect(
    (data: string | Uint8Array) => {
      term?.write(data)
    },
    () => {
      term?.write('\r\n\x1b[33m[连接已断开]\x1b[0m\r\n')
    },
  )
})

watch(connected, (val) => {
  if (val && term) {
    send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
    term.write(
      '\r\n\x1b[36m[OmicHub 沙盒] 已挂载 workspace 等工作目录；删除类操作（如 rm）将弹出确认，防止误删数据。\x1b[0m\r\n',
    )
  }
})

onBeforeUnmount(() => {
  disconnect()
  resizeObserver?.disconnect()
  term?.dispose()
})
</script>

<template>
  <div class="xterm-wrapper" ref="containerRef" />
</template>

<style scoped>
.xterm-wrapper {
  width: 100%;
  height: 100%;
  background-color: #1e1e1e;
  border-radius: 4px;
  padding: 8px;
}

.xterm-wrapper :deep(.xterm) {
  height: 100%;
}

.xterm-wrapper :deep(.xterm-viewport) {
  overflow-y: auto;
}
</style>
