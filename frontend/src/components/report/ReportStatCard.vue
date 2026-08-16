<script setup lang="ts">
import { NCard, NIcon } from 'naive-ui'
import type { PropType } from 'vue'

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  value: {
    type: Number,
    required: true,
  },
  icon: {
    type: Object as PropType<unknown>,
    required: true,
  },
  color: {
    type: String,
    default: 'blue',
  },
  breathing: {
    type: Boolean,
    default: false,
  },
})

const colorMap: Record<string, { bg: string; color: string }> = {
  blue: { bg: 'linear-gradient(135deg, #e8f0ff, #d6e4ff)', color: '#165DFF' },
  purple: { bg: 'linear-gradient(135deg, #f0e8ff, #e9d5ff)', color: '#8E54E9' },
  orange: { bg: 'linear-gradient(135deg, #fff7e6, #ffe4ba)', color: '#FF7D00' },
  amber: { bg: 'linear-gradient(135deg, #fff9e6, #ffefc2)', color: '#FFB800' },
}

const theme = colorMap[props.color] || colorMap.blue
</script>

<template>
  <NCard size="small" class="stat-card">
    <div class="stat-card-content">
      <div
        class="stat-icon"
        :style="{ background: theme.bg, color: theme.color }"
      >
        <NIcon :size="22" :component="icon as any" />
      </div>
      <div class="stat-info">
        <div class="stat-value" :class="{ breathing }">
          {{ value }}
        </div>
        <div class="stat-title">{{ title }}</div>
      </div>
    </div>
  </NCard>
</template>

<style scoped>
.stat-card {
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  background: var(--neutral-card);
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(22, 93, 255, 0.04);
  border: 1px solid var(--neutral-border);
}
.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(22, 93, 255, 0.1);
}
.stat-card-content {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-info {
  flex: 1;
}
.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--neutral-text-1);
  line-height: 1;
  letter-spacing: -0.02em;
}
.stat-value.breathing {
  background: linear-gradient(90deg, #165dff, #8e54e9, #165dff);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: breathe 2.4s ease-in-out infinite;
}
.stat-title {
  font-size: 13px;
  color: var(--neutral-text-2);
  margin-top: 5px;
}
@keyframes breathe {
  0%, 100% { opacity: 1; background-position: 0% center; }
  50% { opacity: 0.75; background-position: 100% center; }
}
</style>
