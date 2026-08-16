<template>
  <div class="error-page-container" role="main" :aria-label="title">
    <div class="error-page-orb" />
    <div class="error-page-content animate-scale-in">
      <div class="error-page-mascot" aria-hidden="true">{{ emoji }}</div>
      <h1 class="error-page-code animate-float">{{ code }}</h1>
      <p class="error-page-message">{{ title }}</p>
      <p v-if="hint" class="error-page-hint">{{ hint }}</p>
      <div class="error-page-actions">
        <slot name="actions">
          <n-button type="primary" size="large" @click="goHome">返回首页</n-button>
        </slot>
      </div>
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

withDefaults(
  defineProps<{
    code: string | number
    title: string
    hint?: string
    emoji?: string
  }>(),
  { hint: '', emoji: '🐱' }
)

const router = useRouter()
const goHome = () => {
  router.push('/')
}
</script>

<style scoped>
.error-page-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(
    -45deg,
    var(--error-gradient-1),
    var(--error-gradient-2),
    var(--error-gradient-3),
    var(--error-gradient-4)
  );
  background-size: 400% 400%;
  animation: gradientShift 12s ease infinite;
  color: white;
  position: relative;
  overflow: hidden;
}

.error-page-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.25;
  pointer-events: none;
  width: 500px;
  height: 500px;
  background: var(--error-orb);
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  animation: drift 18s ease-in-out infinite;
}

.error-page-content {
  text-align: center;
  position: relative;
  z-index: 1;
  padding: 0 var(--space-md, 16px);
}

.error-page-mascot {
  margin-bottom: -8px;
  font-size: 54px;
  filter: drop-shadow(0 8px 18px rgba(11, 15, 25, 0.2));
  animation: mascot-bob 3.5s ease-in-out infinite;
}

.error-page-code {
  font-size: 120px;
  font-weight: 800;
  margin-bottom: 16px;
  line-height: 1;
  text-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
}

.error-page-message {
  font-size: 24px;
  margin-bottom: 8px;
  opacity: 0.95;
}

.error-page-hint {
  font-size: 14px;
  opacity: 0.6;
  margin-bottom: 32px;
}

.error-page-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}

@keyframes mascot-bob {
  0%, 100% { transform: translateY(0) rotate(-3deg); }
  50% { transform: translateY(-8px) rotate(3deg); }
}

@media (max-width: 640px) {
  .error-page-code {
    font-size: 72px;
  }
  .error-page-mascot {
    font-size: 40px;
  }
  .error-page-message {
    font-size: 18px;
  }
}
</style>
