import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { workflowMonitorApi } from '@/api/workflowMonitor'
import type {
  MonitorTemplate,
  WorkflowEvent,
  WorkflowMonitorSummary,
  WorkflowTaskSnapshot,
} from '@/types/workflowMonitor'

function defaultSummary(): WorkflowMonitorSummary {
  return {
    running_count: 0,
    failed_today: 0,
    avg_running_progress: 0,
    stale_task_count: 0,
    warning_count_10m: 0,
    error_count_10m: 0,
    total: 0,
  }
}

export const useWorkflowMonitorStore = defineStore('workflowMonitor', () => {
  const template = ref<MonitorTemplate | null>(null)
  const summary = ref<WorkflowMonitorSummary>(defaultSummary())
  const tasks = ref<WorkflowTaskSnapshot[]>([])
  const events = ref<WorkflowEvent[]>([])
  const errors = ref<WorkflowEvent[]>([])
  const loading = ref(false)
  const connected = ref(false)
  const filters = reactive<Record<string, unknown>>({})

  const runningTasks = computed(() => tasks.value.filter((task) => task.status === 'running'))

  function initFilters(nextTemplate: MonitorTemplate) {
    Object.keys(filters).forEach((key) => delete filters[key])
    for (const filter of nextTemplate.filters || []) {
      filters[filter.key] = filter.default ?? (filter.type === 'search' ? '' : 'all')
    }
  }

  async function fetchTemplate(templateId = 'default') {
    template.value = await workflowMonitorApi.getTemplate(templateId)
    initFilters(template.value)
  }

  async function fetchOverview() {
    loading.value = true
    try {
      const data = await workflowMonitorApi.getOverview({
        status: filters.status ?? 'running',
        flow_id: filters.flow_id ?? 'all',
        keyword: filters.keyword ?? '',
      })
      summary.value = data.summary
      tasks.value = data.tasks
      events.value = data.events
      errors.value = data.errors
    } finally {
      loading.value = false
    }
  }

  function setFilter(key: string, value: unknown) {
    filters[key] = value
  }

  function applyEvent(event: WorkflowEvent) {
    events.value = [event, ...events.value].slice(0, 200)
    if (['warning', 'error', 'critical'].includes(event.level)) {
      errors.value = [event, ...errors.value].slice(0, 100)
    }
  }

  function applyTaskSnapshot(task: WorkflowTaskSnapshot) {
    const idx = tasks.value.findIndex((item) => item.id === task.id)
    if (idx >= 0) tasks.value[idx] = { ...tasks.value[idx], ...task }
    else tasks.value.unshift(task)
    recomputeSummary()
  }

  function applySummary(next: WorkflowMonitorSummary) {
    summary.value = next
  }

  function recomputeSummary() {
    const running = tasks.value.filter((task) => task.status === 'running')
    const avg = running.length
      ? running.reduce((sum, task) => sum + Number(task.progress_percent || 0), 0) / running.length
      : 0
    summary.value = {
      ...summary.value,
      running_count: running.length,
      avg_running_progress: Math.round(avg * 100) / 100,
      total: tasks.value.length,
    }
  }

  function reset() {
    template.value = null
    summary.value = defaultSummary()
    tasks.value = []
    events.value = []
    errors.value = []
    Object.keys(filters).forEach((key) => delete filters[key])
  }

  return {
    template,
    summary,
    tasks,
    runningTasks,
    events,
    errors,
    loading,
    connected,
    filters,
    fetchTemplate,
    fetchOverview,
    setFilter,
    applyEvent,
    applyTaskSnapshot,
    applySummary,
    reset,
  }
})
