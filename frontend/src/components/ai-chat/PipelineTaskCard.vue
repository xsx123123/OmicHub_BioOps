<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NProgress, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'
import { useAgentHubStore } from '@/stores/agentHub'
import type { PipelineTaskStatus, PipelineType } from '@/types/pipeline'

const props = defineProps<{
  taskId: string
  pipelineType: PipelineType
  initialStatus?: string
  initialProgress?: number
  preparedParams?: Record<string, unknown>
}>()

const emit = defineEmits<{
  generateVisualization: [taskId: string, pipelineType: PipelineType]
  adjustParameters: [pipelineType: PipelineType]
}>()

const router = useRouter()
const store = useAgentHubStore()
const activeTaskId = ref(props.taskId)
const task = computed(() => store.pipelineTasks[activeTaskId.value])
const status = computed(() => task.value?.status || 'queued')
const statusLabel = computed(() => ({
  pending: '等待提交',
  queued: '排队中',
  running: '分析中',
  success: '已完成',
  failed: '失败',
  cancelled: '已取消',
}[status.value] || status.value))
const statusType = computed(() => {
  if (status.value === 'success') return 'success'
  if (status.value === 'failed' || status.value === 'cancelled') return 'error'
  if (status.value === 'running') return 'info'
  return 'warning'
})
const progressStatus = computed(() => status.value === 'failed' ? 'error' : status.value === 'success' ? 'success' : 'default')
const pipelineLabel = computed(() => props.pipelineType === 'rna_seq' ? 'RNA-seq' : 'ATAC-seq')
const canRetry = computed(() => !!task.value?.preparedParams)

async function retry(): Promise<void> {
  const nextTask = await store.retryPipelineTask(activeTaskId.value)
  activeTaskId.value = nextTask.taskId
}

onMounted(() => {
  store.trackPipelineTask(props.taskId, props.pipelineType, {
    status: (props.initialStatus?.toLowerCase() || 'queued') as PipelineTaskStatus,
    progress: props.initialProgress || 0,
    preparedParams: props.preparedParams,
  })
})
</script>

<template>
  <section class="pipeline-task-card" :aria-label="`${pipelineLabel} 分析任务`">
    <header class="pipeline-header">
      <div>
        <div class="pipeline-title">{{ pipelineLabel }} 分析</div>
        <div class="pipeline-id">任务 {{ activeTaskId.slice(0, 8) }}</div>
      </div>
      <n-tag :type="statusType" size="small" round>{{ statusLabel }}</n-tag>
    </header>

    <n-progress
      type="line"
      :percentage="Math.round(task?.progress || 0)"
      :status="progressStatus"
      :rail-color="'var(--neutral-border)'"
      processing
    />

    <div v-if="task?.metrics" class="pipeline-metrics" aria-live="polite">
      <div><strong>{{ task.metrics.differential_gene_count ?? '—' }}</strong><span>差异基因</span></div>
      <div><strong>{{ task.metrics.upregulated_count ?? '—' }}</strong><span>上调</span></div>
      <div><strong>{{ task.metrics.downregulated_count ?? '—' }}</strong><span>下调</span></div>
    </div>

    <div v-if="task?.error" class="pipeline-error" role="alert">{{ task.error }}</div>

    <footer class="pipeline-actions">
      <template v-if="status === 'success'">
        <n-button size="small" @click="router.push(`/tasks/${activeTaskId}`)">查看详细结果</n-button>
        <n-button size="small" type="primary" @click="emit('generateVisualization', activeTaskId, pipelineType)">
          生成可视化
        </n-button>
      </template>
      <template v-else-if="status === 'failed' || status === 'cancelled'">
        <n-button size="small" :disabled="!canRetry" @click="retry">重试</n-button>
        <n-button size="small" type="primary" @click="emit('adjustParameters', pipelineType)">
          调整参数
        </n-button>
      </template>
      <span v-else class="pipeline-hint">状态每 2.5 秒自动更新</span>
    </footer>
  </section>
</template>

<style scoped>
.pipeline-task-card {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-lg, 12px);
  background: var(--neutral-card);
  color: var(--neutral-text-1);
}
.pipeline-header,
.pipeline-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.pipeline-header { margin-bottom: 12px; }
.pipeline-title { font-size: 14px; font-weight: 650; }
.pipeline-id,
.pipeline-hint { color: var(--neutral-text-3); font-size: 12px; }
.pipeline-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.pipeline-metrics div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  border-radius: var(--radius-md, 8px);
  background: var(--neutral-fill-2);
}
.pipeline-metrics strong { font-size: 16px; }
.pipeline-metrics span { color: var(--neutral-text-3); font-size: 11px; }
.pipeline-error {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md, 8px);
  background: color-mix(in srgb, var(--status-error, #d03050) 10%, transparent);
  color: var(--status-error, #d03050);
  font-size: 12px;
}
.pipeline-actions { justify-content: flex-end; margin-top: 12px; }
@media (max-width: 560px) {
  .pipeline-metrics { grid-template-columns: 1fr; }
  .pipeline-actions { align-items: stretch; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  .pipeline-task-card { transition: none; }
}
</style>
