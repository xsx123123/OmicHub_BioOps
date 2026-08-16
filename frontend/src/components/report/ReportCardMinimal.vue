<script setup lang="ts">
import { computed } from 'vue'
import type { Report } from '@/types/report'
import {
  NIcon, NTooltip, NPopconfirm, NSpin,
} from 'naive-ui'
import {
  EyeOutline, DownloadOutline, OpenOutline,
  StarOutline, Star, TrashOutline, WarningOutline,
  FlaskOutline, GitNetworkOutline, DocumentTextOutline,
  TimeOutline, SparklesOutline,
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
  optimize: [report: Report]
}>()

const primaryFile = props.report.files.find(f => f.is_primary)

const flowMeta = computed(() => {
  const id = props.report.flow_id
  if (id === 'rna_seq' || id === 'rna-seq') {
    return {
      icon: FlaskOutline,
      label: 'RNA-seq',
      color: '#165DFF',
      bg: 'rgba(22, 93, 255, 0.08)',
    }
  }
  if (id === 'atac_seq' || id === 'atac-seq') {
    return {
      icon: GitNetworkOutline,
      label: 'ATAC-seq',
      color: '#8E54E9',
      bg: 'rgba(142, 84, 233, 0.08)',
    }
  }
  return {
    icon: DocumentTextOutline,
    label: props.report.flow_name || id,
    color: '#4E5969',
    bg: 'rgba(78, 89, 105, 0.08)',
  }
})

const statusConfig: Record<string, { label: string; bg: string; color: string }> = {
  completed: { label: '已完成', bg: '#e8ffea', color: '#00b42a' },
  generating: { label: '生成中', bg: '#e8f3ff', color: '#165dff' },
  failed: { label: '失败', bg: '#ffece8', color: '#f53f3f' },
  expired: { label: '已过期', bg: '#f2f3f5', color: '#86909c' },
}

const status = computed(() => statusConfig[props.report.status] || statusConfig.generating)

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

function handlePrimaryClick() {
  if (!primaryFile) return
  emit('preview', props.report)
}
</script>

<template>
  <div
    class="report-card-minimal"
    :class="[report.status, { 'is-starred': report.is_starred }]"
  >
    <!-- Card Header -->
    <div class="card-header">
      <div class="header-left">
        <div
          class="flow-icon-wrap"
          :style="{ background: flowMeta.bg, color: flowMeta.color }"
        >
          <NIcon :size="20" :component="flowMeta.icon" />
        </div>
        <div class="title-group">
          <h3 class="report-title" :title="report.title">
            {{ report.title }}
          </h3>
          <span class="flow-label">{{ flowMeta.label }}</span>
        </div>
      </div>

      <div class="header-right">
        <span
          class="status-badge"
          :style="{ background: status.bg, color: status.color }"
        >
          <span v-if="report.status === 'generating'" class="status-dot breathing" />
          {{ status.label }}
        </span>
        <NIcon
          v-if="report.is_starred"
          :component="Star"
          class="star-icon"
          :size="18"
        />
      </div>
    </div>

    <!-- Card Body -->
    <div v-if="report.description" class="card-body">
      <p class="report-desc">{{ report.description }}</p>
    </div>

    <!-- Card Footer -->
    <div class="card-footer">
      <div class="meta-tags">
        <span class="meta-tag">
          <NIcon :size="12" :component="flowMeta.icon" />
          {{ report.flow_version }}
        </span>
        <span class="meta-tag">{{ report.sample_count }} 样本</span>
        <span class="meta-tag">运行 {{ formatDuration(report.duration) }}</span>
        <NTooltip trigger="hover">
          <template #trigger>
            <span class="meta-tag">
              <NIcon :size="12" :component="TimeOutline" />
              {{ formatRelativeTime(report.created_at) }}
            </span>
          </template>
          {{ formatTime(report.created_at) }}
        </NTooltip>
      </div>

      <div class="footer-actions">
        <!-- 已完成报告：主题色文字按钮 -->
        <template v-if="report.status === 'completed' && primaryFile">
          <button class="text-action preview" @click.stop="handlePrimaryClick">
            <NIcon :size="14" :component="EyeOutline" />
            <span>在线预览</span>
          </button>
          <button
            class="text-action download"
            @click.stop="emit('download', report, primaryFile.id)"
          >
            <NIcon :size="14" :component="DownloadOutline" />
            <span>下载报告</span>
          </button>
        </template>

        <!-- 生成中提示 -->
        <div v-else-if="report.status === 'generating'" class="status-hint generating">
          <NSpin :size="14" />
          <span>报告生成中，请稍候...</span>
        </div>

        <!-- 失败提示 -->
        <div v-else-if="report.status === 'failed'" class="status-hint failed">
          <NIcon :size="14" :component="WarningOutline" />
          <span>生成失败，请查看任务日志</span>
        </div>

        <!-- 次要操作：任务、收藏、删除 -->
        <div class="icon-actions">
          <NTooltip trigger="hover">
            <template #trigger>
              <button class="icon-btn" title="查看任务" @click.stop="emit('viewTask', report)">
                <NIcon :size="14" :component="OpenOutline" />
              </button>
            </template>
            查看关联任务
          </NTooltip>

          <NTooltip trigger="hover">
            <template #trigger>
              <button
                class="icon-btn"
                :class="{ starred: report.is_starred }"
                :title="report.is_starred ? '取消收藏' : '收藏'"
                @click.stop="emit('toggleStar', report)"
              >
                <NIcon :size="14" :component="report.is_starred ? Star : StarOutline" />
              </button>
            </template>
            {{ report.is_starred ? '取消收藏' : '收藏' }}
          </NTooltip>

          <NPopconfirm
            positive-text="确认"
            negative-text="取消"
            @positive-click="emit('delete', report)"
          >
            <template #trigger>
              <button class="icon-btn action-delete" title="删除" @click.stop>
                <NIcon :size="14" :component="TrashOutline" />
              </button>
            </template>
            确认删除「{{ report.title }}」？
          </NPopconfirm>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-card-minimal {
  background: var(--neutral-card);
  border-radius: 16px;
  padding: 20px 24px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--neutral-border);
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  cursor: pointer;
  position: relative;
  overflow: hidden;
}
.report-card-minimal:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 32px color-mix(in srgb, var(--arco-primary) 10%, transparent), 0 4px 12px rgba(0, 0, 0, 0.04);
  border-color: color-mix(in srgb, var(--arco-primary) 20%, transparent);
}
.report-card-minimal:hover .report-title {
  color: var(--arco-primary);
}

/* Card Header */
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.header-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.flow-icon-wrap {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}
.report-card-minimal:hover .flow-icon-wrap {
  transform: scale(1.08);
}
.title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}
.report-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--neutral-text-1);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s;
  line-height: 1.4;
}
.flow-label {
  font-size: 12px;
  color: var(--neutral-text-2);
  font-weight: 500;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.status-dot.breathing {
  animation: breathe-dot 1.8s ease-in-out infinite;
}
.star-icon {
  color: #ffb800;
}

/* Card Body */
.card-body {
  margin-bottom: 16px;
  padding-left: 58px;
}
.report-desc {
  font-size: 14px;
  color: var(--neutral-text-2);
  margin: 0;
  line-height: 1.6;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* Card Footer */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-left: 58px;
}
.meta-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  background: var(--neutral-hover);
  border-radius: 6px;
  font-size: 12px;
  color: var(--neutral-text-2);
  font-weight: 500;
  line-height: 18px;
  transition: background 0.15s;
}
.report-card-minimal:hover .meta-tag {
  background: var(--neutral-hover);
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.text-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border: none;
  background: transparent;
  color: var(--arco-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s;
}
.text-action:hover {
  background: color-mix(in srgb, var(--arco-primary) 6%, transparent);
}
.text-action.optimize {
  color: #8e54e9;
}
.text-action.download {
  color: var(--kimi-chart-4);
}
.text-action.download:hover {
  background: color-mix(in srgb, var(--kimi-chart-4) 6%, transparent);
}

.status-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 8px;
}
.status-hint.generating {
  color: var(--arco-primary);
  background: var(--arco-primary-light);
}
.status-hint.failed {
  color: var(--arco-danger);
  background: var(--arco-danger-light);
}

.icon-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--neutral-text-4);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.icon-btn:hover {
  background: var(--neutral-hover);
  color: var(--neutral-text-2);
}
.icon-btn.starred {
  color: #ffb800;
}
.icon-btn.starred:hover {
  background: var(--arco-warning-light);
}
.icon-btn.action-delete:hover {
  color: var(--arco-danger);
  background: var(--arco-danger-light);
}

/* 失败状态弱化 */
.report-card-minimal.failed .report-title {
  color: var(--neutral-text-3);
  text-decoration: line-through;
}
.report-card-minimal.failed:hover .report-title {
  color: var(--arco-danger);
}
.report-card-minimal.expired .report-title {
  color: var(--neutral-text-3);
}

/* 收藏高亮 */
.report-card-minimal.is-starred {
  border-color: rgba(255, 184, 0, 0.35);
}
.report-card-minimal.is-starred:hover {
  border-color: rgba(255, 184, 0, 0.55);
  box-shadow: 0 12px 32px rgba(255, 184, 0, 0.1), 0 4px 12px rgba(0, 0, 0, 0.04);
}

@keyframes breathe-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}

@media (max-width: 768px) {
  .report-card-minimal {
    padding: 16px;
  }
  .card-body,
  .card-footer {
    padding-left: 0;
  }
  .card-header {
    flex-direction: column;
    gap: 12px;
  }
  .header-right {
    width: 100%;
    justify-content: space-between;
  }
  .card-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
