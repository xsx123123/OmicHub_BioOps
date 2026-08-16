<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NIcon, NProgress, NTooltip, useMessage } from 'naive-ui'
import { TrashOutline } from '@vicons/ionicons5'
import apiClient from '@/api/client'
import type { QuotaInfo } from '@/types'

const emit = defineEmits<{ (e: 'cleanup'): void; (e: 'refresh'): void }>()
const message = useMessage()
const quota = ref<QuotaInfo>({ used: 0, total: 0, percent: 0 })

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

/** 按阈值返回进度条状态与文案 */
const tier = computed(() => {
  const p = quota.value.percent
  if (p >= 91) return { status: 'error' as const, color: '#F53F3F', text: '配额即将耗尽，请尽快清理' }
  if (p >= 71) return { status: 'warning' as const, color: '#FF7D00', text: '空间已偏紧，建议适度清理' }
  return { status: 'success' as const, color: '#00B42A', text: '存储健康' }
})

async function fetchQuota() {
  try {
    const res = await apiClient.get<QuotaInfo>('/files/quota')
    quota.value = res.data
  } catch {
    /* 静默失败，不打扰用户 */
  }
}

function handleCleanup() {
  emit('cleanup')
  message.info('已筛选临时文件，可在列表中删除无用数据')
}

defineExpose({ refresh: fetchQuota })
onMounted(fetchQuota)
</script>

<template>
  <div class="storage-compact">
    <NTooltip trigger="hover" placement="bottom">
      <template #trigger>
        <div class="storage-inner">
          <NProgress
            type="circle"
            :percentage="quota.percent"
            :stroke-width="6"
            :radius="14"
            :show-indicator="false"
            :color="tier.color"
            :rail-color="'var(--neutral-fill, #e5e6eb)'"
          />
          <div class="storage-text">
            <span class="storage-usage">
              {{ formatSize(quota.used) }} / {{ formatSize(quota.total) }}
            </span>
            <span class="storage-pct" :style="{ color: tier.color }">{{ quota.percent }}%</span>
          </div>
        </div>
      </template>
      <span>{{ tier.text }}（{{ formatSize(quota.used) }} / {{ formatSize(quota.total) }}）</span>
    </NTooltip>
    <NButton size="tiny" quaternary class="storage-btn" @click="handleCleanup">
      <template #icon><NIcon><TrashOutline /></NIcon></template>
      清理
    </NButton>
  </div>
</template>

<style scoped>
.storage-compact {
  display: flex;
  align-items: center;
  gap: 10px;
}
.storage-inner {
  display: flex;
  align-items: center;
  gap: 8px;
}
.storage-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.2;
}
.storage-usage {
  font-size: 12px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.storage-pct {
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.storage-btn {
  flex-shrink: 0;
}
</style>
