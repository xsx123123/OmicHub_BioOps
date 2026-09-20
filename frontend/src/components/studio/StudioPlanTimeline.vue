<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { StudioPlanStep } from '@/api/studio'

const props = defineProps<{ steps: StudioPlanStep[] }>()

const isCollapsed = ref(false)
const hasUserToggled = ref(false)
const wasComplete = ref(false)

const completedCount = computed(() => props.steps.filter((step) => step.status === 'done').length)
const totalCount = computed(() => props.steps.length)
const allDone = computed(() => totalCount.value > 0 && completedCount.value === totalCount.value)
const activeStep = computed(() => props.steps.find((step) => step.status === 'in_progress') || props.steps.find((step) => step.status === 'pending'))
const summary = computed(() => {
  if (allDone.value) return `分析计划 · ${completedCount.value}/${totalCount.value} 已完成 ✓`
  return `分析计划 · 已完成 ${completedCount.value}/${totalCount.value} · 当前：${activeStep.value?.title || '等待执行'}`
})

function toggleCollapsed() {
  isCollapsed.value = !isCollapsed.value
  hasUserToggled.value = true
}

watch(allDone, (complete) => {
  if (complete && !wasComplete.value && !hasUserToggled.value) isCollapsed.value = true
  wasComplete.value = complete
}, { immediate: true })

function statusLabel(status: StudioPlanStep['status']) {
  if (status === 'done') return '已完成'
  if (status === 'in_progress') return '进行中'
  return '待执行'
}
</script>

<template>
  <section v-if="steps.length" class="plan-timeline" :class="{ 'is-collapsed': isCollapsed }" aria-label="分析计划">
    <button
      type="button"
      class="timeline-heading"
      :aria-expanded="!isCollapsed"
      aria-controls="analysis-plan-steps"
      @click="toggleCollapsed"
    >
      <span class="timeline-title">分析计划</span>
      <span class="timeline-summary" :title="summary">{{ summary }}</span>
      <span class="progress-chip">{{ completedCount }}/{{ totalCount }}</span>
      <span class="chevron" aria-hidden="true" />
    </button>
    <div class="timeline-content" :class="{ 'is-open': !isCollapsed }">
      <div class="timeline-content-inner">
        <ol id="analysis-plan-steps">
          <li v-for="(step, index) in steps" :key="`${index}-${step.title}`" :class="`is-${step.status}`">
            <span class="timeline-node" aria-hidden="true" />
            <div class="step-copy"><strong>{{ step.title }}</strong><small>{{ statusLabel(step.status) }}</small></div>
          </li>
        </ol>
      </div>
    </div>
  </section>
</template>

<style scoped>
.plan-timeline {
  box-sizing: border-box;
  /* 与待处理条、输入框同宽居中（受 --chat-content-max-width 约束） */
  width: calc(100% - 32px);
  max-width: var(--chat-content-max-width, 860px);
  margin: 0 auto 8px;
  overflow: hidden;
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  background: var(--chat-ai-card, var(--surface-card, var(--neutral-card)));
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));
}
.timeline-heading { display: flex; align-items: center; width: 100%; min-height: 44px; gap: 8px; padding: 8px 12px; border: 0; color: var(--chat-text-primary, var(--neutral-text-1)); background: transparent; font: inherit; text-align: left; cursor: pointer; }
.timeline-heading:hover { background: var(--chat-surface-hover, var(--neutral-hover)); }
.timeline-title { flex: 0 0 auto; font-size: 14px; font-weight: 600; }
.timeline-summary { display: none; min-width: 0; overflow: hidden; color: var(--chat-text-secondary, var(--neutral-text-2)); font-size: 12px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.is-collapsed .timeline-title { display: none; }
.is-collapsed .timeline-summary { display: block; }
.progress-chip { flex: 0 0 auto; margin-left: auto; padding: 2px 8px; border-radius: 999px; color: var(--chat-accent, var(--arco-primary)); background: color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 12%, transparent); font-size: 12px; line-height: 18px; font-variant-numeric: tabular-nums; }
.chevron { flex: 0 0 auto; width: 7px; height: 7px; margin: 0 3px 3px 4px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(45deg); transition: transform 250ms ease; }
.is-collapsed .chevron { transform: rotate(-45deg); margin-bottom: -3px; }
.timeline-content { display: grid; grid-template-rows: 1fr; transition: grid-template-rows 250ms ease; }
.timeline-content:not(.is-open) { grid-template-rows: 0fr; }
.timeline-content-inner { min-height: 0; overflow: hidden; }
.timeline-content ol { list-style: none; margin: 0; padding: 0 12px 12px; display: flex; flex-direction: column; gap: 0; }
li { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 8px; padding: 8px 0; }
li::before { content: ''; position: absolute; left: 5px; top: 20px; bottom: -8px; width: 2px; background: var(--chat-border, var(--neutral-border)); }
li:last-child::before { display: none; }
.timeline-node { position: relative; z-index: 1; width: 11px; height: 11px; margin-top: 3px; border: 2px solid var(--chat-text-muted, var(--neutral-text-3)); border-radius: 50%; background: var(--chat-ai-card, var(--surface-card, var(--neutral-card))); box-sizing: border-box; }
li.is-in_progress .timeline-node { border-color: var(--chat-accent, var(--arco-primary)); box-shadow: 0 0 0 4px color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 14%, transparent); animation: plan-node-pulse 1.2s ease-in-out infinite; }
li.is-done .timeline-node { border-color: var(--chat-accent, var(--arco-primary)); background: var(--chat-accent, var(--arco-primary)); }
.step-copy { display: flex; align-items: baseline; justify-content: space-between; min-width: 0; gap: 10px; }
li strong { min-width: 0; overflow: hidden; color: var(--chat-text-secondary, var(--neutral-text-2)); font-size: 13px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
li.is-in_progress strong { color: var(--chat-text-primary, var(--neutral-text-1)); font-weight: 500; }
li small { flex: 0 0 auto; color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 12px; font-weight: 400; }
li.is-in_progress small { color: var(--chat-accent, var(--arco-primary)); font-weight: 500; }
li.is-done small { color: var(--chat-accent, var(--arco-primary)); }
@keyframes plan-node-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
@media (prefers-reduced-motion: reduce) { .chevron, .timeline-content { transition: none; } li.is-in_progress .timeline-node { animation: none; box-shadow: none; } }
</style>
