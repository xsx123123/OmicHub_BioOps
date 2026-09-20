<script setup lang="ts">
/**
 * LogoAnimation —— 登录页组合 Logo：之前的黑猫坐在旋转地球上
 *
 * 底层为无限旋转的地球 Lottie，上层复用原来的 loader-cat 黑猫动画，
 * 整体带轻微太空失重浮动，外层有紫色光晕呼应星空背景。
 */
import { onUnmounted, ref } from 'vue'
import { Vue3Lottie } from 'vue3-lottie'

const BASE = import.meta.env.BASE_URL
const globeUrl = `${BASE}lottie/earth-globe.json`
const blackCatUrl = `${BASE}lottie/loader-cat.json`

const globeFailed = ref(false)
const catFailed = ref(false)
let logoClicks = 0
let resetTimer: ReturnType<typeof setTimeout> | null = null

function handleLogoClick() {
  logoClicks += 1
  if (resetTimer) clearTimeout(resetTimer)
  resetTimer = setTimeout(() => { logoClicks = 0 }, 1800)
  if (logoClicks < 5) return
  logoClicks = 0
  window.dispatchEvent(new Event('cygnusX:triggerMeteorShower'))
}

onUnmounted(() => {
  if (resetTimer) clearTimeout(resetTimer)
})
</script>

<template>
  <div class="logo-container" role="button" tabindex="0" aria-label="CygnusX Logo 彩蛋" @click="handleLogoClick" @keydown.enter="handleLogoClick">
    <!-- 底层：旋转地球 -->
    <div class="globe-wrapper">
      <Vue3Lottie
        v-if="!globeFailed"
        :animation-link="globeUrl"
        :loop="true"
        :auto-play="true"
        :height="115"
        @on-error="globeFailed = true"
      />
      <div v-else class="globe-fallback" />
    </div>

    <!-- 上层：原来的黑猫 -->
    <div class="cat-wrapper">
      <Vue3Lottie
        v-if="!catFailed"
        :animation-link="blackCatUrl"
        :loop="true"
        :auto-play="true"
        :height="155"
        @on-error="catFailed = true"
      />
      <span v-else class="cat-emoji">🐱</span>
    </div>
  </div>
</template>

<style scoped>
.logo-container {
  position: relative;
  width: 180px;
  height: 215px;
  display: flex;
  justify-content: center;
  align-items: flex-end;
  margin: 0 auto 12px;
  animation: float 4s ease-in-out infinite;
}

.globe-wrapper {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 125px;
  height: 125px;
  z-index: 1;
}

.globe-wrapper::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 175px;
  height: 175px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.22) 0%, transparent 70%);
  border-radius: 50%;
  z-index: -1;
  pointer-events: none;
}

.globe-wrapper :deep(.lottie-animation-container),
.cat-wrapper :deep(.lottie-animation-container) {
  background-color: transparent !important;
}

.globe-fallback {
  width: 125px;
  height: 125px;
  border-radius: 50%;
  background: conic-gradient(from 0deg, #4f8dff, #3366ff, #7c3aed, #4f8dff);
  opacity: 0.8;
}

.cat-wrapper {
  position: absolute;
  bottom: 53px;
  left: calc(50% - 7px);
  transform: translateX(-50%);
  width: 155px;
  height: 155px;
  z-index: 2;
  pointer-events: none;
}

.cat-emoji {
  font-size: 125px;
  line-height: 1;
  filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.15));
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-6px);
  }
}

@media (max-width: 480px) {
  .logo-container {
    width: 140px;
    height: 170px;
  }

  .globe-wrapper {
    width: 100px;
    height: 100px;
  }

  .globe-wrapper::before {
    width: 140px;
    height: 140px;
  }

  .globe-fallback {
    width: 100px;
    height: 100px;
  }

  .cat-wrapper {
    width: 120px;
    height: 120px;
    bottom: 40px;
    left: calc(50% - 5px);
  }

  .cat-emoji {
    font-size: 100px;
  }
}
</style>
