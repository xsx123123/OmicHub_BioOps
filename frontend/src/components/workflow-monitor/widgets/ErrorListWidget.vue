<script setup lang="ts">
import { NButton, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'
import type { MonitorWidget, WorkflowEvent } from '@/types/workflowMonitor'

defineProps<{
  widget: MonitorWidget
  events: WorkflowEvent[]
  loading?: boolean
}>()

const router = useRouter()
</script>

<template>
  <section class="error-widget">
    <div class="widget-header">
      <h3>{{ widget.title }}</h3>
      <span>{{ events.length }}</span>
    </div>
    <div class="error-list">
      <div v-for="event in events" :key="`${event.task_id}-${event.timestamp}-${event.message}`" class="error-row">
        <NTag size="small" type="error" round>{{ event.level }}</NTag>
        <div class="error-body">
          <p :title="event.message">{{ event.message }}</p>
          <small>
            {{ event.flow_id || event.project_name || event.task_id }}
            <template v-if="event.snakemake?.rule"> / {{ event.snakemake.rule }}</template>
          </small>
        </div>
        <NButton size="tiny" text type="primary" @click="router.push(`/tasks/${event.task_id}`)">查看</NButton>
      </div>
      <div v-if="!events.length" class="empty">暂无错误</div>
    </div>
  </section>
</template>

<style scoped>
.error-widget {
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-card);
  overflow: hidden;
}

.widget-header,
.error-row {
  display: flex;
  align-items: center;
}

.widget-header {
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

.error-list {
  padding: 6px 10px;
}

.error-row {
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--neutral-border);
}

.error-row:last-child {
  border-bottom: 0;
}

.error-body {
  min-width: 0;
  flex: 1;
}

p {
  margin: 0;
  color: var(--neutral-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

small {
  color: var(--neutral-text-3);
}

.empty {
  padding: 32px;
  text-align: center;
  color: var(--neutral-text-3);
}
</style>
