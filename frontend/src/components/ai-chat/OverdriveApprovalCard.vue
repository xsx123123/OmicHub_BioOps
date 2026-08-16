<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NInput, NTag, useMessage } from 'naive-ui'
import { CheckmarkOutline, ShieldCheckmarkOutline, ReturnUpBackOutline } from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { OverdriveApproval } from './types'

const props = defineProps<{ approval: OverdriveApproval }>()

const store = useAgentHubStore()
const message = useMessage()
const rejecting = ref(false)
const reason = ref('')
const submitting = ref(false)

const statusMeta = computed(() => ({
  pending: { label: '等待你的审批', type: 'warning' as const },
  executing: { label: '正在执行', type: 'info' as const },
  completed: { label: '已执行', type: 'success' as const },
  rejected: { label: '已拒绝', type: 'default' as const },
  failed: { label: '执行失败', type: 'error' as const },
}[props.approval.status]))
const pending = computed(() => props.approval.status === 'pending')
const resultText = computed(() => {
  const payload = props.approval.result?.llm_payload
  if (payload && typeof payload === 'object') {
    const data = payload as Record<string, unknown>
    return String(data.summary || data.message || data.error || '')
  }
  return props.approval.error || props.approval.reason || ''
})

async function approve() {
  if (!pending.value || submitting.value) return
  submitting.value = true
  try {
    await store.approveOverdriveApproval(props.approval.approvalId)
    message.success('已批准，主会话正在恢复执行原始工具调用')
  } catch {
    message.error('批准失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

async function reject() {
  if (!pending.value || submitting.value) return
  submitting.value = true
  try {
    await store.rejectOverdriveApproval(props.approval.approvalId, reason.value.trim() || undefined)
    message.success('已拒绝此工具调用')
  } catch {
    message.error('拒绝失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="overdrive-approval" :class="`is-${approval.status}`" aria-live="polite">
    <header class="overdrive-approval__header">
      <span class="overdrive-approval__title">
        <n-icon size="16" aria-hidden="true"><ShieldCheckmarkOutline /></n-icon>
        专家请求执行工具
      </span>
      <n-tag size="small" round :bordered="false" :type="statusMeta.type">{{ statusMeta.label }}</n-tag>
    </header>
    <p class="overdrive-approval__tool">{{ approval.toolName }}</p>
    <pre class="overdrive-approval__args">{{ JSON.stringify(approval.arguments, null, 2) }}</pre>
    <p v-if="resultText" class="overdrive-approval__result">{{ resultText }}</p>
    <template v-if="pending">
      <n-input
        v-if="rejecting"
        v-model:value="reason"
        size="small"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 4 }"
        placeholder="可选：说明拒绝原因"
        aria-label="拒绝超频工具调用的原因"
      />
      <div class="overdrive-approval__actions">
        <n-button type="primary" size="small" :loading="submitting" @click="approve">
          <template #icon><n-icon><CheckmarkOutline /></n-icon></template>
          批准并执行
        </n-button>
        <n-button size="small" :disabled="submitting" @click="rejecting = !rejecting">
          <template #icon><n-icon><ReturnUpBackOutline /></n-icon></template>
          拒绝
        </n-button>
        <n-button v-if="rejecting" size="small" type="warning" :loading="submitting" @click="reject">确认拒绝</n-button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.overdrive-approval {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid var(--border-color, var(--n-border-color));
  border-left: 3px solid var(--warning-color, #f0a020);
  border-radius: 10px;
  background: var(--card-color, var(--n-color));
}
.overdrive-approval.is-completed { border-left-color: var(--success-color, #18a058); }
.overdrive-approval.is-failed { border-left-color: var(--error-color, #d03050); }
.overdrive-approval__header, .overdrive-approval__actions { display: flex; align-items: center; gap: 8px; }
.overdrive-approval__header { justify-content: space-between; }
.overdrive-approval__title { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; color: var(--text-color-1, var(--n-text-color)); }
.overdrive-approval__tool { margin: 8px 0 4px; font-family: var(--font-family-mono, monospace); font-size: 13px; }
.overdrive-approval__args { max-height: 160px; margin: 0 0 10px; overflow: auto; padding: 8px; border-radius: 6px; background: var(--code-color, rgba(128, 128, 128, .08)); font-size: 12px; white-space: pre-wrap; word-break: break-word; }
.overdrive-approval__result { margin: 0 0 10px; color: var(--text-color-2, var(--n-text-color)); font-size: 13px; white-space: pre-wrap; }
.overdrive-approval__actions { margin-top: 10px; flex-wrap: wrap; }
@media (prefers-reduced-motion: reduce) { .overdrive-approval { transition: none; } }
</style>
