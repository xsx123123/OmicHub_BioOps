<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTag } from 'naive-ui'
import { FlagOutline, PauseOutline, PlayOutline, CloseOutline } from '@vicons/ionicons5'
import GoalTimeline from './GoalTimeline.vue'
import type { GoalEvent, GoalRuntimeGoal } from '@/api/goals'

const props = withDefaults(defineProps<{
  goal: GoalRuntimeGoal
  events?: GoalEvent[]
  loading?: boolean
  error?: string
}>(), {
  events: () => [],
  loading: false,
  error: '',
})

const emit = defineEmits<{ pause: []; resume: []; cancel: []; refresh: [] }>()

const statusMeta = computed(() => ({
  in_progress: { label: '执行中', type: 'info' as const },
  waiting_user: { label: '等待你的补充', type: 'warning' as const },
  waiting_external: { label: '等待外部结果', type: 'warning' as const },
  paused: { label: '已暂停', type: 'default' as const },
  completed: { label: '已完成', type: 'success' as const },
  blocked: { label: '已阻塞', type: 'error' as const },
  cancelled: { label: '已取消', type: 'default' as const },
  failed: { label: '失败', type: 'error' as const },
  draft: { label: '草稿', type: 'default' as const },
}[props.goal.status]))

const canPause = computed(() => props.goal.status === 'in_progress')
const canResume = computed(() => ['paused', 'waiting_user'].includes(props.goal.status))
const budgetLabel = computed(() => props.goal.token_budget === null
  ? `第 ${props.goal.turn_count} / ${props.goal.max_turns} 轮`
  : `第 ${props.goal.turn_count} / ${props.goal.max_turns} 轮 · ${props.goal.tokens_used} / ${props.goal.token_budget} Token`)
</script>

<template>
  <section class="goal-status-card" aria-live="polite" aria-label="持久目标状态">
    <div class="goal-status-card__header">
      <div class="goal-status-card__title">
        <n-icon size="18"><FlagOutline /></n-icon>
        <strong>持久目标</strong>
        <n-tag size="small" round :type="statusMeta.type">{{ statusMeta.label }}</n-tag>
      </div>
      <div class="goal-status-card__actions">
        <n-button v-if="canPause" size="tiny" secondary :loading="loading" @click="emit('pause')">
          <template #icon><n-icon><PauseOutline /></n-icon></template>暂停
        </n-button>
        <n-button v-if="canResume" size="tiny" secondary :loading="loading" @click="emit('resume')">
          <template #icon><n-icon><PlayOutline /></n-icon></template>继续
        </n-button>
        <n-button size="tiny" tertiary type="error" :loading="loading" @click="emit('cancel')">
          <template #icon><n-icon><CloseOutline /></n-icon></template>取消
        </n-button>
      </div>
    </div>
    <p class="goal-status-card__objective">{{ goal.objective }}</p>
    <div class="goal-status-card__progress">
      <span>{{ budgetLabel }}</span>
      <button type="button" class="goal-status-card__refresh focus-ring" @click="emit('refresh')">刷新状态</button>
    </div>
    <p v-if="error" class="goal-status-card__error" role="status">{{ error }}</p>
    <GoalTimeline :events="events" />
  </section>
</template>

<style scoped>
.goal-status-card { display: grid; gap: var(--space-sm, 8px); padding: var(--space-md, 16px); border: 1px solid var(--neutral-border, var(--border-default)); border-left: 3px solid var(--brand-primary, #4c6fff); border-radius: var(--radius-card, 12px); background: var(--neutral-card, var(--bg-card)); box-shadow: var(--shadow-soft, var(--shadow-card)); }
.goal-status-card__header, .goal-status-card__title, .goal-status-card__actions, .goal-status-card__progress { display: flex; align-items: center; gap: var(--space-sm, 8px); }
.goal-status-card__header { justify-content: space-between; }
.goal-status-card__title { min-width: 0; color: var(--neutral-text-1, var(--text-primary)); }
.goal-status-card__actions { flex-wrap: wrap; justify-content: flex-end; }
.goal-status-card__objective { margin: 0; color: var(--neutral-text-2, var(--text-secondary)); font-size: 13px; line-height: 20px; }
.goal-status-card__progress { justify-content: space-between; color: var(--neutral-text-3, var(--text-tertiary)); font-size: 12px; }
.goal-status-card__refresh { padding: 0; border: 0; color: var(--brand-primary, #4c6fff); background: transparent; cursor: pointer; font: inherit; }
.goal-status-card__error { margin: 0; color: var(--arco-danger, #f53f3f); font-size: 12px; }
@media (max-width: 560px) { .goal-status-card__header { align-items: flex-start; flex-direction: column; } .goal-status-card__actions { justify-content: flex-start; } }
</style>
