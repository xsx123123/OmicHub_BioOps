<script setup lang="ts">
import type { Report } from '@/types/report'
import {
  NCard, NButton, NTag, NTooltip, NPopconfirm, NSpace, NIcon,
} from 'naive-ui'
import {
  EyeOutline, DownloadOutline, StarOutline, Star,
  TrashOutline, OpenOutline, TimeOutline,
  FileTrayFullOutline, DocumentOutline, ImageOutline,
  FolderOutline,
} from '@vicons/ionicons5'

const props = defineProps<{
  report: Report
}>()

const emit = defineEmits<{
  preview: [report: Report]
  download: [report: Report, fileId: string]
  viewTask: [report: Report]
  toggleStar: [report: Report]
  delete: [report: Report]
}>()

const fileIconMap: Record<string, any> = {
  html: DocumentOutline,
  pdf: FileTrayFullOutline,
  png: ImageOutline,
  csv: DocumentOutline,
  zip: FolderOutline,
}

const statusConfig: Record<string, { label: string; color: string; dot: string }> = {
  generating: { label: '生成中', color: 'orange', dot: 'bg-orange-500' },
  completed: { label: '已完成', color: 'green', dot: 'bg-emerald-500' },
  failed: { label: '失败', color: 'red', dot: 'bg-red-500' },
  expired: { label: '已过期', color: 'gray', dot: 'bg-gray-500' },
}

const status = statusConfig[props.report.status] || statusConfig.generating

function formatTime(iso: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatDuration(seconds: number): string {
  if (!seconds) return '-'
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`
  return `${Math.floor(seconds / 3600)}小时${Math.floor((seconds % 3600) / 60)}分钟`
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '-'
  const now = new Date()
  const target = new Date(iso)
  const diff = now.getTime() - target.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  if (days < 30) return `${Math.floor(days / 7)}周前`
  return formatTime(iso)
}

const primaryFile = props.report.files.find(f => f.is_primary) || props.report.files[0]
</script>

<template>
  <NCard
    class="report-card"
    :class="`report-card--${report.status}`"
    size="small"
    hoverable
  >
    <div class="report-card__content">
      <div class="report-card__icon">
        <span class="text-3xl">{{ report.flow_icon || '📄' }}</span>
      </div>

      <div class="report-card__info">
        <div class="report-card__header">
          <h3 class="report-card__title" :title="report.title">{{ report.title }}</h3>
          <div class="flex items-center gap-2">
            <NTag
              :type="status.color as any"
              size="small"
              round
            >
              <template #icon>
                <span class="w-1.5 h-1.5 rounded-full" :class="status.dot" />
              </template>
              {{ status.label }}
            </NTag>
            <NIcon
              v-if="report.is_starred"
              :component="Star"
              class="text-yellow-500"
              :size="18"
            />
          </div>
        </div>

        <p v-if="report.description" class="report-card__desc">{{ report.description }}</p>

        <div class="report-card__meta">
          <NTooltip trigger="hover">
            <template #trigger>
              <span class="meta-item">
                <NIcon :size="12" :component="TimeOutline" />
                {{ formatRelativeTime(report.created_at) }}
              </span>
            </template>
            {{ formatTime(report.created_at) }}
          </NTooltip>
          <span class="meta-item">{{ report.sample_count }} 个样本</span>
          <span class="meta-item">耗时 {{ formatDuration(report.duration) }}</span>
          <NTag v-if="report.flow_version" size="small" type="info">v{{ report.flow_version }}</NTag>
        </div>

        <div v-if="report.files.length" class="report-card__files">
          <NTag
            v-for="file in report.files"
            :key="file.id"
            size="small"
            :type="file.type === 'html' ? 'primary' : 'default'"
            class="file-tag"
          >
            <span class="file-tag-content">
              <NIcon :size="12" :component="fileIconMap[file.type] || DocumentOutline" />
              <span>{{ file.name }}</span>
              <span class="file-size">({{ formatBytes(file.size) }})</span>
            </span>
          </NTag>
        </div>

        <!-- 生成中提示 -->
        <div v-if="report.status === 'generating'" class="generating-indicator">
          <NSpin :size="14" />
          <span>报告生成中，请稍候...</span>
        </div>
      </div>

      <div class="report-card__actions">
        <NSpace :size="8" align="center">
          <NTooltip v-if="report.status === 'completed' && primaryFile" trigger="hover">
            <template #trigger>
              <NButton size="small" type="primary" @click="emit('preview', report)">
                <template #icon>
                  <NIcon :component="EyeOutline" />
                </template>
                预览
              </NButton>
            </template>
            在线预览 HTML 报告
          </NTooltip>

          <NTooltip v-if="report.status === 'completed' && primaryFile" trigger="hover">
            <template #trigger>
              <NButton size="small" @click="emit('download', report, primaryFile.id)">
                <template #icon>
                  <NIcon :component="DownloadOutline" />
                </template>
                下载
              </NButton>
            </template>
            下载报告文件
          </NTooltip>

          <NTooltip trigger="hover">
            <template #trigger>
              <NButton size="small" quaternary @click="emit('viewTask', report)">
                <template #icon>
                  <NIcon :component="OpenOutline" />
                </template>
                任务
              </NButton>
            </template>
            查看关联任务
          </NTooltip>

          <NTooltip trigger="hover">
            <template #trigger>
              <NButton size="small" quaternary @click="emit('toggleStar', report)">
                <template #icon>
                  <NIcon
                    :component="report.is_starred ? Star : StarOutline"
                    :class="report.is_starred ? 'text-yellow-500' : ''"
                  />
                </template>
              </NButton>
            </template>
            {{ report.is_starred ? '取消收藏' : '收藏' }}
          </NTooltip>

          <NPopconfirm
            positive-text="确认"
            negative-text="取消"
            @positive-click="emit('delete', report)"
          >
            <template #trigger>
              <NButton size="small" quaternary type="error">
                <template #icon>
                  <NIcon :component="TrashOutline" />
                </template>
              </NButton>
            </template>
            确认删除「{{ report.title }}」？此操作不可恢复。
          </NPopconfirm>
        </NSpace>
      </div>
    </div>
  </NCard>
</template>

<style scoped>
.report-card {
  position: relative;
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.report-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 2px 0 0 2px;
}
.report-card--completed::before {
  background: linear-gradient(180deg, var(--success-color, #18a058), #00c853);
}
.report-card--generating::before {
  background: linear-gradient(180deg, var(--warning-color, #f0a020), #ff9800);
  animation: pulse-bar 2s infinite;
}
.report-card--failed::before {
  background: linear-gradient(180deg, var(--error-color, #d03050), #ff4d4f);
}
.report-card--expired::before {
  background: linear-gradient(180deg, var(--text-color-3, #999), #a1a7b3);
}
@keyframes pulse-bar {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.report-card:hover {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  transform: translateY(-3px);
}
.report-card:hover .report-card__title {
  color: var(--primary-color);
}
.report-card__content {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.report-card__icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.report-card__info {
  flex: 1;
  min-width: 0;
}
.report-card__header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.report-card__title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-color-1);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s;
}
.report-card__desc {
  font-size: 13px;
  color: var(--text-color-2);
  margin: 0 0 10px;
  line-height: 1.6;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.report-card__meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-color-3);
}
.report-card__files {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.file-tag {
  cursor: default;
}
.file-tag-content {
  display: flex;
  align-items: center;
  gap: 4px;
}
.file-size {
  font-size: 11px;
  color: var(--text-color-3);
  opacity: 0.7;
}
.generating-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--warning-color-suppl, #fff7e6);
  border-radius: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--warning-color, #f0a020);
}
.report-card__actions {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  opacity: 0;
  transition: opacity 0.2s;
}
.report-card:hover .report-card__actions {
  opacity: 1;
}
@media (max-width: 768px) {
  .report-card__content {
    flex-direction: column;
  }
  .report-card__actions {
    width: 100%;
    opacity: 1;
  }
}
</style>
