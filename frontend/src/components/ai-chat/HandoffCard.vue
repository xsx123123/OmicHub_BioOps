<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'
import type { ToolCall } from './types'

const props = defineProps<{ tool: ToolCall }>()

const handoff = computed<Record<string, unknown>>(() => {
  const result = props.tool.result
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    const payload = result as Record<string, unknown>
    const nested = payload.handoff
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) return nested as Record<string, unknown>
  }
  return {}
})

function text(key: string): string {
  const value = handoff.value[key]
  return typeof value === 'string' ? value : ''
}

function list(key: string): string[] {
  const value = handoff.value[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}
</script>

<template>
  <details class="handoff-card">
    <summary>
      <span class="handoff-icon">🔀</span>
      <span>{{ text('source_agent_name') || text('source_agent_id') }} → {{ text('target_agent_name') || text('target_agent_id') }}</span>
      <NTag size="small" type="default">第 {{ handoff.hop_index || 1 }} 次转交</NTag>
    </summary>
    <div class="handoff-detail">
      <p><strong>转交原因：</strong>{{ text('reason') }}</p>
      <p><strong>后续诉求：</strong>{{ text('user_intent') }}</p>
      <p><strong>已完成：</strong>{{ text('handoff_summary') }}</p>
      <p v-if="list('artifacts').length"><strong>相关产物：</strong>{{ list('artifacts').join('、') }}</p>
      <p v-if="list('constraints').length"><strong>约束：</strong>{{ list('constraints').join('；') }}</p>
    </div>
  </details>
</template>

<style scoped>
.handoff-card { margin: 10px 0; padding: 8px 10px; border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; background: var(--card-color, #f8fafc); color: var(--text-color-2, #64748b); font-size: 12px; }
.handoff-card summary { display: flex; align-items: center; gap: 6px; cursor: pointer; list-style: none; }
.handoff-card summary::-webkit-details-marker { display: none; }
.handoff-icon { font-size: 14px; }
.handoff-detail { padding: 8px 2px 0; line-height: 1.6; }
.handoff-detail p { margin: 3px 0; word-break: break-word; }
</style>
