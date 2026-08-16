<script setup lang="ts">
/**
 * 存储透视卡 —— 用量占比 + 文件夹数 + 清理缓存 / 管理存储
 */
import { NButton, NIcon, NProgress } from 'naive-ui'
import { TrashOutline, SettingsOutline } from '@vicons/ionicons5'
import type { QuotaInfo } from '@/types'

const props = defineProps<{
  quota: QuotaInfo
  directoryCount: number
}>()

const emit = defineEmits<{ (e: 'clean-cache'): void; (e: 'manage-storage'): void }>()

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

function tierColor(p: number) {
  if (p >= 91) return '#F53F3F'
  if (p >= 71) return '#FF7D00'
  return '#00B42A'
}
</script>

<template>
  <div class="widget">
    <h3 class="widget-title">存储透视</h3>
    <div class="usage-row">
      <NProgress
        type="circle"
        :percentage="Math.min(100, props.quota.percent)"
        :stroke-width="8"
        :radius="36"
        :color="tierColor(props.quota.percent)"
        rail-color="rgba(0,0,0,0.06)"
      >
        <span class="circle-pct">{{ props.quota.percent }}%</span>
      </NProgress>
      <div class="usage-meta">
        <span class="usage-val">{{ formatSize(props.quota.used) }}</span>
        <span class="usage-total">/ {{ formatSize(props.quota.total) }}</span>
        <span class="usage-folders">📁 {{ props.directoryCount }} 个文件夹</span>
      </div>
    </div>
    <div class="widget-actions">
      <NButton size="small" block @click="emit('clean-cache')">
        <template #icon><NIcon><TrashOutline /></NIcon></template>
        清理缓存
      </NButton>
      <NButton size="small" block quaternary @click="emit('manage-storage')">
        <template #icon><NIcon><SettingsOutline /></NIcon></template>
        管理存储
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.widget {
  background: var(--neutral-card, #fff);
  border: none;
  border-radius: var(--radius-card);
  padding: 16px;
  box-shadow: var(--shadow-card);
}
.widget-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 0 0 14px;
}
.usage-row {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 16px;
}
.circle-pct {
  font-size: 14px;
  font-weight: 700;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
}
.usage-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.usage-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
}
.usage-total {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
}
.usage-folders {
  font-size: 12px;
  color: var(--neutral-text-2, #4e5969);
  margin-top: 4px;
}
.widget-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
