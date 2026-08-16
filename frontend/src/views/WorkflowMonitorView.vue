<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NAlert, NSpin } from 'naive-ui'
import MonitorFilterBar from '@/components/workflow-monitor/MonitorFilterBar.vue'
import MonitorWidgetRenderer from '@/components/workflow-monitor/MonitorWidgetRenderer.vue'
import { useWorkflowMonitorStore } from '@/stores/workflowMonitor'
import { useWorkflowMonitorWebSocket } from '@/composables/useWorkflowMonitorWebSocket'
import type { MonitorWidget } from '@/types/workflowMonitor'
import PageHeader from '@/components/PageHeader.vue'

const store = useWorkflowMonitorStore()
const { template, summary, tasks, events, errors, loading, connected, filters } = storeToRefs(store)
const { connect, disconnect } = useWorkflowMonitorWebSocket()

const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null
let filterTimer: ReturnType<typeof setTimeout> | null = null

const metrics = computed(() => (template.value?.widgets || []).filter((w) => w.type === 'metric'))
const mainWidgets = computed(() => (template.value?.widgets || []).filter((w) => w.type !== 'metric'))
const fallbackSeconds = computed(() => template.value?.refresh?.fallback_interval_seconds || 5)

function widgetStyle(widget: MonitorWidget) {
  const layout = widget.layout?.desktop
  if (!layout) return {}
  return {
    gridColumn: `span ${Math.min(Math.max(layout.w || 12, 1), 12)}`,
  }
}

async function refresh() {
  error.value = ''
  try {
    await store.fetchOverview()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '获取流程监控数据失败'
  }
}

function updateFilter(key: string, value: unknown) {
  store.setFilter(key, value)
}

function startFallbackPolling() {
  stopFallbackPolling()
  pollTimer = setInterval(() => {
    if (!connected.value) refresh()
  }, fallbackSeconds.value * 1000)
}

function stopFallbackPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(filters, () => {
  if (filterTimer) clearTimeout(filterTimer)
  filterTimer = setTimeout(refresh, 250)
}, { deep: true })

onMounted(async () => {
  try {
    await store.fetchTemplate('default')
    await refresh()
    connect()
    startFallbackPolling()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '初始化流程监控失败'
  }
})

onUnmounted(() => {
  disconnect()
  stopFallbackPolling()
  if (filterTimer) clearTimeout(filterTimer)
})
</script>

<template>
  <div class="page-container workflow-monitor-page">
    <PageHeader title="流程监控" :subtitle="template?.description || '实时监测 Snakemake 分析流程进度、日志和错误'">
      <template #actions>
      <MonitorFilterBar
        v-if="template"
        :filters="template.filters"
        :values="filters"
        :loading="loading"
        @update="updateFilter"
        @refresh="refresh"
      />
      </template>
    </PageHeader>

    <p class="monitor-subtitle" role="status" :aria-live="connected ? 'polite' : 'off'">
      <span class="connection-dot" :class="{ connected }" aria-hidden="true"></span>
      {{ connected ? '实时连接' : '轮询模式' }}
    </p>

    <NAlert v-if="error" type="error" :title="error" class="monitor-alert" role="alert" />

    <NSpin :show="loading && !tasks.length" :aria-busy="loading">
      <div v-if="template" class="monitor-content">
        <div class="metric-grid">
          <MonitorWidgetRenderer
            v-for="widget in metrics"
            :key="widget.id"
            :widget="widget"
            :summary="summary"
            :tasks="tasks"
            :events="events"
            :errors="errors"
            :loading="loading"
          />
        </div>

        <div class="widget-grid">
          <MonitorWidgetRenderer
            v-for="widget in mainWidgets"
            :key="widget.id"
            :widget="widget"
            :summary="summary"
            :tasks="tasks"
            :events="events"
            :errors="errors"
            :loading="loading"
            :style="widgetStyle(widget)"
          />
        </div>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.workflow-monitor-page {
  min-height: 100%;
  background: var(--neutral-bg);
}

.monitor-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 20px;
}

.monitor-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0 0;
  color: var(--neutral-text-2);
  font-size: 13px;
}

.connection-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #d97706;
}

.connection-dot.connected {
  background: #059669;
}

.monitor-alert {
  margin-bottom: 16px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.widget-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 12px;
  align-items: start;
}

@media (max-width: 1024px) {
  .monitor-header {
    flex-direction: column;
  }
  .metric-grid,
  .widget-grid {
    grid-template-columns: 1fr;
  }
  .widget-grid > * {
    grid-column: span 1 !important;
  }
}
</style>
