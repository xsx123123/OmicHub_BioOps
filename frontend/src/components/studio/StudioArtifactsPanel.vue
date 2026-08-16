<script setup lang="ts">
/**
 * StudioArtifactsPanel — 产物列表面板（右栏）
 *
 * GET /studio/sessions/{id}/artifacts：图片 lightbox、CSV/TSV 前 50 行表格、
 * Markdown 渲染；同时支持下载、插入对话引用和保存为报告版本。
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import DOMPurify from 'dompurify'
import {
  NButton,
  NDataTable,
  NIcon,
  NInput,
  NModal,
  NSpin,
  NTooltip,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  ChatboxOutline,
  DocumentOutline,
  DownloadOutline,
  EyeOutline,
  ImageOutline,
  OpenOutline,
  SaveOutline,
} from '@vicons/ionicons5'
import MarkdownIt from 'markdown-it'
import Papa from 'papaparse'
import { studioApi, type StudioArtifact } from '@/api/studio'

const props = defineProps<{
  sessionId: string
  /** 递增以触发刷新（工具结果/重跑后由父级 bump） */
  refreshKey?: number
}>()

const emit = defineEmits<{
  insert: [path: string]
  open: [path: string]
  registered: []
}>()
const message = useMessage()

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'])
const TABLE_EXTS = new Set(['csv', 'tsv'])
const MARKDOWN_EXTS = new Set(['md', 'markdown'])
const markdown = new MarkdownIt({ html: false, linkify: true, typographer: true })

type PreviewKind = 'image' | 'table' | 'markdown' | 'unsupported'
type PreviewRow = Record<string, string | number>

const artifacts = ref<StudioArtifact[]>([])
const artifactsInitialized = ref(false)
const sparklePath = ref('')
const loading = ref(false)
const loadError = ref('')
/** path -> Object URL（图片缩略图缓存） */
const thumbUrls = ref<Record<string, string>>({})

const previewUrl = ref('')
const previewName = ref('')
const previewArtifact = ref<StudioArtifact | null>(null)
const previewKind = ref<PreviewKind>('unsupported')
const previewLoading = ref(false)
const previewError = ref('')
const previewTruncated = ref(false)
const previewMarkdown = ref('')
const previewColumns = ref<DataTableColumns<PreviewRow>>([])
const previewRows = ref<PreviewRow[]>([])
const showPreview = ref(false)

const showRegister = ref(false)
const registerArtifact = ref<StudioArtifact | null>(null)
const registerTitle = ref('')
const registering = ref(false)
let sparkleTimer: number | null = null

const artifactGroups = computed(() => {
  const groups = [
    { key: 'table', label: '数据表', items: [] as StudioArtifact[] },
    { key: 'chart', label: '图表', items: [] as StudioArtifact[] },
    { key: 'report', label: '报告', items: [] as StudioArtifact[] },
  ]
  for (const artifact of artifacts.value) {
    const ext = extension(artifact.path)
    if (TABLE_EXTS.has(ext)) groups[0].items.push(artifact)
    else if (IMAGE_EXTS.has(ext)) groups[1].items.push(artifact)
    else groups[2].items.push(artifact)
  }
  return groups.filter((group) => group.items.length)
})

function extension(path: string): string {
  return path.split('.').pop()?.toLowerCase() || ''
}

function isImage(path: string): boolean {
  return IMAGE_EXTS.has(extension(path))
}

function clearThumbs() {
  for (const url of Object.values(thumbUrls.value)) URL.revokeObjectURL(url)
  thumbUrls.value = {}
}

function clearPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  previewError.value = ''
  previewTruncated.value = false
  previewMarkdown.value = ''
  previewColumns.value = []
  previewRows.value = []
}

async function loadArtifacts() {
  if (!props.sessionId) return
  loading.value = true
  loadError.value = ''
  clearThumbs()
  try {
    const nextArtifacts = await studioApi.listArtifacts(props.sessionId)
    if (artifactsInitialized.value) {
      const previousPaths = new Set(artifacts.value.map((artifact) => artifact.path))
      const fresh = nextArtifacts.find((artifact) => !previousPaths.has(artifact.path))
      if (fresh) {
        sparklePath.value = fresh.path
        message.success('✨ 新产物已就位')
        if (sparkleTimer) clearTimeout(sparkleTimer)
        sparkleTimer = window.setTimeout(() => { if (sparklePath.value === fresh.path) sparklePath.value = '' }, 900)
      }
    }
    artifacts.value = nextArtifacts
    artifactsInitialized.value = true
    for (const artifact of artifacts.value) {
      if (isImage(artifact.path)) {
        studioApi.fetchArtifactBlob(props.sessionId, artifact.path)
          .then((url) => { thumbUrls.value[artifact.path] = url })
          .catch(() => {})
      }
    }
  } catch {
    loadError.value = '产物列表加载失败，请刷新后重试'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.sessionId, props.refreshKey],
  (nextValue, previousValue) => {
    if (nextValue[0] !== previousValue?.[0]) artifactsInitialized.value = false
    void loadArtifacts()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (sparkleTimer) clearTimeout(sparkleTimer)
  clearThumbs()
  clearPreview()
})

function buildTablePreview(content: string, delimiter: string) {
  const parsed = Papa.parse<string[]>(content.replace(/^\uFEFF/, ''), {
    delimiter,
    skipEmptyLines: 'greedy',
  })
  const records = parsed.data.filter((row) => row.some((cell) => String(cell).trim()))
  if (!records.length) {
    previewError.value = '文件中没有可预览的数据'
    return
  }

  const header = records[0]
  const dataRows = records.slice(1)
  previewColumns.value = header.map((label, index) => ({
    title: String(label || `列 ${index + 1}`),
    key: `column_${index}`,
    minWidth: 120,
    ellipsis: { tooltip: true },
  }))
  previewRows.value = dataRows.slice(0, 50).map((row, rowIndex) => {
    const item: PreviewRow = { __rowKey: rowIndex }
    header.forEach((_, columnIndex) => {
      item[`column_${columnIndex}`] = row[columnIndex] ?? ''
    })
    return item
  })
  previewTruncated.value = previewTruncated.value || dataRows.length > 50
}

async function openPreview(artifact: StudioArtifact) {
  clearPreview()
  previewArtifact.value = artifact
  previewName.value = artifact.path.split('/').pop() || artifact.path
  showPreview.value = true
  previewLoading.value = true

  const ext = extension(artifact.path)
  try {
    if (IMAGE_EXTS.has(ext)) {
      previewKind.value = 'image'
      previewUrl.value = await studioApi.fetchArtifactBlob(props.sessionId, artifact.path)
      return
    }

    if (TABLE_EXTS.has(ext)) {
      previewKind.value = 'table'
      const result = await studioApi.readArtifactText(props.sessionId, artifact.path, 500)
      previewTruncated.value = result.truncated
      buildTablePreview(result.content, ext === 'tsv' ? '\t' : ',')
      return
    }

    if (MARKDOWN_EXTS.has(ext)) {
      previewKind.value = 'markdown'
      const result = await studioApi.readArtifactText(props.sessionId, artifact.path, 2000)
      previewTruncated.value = result.truncated
      previewMarkdown.value = DOMPurify.sanitize(markdown.render(result.content))
      return
    }

    previewKind.value = 'unsupported'
  } catch {
    previewError.value = '产物预览失败，请下载后查看'
  } finally {
    previewLoading.value = false
  }
}

function handleDownload(artifact: StudioArtifact) {
  studioApi.downloadArtifact(props.sessionId, artifact.path).catch(() => {})
}

function openRegister(artifact: StudioArtifact) {
  registerArtifact.value = artifact
  registerTitle.value = artifact.path.split('/').pop()?.replace(/\.[^.]+$/, '') || 'Studio 分析产物'
  showRegister.value = true
}

async function submitRegister() {
  const artifact = registerArtifact.value
  const title = registerTitle.value.trim()
  if (!artifact || !title) {
    message.warning('请输入报告标题')
    return
  }
  registering.value = true
  try {
    const result = await studioApi.registerArtifact(props.sessionId, {
      path: artifact.path,
      title,
    })
    const suffix = result.parent_id ? '，已挂到原报告版本树' : ''
    message.success(`已登记为《${result.title}》v${result.version}${suffix}`)
    showRegister.value = false
    sparklePath.value = artifact.path
    if (sparkleTimer) clearTimeout(sparkleTimer)
    sparkleTimer = window.setTimeout(() => { if (sparklePath.value === artifact.path) sparklePath.value = '' }, 900)
    emit('registered')
  } catch {
    message.error('登记失败，请确认产物仍存在')
  } finally {
    registering.value = false
  }
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(mtime: number): string {
  const date = new Date(mtime * 1000)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
</script>

<template>
  <div class="studio-artifacts">
    <div v-if="loading" class="panel-loading">
      <n-spin size="small" />
    </div>
    <div v-else-if="loadError" class="panel-error" role="status" aria-live="polite">
      {{ loadError }}
      <n-button text size="tiny" @click="loadArtifacts">重试</n-button>
    </div>
    <div v-else-if="!artifacts.length" class="panel-empty">
      暂无产物<br>执行生成的文件会出现在这里
    </div>

    <section v-for="group in artifactGroups" :key="group.key" class="artifact-group">
      <div class="artifact-group-heading"><span>{{ group.label }}</span><small>{{ group.items.length }}</small></div>
      <div v-for="artifact in group.items" :key="artifact.path" class="artifact-item" :class="{ sparkle: sparklePath === artifact.path, 'artifact-enter': sparklePath === artifact.path }" :title="artifact.path">
      <button
        v-if="isImage(artifact.path)"
        class="thumb-btn"
        @click="openPreview(artifact)"
      >
        <img
          v-if="thumbUrls[artifact.path]"
          :src="thumbUrls[artifact.path]"
          :alt="artifact.path"
          class="thumb-img"
        />
        <n-icon v-else size="22" class="thumb-placeholder"><ImageOutline /></n-icon>
      </button>
      <n-icon v-else size="20" class="file-icon"><DocumentOutline /></n-icon>

      <div class="artifact-meta">
        <div class="artifact-name">{{ artifact.path.split('/').pop() }}</div>
        <div class="artifact-sub">{{ formatSize(artifact.size) }} · {{ formatTime(artifact.mtime) }}</div>
      </div>

      <div class="artifact-actions">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="openPreview(artifact)">
              <n-icon size="14"><EyeOutline /></n-icon>
            </n-button>
          </template>
          在线预览
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="emit('open', artifact.path)">
              <n-icon size="14"><OpenOutline /></n-icon>
            </n-button>
          </template>
          在分屏中打开
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="handleDownload(artifact)">
              <n-icon size="14"><DownloadOutline /></n-icon>
            </n-button>
          </template>
          下载
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="emit('insert', artifact.path)">
              <n-icon size="14"><ChatboxOutline /></n-icon>
            </n-button>
          </template>
          插入对话引用
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button text size="tiny" @click="openRegister(artifact)">
              <n-icon size="14"><SaveOutline /></n-icon>
            </n-button>
          </template>
          保存为新版本
        </n-tooltip>
      </div>
      </div>
    </section>

    <n-modal v-model:show="showRegister" preset="card" title="保存到报告中心" style="max-width: 480px">
      <div class="register-form">
        <n-input v-model:value="registerTitle" placeholder="报告标题" @keyup.enter="submitRegister" />
        <div class="register-path">{{ registerArtifact?.path }}</div>
        <div class="register-actions">
          <n-button @click="showRegister = false">取消</n-button>
          <n-button type="primary" :loading="registering" @click="submitRegister">
            保存为新版本
          </n-button>
        </div>
      </div>
    </n-modal>

    <n-modal
      v-model:show="showPreview"
      preset="card"
      :title="previewName"
      style="width: min(1000px, calc(100vw - 32px))"
    >
      <div class="preview-body">
        <n-spin v-if="previewLoading" size="medium" />
        <div v-else-if="previewError" class="preview-message">{{ previewError }}</div>
        <img
          v-else-if="previewKind === 'image' && previewUrl"
          :src="previewUrl"
          :alt="previewName"
          class="preview-img"
        />
        <div v-else-if="previewKind === 'table'" class="table-preview">
          <n-data-table
            v-if="previewRows.length"
            :columns="previewColumns"
            :data="previewRows"
            :row-key="(row: PreviewRow) => row.__rowKey"
            :max-height="560"
            :scroll-x="Math.max(720, previewColumns.length * 140)"
            size="small"
            striped
          />
          <div v-else class="preview-message">文件中没有可预览的数据</div>
        </div>
        <article
          v-else-if="previewKind === 'markdown'"
          class="markdown-preview"
          v-html="previewMarkdown"
        />
        <div v-else class="preview-message">
          此文件类型暂不支持在线预览，请下载后查看。
        </div>
        <div v-if="previewTruncated" class="truncated-tip">
          预览内容已截断，仅展示 CSV/TSV 前 50 行或 Markdown 前 2000 行
        </div>
        <n-button
          v-if="previewArtifact && previewKind === 'unsupported'"
          type="primary"
          @click="handleDownload(previewArtifact)"
        >
          下载文件
        </n-button>
      </div>
    </n-modal>
  </div>
</template>

<style scoped lang="scss">
.studio-artifacts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}
.artifact-group { display: grid; gap: 6px; }
.artifact-group + .artifact-group { margin-top: 8px; }
.artifact-group-heading { display: flex; align-items: center; justify-content: space-between; padding: 2px 4px; color: var(--chat-text-muted); font-size: 11px; }
.artifact-group-heading small { display: grid; place-items: center; min-width: 18px; height: 18px; border-radius: 999px; background: var(--chat-surface-hover); }
.panel-loading {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}
.panel-empty {
  padding: 12px 10px;
  font-size: 12px;
  color: var(--chat-text-muted, #aaa);
  line-height: 1.6;
  text-align: center;
}
.panel-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 10px;
  color: var(--arco-danger, #d03050);
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}
.artifact-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--chat-border, #eee);
  border-radius: 8px;
  background: var(--chat-surface, #fff);
}
.artifact-item.artifact-enter { animation: artifact-enter .4s ease both; }
.thumb-btn {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: 1px solid var(--chat-border, #eee);
  border-radius: 6px;
  background: var(--chat-surface-hover, #f5f5f5);
  cursor: zoom-in;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 0;
}
.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-placeholder {
  color: var(--chat-text-muted, #aaa);
}
.file-icon {
  flex-shrink: 0;
  color: var(--chat-text-muted, #888);
}
.artifact-meta {
  flex: 1;
  min-width: 0;
}
.artifact-name {
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-sub {
  font-size: 10px;
  color: var(--chat-text-muted, #aaa);
}
.artifact-item { position: relative; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }.artifact-item:hover { border-color: #d7d0ff; box-shadow: 0 7px 18px rgba(108,92,231,.1); transform: translateY(-1px); }.artifact-item.sparkle::after { content: '✦'; position: absolute; right: 10px; top: -10px; color: var(--studio-primary,#6c5ce7); font-size: 16px; animation: artifact-star .9s ease-out both; pointer-events:none; }
.artifact-actions {
  position: absolute;
  right: 6px;
  top: 50%;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid rgba(232,232,242,.9);
  border-radius: 8px;
  background: rgba(255,255,255,.92);
  box-shadow: 0 4px 14px rgba(43,43,61,.1);
  backdrop-filter: blur(12px);
  opacity: 0;
  pointer-events: none;
  transform: translateY(-45%);
  transition: opacity .16s ease, transform .16s ease;
}
.artifact-item:hover .artifact-actions, .artifact-item:focus-within .artifact-actions { opacity: 1; pointer-events: auto; transform: translateY(-50%); }
@media (hover: none) { .artifact-actions { position: static; opacity: 1; pointer-events: auto; transform: none; box-shadow: none; } }
.register-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.register-path {
  font-size: 12px;
  color: var(--chat-text-muted, #999);
  word-break: break-all;
}
.register-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.preview-body {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.preview-img {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
}
.table-preview,
.markdown-preview {
  width: 100%;
}
.preview-message {
  padding: 28px;
  color: var(--chat-text-muted, #888);
  text-align: center;
}
.truncated-tip {
  width: 100%;
  font-size: 11px;
  color: var(--chat-text-muted, #999);
  text-align: right;
}
.markdown-preview {
  max-height: 68vh;
  overflow: auto;
  padding: 4px 16px;
  box-sizing: border-box;
  color: var(--chat-text-primary, inherit);
  line-height: 1.7;
}
.markdown-preview :deep(img) {
  max-width: 100%;
}
.markdown-preview :deep(pre) {
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: var(--chat-surface-hover, #f6f7f9);
}
.markdown-preview :deep(code) {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
.markdown-preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
}
.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  padding: 6px 8px;
  border: 1px solid var(--chat-border, #ddd);
}
@keyframes artifact-star { 0%{opacity:0;transform:translate(0,10px) scale(.6)} 35%{opacity:1} 100%{opacity:0;transform:translate(12px,-20px) scale(1.15)} }
@keyframes artifact-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce){.artifact-item{transition:none}.artifact-item.sparkle::after,.artifact-item.artifact-enter{animation:none;opacity:1;transform:none}}
</style>
