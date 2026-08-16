<script setup lang="ts">
/**
 * 上传悬浮球 —— 弹窗最小化后显示在右下角，点击重新展开弹窗。
 * 上传任务在 upload store 中持续，切页不中断。
 */
import { NIcon, NProgress } from 'naive-ui'
import { ExpandOutline } from '@vicons/ionicons5'
import { useUploadStore } from '@/stores/upload'
import { storeToRefs } from 'pinia'

const uploadStore = useUploadStore()
const { activeCount, overallProgress } = storeToRefs(uploadStore)

function expand() {
  uploadStore.minimized = false
  uploadStore.modalOpen = true
}
</script>

<template>
  <div v-if="uploadStore.minimized && uploadStore.hasActive" class="floating-ball" @click="expand">
    <NProgress
      type="circle"
      :percentage="overallProgress"
      :stroke-width="5"
      :radius="26"
      :show-indicator="false"
      color="#165DFF"
      rail-color="rgba(22,93,255,0.15)"
    />
    <span class="ball-pct">{{ overallProgress }}%</span>
    <span class="ball-count">{{ activeCount }} 项</span>
    <NIcon :size="14" class="ball-expand"><ExpandOutline /></NIcon>
  </div>
</template>

<style scoped>
.floating-ball {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--neutral-card);
  box-shadow: 0 6px 20px rgba(22, 93, 255, 0.28);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 2000;
  transition: transform 0.2s;
  border: 2px solid #165DFF;
}
.floating-ball:hover {
  transform: scale(1.06);
}
.ball-pct {
  position: absolute;
  font-size: 13px;
  font-weight: 700;
  color: #165DFF;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.ball-count {
  position: absolute;
  bottom: -18px;
  font-size: 10px;
  color: var(--neutral-text-3, #86909c);
  white-space: nowrap;
}
.ball-expand {
  position: absolute;
  top: 4px;
  right: 6px;
  color: var(--neutral-text-3, #86909c);
}
</style>
