<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon, NModal } from 'naive-ui'
import {
  AddOutline,
  DownloadOutline,
  OpenOutline,
  PrintOutline,
  RefreshOutline,
  RemoveOutline,
} from '@vicons/ionicons5'
import hljs from 'highlight.js'
import apiClient from '@/api/client'
import { studioApi } from '@/api/studio'
import { printBlobUrl } from '@/utils/blobPrint'
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
/** 每个预览 blob 对应的加载来源('' = studio 会话接口,其余 = 直连下载地址),来源变化时需重拉 */
const loadedUrlByPath = ref<Record<string, string>>({})
const unavailablePreviews = ref(new Set<string>())
const downloadingPaths = ref(new Set<string>())
const failedDownloadPaths = ref(new Set<string>())
const previewModalVisible = ref(false)
// 产物窗口:完整画廊(大图/PDF/文件列表)所在的大弹窗。内联只保留紧凑卡片,
// 避免长产物列表把 AI 正文顶出可视区,用户第一时间看不到最新回复
const galleryVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewTitle = ref('')
const previewCodeHtml = ref('')
const previewCodeTruncated = ref(false)
const previewSheets = ref<SheetPreview[]>([])

// 图片/PDF 放大预览弹窗
const mediaPreviewVisible = ref(false)
const mediaPreviewKind = ref<'image' | 'pdf'>('image')
const mediaPreviewPath = ref('')
const mediaPreviewTitle = ref('')
const mediaZoom = ref(1)
const ZOOM_MIN = 0.25
const ZOOM_MAX = 5
const ZOOM_STEP = 0.25

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

/** 内联缩略图条最多展示的图片数;其余预览(含 PDF)等产物窗口打开后再加载 */
const INLINE_THUMB_MAX = 4

// 内联只急切加载前几张可加载的图片;不可加载(无 url 且无会话)的不占缩略图位
const inlineThumbArtifacts = computed(() =>
  previewArtifacts.value
    .filter((artifact) => isImageArtifact(artifact.path) && (artifact.url || props.sessionId))
    .slice(0, INLINE_THUMB_MAX),
)

function isImageArtifact(path: string): boolean {
  return IMAGE_EXTENSIONS.has(path.split('.').pop()?.toLowerCase() || '')
}

function isPdfArtifact(path: string): boolean {
  return extensionOf(path) === 'pdf'
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
  loadedUrlByPath.value = {}
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

const mediaPreviewSrc = computed(() => {
  const url = previewUrls.value[mediaPreviewPath.value]
  if (!url) return ''
  // 隐藏浏览器 PDF 查看器自带的深色工具栏，由弹窗内的语义令牌工具条接管下载/打印
  return mediaPreviewKind.value === 'pdf' ? `${url}#toolbar=0&navpanes=0` : url
})

// 卡片内嵌 PDF 预览：同样隐藏浏览器自带工具栏，仅保留首页视图
function pdfInlineSrc(url: string): string {
  return `${url}#toolbar=0&navpanes=0&view=FitH&page=1`
}

function openMediaPreview(artifact: ArtifactItem) {
  if (!previewUrls.value[artifact.path]) return
  mediaPreviewKind.value = isImageArtifact(artifact.path) ? 'image' : 'pdf'
  mediaPreviewPath.value = artifact.path
  mediaPreviewTitle.value = fileName(artifact.path)
  mediaZoom.value = 1
  mediaPreviewVisible.value = true
}

function zoomBy(delta: number) {
  mediaZoom.value = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round((mediaZoom.value + delta) * 100) / 100))
}

function onMediaWheel(event: WheelEvent) {
  if (mediaPreviewKind.value !== 'image') return
  event.preventDefault()
  zoomBy(event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)
}

function printMediaPreview() {
  const url = previewUrls.value[mediaPreviewPath.value]
  if (url) printBlobUrl(url)
}

async function loadPreviewUrls(items: ArtifactItem[]) {
  const targets = items.filter((artifact) => artifact.url || props.sessionId)
  await Promise.all(targets.map(async (artifact) => {
    const sourceKey = artifact.url || ''
    // 同一产物按相同来源加载过则跳过;URL 从空补齐为直连地址时来源变化,需重拉
    if (previewUrls.value[artifact.path] && loadedUrlByPath.value[artifact.path] === sourceKey) return
    try {
      const objectUrl = await fetchArtifactObjectUrl(artifact)
      const stale = previewUrls.value[artifact.path]
      if (stale) URL.revokeObjectURL(stale)
      previewUrls.value[artifact.path] = objectUrl
      loadedUrlByPath.value[artifact.path] = sourceKey
    } catch {
      unavailablePreviews.value = new Set([...unavailablePreviews.value, artifact.path])
    }
  }))
}

function openGalleryWindow() {
  galleryVisible.value = true
  void loadPreviewUrls(previewArtifacts.value)
}

// 窗口关闭后释放非缩略图预览占用的 object URL,重新打开时再按需加载
watch(galleryVisible, (visible) => {
  if (visible) return
  const keep = new Set(inlineThumbArtifacts.value.map((artifact) => artifact.path))
  for (const [path, url] of Object.entries(previewUrls.value)) {
    if (!keep.has(path)) {
      URL.revokeObjectURL(url)
      delete previewUrls.value[path]
      delete loadedUrlByPath.value[path]
    }
  }
})

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
  () => {
    // 产物被移除时释放对应 object URL
    const keep = new Set(previewArtifacts.value.map((artifact) => artifact.path))
    for (const [path, url] of Object.entries(previewUrls.value)) {
      if (!keep.has(path)) {
        URL.revokeObjectURL(url)
        delete previewUrls.value[path]
        delete loadedUrlByPath.value[path]
      }
    }
    const nextUnavailable = new Set([...unavailablePreviews.value].filter((path) => keep.has(path)))
    if (nextUnavailable.size !== unavailablePreviews.value.size) unavailablePreviews.value = nextUnavailable
    // 内联只急切加载缩略图;产物窗口打开期间补全其余预览
    void loadPreviewUrls(galleryVisible.value ? previewArtifacts.value : inlineThumbArtifacts.value)
  },
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
      <button
        type="button"
        class="message-artifacts__open-window"
        @click="openGalleryWindow"
      >
        <NIcon :size="14" aria-hidden="true"><OpenOutline /></NIcon>
        打开产物窗口
      </button>
    </div>

    <!-- 内联只留缩略图条:大图/PDF/文件列表收进产物窗口,不再挤占对话正文,
         用户打开对话即可先看到 AI 的最新回复 -->
    <div v-if="inlineThumbArtifacts.length" class="message-artifacts__thumbs">
      <button
        v-for="artifact in inlineThumbArtifacts"
        :key="artifact.path"
        type="button"
        class="message-artifacts__thumb"
        :aria-label="`放大查看 ${fileName(artifact.path)}`"
        @click="openMediaPreview(artifact)"
      >
        <img
          v-if="previewUrls[artifact.path]"
          :src="previewUrls[artifact.path]"
          :alt="`${fileName(artifact.path)} 预览`"
        />
        <span v-else class="message-artifacts__thumb-loading" aria-live="polite">
          {{ unavailablePreviews.has(artifact.path) ? '不可预览' : '加载中…' }}
        </span>
      </button>
      <button
        v-if="previewArtifacts.length > inlineThumbArtifacts.length"
        type="button"
        class="message-artifacts__thumb is-more"
        :aria-label="`还有 ${previewArtifacts.length - inlineThumbArtifacts.length} 个可预览文件`"
        @click="openGalleryWindow"
      >
        +{{ previewArtifacts.length - inlineThumbArtifacts.length }}
      </button>
    </div>
    <p class="message-artifacts__hint">大图与文件的完整预览、下载已移至产物窗口</p>

    <NModal
      v-model:show="galleryVisible"
      preset="card"
      :title="`分析产物 · 已生成 ${artifactItems.length} 个文件`"
      style="width: min(92vw, 1200px)"
      :bordered="false"
      segmented
    >
      <div class="artifact-gallery-window__body">
        <div v-if="previewArtifacts.length" class="message-artifacts__images">
          <figure v-for="artifact in previewArtifacts" :key="artifact.path" class="message-artifacts__image-card">
            <div class="message-artifacts__preview">
              <button
                v-if="isImageArtifact(artifact.path) && previewUrls[artifact.path]"
                type="button"
                class="message-artifacts__zoom-trigger"
                :aria-label="`放大查看 ${fileName(artifact.path)}`"
                @click="openMediaPreview(artifact)"
              >
                <img
                  :src="previewUrls[artifact.path]"
                  :alt="`${fileName(artifact.path)} 预览`"
                />
                <span class="message-artifacts__zoom-hint" aria-hidden="true">点击放大</span>
              </button>
              <!-- PDF：卡片内直接内嵌预览（blob URL 走浏览器原生 PDF 查看器），点击放大仍可用 -->
              <button
                v-else-if="isPdfArtifact(artifact.path) && previewUrls[artifact.path]"
                type="button"
                class="message-artifacts__pdf-trigger"
                :aria-label="`放大预览 ${fileName(artifact.path)}`"
                @click="openMediaPreview(artifact)"
              >
                <iframe
                  class="message-artifacts__pdf-inline"
                  :src="pdfInlineSrc(previewUrls[artifact.path])"
                  :title="`${fileName(artifact.path)} PDF 预览`"
                  tabindex="-1"
                  aria-hidden="true"
                />
                <span class="message-artifacts__zoom-hint" aria-hidden="true">点击放大</span>
              </button>
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
                {{ downloadingPaths.has(artifact.path) ? '下载中…' : failedDownloadPaths.has(artifact.path) ? '重试下载' : isImageArtifact(artifact.path) ? '下载图片' : '下载' }}
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
      </div>
    </NModal>

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

    <NModal
      v-model:show="mediaPreviewVisible"
      preset="card"
      :title="mediaPreviewTitle"
      style="width: min(92vw, 1200px)"
      :bordered="false"
      segmented
    >
      <div class="artifact-media__toolbar">
        <template v-if="mediaPreviewKind === 'image'">
          <button
            type="button"
            class="artifact-media__tool"
            aria-label="缩小"
            :disabled="mediaZoom <= ZOOM_MIN"
            @click="zoomBy(-ZOOM_STEP)"
          >
            <NIcon :size="16" aria-hidden="true"><RemoveOutline /></NIcon>
          </button>
          <span class="artifact-media__zoom-value" aria-live="polite">{{ Math.round(mediaZoom * 100) }}%</span>
          <button
            type="button"
            class="artifact-media__tool"
            aria-label="放大"
            :disabled="mediaZoom >= ZOOM_MAX"
            @click="zoomBy(ZOOM_STEP)"
          >
            <NIcon :size="16" aria-hidden="true"><AddOutline /></NIcon>
          </button>
          <button
            type="button"
            class="artifact-media__tool"
            aria-label="重置缩放"
            @click="mediaZoom = 1"
          >
            <NIcon :size="16" aria-hidden="true"><RefreshOutline /></NIcon>
          </button>
        </template>
        <span class="artifact-media__spacer" />
        <button type="button" class="artifact-media__action" @click="printMediaPreview">
          <NIcon :size="14" aria-hidden="true"><PrintOutline /></NIcon>
          打印
        </button>
        <button
          type="button"
          class="artifact-media__action"
          :disabled="downloadingPaths.has(mediaPreviewPath)"
          @click="downloadArtifact(mediaPreviewPath)"
        >
          <NIcon :size="14" aria-hidden="true"><DownloadOutline /></NIcon>
          {{ downloadingPaths.has(mediaPreviewPath) ? '下载中…' : '下载' }}
        </button>
      </div>
      <div class="artifact-media__stage" @wheel="onMediaWheel">
        <img
          v-if="mediaPreviewKind === 'image' && mediaPreviewSrc"
          :src="mediaPreviewSrc"
          :alt="`${mediaPreviewTitle} 放大预览`"
          class="artifact-media__image"
          :style="{ transform: `scale(${mediaZoom})` }"
        />
        <iframe
          v-else-if="mediaPreviewKind === 'pdf' && mediaPreviewSrc"
          :src="mediaPreviewSrc"
          :title="`${mediaPreviewTitle} PDF 预览`"
          class="artifact-media__pdf"
        />
      </div>
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

.message-artifacts__header .message-artifacts__hint {
  flex: 0 0 auto;
}

p.message-artifacts__hint {
  margin: 0;
}

.message-artifacts__open-window {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  color: var(--brand-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  background: var(--brand-primary-light);
  border: 0;
  border-radius: 999px;
  cursor: pointer;
}

.message-artifacts__open-window:hover {
  background: color-mix(in srgb, var(--brand-primary-light) 72%, var(--brand-primary));
}

.message-artifacts__open-window:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.message-artifacts__thumbs {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  margin-bottom: var(--space-sm, 8px);
  overflow-x: auto;
}

.message-artifacts__thumb {
  flex: 0 0 auto;
  width: 64px;
  height: 64px;
  padding: 0;
  overflow: hidden;
  background: var(--bg-secondary, var(--bg-card));
  border: 1px solid var(--stardust-border-soft);
  border-radius: 8px;
  cursor: zoom-in;
}

.message-artifacts__thumb:hover {
  border-color: var(--brand-primary);
}

.message-artifacts__thumb:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.message-artifacts__thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.message-artifacts__thumb.is-more {
  display: grid;
  place-items: center;
  color: var(--brand-primary);
  font-size: 13px;
  font-weight: 600;
  background: var(--brand-primary-light);
  cursor: pointer;
}

.message-artifacts__thumb-loading {
  padding: 4px;
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 1.3;
  text-align: center;
}

.artifact-gallery-window__body {
  max-height: 70vh;
  overflow: auto;
  padding-right: 2px;
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
  background: var(--bg-secondary, var(--bg-card));
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

.message-artifacts__zoom-trigger {
  position: relative;
  display: block;
  width: 100%;
  padding: 0;
  background: transparent;
  border: 0;
  cursor: zoom-in;
}

.message-artifacts__zoom-hint {
  position: absolute;
  right: var(--space-sm, 8px);
  bottom: var(--space-sm, 8px);
  padding: 2px 8px;
  color: var(--text-primary);
  font-size: 11px;
  background: color-mix(in srgb, var(--bg-card) 82%, transparent);
  border: 1px solid var(--stardust-border-soft);
  border-radius: 999px;
  opacity: 0;
  transition: opacity 140ms ease-out;
  pointer-events: none;
}

.message-artifacts__zoom-trigger:hover .message-artifacts__zoom-hint,
.message-artifacts__zoom-trigger:focus-visible .message-artifacts__zoom-hint,
.message-artifacts__pdf-trigger:hover .message-artifacts__zoom-hint,
.message-artifacts__pdf-trigger:focus-visible .message-artifacts__zoom-hint {
  opacity: 1;
}

.message-artifacts__pdf-trigger {
  position: relative;
  display: block;
  width: 100%;
  min-height: 180px;
  padding: 0;
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  background: transparent;
  border: 0;
  overflow: hidden;
  cursor: zoom-in;
}

/* 卡片内嵌 PDF 预览：绝对定位撑满卡片，pointer-events 关闭让点击穿透到放大按钮 */
.message-artifacts__pdf-inline {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: var(--bg-secondary, var(--bg-card));
  pointer-events: none;
}

.message-artifacts__pdf-trigger:hover {
  color: var(--brand-primary);
}

.message-artifacts__zoom-trigger:focus-visible,
.message-artifacts__pdf-trigger:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: -2px;
}

.artifact-media__toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 8px);
  margin-bottom: var(--space-md, 12px);
  padding: 6px var(--space-sm, 8px);
  background: var(--bg-secondary, var(--bg-card));
  border: 1px solid var(--stardust-border-soft);
  border-radius: 8px;
}

.artifact-media__tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  color: var(--text-secondary);
  background: transparent;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.artifact-media__tool:hover:not(:disabled) {
  color: var(--text-primary);
  background: var(--stardust-border-soft);
}

.artifact-media__tool:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.artifact-media__zoom-value {
  min-width: 44px;
  color: var(--text-secondary);
  font-size: 12px;
  text-align: center;
}

.artifact-media__spacer {
  flex: 1;
}

.artifact-media__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  color: var(--brand-primary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  background: var(--brand-primary-light);
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.artifact-media__action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--brand-primary-light) 72%, var(--brand-primary));
}

.artifact-media__action:disabled {
  cursor: wait;
  opacity: 0.72;
}

.artifact-media__tool:focus-visible,
.artifact-media__action:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.artifact-media__stage {
  display: grid;
  place-items: center;
  max-height: 72vh;
  overflow: auto;
  background: color-mix(in srgb, var(--bg-card) 86%, var(--brand-primary-light));
  border-radius: 8px;
}

.artifact-media__image {
  display: block;
  max-width: 100%;
  transform-origin: top center;
  transition: transform 140ms ease-out;
}

.artifact-media__pdf {
  display: block;
  width: 100%;
  height: 72vh;
  border: 0;
  background: var(--bg-card, #fff);
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

/* 预览弹层经 NModal teleport 到 body，吃不到聊天流内的 hljs 暗色覆盖，
   这里补齐 github-dark 系 token 颜色，避免亮色主题 token 落在深底上不可读 */
:root[data-theme="dark"] .artifact-code-preview.hljs {
  color: #c9d1d9;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-comment),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-quote),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-meta) {
  color: #8b949e;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-keyword),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-selector-tag),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-deletion) {
  color: #ff7b72;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-string),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-regexp),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-addition) {
  color: #a5d6ff;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-number),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-literal),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-attr),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-attribute),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-variable),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-template-variable),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-type),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-selector-class),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-selector-id) {
  color: #79c0ff;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-title),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-section),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-function) {
  color: #d2a8ff;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-built_in) {
  color: #ffa657;
}
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-name),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-selector-attr),
:root[data-theme="dark"] .artifact-code-preview.hljs :deep(.hljs-selector-pseudo) {
  color: #7ee787;
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
  /* --bg-secondary 未在全局令牌中定义，兜底到卡片底色（亮色同为白，暗色为深色卡片面） */
  background: var(--bg-secondary, var(--bg-card));
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

@media (prefers-reduced-motion: reduce) {
  .message-artifacts__zoom-hint,
  .artifact-media__image {
    transition: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .message-artifacts__preview {
    background: var(--bg-secondary, var(--bg-card));
  }
}
</style>
