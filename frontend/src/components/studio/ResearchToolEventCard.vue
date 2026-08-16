<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCall } from '@/components/ai-chat/types'
import { researchToolMeta, summarizeToolResult } from '@/utils/studioPresentation'

const props = defineProps<{ tool: ToolCall }>()
const meta = computed(() => researchToolMeta(props.tool))
const statusLabel = computed(() => ({
  pending: '等待中',
  running: '执行中',
  awaiting_approval: '待确认',
  success: '已完成',
  error: '失败',
  timed_out: '超时·已降级',
}[props.tool.status]))
</script>

<template>
  <section class="research-tool-event" :class="`is-${tool.status}`">
    <div class="event-summary">
      <span class="event-icon" aria-hidden="true">{{ meta.icon }}</span>
      <div class="event-title"><strong>{{ meta.label }}</strong><span>{{ meta.duration }}</span></div>
      <span class="event-status">{{ statusLabel }}</span>
    </div>
    <details>
      <summary>技术细节</summary>
      <dl>
        <div><dt>工具</dt><dd>{{ tool.name }}</dd></div>
        <div v-if="tool.mcpServer"><dt>来源</dt><dd>{{ tool.mcpServer }}</dd></div>
        <div><dt>参数</dt><dd><pre>{{ JSON.stringify(tool.arguments, null, 2) }}</pre></dd></div>
        <div><dt>结果</dt><dd>{{ summarizeToolResult(tool.result ?? tool.output) }}</dd></div>
      </dl>
    </details>
  </section>
</template>

<style scoped>
.research-tool-event { margin: 8px 0; padding: 11px 13px; border: 1px solid var(--border-subtle, var(--chat-border)); border-radius: 13px; background: var(--surface-card, var(--chat-surface)); }
.event-summary { display: flex; align-items: center; gap: 10px; }
.event-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 9px; background: var(--surface-highlight, var(--chat-surface-hover)); color: var(--brand-primary, var(--stardust-blue)); font-weight: 700; }
.event-title { display: flex; min-width: 0; flex: 1; flex-direction: column; }
.event-title strong { color: var(--text-primary, var(--chat-text-primary)); font-size: 12px; }
.event-title span { color: var(--text-tertiary, var(--chat-text-muted)); font-size: 10px; }
.event-status { padding: 3px 8px; border-radius: 999px; background: var(--surface-highlight, var(--chat-surface-hover)); color: var(--text-secondary, var(--chat-text-secondary)); font-size: 10px; white-space: nowrap; }
.is-success .event-status { color: var(--success-color, var(--brand-primary)); }
.is-error .event-status { color: var(--error-color, var(--arco-danger)); }
details { margin-top: 8px; border-top: 1px solid var(--border-subtle, var(--chat-border)); padding-top: 7px; }
summary { cursor: pointer; color: var(--text-tertiary, var(--chat-text-muted)); font-size: 11px; }
dl { display: grid; gap: 6px; margin: 8px 0 0; }
dl div { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; }
dt { color: var(--text-tertiary, var(--chat-text-muted)); font-size: 10px; }
dd { min-width: 0; margin: 0; color: var(--text-secondary, var(--chat-text-secondary)); font-size: 11px; overflow-wrap: anywhere; }
pre { max-height: 160px; margin: 0; overflow: auto; white-space: pre-wrap; font: inherit; }
</style>
