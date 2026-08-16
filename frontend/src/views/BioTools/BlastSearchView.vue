<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert, NButton, NCard, NDataTable, NIcon, NInput, NInputNumber, NProgress, NSelect,
  NSpace, NSpin, NStatistic, NTag, NTooltip, NUpload, useMessage, type UploadFileInfo,
} from 'naive-ui'
import {
  ChevronDownOutline, DownloadOutline, FileTrayFullOutline, ListOutline, SearchOutline,
} from '@vicons/ionicons5'
import {
  cancelBlastTask, downloadBlastResult, fetchBlastDatabases, fetchBlastResult, fetchBlastTasks,
  fetchBlastTaskStatus, streamBlastTaskEvents, submitBlastTask,
} from '@/api/blast'
import BlastRightPanel from '@/components/blast/BlastRightPanel.vue'
import BlastGraphicSummary from '@/components/blast/BlastGraphicSummary.vue'
import BlastHitDetailCard from '@/components/blast/BlastHitDetailCard.vue'
import BlastParamsInfo from '@/components/blast/BlastParamsInfo.vue'
import PageHeader from '@/components/PageHeader.vue'
import ToolActionBar from '@/components/ToolActionBar.vue'
import { consumeSequenceHandoff } from '@/engine/ecosystemLinks'
import { analyzeSequence, detectSequenceType } from '@/utils/sequenceAnalysis'
import type { BlastDatabase, BlastHit, BlastResult, BlastTask, BlastTaskListItem, ProgramType } from '@/types/blast'

const router = useRouter()
const route = useRoute()
const message = useMessage()

const POLLING_INTERVAL = 2000

// ---------------------------------------------------------------------------
// Refs / State
// ---------------------------------------------------------------------------

const databases = ref<BlastDatabase[]>([])
const loadingDatabases = ref(false)

const selectedDbId = ref<string | null>(null)
const fastaInput = ref('')
const projectName = ref('')
const queryTitle = ref('Untitled Query')
const program = ref<ProgramType | undefined>(undefined)
const evalue = ref(1e-5)
const maxTargetSeqs = ref(10)
const wordSize = ref<number | undefined>(undefined)
const gapOpen = ref<number | undefined>(undefined)
const gapExtend = ref<number | undefined>(undefined)
const advancedParamsExpanded = ref(false)

const isSearching = ref(false)
const currentTask = ref<BlastTask | null>(null)
const currentResult = ref<BlastResult | null>(null)
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)
const eventAbortController = ref<AbortController | null>(null)

const recentTasks = ref<BlastTaskListItem[]>([])
const loadingTasks = ref(false)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const dbOptions = computed(() =>
  databases.value.map((db) => ({
    label: `${db.name} (${db.db_type === 'nucl' ? '核酸' : '蛋白'})`,
    value: db.id,
  })),
)

const programOptions = [
  { label: 'blastn (核酸 vs 核酸)', value: 'blastn' },
  { label: 'blastp (蛋白 vs 蛋白)', value: 'blastp' },
  { label: 'blastx (核酸 vs 蛋白)', value: 'blastx' },
  { label: 'tblastn (蛋白 vs 核酸)', value: 'tblastn' },
  { label: 'tblastx (核酸 vs 核酸，双向翻译)', value: 'tblastx' },
]

const selectedDb = computed(() =>
  databases.value.find((db) => db.id === selectedDbId.value),
)

const sequenceStats = computed(() => analyzeSequence(fastaInput.value, selectedDb.value?.db_type))

const taskStatusText = computed(() => {
  if (!currentTask.value) return ''
  const map: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[currentTask.value.status] || currentTask.value.status
})

const taskStatusType = computed(() => {
  if (!currentTask.value) return 'default'
  const map: Record<string, 'default' | 'success' | 'warning' | 'error'> = {
    queued: 'default',
    running: 'warning',
    completed: 'success',
    failed: 'error',
    cancelled: 'default',
  }
  return map[currentTask.value.status] || 'default'
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseFasta(text: string): { title: string; sequence: string } {
  const lines = text.trim().split('\n').map((l) => l.trim())
  let title = ''
  const seqLines: string[] = []
  for (const line of lines) {
    if (!line) continue
    if (line.startsWith('>')) {
      title = line.slice(1).split(' ')[0]
      continue
    }
    seqLines.push(line)
  }
  return { title, sequence: seqLines.join('') }
}

function autoRecommendProgram() {
  if (sequenceStats.value.recommendedProgram) {
    program.value = sequenceStats.value.recommendedProgram
  }
}

function handleSequenceChange() {
  if (!program.value) {
    autoRecommendProgram()
  }
}

function handleFileUpload({ file }: { file: UploadFileInfo }) {
  if (file.file) {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result || '')
      fastaInput.value = text.slice(0, 50000)
      handleSequenceChange()
    }
    reader.readAsText(file.file)
  }
  return false
}

function ensureFasta(text: string, title: string): string {
  const trimmed = text.trim()
  if (trimmed.startsWith('>')) return trimmed
  return `>${title || 'query'}\n${trimmed}`
}

function validateInput(): string | null {
  if (!selectedDbId.value) return '请选择目标数据库'
  if (!projectName.value.trim()) return '请填写项目名称'
  const trimmed = fastaInput.value.trim()
  if (!trimmed) return '请输入查询序列'
  const { sequence } = parseFasta(trimmed)
  if (!sequence) return '查询序列不能为空'
  if (sequence.length < 5) return '查询序列过短'
  const queryType = detectSequenceType(sequence)
  if (queryType === 'unknown') return '无法识别查询序列类型，请检查输入'
  return null
}

const searchBlocker = computed(() => validateInput())

async function handleSearch() {
  const error = validateInput()
  if (error) {
    message.error(error)
    return
  }

  isSearching.value = true
  currentResult.value = null
  stopTaskTracking()

  try {
    const db = selectedDb.value!
    const { title } = parseFasta(fastaInput.value)
    const requestTitle = queryTitle.value.trim() || title || 'Untitled Query'
    const request = {
      db_id: db.id,
      project_name: projectName.value.trim(),
      query_sequence: ensureFasta(fastaInput.value, requestTitle),
      query_title: requestTitle,
      program: program.value,
      evalue: evalue.value,
      max_target_seqs: maxTargetSeqs.value,
      word_size: wordSize.value,
      gapopen: gapOpen.value,
      gapextend: gapExtend.value,
      result_format: 'json' as const,
    }
    const task = await submitBlastTask(request)
    currentTask.value = task
    message.success(task.status === 'completed' ? '命中缓存，已直接返回结果' : `任务已提交：${task.task_id}`)
    if (task.status === 'completed') {
      await loadResult(task.task_id)
      await loadRecentTasks()
    } else {
      startTaskTracking(task.task_id)
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '任务提交失败')
  } finally {
    isSearching.value = false
  }
}

async function pollTaskStatus(taskId: string) {
  try {
    const task = await fetchBlastTaskStatus(taskId)
    currentTask.value = task
    if (task.status === 'completed') {
      stopPolling()
      await loadResult(taskId)
      await loadRecentTasks()
      message.success('比对完成')
    } else if (task.status === 'failed' || task.status === 'cancelled') {
      stopPolling()
      message.error(task.error_message || `任务${task.status === 'failed' ? '失败' : '已取消'}`)
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '查询任务状态失败')
    stopPolling()
  }
}

async function loadResult(taskId: string) {
  try {
    const result = await fetchBlastResult(taskId, 'json')
    currentResult.value = result
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载结果失败')
  }
}

async function handleTaskEvent(taskId: string, event: { status: BlastTask['status']; progress: number; message: string; error_message?: string }) {
  currentTask.value = {
    ...(currentTask.value || { task_id: taskId }),
    task_id: taskId,
    status: event.status,
    progress: event.progress,
    message: event.message,
    error_message: event.error_message,
  }
  if (event.status === 'completed') {
    stopTaskTracking()
    await loadResult(taskId)
    await loadRecentTasks()
    message.success('比对完成')
  } else if (event.status === 'failed' || event.status === 'cancelled') {
    stopTaskTracking()
    message.error(event.error_message || `任务${event.status === 'failed' ? '失败' : '已取消'}`)
  }
}

function startTaskTracking(taskId: string) {
  stopTaskTracking()
  const controller = new AbortController()
  eventAbortController.value = controller
  void streamBlastTaskEvents(taskId, (event) => handleTaskEvent(taskId, event), controller.signal)
    .catch(() => {
      if (!controller.signal.aborted) startPolling(taskId)
    })
}

function stopTaskTracking() {
  eventAbortController.value?.abort()
  eventAbortController.value = null
  stopPolling()
}

function startPolling(taskId: string) {
  stopPolling()
  pollingTimer.value = setInterval(() => pollTaskStatus(taskId), POLLING_INTERVAL)
}

function stopPolling() {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

async function handleCancel() {
  if (!currentTask.value) return
  try {
    await cancelBlastTask(currentTask.value.task_id)
    message.info('已取消任务')
    stopTaskTracking()
    currentTask.value = await fetchBlastTaskStatus(currentTask.value.task_id)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '取消任务失败')
  }
}

async function loadRecentTasks() {
  loadingTasks.value = true
  try {
    const response = await fetchBlastTasks(undefined, 1, 5)
    recentTasks.value = response.items
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载最近任务失败')
  } finally {
    loadingTasks.value = false
  }
}

async function openTask(taskId: string) {
  try {
    stopTaskTracking()
    currentTask.value = await fetchBlastTaskStatus(taskId)
    currentResult.value = null
    if (currentTask.value.status === 'completed') {
      await loadResult(taskId)
    } else if (currentTask.value.status === 'queued' || currentTask.value.status === 'running') {
      startTaskTracking(taskId)
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载历史任务失败')
  }
}

async function handleSelectTask(task: BlastTaskListItem) {
  await openTask(task.task_id)
}

async function rerunTask(taskId: string, fallback?: BlastTaskListItem) {
  try {
    const detail = await fetchBlastTaskStatus(taskId)
    selectedDbId.value = detail.db_id || fallback?.db_id || null
    fastaInput.value = detail.query_sequence || ''
    queryTitle.value = detail.query_title || fallback?.query_title || 'Untitled Query'
    program.value = detail.program
    evalue.value = detail.evalue ?? 1e-5
    maxTargetSeqs.value = detail.max_target_seqs ?? 10
    wordSize.value = detail.word_size
    gapOpen.value = detail.gapopen
    gapExtend.value = detail.gapextend
    currentTask.value = null
    currentResult.value = null
    message.success('已填充历史任务参数，可直接重新检索')
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '读取历史任务参数失败')
  }
}

async function handleRerunTask(task: BlastTaskListItem) {
  await rerunTask(task.task_id, task)
}

async function handleDownload(format: 'xml' | 'json' | 'text') {
  if (!currentResult.value) return
  try {
    await downloadBlastResult(currentResult.value.task_id, format, `${currentResult.value.task_id}.${format}`)
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '下载失败')
  }
}

// ---------------------------------------------------------------------------
// Result table
// ---------------------------------------------------------------------------

function getIdentityTagType(identity: number): 'success' | 'info' | 'warning' | 'error' {
  if (identity >= 90) return 'success'
  if (identity >= 70) return 'info'
  if (identity >= 40) return 'warning'
  return 'error'
}

function renderEvalue(evalue: number) {
  if (evalue < 1e-100) {
    return h(NTag, { type: 'error', size: 'small' }, { default: () => evalue.toExponential(1) })
  }
  return h('span', { class: 'blast-table-number' }, evalue.toExponential(2))
}

function renderCoverage(coverage: number) {
  const value = Math.max(0, Math.min(100, coverage || 0))
  return h('div', { class: 'blast-coverage' }, [
    h(NProgress, {
      percentage: value,
      showIndicator: false,
      railColor: '#eef0f2',
      color: value >= 90 ? '#22c55e' : value >= 70 ? '#3b82f6' : value >= 40 ? '#f59e0b' : '#ef4444',
    }),
    h('span', { class: 'blast-coverage__value' }, `${value.toFixed(1)}%`),
  ])
}

function scrollToHit(hitNum: number) {
  document.getElementById(`blast-hit-${hitNum}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const columns = [
  {
    title: '#',
    key: 'hit_num',
    width: 50,
    align: 'center' as const,
    render: (row: BlastHit) => h('strong', null, row.hit_num),
  },
  {
    title: 'Subject ID',
    key: 'hit_id',
    width: 110,
    align: 'center' as const,
    render: (row: BlastHit) => h(
      NTooltip,
      { trigger: 'hover' },
      {
        trigger: () => h('span', {
          style: {
            fontFamily: 'monospace',
            fontWeight: 600,
            fontSize: '13px',
          },
        }, row.hit_id),
        default: () => row.hit_def || '无描述',
      },
    ),
  },
  {
    title: 'Subject Description',
    key: 'hit_def',
    width: 240,
    align: 'left' as const,
    ellipsis: { tooltip: true },
    render: (row: BlastHit) => h('span', { style: { fontSize: '12px', color: 'var(--neutral-text-3)' } }, row.hit_def || '-'),
  },
  {
    title: 'Length',
    key: 'hit_len',
    width: 140,
    align: 'center' as const,
    render: (row: BlastHit) => h('span', { class: 'blast-table-number blast-table-nowrap' }, `${row.hit_len.toLocaleString()} bp`),
  },
  {
    title: 'Identity %',
    key: 'identity_percent',
    width: 100,
    align: 'center' as const,
    sorter: (a: BlastHit, b: BlastHit) => a.identity_percent - b.identity_percent,
    render: (row: BlastHit) => h(
      NTag,
      { type: getIdentityTagType(row.identity_percent), size: 'small', round: true, class: 'identity-pill' },
      { default: () => `${row.identity_percent.toFixed(1)}%` },
    ),
  },
  {
    title: 'E-value',
    key: 'evalue',
    width: 120,
    align: 'center' as const,
    sorter: (a: BlastHit, b: BlastHit) => a.evalue - b.evalue,
    render: (row: BlastHit) => renderEvalue(row.evalue),
  },
  {
    title: 'Bit Score',
    key: 'bit_score',
    width: 100,
    align: 'center' as const,
    sorter: (a: BlastHit, b: BlastHit) => a.bit_score - b.bit_score,
    render: (row: BlastHit) => h('span', { class: 'blast-table-number' }, row.bit_score.toFixed(1)),
  },
  {
    title: 'Align Len',
    key: 'align_length',
    width: 100,
    align: 'center' as const,
    render: (row: BlastHit) => h('span', { class: 'blast-table-number blast-table-nowrap' }, `${row.align_length} bp`),
  },
  {
    title: 'Query Range',
    key: 'q_range',
    width: 110,
    align: 'center' as const,
    render: (row: BlastHit) => h('span', { class: 'blast-table-number blast-table-nowrap' }, `${row.q_start}-${row.q_end}`),
  },
  {
    title: 'Subject Range',
    key: 's_range',
    width: 110,
    align: 'center' as const,
    render: (row: BlastHit) => h('span', { class: 'blast-table-number blast-table-nowrap' }, `${row.s_start}-${row.s_end}`),
  },
  {
    title: 'Coverage',
    key: 'query_coverage',
    width: 160,
    sorter: (a: BlastHit, b: BlastHit) => a.query_coverage - b.query_coverage,
    render: (row: BlastHit) => renderCoverage(row.query_coverage),
  },
]



// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(async () => {
  loadingDatabases.value = true
  try {
    databases.value = await fetchBlastDatabases()
    const handoff = consumeSequenceHandoff('blast')
    if (handoff) {
      fastaInput.value = `>${handoff.record.header}\n${handoff.record.sequence}`
      queryTitle.value = handoff.record.id
      projectName.value = `${handoff.record.id}_BLAST`
      message.success('已从序列魔术师载入查询序列')
    }
    await loadRecentTasks()
    if (typeof route.query.task === 'string') {
      await openTask(route.query.task)
    } else if (typeof route.query.rerun === 'string') {
      await rerunTask(route.query.rerun)
    }
  } catch (err: any) {
    message.error(err?.response?.data?.detail || '加载数据库列表失败')
  } finally {
    loadingDatabases.value = false
  }
})

onUnmounted(() => {
  stopTaskTracking()
})
</script>

<template>
  <div class="blast-page">
    <PageHeader title="序列检索 BLAST" subtitle="在本地和已配置数据库中执行序列相似性检索" back-to="/tools" back-label="返回工具箱">
      <template #actions>
        <NButton size="small" text @click="router.push('/tools/blast/tasks')">
          <template #icon><NIcon><ListOutline /></NIcon></template>
          任务中心
        </NButton>
      </template>
    </PageHeader>

    <NAlert type="warning" :show-icon="true" class="data-retention-alert">
      BLAST 任务结果将在 7 天后自动清理，请及时下载或保存重要结果。
    </NAlert>

    <div class="blast-layout">
      <div class="input-section">
        <div class="input-card">
          <h3 class="section-title">查询设置</h3>
          <label class="field-label">目标数据库</label>
          <NSelect v-model:value="selectedDbId" :options="dbOptions" :loading="loadingDatabases" placeholder="选择 BLAST 数据库" @update:value="autoRecommendProgram" />
          <label class="field-label">查询序列 (FASTA)</label>
          <NInput
            v-model:value="fastaInput"
            type="textarea"
            :rows="8"
            placeholder=">OsNAC14&#10;ATGGCTGACGCCGACGACGACGACGGCGGCGGCGGCGGCGGC..."
            class="fasta-textarea"
            @input="handleSequenceChange"
          />
          <div class="upload-row">
            <NUpload accept=".fasta,.fa,.fna,.txt" :max="1" :default-upload="false" @change="handleFileUpload">
              <NButton size="small">
                <template #icon><NIcon><FileTrayFullOutline /></NIcon></template>
                上传 FASTA 文件
              </NButton>
            </NUpload>
          </div>
        </div>

        <div class="input-card parameter-card">
          <h3 class="section-title">比对参数</h3>
          <label class="field-label">比对算法</label>
          <NSelect v-model:value="program" :options="programOptions" clearable placeholder="自动推断" />
          <div class="params-row">
            <div>
              <label class="field-label">E-value 阈值</label>
            <NInputNumber v-model:value="evalue" :min="1e-100" :max="10" :show-button="false" placeholder="1e-5" />
            </div>
            <div>
              <label class="field-label">最大匹配数</label>
            <NInputNumber v-model:value="maxTargetSeqs" :min="1" :max="100" :show-button="false" />
            </div>
          </div>
          <label class="field-label">查询名称</label>
          <NInput v-model:value="queryTitle" placeholder="自定义查询名称" />
          <label class="field-label">项目名称</label>
          <NInput v-model:value="projectName" placeholder="例如：水稻抗病基因检索" />
          <button type="button" class="advanced-toggle" :aria-expanded="advancedParamsExpanded" @click="advancedParamsExpanded = !advancedParamsExpanded">
            高级参数 <NIcon :class="{ 'is-expanded': advancedParamsExpanded }"><ChevronDownOutline /></NIcon>
          </button>
          <div v-if="advancedParamsExpanded" class="params-row advanced-params">
            <div>
              <label class="field-label">Word Size</label>
              <NInputNumber v-model:value="wordSize" :show-button="false" placeholder="默认" />
            </div>
            <div>
              <label class="field-label">Gap Open</label>
              <NInputNumber v-model:value="gapOpen" :show-button="false" placeholder="默认" />
            </div>
            <div>
              <label class="field-label">Gap Extend</label>
              <NInputNumber v-model:value="gapExtend" :show-button="false" placeholder="默认" />
            </div>
          </div>
        </div>
      </div>

      <div class="results-section">
        <BlastRightPanel
          :sequence-stats="sequenceStats"
          :recent-tasks="recentTasks"
          :loading-tasks="loadingTasks"
          @select-task="handleSelectTask"
          @rerun-task="handleRerunTask"
        />
        <div v-if="currentTask" class="results-header">
          <h3 class="section-title">任务状态</h3>
          <NSpace align="center">
            <NTag :type="taskStatusType" size="small" round>{{ taskStatusText }}</NTag>
            <span v-if="currentTask.status === 'running'" class="status-detail">
              进度 {{ currentTask.progress }}%
            </span>
            <NButton v-if="currentTask.status === 'running'" size="tiny" @click="handleCancel">
              取消
            </NButton>
          </NSpace>
        </div>

        <NProgress
          v-if="currentTask && currentTask.status === 'running'"
          :percentage="currentTask.progress"
          :show-indicator="false"
          status="warning"
          class="progress-bar"
        />

        <div v-if="currentTask?.error_message" class="error-message">
          {{ currentTask.error_message }}
        </div>

        <NSpin v-if="currentTask?.status === 'running'" description="正在执行 BLAST 比对..." />

        <template v-if="currentResult">
          <NCard size="small" class="stats-card">
            <div class="summary-header"><div><NTag :type="taskStatusType" size="small" round>{{ taskStatusText }}</NTag><strong>{{ currentResult.statistics.query_title || currentResult.query_def || 'BLAST 结果' }}</strong></div><NSpace class="summary-downloads">
              <NButton size="small" @click="handleDownload('xml')">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                XML
              </NButton>
              <NButton size="small" @click="handleDownload('json')">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                JSON
              </NButton>
              <NButton size="small" @click="handleDownload('text')">
                <template #icon><NIcon><DownloadOutline /></NIcon></template>
                Text
              </NButton>
            </NSpace></div>
            <div class="stats-row">
              <NStatistic label="数据库" :value="currentResult.db_display_name || currentResult.statistics.db_name" />
              <NStatistic label="算法" :value="(currentResult.program || currentResult.statistics.program || '').toUpperCase()" />
              <NStatistic label="Query 长度" :value="`${currentResult.query_len.toLocaleString()} bp`" />
              <NStatistic label="命中数" :value="currentResult.statistics.hit_count" />
              <NStatistic label="最佳 E-value" :value="currentResult.hits[0]?.best_hsp?.evalue?.toExponential(2) || '-'" />
              <NStatistic label="最佳 Identity" :value="`${currentResult.hits[0]?.identity_percent?.toFixed(1) || 0}%`" />
            </div>
          </NCard>

          <BlastGraphicSummary
            v-if="currentResult.statistics.hit_count > 0"
            :query-len="currentResult.query_len"
            :hits="currentResult.hits"
            @select-hit="scrollToHit"
          />

          <BlastParamsInfo v-if="currentResult.query_params" :params="currentResult.query_params" />

          <NCard size="small" title="比对结果" class="results-table-card">
            <NDataTable
              :columns="columns"
              :data="currentResult.hits"
              :row-key="(row) => row.hit_id || `${row.query_id}-${row.subject_id}-${row.hit_num}`"
              :bordered="false"
              size="small"
              :single-line="false"
              :pagination="currentResult.hits.length > 10 ? { pageSize: 10, showSizePicker: false } : false"
              :scroll-x="1340"
              :max-height="560"
              virtual-scroll
              class="results-table"
            />
          </NCard>

          <div v-if="currentResult.hits.length > 0" class="hit-cards-section">
            <h3 class="hit-cards-title">序列比对详情 ({{ currentResult.statistics.hit_count }} hits)</h3>
            <BlastHitDetailCard
              v-for="hit in currentResult.hits"
              :key="hit.hit_num"
              :hit="hit"
              :query-len="currentResult.query_len"
            />
          </div>
        </template>

        <div v-if="!currentTask && !currentResult" class="empty-hint">
          输入查询序列并选择数据库后点击「开始检索」
        </div>
      </div>
    </div>

    <ToolActionBar
      :ready="!searchBlocker"
      ready-text="序列与数据库已就绪"
      :not-ready-text="searchBlocker || '待完善检索参数'"
      :not-ready-tip="searchBlocker || ''"
      primary-label="开始检索"
      :primary-icon="SearchOutline"
      :loading="isSearching"
      @action="handleSearch"
    />
  </div>
</template>

<style scoped>
.blast-page {
  box-sizing: border-box;
  min-width: 0;
  min-height: 100%;
  padding: 16px;
}
.page-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0;
}
.blast-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 16px;
  align-items: start;
  min-width: 0;
}
.input-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.input-card {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 16px;
  box-shadow: var(--shadow-card);
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin: 0 0 10px;
}
.fasta-textarea :deep(textarea) {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
}
.upload-row {
  margin-top: 8px;
}
.field-label {
  display: block;
  margin: 14px 0 6px;
  color: var(--neutral-text-2);
  font-size: 12px;
  font-weight: 500;
}
.section-title + .field-label { margin-top: 0; }
.params-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.advanced-params { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 14px;
  padding: 0;
  color: var(--arco-primary);
  font: inherit;
  font-size: 12px;
  background: transparent;
  border: 0;
  cursor: pointer;
}
.advanced-toggle :deep(.n-icon) { transition: transform 200ms ease; }
.advanced-toggle :deep(.n-icon.is-expanded) { transform: rotate(180deg); }
.advanced-toggle:focus-visible { outline: 2px solid var(--arco-primary); outline-offset: 3px; border-radius: 4px; }
.data-retention-alert {
  margin-bottom: 12px;
}
.results-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.results-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.results-header .section-title {
  margin: 0;
}
.status-detail {
  font-size: 12px;
  color: var(--neutral-text-2);
}
.progress-bar {
  margin-top: -8px;
}
.error-message {
  color: #f53f3f;
  font-size: 13px;
  background: rgba(245, 63, 63, 0.08);
  padding: 10px 12px;
  border-radius: 8px;
}
.results-table {
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  overflow: hidden;
}
.results-table :deep(th) {
  font-size: 12px;
  font-weight: 500;
  background: var(--neutral-bg);
  height: 52px;
  text-align: center;
  white-space: nowrap;
}
.results-table :deep(th:nth-child(3)) { text-align: left; }
.results-table :deep(td) {
  height: 52px;
  font-variant-numeric: tabular-nums;
}
.results-table :deep(tr:hover > td) { background: var(--neutral-hover); }
.results-table :deep(.n-data-table-td:last-child) { text-align: center; }
.results-table :deep(.identity-pill) { padding-inline: 8px; font-variant-numeric: tabular-nums; }
.results-table :deep(.blast-table-number) {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.results-table :deep(.blast-table-nowrap) { white-space: nowrap; }
.results-table :deep(.blast-coverage) {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  white-space: nowrap;
}
.results-table :deep(.blast-coverage .n-progress) { flex: 1 1 auto; min-width: 64px; }
.results-table :deep(.blast-coverage__value) { flex: 0 0 48px; text-align: right; font-variant-numeric: tabular-nums; }
.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.summary-header > div { display: flex; align-items: center; gap: 10px; min-width: 0; }
.summary-header strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.summary-downloads { flex: 0 0 auto; }
.stats-card :deep(.n-card__content) { padding: 16px; }
.stats-card :deep(.n-statistic) { min-width: 0; }
.stats-card :deep(.n-statistic-value) { font-variant-numeric: tabular-nums; }
.stats-card {
  margin-bottom: 16px;
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 12px;
}
.results-table-card {
  min-width: 0;
  margin-bottom: 16px;
}
.results-table-card :deep(.n-card__content) {
  min-width: 0;
  overflow: hidden;
}
.hit-cards-section {
  min-width: 0;
  margin-bottom: 16px;
}
.hit-cards-title {
  font-size: 14px;
  margin: 0 0 12px;
  color: var(--neutral-text-2);
}
.alignment-card {
  min-width: 0;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  padding: 16px;
}
.alignment-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.alignment-header .section-title {
  margin: 0;
}
.alignment-view {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--neutral-text-1);
  background: var(--neutral-bg);
  padding: 14px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0;
  white-space: pre;
}
.empty-hint {
  color: var(--neutral-text-3);
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}
@media (max-width: 900px) {
  .blast-layout {
    grid-template-columns: 1fr;
  }
  .advanced-params { grid-template-columns: 1fr; }
  .summary-header { align-items: flex-start; flex-direction: column; }
}
</style>
