<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NIcon, NTooltip } from 'naive-ui'
import {
  AddOutline, ChevronDownOutline, ChevronUpOutline, CloseOutline, PlayOutline,
  SaveOutline, StopOutline, TerminalOutline,
} from '@vicons/ionicons5'
import StudioMonacoEditor from './StudioMonacoEditor.vue'
import StudioMonacoDiffEditor from './StudioMonacoDiffEditor.vue'
import StudioTerminal from './StudioTerminal.vue'
import { studioApi } from '@/api/studio'
import type { ToolCall } from '@/components/ai-chat/types'

interface EditorTab {
  path: string
  content: string
  savedContent: string
  size: number
  pinned: boolean
  externallyChanged: boolean
  incomingContent?: string
  externalSavedContent?: string
  showDiff?: boolean
}

interface DiffHunk {
  startMine: number
  endMine: number
  startIncoming: number
  endIncoming: number
  oldLines: string[]
  newLines: string[]
}

const props = defineProps<{ sessionId: string; sandboxStatus: string; terminalCollapsed?: boolean }>()
const MAX_WORKSPACE_READ_LINES = 2000
const emit = defineEmits<{
  workspaceChanged: []
  userSaved: [path: string]
  requestFile: []
  runStarted: [tool: ToolCall]
  terminalCollapsedChanged: [collapsed: boolean]
}>()

const tabs = ref<EditorTab[]>([])
const activePath = ref('')
const loading = ref(false)
const line = ref(1)
const column = ref(1)
const terminalOpen = ref(!props.terminalCollapsed)
// 终端高度：默认容器 40%（≥280px、≤60%），可拖拽 160px~70%，写入 localStorage 记忆（问题⑧）
const TERMINAL_HEIGHT_KEY = 'omichub:studio:terminal-height'
const shellRef = ref<HTMLElement | null>(null)
const terminalDragging = ref(false)
function loadTerminalHeight(): number | null {
  const saved = Number(localStorage.getItem(TERMINAL_HEIGHT_KEY))
  return Number.isFinite(saved) && saved > 0 ? saved : null
}
function maxTerminalHeight(): number {
  return Math.max(160, Math.round((shellRef.value?.clientHeight || 600) * 0.7))
}
function defaultTerminalHeight(): number {
  const host = shellRef.value?.clientHeight || 0
  if (!host) return 280
  return Math.round(Math.min(host * 0.6, Math.max(280, host * 0.4)))
}
const terminalHeight = ref(280)
const terminalRef = ref<InstanceType<typeof StudioTerminal> | null>(null)
const terminalConnected = ref(false)
const isRunning = ref(false)
const exitCode = ref<number | null>(null)
const runArtifacts = ref<{ path: string; size: number; mtime: number }[]>([])
let activeCommandId = ''
let activeRunCard: ToolCall | null = null
let activeRunOutput = ''

watch(() => props.terminalCollapsed, (collapsed) => {
  if (collapsed !== undefined) terminalOpen.value = !collapsed
})

function setTerminalOpen(open: boolean) {
  terminalOpen.value = open
  emit('terminalCollapsedChanged', !open)
}

const activeTab = computed(() => tabs.value.find((tab) => tab.path === activePath.value) || null)
const dirty = computed(() => !!activeTab.value && activeTab.value.content !== activeTab.value.savedContent)
const breadcrumb = computed(() => activePath.value.split('/').filter(Boolean))
function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`
}

const runCommand = computed(() => {
  if (!activeTab.value) return ''
  const path = shellQuote(activeTab.value.path)
  if (runLanguage(activeTab.value.path) === 'r') return `Rscript ${path}`
  if (runLanguage(activeTab.value.path) === 'bash') return `bash ${path}`
  return `python -u ${path}`
})

function buildLineHunks(mineText: string, incomingText: string): DiffHunk[] {
  const mine = mineText.split('\n')
  const incoming = incomingText.split('\n')
  const hunks: DiffHunk[] = []
  let mineIndex = 0
  let incomingIndex = 0
  const lookahead = 12
  while (mineIndex < mine.length || incomingIndex < incoming.length) {
    if (mine[mineIndex] === incoming[incomingIndex]) {
      mineIndex += 1
      incomingIndex += 1
      continue
    }
    const startMine = mineIndex
    const startIncoming = incomingIndex
    let alignedMine = mine.length
    let alignedIncoming = incoming.length
    let bestDistance = Number.POSITIVE_INFINITY
    for (let mineOffset = 0; mineOffset <= lookahead && mineIndex + mineOffset < mine.length; mineOffset += 1) {
      for (let incomingOffset = 0; incomingOffset <= lookahead && incomingIndex + incomingOffset < incoming.length; incomingOffset += 1) {
        if (mineOffset === 0 && incomingOffset === 0) continue
        if (mine[mineIndex + mineOffset] === incoming[incomingIndex + incomingOffset]) {
          const distance = mineOffset + incomingOffset
          if (distance < bestDistance) {
            bestDistance = distance
            alignedMine = mineIndex + mineOffset
            alignedIncoming = incomingIndex + incomingOffset
          }
        }
      }
    }
    if (bestDistance === Number.POSITIVE_INFINITY) {
      alignedMine = mine.length
      alignedIncoming = incoming.length
    }
    hunks.push({
      startMine,
      endMine: alignedMine,
      startIncoming,
      endIncoming: alignedIncoming,
      oldLines: mine.slice(startMine, alignedMine),
      newLines: incoming.slice(startIncoming, alignedIncoming),
    })
    mineIndex = alignedMine
    incomingIndex = alignedIncoming
  }
  return hunks
}

const diffHunks = computed(() => {
  const tab = activeTab.value
  if (!tab?.incomingContent || tab.showDiff) return []
  return buildLineHunks(tab.content, tab.incomingContent)
})
function languageFor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase()
  return ({ py: 'python', r: 'r', sh: 'shell', bash: 'shell', js: 'javascript', ts: 'typescript', vue: 'html', json: 'json', yaml: 'yaml', yml: 'yaml', md: 'markdown', html: 'html', css: 'css', scss: 'scss' } as Record<string, string>)[ext || ''] || 'plaintext'
}
function runLanguage(path: string): 'python' | 'r' | 'bash' {
  const ext = path.split('.').pop()?.toLowerCase()
  if (ext === 'r') return 'r'
  if (ext === 'sh' || ext === 'bash') return 'bash'
  return 'python'
}
function canRun(path: string): boolean { return /\.(py|r|sh|bash)$/i.test(path) }
function fileName(path: string): string { return path.split('/').pop() || path }
function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  return `${(size / 1024).toFixed(1)} KB`
}

let externallyChangedTimer: number | null = null

async function openFile(path: string, pin = false, externallyChanged = false, activate = true) {
  let tab = tabs.value.find((item) => item.path === path)
  if (tab && externallyChanged) {
    loading.value = true
    try {
      const result = await studioApi.readFile(props.sessionId, path, 0, MAX_WORKSPACE_READ_LINES)
      if (result.content !== tab.savedContent) {
        if (tab.content !== tab.savedContent) {
          tab.externallyChanged = true
          tab.incomingContent = result.content
          tab.externalSavedContent = result.content
          tab.showDiff = buildLineHunks(tab.content, result.content).reduce((total, hunk) => total + hunk.oldLines.length + hunk.newLines.length, 0) >= 20
        } else {
          tab.content = result.content
          tab.savedContent = result.content
          tab.size = new Blob([result.content]).size
          tab.externallyChanged = true
          if (externallyChangedTimer) clearTimeout(externallyChangedTimer)
          externallyChangedTimer = window.setTimeout(() => { if (tab) tab.externallyChanged = false }, 1800)
        }
      }
    } finally {
      loading.value = false
    }
  } else if (!tab) {
    loading.value = true
    try {
      const result = await studioApi.readFile(props.sessionId, path, 0, MAX_WORKSPACE_READ_LINES)
      const incoming: EditorTab = {
        path,
        content: result.content,
        savedContent: result.content,
        size: new Blob([result.content]).size,
        pinned: pin,
        externallyChanged,
        externalSavedContent: externallyChanged ? result.content : undefined,
      }
      if (!pin) {
        const previewIndex = tabs.value.findIndex((item) => !item.pinned && item.content === item.savedContent)
        if (previewIndex >= 0) tabs.value.splice(previewIndex, 1, incoming)
        else tabs.value.push(incoming)
      } else tabs.value.push(incoming)
      tab = incoming
    } finally {
      loading.value = false
    }
  } else if (pin) tab.pinned = true
  if (activate) activePath.value = path
  await nextTick()
}

async function markFileChanged(path: string) {
  if (!tabs.value.some((tab) => tab.path === path)) return
  await openFile(path, false, true, false)
}

function finishIncomingIfResolved(tab: EditorTab) {
  if (!tab.incomingContent || tab.content !== tab.incomingContent) return
  tab.savedContent = tab.externalSavedContent || tab.incomingContent
  tab.incomingContent = undefined
  tab.externalSavedContent = undefined
  tab.externallyChanged = false
  tab.showDiff = false
}

function acceptHunk(index: number) {
  const tab = activeTab.value
  const hunk = diffHunks.value[index]
  if (!tab?.incomingContent || !hunk) return
  const lines = tab.content.split('\n')
  lines.splice(hunk.startMine, hunk.endMine - hunk.startMine, ...hunk.newLines)
  tab.content = lines.join('\n')
  finishIncomingIfResolved(tab)
}

function rejectHunk(index: number) {
  const tab = activeTab.value
  const hunk = diffHunks.value[index]
  if (!tab?.incomingContent || !hunk) return
  const lines = tab.incomingContent.split('\n')
  lines.splice(hunk.startIncoming, hunk.endIncoming - hunk.startIncoming, ...hunk.oldLines)
  tab.incomingContent = lines.join('\n')
  if (tab.content === tab.incomingContent) {
    tab.incomingContent = undefined
    tab.externalSavedContent = undefined
    tab.externallyChanged = false
    tab.showDiff = false
  }
}

function acceptIncoming() {
  const tab = activeTab.value
  if (!tab?.incomingContent) return
  tab.content = tab.incomingContent
  tab.savedContent = tab.incomingContent
  tab.size = new Blob([tab.incomingContent]).size
  tab.incomingContent = undefined
  tab.externalSavedContent = undefined
  tab.externallyChanged = false
  tab.showDiff = false
}

function keepMine() {
  const tab = activeTab.value
  if (!tab?.incomingContent) return
  tab.savedContent = tab.externalSavedContent || tab.incomingContent
  tab.incomingContent = undefined
  tab.externallyChanged = false
  tab.showDiff = false
}

async function copyIncomingToNewFile() {
  const tab = activeTab.value
  if (!tab?.incomingContent) return
  const suggested = tab.path.replace(/(\.[^./]+)?$/, '_ai$1')
  const path = window.prompt('复制 AI 版本到新文件', suggested)?.trim()
  if (!path) return
  await studioApi.writeFile(props.sessionId, { path, content: tab.incomingContent })
  emit('workspaceChanged')
  await openFile(path, true)
}

function closeTab(path: string) {
  const index = tabs.value.findIndex((tab) => tab.path === path)
  if (index < 0) return
  if (tabs.value[index].content !== tabs.value[index].savedContent && !window.confirm('文件尚未保存，仍要关闭吗？')) return
  tabs.value.splice(index, 1)
  if (activePath.value === path) activePath.value = tabs.value[Math.max(0, index - 1)]?.path || ''
}

async function saveActive() {
  const tab = activeTab.value
  if (!tab || tab.content === tab.savedContent) return
  const result = await studioApi.writeFile(props.sessionId, { path: tab.path, content: tab.content })
  tab.savedContent = tab.content
  tab.size = result.size
  tab.externallyChanged = false
  tab.incomingContent = undefined
  tab.externalSavedContent = undefined
  tab.showDiff = false
  emit('workspaceChanged')
  emit('userSaved', tab.path)
}

async function runActive(_selection?: string) {
  const tab = activeTab.value
  if (!tab || !canRun(tab.path) || isRunning.value) return
  await saveActive()
  terminalOpen.value = true
  exitCode.value = null
  runArtifacts.value = []
  await nextTick()

  const runCard: ToolCall = {
    id: `editor-run-${Date.now()}`,
    name: 'sandbox_execute',
    arguments: { path: tab.path, command: runCommand.value, language: runLanguage(tab.path) },
    status: 'running',
    output: '',
  }
  activeRunCard = runCard
  activeRunOutput = ''
  isRunning.value = true
  emit('runStarted', runCard)
  activeCommandId = terminalRef.value?.runCommand(runCommand.value) || ''
  if (!activeCommandId) {
    isRunning.value = false
    runCard.status = 'error'
    runCard.result = 'Studio 终端尚未就绪'
  }
}

function handleTerminalOutput(data: string) {
  if (!isRunning.value || !activeRunCard) return
  activeRunOutput = `${activeRunOutput}${data}`.slice(-20_000)
  activeRunCard.output = activeRunOutput
}

async function handleCommandExit(commandId: string, code: number) {
  if (!activeRunCard || commandId !== activeCommandId) return
  exitCode.value = code
  isRunning.value = false
  activeRunCard.status = code === 0 ? 'success' : 'error'
  activeRunCard.result = { exit_code: code, command: runCommand.value }
  activeRunCard = null
  activeCommandId = ''
  runArtifacts.value = await studioApi.listArtifacts(props.sessionId).catch(() => [])
  emit('workspaceChanged')
}

function stopActive() {
  terminalRef.value?.interrupt()
}

function startTerminalResize(event: PointerEvent) {
  const startY = event.clientY
  const startHeight = terminalHeight.value
  const target = event.currentTarget as HTMLElement
  target.setPointerCapture(event.pointerId)
  terminalDragging.value = true
  const move = (next: PointerEvent) => {
    terminalHeight.value = Math.min(maxTerminalHeight(), Math.max(160, startHeight + startY - next.clientY))
  }
  const up = (next: PointerEvent) => {
    target.releasePointerCapture(next.pointerId)
    target.removeEventListener('pointermove', move)
    target.removeEventListener('pointerup', up)
    terminalDragging.value = false
    localStorage.setItem(TERMINAL_HEIGHT_KEY, String(terminalHeight.value))
  }
  target.addEventListener('pointermove', move)
  target.addEventListener('pointerup', up)
}

onMounted(() => {
  // 恢复用户上次拖拽的高度（越界钳制），否则按容器 40% 计算默认高度
  const saved = loadTerminalHeight()
  terminalHeight.value = saved !== null
    ? Math.min(maxTerminalHeight(), Math.max(160, saved))
    : defaultTerminalHeight()
})

onUnmounted(() => {
  if (externallyChangedTimer) clearTimeout(externallyChangedTimer)
})

defineExpose({ openFile, markFileChanged })
</script>

<template>
  <section ref="shellRef" class="workspace-editor-shell">
    <div class="editor-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.path"
        class="editor-tab"
        :class="{ active: tab.path === activePath, preview: !tab.pinned }"
        @click="activePath = tab.path"
        @dblclick="tab.pinned = true"
      >
        <span>{{ fileName(tab.path) }}</span>
        <i v-if="tab.content !== tab.savedContent || tab.externallyChanged" class="dirty-dot" />
        <n-icon size="13" class="tab-close" @click.stop="closeTab(tab.path)"><CloseOutline /></n-icon>
      </button>
      <n-tooltip trigger="hover"><template #trigger><n-button text class="new-tab" @click="emit('requestFile')"><n-icon><AddOutline /></n-icon></n-button></template>打开工作区文件</n-tooltip>
      <span class="tabs-spacer" />
      <n-button text size="small" @click="setTerminalOpen(!terminalOpen)"><n-icon><TerminalOutline /></n-icon>终端</n-button>
    </div>

    <template v-if="activeTab">
      <div v-if="activeTab.incomingContent !== undefined" class="conflict-banner">
        <span>AI 在你编辑期间修改了此文件，未覆盖你的版本。</span>
        <div><button @click="activeTab.showDiff = !activeTab.showDiff">{{ activeTab.showDiff ? '收起 Diff' : '查看 Diff' }}</button><button @click="copyIncomingToNewFile">复制新文件</button><button @click="acceptIncoming">接受 AI 版本</button><button class="primary" @click="keepMine">保留我的版本</button></div>
      </div>
      <div v-if="diffHunks.length" class="inline-diff">
        <div v-for="(hunk, hunkIndex) in diffHunks" :key="`${hunkIndex}-${hunk.startMine}-${hunk.startIncoming}`" class="diff-hunk">
          <div class="diff-hunk-lines">
            <div v-for="(lineText, index) in hunk.oldLines" :key="`old-${index}`" class="old"><b>−</b><code>{{ lineText }}</code></div>
            <div v-for="(lineText, index) in hunk.newLines" :key="`new-${index}`" class="new"><b>+</b><code>{{ lineText }}</code></div>
          </div>
          <div class="diff-hunk-actions"><button @click="acceptHunk(hunkIndex)">接受此块</button><button @click="rejectHunk(hunkIndex)">拒绝此块</button></div>
        </div>
      </div>
      <div v-if="activeTab.showDiff && activeTab.incomingContent !== undefined" class="conflict-diff">
        <StudioMonacoDiffEditor :original="activeTab.content" :modified="activeTab.incomingContent" :language="languageFor(activeTab.path)" />
      </div>
      <div class="editor-toolbar">
        <div class="breadcrumb"><span>工作区</span><template v-for="part in breadcrumb" :key="part"><b>›</b><span>{{ part }}</span></template></div>
        <div class="editor-actions">
          <n-tooltip trigger="hover"><template #trigger><n-button text :disabled="!dirty" @click="saveActive"><n-icon><SaveOutline /></n-icon></n-button></template>保存 Ctrl/Cmd+S</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><n-button text :disabled="!canRun(activeTab.path)" :loading="isRunning" @click="runActive()"><n-icon><PlayOutline /></n-icon></n-button></template>运行 Ctrl/Cmd+Enter</n-tooltip>
          <n-button v-if="isRunning" text type="error" @click="stopActive"><n-icon><StopOutline /></n-icon></n-button>
        </div>
      </div>
      <div v-show="!activeTab.showDiff" class="monaco-wrap" :class="{ 'with-terminal': terminalOpen }">
        <StudioMonacoEditor
          v-model="activeTab.content"
          :language="languageFor(activeTab.path)"
          @save="saveActive"
          @run="runActive"
          @cursor="(l, c) => { line = l; column = c }"
        />
      </div>
      <div v-if="terminalOpen" class="terminal-panel" :class="{ dragging: terminalDragging }" :style="{ height: `${terminalHeight}px` }">
        <div class="terminal-resize" @pointerdown="startTerminalResize" />
        <div class="terminal-titlebar">
          <div class="traffic"><i /><i /><i /></div>
          <span>终端 · BASH</span><span class="terminal-connection" :class="{ connected: terminalConnected }">{{ terminalConnected ? '已连接沙箱' : '连接中' }}</span>
          <span class="terminal-command">{{ runCommand }}</span>
          <span class="terminal-spacer" />
          <button @click="terminalRef?.clear()">清空</button>
          <span v-if="exitCode !== null" class="exit-badge" :class="exitCode === 0 ? 'success' : 'error'">Exit {{ exitCode }}</span>
          <button @click="setTerminalOpen(false)"><n-icon><ChevronDownOutline /></n-icon></button>
        </div>
        <StudioTerminal
          ref="terminalRef"
          :session-id="sessionId"
          @connected="terminalConnected = $event"
          @output="handleTerminalOutput"
          @command-exit="handleCommandExit"
        />
        <div v-if="runArtifacts.length" class="terminal-artifacts"><span>产物</span><button v-for="item in runArtifacts" :key="item.path">{{ fileName(item.path) }}</button></div>
      </div>
      <footer class="editor-statusbar">
        <span :class="['status-dot', sandboxStatus]" />{{ sandboxStatus === 'running' ? '沙盒运行中' : '按运行自动唤醒' }}
        <span>{{ runLanguage(activeTab.path) === 'python' ? 'Python 3.12' : runLanguage(activeTab.path).toUpperCase() }}</span><span>行 {{ line }}, 列 {{ column }}</span><span>{{ formatSize(activeTab.size) }}</span><span>UTF-8</span>
      </footer>
    </template>

    <div v-else class="editor-empty">
      <div class="star-orbit">✦</div>
      <h3>从工作区打开一个脚本</h3>
      <p>单击文件临时预览，双击固定为 Tab；保存与运行都在同一处完成。</p>
      <n-button type="primary" secondary @click="emit('requestFile')">选择文件</n-button>
    </div>
  </section>
</template>

<style scoped lang="scss">
.workspace-editor-shell { height: 100%; min-width: 0; display: flex; flex-direction: column; background: var(--studio-card, #fff); color: var(--studio-text, #2b2b3d); }
.editor-tabs { height: 38px; display: flex; align-items: stretch; border-bottom: 1px solid var(--studio-border, #e8e8f2); background: rgba(248,247,252,.88); backdrop-filter: blur(18px); }
.editor-tab { position: relative; display: flex; align-items: center; gap: 8px; max-width: 180px; padding: 0 10px; border: 0; border-right: 1px solid var(--studio-border, #e8e8f2); background: transparent; color: var(--studio-text-sub, #8a8aa3); cursor: default; }
.editor-tab.preview span { font-style: italic; }.editor-tab.active { color: var(--studio-text, #2b2b3d); background: #fff; box-shadow: inset 0 2px var(--studio-primary, #6c5ce7); }.editor-tab:active,.new-tab:active { transform: scale(.97); }
.tab-close { opacity: 0; }.editor-tab:hover .tab-close,.editor-tab.active .tab-close { opacity: .65; }.dirty-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--studio-primary, #6c5ce7); }.new-tab { width: 36px; }.tabs-spacer,.terminal-spacer { flex: 1; }
.editor-toolbar { height: 40px; display: flex; align-items: center; padding: 0 10px 0 14px; border-bottom: 1px solid var(--studio-border, #e8e8f2); }.breadcrumb { display: flex; gap: 7px; min-width: 0; font-size: 12px; color: var(--studio-text-sub, #8a8aa3); }.breadcrumb span:last-child { color: var(--studio-text, #2b2b3d); }.editor-actions { margin-left: auto; display: flex; gap: 2px; }
.conflict-banner { display:flex; align-items:center; gap:12px; padding:8px 14px; border-bottom:1px solid #f2cf7a; background:#fff8df; color:#7a5a10; font-size:12px; }.conflict-banner > div{margin-left:auto;display:flex;gap:6px}.conflict-banner button{border:1px solid #dbc06e;border-radius:7px;padding:4px 8px;background:rgba(255,255,255,.7);color:#6c5313;cursor:pointer}.conflict-banner button.primary{border-color:var(--studio-primary,#6c5ce7);background:var(--studio-primary,#6c5ce7);color:#fff}.inline-diff{max-height:180px;overflow:auto;border-bottom:1px solid var(--studio-border,#e8e8f2);font:11px/1.55 SFMono-Regular,Menlo,monospace}.inline-diff>div{display:flex;gap:8px;padding:2px 12px}.diff-hunk{border-bottom:1px solid var(--studio-border,#e8e8f2)}.diff-hunk-lines>div{display:flex;gap:8px;padding:2px 12px}.diff-hunk-actions{display:flex;justify-content:flex-end;gap:6px;padding:4px 10px}.diff-hunk-actions button{border:1px solid var(--studio-border,#e8e8f2);border-radius:6px;padding:3px 8px;background:#fff;color:var(--studio-primary,#6c5ce7);cursor:pointer}.inline-diff .old{background:#fff0f1;color:#9a3342}.inline-diff .new{background:#edf9f3;color:#23704d}.inline-diff code{white-space:pre-wrap}.conflict-diff{flex:1;min-height:260px;overflow:hidden;border-bottom:1px solid var(--studio-border,#e8e8f2)}.monaco-wrap { flex: 1; min-height: 180px; }.terminal-panel { position: relative; flex-shrink: 0; display: flex; flex-direction: column; background: var(--studio-terminal, #1b1b2e); color: #d7d6e8; transition: height .2s ease; }.terminal-panel.dragging { transition: none; }.terminal-resize { position: absolute; top: -3px; width: 100%; height: 6px; cursor: row-resize; touch-action: none; }.terminal-resize:hover { background: rgba(76,111,255,.35); }.terminal-titlebar { height: 34px; display: flex; align-items: center; gap: 9px; padding: 0 10px; border-bottom: 1px solid rgba(255,255,255,.08); font-size: 11px; }.traffic { display: flex; gap: 5px; }.traffic i { width: 8px; height: 8px; border-radius: 50%; background: #ff5f57; }.traffic i:nth-child(2){background:#febc2e}.traffic i:nth-child(3){background:#28c840}.terminal-command { color: #85839a; font-family: monospace; }.terminal-titlebar button { border: 0; background: transparent; color: inherit; }.terminal-connection { color: #f8d57e; }.terminal-connection.connected { color: #83e1a9; }.exit-badge { padding: 2px 7px; border-radius: 999px; }.exit-badge.success { background: rgba(46,204,113,.18); color: #83e1a9; }.exit-badge.error { background: rgba(255,107,107,.18); color: #ff9d9d; }.terminal-artifacts { display: flex; gap: 6px; padding: 7px 12px; border-top: 1px solid rgba(255,255,255,.08); font-size: 11px; }.terminal-artifacts button { border: 0; border-radius: 999px; padding: 3px 8px; color: #d8d4ff; background: rgba(108,92,231,.22); }
.editor-statusbar { height: 24px; display: flex; align-items: center; gap: 12px; padding: 0 10px; color: var(--studio-text-sub, #8a8aa3); background: #f8f7fc; border-top: 1px solid var(--studio-border, #e8e8f2); font-size: 10px; }.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #aaa; }.status-dot.running { background: #2ecc71; box-shadow: 0 0 0 3px rgba(46,204,113,.12); }
.editor-empty { flex: 1; display: grid; place-content: center; justify-items: center; padding: 32px; text-align: center; background: radial-gradient(circle at 50% 35%, #f0edff, #fff 48%); }.editor-empty h3 { margin: 8px 0 4px; }.editor-empty p { max-width: 420px; color: var(--studio-text-sub, #8a8aa3); }.star-orbit { font-size: 38px; color: var(--studio-primary, #6c5ce7); filter: drop-shadow(0 8px 18px rgba(108,92,231,.25)); }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; } }
</style>
