<script setup lang="ts">
/**
 * StudioCodeCard — Studio 代码卡片（工作台核心交互）
 *
 * 渲染 sandbox_execute / workspace_write / workspace_edit 三类 Studio 工具调用：
 *  - 头部：文件名 / 语言徽章 / 退出码徽章 / 工具类型
 *  - 代码区：CodeMirror（默认只读，「编辑」解锁，「重跑」走 /studio/sessions/{id}/run SSE）
 *  - workspace_edit：diff2html 展示改动，支持接受或拒绝并安全回滚
 *  - 输出区：stdout/stderr 实时累计（ANSI 转义剥离、自动滚动、可折叠）
 *  - 产物：执行完成后的产物 chips，点击下载
 */
import { ref, computed, watch, nextTick, inject, onUnmounted } from 'vue'
import DOMPurify from 'dompurify'
import { NButton, NIcon, NTag, NTooltip, useMessage } from 'naive-ui'
import { html as diffToHtml } from 'diff2html'
import 'diff2html/bundles/css/diff2html.min.css'
import {
  CreateOutline, PlayOutline, CopyOutline, ChevronDownOutline, ChevronUpOutline,
  CheckmarkOutline, CloseOutline, DocumentOutline, ReturnDownBackOutline,
} from '@vicons/ionicons5'
import CodeEditor from '@/components/sandbox/CodeEditor.vue'
import TaskProgressCard from '@/components/ai-chat/TaskProgressCard.vue'
import { useStudioRunStream, type StudioRunUiPayload } from '@/composables/useStudioRunStream'
import { studioApi } from '@/api/studio'
import { StudioContextKey } from './context'
import type { ToolCall } from '@/components/ai-chat/types'

const props = defineProps<{ tool: ToolCall }>()

const ctx = inject(StudioContextKey, null)
const message = useMessage()

const TOOL_LABELS: Record<string, string> = {
  sandbox_execute: '沙盒执行',
  workspace_write: '写入文件',
  workspace_edit: '修改文件',
}

const toolLabel = computed(() => TOOL_LABELS[props.tool.name] || props.tool.name)
const isEditTool = computed(() => props.tool.name === 'workspace_edit')
const asyncTaskId = computed(() => String(props.tool.uiPayload?.task_id || ''))
const isAsyncTask = computed(() => props.tool.name === 'sandbox_execute' && !!asyncTaskId.value)

function handleAsyncCompleted() {
  ctx?.refreshWorkspace()
}

/** 语言：优先工具参数 / ui_payload，其次按文件扩展名推断，默认 python */
const language = computed(() => {
  const l = (props.tool.arguments?.language ?? props.tool.uiPayload?.language) as string | undefined
  if (l) return String(l).toLowerCase()
  const path = String(props.tool.arguments?.path || '')
  const ext = path.split('.').pop()?.toLowerCase() || ''
  if (ext === 'r') return 'r'
  if (['sh', 'bash'].includes(ext)) return 'bash'
  return 'python'
})

const LANG_BADGES: Record<string, string> = { python: 'Python', r: 'R', bash: 'Bash' }
const languageBadge = computed(() => LANG_BADGES[language.value] || language.value)

/** 文件名：写/改文件取 basename；执行单元格命名 code_cell.{ext} */
const fileName = computed(() => {
  const p = props.tool.arguments?.path as string | undefined
  if (p) return p.split('/').pop() || p
  const ext = language.value === 'r' ? 'R' : language.value === 'bash' ? 'sh' : 'py'
  return `code_cell.${ext}`
})

const code = computed(() => String(props.tool.arguments?.code ?? props.tool.arguments?.content ?? ''))
const diffText = computed(() => String(props.tool.uiPayload?.diff ?? ''))
const editPayload = computed(() => ({
  path: String(props.tool.arguments?.path ?? ''),
  old_string: String(props.tool.arguments?.old_string ?? ''),
  new_string: String(props.tool.arguments?.new_string ?? ''),
}))
const rollbackPayload = computed(() => {
  const reverse = props.tool.uiPayload?.reverse_edit as Record<string, unknown> | undefined
  if (reverse && typeof reverse.old_string === 'string' && typeof reverse.new_string === 'string') {
    return {
      path: editPayload.value.path,
      old_string: reverse.old_string,
      new_string: reverse.new_string,
    }
  }
  return {
    path: editPayload.value.path,
    old_string: editPayload.value.new_string,
    new_string: editPayload.value.old_string,
  }
})
const diffHtml = computed(() => {
  if (!diffText.value) return ''
  return DOMPurify.sanitize(diffToHtml(diffText.value, {
    drawFileList: false,
    matching: 'lines',
    outputFormat: 'line-by-line',
  }))
})

/** workspace_write 且内容可执行时同样允许重跑 */
const canRerun = computed(
  () => props.tool.name === 'sandbox_execute'
    || (props.tool.name === 'workspace_write' && ['python', 'r', 'bash'].includes(language.value)),
)

// ---------- 编辑 / 重跑 ----------
const editing = ref(false)
const editorCode = ref(code.value)
watch(code, (v) => {
  if (!editing.value) editorCode.value = v
})

const copied = ref(false)
const editDecision = ref<'pending' | 'accepted' | 'rejected'>('pending')
const reverting = ref(false)
const restoringCheckpoint = ref(false)
let copyTimer: ReturnType<typeof setTimeout> | null = null

function handleCopy() {
  navigator.clipboard.writeText(isEditTool.value ? diffText.value : editorCode.value)
  copied.value = true
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copied.value = false }, 1500)
}

function acceptEdit() {
  editDecision.value = 'accepted'
  message.success('已接受文件修改')
}

async function rejectEdit() {
  if (!ctx || reverting.value || editDecision.value !== 'pending') return
  const payload = rollbackPayload.value
  if (!payload.path || !payload.old_string) {
    message.error('缺少可回滚的编辑信息')
    return
  }
  reverting.value = true
  try {
    await studioApi.editFile(ctx.sessionId.value, {
      path: payload.path,
      old_string: payload.new_string,
      new_string: payload.old_string,
    })
    editDecision.value = 'rejected'
    message.success('已拒绝修改并恢复原文件')
    ctx.refreshWorkspace()
  } catch {
    message.error('回滚失败：文件可能已被后续修改，请先检查当前文件')
  } finally {
    reverting.value = false
  }
}

async function restoreCheckpoint() {
  if (!ctx || !props.tool.checkpointId || restoringCheckpoint.value) return
  if (!window.confirm('将工作区文件回退到此检查点？对话记录不会删除。')) return
  restoringCheckpoint.value = true
  try {
    await studioApi.restoreCheckpoint(ctx.sessionId.value, props.tool.checkpointId)
    ctx.refreshWorkspace()
    message.success('工作区已回退到该检查点')
  } catch {
    message.error('检查点回退失败，请检查工作区状态')
  } finally {
    restoringCheckpoint.value = false
  }
}

watch(
  () => props.tool.id,
  () => {
    editDecision.value = 'pending'
  },
)

const { isRunning, run, abort } = useStudioRunStream()
const rerunHappened = ref(false)
const rerunOutput = ref('')
const RERUN_OUTPUT_CAP = 20_000

function appendBoundedRerunOutput(data: string): void {
  const combined = rerunOutput.value + data
  rerunOutput.value =
    combined.length <= RERUN_OUTPUT_CAP
      ? combined
      : `…\n${combined.slice(-(RERUN_OUTPUT_CAP - 2))}`
}
const rerunExitCode = ref<number | undefined>(undefined)
const rerunArtifacts = ref<{ path: string; size: number; mtime: number }[]>([])

async function handleRerun() {
  if (!ctx || isRunning.value) return
  rerunHappened.value = true
  rerunOutput.value = ''
  rerunExitCode.value = undefined
  showOutput.value = true
  const lang = (['python', 'r', 'bash'].includes(language.value) ? language.value : 'python') as
    'python' | 'r' | 'bash'
  await run(
    { sessionId: ctx.sessionId.value, code: editorCode.value, language: lang },
    {
      onOutput: (_stream, data) => {
        appendBoundedRerunOutput(data)
      },
      onResult: ({ success, uiPayload }: { success: boolean; result: unknown; uiPayload?: StudioRunUiPayload }) => {
        rerunExitCode.value = uiPayload?.exit_code ?? (success ? 0 : 1)
        rerunArtifacts.value = uiPayload?.artifacts || []
        if (!rerunOutput.value && uiPayload) {
          rerunOutput.value = (uiPayload.stdout || '') + (uiPayload.stderr || '')
        }
        ctx.refreshWorkspace()
      },
      onError: (error) => {
        appendBoundedRerunOutput(`\n[错误] ${error}\n`)
        rerunExitCode.value = 1
        ctx?.refreshWorkspace()
      },
    },
  )
}

// ---------- 输出区 ----------
function stripAnsi(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\x1B(?:\[[0-9;]*[A-Za-z]|\][^\x07]*\x07)/g, '')
}

/** 基础输出：流式累计的 tool.output，缺失时回退 ui_payload 的 stdout/stderr */
const baseOutput = computed(() => {
  if (props.tool.output) return props.tool.output
  const up = props.tool.uiPayload || {}
  const so = typeof up.stdout === 'string' ? (up.stdout as string) : ''
  const se = typeof up.stderr === 'string' ? (up.stderr as string) : ''
  return so + se
})

const displayOutput = computed(() => {
  // 归一化 \r\n / \r：PTY 风格的输出若直接 split('\n') 会把多行误算成 1 行（问题⑨）
  const raw = (rerunHappened.value ? rerunOutput.value : baseOutput.value)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
  return stripAnsi(raw)
})

const outputLines = computed(() => (displayOutput.value ? displayOutput.value.split('\n').length : 0))
const showOutput = ref(true)
const outputRef = ref<HTMLElement | null>(null)

watch(displayOutput, () => {
  nextTick(() => {
    if (outputRef.value) outputRef.value.scrollTop = outputRef.value.scrollHeight
  })
})

// ---------- 状态与产物 ----------
const exitCode = computed(() =>
  rerunExitCode.value ?? (props.tool.uiPayload?.exit_code as number | undefined),
)

const statusText = computed(() => {
  if (isRunning.value || props.tool.status === 'running') return '执行中'
  if (exitCode.value != null) return exitCode.value === 0 ? '成功' : `退出码 ${exitCode.value}`
  if (props.tool.status === 'success') return '成功'
  if (props.tool.status === 'error') return '失败'
  return ''
})

const statusTagType = computed(() => {
  if (isRunning.value || props.tool.status === 'running') return 'warning'
  if (exitCode.value != null) return exitCode.value === 0 ? 'success' : 'error'
  if (props.tool.status === 'error') return 'error'
  return 'success'
})

const artifacts = computed(() => {
  if (rerunHappened.value) return rerunArtifacts.value
  return (props.tool.uiPayload?.artifacts as { path: string; size: number; mtime: number }[] | undefined) || []
})

const imageArtifacts = computed(() => artifacts.value.filter((artifact) => /\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.path)))
const imagePreviewUrls = ref<Record<string, string>>({})

function revokeImagePreviewUrls() {
  Object.values(imagePreviewUrls.value).forEach((url) => URL.revokeObjectURL(url))
  imagePreviewUrls.value = {}
}

async function loadImagePreviews() {
  const activeSessionId = ctx?.sessionId.value
  if (!activeSessionId || !imageArtifacts.value.length) {
    revokeImagePreviewUrls()
    return
  }
  const currentPaths = new Set(imageArtifacts.value.map((artifact) => artifact.path))
  for (const [path, url] of Object.entries(imagePreviewUrls.value)) {
    if (!currentPaths.has(path)) {
      URL.revokeObjectURL(url)
      delete imagePreviewUrls.value[path]
    }
  }
  await Promise.all(imageArtifacts.value.map(async (artifact) => {
    if (imagePreviewUrls.value[artifact.path]) return
    try {
      imagePreviewUrls.value[artifact.path] = await studioApi.fetchArtifactBlob(activeSessionId, artifact.path)
    } catch {
      try {
        imagePreviewUrls.value[artifact.path] = await studioApi.fetchWorkspaceBlob(activeSessionId, artifact.path)
      } catch {}
    }
  }))
}

watch(
  () => [ctx?.sessionId.value, imageArtifacts.value.map((artifact) => artifact.path).join('|')],
  () => { void loadImagePreviews() },
  { immediate: true },
)

function handleDownloadArtifact(path: string) {
  if (!ctx) return
  studioApi.downloadArtifact(ctx.sessionId.value, path).catch(() => {})
}

onUnmounted(() => {
  abort()
  if (copyTimer) clearTimeout(copyTimer)
  revokeImagePreviewUrls()
})
</script>

<template>
  <div class="studio-code-card">
    <div class="card-header">
      <n-icon size="15" class="file-icon"><DocumentOutline /></n-icon>
      <span class="file-name" :title="String(tool.arguments?.path || '')">{{ fileName }}</span>
      <n-tag size="tiny" round :bordered="false" type="info">{{ languageBadge }}</n-tag>
      <n-tag size="tiny" round :bordered="false" class="tool-tag">{{ toolLabel }}</n-tag>
      <n-tag v-if="statusText" size="tiny" round :bordered="false" :type="statusTagType">
        {{ statusText }}
      </n-tag>
      <div class="header-actions">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" :disabled="isEditTool" @click="editing = !editing">
              <n-icon size="14"><CreateOutline /></n-icon>
            </n-button>
          </template>
          {{ isEditTool ? 'diff 视图不可编辑' : editing ? '锁定编辑' : '编辑代码' }}
        </n-tooltip>
        <n-tooltip v-if="ctx && tool.arguments?.path" trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="ctx?.openFileInEditor?.(String(tool.arguments.path), { pin: true, externallyChanged: tool.name !== 'sandbox_execute' })">
              <n-icon size="14"><DocumentOutline /></n-icon>
            </n-button>
          </template>
          在编辑器打开
        </n-tooltip>
        <n-tooltip v-if="canRerun" trigger="hover">
          <template #trigger>
            <n-button text size="tiny" :loading="isRunning" @click="handleRerun">
              <n-icon size="14"><PlayOutline /></n-icon>
            </n-button>
          </template>
          重跑（沙盒执行）
        </n-tooltip>
        <n-tooltip v-if="tool.checkpointId" trigger="hover">
          <template #trigger>
            <n-button text size="tiny" :loading="restoringCheckpoint" @click="restoreCheckpoint">
              <n-icon size="14"><ReturnDownBackOutline /></n-icon>
            </n-button>
          </template>
          回退到此检查点
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="handleCopy">
              <n-icon size="14">
                <CheckmarkOutline v-if="copied" />
                <CopyOutline v-else />
              </n-icon>
            </n-button>
          </template>
          {{ copied ? '已复制' : '复制' }}
        </n-tooltip>
      </div>
    </div>

    <TaskProgressCard
      v-if="isAsyncTask"
      :task-id="asyncTaskId"
      :task-url="tool.uiPayload?.task_url ? String(tool.uiPayload.task_url) : undefined"
      :progress-url="tool.uiPayload?.progress_url ? String(tool.uiPayload.progress_url) : undefined"
      :result-url="tool.uiPayload?.result_url ? String(tool.uiPayload.result_url) : undefined"
      @completed="handleAsyncCompleted"
    />

    <!-- workspace_edit：diff2html 视图 + 接受/拒绝 -->
    <div v-else-if="isEditTool" class="edit-diff-block">
      <div class="diff-actions">
        <span v-if="editDecision === 'pending'" class="diff-prompt">这次文件修改是否保留？</span>
        <n-tag v-else size="small" :type="editDecision === 'accepted' ? 'success' : 'warning'">
          {{ editDecision === 'accepted' ? '已接受' : '已拒绝并回滚' }}
        </n-tag>
        <div v-if="editDecision === 'pending'" class="diff-action-buttons">
          <n-button size="tiny" type="success" @click="acceptEdit">
            <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
            接受
          </n-button>
          <n-button size="tiny" type="error" :loading="reverting" @click="rejectEdit">
            <template #icon><n-icon><CloseOutline /></n-icon></template>
            拒绝并回滚
          </n-button>
        </div>
      </div>
      <div v-if="diffHtml" class="diff-html d2h-wrapper" v-html="diffHtml" />
      <pre v-else class="diff-view">暂无 diff 内容</pre>
    </div>

    <div v-else class="editor-wrap" :class="{ editing }">
      <CodeEditor v-model="editorCode" :readonly="!editing" />
    </div>

    <!-- 输出区 -->
    <div v-if="!isAsyncTask && (displayOutput || isRunning || tool.status === 'running')" class="output-block">
      <button class="output-toggle" @click="showOutput = !showOutput">
        <n-icon size="12">
          <ChevronUpOutline v-if="showOutput" />
          <ChevronDownOutline v-else />
        </n-icon>
        <span v-if="isRunning || tool.status === 'running'">运行中 · 已输出 {{ outputLines }} 行</span>
        <span v-else>输出 {{ outputLines }} 行</span>
      </button>
      <pre v-show="showOutput" ref="outputRef" class="output-view">{{ displayOutput || '（暂无输出）' }}</pre>
    </div>

    <div v-if="imageArtifacts.length" class="artifact-previews">
      <figure v-for="artifact in imageArtifacts" :key="artifact.path" class="artifact-preview">
        <img v-if="imagePreviewUrls[artifact.path]" :src="imagePreviewUrls[artifact.path]" :alt="artifact.path.split('/').pop() || '生成图片'">
        <div v-else class="artifact-preview-loading">正在加载图片预览…</div>
        <figcaption>{{ artifact.path.split('/').pop() }}</figcaption>
      </figure>
    </div>

    <!-- 产物 chips -->
    <div v-if="!isAsyncTask && artifacts.length" class="artifact-chips">
      <span class="chips-label">产物</span>
      <button
        v-for="a in artifacts"
        :key="a.path"
        class="artifact-chip"
        :title="a.path"
        @click="handleDownloadArtifact(a.path)"
      >
        {{ a.path.split('/').pop() }}
      </button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.studio-code-card {
  margin-top: 10px;
  border: 1px solid var(--bubble-border, var(--chat-border, #e5e7eb));
  border-radius: var(--card-radius, 12px);
  overflow: hidden;
  background: var(--chat-surface, #fff);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  background: var(--chat-surface-hover, #f7f8fa);
  border-bottom: 1px solid var(--chat-border, #e5e7eb);
}
.file-icon { color: var(--chat-text-muted, #888); flex-shrink: 0; }
.file-name {
  font-size: 12px;
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.tool-tag { opacity: 0.75; }
.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.editor-wrap {
  min-height: 22px;
  max-height: 110px;
  margin: 8px 10px;
  border: 1px solid var(--code-block-border, rgba(0, 0, 0, 0.08));
  border-radius: 8px;
  overflow: hidden;
}
.editor-wrap.editing {
  outline: 2px solid var(--chat-accent, #4f8ef7);
  outline-offset: -2px;
}

.edit-diff-block {
  border-bottom: 1px solid var(--chat-border, #e5e7eb);
}
.diff-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 12px;
  background: var(--chat-surface-hover, #f7f8fa);
}
.diff-prompt {
  font-size: 11px;
  color: var(--chat-text-muted, #888);
}
.diff-action-buttons {
  display: flex;
  gap: 6px;
  margin-left: auto;
}
.diff-html {
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
}
.diff-html :deep(.d2h-file-header) {
  display: none;
}
.diff-html :deep(.d2h-code-line-ctn) {
  white-space: pre-wrap;
  word-break: break-word;
}

:root[data-theme="dark"] .diff-html :deep(.d2h-file-wrapper) {
  background: var(--chat-surface, #1a1a1a);
  border-color: var(--chat-border, #333);
}
:root[data-theme="dark"] .diff-html :deep(.d2h-info) {
  background: #2d2d2d;
  color: #8b949e;
  border-color: #444;
}
:root[data-theme="dark"] .diff-html :deep(.d2h-code-linenumber),
:root[data-theme="dark"] .diff-html :deep(.d2h-code-side-linenumber) {
  background: #1e1e1e;
  color: #6e7681;
  border-color: #333;
}
:root[data-theme="dark"] .diff-html :deep(.d2h-ins) {
  background: rgba(46, 160, 67, 0.15);
}
:root[data-theme="dark"] .diff-html :deep(.d2h-ins .d2h-code-linenumber),
:root[data-theme="dark"] .diff-html :deep(.d2h-ins .d2h-code-side-linenumber) {
  background: rgba(46, 160, 67, 0.1);
  color: #7ee787;
}
:root[data-theme="dark"] .diff-html :deep(.d2h-del) {
  background: rgba(248, 81, 73, 0.15);
}
:root[data-theme="dark"] .diff-html :deep(.d2h-del .d2h-code-linenumber),
:root[data-theme="dark"] .diff-html :deep(.d2h-del .d2h-code-side-linenumber) {
  background: rgba(248, 81, 73, 0.1);
  color: #ff7b72;
}
:root[data-theme="dark"] .diff-html :deep(.d2h-code-line) {
  color: #c9d1d9;
}
.diff-view {
  margin: 0 10px 10px;
  padding: 10px 12px;
  max-height: 260px;
  overflow: auto;
  background: var(--code-block-bg, #24292f);
  border: 1px solid var(--code-block-border, rgba(0, 0, 0, 0.08));
  border-radius: 8px;
  color: #d7dae0;
  font-size: 12px;
  font-family: ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, 'JetBrains Mono', monospace;
  line-height: 1.6;
}

.output-block {
  border-top: 1px solid var(--chat-border, #e5e7eb);
}
.output-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 5px 12px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}
.output-toggle:hover { color: var(--chat-text-primary, #333); }
.output-view {
  /* 深色块与白卡片之间留白 + 圆角嵌套 + 过渡描边，避免"黑贴白"硬切（问题⑥） */
  margin: 0 10px 10px;
  padding: 8px 12px;
  max-height: 240px;
  overflow: auto;
  background: var(--code-block-bg, #1f2329);
  border: 1px solid var(--code-block-border, rgba(0, 0, 0, 0.08));
  border-radius: 8px;
  color: #d7dae0;
  font-size: 12px;
  font-family: ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, 'JetBrains Mono', monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.artifact-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 7px 12px;
  border-top: 1px solid var(--chat-border, #e5e7eb);
}
.artifact-previews {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  padding: 12px;
  border-top: 1px solid var(--chat-border, #e5e7eb);
}
.artifact-preview {
  display: grid;
  gap: 6px;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 8px;
  background: var(--chat-surface, #fff);
}
.artifact-preview img {
  display: block;
  width: 100%;
  max-height: 280px;
  object-fit: contain;
  background: var(--chat-surface-hover, #f7f8fa);
}
.artifact-preview-loading {
  display: grid;
  min-height: 160px;
  place-items: center;
  color: var(--chat-text-muted, #999);
  font-size: 12px;
}
.artifact-preview figcaption {
  overflow: hidden;
  padding: 0 8px 8px;
  color: var(--chat-text-secondary, #666);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chips-label {
  font-size: 11px;
  color: var(--chat-text-muted, #999);
}
.artifact-chip {
  padding: 2px 10px;
  border: 1px solid var(--chat-border, #e5e7eb);
  border-radius: 999px;
  background: var(--chat-surface, #fff);
  font-size: 11px;
  cursor: pointer;
  color: var(--chat-accent, #4f8ef7);
  transition: background 0.15s ease;
}
.artifact-chip:hover {
  background: var(--chat-surface-hover, #f0f4ff);
}
</style>
