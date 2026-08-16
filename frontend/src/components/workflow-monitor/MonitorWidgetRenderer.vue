<script setup lang="ts">
import type {
  MonitorWidget,
  WorkflowEvent,
  WorkflowMonitorSummary,
  WorkflowTaskSnapshot,
} from '@/types/workflowMonitor'
import MetricWidget from './widgets/MetricWidget.vue'
import TaskTableWidget from './widgets/TaskTableWidget.vue'
import EventStreamWidget from './widgets/EventStreamWidget.vue'
import ErrorListWidget from './widgets/ErrorListWidget.vue'

defineProps<{
  widget: MonitorWidget
  summary: WorkflowMonitorSummary
  tasks: WorkflowTaskSnapshot[]
  events: WorkflowEvent[]
  errors: WorkflowEvent[]
  loading?: boolean
}>()
</script>

<template>
  <MetricWidget
    v-if="widget.type === 'metric'"
    :widget="widget"
    :summary="summary"
    :loading="loading"
  />
  <TaskTableWidget
    v-else-if="widget.type === 'task_table'"
    :widget="widget"
    :tasks="tasks"
    :loading="loading"
  />
  <EventStreamWidget
    v-else-if="widget.type === 'event_stream'"
    :widget="widget"
    :events="events"
    :loading="loading"
  />
  <ErrorListWidget
    v-else-if="widget.type === 'error_list'"
    :widget="widget"
    :events="errors"
    :loading="loading"
  />
  <div v-else class="monitor-widget unsupported">
    <div class="widget-title">{{ widget.title }}</div>
    <p>暂不支持的监控组件：{{ widget.type }}</p>
  </div>
</template>

<style scoped>
.monitor-widget.unsupported {
  padding: 16px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-card);
  color: var(--neutral-text-2);
}

.widget-title {
  font-weight: 600;
  color: var(--neutral-text-1);
}
</style>
