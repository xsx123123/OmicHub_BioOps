<script setup lang="ts">
import { computed } from 'vue'
import type { GoalEvent } from '@/api/goals'

const props = withDefaults(defineProps<{ events?: GoalEvent[] }>(), { events: () => [] })

const recentEvents = computed(() => props.events.slice(-5).reverse())

function labelFor(event: GoalEvent): string {
  const labels: Record<string, string> = {
    created: '已创建目标',
    continued: '开始下一轮推进',
    step_finished: '完成一个执行步骤',
    waiting_user: '等待你的补充',
    paused: '已暂停',
    completed: '目标已完成',
    blocked: '目标已阻塞',
    cancelled: '已取消',
    budget_exhausted: '已到达轮次预算',
    token_budget_exhausted: '已到达 Token 预算',
    deadline_exhausted: '已到达截止时间',
  }
  return labels[event.event_type] || event.event_type.replace(/_/g, ' ')
}
</script>

<template>
  <ol v-if="recentEvents.length" class="goal-timeline" aria-label="目标执行事件">
    <li v-for="event in recentEvents" :key="event.id" class="goal-timeline__item">
      <span class="goal-timeline__marker" aria-hidden="true" />
      <span class="goal-timeline__label">{{ labelFor(event) }}</span>
      <time class="goal-timeline__time">{{ new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</time>
    </li>
  </ol>
</template>

<style scoped>
.goal-timeline { display: grid; gap: var(--space-xs, 4px); margin: 0; padding: 0; list-style: none; }
.goal-timeline__item { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: var(--space-sm, 8px); color: var(--neutral-text-2, var(--text-secondary)); font-size: 12px; line-height: 18px; }
.goal-timeline__marker { width: 6px; height: 6px; border-radius: 999px; background: var(--brand-primary, #4c6fff); box-shadow: 0 0 0 3px var(--brand-primary-light, rgba(76, 111, 255, .12)); }
.goal-timeline__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.goal-timeline__time { color: var(--neutral-text-3, var(--text-tertiary)); white-space: nowrap; }
</style>
