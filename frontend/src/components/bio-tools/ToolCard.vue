<script setup lang="ts">
import { NIcon, NButton } from 'naive-ui'
import { ChevronForwardOutline } from '@vicons/ionicons5'
import type { Component } from 'vue'

defineProps<{
  title: string
  description: string
  icon: Component
  gradient: string
  to?: string
}>()

const emit = defineEmits<{
  click: []
}>()
</script>

<template>
  <div
    class="tool-card cygnusx-card"
    role="link"
    tabindex="0"
    @click="emit('click')"
    @keydown.enter="emit('click')"
    @keydown.space.prevent="emit('click')"
  >
    <div class="tool-card-icon" :style="{ background: gradient }">
      <NIcon :size="28" color="#fff">
        <component :is="icon" />
      </NIcon>
    </div>
    <div class="tool-card-body">
      <h3 class="tool-card-title">{{ title }}</h3>
      <p class="tool-card-desc">{{ description }}</p>
    </div>
    <NButton text class="tool-card-arrow" tabindex="-1">
      <NIcon :size="18">
        <ChevronForwardOutline />
      </NIcon>
    </NButton>
  </div>
</template>

<style scoped>
/*
 * Apple Design 交互原则（详见 tool_configs/tools_design.md §十六）：
 * - 缓动统一 cubic-bezier(0.16, 1, 0.3, 1)，模拟临界阻尼弹簧（无过冲）
 * - 按压反馈即时（100ms），悬停反馈柔和（320ms）
 * - 箭头位移暗示「即将前进」，预示手势方向
 */
.tool-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid var(--neutral-border);
  cursor: pointer;
  transition:
    transform var(--card-state-duration) var(--card-state-easing),
    box-shadow var(--card-state-duration) var(--card-state-easing);
}
.tool-card:hover {
  border-color: var(--arco-primary, #165DFF);
  /* 分层阴影：大面积柔光 + 近身接触影，比单层阴影更有「浮起」的纵深感 */
  box-shadow:
    inset 0 0 0 1px var(--arco-primary, #165DFF),
    0 12px 28px rgba(22, 93, 255, 0.12),
    0 2px 6px rgba(0, 0, 0, 0.05);
  transform: translateY(-2px);
}
/* 按下瞬间立刻收缩，反馈不等待松手 */
.tool-card:active {
  transform: translateY(0) scale(0.98);
  box-shadow: 0 2px 8px rgba(22, 93, 255, 0.08);
  transition-duration: 100ms;
}
.tool-card:focus-visible {
  outline: 2px solid var(--arco-primary, #165DFF);
  outline-offset: 2px;
}
.tool-card-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  /* 顶部内高光 = 光打在材质上；底部浅投影让色块浮于卡片 */
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.28),
    0 2px 8px rgba(0, 0, 0, 0.14);
}
.tool-card-body {
  flex: 1;
  min-width: 0;
}
.tool-card-title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--neutral-text-1, #1d2129);
  margin: 0 0 4px;
}
.tool-card-desc {
  font-size: 13px;
  color: var(--neutral-text-3, #86909c);
  margin: 0;
  line-height: 1.4;
}
.tool-card-arrow {
  color: var(--neutral-text-3, #86909c);
  flex-shrink: 0;
  transition:
    transform var(--card-state-duration) var(--card-state-easing),
    color var(--card-state-duration) var(--card-state-easing);
}
/* 悬停时箭头右移，朝「前进」的方向给动作暗示 */
.tool-card:hover .tool-card-arrow,
.tool-card:focus-visible .tool-card-arrow {
  color: var(--arco-primary, #165DFF);
  transform: translateX(3px);
}

@media (prefers-reduced-motion: reduce) {
  .tool-card,
  .tool-card-arrow {
    transition: none;
  }
  .tool-card:hover,
  .tool-card:active {
    transform: none;
  }
  .tool-card:hover .tool-card-arrow,
  .tool-card:focus-visible .tool-card-arrow {
    transform: none;
  }
}
</style>
