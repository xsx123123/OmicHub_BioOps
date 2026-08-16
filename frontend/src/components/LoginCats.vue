<script setup lang="ts">
/**
 * LoginCats —— 登录页唯一吉祥物：黑猫
 *
 * 仅保留 loader-cat（黑猫）一只，居中放置于 OmicHub 标题正上方，
 * 头部探出登录卡片顶部，不遮挡标题与表单。
 * 复用项目既有 vue3-lottie 模式，资源缺失时兜底为 🐱 emoji。
 */
import { ref } from 'vue'
import { Vue3Lottie } from 'vue3-lottie'

const BASE = import.meta.env.BASE_URL
const blackCatUrl = `${BASE}lottie/loader-cat.json`

const failed = ref(false)
</script>

<template>
  <div class="cat-mascot-wrapper" aria-hidden="true">
    <div class="cat-mascot">
      <Vue3Lottie
        v-if="!failed"
        :animation-link="blackCatUrl"
        :loop="true"
        :auto-play="true"
        :height="160"
        @on-error="failed = true"
      />
      <span v-else class="cat-emoji">🐱</span>
    </div>
  </div>
</template>

<style scoped>
.cat-mascot-wrapper {
  display: flex;
  justify-content: center;
  align-items: center;
  margin-top: -55px;
  margin-bottom: 12px;
  position: relative;
  z-index: 15;
  opacity: 0;
  transform: translateY(-20px);
  animation: catDropIn 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) 0.5s forwards;
}

.cat-mascot {
  width: 160px;
  height: auto;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.15));
  transition: transform 0.3s ease;
  pointer-events: auto;
  background: transparent !important;
}

.cat-mascot :deep(.lottie-animation-container) {
  background-color: transparent !important;
}

.cat-mascot:hover {
  transform: scale(1.05) translateY(-4px);
}

.cat-emoji {
  font-size: 100px;
  line-height: 1;
  filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.15));
}

@keyframes catDropIn {
  0% {
    opacity: 0;
    transform: translateY(-20px) scale(0.9);
  }
  70% {
    transform: translateY(4px) scale(1.02);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (max-width: 768px) {
  .cat-mascot-wrapper {
    margin-top: -40px;
    margin-bottom: 8px;
  }

  .cat-mascot {
    width: 120px;
  }

  .cat-emoji {
    font-size: 80px;
  }
}

@media (max-width: 480px) {
  .cat-mascot-wrapper {
    margin-top: -30px;
    margin-bottom: 6px;
  }

  .cat-mascot {
    width: 100px;
  }

  .cat-emoji {
    font-size: 72px;
  }
}
</style>
