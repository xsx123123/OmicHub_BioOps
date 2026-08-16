<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

interface Meteor {
  id: number
  top: number
  left: number
  delay: number
  duration: number
}

const EVENT_NAME = 'omicHub:triggerMeteorShower'
const meteors = ref<Meteor[]>([])
const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function trigger() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  if (timer) clearTimeout(timer)
  meteors.value = Array.from({ length: 12 }, (_, index) => ({
    id: Date.now() + index,
    top: 4 + Math.random() * 48,
    left: 12 + Math.random() * 76,
    delay: index * 0.12,
    duration: 0.72 + Math.random() * 0.42,
  }))
  visible.value = true
  timer = setTimeout(() => {
    visible.value = false
    meteors.value = []
  }, 2800)
}

onMounted(() => window.addEventListener(EVENT_NAME, trigger))
onBeforeUnmount(() => {
  window.removeEventListener(EVENT_NAME, trigger)
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div v-if="visible" class="meteor-overlay" aria-hidden="true">
    <span
      v-for="meteor in meteors"
      :key="meteor.id"
      class="meteor"
      :style="{
        top: `${meteor.top}%`,
        left: `${meteor.left}%`,
        animationDelay: `${meteor.delay}s`,
        animationDuration: `${meteor.duration}s`,
      }"
    />
  </div>
</template>

<style scoped>
.meteor-overlay {
  position: fixed;
  inset: 0;
  z-index: 9998;
  overflow: hidden;
  pointer-events: none;
}

.meteor {
  position: absolute;
  width: 130px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.96), rgba(139, 92, 246, 0.08));
  box-shadow: 0 0 12px rgba(118, 145, 255, 0.9);
  opacity: 0;
  transform: rotate(-28deg) translate3d(0, 0, 0);
  animation: meteor-fall ease-out forwards;
}

@keyframes meteor-fall {
  0% { opacity: 0; transform: rotate(-28deg) translate3d(0, 0, 0); }
  14% { opacity: 1; }
  100% { opacity: 0; transform: rotate(-28deg) translate3d(-230px, 360px, 0); }
}
</style>
