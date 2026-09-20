<script setup lang="ts">
/**
 * RoomRouteTransitionCard — room.route_transition 事件的咨询分诊转场卡。
 *
 * 纯咨询问题（CHAT 意图）由经理 LLM 分诊给领域专家直答时，在时间线上展示
 * 「{from_name} → {target_name}」转场条 + 分诊原因 + 置信度百分比。
 * 视觉效果参考 ai-chat 侧 RouteTransitionCard（淡入动画、左侧强调条），
 * 配色/间距遵循 agent-teams 目录既有卡片约定（--chat-* 变量体系，同 RouteDecisionCard）。
 * 与 RouteDecisionCard（room.route_decision，流程路径决策）语义隔离，不复用。
 */
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { SwapHorizontalOutline } from '@vicons/ionicons5'
import type { RoomRouteTransition } from '@/utils/agentTeamsRoom'

const props = defineProps<{ transition: RoomRouteTransition }>()

const confidencePercent = computed(() => {
  const value = Number(props.transition.confidence)
  if (!Number.isFinite(value)) return null
  return Math.round(Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)))
})
</script>

<template>
  <Transition name="room-route-transition" appear>
    <aside
      class="room-route-transition"
      role="status"
      aria-live="polite"
      aria-label="咨询已分诊给领域专家"
    >
      <n-icon size="14" class="rrt-icon" aria-hidden="true"><SwapHorizontalOutline /></n-icon>
      <div class="rrt-main">
        <div class="rrt-path">
          <span class="rrt-label">咨询分诊</span>
          <span class="rrt-from">{{ transition.fromName || '经理' }}</span>
          <span class="rrt-arrow" aria-hidden="true">→</span>
          <strong class="rrt-target">{{ transition.targetName }}</strong>
          <span v-if="confidencePercent !== null" class="rrt-confidence">置信度 {{ confidencePercent }}%</span>
        </div>
        <p v-if="transition.reason" class="rrt-reason">{{ transition.reason }}</p>
      </div>
    </aside>
  </Transition>
</template>

<style scoped lang="scss">
.room-route-transition {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  margin-top: 10px;
  padding: 8px 12px;
  overflow: hidden;
  background: var(--chat-ai-card, var(--neutral-card));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  box-shadow: var(--chat-shadow-sm, var(--shadow-card));

  &::before {
    position: absolute;
    inset: 0 auto 0 0;
    width: 2px;
    background: color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 68%, var(--neutral-border));
    content: '';
  }
}

.rrt-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--chat-accent, var(--arco-primary));
}

.rrt-main {
  min-width: 0;
}

.rrt-path {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  font-size: 12px;
}

.rrt-label {
  flex-shrink: 0;
  padding: 2px 6px;
  color: var(--chat-accent, var(--arco-primary));
  background: color-mix(in srgb, var(--chat-accent, var(--arco-primary)) 8%, transparent);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 650;
}

.rrt-from,
.rrt-arrow {
  color: var(--chat-text-muted, var(--neutral-text-3));
}

.rrt-target {
  min-width: 0;
  overflow: hidden;
  color: var(--chat-accent, var(--arco-primary));
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rrt-confidence {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--chat-text-muted, var(--neutral-text-3));
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.rrt-reason {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--chat-text-secondary, var(--neutral-text-2));
  font-size: 11px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.room-route-transition-enter-active,
.room-route-transition-leave-active {
  transition: opacity var(--motion-standard, 220ms) ease-out, transform var(--motion-standard, 220ms) ease-out;
}

.room-route-transition-enter-from,
.room-route-transition-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (max-width: 680px) {
  .rrt-confidence {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .room-route-transition-enter-active,
  .room-route-transition-leave-active {
    transition: none;
  }
  .room-route-transition-enter-from,
  .room-route-transition-leave-to {
    transform: none;
  }
}
</style>
