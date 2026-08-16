<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NModal, NSelect, NSpace, NSpin, NTag, useMessage } from 'naive-ui'
import { DocumentOutline, CheckmarkCircleOutline } from '@vicons/ionicons5'
import apiClient from '@/api/client'
import type { Directory, FilePickerItem } from '@/types'

const props = defineProps<{
  show: boolean
  /** 文件类型过滤，如 'fastq'；不传则全部 */
  fileType?: string
  /** 选择模式：single / multi */
  multiple?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'select', items: FilePickerItem[]): void
}>()

const message = useMessage()
const directories = ref<Directory[]>([])
const files = ref<FilePickerItem[]>([])
const loading = ref(false)
const currentDirectory = ref('')
const selectedIds = ref<Set<string>>(new Set())

const dirOptions = computed(() => [
  { label: '根目录', value: '' },
  ...directories.value.map((d) => ({ label: d.path, value: d.path })),
])

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

async function fetchDirectories() {
  try {
    const res = await apiClient.get<Directory[]>('/files/directories')
    directories.value = res.data
  } catch {
    /* 静默 */
  }
}

async function fetchFiles() {
  loading.value = true
  try {
    const res = await apiClient.get<FilePickerItem[]>('/files/picker', {
      params: { directory: currentDirectory.value || '', file_type: props.fileType },
    })
    files.value = res.data
  } catch {
    files.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (v) => {
    if (v) {
      selectedIds.value = new Set()
      fetchDirectories()
      fetchFiles()
    }
  },
)

watch(currentDirectory, fetchFiles)

function toggleSelect(row: FilePickerItem) {
  const s = new Set(selectedIds.value)
  if (props.multiple) {
    if (s.has(row.id)) s.delete(row.id)
    else s.add(row.id)
  } else {
    s.clear()
    s.add(row.id)
  }
  selectedIds.value = s
}

function handleConfirm() {
  const selected = files.value.filter((f) => selectedIds.value.has(f.id))
  if (!selected.length) {
    message.warning('请先选择文件')
    return
  }
  emit('select', selected)
  emit('update:show', false)
}

function close() {
  emit('update:show', false)
}

onMounted(() => {
  if (props.show) {
    fetchDirectories()
    fetchFiles()
  }
})
</script>

<template>
  <NModal
    :show="props.show"
    :auto-focus="false"
    :mask-closable="true"
    transform-origin="center"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div class="picker-modal">
      <h3 class="picker-title">
        选择文件
        <NTag v-if="props.fileType" size="small" type="info" round>{{ props.fileType }}</NTag>
        <NTag v-if="props.multiple" size="small" round>多选</NTag>
      </h3>

      <NSpace align="center" class="picker-filter">
        <span class="filter-label">目录：</span>
        <NSelect
          v-model:value="currentDirectory"
          :options="dirOptions"
          size="small"
          filterable
          style="width: 240px"
          placeholder="选择目录"
        />
      </NSpace>

      <NSpin :show="loading">
        <div class="picker-list">
          <table v-if="files.length" class="picker-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th style="width: 100px">类型</th>
                <th style="width: 100px">大小</th>
                <th style="width: 60px">已选</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in files"
                :key="row.id"
                :class="{ 'row-selected': selectedIds.has(row.id) }"
                @click="toggleSelect(row)"
              >
                <td class="picker-name-cell">
                  <NIcon :size="16"><DocumentOutline /></NIcon>
                  <span>{{ row.original_name }}</span>
                </td>
                <td>{{ row.file_type }}</td>
                <td>{{ formatSize(row.size) }}</td>
                <td>
                  <NIcon v-if="selectedIds.has(row.id)" color="#18a058"><CheckmarkCircleOutline /></NIcon>
                </td>
              </tr>
            </tbody>
          </table>
          <NEmpty v-else description="该目录下暂无文件" />
        </div>
      </NSpin>

      <NSpace justify="end" class="picker-actions">
        <NButton @click="close">取消</NButton>
        <NButton type="primary" @click="handleConfirm">确认选择</NButton>
      </NSpace>
    </div>
  </NModal>
</template>

<style scoped>
.picker-modal {
  width: 640px;
  max-width: calc(100vw - 32px);
  background: var(--neutral-card, #fff);
  border-radius: 12px;
  padding: 20px;
  box-sizing: border-box;
}
.picker-title {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.picker-filter {
  margin-bottom: 12px;
}
.filter-label {
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
}
.picker-list {
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 8px;
}
.picker-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.picker-table th {
  text-align: left;
  padding: 8px 12px;
  background: var(--neutral-fill, #fafafa);
  border-bottom: 1px solid var(--neutral-border, #e5e6eb);
  font-weight: 600;
  color: var(--neutral-text-2, #4e5969);
}
.picker-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--neutral-border, #f0f0f0);
}
.picker-table tr {
  cursor: pointer;
}
.picker-table tr:hover {
  background: rgba(22, 93, 255, 0.04);
}
.picker-table tr.row-selected {
  background: rgba(24, 160, 88, 0.08);
}
.picker-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.picker-actions {
  margin-top: 16px;
  width: 100%;
}
</style>
