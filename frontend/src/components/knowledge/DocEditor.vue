<script setup lang="ts">
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { NInput, useMessage } from 'naive-ui'
import { computed } from 'vue'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const props = defineProps<{
  modelValue: string
  editSummary?: string
  isAdmin?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:editSummary': [value: string]
}>()

const themeStore = useThemeStore()
const mdTheme = computed<'light' | 'dark'>(() => (themeStore.isDark ? 'dark' : 'light'))

const message = useMessage()

function handleChange(value: string) {
  emit('update:modelValue', value)
}

function handleSummaryChange(value: string) {
  emit('update:editSummary', value)
}

async function handleUploadImg(files: File[], callback: (urls: string[]) => void) {
  const urls: string[] = new Array(files.length)
  try {
    await Promise.all(
      files.map(async (file, index) => {
        const formData = new FormData()
        formData.append('file', file)
        const res = await apiClient.post<{ url: string }>('/docs/knowledge/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        urls[index] = res.data.url
      }),
    )
    callback(urls)
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || '图片上传失败')
  }
}
</script>

<template>
  <div class="doc-editor">
    <div class="summary-row">
      <NInput
        :value="editSummary"
        placeholder="编辑摘要（可选）：简述本次变更"
        @update:value="handleSummaryChange"
      />
    </div>
    <MdEditor
      :model-value="props.modelValue"
      :preview="false"
      :theme="mdTheme"
      :toolbars-exclude="['github', 'save', 'pageFullscreen', 'catalog']"
      :style="{ height: 'calc(100vh - 280px)' }"
      placeholder="在此编写 Markdown 文档…"
      @update:model-value="handleChange"
      @on-upload-img="handleUploadImg"
    />
  </div>
</template>

<style scoped>
.doc-editor {
  width: 100%;
}

.summary-row {
  margin-bottom: 12px;
}

.doc-editor :deep(.md-editor) {
  border-radius: 8px;
  border: 1px solid var(--neutral-border);
}
</style>
