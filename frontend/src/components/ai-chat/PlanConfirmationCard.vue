<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { NButton, NIcon, NInput, NModal, NPopconfirm, NTag, useMessage } from 'naive-ui'
import {
  CheckmarkCircleOutline,
  CloseCircleOutline,
  DocumentTextOutline,
  GitNetworkOutline,
  PeopleOutline,
  RefreshOutline,
  ShieldCheckmarkOutline,
} from '@vicons/ionicons5'
import { chatApi } from '@/api/chat'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { useAgentHubStore } from '@/stores/agentHub'
import type { PlanConfirmation, PlanDecisionAction } from './types'

const props = defineProps<{
  plan: PlanConfirmation
  sessionId?: string
}>()

const store = useAgentHubStore()
const message = useMessage()
const feedback = ref('')
const showFeedback = ref(false)
const showPreview = ref(false)
const previewLoading = ref(false)
const previewContent = ref('')
const previewError = ref('')
const previewTitle = ref<HTMLElement | null>(null)

const pending = computed(() => props.plan.status === 'pending')
const showingActions = computed(() => props.plan.status === 'pending' || props.plan.status === 'submitting')
const planReadable = computed(() => Boolean(previewContent.value) && !previewLoading.value && !previewError.value)
const titleId = computed(() => `plan-confirmation-${props.plan.runId.replace(/[^a-zA-Z0-9_-]/g, '-')}`)
const statusMeta = computed(() => ({
  pending: { label: '等待你的确认', type: 'warning' as const },
  submitting: { label: '正在提交', type: 'info' as const },
  approved: { label: '已确认执行', type: 'success' as const },
  revision_requested: { label: '已提出修改', type: 'info' as const },
  cancelled: { label: '已取消任务', type: 'default' as const },
  error: { label: '提交失败', type: 'error' as const },
}[props.plan.status]))
const planningSourceMeta = computed(() => props.plan.planningMode ? ({
  llm: { label: 'AI 规划', type: 'success' as const },
  llm_repaired: { label: 'AI 规划（已自动校正）', type: 'info' as const },
  rule_merge: { label: '领域标准流程辅助', type: 'warning' as const },
  rule_override: { label: '领域标准流程辅助', type: 'warning' as const },
  rule_preflight: { label: '领域标准流程辅助', type: 'warning' as const },
}[props.plan.planningMode]) : null)

function hasAction(action: PlanDecisionAction): boolean {
  return props.plan.actions.includes(action)
}

async function decide(action: PlanDecisionAction) {
  if (!pending.value) return
  if (action === 'revise' && !showFeedback.value) {
    showFeedback.value = true
    await nextTick()
    document.querySelector<HTMLTextAreaElement>('.plan-confirmation__feedback textarea')?.focus()
    return
  }
  if (action === 'revise' && !feedback.value.trim()) {
    message.warning('请先说明希望如何修改计划')
    return
  }
  try {
    await store.decideOverdrivePlan(props.plan.runId, action, feedback.value)
    message.success(action === 'approve' ? '计划已确认，主 Agent 将开始串行前置工作' : action === 'revise' ? '修改意见已提交' : '任务已取消')
  } catch {
    message.error(props.plan.error || '计划决策提交失败，请重试')
  }
}

async function loadPlanContent() {
  previewError.value = ''
  if (previewContent.value || previewLoading.value) return
  if (!props.sessionId || !props.plan.runId) {
    previewError.value = '会话尚未完成初始化，暂时无法预览计划。'
    return
  }
  previewLoading.value = true
  try {
    previewContent.value = await chatApi.getOverdrivePlan(props.sessionId, props.plan.runId)
    if (!previewContent.value) previewError.value = '计划内容为空，请返回后重试。'
  } catch {
    previewError.value = '计划预览加载失败，请稍后重试。'
  } finally {
    previewLoading.value = false
  }
}

async function openPreview() {
  showPreview.value = true
  await loadPlanContent()
  await nextTick()
  previewTitle.value?.focus()
}

onMounted(() => {
  void loadPlanContent()
})
</script>

<template>
  <section class="plan-confirmation" :class="`is-${plan.status}`" :aria-labelledby="titleId" aria-live="polite">
    <header class="plan-confirmation__header">
      <div>
        <span class="plan-confirmation__eyebrow">
          <n-icon aria-hidden="true"><ShieldCheckmarkOutline /></n-icon>
          PLAN REVIEW · V{{ plan.planVersion }}
        </span>
        <h3 :id="titleId">{{ plan.title }}</h3>
      </div>
      <div class="plan-confirmation__tags" aria-label="计划状态与来源">
        <n-tag v-if="planningSourceMeta" size="small" round :bordered="false" :type="planningSourceMeta.type">{{ planningSourceMeta.label }}</n-tag>
        <n-tag size="small" round :bordered="false" :type="statusMeta.type">{{ statusMeta.label }}</n-tag>
      </div>
    </header>

    <p v-if="plan.summary" class="plan-confirmation__summary">{{ plan.summary }}</p>

    <dl class="plan-confirmation__metrics" aria-label="计划规模">
      <div>
        <dt><n-icon aria-hidden="true"><GitNetworkOutline /></n-icon>预计波次</dt>
        <dd>{{ plan.waveCount || '待计划确定' }}</dd>
      </div>
      <div>
        <dt><n-icon aria-hidden="true"><PeopleOutline /></n-icon>参与 Agent</dt>
        <dd>{{ plan.agents.length || '待计划确定' }}</dd>
      </div>
      <div>
        <dt><n-icon aria-hidden="true"><DocumentTextOutline /></n-icon>最终交付物</dt>
        <dd>{{ plan.deliverables.length || '见计划全文' }}</dd>
      </div>
    </dl>

    <div v-if="plan.agents.length" class="plan-confirmation__agents" aria-label="参与 Agent">
      <span v-for="agent in plan.agents" :key="agent.agentId" :title="agent.reason">{{ agent.name }}</span>
    </div>

    <div class="plan-confirmation__details">
      <section v-if="plan.serialPreflight.length">
        <h4>主 Agent 串行前置</h4>
        <ul><li v-for="item in plan.serialPreflight" :key="item">{{ item }}</li></ul>
      </section>
      <section v-if="plan.risks.length || plan.approvalPoints.length" class="is-risk">
        <h4>风险与审批点</h4>
        <ul>
          <li v-for="item in plan.risks" :key="`risk-${item}`">{{ item }}</li>
          <li v-for="item in plan.approvalPoints" :key="`approval-${item}`">审批：{{ item }}</li>
        </ul>
      </section>
      <section v-if="plan.deliverables.length">
        <h4>最终交付物</h4>
        <ul><li v-for="item in plan.deliverables" :key="item">{{ item }}</li></ul>
      </section>
    </div>

    <section class="plan-confirmation__full-plan" aria-labelledby="full-plan-title">
      <div class="plan-confirmation__full-plan-header">
        <div>
          <h4 id="full-plan-title">完整执行计划（请审阅后确认）</h4>
          <small>{{ plan.planPath || '冻结计划快照' }}</small>
        </div>
        <n-button text type="primary" :disabled="previewLoading" @click="openPreview">在大窗口阅读</n-button>
      </div>
      <div v-if="previewLoading" class="plan-confirmation__plan-state" role="status">正在加载计划全文…</div>
      <div v-else-if="previewError" class="plan-confirmation__plan-state is-error" role="alert">
        <span>{{ previewError }}</span>
        <n-button size="small" secondary @click="loadPlanContent">重试</n-button>
      </div>
      <div v-else class="plan-confirmation__plan-content">
        <MarkdownRenderer :content="previewContent" />
      </div>
    </section>

    <button type="button" class="plan-confirmation__preview" :disabled="previewLoading" @click="openPreview">
      <n-icon aria-hidden="true"><DocumentTextOutline /></n-icon>
      <span><strong>在大窗口阅读完整 plan.md</strong><small>计划全文已在上方默认展开</small></span>
      <span aria-hidden="true">→</span>
    </button>

    <n-input
      v-if="showFeedback && showingActions"
      v-model:value="feedback"
      class="plan-confirmation__feedback"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 5 }"
      placeholder="说明需要调整的任务、波次、风险或交付物"
      :input-props="{ 'aria-label': '计划修改意见' }"
    />

    <p v-if="plan.error" class="plan-confirmation__error" role="alert">{{ plan.error }}</p>
    <p v-if="plan.feedback && !pending" class="plan-confirmation__feedback-summary">修改意见：{{ plan.feedback }}</p>

    <footer v-if="showingActions" class="plan-confirmation__actions">
      <n-button v-if="hasAction('approve')" type="primary" :loading="plan.status === 'submitting'" :disabled="!planReadable" @click="decide('approve')">
        <template #icon><n-icon><CheckmarkCircleOutline /></n-icon></template>
        确认并执行
      </n-button>
      <n-button v-if="hasAction('revise')" :disabled="plan.status === 'submitting'" @click="decide('revise')">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
        {{ showFeedback ? '提交修改意见' : '提出修改' }}
      </n-button>
      <n-popconfirm v-if="hasAction('cancel')" positive-text="确认取消" negative-text="返回" @positive-click="decide('cancel')">
        <template #trigger>
          <n-button quaternary type="error" :disabled="plan.status === 'submitting'">
            <template #icon><n-icon><CloseCircleOutline /></n-icon></template>
            取消任务
          </n-button>
        </template>
        取消后本轮计划不会执行，已生成的研究与计划快照仍会保留。
      </n-popconfirm>
    </footer>

    <n-modal v-model:show="showPreview" preset="card" class="plan-preview-modal" :style="{ width: 'min(900px, calc(100vw - 32px))' }" aria-label="计划全文预览">
      <template #header>
        <span ref="previewTitle" tabindex="-1">plan.md · 版本 {{ plan.planVersion }}</span>
      </template>
      <div v-if="previewLoading" class="plan-preview-modal__state" role="status">正在加载计划全文…</div>
      <div v-else-if="previewError" class="plan-preview-modal__state is-error" role="alert">{{ previewError }}</div>
      <div v-else class="plan-preview-modal__content"><MarkdownRenderer :content="previewContent" /></div>
    </n-modal>
  </section>
</template>

<style scoped>
.plan-confirmation { width:100%; margin-top:var(--space-md); padding:var(--space-xl); border:1px solid var(--border-focus, var(--neutral-border)); border-radius:12px; background:var(--surface-elevated, var(--neutral-card)); box-shadow:var(--shadow-card); }
.plan-confirmation__header,.plan-confirmation__actions,.plan-confirmation__eyebrow,.plan-confirmation__preview,.plan-confirmation__metrics dt,.plan-confirmation__tags { display:flex; align-items:center; }
.plan-confirmation__header { justify-content:space-between; gap:var(--space-lg); }
.plan-confirmation__tags { flex-wrap:wrap; justify-content:flex-end; gap:var(--space-xs); }
.plan-confirmation__eyebrow { gap:var(--space-sm); color:var(--arco-primary); font-size:12px; font-weight:700; letter-spacing:.05em; }
.plan-confirmation h3 { margin:var(--space-xs) 0 0; color:var(--neutral-text-1); font-size:16px; line-height:24px; }
.plan-confirmation__summary { margin:var(--space-md) 0; color:var(--neutral-text-2); font-size:14px; line-height:22px; white-space:pre-wrap; }
.plan-confirmation__metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-sm); margin:0 0 var(--space-md); }
.plan-confirmation__metrics>div { min-width:0; padding:var(--space-md); border:1px solid var(--border-subtle, var(--neutral-border)); border-radius:8px; background:var(--surface-card, var(--neutral-card)); }
.plan-confirmation__metrics dt { gap:var(--space-xs); color:var(--neutral-text-3); font-size:12px; }
.plan-confirmation__metrics dd { margin:var(--space-xs) 0 0; color:var(--neutral-text-1); font-size:18px; font-weight:600; }
.plan-confirmation__agents { display:flex; flex-wrap:wrap; gap:var(--space-sm); margin-bottom:var(--space-md); }
.plan-confirmation__agents span { padding:4px 8px; border-radius:9999px; background:var(--neutral-hover); color:var(--neutral-text-2); font-size:12px; }
.plan-confirmation__details { display:grid; gap:var(--space-md); margin-bottom:var(--space-md); }
.plan-confirmation__details section { padding-left:var(--space-md); border-left:3px solid var(--arco-primary); }
.plan-confirmation__details section.is-risk { border-left-color:var(--arco-warning); }
.plan-confirmation__details h4 { margin:0 0 var(--space-xs); color:var(--neutral-text-1); font-size:13px; }
.plan-confirmation__details ul { margin:0; padding-left:20px; color:var(--neutral-text-2); font-size:13px; line-height:20px; }
.plan-confirmation__full-plan { margin-top:var(--space-md); overflow:hidden; border:1px solid var(--neutral-border); border-radius:8px; background:var(--surface-card, var(--neutral-card)); }
.plan-confirmation__full-plan-header { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-md); padding:var(--space-md); border-bottom:1px solid var(--neutral-border); }
.plan-confirmation__full-plan-header h4 { margin:0; color:var(--neutral-text-1); font-size:14px; }
.plan-confirmation__full-plan-header small { display:block; margin-top:var(--space-xs); color:var(--neutral-text-3); word-break:break-all; }
.plan-confirmation__plan-state { display:flex; min-height:120px; align-items:center; justify-content:center; gap:var(--space-md); padding:var(--space-lg); color:var(--neutral-text-2); text-align:center; }
.plan-confirmation__plan-state.is-error { color:var(--arco-danger); }
.plan-confirmation__plan-content { max-height:520px; overflow:auto; padding:var(--space-lg); color:var(--neutral-text-1); }
.plan-confirmation__preview { width:100%; justify-content:flex-start; gap:var(--space-md); padding:var(--space-md); border:1px solid var(--neutral-border); border-radius:8px; background:var(--surface-card, var(--neutral-card)); color:var(--neutral-text-1); text-align:left; cursor:pointer; transition:border-color var(--motion-quick) ease-out,background var(--motion-quick) ease-out; }
.plan-confirmation__preview:hover { border-color:var(--arco-primary); background:var(--surface-highlight, var(--neutral-hover)); }
.plan-confirmation__preview:focus-visible { outline:2px solid var(--arco-primary); outline-offset:3px; }
.plan-confirmation__preview span:nth-child(2) { display:flex; min-width:0; flex:1; flex-direction:column; }
.plan-confirmation__preview small { overflow:hidden; color:var(--neutral-text-3); text-overflow:ellipsis; white-space:nowrap; }
.plan-confirmation__feedback { margin-top:var(--space-md); }
.plan-confirmation__actions { flex-wrap:wrap; gap:var(--space-sm); margin-top:var(--space-lg); }
.plan-confirmation__error { color:var(--arco-danger); font-size:13px; }
.plan-confirmation__feedback-summary { color:var(--neutral-text-2); font-size:13px; white-space:pre-wrap; }
.plan-preview-modal__state { padding:var(--space-3xl); color:var(--neutral-text-2); text-align:center; }
.plan-preview-modal__state.is-error { color:var(--arco-danger); }
.plan-preview-modal__content { max-height:65vh; margin:0; overflow:auto; padding:var(--space-lg); border-radius:8px; background:var(--surface-card, var(--neutral-bg)); color:var(--neutral-text-1); font:13px/1.7 var(--font-family-mono,monospace); white-space:pre-wrap; word-break:break-word; }
@media (max-width:640px) { .plan-confirmation { padding:var(--space-lg); } .plan-confirmation__header { align-items:flex-start; } .plan-confirmation__metrics { grid-template-columns:1fr; } .plan-confirmation__full-plan-header { align-items:stretch; flex-direction:column; } .plan-confirmation__actions :deep(.n-button) { width:100%; } }
@media (prefers-reduced-motion:reduce) { .plan-confirmation__preview { transition:none; } }
@media (prefers-contrast:more) { .plan-confirmation,.plan-confirmation__metrics>div,.plan-confirmation__preview { border-width:2px; } }
</style>
