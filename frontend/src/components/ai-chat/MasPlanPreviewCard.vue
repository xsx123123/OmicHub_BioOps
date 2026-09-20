<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NTag } from 'naive-ui'
import { masApi, type MasPlan, type MasRunCreateRequest } from '@/api/mas'
import MasRunProgressCard from './MasRunProgressCard.vue'

const props = defineProps<{
  plan: MasPlan
  contextSummary?: Record<string, unknown>
  sessionId?: string
  workspaceId?: string
}>()

const submitting = ref(false)
const error = ref('')
const runId = ref('')

const nodeCount = computed(() => props.plan.nodes.length)

async function approvePlan(): Promise<void> {
  if (submitting.value || runId.value) return
  submitting.value = true
  error.value = ''
  try {
    const request: MasRunCreateRequest = {
      plan: props.plan,
      context_summary: props.contextSummary || {},
      ...(props.sessionId ? { session_id: props.sessionId } : {}),
      ...(props.workspaceId ? { workspace_id: props.workspaceId } : {}),
    }
    const run = await masApi.createRun(request)
    await masApi.approveRun(run.id)
    runId.value = run.id
  } catch {
    error.value = '计划确认失败：请检查分析信息或稍后重试。'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="mas-plan-preview-card">
    <header>
      <div>
        <strong>多智能体分析计划</strong>
        <p>{{ plan.title }}</p>
      </div>
      <NTag type="warning" size="small">待确认</NTag>
    </header>
    <p class="notice">确认前不会下载数据、创建 Celery 执行任务或启动分析。</p>
    <ol class="nodes">
      <li v-for="node in plan.nodes" :key="node.key">
        <span class="node-key">{{ node.key }}</span>
        <span>{{ node.intent }}</span>
        <small>{{ node.agent_id }}<template v-if="node.depends_on?.length"> · 依赖 {{ node.depends_on.join(', ') }}</template></small>
      </li>
    </ol>
    <footer>
      <span>{{ nodeCount }} 个节点</span>
      <NButton type="primary" size="small" :loading="submitting" :disabled="!!runId" @click="approvePlan">
        {{ runId ? '计划已确认' : '确认并开始执行' }}
      </NButton>
    </footer>
    <p v-if="error" class="error">{{ error }}</p>
    <MasRunProgressCard v-if="runId" :run-id="runId" />
  </section>
</template>

<style scoped>
.mas-plan-preview-card { margin-top: 12px; padding: 14px; border: 1px solid #d8c8ff; border-radius: 10px; background: #faf8ff; }
/* 深色模式：紫色调浅底，跟随 stardust 紫变量 */
:root[data-theme="dark"] .mas-plan-preview-card { border-color: color-mix(in srgb, var(--stardust-purple, #9a7bff) 32%, transparent); background: color-mix(in srgb, var(--stardust-purple, #9a7bff) 12%, transparent); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
header p { margin: 4px 0 0; color: var(--chat-text-secondary, #666); font-size: 13px; }
.notice { margin: 12px 0; color: var(--chat-text-secondary, #666); font-size: 12px; }
.nodes { margin: 0; padding-left: 20px; }
.nodes li { display: grid; grid-template-columns: minmax(90px, 1fr) minmax(100px, 2fr); gap: 4px 12px; padding: 6px 0; font-size: 13px; }
.node-key { font-weight: 600; }
.nodes small { grid-column: 1 / -1; color: var(--chat-text-muted, #999); }
footer { margin-top: 12px; color: var(--chat-text-muted, #999); font-size: 12px; }
.error { margin: 10px 0 0; color: #d03050; font-size: 12px; }
</style>
