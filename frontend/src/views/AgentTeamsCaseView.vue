<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NSelect,
  NSpin,
  NSteps,
  NStep,
  NTag,
  NText,
  NTimeline,
  NTimelineItem,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  ArrowBackOutline,
  RefreshOutline,
  ShieldCheckmarkOutline,
  SyncOutline,
} from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import {
  agentTeamsApi,
  type AgentTeamsCase,
  type AgentTeamsCaseStatus,
  type AgentTeamsEvent,
} from '@/api/agentTeams'
import { mergeAgentTeamsEvents, shouldPollAgentTeamsCase } from '@/utils/agentTeamsState'
import { formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'

const POLLING_INTERVAL_MS = 20_000
const SSE_RETRY_INITIAL_MS = 1_000
const SSE_RETRY_MAX_MS = 30_000
const message = useMessage()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const syncing = ref(false)
const available = ref(false)
const detail = ref<AgentTeamsCase | null>(null)
const events = ref<AgentTeamsEvent[]>([])
const eventCursor = ref<string | null>(null)
const error = ref('')
const pollingActive = ref(false)
const eventStreamHealthy = ref(false)
const lastSyncedAt = ref<Date | null>(null)
const submitVisible = ref(false)
const submitting = ref(false)
const retrying = ref(false)
const manifestVisible = ref(false)
const manifestLoading = ref(false)
const manifest = ref<Record<string, unknown> | null>(null)
const approvalConfirmed = ref(false)
const submitForm = ref({
  task_name: '',
})
const qualityGateVisible = ref(false)
const qualityGateSubmitting = ref(false)
const qualityGateForm = ref({
  task_id: '',
  decision: 'manual_review' as 'passed' | 'blocked' | 'manual_review',
  rule_version: 'demo-rna-qc-1.0',
  summary: '',
  evidence_refs: '',
})
let pollingTimer: ReturnType<typeof setInterval> | null = null
let eventStreamAbort: AbortController | null = null
let eventStreamRetryTimer: number | null = null
let eventStreamFailures = 0

const caseId = computed(() => String(route.params.caseId || ''))
const phases: { key: AgentTeamsCaseStatus[]; label: string }[] = [
  { key: ['received', 'preflight_running', 'preflight_blocked', 'waiting_for_correction'], label: '预检' },
  { key: ['approval_pending', 'approved'], label: '审批' },
  { key: ['executing', 'execution_failed'], label: '执行' },
  { key: ['quality_running', 'quality_blocked', 'remediation_pending'], label: '质量' },
  { key: ['delivery_ready', 'closed'], label: '交付' },
]
const activePhase = computed(() => {
  const status = detail.value?.status
  return Math.max(1, phases.findIndex((item) => status && item.key.includes(status)) + 1)
})
const stepsStatus = computed<'error' | 'process'>(() => (
  detail.value?.status.includes('blocked') || detail.value?.status === 'execution_failed' ? 'error' : 'process'
))
const nextStep = computed(() => {
  const status = detail.value?.status
  const workItem = detail.value?.work_items.find((item) => item.status === 'pending' || item.status === 'in_progress')
  if (workItem) {
    return {
      title: `等待 ${workItem.target} 处理`,
      description: `${workItem.objective}（${workItem.skill_name}）`,
    }
  }
  if (status === 'approval_pending') {
    return {
      title: '预检已通过，等待人工审批',
      description: '审批机关确认后，Workflow Operator 才能携带短期令牌提交 OmicHub 计算任务。',
    }
  }
  if (status === 'preflight_blocked' || status === 'waiting_for_correction') {
    return {
      title: '请修正预检问题后重试',
      description: '查看时间线中的预检证据，修正样本表或分组对比后创建新的协作 Case。',
    }
  }
  if (status === 'executing') {
    return {
      title: 'Workflow Operator 正在跟踪执行',
      description: 'OmicHub 是任务状态、日志和产物的唯一事实来源；完成后将进入质量门禁。',
    }
  }
  if (status === 'execution_failed') {
    return {
      title: '执行失败，可按冻结计划重试',
      description: '先查看时间线中的错误摘要；确认后重试会创建新的提交版本，不会覆盖原任务证据。',
    }
  }
  if (status === 'quality_running' || status === 'quality_blocked' || status === 'remediation_pending') {
    return {
      title: '等待 Quality Auditor 结论',
      description: '质量通过后 Delivery Reporter 会整理任务、审批与产物证据。',
    }
  }
  if (status === 'delivery_ready') {
    return {
      title: '等待交付确认',
      description: 'Delivery Reporter 应核对 Manifest 和关键证据后关闭 Case。',
    }
  }
  return {
    title: 'Manager 正在编排协作',
    description: '请查看工作项与时间线，等待下一项受控动作写入 Case。',
  }
})
const canSubmit = computed(() => detail.value?.status === 'approval_pending')
const canSubmitQualityGate = computed(() => {
  const status = detail.value?.status
  return (
    ['quality_running', 'quality_blocked', 'remediation_pending'].includes(status || '') &&
    (detail.value?.omic_task_ids.length || 0) > 0
  )
})
const planShortHash = computed(() => detail.value?.plan_hash ? detail.value.plan_hash.slice(0, 12) : '')
const eventLabel = (type: string) => ({
  'case.created': 'Case 已创建',
  'case.state_changed': '阶段已更新',
  'work_item.assigned': 'Manager 已分派工作项',
  'skill.finished': 'Skill 已完成',
  'skill.failed': 'Skill 未完成',
  'approval.requested': '已请求人工审批',
  'approval.resolved': '审批已决议',
  'omic_task.submitted': 'OmicHub 任务已提交',
  'omic_task.status_changed': '任务状态已回传',
  'omic_task.completed': '任务已完成，已转入质量核验',
  'omic_task.failed': '任务执行失败，等待修复处理',
  'omic_task.cancelled': '任务已取消',
  'quality.decision': '质量门禁结论',
  'case.closed': 'Case 已关闭',
}[type] || type)

function mergeEvents(incoming: AgentTeamsEvent[]) {
  events.value = mergeAgentTeamsEvents(events.value, incoming)
}

function openSubmit() {
  if (!detail.value) return
  submitForm.value = {
    task_name: detail.value.intent.slice(0, 128),
  }
  approvalConfirmed.value = false
  submitVisible.value = true
}

async function openManifest() {
  if (!detail.value?.case_id) return
  manifestLoading.value = true
  try {
    manifest.value = await agentTeamsApi.getManifest(detail.value.case_id)
    manifestVisible.value = true
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || 'Manifest 暂不可用。')
  } finally {
    manifestLoading.value = false
  }
}

async function downloadManifest() {
  if (!detail.value?.case_id) return
  manifestLoading.value = true
  try {
    const payload = manifest.value || await agentTeamsApi.getManifest(detail.value.case_id)
    manifest.value = payload
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${detail.value.case_id}-manifest.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || 'Manifest 下载失败。')
  } finally {
    manifestLoading.value = false
  }
}

async function confirmSubmit() {
  if (!detail.value) return
  const taskName = submitForm.value.task_name.trim()
  if (!taskName) {
    message.warning('请填写任务名称。')
    return
  }
  if (!approvalConfirmed.value) {
    message.warning('请先确认本次真实计算的审批范围。')
    return
  }
  submitting.value = true
  try {
    const receipt = await agentTeamsApi.submitCase(detail.value.case_id, {
      task_name: taskName,
    })
    submitVisible.value = false
    message.success(`已通过 Workflow Operator 提交 OmicHub 任务 ${receipt.omic_task_id}。`)
    await refresh({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '任务提交失败，未确认前请勿重复操作。')
  } finally {
    submitting.value = false
  }
}

async function retryFailedCase() {
  if (!detail.value || retrying.value) return
  retrying.value = true
  try {
    const queued = await agentTeamsApi.retryCase(detail.value.case_id)
    message.success(`重试已排队：${queued.work_item_id}`)
    await refresh({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '重试排队失败，请核对错误摘要后再试。')
  } finally {
    retrying.value = false
  }
}

function openQualityGate() {
  if (!detail.value) return
  qualityGateForm.value = {
    task_id: detail.value.omic_task_ids.at(-1) || '',
    decision: 'manual_review',
    rule_version: 'demo-rna-qc-1.0',
    summary: '',
    evidence_refs: '',
  }
  qualityGateVisible.value = true
}

async function confirmQualityGate() {
  if (!detail.value) return
  const { decision, rule_version, summary, evidence_refs } = qualityGateForm.value
  if (!rule_version.trim()) {
    message.warning('请填写规则版本。')
    return
  }
  if (!summary.trim()) {
    message.warning('请填写质量结论摘要。')
    return
  }
  qualityGateSubmitting.value = true
  try {
    const refs = evidence_refs
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    await agentTeamsApi.submitQualityGate(detail.value.case_id, {
      task_id: qualityGateForm.value.task_id || undefined,
      decision,
      rule_version: rule_version.trim(),
      summary: summary.trim(),
      evidence_refs: refs,
    })
    qualityGateVisible.value = false
    message.success('质量结论已提交。')
    await refresh({ resetEvents: true })
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '质量结论提交失败。')
  } finally {
    qualityGateSubmitting.value = false
  }
}

async function refresh(options: { background?: boolean; resetEvents?: boolean } = {}) {
  if (!caseId.value) return
  if (options.background) syncing.value = true
  else loading.value = true
  if (!options.background) error.value = ''
  try {
    const state = await agentTeamsApi.status()
    available.value = state.available
    if (!state.available) {
      detail.value = null
      events.value = []
      eventCursor.value = null
      return
    }
    const cursor = options.resetEvents ? undefined : eventCursor.value ?? undefined
    let caseData = await agentTeamsApi.getCase(caseId.value)
    if (caseData.status === 'executing') {
      caseData = await agentTeamsApi.refreshCase(caseId.value)
    }
    const eventData = await agentTeamsApi.getEvents(caseId.value, { cursor, limit: 100 })
    detail.value = caseData
    if (options.resetEvents) events.value = eventData.events
    else mergeEvents(eventData.events)
    eventCursor.value = eventData.next_cursor ?? (events.value.at(-1)?.event_id ?? null)
    lastSyncedAt.value = new Date()
  } catch (cause: any) {
    if (!options.background) {
      error.value = cause?.response?.data?.detail || '无法获取协作 Case 详情。'
    }
  } finally {
    loading.value = false
    syncing.value = false
  }
}

function syncIfVisible() {
  pollingActive.value = shouldPollAgentTeamsCase(document.visibilityState)
  if (pollingActive.value && !eventStreamHealthy.value) void refresh({ background: true })
}

function startPolling() {
  stopPolling()
  pollingActive.value = shouldPollAgentTeamsCase(document.visibilityState)
  pollingTimer = setInterval(syncIfVisible, POLLING_INTERVAL_MS)
  document.addEventListener('visibilitychange', syncIfVisible)
}

function stopPolling() {
  if (pollingTimer) clearInterval(pollingTimer)
  pollingTimer = null
  document.removeEventListener('visibilitychange', syncIfVisible)
  pollingActive.value = false
}

function stopEventStream() {
  eventStreamAbort?.abort()
  eventStreamAbort = null
  if (eventStreamRetryTimer) clearTimeout(eventStreamRetryTimer)
  eventStreamRetryTimer = null
  eventStreamHealthy.value = false
  eventStreamFailures = 0
}

async function startEventStream() {
  if (!caseId.value) return
  stopEventStream()
  const controller = new AbortController()
  eventStreamAbort = controller
  try {
    const token = localStorage.getItem('access_token')
    const params = new URLSearchParams()
    if (eventCursor.value) params.set('cursor', eventCursor.value)
    const response = await fetch(`/api/v1/agent-teams/cases/${caseId.value}/events/stream?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`SSE 请求失败（${response.status}）`)
    eventStreamHealthy.value = true
    eventStreamFailures = 0
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const event = JSON.parse(line.slice(5).trim()) as AgentTeamsEvent
          mergeEvents([event])
          eventCursor.value = event.event_id || eventCursor.value
          lastSyncedAt.value = new Date()
          if (detail.value && event.event_type === 'case.state_changed') void refresh({ background: true })
        } catch {
          // Ignore malformed events and retain polling as a reliable fallback.
        }
      }
    }
  } catch (cause) {
    if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
      console.warn('协作 Case 事件流连接异常，将继续使用轮询同步。', cause)
    }
  } finally {
    if (eventStreamAbort === controller) {
      eventStreamAbort = null
      eventStreamHealthy.value = false
      if (!controller.signal.aborted) {
        const delay = Math.min(
          SSE_RETRY_MAX_MS,
          SSE_RETRY_INITIAL_MS * 2 ** Math.min(eventStreamFailures, 5),
        )
        eventStreamFailures += 1
        eventStreamRetryTimer = window.setTimeout(() => {
          eventStreamRetryTimer = null
          void startEventStream()
        }, delay)
      }
    }
  }
}

watch(caseId, () => {
  events.value = []
  eventCursor.value = null
  stopEventStream()
  void refresh({ resetEvents: true })
  void startEventStream()
})
onMounted(() => {
  void refresh({ resetEvents: true })
  startPolling()
  void startEventStream()
})
onBeforeUnmount(() => {
  stopPolling()
  stopEventStream()
})
</script>

<template>
  <main class="page-container case-page">
    <PageHeader :title="detail?.intent || '协作案例'" :subtitle="detail ? `Case ID · ${detail.case_id}` : '加载协作案例'">
      <template #leading>
        <NTooltip trigger="hover">
          <template #trigger>
            <NButton quaternary circle aria-label="返回任务中心" @click="router.push('/tasks?tab=agent-teams')">
              <NIcon><ArrowBackOutline /></NIcon>
            </NButton>
          </template>
          返回任务中心
        </NTooltip>
      </template>
      <template #actions>
        <NButton secondary :loading="loading" @click="refresh({ resetEvents: true })">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>刷新
        </NButton>
      </template>
    </PageHeader>

    <NAlert v-if="!loading && !available && !error" type="info" title="AgentTeams 尚未接通" :show-icon="true">
      未连接时不会显示演示 Case 或伪造执行记录。
    </NAlert>
    <template v-else-if="error">
      <NAlert type="error" title="无法加载协作案例" :show-icon="true">{{ error }}</NAlert>
      <NButton class="alert-retry" size="small" @click="refresh({ resetEvents: true })">重试</NButton>
    </template>
    <NSpin v-else :show="loading">
      <NEmpty v-if="!detail" description="未找到协作案例" />
      <div v-else class="case-workbench">
        <section class="overview-column">
          <NCard title="协作概览" size="small">
            <NSteps vertical size="small" :current="activePhase" :status="stepsStatus">
              <NStep v-for="phase in phases" :key="phase.label" :title="phase.label" />
            </NSteps>
          </NCard>
          <NCard title="工作项" size="small">
            <ul v-if="detail.work_items.length" class="work-item-list">
              <li v-for="item in detail.work_items" :key="item.work_item_id">
                <strong>{{ item.target }}</strong><span>{{ item.objective }}</span>
                <small>{{ item.skill_name }} · {{ item.status }}</small>
              </li>
            </ul>
            <NEmpty v-else size="small" description="Manager 尚未分派工作项" />
          </NCard>
          <NCard title="角色边界" size="small">
            <ul class="role-list">
              <li><strong>Manager</strong><span>拆解、状态汇总与审批协调</span></li>
              <li><strong>Data Steward</strong><span>只读预检与证据检索</span></li>
              <li><strong>Workflow Operator</strong><span>受审批约束的任务执行</span></li>
              <li><strong>Quality Auditor</strong><span>质量门禁与证据核验</span></li>
              <li><strong>Delivery Reporter</strong><span>交付包与复盘证据</span></li>
            </ul>
          </NCard>
        </section>
        <section class="timeline-column">
          <NCard title="协作时间线" size="small">
            <template #header-extra>
              <span class="sync-status" :aria-live="syncing ? 'polite' : 'off'">
                <NIcon><SyncOutline /></NIcon>{{ syncing ? '同步中' : eventStreamHealthy ? '实时同步' : pollingActive ? '每 20 秒刷新' : '后台暂停刷新' }}
              </span>
            </template>
            <NTimeline v-if="events.length">
              <NTimelineItem
                v-for="event in events"
                :key="event.event_id"
                :title="eventLabel(event.event_type)"
                :time="new Date(event.recorded_at).toLocaleString('zh-CN')"
              >
                <p>{{ event.actor }}</p>
                <code v-if="event.payload?.summary">{{ event.payload.summary }}</code>
              </NTimelineItem>
            </NTimeline>
            <NEmpty v-else description="暂未产生协作事件" />
            <small v-if="lastSyncedAt" class="sync-time">最近同步：{{ lastSyncedAt.toLocaleTimeString('zh-CN') }}</small>
          </NCard>
        </section>
        <aside class="evidence-column">
          <NCard v-if="canSubmit" class="approval-card" title="人工审批" size="small">
            <template #header-extra><NTag type="warning" :bordered="false">需要确认</NTag></template>
            <p class="approval-card__summary">预检已通过，但真实计算尚未启动。请审阅本次执行范围后确认。</p>
            <dl class="approval-card__scope">
              <div><dt>执行者</dt><dd>Workflow Operator</dd></div>
              <div><dt>输入</dt><dd>已通过预检的固定样本表与分组对比</dd></div>
              <div><dt>动作</dt><dd>创建一个真实 OmicHub RNA-seq 计算任务</dd></div>
              <div><dt>审计</dt><dd>审批、提交回执与后续状态均写入此 Case</dd></div>
            </dl>
            <NButton type="primary" size="small" @click="openSubmit">审阅并批准执行</NButton>
          </NCard>
          <NCard v-if="detail.status === 'execution_failed'" class="failure-card" title="执行恢复" size="small">
            <template #header-extra><NTag type="error" :bordered="false">需要处理</NTag></template>
            <p class="approval-card__summary">本次任务证据会保留。重试将复用冻结计划，并生成新的提交版本与幂等键。</p>
            <NButton type="primary" size="small" :loading="retrying" @click="retryFailedCase">按冻结计划重试</NButton>
          </NCard>
          <NCard title="下一步" size="small">
            <div class="next-step">
              <strong>{{ nextStep.title }}</strong>
              <span>{{ nextStep.description }}</span>
            </div>
          </NCard>
          <NCard title="执行证据" size="small">
            <NDescriptions :column="1" label-placement="top" size="small">
              <NDescriptionsItem label="当前阶段"><NTag type="info" :bordered="false">{{ formatAgentTeamsStatus(detail.status) }}</NTag></NDescriptionsItem>
              <NDescriptionsItem label="执行上下文">
                {{ detail.project_ref?.id || detail.context_refs.map((ref) => `${ref.kind}:${ref.id}`).join(', ') || '未关联' }}
              </NDescriptionsItem>
              <NDescriptionsItem label="来源会诊">
                {{ detail.origin_consultation_id || '非会诊创建' }}
              </NDescriptionsItem>
              <NDescriptionsItem v-if="detail.consultation_summary" label="会诊纪要">
                {{ detail.consultation_summary }}
              </NDescriptionsItem>
              <NDescriptionsItem label="关联任务">
                <div v-if="detail.omic_task_ids.length" class="task-links">
                  <NButton v-for="taskId in detail.omic_task_ids" :key="taskId" text type="primary" size="tiny" @click="router.push({ name: 'task-detail', params: { taskId } })">{{ taskId }}</NButton>
                </div>
                <span v-else>尚未提交</span>
              </NDescriptionsItem>
              <NDescriptionsItem label="质量结论">
                <div class="quality-decision-line">
                  <span>{{ detail.quality_decision || '尚未形成' }}</span>
                  <NButton v-if="canSubmitQualityGate" size="tiny" type="primary" @click="openQualityGate">提交质量结论</NButton>
                </div>
              </NDescriptionsItem>
              <NDescriptionsItem label="计划短码">{{ planShortHash || '尚未冻结' }}</NDescriptionsItem>
              <NDescriptionsItem label="交付 Manifest">
                <div v-if="detail.manifest_uri" class="manifest-actions">
                  <span class="manifest-uri">{{ detail.manifest_uri }}</span>
                  <div class="manifest-buttons">
                    <NButton size="tiny" secondary :loading="manifestLoading" @click="openManifest">在线预览</NButton>
                    <NButton size="tiny" type="primary" :loading="manifestLoading" @click="downloadManifest">下载 JSON</NButton>
                  </div>
                </div>
                <span v-else>尚未生成</span>
              </NDescriptionsItem>
            </NDescriptions>
          </NCard>
          <NCard title="安全边界" size="small">
            <div class="security-note"><NIcon><ShieldCheckmarkOutline /></NIcon><span>所有计算操作经独立 Bridge；此页面只展示经授权的 Case 证据。</span></div>
          </NCard>
        </aside>
      </div>
    </NSpin>
    <NModal v-model:show="submitVisible" preset="card" title="人工确认并提交计算任务" :style="{ width: 'min(92vw, 560px)' }" :mask-closable="!submitting">
      <NAlert type="warning" :show-icon="true" class="submit-warning">
        此操作会由后端以独立审批与 Workflow Operator 身份创建真实 OmicHub 计算任务，并严格复用已通过预检的样本表、分组对比和流程输入。浏览器无法修改这些输入。
      </NAlert>
      <NForm label-placement="top" @submit.prevent="confirmSubmit">
        <NFormItem label="任务名称" required><NInput v-model:value="submitForm.task_name" /></NFormItem>
        <NCheckbox v-model:checked="approvalConfirmed">
          我确认提交本次真实 RNA-seq 计算；浏览器不会修改已预检通过的输入，执行与结果将记录在当前 Case。
        </NCheckbox>
        <div class="submit-actions"><NButton :disabled="submitting" @click="submitVisible = false">取消</NButton><NButton type="primary" attr-type="submit" :disabled="!approvalConfirmed" :loading="submitting">确认并提交</NButton></div>
      </NForm>
    </NModal>
    <NModal v-model:show="manifestVisible" preset="card" title="交付 Manifest" :style="{ width: 'min(94vw, 760px)' }">
      <pre class="manifest-preview">{{ JSON.stringify(manifest, null, 2) }}</pre>
    </NModal>
    <NModal v-model:show="qualityGateVisible" preset="card" title="提交质量门禁结论" :style="{ width: 'min(92vw, 520px)' }" :mask-closable="!qualityGateSubmitting">
      <NForm label-placement="top" @submit.prevent="confirmQualityGate">
        <NFormItem label="关联任务" required>
          <NSelect v-model:value="qualityGateForm.task_id" :options="detail?.omic_task_ids.map((id) => ({ label: id, value: id })) || []" placeholder="选择 OmicHub 任务" />
        </NFormItem>
        <NFormItem label="决策" required>
          <NSelect v-model:value="qualityGateForm.decision" :options="[
            { label: '通过', value: 'passed' },
            { label: '阻断', value: 'blocked' },
            { label: '转人工复核', value: 'manual_review' },
          ]" />
        </NFormItem>
        <NFormItem label="规则版本" required><NInput v-model:value="qualityGateForm.rule_version" placeholder="如 demo-rna-qc-1.0" /></NFormItem>
        <NFormItem label="结论摘要" required>
          <NInput v-model:value="qualityGateForm.summary" type="textarea" :rows="3" placeholder="说明质量审查依据与结论" />
        </NFormItem>
        <NFormItem label="证据引用（每行一个，格式 kind:id）">
          <NInput v-model:value="qualityGateForm.evidence_refs" type="textarea" :rows="3" placeholder="例如：task:abc-123" />
          <template #feedback><NText depth="3">每行一个引用，格式为 kind:id；留空则仅提交决策。</NText></template>
        </NFormItem>
        <div class="submit-actions">
          <NButton :disabled="qualityGateSubmitting" @click="qualityGateVisible = false">取消</NButton>
          <NButton type="primary" attr-type="submit" :loading="qualityGateSubmitting">提交结论</NButton>
        </div>
      </NForm>
    </NModal>
  </main>
</template>

<style scoped>
.case-page { min-height: 100%; }
.case-workbench { display: grid; grid-template-columns: minmax(190px, 264px) minmax(0, 1fr) minmax(280px, 360px); gap: 16px; align-items: start; }
.overview-column, .evidence-column { display: grid; gap: 16px; }
.role-list, .work-item-list { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.role-list li, .work-item-list li { display: grid; gap: 3px; }
.role-list strong, .work-item-list strong { color: var(--text-primary); font-size: 13px; }
.role-list span, .work-item-list span { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.work-item-list small, .sync-time { color: var(--text-tertiary); font-size: 11px; }
.sync-time { display: block; margin-top: 12px; }
.sync-status { display: inline-flex; align-items: center; gap: 4px; color: var(--text-secondary); font-size: 12px; }
.security-note { display: flex; gap: 8px; color: var(--text-secondary); font-size: 13px; line-height: 1.55; }
.security-note :deep(svg) { flex: 0 0 auto; margin-top: 2px; color: var(--primary-color); }
.next-step { display: grid; gap: 6px; }
.next-step strong { color: var(--text-primary); font-size: 13px; }
.next-step span { color: var(--text-secondary); font-size: 13px; line-height: 1.55; }
.approval-card { border-left: 3px solid var(--warning-color, #f0a020); }
.failure-card { border-left: 3px solid var(--error-color); }
.approval-card__summary { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; line-height: 1.55; }
.approval-card__scope { display: grid; gap: 10px; margin: 0 0 16px; }
.approval-card__scope div { display: grid; gap: 2px; }
.approval-card__scope dt { color: var(--text-tertiary); font-size: 11px; }
.approval-card__scope dd { margin: 0; color: var(--text-primary); font-size: 12px; line-height: 1.45; }
.submit-warning { margin-bottom: 16px; }
.submit-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.timeline-column :deep(.n-timeline-item-content p) { margin: 0 0 5px; color: var(--text-secondary); font-size: 12px; }
.timeline-column code { display: block; white-space: pre-wrap; color: var(--text-secondary); font-size: 12px; }
.alert-retry { margin-left: 10px; }
.manifest-actions { display: grid; gap: 8px; }
.manifest-buttons, .task-links { display: flex; flex-wrap: wrap; gap: 8px; }
.manifest-uri { overflow-wrap: anywhere; color: var(--text-secondary); font-size: 12px; }
.manifest-preview { max-height: 60vh; overflow: auto; margin: 0; padding: 12px; border-radius: 8px; background: var(--surface-color-soft); color: var(--text-secondary); font: 12px/1.6 ui-monospace, monospace; white-space: pre-wrap; }
.quality-decision-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
@media (max-width: 1024px) { .case-workbench { grid-template-columns: minmax(190px, 240px) minmax(0, 1fr); } .evidence-column { grid-column: 1 / -1; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 768px) { .case-workbench, .evidence-column { grid-template-columns: 1fr; } .overview-column, .timeline-column, .evidence-column { grid-column: auto; } }
</style>
