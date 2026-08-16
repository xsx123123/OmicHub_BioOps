<script setup lang="ts">
import { NButton, NProgress, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'
import type { MonitorWidget, WorkflowTaskSnapshot } from '@/types/workflowMonitor'
import { displayName } from '@/utils/displayName'

defineProps<{
  widget: MonitorWidget
  tasks: WorkflowTaskSnapshot[]
  loading?: boolean
}>()

const router = useRouter()

function statusType(status: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  if (status === 'running') return 'info'
  if (status === 'success') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'queued' || status === 'pending') return 'warning'
  return 'default'
}

function statusText(status: string): string {
  const map: Record<string, string> = {
    pending: '待审核',
    queued: '排队中',
    running: '运行中',
    success: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || status
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
</script>

<template>
  <section class="table-widget">
    <div class="widget-header">
      <h3>{{ widget.title }}</h3>
      <span>{{ tasks.length }} 个任务</span>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>流程</th>
            <th>状态</th>
            <th>进度</th>
            <th>当前 Rule</th>
            <th>最后事件</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td>
              <strong :title="task.name">{{ task.name }}</strong>
              <small v-if="displayName(task)">{{ displayName(task) }}</small>
              <small v-if="task.last_error" class="error" :title="task.last_error">{{ task.last_error }}</small>
            </td>
            <td><span class="flow">{{ task.flow_id }}</span></td>
            <td><NTag size="small" :type="statusType(task.status)" round>{{ statusText(task.status) }}</NTag></td>
            <td class="progress-cell">
              <NProgress
                type="line"
                :percentage="Math.round(task.progress_percent || task.progress * 100)"
                :height="6"
                :show-indicator="false"
                :status="task.status === 'failed' ? 'error' : task.status === 'success' ? 'success' : 'default'"
              />
              <span>{{ Math.round(task.progress_percent || task.progress * 100) }}%</span>
            </td>
            <td><span class="rule" :title="task.current_rule || ''">{{ task.current_rule || '-' }}</span></td>
            <td>{{ formatTime(task.last_event_at || task.created_at) }}</td>
            <td class="actions">
              <NButton size="tiny" text type="primary" @click="router.push(`/tasks/${task.id}`)">详情</NButton>
            </td>
          </tr>
          <tr v-if="!tasks.length">
            <td colspan="7" class="empty">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.table-widget {
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-card);
  overflow: hidden;
}

.widget-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--neutral-border);
}

.widget-header h3 {
  margin: 0;
  font-size: 15px;
  color: var(--neutral-text-1);
}

.widget-header span,
td,
th {
  font-size: 13px;
}

.table-scroll {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 860px;
  border-collapse: collapse;
}

th {
  color: var(--neutral-text-3);
  text-align: left;
  font-weight: 600;
  padding: 10px 12px;
  background: var(--neutral-bg);
}

td {
  padding: 11px 12px;
  border-top: 1px solid var(--neutral-border);
  color: var(--neutral-text-2);
  vertical-align: middle;
}

td strong,
.rule {
  display: block;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--neutral-text-1);
}

td small {
  display: block;
  margin-top: 2px;
  color: var(--neutral-text-3);
}

td small.error {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #dc2626;
}

.flow {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.progress-cell {
  min-width: 150px;
}

.progress-cell span {
  display: inline-block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--neutral-text-3);
}

.actions {
  text-align: right;
}

.empty {
  text-align: center;
  color: var(--neutral-text-3);
  padding: 32px;
}
</style>
