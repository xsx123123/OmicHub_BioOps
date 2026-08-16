<script setup lang="ts">
import { NTag } from 'naive-ui'
import type { MonitorWidget, WorkflowEvent } from '@/types/workflowMonitor'

defineProps<{
  widget: MonitorWidget
  events: WorkflowEvent[]
  loading?: boolean
}>()

function tagType(level: string): 'default' | 'info' | 'success' | 'warning' | 'error' {
  if (level === 'error' || level === 'critical') return 'error'
  if (level === 'warning') return 'warning'
  if (level === 'info') return 'info'
  return 'default'
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleTimeString()
}
</script>

<template>
  <section class="event-widget">
    <div class="widget-header">
      <h3>{{ widget.title }}</h3>
      <span>{{ events.length }}</span>
    </div>
    <div class="event-list">
      <div v-for="event in events" :key="`${event.task_id}-${event.timestamp}-${event.message}`" class="event-row">
        <div class="event-meta">
          <span>{{ formatTime(event.timestamp) }}</span>
          <NTag size="tiny" :type="tagType(event.level)" round>{{ event.level }}</NTag>
        </div>
        <p :title="event.message">{{ event.message }}</p>
        <small>
          {{ event.flow_id || event.project_name || event.task_id }}
          <template v-if="event.snakemake?.rule"> / {{ event.snakemake.rule }}</template>
        </small>
      </div>
      <div v-if="!events.length" class="empty">暂无实时事件</div>
    </div>
  </section>
</template>

<style scoped>
.event-widget {
  height: 100%;
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

.widget-header span {
  color: var(--neutral-text-3);
  font-size: 13px;
}

.event-list {
  max-height: 510px;
  overflow: auto;
  padding: 8px;
}

.event-row {
  padding: 9px 8px;
  border-bottom: 1px solid var(--neutral-border);
}

.event-row:last-child {
  border-bottom: 0;
}

.event-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--neutral-text-3);
}

p {
  margin: 0;
  color: var(--neutral-text-1);
  font-size: 13px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

small {
  display: block;
  margin-top: 4px;
  color: var(--neutral-text-3);
  font-size: 12px;
}

.empty {
  padding: 32px;
  text-align: center;
  color: var(--neutral-text-3);
}
</style>
