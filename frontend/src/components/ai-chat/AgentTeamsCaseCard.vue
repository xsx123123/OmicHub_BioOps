<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NButton, NCollapse, NCollapseItem, NInput, NModal, NPopconfirm, NTag } from 'naive-ui'
import { useRouter } from 'vue-router'
import { agentTeamsApi, type AgentTeamsCapabilityCheck, type AgentTeamsEvent } from '@/api/agentTeams'
import { useAgentTeamsStore } from '@/stores/agentTeams'
import { shouldPollAgentTeamsCase } from '@/utils/agentTeamsState'
import { agentTeamsNextActor, formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'
import type { AgentTeamsCaseCardPayload } from './types'

const props = defineProps<{ caseInfo: AgentTeamsCaseCardPayload }>()

const router = useRouter()
const agentTeamsStore = useAgentTeamsStore()
const detail = ref<AgentTeamsCaseCardPayload>({ ...props.caseInfo })
const loading = ref(false)
const decisionLoading = ref(false)
const decisionError = ref('')
const recentEvents = ref<AgentTeamsEvent[]>([])
const capabilityCheck = ref<AgentTeamsCapabilityCheck | null>(null)
const rejectVisible = ref(false)
const rejectReason = ref('')
const revisionVisible = ref(false)
const revisionParameters = ref('')
const revisionReason = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const isApprovalPending = computed(() => detail.value.status === 'approval_pending')
const isExecutionFailed = computed(() => detail.value.status === 'execution_failed')
const canCancel = computed(() => !['closed', 'cancelled'].includes(detail.value.status))
const displayStatus = computed(() => formatAgentTeamsStatus(detail.value.status))
const updatedAt = computed(() => {
  if (!detail.value.updated_at) return ''
  const value = new Date(detail.value.updated_at)
  return Number.isNaN(value.getTime()) ? '' : value.toLocaleString()
})
const planShortHash = computed(() => detail.value.plan_hash ? detail.value.plan_hash.slice(0, 12) : '')

function eventSummary(event: AgentTeamsEvent): string {
  const payload = event.payload || {}
  return String(payload.summary || payload.reason || payload.error_excerpt || payload.status || event.event_type)
}

async function refresh() {
  if (!shouldPollAgentTeamsCase(document.visibilityState) || loading.value) return
  loading.value = true
  try {
    const [value, eventPage, capability] = await Promise.all([
      agentTeamsStore.refreshCase(detail.value.case_id),
      agentTeamsApi.getEvents(detail.value.case_id, { limit: 3 }),
      agentTeamsApi.getCapabilityCheck(detail.value.case_id).catch(() => null),
    ])
    detail.value = {
      ...detail.value,
      title: value.intent.slice(0, 80) || detail.value.title,
      status: value.status,
      next_actor: agentTeamsNextActor[value.status] || detail.value.next_actor,
      updated_at: value.updated_at,
      plan_hash: value.plan_hash,
      plan_version: value.plan_version,
      proposed_submission: value.proposed_submission,
      work_items: value.work_items,
      quality_decision: value.quality_decision,
      manifest_uri: value.manifest_uri,
    }
    recentEvents.value = eventPage.events.slice(-3).reverse()
    capabilityCheck.value = capability
  } catch {
  } finally {
    loading.value = false
  }
}

async function approveCase() {
  if (decisionLoading.value) return
  decisionLoading.value = true
  decisionError.value = ''
  try {
    await agentTeamsStore.submitCase(detail.value.case_id, { task_name: detail.value.title.slice(0, 128) })
    await refresh()
  } catch (cause: any) {
    decisionError.value = cause?.response?.data?.detail || '审批失败，请刷新后重试。'
  } finally {
    decisionLoading.value = false
  }
}

async function rejectCase() {
  if (decisionLoading.value) return
  const reason = rejectReason.value.trim()
  if (reason.length < 3) {
    decisionError.value = '请填写至少 3 个字符的拒绝理由。'
    return
  }
  decisionLoading.value = true
  decisionError.value = ''
  try {
    const value = await agentTeamsStore.rejectCase(detail.value.case_id, {
      reason,
    })
    detail.value = { ...detail.value, status: value.status, updated_at: value.updated_at }
    rejectVisible.value = false
  } catch (cause: any) {
    decisionError.value = cause?.response?.data?.detail || '拒绝失败，请刷新后重试。'
  } finally {
    decisionLoading.value = false
  }
}

async function retryCase() {
  if (decisionLoading.value) return
  decisionLoading.value = true
  decisionError.value = ''
  try {
    await agentTeamsStore.retryCase(detail.value.case_id)
    await refresh()
  } catch (cause: any) {
    decisionError.value = cause?.response?.data?.detail || '重试失败，请打开 Case 查看错误摘要。'
  } finally {
    decisionLoading.value = false
  }
}

async function cancelCase() {
  if (decisionLoading.value || !canCancel.value) return
  decisionLoading.value = true
  decisionError.value = ''
  try {
    const value = await agentTeamsStore.cancelCase(detail.value.case_id, {
      reason: '用户从聊天窗口主动取消协作 Case',
    })
    detail.value = { ...detail.value, status: value.status, updated_at: value.updated_at }
  } catch (cause: any) {
    decisionError.value = cause?.response?.data?.detail || '取消失败，请刷新后重试。'
  } finally {
    decisionLoading.value = false
  }
}

function openRevision() {
  const parameters = detail.value.proposed_submission?.parameters
  revisionParameters.value = JSON.stringify(parameters && typeof parameters === 'object' ? parameters : {}, null, 2)
  revisionReason.value = ''
  decisionError.value = ''
  revisionVisible.value = true
}

async function revisePlan() {
  if (decisionLoading.value || !detail.value.plan_hash) return
  const reason = revisionReason.value.trim()
  if (reason.length < 3) {
    decisionError.value = '请填写至少 3 个字符的修改理由。'
    return
  }
  let parameters: Record<string, unknown>
  try {
    const parsed = JSON.parse(revisionParameters.value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('invalid')
    parameters = parsed
  } catch {
    decisionError.value = '参数必须是合法的 JSON 对象。'
    return
  }
  decisionLoading.value = true
  decisionError.value = ''
  try {
    await agentTeamsStore.revisePlan(detail.value.case_id, {
      expected_plan_hash: detail.value.plan_hash,
      parameters,
      reason,
    })
    revisionVisible.value = false
    await refresh()
  } catch (cause: any) {
    decisionError.value = cause?.response?.data?.detail || '计划修改失败，请刷新后重试。'
  } finally {
    decisionLoading.value = false
  }
}

function openCase() {
  void router.push(detail.value.case_url || `/agent-teams/cases/${detail.value.case_id}`)
}

onMounted(() => {
  void refresh()
  timer = setInterval(() => void refresh(), 20_000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="agentteams-case-card">
    <div class="case-header">
      <div>
        <p class="eyebrow">AgentTeams 协作 Case</p>
        <strong>{{ detail.title }}</strong>
      </div>
      <NTag size="small" :type="isApprovalPending ? 'warning' : 'info'">{{ displayStatus }}</NTag>
    </div>
    <p class="case-meta">下一责任方：{{ detail.next_actor }}</p>
    <p v-if="updatedAt" class="case-updated">最近更新：{{ updatedAt }}</p>
    <section class="fact-panel" aria-label="Case 运行事实">
      <div class="fact-heading"><strong>运行事实</strong><span>{{ detail.status }}</span></div>
      <div v-if="detail.work_items?.length" class="fact-list">
        <div v-for="item in detail.work_items" :key="item.work_item_id" class="fact-row">
          <span>{{ item.work_item_id }} · {{ item.target }}</span><NTag size="tiny">{{ item.status }}</NTag>
        </div>
      </div>
      <p v-else class="fact-empty">
        {{ detail.status === 'received' ? '尚未派发：Case 已创建，等待规划或人工确认。' : '当前还没有可展示的工作项。' }}
      </p>
      <p class="fact-note">质量门：{{ detail.quality_decision || '尚未形成判定' }}</p>
      <p v-if="detail.manifest_uri" class="fact-note">交付 Manifest 已生成。</p>
      <div v-if="capabilityCheck?.stages?.length" class="capability-list">
        <div v-for="stage in capabilityCheck.stages" :key="stage.stage" class="fact-row">
          <span>{{ stage.stage }} · {{ stage.agent_id }}</span>
          <NTag size="tiny" :type="stage.available ? 'success' : 'warning'">{{ stage.available ? '可交接' : stage.reason }}</NTag>
        </div>
      </div>
    </section>
    <div v-if="isApprovalPending" class="approval-rail">
      <p>审批待处理：确认冻结计划后继续执行。</p>
      <p v-if="planShortHash" class="plan-hash">
        计划 v{{ detail.plan_version || 1 }} · 短码 {{ planShortHash }}
      </p>
      <NCollapse v-if="detail.proposed_submission" class="plan-details">
        <NCollapseItem title="查看冻结参数" name="parameters">
          <pre>{{ JSON.stringify(detail.proposed_submission, null, 2) }}</pre>
        </NCollapseItem>
      </NCollapse>
      <div class="approval-actions">
        <NButton size="small" type="primary" :loading="decisionLoading" @click="approveCase">批准并继续</NButton>
        <NButton size="small" secondary :disabled="decisionLoading || !detail.plan_hash" @click="openRevision">修改参数</NButton>
        <NButton size="small" type="error" secondary :disabled="decisionLoading" @click="rejectVisible = true">拒绝计划</NButton>
      </div>
      <span v-if="decisionError" class="decision-error" role="alert">{{ decisionError }}</span>
    </div>
    <div v-else-if="isExecutionFailed" class="failure-rail">
      <p>任务执行失败。重试会保留原任务证据，并创建新的提交版本。</p>
      <NButton size="small" type="primary" :loading="decisionLoading" @click="retryCase">按冻结计划重试</NButton>
      <span v-if="decisionError" class="decision-error" role="alert">{{ decisionError }}</span>
    </div>
    <ol v-if="recentEvents.length" class="recent-events" aria-label="最近协作事件">
      <li v-for="event in recentEvents" :key="event.event_id">
        <span>{{ event.event_type }}</span>
        <small>{{ eventSummary(event) }}</small>
      </li>
    </ol>
    <div class="case-actions">
      <NButton size="small" :loading="loading" @click="refresh">刷新状态</NButton>
      <NButton size="small" type="primary" @click="openCase">打开 Case</NButton>
      <NPopconfirm v-if="canCancel" @positive-click="cancelCase">
        <template #trigger>
          <NButton size="small" type="error" secondary :disabled="decisionLoading">取消协作</NButton>
        </template>
        取消后将停止未完成工单，但保留已产生的审计记录与产物。
      </NPopconfirm>
    </div>
    <span v-if="decisionError && !isApprovalPending && !isExecutionFailed" class="decision-error" role="alert">{{ decisionError }}</span>
    <NModal v-model:show="rejectVisible" preset="card" title="拒绝冻结计划" :style="{ width: 'min(92vw, 480px)' }" :mask-closable="!decisionLoading">
      <NInput v-model:value="rejectReason" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" maxlength="512" show-count placeholder="说明需要修正的输入、参数或交付范围" />
      <div class="reject-actions">
        <NButton :disabled="decisionLoading" @click="rejectVisible = false">取消</NButton>
        <NButton type="error" :loading="decisionLoading" @click="rejectCase">提交拒绝理由</NButton>
      </div>
      <span v-if="decisionError" class="decision-error" role="alert">{{ decisionError }}</span>
    </NModal>
    <NModal v-model:show="revisionVisible" preset="card" title="修改冻结计划参数" :style="{ width: 'min(94vw, 680px)' }" :mask-closable="!decisionLoading">
      <p class="revision-help">仅可修改 <code>parameters</code>。系统会生成新 plan_hash，并只重放改动工作项及其下游依赖。</p>
      <NInput v-model:value="revisionParameters" type="textarea" :autosize="{ minRows: 8, maxRows: 18 }" placeholder="参数 JSON 对象" />
      <NInput v-model:value="revisionReason" class="revision-reason" maxlength="512" show-count placeholder="修改理由" />
      <div class="reject-actions">
        <NButton :disabled="decisionLoading" @click="revisionVisible = false">取消</NButton>
        <NButton type="primary" :loading="decisionLoading" @click="revisePlan">生成新计划</NButton>
      </div>
      <span v-if="decisionError" class="decision-error" role="alert">{{ decisionError }}</span>
    </NModal>
  </section>
</template>

<style scoped>
.agentteams-case-card { margin-top: 12px; padding: 14px; border: 1px solid var(--chat-border); border-radius: 12px; background: color-mix(in srgb, var(--chat-bg) 88%, #6366f1 12%); }
.case-header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.eyebrow { margin: 0 0 4px; color: var(--chat-text-muted); font-size: 12px; }
.case-meta, .case-updated, .approval-rail, .failure-rail { margin: 10px 0 0; font-size: 13px; color: var(--chat-text-secondary); }
.fact-panel { display: grid; gap: 7px; margin-top: 10px; padding: 9px; border: 1px solid var(--chat-border); border-radius: 9px; background: color-mix(in srgb, var(--chat-bg) 94%, #64748b 6%); }
.fact-heading, .fact-row { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.fact-heading { color: var(--chat-text-secondary); font-size: 12px; }
.fact-heading span, .fact-empty, .fact-note { margin: 0; color: var(--chat-text-muted); font-size: 11px; }
.fact-list, .capability-list { display: grid; gap: 5px; }
.fact-row { color: var(--chat-text-secondary); font-size: 11px; }
.approval-rail { display: grid; gap: 8px; padding: 8px; border-left: 3px solid var(--warning-color, #f59e0b); background: color-mix(in srgb, var(--warning-color, #f59e0b) 12%, transparent); }
.failure-rail { display: grid; gap: 8px; padding: 8px; border-left: 3px solid var(--error-color); background: color-mix(in srgb, var(--error-color) 10%, transparent); }
.approval-rail p, .failure-rail p { margin: 0; }
.approval-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.plan-hash { color: var(--chat-text-muted); font-family: ui-monospace, monospace; font-size: 12px; }
.plan-details :deep(.n-collapse-item__content-inner) { padding-top: 6px; }
.plan-details pre { max-height: 180px; margin: 0; overflow: auto; color: var(--chat-text-secondary); font-size: 11px; white-space: pre-wrap; }
.decision-error { color: var(--error-color, #d03050); font-size: 12px; }
.reject-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.revision-help { margin: 0 0 10px; color: var(--chat-text-secondary); font-size: 12px; }
.revision-reason { margin-top: 10px; }
.recent-events { display: grid; gap: 6px; margin: 12px 0 0; padding: 0; list-style: none; }
.recent-events li { display: grid; gap: 2px; padding-left: 8px; border-left: 2px solid var(--chat-border); }
.recent-events span { color: var(--chat-text-secondary); font-size: 12px; font-weight: 600; }
.recent-events small { overflow: hidden; color: var(--chat-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.case-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
</style>
