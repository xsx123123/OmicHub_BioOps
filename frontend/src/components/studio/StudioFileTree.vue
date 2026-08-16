<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NIcon, NSpin, NTooltip } from 'naive-ui'
import {
  AddOutline, EyeOffOutline, EyeOutline, FolderOpenOutline, FolderOutline,
  RefreshOutline, ChevronForwardOutline, DocumentTextOutline,
} from '@vicons/ionicons5'
import { studioApi, type WorkspaceEntry } from '@/api/studio'

const props = defineProps<{
  sessionId: string
  refreshKey?: number
}>()
const emit = defineEmits<{
  select: [path: string]
  refresh: []
  import: []
  reference: [path: string]
}>()

interface TreeNode { path: string; name: string; type: 'file' | 'dir'; size: number; depth: number }
const rootEntries = ref<WorkspaceEntry[]>([])
const childrenMap = ref<Record<string, WorkspaceEntry[]>>({})
const expandedDirs = ref<Set<string>>(new Set())
const loadingDirs = ref<Set<string>>(new Set())
const loading = ref(false)
const showHidden = ref(false)
const contextMenu = ref<{ x: number; y: number; node: TreeNode } | null>(null)

function isHidden(name: string): boolean { return name.startsWith('.') || name === 'node_modules' }
function sortEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((a, b) => a.type !== b.type ? (a.type === 'dir' ? -1 : 1) : a.name.localeCompare(b.name))
}
async function loadDir(path: string): Promise<WorkspaceEntry[]> {
  const result = await studioApi.listFiles(props.sessionId, path)
  return sortEntries(result.entries || [])
}
async function loadRoot() {
  loading.value = true
  try {
    rootEntries.value = await loadDir('')
    for (const dir of expandedDirs.value) {
      try { childrenMap.value[dir] = await loadDir(dir) } catch { expandedDirs.value.delete(dir); delete childrenMap.value[dir] }
    }
  } catch { rootEntries.value = [] } finally { loading.value = false }
}
watch(() => [props.sessionId, props.refreshKey], () => { if (props.sessionId) loadRoot() }, { immediate: true })
async function toggleDir(node: TreeNode) {
  if (expandedDirs.value.has(node.path)) { expandedDirs.value.delete(node.path); return }
  expandedDirs.value.add(node.path)
  if (!childrenMap.value[node.path]) {
    loadingDirs.value.add(node.path)
    try { childrenMap.value[node.path] = await loadDir(node.path) } catch { childrenMap.value[node.path] = [] }
    finally { loadingDirs.value.delete(node.path) }
  }
}
const visibleNodes = computed<TreeNode[]>(() => {
  const out: TreeNode[] = []
  const walk = (entries: WorkspaceEntry[], parent: string, depth: number) => {
    for (const entry of entries) {
      if (!showHidden.value && isHidden(entry.name)) continue
      const path = parent ? `${parent}/${entry.name}` : entry.name
      out.push({ path, name: entry.name, type: entry.type, size: entry.size, depth })
      if (entry.type === 'dir' && expandedDirs.value.has(path) && childrenMap.value[path]) walk(childrenMap.value[path], path, depth + 1)
    }
  }
  walk(rootEntries.value, '', 0)
  return out
})
function iconFor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase()
  if (['py', 'r', 'sh', 'bash'].includes(ext || '')) return '⌘'
  if (['csv', 'tsv', 'xlsx'].includes(ext || '')) return '▦'
  if (['png', 'jpg', 'jpeg', 'svg', 'gif'].includes(ext || '')) return '◈'
  if (['json', 'yaml', 'yml', 'toml'].includes(ext || '')) return '{}'
  return '·'
}
function formatSize(size: number): string { return size < 1024 ? `${size}B` : size < 1048576 ? `${(size / 1024).toFixed(1)}K` : `${(size / 1048576).toFixed(1)}M` }
function openContext(node: TreeNode, event: MouseEvent) { contextMenu.value = { x: event.clientX, y: event.clientY, node } }
function closeContext() { contextMenu.value = null }
function parentPath(path: string) { return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '' }
async function createFile() {
  const path = window.prompt('新建文件路径（例如 scripts/analysis.py）')?.trim()
  if (!path) return
  await studioApi.writeFile(props.sessionId, { path, content: '' })
  emit('refresh'); await loadRoot(); emit('select', path)
}
async function createFolder() {
  const path = window.prompt('新建文件夹路径（例如 scripts）')?.trim()
  if (!path) return
  await studioApi.makeDirectory(props.sessionId, path)
  emit('refresh'); await loadRoot()
}
async function renameNode() {
  const node = contextMenu.value?.node
  if (!node) return
  const name = window.prompt('重命名为', node.name)?.trim()
  if (!name || name === node.name || name.includes('/')) return
  await studioApi.renameFile(props.sessionId, node.path, parentPath(node.path) ? `${parentPath(node.path)}/${name}` : name)
  closeContext(); emit('refresh'); await loadRoot()
}
async function deleteNode() {
  const node = contextMenu.value?.node
  if (!node || !window.confirm(`确认删除 ${node.path}？此操作不可撤销。`)) return
  await studioApi.deleteFile(props.sessionId, node.path)
  closeContext(); emit('refresh'); await loadRoot()
}
async function downloadNode() {
  const node = contextMenu.value?.node
  if (!node || node.type !== 'file') return
  await studioApi.downloadWorkspaceFile(props.sessionId, node.path); closeContext()
}
function referenceNode() {
  const node = contextMenu.value?.node
  if (node?.type === 'file') emit('reference', node.path)
  closeContext()
}
</script>

<template>
  <div class="studio-file-tree" @click="closeContext">
    <div class="tree-toolbar">
      <span class="tree-caption">工作区</span><span class="tree-spacer" />
      <n-tooltip trigger="hover">
        <template #trigger><n-button text size="tiny" @click.stop="createFile"><n-icon><AddOutline /></n-icon></n-button></template>
        新建文件
      </n-tooltip>
      <n-tooltip trigger="hover">
        <template #trigger><n-button text size="tiny" @click.stop="createFolder">＋□</n-button></template>
        新建文件夹
      </n-tooltip>
      <n-tooltip trigger="hover">
        <template #trigger><n-button text size="tiny" @click.stop="emit('import')"><n-icon><AddOutline /></n-icon></n-button></template>
        从数据管理引入
      </n-tooltip>
      <n-tooltip trigger="hover">
        <template #trigger><n-button text size="tiny" @click="emit('refresh'); loadRoot()"><n-icon><RefreshOutline /></n-icon></n-button></template>
        刷新文件树
      </n-tooltip>
      <n-tooltip trigger="hover">
        <template #trigger><n-button text size="tiny" :class="{ active: showHidden }" @click="showHidden = !showHidden"><n-icon><EyeOutline v-if="showHidden" /><EyeOffOutline v-else /></n-icon></n-button></template>
        {{ showHidden ? '隐藏内部文件' : '显示隐藏文件' }}
      </n-tooltip>
    </div>
    <div v-if="loading && !visibleNodes.length" class="tree-loading"><n-spin size="small" /></div>
    <div v-else-if="!visibleNodes.length" class="tree-empty">工作区暂无可见文件<br><small>发送消息或从数据管理引入文件</small></div>
    <div v-for="node in visibleNodes" :key="node.path" class="tree-node" :style="{ paddingLeft: `${8 + node.depth * 14}px` }" :title="node.path" @click="node.type === 'dir' ? toggleDir(node) : emit('select', node.path)" @contextmenu.prevent.stop="openContext(node, $event)">
      <n-icon v-if="node.type === 'dir'" size="12" class="node-caret" :class="{ open: expandedDirs.has(node.path) }"><ChevronForwardOutline /></n-icon><span v-else class="node-caret-placeholder" />
      <n-icon v-if="node.type === 'dir'" size="15" class="node-icon"><component :is="expandedDirs.has(node.path) ? FolderOpenOutline : FolderOutline" /></n-icon>
      <span v-else class="file-kind">{{ iconFor(node.name) }}</span>
      <span class="node-name">{{ node.name }}</span><n-spin v-if="loadingDirs.has(node.path)" :size="12" /><span v-else-if="node.type === 'file'" class="node-size">{{ formatSize(node.size) }}</span>
    </div>
    <div v-if="contextMenu" class="file-context-menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }" @click.stop>
      <button @click="emit('select', contextMenu.node.path); closeContext()">打开</button>
      <button @click="renameNode">重命名</button>
      <button v-if="contextMenu.node.type === 'file'" @click="downloadNode">下载</button>
      <button v-if="contextMenu.node.type === 'file'" @click="referenceNode">在对话中引用</button>
      <button class="danger" @click="deleteNode">删除</button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.studio-file-tree { display:flex; flex-direction:column; padding:4px 6px 10px; font-size:12px; }
.tree-toolbar { display:flex; align-items:center; gap:3px; min-height:30px; padding:0 3px; color:var(--studio-text-sub,#8a8aa3); }.tree-caption{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}.tree-spacer{flex:1}.tree-toolbar :deep(button){color:var(--studio-text-sub,#8a8aa3)}.tree-toolbar :deep(button.active){color:var(--studio-primary,#6c5ce7)}
.tree-loading{display:flex;justify-content:center;padding:18px}.tree-empty{padding:18px 8px;color:var(--studio-text-sub,#8a8aa3);line-height:1.6;text-align:center}.tree-empty small{font-size:11px}.tree-node{display:flex;align-items:center;gap:5px;min-height:29px;border-radius:7px;cursor:pointer;color:var(--studio-text,#2b2b3d);}.tree-node:hover{background:var(--studio-primary-soft,#f0edff);}.node-caret{transition:transform .18s ease;color:#aaa}.node-caret.open{transform:rotate(90deg);color:var(--studio-primary,#6c5ce7)}.node-caret-placeholder{width:12px}.node-icon{color:#9a8be8}.file-kind{display:inline-grid;place-items:center;width:15px;color:#6c5ce7;font-family:ui-monospace;font-size:11px;font-weight:700}.node-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.node-size{margin-left:auto;color:#b1afc0;font-size:10px}.tree-node :deep(.n-spin-container){margin-left:auto}
@media (prefers-reduced-motion: reduce){.node-caret{transition:none}}
.file-context-menu{position:fixed;z-index:30;display:grid;min-width:150px;padding:5px;border:1px solid var(--studio-border,#e8e8f2);border-radius:10px;background:rgba(255,255,255,.96);box-shadow:0 12px 30px rgba(43,43,61,.16);backdrop-filter:blur(14px)}.file-context-menu button{border:0;border-radius:6px;padding:7px 10px;text-align:left;background:transparent;color:var(--studio-text,#2b2b3d);font-size:12px;cursor:pointer}.file-context-menu button:hover{background:var(--studio-primary-soft,#f0edff);color:var(--studio-primary,#6c5ce7)}.file-context-menu button.danger:hover{color:#d45367;background:#fff0f2}
</style>
