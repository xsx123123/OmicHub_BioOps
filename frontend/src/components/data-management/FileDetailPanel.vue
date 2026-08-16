<script setup lang="ts">
/**
 * 文件详情面板 —— Finder 右栏选中态：展示文件 Metadata + 操作
 */
import { computed } from 'vue'
import { NButton, NIcon, NTag, NTooltip, useMessage } from 'naive-ui'
import {
  CloseOutline, DownloadOutline, MoveOutline, TrashOutline,
  DocumentOutline, CopyOutline, EyeOutline,
} from '@vicons/ionicons5'
import type { DataFile } from '@/types'

const props = defineProps<{ file: DataFile }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'preview', file: DataFile): void
  (e: 'download', file: DataFile): void
  (e: 'move', file: DataFile): void
  (e: 'delete', file: DataFile): void
}>()
const message = useMessage()

const TYPE_META: Record<string, { label: string; type?: 'info' | 'success' | 'warning' | 'default'; color?: string }> = {
  fastq: { label: 'FASTQ', type: 'info' },
  bam: { label: 'BAM', type: 'success' },
  vcf: { label: 'VCF', type: 'warning' },
  count_matrix: { label: '矩阵', color: '#0FC6C2' },
  h5ad: { label: 'H5AD', color: '#8E54E9' },
  rds: { label: 'RDS', color: '#8E54E9' },
  meta: { label: '元数据', type: 'default' },
  report: { label: '报告', type: 'default' },
  image: { label: '图片', type: 'default' },
  other: { label: '其他', type: 'default' },
}

const tagMeta = computed(() => TYPE_META[props.file.file_type] || TYPE_META.other)

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

const metaEntries = computed(() => {
  const m = props.file.metadata || {}
  return Object.entries(m).filter(([, v]) => v !== null && v !== undefined && v !== '')
})

const checksumShort = computed(() => {
  const c = props.file.checksum || ''
  return c ? `${c.slice(0, 8)}…${c.slice(-6)}` : '—'
})

async function copyChecksum() {
  if (!props.file.checksum) return
  try {
    await navigator.clipboard.writeText(props.file.checksum)
    message.success('已复制校验和')
  } catch {
    message.error('复制失败')
  }
}
</script>

<template>
  <div class="file-detail">
    <div class="detail-header">
      <span class="detail-title">文件详情</span>
      <NButton size="tiny" quaternary title="关闭" @click="emit('close')">
        <template #icon><NIcon><CloseOutline /></NIcon></template>
      </NButton>
    </div>

    <div class="detail-preview">
      <div class="preview-icon">
        <NIcon :size="40" color="#165DFF"><DocumentOutline /></NIcon>
      </div>
      <span class="preview-name" :title="file.original_name">{{ file.original_name }}</span>
      <div class="preview-tags">
        <NTag
          size="small"
          round
          :type="tagMeta.type"
          :color="tagMeta.color ? { color: tagMeta.color, textColor: '#fff', borderColor: tagMeta.color } : undefined"
        >
          {{ tagMeta.label }}
        </NTag>
      </div>
    </div>

    <div class="detail-section">
      <div class="kv-row">
        <span class="kv-key">大小</span>
        <span class="kv-val">{{ formatSize(file.size) }}</span>
      </div>
      <div class="kv-row">
        <span class="kv-key">创建时间</span>
        <span class="kv-val">{{ file.created_at ? new Date(file.created_at).toLocaleString('zh-CN') : '—' }}</span>
      </div>
      <div class="kv-row">
        <span class="kv-key">所在目录</span>
        <span class="kv-val">{{ file.directory || '根目录' }}</span>
      </div>
      <div class="kv-row">
        <span class="kv-key">校验和</span>
        <span class="kv-val mono">
          <NTooltip trigger="hover">
            <template #trigger>
              <span class="checksum" @click="copyChecksum">
                {{ checksumShort }}
                <NIcon :size="12" class="copy-ic"><CopyOutline /></NIcon>
              </span>
            </template>
            {{ file.checksum || '无' }}（点击复制）
          </NTooltip>
        </span>
      </div>
    </div>

    <div v-if="metaEntries.length" class="detail-section">
      <h4 class="section-label">Metadata</h4>
      <div v-for="[k, v] in metaEntries" :key="k" class="kv-row">
        <span class="kv-key">{{ k }}</span>
        <span class="kv-val" :title="String(v)">{{ typeof v === 'object' ? JSON.stringify(v) : String(v) }}</span>
      </div>
    </div>

    <div class="detail-actions">
      <NButton size="small" block type="primary" @click="emit('preview', file)">
        <template #icon><NIcon><EyeOutline /></NIcon></template>
        预览
      </NButton>
      <NButton size="small" block @click="emit('download', file)">
        <template #icon><NIcon><DownloadOutline /></NIcon></template>
        下载
      </NButton>
      <NButton size="small" block @click="emit('move', file)">
        <template #icon><NIcon><MoveOutline /></NIcon></template>
        移动
      </NButton>
      <NButton size="small" block type="error" ghost @click="emit('delete', file)">
        <template #icon><NIcon><TrashOutline /></NIcon></template>
        删除
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.file-detail {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: var(--radius-lg, 16px);
  padding: 16px;
  box-shadow: var(--shadow-soft, 0 4px 12px rgba(0,0,0,0.05));
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.detail-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
}
.detail-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 8px 18px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--neutral-border, #e5e6eb);
}
.preview-icon {
  width: 64px;
  height: 64px;
  border-radius: var(--radius-md, 12px);
  background: #F5F8FF;
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  text-align: center;
  word-break: break-all;
  max-width: 100%;
}
.preview-tags {
  display: flex;
  gap: 6px;
}
.detail-section {
  margin-bottom: 16px;
}
.section-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--neutral-text-3, #86909c);
  margin: 0 0 10px;
}
.kv-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  font-size: 12px;
}
.kv-key {
  color: var(--neutral-text-3, #86909c);
  flex-shrink: 0;
}
.kv-val {
  color: var(--neutral-text-1, #1d2129);
  text-align: right;
  word-break: break-all;
  max-width: 60%;
}
.mono {
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.checksum {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.copy-ic {
  opacity: 0.5;
}
.detail-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}
</style>
