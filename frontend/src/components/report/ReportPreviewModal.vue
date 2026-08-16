<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Report } from '@/types/report'
import { reportApi } from '@/api/report'
import {
  NModal, NButton, NSpace, NSpin, NIcon,
} from 'naive-ui'
import {
  DownloadOutline, OpenOutline, ExpandOutline, ContractOutline,
  CloseOutline,
} from '@vicons/ionicons5'

const props = defineProps<{
  report: Report | null
}>()

const emit = defineEmits<{
  close: []
}>()

const htmlContent = ref('')
const loading = ref(false)
const isFullscreen = ref(false)

async function loadPreview() {
  if (!props.report) return
  loading.value = true
  try {
    const res = await reportApi.previewReport(props.report.id)
    htmlContent.value = res.data
  } catch {
    htmlContent.value = '<p style="color:var(--neutral-text-3, #999);text-align:center;padding:40px 0;">报告加载失败，请尝试下载查看</p>'
  } finally {
    loading.value = false
  }
}

function handleDownload() {
  if (!props.report) return
  const primary = props.report.files.find(f => f.is_primary) || props.report.files[0]
  if (!primary) return
  const link = document.createElement('a')
  link.href = `/api/v1/reports/${props.report.id}/files/${primary.id}/download`
  link.download = primary.name
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function openInNewTab() {
  if (!props.report) return
  const primary = props.report.files.find(f => f.is_primary) || props.report.files[0]
  if (!primary) return
  window.open(`/api/v1/reports/${props.report.id}/files/${primary.id}/download`, '_blank')
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

watch(() => props.report, (report) => {
  if (report) {
    loadPreview()
  } else {
    htmlContent.value = ''
    isFullscreen.value = false
  }
}, { immediate: true })
</script>

<template>
  <NModal
    :show="!!report"
    :title="report?.title || '报告预览'"
    preset="card"
    :style="{
      width: isFullscreen ? '100vw' : '90vw',
      maxWidth: isFullscreen ? '100vw' : '1200px',
      height: isFullscreen ? '100vh' : 'auto',
      margin: isFullscreen ? 0 : 'auto',
      top: isFullscreen ? 0 : '5vh',
    }"
    :closable="true"
    :mask-closable="false"
    @close="emit('close')"
    @update:show="(v: boolean) => { if (!v) emit('close') }"
  >
    <template #header-extra>
      <NSpace :size="8">
        <NButton size="small" @click="handleDownload">
          <template #icon>
            <NIcon :component="DownloadOutline" />
          </template>
          下载
        </NButton>
        <NButton size="small" @click="openInNewTab">
          <template #icon>
            <NIcon :component="OpenOutline" />
          </template>
          新窗口
        </NButton>
        <NButton size="small" @click="toggleFullscreen">
          <template #icon>
            <NIcon :component="isFullscreen ? ContractOutline : ExpandOutline" />
          </template>
          {{ isFullscreen ? '退出全屏' : '全屏' }}
        </NButton>
        <NButton size="small" quaternary circle @click="emit('close')">
          <template #icon>
            <NIcon :component="CloseOutline" />
          </template>
        </NButton>
      </NSpace>
    </template>

    <NSpin :show="loading" style="width: 100%;">
      <div
        class="preview-container"
        :style="{ height: isFullscreen ? 'calc(100vh - 120px)' : '70vh' }"
      >
        <iframe
          v-if="htmlContent"
          :srcdoc="htmlContent"
          :title="report?.title || '报告预览'"
          class="preview-iframe"
          sandbox="allow-scripts allow-same-origin"
        />
      </div>
    </NSpin>
  </NModal>
</template>

<style scoped>
.preview-container {
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: var(--neutral-card);
}
.preview-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
</style>
