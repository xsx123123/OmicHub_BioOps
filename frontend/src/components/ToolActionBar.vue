<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { NButton, NIcon, NTooltip } from 'naive-ui'
import type { Component } from 'vue'

const props = withDefaults(defineProps<{
  /** 表单/数据是否就绪，决定主按钮可用性与状态点颜色 */
  ready: boolean
  /** 就绪时的状态文案 */
  readyText?: string
  /** 未就绪时的状态文案 */
  notReadyText?: string
  /** 主按钮文字（全页唯一 primary） */
  primaryLabel: string
  /** 主按钮图标组件（@vicons/ionicons5） */
  primaryIcon?: Component
  loading?: boolean
  /** 未就绪时悬浮主按钮的提示，说明缺什么 */
  notReadyTip?: string
}>(), {
  readyText: '参数已就绪',
  notReadyText: '待完善必填参数',
  loading: false,
  notReadyTip: '',
})

const emit = defineEmits<{ action: [] }>()

const statusText = computed(() => (props.ready ? props.readyText : props.notReadyText))
const showTip = computed(() => !props.ready && !!props.notReadyTip && !props.loading)

function trigger() {
  if (props.ready && !props.loading) emit('action')
}

function onKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    trigger()
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="tool-action-bar" :class="{ 'is-ready': ready }">
    <div class="action-status" role="status" :aria-live="ready ? 'off' : 'polite'">
      <span class="status-dot" aria-hidden="true" />
      <span class="status-text">{{ statusText }}</span>
    </div>
    <NTooltip :disabled="!showTip" placement="top" :delay="200">
      <template #trigger>
        <!-- disabled 按钮不派发鼠标事件，包一层 span 让 tooltip 可用 -->
        <span class="primary-wrap">
          <NButton
            type="primary"
            size="large"
            class="primary-action"
            :loading="loading"
            :disabled="!ready"
            @click="trigger"
          >
            <template v-if="primaryIcon" #icon>
              <NIcon :size="18"><component :is="primaryIcon" /></NIcon>
            </template>
            {{ primaryLabel }}
            <kbd class="action-kbd" aria-hidden="true">⌘↵</kbd>
          </NButton>
        </span>
      </template>
      {{ notReadyTip }}
    </NTooltip>
  </div>
</template>

<style scoped>
.tool-action-bar {
  position: sticky;
  bottom: 12px;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px) saturate(170%);
  -webkit-backdrop-filter: blur(20px) saturate(170%);
  border: 1px solid rgba(255, 255, 255, 0.65);
  border-top-color: rgba(255, 255, 255, 0.8);
  border-radius: 14px;
  box-shadow: 0 -2px 24px rgba(15, 23, 42, 0.08), 0 2px 8px rgba(15, 23, 42, 0.05);
}

:root[data-theme="dark"] .tool-action-bar {
  background: rgba(17, 22, 34, 0.62);
  border-color: rgba(255, 255, 255, 0.08);
  border-top-color: rgba(255, 255, 255, 0.14);
  box-shadow: 0 -2px 24px rgba(0, 0, 0, 0.32), 0 2px 8px rgba(0, 0, 0, 0.24);
}

.action-status {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.status-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--neutral-text-3, #86909c);
  box-shadow: 0 0 0 3px rgba(134, 144, 156, 0.15);
  transition: background 320ms cubic-bezier(0.16, 1, 0.3, 1),
    box-shadow 320ms cubic-bezier(0.16, 1, 0.3, 1);
}

.is-ready .status-dot {
  background: #00b42a;
  box-shadow: 0 0 0 3px rgba(0, 180, 42, 0.16);
}

.status-text {
  color: var(--neutral-text-2, #4e5969);
  font-size: 13px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.primary-wrap {
  display: inline-flex;
}

.primary-action {
  min-width: 132px;
  transition: opacity 320ms cubic-bezier(0.16, 1, 0.3, 1),
    transform 320ms cubic-bezier(0.16, 1, 0.3, 1);
}

.primary-action:active {
  transform: scale(0.98);
  transition-duration: 100ms;
}

.action-kbd {
  margin-left: 8px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.22);
  font-family: inherit;
  font-size: 11px;
  line-height: 1.4;
  opacity: 0.85;
}

@media (max-width: 640px) {
  .tool-action-bar {
    bottom: 0;
    margin: 16px -16px 0;
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
    border-radius: 0;
    border-left: none;
    border-right: none;
  }

  .primary-action {
    min-height: 44px;
    flex: 1;
  }

  .action-kbd {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .status-dot,
  .primary-action {
    transition: none;
  }

  .primary-action:active {
    transform: none;
  }
}
</style>
