<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  context: 'hero' | 'login'
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let cleanup: (() => void) | null = null

onMounted(async () => {
  // 动画库是副作用脚本，直接执行即可挂载 window 方法
  await import('@/utils/animationLibrary')
  if (!canvasRef.value) return
  const fn = props.context === 'hero' ? window.initHeroAnimation : window.initLoginAnimation
  if (fn) {
    const destroy = fn(canvasRef.value)
    if (destroy) cleanup = destroy
  }
})

onUnmounted(() => {
  cleanup?.()
})
</script>

<template>
  <canvas ref="canvasRef" class="omic-canvas" />
</template>

<style scoped>
.omic-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}
</style>
