<script setup lang="ts">
/**
 * 建议追问卡片（Suggested Follow-ups）。
 * 渲染在 assistant 回复气泡/产物卡片下方的竖向可点击卡片列表：
 * - action='send'：emit('send', prompt)，由页面侧走与输入框相同的发送 action，
 *   行尾显示 ↵ Enter 键位提示，示意"点击即发送"；
 * - action='prefill'：emit('prefill', prompt)，由页面侧写入输入框并聚焦，
 *   行尾显示 ✎ 提示"填入输入框待补充"。
 * suggestions 为空时不渲染任何占位；组件独立挂载，出问题一行 v-if 即可隐藏。
 * 卡片整行展示完整 label（不截断），完整 prompt 同时入 title/aria-label；
 * 可访问性：每个条目为原生 button（Tab 聚焦、Enter/Space 触发）；
 * 动画仅 transform/opacity 且 ≤200ms，尊重 prefers-reduced-motion。
 */
import type { SuggestedFollowUp } from '@/utils/nextStepSuggestions'

interface Props {
  suggestions: SuggestedFollowUp[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
  send: [prompt: string]
  prefill: [prompt: string]
}>()

function handleClick(item: SuggestedFollowUp) {
  if (item.action === 'prefill') {
    emit('prefill', item.prompt)
  } else {
    emit('send', item.prompt)
  }
}

function cardAriaLabel(item: SuggestedFollowUp): string {
  return item.action === 'prefill'
    ? `建议追问（填入输入框待补充）：${item.prompt}`
    : `建议追问（直接发送）：${item.prompt}`
}
</script>

<template>
  <div v-if="props.suggestions.length" class="suggestion-cards" role="group" aria-label="建议追问">
    <button
      v-for="(item, index) in props.suggestions"
      :key="index"
      type="button"
      class="suggestion-card"
      :class="{ 'is-prefill': item.action === 'prefill' }"
      :title="item.prompt"
      :aria-label="cardAriaLabel(item)"
      @click="handleClick(item)"
    >
      <span class="suggestion-card__label">{{ item.label }}</span>
      <span
        v-if="item.action === 'prefill'"
        class="suggestion-card__key"
        aria-hidden="true"
        title="填入输入框待补充"
      >✎</span>
      <span v-else class="suggestion-card__key" aria-hidden="true"><span class="suggestion-card__enter">↵</span> Enter</span>
    </button>
  </div>
</template>

<style scoped lang="scss">
.suggestion-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  animation: suggestion-cards-in 0.18s ease-out both;
}

.suggestion-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.12));
  border-radius: 10px;
  background: var(--bg-card, #fff);
  color: var(--chat-text-primary, var(--n-text-color));
  font-size: 13px;
  line-height: 1.6;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.16s ease, border-color 0.16s ease;
}

.suggestion-card:hover {
  background: var(--brand-primary-light, #eef1ff);
  border-color: var(--stardust-blue, #2e5bff);
}

.suggestion-card:focus-visible {
  outline: 2px solid var(--stardust-blue, #2e5bff);
  outline-offset: 1px;
}

/* 整行展示完整文案，不截断 */
.suggestion-card__label {
  flex: 1 1 auto;
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

/* 行尾键位提示：示意"点击即发送/填入"，kbd 风格 */
.suggestion-card__key {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border: 1px solid var(--stardust-border-soft, rgba(46, 91, 255, 0.16));
  border-radius: 6px;
  background: var(--chat-surface, rgba(128, 128, 128, 0.06));
  color: var(--chat-text-secondary, rgba(128, 128, 128, 0.9));
  font-size: 11px;
  line-height: 1.4;
  white-space: nowrap;
}

.suggestion-card__enter {
  font-size: 12px;
}

.suggestion-card:hover .suggestion-card__key {
  border-color: var(--stardust-blue, #2e5bff);
  color: var(--stardust-blue, #2e5bff);
}

@keyframes suggestion-cards-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .suggestion-cards {
    animation: none;
  }

  .suggestion-card {
    transition: none;
  }
}
</style>
