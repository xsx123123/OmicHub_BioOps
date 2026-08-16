<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

export type AiLoadingType = 'auto' | 'dots' | 'shimmer' | 'pulse' | 'typewriter'

interface Props {
  type?: AiLoadingType
  phrases?: string[]
  interval?: number
  stage?: string
}

const props = withDefaults(defineProps<Props>(), {
  type: 'auto',
  phrases: () => [
    '星尘正在穿越神经网络…',
    '正在理解你的问题…',
    '正在检索工作区数据…',
    '内容较多，正在努力生成…',
  ],
  interval: 0,
  stage: '',
})

const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const thresholds = [0, 2000, 5000, 10000]

const phraseIndex = computed(() => {
  if (props.interval > 0) {
    return Math.min(Math.floor(elapsed.value / props.interval), props.phrases.length - 1)
  }
  if (elapsed.value >= thresholds[3]) return Math.min(3, props.phrases.length - 1)
  if (elapsed.value >= thresholds[2]) return Math.min(2, props.phrases.length - 1)
  if (elapsed.value >= thresholds[1]) return Math.min(1, props.phrases.length - 1)
  return 0
})

const activePhrase = computed(() => props.stage || props.phrases[phraseIndex.value] || '正在生成回复…')

const activeType = computed<Exclude<AiLoadingType, 'auto'>>(() => {
  if (props.type !== 'auto') return props.type
  return (['dots', 'shimmer', 'pulse', 'typewriter'] as const)[Math.min(phraseIndex.value, 3)]
})

function startTimer() {
  stopTimer()
  elapsed.value = 0
  timer = setInterval(() => {
    elapsed.value += 250
  }, 250)
}

function stopTimer() {
  if (timer) clearInterval(timer)
  timer = null
}

watch(() => [props.phrases, props.interval], startTimer, { deep: true })
onMounted(startTimer)
onUnmounted(stopTimer)
</script>

<template>
  <div class="ai-loading" role="status" aria-live="polite" :aria-label="activePhrase">
    <div class="loading-visual" :class="`is-${activeType}`" aria-hidden="true">
      <div v-if="activeType === 'dots'" class="typing-dots">
        <span /><span /><span />
      </div>

      <div v-else-if="activeType === 'shimmer'" class="shimmer-bars">
        <span /><span /><span />
      </div>

      <div v-else-if="activeType === 'pulse'" class="pulse-orbit">
        <span class="pulse-core">✦</span>
        <span class="pulse-ring ring-one" />
        <span class="pulse-ring ring-two" />
      </div>

      <div v-else class="typewriter-placeholder">
        <span class="typewriter-line" />
        <span class="typewriter-cursor" />
      </div>
    </div>

    <!-- 不用 mode="out-in"：该组件常被父级 v-if 在首个正文 token 到达时立即卸载，
         out-in 的延迟 afterLeave 会在节点已脱离后触发，导致 Vue parentNode null 崩溃，
         进而整条消息的正文/tokens 补丁被中断（刷新前不渲染）。 -->
    <transition name="loading-phrase">
      <div :key="activePhrase" class="loading-phrase">
        <span class="loading-icon" aria-hidden="true">🌌</span>
        <span>{{ activePhrase }}</span>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.ai-loading {
  width: 100%;
  max-width: 1120px;
  box-sizing: border-box;
  min-height: 126px;
  padding: 18px 22px 14px;
  overflow: hidden;
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  background: var(--chat-ai-card, var(--neutral-card));
  box-shadow: 0 1px 3px color-mix(in srgb, var(--neutral-text-1) 5%, transparent);
}

.loading-visual {
  min-height: 72px;
  display: flex;
  align-items: center;
}

.typing-dots {
  display: flex;
  gap: 9px;
  align-items: center;
  padding-left: 4px;
}

.typing-dots span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--arco-primary), var(--kimi-chart-2, #a855f7));
  animation: dot-breathe 1.2s ease-in-out infinite;
  will-change: transform, opacity;
}

.typing-dots span:nth-child(2) { animation-delay: 0.16s; }
.typing-dots span:nth-child(3) { animation-delay: 0.32s; }

.shimmer-bars {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shimmer-bars span {
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--arco-primary) 24%, transparent), transparent);
  background-color: color-mix(in srgb, var(--arco-primary) 8%, transparent);
  background-size: 200% 100%;
  animation: shimmer 1.6s ease-in-out infinite;
  will-change: background-position;
}

.shimmer-bars span:nth-child(2) { width: 78%; }
.shimmer-bars span:nth-child(3) { width: 58%; }

.pulse-orbit {
  position: relative;
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  margin-left: 8px;
}

.pulse-core {
  color: var(--arco-primary);
  font-size: 24px;
  animation: core-pulse 1.8s ease-in-out infinite;
  will-change: transform, opacity;
}

.pulse-ring {
  position: absolute;
  inset: 10px;
  border: 1px solid color-mix(in srgb, var(--arco-primary) 55%, transparent);
  border-radius: 50%;
  animation: ring-expand 2s ease-out infinite;
  will-change: transform, opacity;
}

.ring-two { animation-delay: 1s; }

.typewriter-placeholder {
  display: flex;
  align-items: center;
  width: min(78%, 440px);
  height: 34px;
}

.typewriter-line {
  width: 76%;
  height: 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--arco-primary) 14%, transparent);
  transform-origin: left;
  animation: line-grow 1.8s ease-in-out infinite;
  will-change: transform, opacity;
}

.typewriter-cursor {
  width: 2px;
  height: 20px;
  margin-left: 5px;
  border-radius: 2px;
  background: var(--arco-primary);
  animation: cursor-blink 0.9s step-end infinite;
}

.loading-phrase {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 20px;
  color: var(--chat-text-muted, var(--neutral-text-3));
  font-size: 12px;
}

.loading-icon { animation: core-pulse 2s ease-in-out infinite; }

.loading-phrase-enter-active,
.loading-phrase-leave-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.loading-phrase-enter-from { opacity: 0; transform: translateY(4px); }
.loading-phrase-leave-to { opacity: 0; transform: translateY(-4px); }

@keyframes dot-breathe {
  0%, 60%, 100% { opacity: 0.35; transform: translateY(0) scale(0.82); }
  30% { opacity: 1; transform: translateY(-7px) scale(1); }
}

@keyframes shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

@keyframes core-pulse {
  0%, 100% { opacity: 0.55; transform: scale(0.92); }
  50% { opacity: 1; transform: scale(1.08); }
}

@keyframes ring-expand {
  0% { opacity: 0.75; transform: scale(0.55); }
  100% { opacity: 0; transform: scale(1.7); }
}

@keyframes line-grow {
  0%, 100% { opacity: 0.45; transform: scaleX(0.35); }
  55% { opacity: 1; transform: scaleX(1); }
}

@keyframes cursor-blink { 50% { opacity: 0; } }

@media (max-width: 640px) {
  .ai-loading {
    width: 100%;
    min-height: 104px;
    padding: 14px 16px 12px;
  }
  .loading-visual { min-height: 56px; }
}

@media (prefers-reduced-motion: reduce) {
  .ai-loading *,
  .loading-phrase-enter-active,
  .loading-phrase-leave-active {
    animation: none !important;
    transition: none !important;
  }
  .typing-dots span { opacity: 0.65; transform: none; }
  .pulse-ring { display: none; }
  .typewriter-line { transform: scaleX(1); }
}
</style>
