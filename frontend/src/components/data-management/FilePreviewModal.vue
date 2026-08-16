<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NIcon, NModal, NSpin } from 'naive-ui'
import { DownloadOutline, DocumentOutline, ImageOutline } from '@vicons/ionicons5'
import type { DataFile } from '@/types'
import apiClient from '@/api/client'
import StudioMonacoEditor from '@/components/studio/StudioMonacoEditor.vue'

const props = defineProps<{
  show: boolean
  file: DataFile | null
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'download', file: DataFile): void
}>()

const MAX_PREVIEW_SIZE = 25 * 1024 * 1024
const imageExtensions = new Set(['avif', 'bmp', 'gif', 'jpeg', 'jpg', 'png', 'svg', 'webp'])
const textExtensions = new Set([
  'bash', 'c', 'cc', 'cpp', 'css', 'csv', 'go', 'h', 'html', 'ini', 'java', 'js', 'json',
  'jsx', 'log', 'md', 'py', 'r', 'rb', 'rs', 'sh', 'sql', 'toml', 'ts', 'tsx', 'txt', 'vue',
  'xml', 'yaml', 'yml',
])
const languageByExtension: Record<string, string> = {
  bash: 'shell', c: 'c', cc: 'cpp', cpp: 'cpp', css: 'css', csv: 'plaintext', go: 'go',
  h: 'c', html: 'html', ini: 'ini', java: 'java', js: 'javascript', json: 'json', jsx: 'javascript',
  log: 'plaintext', md: 'markdown', py: 'python', r: 'r', rb: 'ruby', rs: 'rust', sh: 'shell',
  sql: 'sql', toml: 'ini', ts: 'typescript', tsx: 'typescript', txt: 'plaintext', vue: 'html',
  xml: 'xml', yaml: 'yaml', yml: 'yaml',
}

const loading = ref(false)
const previewError = ref('')
const textContent = ref('')
const imageUrl = ref('')

const extension = computed(() => {
  const name = props.file?.original_name ?? ''
  const lastDot = name.lastIndexOf('.')
  return lastDot >= 0 ? name.slice(lastDot + 1).toLowerCase() : ''
})
const previewKind = computed<'image' | 'text' | 'unsupported'>(() => {
  if (imageExtensions.has(extension.value)) return 'image'
  if (textExtensions.has(extension.value)) return 'text'
  return 'unsupported'
})
const language = computed(() => languageByExtension[extension.value] ?? 'plaintext')
const title = computed(() => props.file?.original_name || '文件预览')
const tooLarge = computed(() => (props.file?.size ?? 0) > MAX_PREVIEW_SIZE)

function clearPreview() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
  textContent.value = ''
  previewError.value = ''
}

async function loadPreview() {
  clearPreview()
  if (!props.show || !props.file || previewKind.value === 'unsupported' || tooLarge.value) return

  loading.value = true
  try {
    const response = await apiClient.get<Blob>(`/files/${props.file.id}/download`, { responseType: 'blob' })
    const blob = response.data
    if (previewKind.value === 'image') {
      imageUrl.value = URL.createObjectURL(blob)
      return
    }

    const content = await blob.text()
    if (content.slice(0, 1024).includes('\u0000')) {
      previewError.value = '该文件包含二进制内容，无法按文本安全预览。'
      return
    }
    textContent.value = content
  } catch {
    previewError.value = '预览加载失败，请稍后重试或直接下载文件。'
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:show', false)
}

watch(() => [props.show, props.file?.id], loadPreview, { immediate: true })
onBeforeUnmount(clearPreview)
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="title"
    :style="{ width: 'min(94vw, 1120px)' }"
    :mask-closable="!loading"
    @update:show="(value) => emit('update:show', value)"
  >
    <template #header-extra>
      <NButton v-if="file" size="small" secondary @click="emit('download', file)">
        <template #icon><NIcon><DownloadOutline /></NIcon></template>
        下载
      </NButton>
    </template>

    <div class="preview-shell">
      <NSpin :show="loading">
        <div v-if="previewKind === 'image' && imageUrl" class="image-preview">
          <img :src="imageUrl" :alt="`${title} 预览`" />
        </div>

        <div v-else-if="previewKind === 'text' && !previewError" class="code-preview">
          <StudioMonacoEditor :model-value="textContent" :language="language" readonly />
        </div>

        <NAlert v-else-if="tooLarge" type="info" :show-icon="false">
          此文件超过 25 MB，为避免影响工作台性能暂不在线预览。请下载后查看。
        </NAlert>

        <NAlert v-else-if="previewKind === 'unsupported'" type="info" :show-icon="false">
          当前支持图片、TXT、CSV、JSON、Markdown 及常见源码文件预览。该文件类型请下载后使用本地工具打开。
        </NAlert>

        <NAlert v-else type="error" :show-icon="false">{{ previewError }}</NAlert>
      </NSpin>
    </div>

    <template #footer>
      <div class="preview-footer">
        <span class="preview-format">
          <NIcon><ImageOutline v-if="previewKind === 'image'" /><DocumentOutline v-else /></NIcon>
          {{ previewKind === 'text' ? `只读 ${language} 预览` : '文件预览' }}
        </span>
        <NButton @click="close">关闭</NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.preview-shell { min-height: 360px; }
.image-preview { display: grid; min-height: 420px; max-height: 68vh; place-items: center; overflow: auto; background: var(--neutral-fill-1, #f7f8fa); border: 1px solid var(--neutral-border, #e5e6eb); border-radius: var(--radius-md, 12px); }
.image-preview img { display: block; max-width: 100%; max-height: 66vh; object-fit: contain; }
.code-preview { height: min(68vh, 720px); min-height: 420px; overflow: hidden; border: 1px solid var(--neutral-border, #e5e6eb); border-radius: var(--radius-md, 12px); }
.preview-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.preview-format { display: inline-flex; align-items: center; gap: 6px; color: var(--neutral-text-3, #86909c); font-size: 12px; }
@media (max-width: 767px) { .preview-shell { min-height: 280px; } .image-preview, .code-preview { min-height: 320px; height: 60vh; } }
</style>
