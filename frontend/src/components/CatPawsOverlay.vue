<script setup lang="ts">
/**
 * 全局猫爪彩蛋覆盖层 —— 全局挂载（App.vue），监听 window 事件
 * `cygnusX:triggerCatPaws`，收到后全屏随机浮现发光猫爪足迹。
 *
 * 设计为“被动触发”：不自行弹 Toast，由调用方决定是否提示
 * （如关于页召唤按钮自己弹 Toast 后再派发事件；激活弹窗第 5 次点击只派发事件）。
 * pointer-events:none，不阻挡页面交互。
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'

interface CatPaw {
  id: number
  top: number
  left: number
  rotate: number
  scale: number
  delay: number
}

const EVENT_NAME = 'cygnusX:triggerCatPaws'
const PAW_COUNT = 26
const VISIBLE_MS = 7000

const showCatPaws = ref(false)
const catPaws = ref<CatPaw[]>([])
let hideTimer: ReturnType<typeof setTimeout> | null = null
let seq = 0 // 猫爪 id 自增（避免 Date.now 受系统时间影响 + 同批重复）

function trigger() {
  // 重新触发时先清掉上一次的收起定时器，覆盖一批新猫爪
  if (hideTimer) clearTimeout(hideTimer)
  const batch: CatPaw[] = Array.from({ length: PAW_COUNT }, () => ({
    id: seq++,
    top: 8 + Math.random() * 84,
    left: 5 + Math.random() * 90,
    rotate: -30 + Math.random() * 60,
    scale: 0.7 + Math.random() * 0.8,
    delay: Math.random() * 1.2,
  }))
  catPaws.value = batch
  showCatPaws.value = true
  hideTimer = setTimeout(() => {
    showCatPaws.value = false
    catPaws.value = []
  }, VISIBLE_MS)
}

function onEvent(e: Event) {
  // 允许通过 detail 预留扩展（如自定义猫爪数量），暂不使用
  void e
  trigger()
}

onMounted(() => window.addEventListener(EVENT_NAME, onEvent))
onBeforeUnmount(() => {
  window.removeEventListener(EVENT_NAME, onEvent)
  if (hideTimer) clearTimeout(hideTimer)
})
</script>

<template>
  <Transition name="paws-fade">
    <div v-if="showCatPaws" class="cat-paws-overlay">
      <span
        v-for="p in catPaws"
        :key="p.id"
        class="cat-paw"
        :style="{
          top: p.top + '%',
          left: p.left + '%',
          '--rot': p.rotate + 'deg',
          '--scale': p.scale,
          animationDelay: p.delay + 's',
        }"
      >🐾</span>
    </div>
  </Transition>
</template>

<style scoped>
.cat-paws-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none; /* 不阻挡页面交互 */
}
.cat-paw {
  position: absolute;
  font-size: 52px;
  /* 彩色 emoji 不受 color 影响，用多层 drop-shadow 叠出强发光，让深空/浅色背景上都醒目 */
  filter:
    drop-shadow(0 0 6px rgba(255, 255, 255, 0.95))
    drop-shadow(0 0 12px rgba(167, 139, 250, 0.9))
    drop-shadow(0 0 22px rgba(103, 232, 249, 0.7));
  opacity: 0;
  animation: paw-appear 2s ease-out forwards;
}
@keyframes paw-appear {
  0% {
    opacity: 0;
    transform: translate(-50%, -50%) rotate(var(--rot, 0deg))
      scale(calc(var(--scale, 1) * 0.4));
  }
  18% {
    opacity: 1;
    transform: translate(-50%, -50%) rotate(var(--rot, 0deg)) scale(var(--scale, 1));
  }
  78% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}
.paws-fade-leave-active {
  transition: opacity 0.4s ease;
}
.paws-fade-leave-to {
  opacity: 0;
}
</style>
