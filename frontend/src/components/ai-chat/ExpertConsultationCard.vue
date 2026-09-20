<script setup lang="ts">
import { NButton } from 'naive-ui'

const props = defineProps<{
  experts: Array<{ agent_id: string; name: string; opinion: string }>
  consultationId?: string
  consultationSummary?: string
  caseAvailable?: boolean
}>()

const emit = defineEmits<{ createCase: [summary: string, consultationId?: string] }>()
</script>

<template>
  <details v-if="experts.length" class="expert-consultation-card">
    <summary>👥 已征询 {{ experts.length }} 位专家意见</summary>
    <div v-for="expert in experts" :key="expert.agent_id" class="expert-opinion">
      <strong>{{ expert.name }}</strong>
      <p>{{ expert.opinion }}</p>
    </div>
    <div v-if="props.consultationSummary" class="consultation-actions">
      <NButton size="tiny" type="primary" :disabled="props.caseAvailable === false" @click="emit('createCase', props.consultationSummary, props.consultationId)">
        基于此创建协作 Case
      </NButton>
      <span v-if="props.caseAvailable === false" class="case-unavailable">协作 Case 尚未接通，请联系管理员启用 AgentTeams。</span>
    </div>
  </details>
</template>

<style scoped>
.expert-consultation-card { margin: 10px 0; padding: 10px 12px; border: 1px solid #b9d8ff; border-radius: 8px; background: #f5faff; color: #36516e; font-size: 13px; }
/* 深色模式：复用星尘浅底变量，文字用次级文字色 */
:root[data-theme="dark"] .expert-consultation-card { border-color: var(--stardust-border-soft); background: var(--stardust-bg-soft); color: var(--text-secondary); }
summary { cursor: pointer; font-weight: 600; }
.expert-opinion { padding-top: 8px; }
.expert-opinion p { margin: 4px 0 0; white-space: pre-wrap; }
.consultation-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; align-items: center; margin-top: 10px; }
.case-unavailable { color: #a56700; font-size: 12px; }
</style>
