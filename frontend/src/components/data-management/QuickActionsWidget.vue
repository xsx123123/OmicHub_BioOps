<script setup lang="ts">
/**
 * 快捷操作中心 —— Upload FASTQ / Batch Upload / Create Folder / Download Metadata Template
 */
import { NButton, NIcon } from 'naive-ui'
import {
  CloudUploadOutline, AddCircleOutline, FolderOpenOutline, DownloadOutline,
} from '@vicons/ionicons5'
import { useUploadStore } from '@/stores/upload'
import { useMessage } from 'naive-ui'

const uploadStore = useUploadStore()
const message = useMessage()

const emit = defineEmits<{ (e: 'create-folder'): void }>()

function openUpload() {
  uploadStore.open()
}
function batchUpload() {
  uploadStore.open()
  message.info('批量上传：可在弹窗中拖入多个文件')
}
function metadataTemplate() {
  message.info('元数据模板下载即将上线')
}
</script>

<template>
  <div class="widget">
    <h3 class="widget-title">快捷操作</h3>
    <div class="action-grid">
      <NButton size="small" type="primary" @click="openUpload">
        <template #icon><NIcon><CloudUploadOutline /></NIcon></template>
        Upload FASTQ
      </NButton>
      <NButton size="small" @click="batchUpload">
        <template #icon><NIcon><AddCircleOutline /></NIcon></template>
        Batch Upload
      </NButton>
      <NButton size="small" @click="emit('create-folder')">
        <template #icon><NIcon><FolderOpenOutline /></NIcon></template>
        Create Folder
      </NButton>
      <NButton size="small" quaternary @click="metadataTemplate">
        <template #icon><NIcon><DownloadOutline /></NIcon></template>
        Metadata Template
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.widget {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.widget-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 0 0 14px;
}
.action-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
</style>
