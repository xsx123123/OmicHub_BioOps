<script setup lang="ts">
import { computed } from 'vue'
import type { MonitorWidget, WorkflowMonitorSummary } from '@/types/workflowMonitor'

const props = defineProps<{
  widget: MonitorWidget
  summary: WorkflowMonitorSummary
  loading?: boolean
}>()

const field = computed(() => String(props.widget.query?.field || 'total'))
const value = computed(() => {
  const raw = props.summary[field.value as keyof WorkflowMonitorSummary] ?? 0
  if (props.widget.style?.unit === 'percent') return `${Number(raw).toFixed(1)}%`
  return String(raw)
})
const tone = computed(() => String(props.widget.style?.tone || 'default'))
</script>

<template>
  <section class="metric-widget" :class="`tone-${tone}`">
    <span class="metric-label">{{ widget.title }}</span>
    <strong class="metric-value">{{ loading ? '-' : value }}</strong>
  </section>
</template>

<style scoped>
.metric-widget {
  min-height: 86px;
  padding: 16px;
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
  background: var(--neutral-card);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.metric-label {
  font-size: 13px;
  color: var(--neutral-text-2);
}

.metric-value {
  font-size: 28px;
  line-height: 1;
  color: var(--neutral-text-1);
  font-variant-numeric: tabular-nums;
}

.tone-info .metric-value { color: #2563eb; }
.tone-success .metric-value { color: #059669; }
.tone-warning .metric-value { color: #d97706; }
.tone-danger .metric-value { color: #dc2626; }
</style>
