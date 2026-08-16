<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import hljs from 'highlight.js'
import apiClient from '@/api/client'
import { studioApi } from '@/api/studio'
import type { ToolCall } from './types'

interface ArtifactItem {
  path: string
  size?: number
  mtime?: number
  /** 直接下载地址（如聊天沙盒产物）；提供时不走 studio 会话下载 */
  url?: string
}

const props = withDefaults(defineProps<{
  sessionId?: string
  tools?: ToolCall[]
  /** Agent/worker 直接回传的产物映射；键通常是工作区相对路径。 */
  artifacts?: unknown
}>(), {
  sessionId: '',
  tools: () => [],
  artifacts: undefined,
})

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'])
const PREVIEW_EXTENSIONS = new Set([...IMAGE_EXTENSIONS, 'pdf'])
// 按需预览（弹窗）：文本/代码与表格文件
const TEXT_PREVIEW_EXTENSIONS = new Set([
  'txt', 'log', 'md', 'py', 'r', 'json', 'jsonl', 'csv', 'tsv',
  'yaml', 'yml', 'sh', 'bash', 'sql', 'xml', 'html', 'js', 'ts', 'css', 'toml', 'ini',
])
const SHEET_PREVIEW_EXTENSIONS = new Set(['xlsx', 'xls'])
const HLJS_LANGUAGE_ALIASES: Record<string, string> = {
  py: 'python', sh: 'bash', bash: 'bash', yml: 'yaml', js: 'javascript', ts: 'typescript',
  md: 'markdown', jsonl: 'json', txt: 'plaintext', log: 'plaintext', csv: 'plaintext', tsv: 'plaintext',
}
const TEXT_PREVIEW_MAX_CHARS = 200_000
const SHEET_PREVIEW_MAX_ROWS = 100
const SHEET_PREVIEW_MAX_SHEETS = 3

interface SheetPreview {
  name: string
  header: string[]
  rows: string[][]
  truncated: boolean
}

const previewUrls = ref<Record<string, string>>({})
const unavailablePreviews = ref(new Set<string>())
const downloadingPaths = ref(new Set<string>())
const failedDownloadPaths = ref(new Set<string>())
const previewModalVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewTitle = ref('')
const previewCodeHtml = ref('')
const previewCodeTruncated = ref(false)
const previewSheets = ref<SheetPreview[]>([])

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function artifactPath(value: unknown): string {
  const normalize = (raw: string) => {
    const trimmed = raw.trim().replace(/\\/g, '/')
    const outputIndex = trimmed.indexOf('/output/')
    if (outputIndex >= 0) return trimmed.slice(outputIndex + 1)
    return trimmed.startsWith('output/') ? trimmed : trimmed
  }
  if (typeof value === 'string') return normalize(value)
  const item = asRecord(value)
  return typeof item?.path === 'string' ? normalize(item.path) : ''
}

function artifactUrl(value: unknown): string | undefined {
  const item = asRecord(value)
  const url = item?.url ?? item?.download_url
  return typeof url === 'string' && url ? url : undefined
}

function artifactDetails(value: unknown): ArtifactItem | undefined {
  const path = artifactPath(value)
  if (!path) return undefined
  const item = asRecord(value)
  return {
    path,
    size: typeof item?.size === 'number' ? item.size : undefined,
    mtime: typeof item?.mtime === 'number' ? item.mtime : undefined,
    url: artifactUrl(value),
  }
}

function artifactDetailsFromEntry(pathValue: unknown, metadata: unknown): ArtifactItem | undefined {
  const path = artifactPath(pathValue)
  if (!path) return undefined
  const item = asRecord(metadata)
  return {
    path,
    size: typeof item?.size === 'number' ? item.size : undefined,
    mtime: typeof item?.mtime === 'number' ? item.mtime : undefined,
    url: artifactUrl(pathValue) ?? artifactUrl(metadata),
  }
}

function directArtifacts(value: unknown): ArtifactItem[] {
  if (Array.isArray(value)) {
    return value
      .map(artifactDetails)
      .filter((item): item is ArtifactItem => Boolean(item))
  }
  const record = asRecord(value)
  if (!record) return []
  return Object.entries(record)
    .map(([path, metadata]) => artifactDetailsFromEntry(path, metadata))
    .filter((item): item is ArtifactItem => Boolean(item))
}

function collectArtifacts(tool: ToolCall): ArtifactItem[] {
  const result = asRecord(tool.result)
  const nestedPayload = asRecord(result?.ui_payload) || asRecord(result?.uiPayload)
  const sources = [tool.uiPayload?.artifacts, result?.artifacts, nestedPayload?.artifacts]
  return sources.flatMap((source) => Array.isArray(source)
    ? source.map(artifactDetails).filter((item): item is ArtifactItem => Boolean(item))
    : [])
}

const artifactItems = computed(() => {
  const unique = new Map<string, ArtifactItem>()
  const addArtifact = (artifact: ArtifactItem) => {
    const existing = unique.get(artifact.path)
    unique.set(artifact.path, existing
      ? {
          ...existing,
          ...artifact,
          size: artifact.size ?? existing.size,
          mtime: artifact.mtime ?? existing.mtime,
          url: artifact.url ?? existing.url,
        }
      : artifact)
  }
  for (const tool of props.tools) {
    for (const artifact of collectArtifacts(tool)) addArtifact(artifact)
  }
  for (const artifact of directArtifacts(props.artifacts)) addArtifact(artifact)
  return [...unique.values()]
})

const previewArtifacts = computed(() =>
  artifactItems.value.filter((artifact) => PREVIEW_EXTENSIONS.has(artifact.path.split('.').pop()?.toLowerCase() || '')),
)

const otherArtifacts = computed(() =>
  artifactItems.value.filter((artifact) => !previewArtifacts.value.some((preview) => preview.path === artifact.path)),
)

function isImageArtifact(path: string): boolean {
  return IMAGE_EXTENSIONS.has(path.split('.').pop()?.toLowerCase() || '')
}

function fileName(path: string): string {
  return path.split('/').pop() || path
}

function extensionOf(path: string): string {
  return path.split('.').pop()?.toLowerCase() || ''
}

function canPreviewOnDemand(path: string): boolean {
  const ext = extensionOf(path)
  return TEXT_PREVIEW_EXTENSIONS.has(ext) || SHEET_PREVIEW_EXTENSIONS.has(ext)
}

function clearPreviews() {
  for (const url of Object.values(previewUrls.value)) URL.revokeObjectURL(url)
  previewUrls.value = {}
  unavailablePreviews.value = new Set()
}

async function fetchArtifactBlobData(artifact: ArtifactItem): Promise<Blob> {
  if (artifact.url) {
    // apiClient baseURL 为 /api/v1，剥掉前缀后直连产物下载地址
    const res = await apiClient.get(artifact.url.replace(/^\/api\/v1/, ''), { responseType: 'blob' })
    return res.data as Blob
  }
  const objectUrl = await studioApi.fetchArtifactBlob(props.sessionId, artifact.path)
  return await (await fetch(objectUrl)).blob()
}

async function fetchArtifactObjectUrl(artifact: ArtifactItem): Promise<string> {
  return URL.createObjectURL(await fetchArtifactBlobData(artifact))
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

async function buildSheetPreviews(buffer: ArrayBuffer): Promise<SheetPreview[]> {
  const XLSX = await import('xlsx')
  const workbook = XLSX.read(buffer, { type: 'array' })
  return workbook.SheetNames.slice(0, SHEET_PREVIEW_MAX_SHEETS).map((name) => {
    const rawRows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets[name], {
      header: 1,
      raw: false,
      defval: '',
    })
    const normalized = rawRows.map((row) => (Array.isArray(row) ? row.map((cell) => String(cell)) : []))
    const [header = [], ...body] = normalized
    return {
      name,
      header,
      rows: body.slice(0, SHEET_PREVIEW_MAX_ROWS),
      truncated: body.length > SHEET_PREVIEW_MAX_ROWS,
    }
  })
}

async function openPreview(artifact: ArtifactItem) {
  previewTitle.value = fileName(artifact.path)
  previewError.value = ''
  previewCodeHtml.value = ''
  previewCodeTruncated.value = false
  previewSheets.value = []
  previewModalVisible.value = true
  previewLoading.value = true
  try {
    const blob = await fetchArtifactBlobData(artifact)
    const ext = extensionOf(artifact.path)
    if (SHEET_PREVIEW_EXTENSIONS.has(ext)) {
      previewSheets.value = await buildSheetPreviews(await blob.arrayBuffer())
    } else {
      let text = await blob.text()
      if (text.length > TEXT_PREVIEW_MAX_CHARS) {
        text = text.slice(0, TEXT_PREVIEW_MAX_CHARS)
        previewCodeTruncated.value = true
      }
      const language = HLJS_LANGUAGE_ALIASES[ext] || ext
      previewCodeHtml.value = hljs.getLanguage(language)
        ? hljs.highlight(text, { language }).value
        : escapeHtml(text)
    }
  } catch {
    previewError.value = '预览加载失败，请尝试下载后查看'
  } finally {
    previewLoading.value = false
  }
}

async function loadPreviews() {
  clearPreviews()
  const targets = previewArtifacts.value.filter((artifact) => artifact.url || props.sessionId)
  await Promise.all(targets.map(async (artifact) => {
    try {
      previewUrls.value[artifact.path] = await fetchArtifactObjectUrl(artifact)
    } catch {
      unavailablePreviews.value = new Set([...unavailablePreviews.value, artifact.path])
    }
  }))
}

async function downloadArtifact(path: string) {
  const artifact = artifactItems.value.find((item) => item.path === path)
  if (!artifact || (!artifact.url && !props.sessionId) || downloadingPaths.value.has(path)) return

  downloadingPaths.value = new Set([...downloadingPaths.value, path])
  const nextFailedPaths = new Set(failedDownloadPaths.value)
  nextFailedPaths.delete(path)
  failedDownloadPaths.value = nextFailedPaths
  try {
    const objectUrl = await fetchArtifactObjectUrl(artifact)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = fileName(path)
    link.click()
    URL.revokeObjectURL(objectUrl)
  } catch {
    failedDownloadPaths.value = new Set([...failedDownloadPaths.value, path])
  } finally {
    const nextPaths = new Set(downloadingPaths.value)
    nextPaths.delete(path)
    downloadingPaths.value = nextPaths
  }
}

watch(
  () => [
    props.sessionId,
    previewArtifacts.value.map((artifact) => `${artifact.path}:${artifact.url || ''}`).join('|'),
  ],
  () => { void loadPreviews() },
  { immediate: true },
)

onBeforeUnmount(clearPreviews)
</script>

<template>
  <section v-if="artifactItems.length" class="message-artifacts" aria-label="分析产物">
    <div class="message-artifacts__header">
      <div>
        <span class="message-artifacts__eyebrow">分析产物</span>
        <strong>已生成 {{ artifactItems.length }} 个文件</strong>
      </div>
      <span class="message-artifacts__hint">预览与下载</span>
    </div>

    <div v-if="previewArtifacts.length" class="message-artifacts__images">
      <figure v-for="artifact in previewArtifacts" :key="artifact.path" class="message-artifacts__image-card">
        <div class="message-artifacts__preview">
          <img
            v-if="isImageArtifact(artifact.path) && previewUrls[artifact.path]"
            :src="previewUrls[artifact.path]"
            :alt="`${fileName(artifact.path)} 预览`"
          />
          <iframe
            v-else-if="previewUrls[artifact.path]"
            :src="previewUrls[artifact.path]"
            :title="`${fileName(artifact.path)} PDF 预览`"
            class="message-artifacts__pdf"
          />
          <span v-else class="message-artifacts__fallback" aria-live="polite">
            {{ unavailablePreviews.has(artifact.path) ? '暂时无法预览，可直接下载文件' : '正在加载预览…' }}
          </span>
        </div>
        <figcaption>
          <span class="message-artifacts__file-name" :title="artifact.path">{{ fileName(artifact.path) }}</span>
          <button
            type="button"
            class="message-artifacts__download"
            :disabled="downloadingPaths.has(artifact.path)"
            @click="downloadArtifact(artifact.path)"
          >
            {{ downloadingPaths.has(artifact.path) ? '下载中…' : failedDownloadPaths.has(artifact.path) ? '重试下载' : '下载图片' }}
          </button>
          <span v-if="failedDownloadPaths.has(artifact.path)" class="message-artifacts__download-error" role="status">
            下载失败，请重试
          </span>
        </figcaption>
      </figure>
    </div>

    <ul v-if="otherArtifacts.length" class="message-artifacts__files">
      <li v-for="artifact in otherArtifacts" :key="artifact.path">
        <span class="message-artifacts__file-name" :title="artifact.path">{{ fileName(artifact.path) }}</span>
        <div class="message-artifacts__actions">
          <button
            v-if="canPreviewOnDemand(artifact.path) && (artifact.url || sessionId)"
            type="button"
            class="message-artifacts__download"
            @click="openPreview(artifact)"
          >
            预览
          </button>
          <button
            type="button"
            class="message-artifacts__download"
            :disabled="downloadingPaths.has(artifact.path)"
            @click="downloadArtifact(artifact.path)"
          >
            {{ downloadingPaths.has(artifact.path) ? '下载中…' : failedDownloadPaths.has(artifact.path) ? '重试下载' : '下载' }}
          </button>
          <span v-if="failedDownloadPaths.has(artifact.path)" class="message-artifacts__download-error" role="status">
            下载失败，请重试
          </span>
        </div>
      </li>
    </ul>

    <NModal
      v-model:show="previewModalVisible"
      preset="card"
      :title="`预览 ${previewTitle}`"
      style="width: min(90vw, 1100px)"
      :bordered="false"
      segmented
    >
      <div v-if="previewLoading" class="artifact-preview__status">正在加载预览…</div>
      <div v-else-if="previewError" class="artifact-preview__status">{{ previewError }}</div>
      <template v-else-if="previewSheets.length">
        <div v-for="sheet in previewSheets" :key="sheet.name" class="artifact-sheet-preview">
          <h4 class="artifact-sheet-preview__name">{{ sheet.name }}</h4>
          <div class="artifact-sheet-preview__scroll">
            <table>
              <thead>
                <tr><th v-for="(cell, i) in sheet.header" :key="i">{{ cell }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in sheet.rows" :key="ri">
                  <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="sheet.truncated" class="artifact-preview__hint">仅展示前 {{ SHEET_PREVIEW_MAX_ROWS }} 行，完整数据请下载查看</p>
        </div>
      </template>
      <template v-else>
        <pre class="artifact-code-preview hljs"><code v-html="previewCodeHtml"></code></pre>
        <p v-if="previewCodeTruncated" class="artifact-preview__hint">内容过长，仅展示前面部分，完整内容请下载查看</p>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.message-artifacts {
  margin-top: var(--space-lg, 16px);
  padding: var(--space-md, 12px);
  border: 1px solid var(--stardust-border-soft);
  border-radius: var(--radius-card, 12px);
  background: var(--bg-card);
}

.message-artifacts__header,
.message-artifacts__image-card figcaption,
.message-artifacts__files li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm, 8px);
}

.message-artifacts__header {
  margin-bottom: var(--space-md, 12px);
}

.message-artifacts__header > div {
  display: grid;
  gap: 2px;
}

.message-artifacts__eyebrow,
.message-artifacts__hint {
  color: var(--text-tertiary);
  font-size: 12px;
}

.message-artifacts__header strong {
  color: var(--text-primary);
  font-size: 14px;
}

.message-artifacts__images {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-md, 12px);
}

.message-artifacts__image-card {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--stardust-border-soft);
  border-radius: calc(var(--radius-card, 12px) - 2px);
  background: var(--bg-secondary);
}

.message-artifacts__preview {
  display: grid;
  min-height: 180px;
  place-items: center;
  overflow: hidden;
  background: color-mix(in srgb, var(--bg-card) 86%, var(--brand-primary-light));
}

.message-artifacts__preview img {
  display: block;
  width: 100%;
  max-height: 360px;
  object-fit: contain;
}

.message-artifacts__pdf {
  display: block;
  width: 100%;
  height: 360px;
  border: 0;
  background: #fff;
}

.message-artifacts__fallback {
  padding: var(--space-md, 12px);
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
}

.message-artifacts__image-card figcaption,
.message-artifacts__files li {
  padding: var(--space-sm, 8px) var(--space-md, 12px);
}

.message-artifacts__files {
  display: grid;
  gap: 1px;
  margin: var(--space-md, 12px) 0 0;
  padding: 0;
  overflow: hidden;
  list-style: none;
  border: 1px solid var(--stardust-border-soft);
  border-radius: calc(var(--radius-card, 12px) - 2px);
}

.message-artifacts__files li {
  background: var(--bg-card);
}

.message-artifacts__files li + li {
  border-top: 1px solid var(--stardust-border-soft);
}

.message-artifacts__file-name {
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-artifacts__download {
  flex: 0 0 auto;
  padding: 4px 8px;
  color: var(--brand-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  background: var(--brand-primary-light);
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.message-artifacts__download:disabled {
  cursor: wait;
  opacity: 0.72;
}

.message-artifacts__download-error {
  color: var(--error-color, #d03050);
  font-size: 12px;
}

.message-artifacts__actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
}

.artifact-preview__status {
  padding: var(--space-lg, 16px);
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
}

.artifact-preview__hint {
  margin: var(--space-sm, 8px) 0 0;
  color: var(--text-tertiary);
  font-size: 12px;
}

.artifact-code-preview {
  max-height: 65vh;
  margin: 0;
  padding: var(--space-md, 12px);
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 双类选择器压过全局 hljs 主题底色，跟随聊天主题明暗 */
.artifact-code-preview.hljs {
  color: var(--chat-text-primary, #1a1a1a);
  background: var(--chat-bg-code, #f5f6f8);
}

.artifact-sheet-preview + .artifact-sheet-preview {
  margin-top: var(--space-lg, 16px);
}

.artifact-sheet-preview__name {
  margin: 0 0 var(--space-sm, 8px);
  font-size: 13px;
}

.artifact-sheet-preview__scroll {
  max-height: 55vh;
  overflow: auto;
  border: 1px solid var(--stardust-border-soft);
  border-radius: 8px;
}

.artifact-sheet-preview__scroll table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.artifact-sheet-preview__scroll th,
.artifact-sheet-preview__scroll td {
  padding: 4px 10px;
  border-bottom: 1px solid var(--stardust-border-soft);
  text-align: left;
  white-space: nowrap;
}

.artifact-sheet-preview__scroll th {
  position: sticky;
  top: 0;
  background: var(--bg-secondary);
}

.message-artifacts__download:hover {
  background: color-mix(in srgb, var(--brand-primary-light) 72%, var(--brand-primary));
}

.message-artifacts__download:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

@media (max-width: 640px) {
  .message-artifacts__header,
  .message-artifacts__image-card figcaption,
  .message-artifacts__files li {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .message-artifacts__preview {
    background: var(--bg-secondary);
  }
}
</style>
