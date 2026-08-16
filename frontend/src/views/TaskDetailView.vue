<script setup lang="ts">
import type { Task, TaskLog } from '@/types'
import type { RunProgress } from '@/types/download'
import DOMPurify from 'dompurify'
import apiClient from '@/api/client'
import { useDownloadProgress } from '@/composables/useDownloadProgress'
import {
  NAlert,
  NBreadcrumb,
  NBreadcrumbItem,
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NIcon,
  NProgress,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  useMessage,
} from 'naive-ui'
import { CopyOutline } from '@vicons/ionicons5'
import { useClipboard } from '@vueuse/core'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import { formatUserPath, redactUserHomePaths } from '@/utils/userPathDisplay'

const route = useRoute()
const taskId = computed(() => route.params.taskId as string)
const message = useMessage()
const clipboard = useClipboard()

const task = ref<Task | null>(null)
const logs = ref<TaskLog[]>([])
const loading = ref(false)
const error = ref('')
const socket = ref<WebSocket | null>(null)
// 记录上次轮询到的任务状态，用于检测「运行中 → 已完成」的状态转换并触发提示
const lastStatus = ref<string>('')

// 下载进度：逐 run 进度条
const { progress: downloadProgress, startPolling: startProgressPolling, stopPolling: stopProgressPolling } =
  useDownloadProgress(taskId)

type MasDagNode = {
  id: string
  label: string
  agent_id: string
  status: string
  attempt_count: number
}

type TaskDag = {
  status: string
  format?: string
  content?: string
  error?: string
  kind?: string
  nodes?: MasDagNode[]
}

const dag = ref<TaskDag | null>(null)
const dagLoading = ref(false)

function sanitizeSvg(raw: string): string {
  return DOMPurify.sanitize(raw, { USE_PROFILES: { svg: true, svgFilters: true } })
}

const statusType = computed(() => {
  const map: Record<string, 'default' | 'success' | 'warning' | 'error'> = {
    pending: 'default',
    queued: 'warning',
    running: 'warning',
    success: 'success',
    failed: 'error',
    cancelled: 'default',
  }
  return map[task.value?.status || 'pending'] || 'default'
})

const statusText = computed(() => {
  const map: Record<string, string> = {
    pending: '待审核',
    queued: '排队中',
    running: '运行中',
    success: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[task.value?.status || 'pending'] || task.value?.status || '未知'
})

// 数据下载任务的 flow_id 标识（与后端 DOWNLOAD_FLOW_ID 一致）
const DOWNLOAD_FLOW_ID = 'ebi_download'

const isDownloadTask = computed(() => task.value?.flow_id === DOWNLOAD_FLOW_ID)
const isMasTask = computed(() => task.value?.flow_id === 'mas')

// 阶段标签映射
function stageLabel(stage: string): string {
  const map: Record<string, string> = {
    pending: '等待',
    downloading: '下载中',
    extracting: '解压中',
    compressing: '压缩中',
    completed: '完成',
    failed: '失败',
  }
  return map[stage] || stage
}

function stageTagType(stage: string): 'default' | 'info' | 'warning' | 'success' | 'error' {
  const map: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
    pending: 'default',
    downloading: 'info',
    extracting: 'warning',
    compressing: 'warning',
    completed: 'success',
    failed: 'error',
  }
  return map[stage] || 'default'
}

// 将 runs dict 转为数组便于 v-for
const runList = computed<RunProgress[]>(() => {
  if (!downloadProgress.value?.runs) return []
  return Object.values(downloadProgress.value.runs)
})

// 数据路径：仅任务成功且有 result_path 时才有值。展示、通知和复制都不暴露平台用户目录前缀。
const dataPath = computed(() => {
  if (!task.value || task.value.status !== 'success') return ''
  return formatUserPath(task.value.result_path)
})

const workDirectory = computed(() => formatUserPath(task.value?.work_dir))

// 任务完成提示：在「运行中 → 成功」转换时弹通知，并在文案中给出最终数据路径
function notifyOnSuccess(t: Task) {
  const path = formatUserPath(t.result_path)
  if (t.flow_id === DOWNLOAD_FLOW_ID) {
    // 下载任务：明确告知数据落地路径，并引导至「数据管理」
    const text = path
      ? `下载完成！数据已保存至：${path}（可在「数据管理」中查看）`
      : '下载完成！数据已保存至工作目录（可在「数据管理」中查看）'
    message.success(text, { duration: 6000 })
  } else if (path) {
    // 其他任务：若有结果路径同样展示
    message.success(`任务完成，结果路径：${path}`, { duration: 6000 })
  }
}

function copyDataPath() {
  if (!dataPath.value) return
  clipboard.copy(dataPath.value)
  message.success('数据路径已复制到剪贴板')
}

const TERMINAL_STATUSES = ['success', 'failed', 'cancelled']
let pollTimer: ReturnType<typeof setInterval> | null = null

function isTerminalStatus(status?: string): boolean {
  return TERMINAL_STATUSES.includes(status || '')
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => fetchTask(true), 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchTask(silent = false) {
  if (!silent) loading.value = true
  if (!silent) error.value = ''
  try {
    const res = await apiClient.get<Task>(`/tasks/${taskId.value}`)
    task.value = res.data
    // 状态转换检测：仅当上次状态存在且非 success、当前为 success 时提示，
    // 避免首次打开历史已完成任务时重复弹窗
    if (res.data.status === 'success' && lastStatus.value && lastStatus.value !== 'success') {
      notifyOnSuccess(res.data)
    }
    lastStatus.value = res.data.status
    // 仅首次（非静默）拉取历史日志；运行中由 WebSocket 维护 logs，
    // 轮询只更新 task（status/progress），不覆盖 logs 以防日志面板跳动/丢失在途行
    if (!silent) logs.value = res.data.logs || []
    if (isTerminalStatus(res.data.status)) {
      stopPolling()
      stopProgressPolling()
    }
  } catch (e: any) {
    if (!silent) error.value = e.response?.data?.detail || '获取任务详情失败'
  } finally {
    if (!silent) loading.value = false
  }
}

async function fetchDag() {
  dagLoading.value = true
  try {
    const res = await apiClient.get(`/tasks/${taskId.value}/dag`)
    dag.value = res.data
  } catch (e: any) {
    dag.value = { status: 'failed', error: e.response?.data?.detail || '生成 DAG 失败' }
  } finally {
    dagLoading.value = false
  }
}

function connectWebSocket() {
  if (isMasTask.value) return
  const token = localStorage.getItem('access_token')
  if (!token) return

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/v1/tasks/${taskId.value}/ws?token=${token}`

  const ws = new WebSocket(wsUrl)
  socket.value = ws

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as TaskLog
      logs.value.push(data)
    } catch {
      logs.value.push({
        timestamp: new Date().toISOString(),
        level: 'info',
        message: event.data,
        source: 'websocket',
      })
    }
  }

  ws.onerror = () => {
    error.value = 'WebSocket 连接失败'
  }

  ws.onclose = () => {
    socket.value = null
  }
}

function disconnectWebSocket() {
  if (socket.value) {
    socket.value.close()
    socket.value = null
  }
}

onMounted(async () => {
  await fetchTask()
  connectWebSocket()
  if (!isTerminalStatus(task.value?.status)) startPolling()
  if (isDownloadTask.value && !isTerminalStatus(task.value?.status)) startProgressPolling()
})

onUnmounted(() => {
  stopPolling()
  stopProgressPolling()
  disconnectWebSocket()
})

watch(taskId, async () => {
  stopPolling()
  stopProgressPolling()
  disconnectWebSocket()
  await fetchTask()
  connectWebSocket()
  if (!isTerminalStatus(task.value?.status)) startPolling()
  if (isDownloadTask.value && !isTerminalStatus(task.value?.status)) startProgressPolling()
})
</script>

<template>
  <div class="page-container">
    <PageHeader title="任务详情" subtitle="查看任务状态、运行阶段、实时日志与结果产物" />
    <NBreadcrumb class="task-breadcrumb">
      <NBreadcrumbItem>任务中心</NBreadcrumbItem>
      <NBreadcrumbItem>任务详情</NBreadcrumbItem>
    </NBreadcrumb>

    <NAlert v-if="error" type="error" :title="error" role="alert" />

    <NCard v-if="task" title="任务概览" :bordered="false" class="arco-card overview-card">
      <NSpace vertical>
        <NDescriptions :columns="3" bordered>
          <NDescriptionsItem label="任务名称">{{ task.name }}</NDescriptionsItem>
          <NDescriptionsItem label="流程">{{ task.flow_id }}</NDescriptionsItem>
          <NDescriptionsItem label="状态">
            <NTag :type="statusType" round>{{ statusText }}</NTag>
          </NDescriptionsItem>
          <NDescriptionsItem label="执行模式">{{ task.execution_mode }}</NDescriptionsItem>
          <NDescriptionsItem label="工作目录">{{ workDirectory || '-' }}</NDescriptionsItem>
          <NDescriptionsItem v-if="dataPath" label="数据路径">
            <NSpace align="center" :size="6" wrap>
              <span class="data-path">{{ dataPath }}</span>
              <NButton text size="tiny" class="copy-btn" @click="copyDataPath">
                <template #icon>
                  <NIcon :size="14"><CopyOutline /></NIcon>
                </template>
                复制
              </NButton>
            </NSpace>
          </NDescriptionsItem>
          <NDescriptionsItem label="创建时间">{{ task.created_at }}</NDescriptionsItem>
        </NDescriptions>
        <NProgress
          :percentage="Math.round(task.progress * 100)"
          :status="task.status === 'failed' ? 'error' : 'success'"
          :indicator-text-color="task.status === 'failed' ? 'var(--arco-danger)' : 'var(--arco-success)'"
        />

        <!-- 逐 Run 进度（仅下载任务且 progress API 有数据时显示） -->
        <div v-if="isDownloadTask && runList.length > 0" class="run-progress-section">
          <h4 class="run-section-title">逐样本进度 ({{ runList.length }} runs)</h4>
          <div class="run-list">
            <div v-for="run in runList" :key="run.run_id" class="run-item">
              <div class="run-header">
                <span class="run-id">{{ run.run_id }}</span>
                <NTag :type="stageTagType(run.stage)" size="small" round>
                  {{ stageLabel(run.stage) }}
                </NTag>
              </div>
              <NProgress
                :percentage="Math.round(run.overall_percent)"
                :status="run.stage === 'failed' ? 'error' : run.stage === 'completed' ? 'success' : 'default'"
                :height="6"
                :show-indicator="true"
              />
              <div class="stage-details">
                <span>下载 {{ run.download.percent.toFixed(0) }}%</span>
                <span>解压 {{ run.extraction.percent.toFixed(0) }}%</span>
                <span>压缩 {{ run.compression.percent.toFixed(0) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </NSpace>
    </NCard>

    <NTabs type="line" animated>
      <NTabPane name="logs" tab="实时日志">
        <NCard :bordered="false" class="arco-card logs-card">
          <div class="log-container">
            <div
              v-for="(log, index) in logs"
              :key="index"
              class="log-line"
              :class="`level-${log.level}`"
            >
              <span class="log-time">{{ log.timestamp }}</span>
              <span class="log-level">{{ log.level.toUpperCase() }}</span>
              <span class="log-message">{{ redactUserHomePaths(log.message) }}</span>
            </div>
            <div v-if="logs.length === 0" class="empty-logs">暂无日志</div>
          </div>
        </NCard>
      </NTabPane>

      <NTabPane name="dag" tab="DAG 可视化">
        <NCard :bordered="false" class="arco-card dag-card">
          <NSpace vertical>
            <NButton type="primary" :loading="dagLoading" @click="fetchDag">
              生成 DAG
            </NButton>
            <NAlert v-if="dag?.status === 'failed'" type="error" :title="dag.error || '生成失败'" />
            <div v-else-if="dag?.format === 'svg'" class="dag-svg" v-html="sanitizeSvg(dag.content || '')" />
            <pre v-else-if="dag?.format === 'dot'" class="dag-dot">{{ dag.content }}</pre>
            <div v-else-if="dag?.kind === 'mas'" class="mas-dag-list">
              <div v-for="node in dag.nodes || []" :key="node.id" class="mas-dag-node">
                <strong>{{ node.id }}</strong>
                <span>{{ node.label }}</span>
                <NTag size="small" round>{{ node.agent_id }}</NTag>
                <NTag size="small" round :type="node.status === 'failed' ? 'error' : node.status === 'succeeded' ? 'success' : 'warning'">
                  {{ node.status }} · 第 {{ node.attempt_count }} 次
                </NTag>
              </div>
            </div>
            <div v-else-if="dag === null" class="empty-dag">点击上方按钮生成 DAG</div>
          </NSpace>
        </NCard>
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.task-breadcrumb {
  margin-bottom: 16px;
}

.overview-card {
  margin-bottom: 24px;
}

/* 数据路径：等宽字体便于辨识，长路径可折行不撑破布局 */
.data-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  color: var(--neutral-text-2, #4e5969);
  word-break: break-all;
}

.copy-btn {
  color: var(--arco-primary, #165DFF) !important;
  flex-shrink: 0;
}

.logs-card {
  margin-top: 16px;
}

.log-container {
  max-height: 600px;
  overflow-y: auto;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 8px;
}

.log-line {
  display: flex;
  gap: 12px;
  padding: 2px 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-time {
  color: #858585;
  min-width: 180px;
}

.log-level {
  min-width: 60px;
  font-weight: bold;
}

.level-error .log-level {
  color: #f14c4c;
}

.level-warning .log-level {
  color: #f5a623;
}

.level-info .log-level {
  color: #4ec9b0;
}

.level-debug .log-level {
  color: #9cdcfe;
}

.empty-logs {
  color: #858585;
  text-align: center;
  padding: 24px;
}

.dag-card {
  min-height: 400px;
  margin-top: 16px;
}

.dag-svg {
  overflow-x: auto;
}

.dag-svg svg {
  max-width: 100%;
  height: auto;
}

.dag-dot {
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  white-space: pre;
}

.empty-dag {
  color: var(--neutral-text-3);
  text-align: center;
  padding: 48px;
}

/* 逐 Run 进度区 */
.run-progress-section {
  margin-top: 16px;
}

.run-section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0 0 12px;
}

.run-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.run-item {
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--neutral-bg-2, #f7f8fa);
}

.run-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.run-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-text-1);
}

.stage-details {
  display: flex;
  gap: 16px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--neutral-text-3);
}

.mas-dag-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mas-dag-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--neutral-bg-2, #f7f8fa);
}

.mas-dag-node strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.mas-dag-node span {
  flex: 1;
  color: var(--neutral-text-2);
}
</style>
