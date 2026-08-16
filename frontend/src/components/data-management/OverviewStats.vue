<script setup lang="ts">
/**
 * 顶部数据大盘 —— Samples / Files / Projects / Storage 四卡
 */
import { NIcon, NProgress } from 'naive-ui'
import type { Component } from 'vue'
import {
  FlaskOutline, FolderOpenOutline, FolderOutline, CloudUploadOutline,
} from '@vicons/ionicons5'
import type { QuotaInfo } from '@/types'

defineProps<{
  samples: number
  files: number
  projects: number
  quota: QuotaInfo
}>()

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(2)} ${sizes[i]}`
}

interface CardDef {
  key: string
  label: string
  icon: Component
}
const cards: CardDef[] = [
  { key: 'samples', label: 'Samples 样本', icon: FlaskOutline },
  { key: 'files', label: 'Files 文件', icon: FolderOpenOutline },
  { key: 'projects', label: 'Projects 项目', icon: FolderOutline },
  { key: 'storage', label: 'Storage 存储', icon: CloudUploadOutline },
]
</script>

<template>
  <div class="overview-stats">
    <div v-for="c in cards" :key="c.key" class="stat-card">
      <div class="stat-icon">
        <NIcon :size="20"><component :is="c.icon" /></NIcon>
      </div>
      <div class="stat-body">
        <span class="stat-label">{{ c.label }}</span>
        <template v-if="c.key === 'storage'">
          <span class="stat-value">{{ formatSize(quota.used) }} <span class="stat-total">/ {{ formatSize(quota.total) }}</span></span>
          <NProgress
            :percentage="Math.min(100, quota.percent)"
            :height="4"
            :show-indicator="false"
            :color="quota.percent >= 91 ? '#F53F3F' : quota.percent >= 71 ? '#FF7D00' : '#165DFF'"
            rail-color="rgba(22,93,255,0.08)"
            class="stat-bar"
          />
          <span class="stat-sub">{{ quota.percent }}% 已用</span>
        </template>
        <template v-else>
          <span class="stat-value">{{ c.key === 'samples' ? samples : c.key === 'files' ? files : projects }}</span>
          <span class="stat-sub">{{ c.key === 'samples' ? '已注册样本' : c.key === 'files' ? '累计文件' : '关联项目' }}</span>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.stat-card {
  height: 88px;
  background: var(--neutral-card, #fff);
  border-radius: var(--radius-lg, 16px);
  box-shadow: var(--shadow-soft, 0 4px 12px rgba(0, 0, 0, 0.05));
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-sizing: border-box;
  border: 1px solid var(--neutral-border);
}
.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md, 12px);
  background: var(--arco-primary-light);
  color: var(--arco-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.stat-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--neutral-text-3, #86909c);
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--neutral-text-1, #1d2129);
  font-variant-numeric: tabular-nums;
  line-height: 1.25;
}
.stat-total {
  font-size: 12px;
  font-weight: 500;
  color: var(--neutral-text-3, #86909c);
}
.stat-sub {
  font-size: 11px;
  color: var(--neutral-text-3, #86909c);
}
.stat-bar {
  margin-top: 2px;
}
@media (max-width: 1100px) {
  .overview-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 600px) {
  .overview-stats {
    grid-template-columns: 1fr;
  }
}
</style>
