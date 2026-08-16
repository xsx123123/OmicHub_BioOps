<script setup lang="ts">
/**
 * 分块上传组件 —— 纯展示层，状态由 upload store 全局托管。
 * 支持最小化为悬浮球（跨页面持续上传）。
 */
import {
  NButton,
  NIcon,
  NProgress,
  NSpace,
  NTag,
  NUpload,
  useMessage,
} from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import {
  CloudUploadOutline, PauseOutline, PlayOutline, CloseOutline,
  ContractOutline, CheckmarkCircleOutline,
} from '@vicons/ionicons5'
import { useUploadStore } from '@/stores/upload'
import { storeToRefs } from 'pinia'
import type { UploadQueueItem } from '@/types'

const uploadStore = useUploadStore()
const { queue, targetDirectory } = storeToRefs(uploadStore)
const message = useMessage()

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

/** NUpload before-upload：接管原始 File，阻止默认上传 */
function handleBeforeUpload({ file }: { file: UploadFileInfo }): boolean {
  const raw = file.file
  if (raw) {
    uploadStore.addFile(raw)
    message.info(`已加入上传队列：${raw.name}`)
  }
  return false
}

function pause(item: UploadQueueItem) {
  uploadStore.pause(item.id)
}
function resume(item: UploadQueueItem) {
  uploadStore.resume(item.id)
}
async function cancel(item: UploadQueueItem) {
  await uploadStore.cancel(item.id)
}

function statusTagType(status: UploadQueueItem['status']) {
  const map: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
    completed: 'success',
    uploading: 'info',
    merging: 'info',
    paused: 'warning',
    failed: 'error',
    cancelled: 'default',
    pending: 'default',
  }
  return map[status] || 'default'
}

const statusText: Record<string, string> = {
  completed: '已完成',
  uploading: '上传中',
  merging: '合并中',
  paused: '已暂停',
  failed: '失败',
  cancelled: '已取消',
  pending: '等待中',
}
</script>

<template>
  <div class="chunk-uploader">
    <!-- 能力标签条 -->
    <div class="capability-tags">
      <NTag size="small" type="success" round :bordered="false">
        <template #icon><NIcon><CheckmarkCircleOutline /></NIcon></template>
        Chunk Upload 分块上传
      </NTag>
      <NTag size="small" type="success" round :bordered="false">
        <template #icon><NIcon><CheckmarkCircleOutline /></NIcon></template>
        Resume Upload 断点续传
      </NTag>
      <NTag size="small" type="success" round :bordered="false">
        <template #icon><NIcon><CheckmarkCircleOutline /></NIcon></template>
        Multiple Files 多文件
      </NTag>
      <NButton size="small" quaternary class="minimize-btn" title="最小化为悬浮球" @click="uploadStore.minimize()">
        <template #icon><NIcon><ContractOutline /></NIcon></template>
        最小化
      </NButton>
    </div>

    <NUpload
      :show-file-list="false"
      :default-upload="false"
      multiple
      directory-dnd
      @before-upload="handleBeforeUpload"
    >
      <div class="drop-zone">
        <NIcon :size="32" class="drop-icon"><CloudUploadOutline /></NIcon>
        <p class="drop-title">拖拽文件到此处上传，或点击选择</p>
        <p class="drop-desc">支持 FASTQ / BAM / VCF / CRAM / ZIP 等大文件，分块续传</p>
        <p v-if="targetDirectory" class="drop-target">目标目录：{{ targetDirectory || '根目录' }}</p>
      </div>
    </NUpload>

    <div v-if="queue.length" class="queue-panel">
      <div class="queue-head">
        <span>上传队列 ({{ queue.length }})</span>
        <NButton size="tiny" quaternary @click="uploadStore.removeCompleted()">清除已完成</NButton>
      </div>
      <div v-for="item in queue" :key="item.id" class="queue-item">
        <div class="queue-item-head">
          <span class="queue-name">{{ item.file.name }}</span>
          <NSpace :size="8" align="center">
            <NTag :type="statusTagType(item.status)" size="small" round>
              {{ statusText[item.status] || item.status }}
            </NTag>
            <span class="queue-meta">{{ formatSize(item.file.size) }}</span>
            <span v-if="item.speed > 0 && item.status === 'uploading'" class="queue-meta">
              {{ formatSize(item.speed) }}/s
            </span>
            <NButton v-if="item.status === 'uploading'" size="tiny" quaternary @click="pause(item)">
              <template #icon><NIcon><PauseOutline /></NIcon></template>
            </NButton>
            <NButton v-if="item.status === 'paused'" size="tiny" quaternary type="primary" @click="resume(item)">
              <template #icon><NIcon><PlayOutline /></NIcon></template>
            </NButton>
            <NButton v-if="!['completed', 'cancelled'].includes(item.status)" size="tiny" quaternary @click="cancel(item)">
              <template #icon><NIcon><CloseOutline /></NIcon></template>
            </NButton>
            <NIcon v-if="item.status === 'completed'" color="#52c41a"><CheckmarkCircleOutline /></NIcon>
          </NSpace>
        </div>
        <NProgress
          :percentage="item.progress"
          :status="item.status === 'failed' ? 'error' : item.status === 'completed' ? 'success' : 'default'"
          :show-indicator="false"
          :height="6"
        />
        <div class="queue-chunks">
          {{ item.uploadedChunks }} / {{ item.totalChunks }} 分片
          <span v-if="item.error" class="queue-err">{{ item.error }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chunk-uploader {
  margin-bottom: 0;
}
.capability-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--neutral-border, #e5e6eb);
}
.minimize-btn {
  margin-left: auto;
}
.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 28px;
  border: 1.5px dashed var(--neutral-border, #d9d9d9);
  border-radius: 10px;
  background: var(--neutral-fill, #fafafa);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.drop-zone:hover {
  border-color: #165DFF;
  background: rgba(22, 93, 255, 0.04);
}
.drop-icon {
  color: #6B8DD6;
  margin-bottom: 8px;
}
.drop-title {
  margin: 0 0 4px;
  font-size: 14px;
  color: var(--neutral-text-1, #1d2129);
}
.drop-desc {
  margin: 0;
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.drop-target {
  margin: 6px 0 0;
  font-size: 12px;
  color: #165DFF;
  font-weight: 500;
}
.queue-panel {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.queue-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-2, #4e5969);
}
.queue-item {
  padding: 10px 12px;
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
}
.queue-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.queue-name {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-meta {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.queue-chunks {
  margin-top: 6px;
  font-size: 11px;
  color: var(--neutral-text-3, #86909c);
}
.queue-err {
  margin-left: 8px;
  color: #f53f3f;
}
</style>
