<script setup lang="ts">
import type { StudioPlanStep } from '@/api/studio'

defineProps<{ steps: StudioPlanStep[] }>()

function statusLabel(status: StudioPlanStep['status']) {
  if (status === 'done') return '已完成'
  if (status === 'in_progress') return '进行中'
  return '待执行'
}
</script>

<template>
  <section v-if="steps.length" class="plan-timeline" aria-label="分析计划">
    <div class="timeline-heading"><span>分析计划</span><small>{{ steps.length }} 个步骤</small></div>
    <ol>
      <li v-for="(step, index) in steps" :key="`${index}-${step.title}`" :class="`is-${step.status}`">
        <span class="timeline-node" aria-hidden="true" />
        <div><strong>{{ step.title }}</strong><small>{{ statusLabel(step.status) }}</small></div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.plan-timeline { box-sizing: border-box; margin: 0 0 12px; width: 100%; padding: 14px 16px; border: 1px solid var(--border-subtle, var(--chat-border)); border-radius: 14px; background: var(--surface-card, var(--chat-surface)); }
.timeline-heading { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; color: var(--text-primary, var(--chat-text-primary)); font-size: 13px; font-weight: 650; }
.timeline-heading small, li small { color: var(--text-tertiary, var(--chat-text-muted)); font-size: 11px; font-weight: 400; }
ol { list-style: none; margin: 0; padding: 0; }
li { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px; padding-bottom: 12px; }
li:last-child { padding-bottom: 0; }
li::before { content: ''; position: absolute; left: 5px; top: 12px; bottom: 0; width: 1px; background: var(--border-subtle, var(--chat-border)); }
li:last-child::before { display: none; }
.timeline-node { position: relative; z-index: 1; width: 11px; height: 11px; margin-top: 3px; border: 2px solid var(--border-strong, var(--chat-border)); border-radius: 50%; background: var(--surface-card, var(--chat-surface)); box-sizing: border-box; }
li.is-in_progress .timeline-node { border-color: var(--brand-primary, var(--stardust-blue)); box-shadow: 0 0 0 4px var(--brand-primary-light, var(--chat-surface-hover)); }
li.is-done .timeline-node { border-color: var(--success-color, var(--brand-primary)); background: var(--success-color, var(--brand-primary)); }
li div { display: flex; justify-content: space-between; gap: 10px; }
li strong { color: var(--text-secondary, var(--chat-text-secondary)); font-size: 12px; font-weight: 550; }
@media (prefers-reduced-motion: reduce) { .timeline-node { box-shadow: none !important; } }
</style>
