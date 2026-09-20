<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { NProgress } from 'naive-ui'
import apiClient from '@/api/client'

interface Props {
  taskId: string
  progressUrl?: string
  resultUrl?: string
  /** 数据库任务详情 URL；传入时使用带 JWT 的轮询，不走 EventSource。 */
  taskUrl?: string
}

const props = withDefaults(defineProps<Props>(), {
  progressUrl: '',
  resultUrl: '',
  taskUrl: '',
})

const emit = defineEmits<{
  completed: [status: 'success' | 'error']
}>()

interface ProgressEvent {
  task_id: string
  phase: string
  progress: number
  message: string
}

interface TaskDetail {
  status: 'pending' | 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
  progress: number
  error_message?: string
  logs?: Array<{ message: string }>
}

const phase = ref('PENDING')
const progress = ref(0)
const message = ref('等待进度...')
const status = ref<'pending' | 'running' | 'success' | 'error'>('pending')
const error = ref('')
const streamDisconnected = ref(false)
let eventSource: EventSource | null = null
let pollTimer: ReturnType<typeof setTimeout> | null = null
let completedEmitted = false

const displayPhase = computed(() => {
  const map: Record<string, string> = {
    PENDING: '等待中',
    QUEUED: '排队中',
    STARTING: '启动沙盒',
    RUNNING: '执行中',
    ALIGNING: '多序列比对',
    BUILDING: '构建进化树',
    BOOTSTRAPPING: 'Bootstrap 评估',
    FORMATTING: '格式化结果',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
  }
  return map[phase.value] || phase.value
})

const nprogressStatus = computed(() => {
  if (status.value === 'success') return 'success'
  if (status.value === 'error') return 'error'
  return 'default'
})

function finish(finalStatus: 'success' | 'error') {
  if (completedEmitted) return
  completedEmitted = true
  emit('completed', finalStatus)
  stopPolling()
  eventSource?.close()
  eventSource = null
}

function connect() {
  if (eventSource) return
  const url = props.progressUrl || `/api/v1/tasks/${props.taskId}/progress`
  eventSource = new EventSource(url)
  streamDisconnected.value = false

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as ProgressEvent
      phase.value = data.phase || phase.value
      progress.value = Math.min(Math.max(data.progress || 0, 0), 1)
      message.value = data.message || message.value
      if (data.phase === 'COMPLETED') {
        status.value = 'success'
        finish('success')
      } else if (data.phase === 'FAILED') {
        status.value = 'error'
        error.value = data.message || '任务执行失败'
        finish('error')
      } else {
        status.value = 'running'
      }
    } catch {
      // 忽略解析失败的非 JSON 事件
    }
  }

  eventSource.onerror = () => {
    eventSource?.close()
    eventSource = null
    streamDisconnected.value = true
    message.value = '实时进度连接已断开；任务仍可能继续执行。'
  }
}

function taskApiUrl(): string {
  return props.taskUrl.replace(/^\/api\/v1/, '') || `/tasks/${props.taskId}`
}

async function pollTask() {
  try {
    const response = await apiClient.get<TaskDetail>(taskApiUrl())
    const task = response.data
    error.value = ''
    progress.value = Math.min(Math.max(Number(task.progress || 0), 0), 1)
    phase.value = task.status.toUpperCase()
    const lastLog = task.logs?.[task.logs.length - 1]?.message
    message.value = lastLog || task.error_message || message.value

    if (task.status === 'success') {
      progress.value = 1
      status.value = 'success'
      finish('success')
      return
    }
    if (task.status === 'failed' || task.status === 'cancelled') {
      status.value = 'error'
      error.value = task.error_message || (task.status === 'cancelled' ? '任务已取消' : '任务执行失败')
      finish('error')
      return
    }
    status.value = task.status === 'pending' || task.status === 'queued' ? 'pending' : 'running'
  } catch {
    error.value = '任务状态获取失败，稍后自动重试'
  }
  pollTimer = setTimeout(pollTask, 2000)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

onMounted(() => {
  if (props.taskUrl) pollTask()
  else connect()
})

onUnmounted(() => {
  eventSource?.close()
  eventSource = null
  stopPolling()
})
</script>

<template>
  <div class="task-progress-card" :class="status">
    <div class="task-header">
      <span class="task-icon">{{ status === 'success' ? '✅' : status === 'error' ? '❌' : '⏳' }}</span>
      <span class="task-title">异步任务 {{ taskId.slice(0, 8) }}</span>
      <span class="task-phase">{{ displayPhase }}</span>
    </div>
    <n-progress
      type="line"
      :percentage="Math.round(progress * 100)"
      :status="nprogressStatus"
      :show-indicator="true"
    />
    <div class="task-message">{{ message }}</div>
    <div v-if="streamDisconnected" class="task-stream-warning">实时连接中断，请稍后刷新查看最新状态。</div>
    <div v-if="resultUrl && status === 'success'" class="task-actions">
      <a :href="resultUrl" target="_blank">查看结果</a>
    </div>
    <div v-if="error" class="task-error">{{ error }}</div>
  </div>
</template>

<style scoped lang="scss">
.task-progress-card {
  margin-top: 12px;
  padding: 14px;
  background: var(--chat-surface, #f8f9fa);
  border: 1px solid var(--chat-border, #e8e8e8);
  border-radius: 8px;
}
.task-progress-card.success {
  border-color: #b7eb8f;
  background: #f6ffed;
}
.task-progress-card.error {
  border-color: #ffccc7;
  background: #fff2f0;
}
/* 深色模式：状态底色跟随全局 danger/success 浅底变量 */
:root[data-theme="dark"] .task-progress-card.success {
  border-color: color-mix(in srgb, var(--arco-success, #22c55e) 40%, transparent);
  background: var(--arco-success-light, rgba(34, 197, 94, 0.15));
}
:root[data-theme="dark"] .task-progress-card.error {
  border-color: color-mix(in srgb, var(--arco-danger, #ef4444) 40%, transparent);
  background: var(--arco-danger-light, rgba(239, 68, 68, 0.15));
}
.task-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
}
.task-icon { font-size: 16px; }
.task-title {
  font-weight: 600;
  color: var(--chat-text-primary, #1a1a1a);
}
.task-phase {
  margin-left: auto;
  color: var(--chat-text-muted, #999);
}
.task-message {
  margin-top: 8px;
  font-size: 12px;
  color: var(--chat-text-secondary, #666);
}
.task-actions {
  margin-top: 10px;
  text-align: right;
}
.task-actions a {
  font-size: 12px;
  color: var(--chat-accent, #4f8ef7);
  text-decoration: none;
}
.task-actions a:hover { text-decoration: underline; }
.task-error {
  margin-top: 8px;
  font-size: 12px;
  color: #d03050;
}
.task-stream-warning {
  margin-top: 8px;
  font-size: 12px;
  color: var(--oh-warning, #d08a00);
}
</style>
