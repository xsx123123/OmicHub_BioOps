<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NInput, NTag, NUpload, NUploadDragger, useMessage, type UploadFileInfo } from 'naive-ui'
import { ClipboardOutline, CloudUploadOutline, SparklesOutline, TrashOutline } from '@vicons/ionicons5'
import { calculateStats } from '@/engine/dna/dna'
import type { FastaRecord } from '@/engine/types'

const props = defineProps<{
  modelValue: string
  records: FastaRecord[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  sample: []
}>()

const message = useMessage()
const fileList = ref<UploadFileInfo[]>([])
const firstRecord = computed(() => props.records[0] || null)
const firstStats = computed(() => firstRecord.value ? calculateStats(firstRecord.value.sequence) : null)
const totalLength = computed(() => props.records.reduce((sum, record) => sum + record.length, 0))

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText()
    if (!text.trim()) {
      message.warning('剪贴板中没有可用序列')
      return
    }
    emit('update:modelValue', text)
    message.success('已粘贴剪贴板内容')
  } catch {
    message.error('无法读取剪贴板，请使用 Ctrl/⌘ + V')
  }
}

async function handleFileChange(options: { file: UploadFileInfo }) {
  const file = options.file.file
  if (!file) return
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !['fa', 'fasta', 'fna', 'faa', 'txt'].includes(extension)) {
    message.error('仅支持 .fa、.fasta、.fna、.faa 和 .txt 文件')
    fileList.value = []
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    message.error('本地序列文件不能超过 10 MB')
    fileList.value = []
    return
  }
  emit('update:modelValue', await file.text())
  fileList.value = []
  message.success(`已读取 ${file.name}`)
}
</script>

<template>
  <section class="input-panel" aria-labelledby="sequence-input-title">
    <header class="panel-heading">
      <div>
        <span class="panel-kicker">Sequence input</span>
        <h2 id="sequence-input-title">输入序列</h2>
      </div>
      <div class="input-actions" aria-label="序列输入操作">
        <NButton size="tiny" quaternary @click="pasteFromClipboard">
          <template #icon><NIcon><ClipboardOutline /></NIcon></template>
          粘贴
        </NButton>
        <NButton size="tiny" quaternary @click="emit('sample')">
          <template #icon><NIcon><SparklesOutline /></NIcon></template>
          示例
        </NButton>
        <NButton size="tiny" quaternary :disabled="!modelValue" @click="emit('update:modelValue', '')">
          <template #icon><NIcon><TrashOutline /></NIcon></template>
          清空
        </NButton>
      </div>
    </header>

    <NInput
      :value="modelValue"
      type="textarea"
      :autosize="{ minRows: 12, maxRows: 22 }"
      placeholder=">sequence_1&#10;ATGCGT...&#10;&#10;支持 FASTA 或原始 DNA / RNA / Protein 序列"
      class="sequence-input"
      aria-label="FASTA 或原始序列输入"
      @update:value="emit('update:modelValue', $event)"
    />

    <NUpload
      v-model:file-list="fileList"
      accept=".fa,.fasta,.fna,.faa,.txt"
      :default-upload="false"
      :max="1"
      class="sequence-upload"
      @change="handleFileChange"
    >
      <NUploadDragger>
        <div class="upload-copy">
          <NIcon :size="22"><CloudUploadOutline /></NIcon>
          <div>
            <strong>拖入 FASTA 文件，或点击选择</strong>
            <span>.fa / .fasta / .fna / .faa / .txt，最大 10 MB</span>
          </div>
        </div>
      </NUploadDragger>
    </NUpload>

    <div class="sequence-status" role="status" aria-live="polite">
      <NTag size="small" :type="records.length ? 'success' : 'default'">{{ records.length }} 条序列</NTag>
      <span>总长度 <strong>{{ totalLength.toLocaleString() }}</strong></span>
      <span>类型 <strong>{{ firstRecord?.type?.toUpperCase() || '—' }}</strong></span>
      <span>首条 GC <strong>{{ firstStats ? `${firstStats.gcContent}%` : '—' }}</strong></span>
    </div>
  </section>
</template>

<style scoped>
.input-panel {
  min-width: 0;
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.panel-kicker {
  color: var(--primary-color, var(--arco-primary));
  font-size: var(--font-micro-size);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin: 2px 0 0;
  color: var(--neutral-text-1);
  font-size: 16px;
  line-height: 1.4;
}

.input-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-xs);
}

.sequence-input :deep(textarea) {
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  resize: vertical;
}

.sequence-upload {
  margin-top: var(--space-md);
}

.sequence-upload :deep(.n-upload-dragger) {
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-sm);
}

.upload-copy {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-md);
  color: var(--neutral-text-2);
  text-align: left;
}

.upload-copy .n-icon {
  color: var(--primary-color, var(--arco-primary));
}

.upload-copy strong,
.upload-copy span {
  display: block;
}

.upload-copy strong {
  color: var(--neutral-text-1);
  font-size: 13px;
}

.upload-copy span {
  margin-top: 2px;
  color: var(--neutral-text-3);
  font-size: 11px;
}

.sequence-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-sm) var(--space-lg);
  margin-top: var(--space-md);
  color: var(--neutral-text-3);
  font-size: 12px;
}

.sequence-status strong {
  color: var(--neutral-text-1);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .panel-heading {
    flex-direction: column;
  }

  .input-actions {
    justify-content: flex-start;
  }
}
</style>
