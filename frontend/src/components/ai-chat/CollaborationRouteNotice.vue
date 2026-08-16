<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NTag } from 'naive-ui'
import type { CollaborationRouteInfo } from './types'

const props = defineProps<{ route: CollaborationRouteInfo }>()
const emit = defineEmits<{ correct: [route: CollaborationRouteInfo] }>()

const isDirectAnswer = computed(() => (
  props.route.intent === 'chat'
  && props.route.available
  && !props.route.degraded
))

const tagType = computed(() => {
  if (props.route.degraded) return 'warning'
  if (!props.route.available) return 'error'
  return 'info'
})

const stateText = computed(() => {
  if (props.route.degraded) return '当前不可用'
  if (!props.route.available) return '需要澄清'
  return '已选择'
})

const displayReason = computed(() => {
  if (!props.route.available) return props.route.message
  if (props.route.intent === 'chat' && /缺乏上下文|补全上下文|需要.*追问/.test(props.route.reason)) {
    return '当前助手将直接处理你的问题。'
  }
  return props.route.reason
})
</script>

<template>
  <div v-if="isDirectAnswer" class="direct-response-notice" role="status" aria-live="polite">
    <span class="direct-response-notice__label">由通用助手直接回复</span>
  </div>
  <details
    v-else
    class="collaboration-route-notice"
    :class="{ 'is-degraded': route.degraded, 'is-blocked': !route.available }"
    aria-live="polite"
  >
    <summary class="notice-summary">
      <div class="notice-heading">
        <strong>{{ route.label }}</strong>
        <NTag size="small" :type="tagType" :bordered="false">{{ stateText }}</NTag>
      </div>
      <span class="notice-reason">{{ displayReason }}</span>
    </summary>
    <div class="notice-detail">
      <p>{{ displayReason }}</p>
      <NButton quaternary size="tiny" @click="emit('correct', route)">走错了？</NButton>
    </div>
  </details>
</template>

<style scoped>
.direct-response-notice {
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 1120px;
  min-height: 24px;
  margin: 0 0 var(--space-md, 12px);
  padding: 6px 12px;
  border: 1px solid var(--chat-border);
  border-left: 3px solid var(--primary-color, #6366f1);
  border-radius: 10px;
  background: var(--chat-bg);
  color: var(--chat-text-secondary);
  font-size: 12px;
  line-height: 1.5;
  box-sizing: border-box;
}

.direct-response-notice::before {
  width: 5px;
  height: 5px;
  margin-right: 7px;
  background: var(--brand-primary);
  border-radius: 50%;
  content: '';
}

.direct-response-notice__label { white-space: nowrap; }

.collaboration-route-notice {
  width: 100%;
  max-width: 1120px;
  margin: 0 0 var(--space-md, 12px);
  padding: 10px 12px;
  border: 1px solid var(--chat-border);
  border-left: 3px solid var(--primary-color, #6366f1);
  border-radius: 10px;
  background: var(--chat-bg);
  box-sizing: border-box;
}
.collaboration-route-notice.is-degraded { border-left-color: var(--warning-color, #d97706); }
.collaboration-route-notice.is-blocked { border-left-color: var(--error-color, #dc2626); }
.notice-summary { display: flex; align-items: center; gap: 10px; cursor: pointer; list-style: none; }
.notice-summary::-webkit-details-marker { display: none; }
.notice-heading { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; white-space: nowrap; }
.notice-heading strong { color: var(--chat-text-primary); font-size: 13px; white-space: nowrap; }
.notice-reason { flex: 1 1 auto; min-width: 0; overflow: hidden; color: var(--chat-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.notice-detail { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-top: 8px; }
p { margin: 0; color: var(--chat-text-secondary); font-size: 12px; line-height: 1.5; }
@media (max-width: 640px) { .notice-summary, .notice-detail { align-items: flex-start; flex-direction: column; gap: 6px; } .notice-reason { white-space: normal; } }
</style>
