<script setup lang="ts">
withDefaults(defineProps<{
  text?: string
  size?: 'small' | 'medium' | 'large'
}>(), {
  text: '加载中...',
  size: 'medium',
})
</script>

<template>
  <div class="app-loading" :class="`app-loading--${size}`">
    <svg class="app-loading__dna" viewBox="0 0 40 48" fill="none" aria-hidden="true">
      <path class="app-loading__strand app-loading__strand--left" d="M10 2C31 10 31 18 10 24C-11 31 -11 39 10 46" />
      <path class="app-loading__strand app-loading__strand--right" d="M30 2C9 10 9 18 30 24C51 31 51 39 30 46" />
      <path class="app-loading__rung" d="M13 8H27M11 16H29M11 32H29M13 40H27" />
    </svg>
    <span v-if="text" class="app-loading__text">{{ text }}</span>
  </div>
</template>

<style scoped>
.app-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--neutral-text-3);
}

.app-loading--small .app-loading__dna {
  width: 20px;
  height: 20px;
}
.app-loading--small .app-loading__text {
  font-size: 12px;
}

.app-loading--medium .app-loading__dna {
  width: 32px;
  height: 32px;
}
.app-loading--medium .app-loading__text {
  font-size: 14px;
}

.app-loading--large .app-loading__dna {
  width: 48px;
  height: 48px;
}
.app-loading--large .app-loading__text {
  font-size: 16px;
}

.app-loading__dna {
  overflow: visible;
  color: var(--brand-primary);
  animation: app-loading-dna-breathe 1.5s ease-in-out infinite;
}

.app-loading__strand {
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 3;
}

.app-loading__strand--right {
  opacity: 0.45;
}

.app-loading__rung {
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 2;
  opacity: 0.55;
}

.app-loading__text {
  color: var(--neutral-text-2);
}

@keyframes app-loading-dna-breathe {
  0%, 100% { opacity: 0.55; transform: scale(0.94); }
  50% { opacity: 1; transform: scale(1.06); }
}

@media (prefers-reduced-motion: reduce) {
  .app-loading__dna {
    animation: none;
  }
}
</style>
