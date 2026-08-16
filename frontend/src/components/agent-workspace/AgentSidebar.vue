<script setup lang="ts">
import { NButton, NIcon, NTooltip } from 'naive-ui'
import { AddOutline, TimeOutline } from '@vicons/ionicons5'

defineEmits<{
  newChat: []
  openHistory: []
}>()
</script>

<template>
  <aside class="agent-sidebar">
    <div class="sidebar-top">
      <div class="nav-top-controls">
        <NTooltip trigger="hover" placement="right">
          <template #trigger>
            <NButton text class="nav-icon-btn add-btn" @click="$emit('newChat')">
              <NIcon size="18"><AddOutline /></NIcon>
            </NButton>
          </template>
          新建对话
        </NTooltip>
        <NTooltip trigger="hover" placement="right">
          <template #trigger>
            <NButton text class="nav-icon-btn menu-btn" @click="$emit('openHistory')">
              <NIcon size="18"><TimeOutline /></NIcon>
            </NButton>
          </template>
          历史会话
        </NTooltip>
      </div>
    </div>

  </aside>
</template>

<style scoped lang="scss">
.agent-sidebar {
  width: 60px;
  min-width: 60px;
  height: 100%;
  background: var(--chat-sidebar-bg);
  border-right: 1px solid var(--chat-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-top {
  display: flex; align-items: center; justify-content: center;
  padding: 12px;
}

.nav-top-controls {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.nav-icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  transition: all 0.2s ease;
  padding: 0;
}
.nav-icon-btn .n-icon {
  width: 18px;
  height: 18px;
  font-size: 18px;
}

.nav-icon-btn.menu-btn {
  color: var(--chat-text-muted, #86909c);
}
.nav-icon-btn.menu-btn:hover {
  background: var(--chat-surface-hover, rgba(0,0,0,.06));
  color: var(--chat-text-primary, #1d2129);
}
.nav-icon-btn.add-btn {
  color: #fff;
  background: var(--brand-gradient);
}
.nav-icon-btn.add-btn:hover {
  color: #fff;
  box-shadow: 0 4px 12px rgba(76, 111, 255, .24);
  transform: translateY(-1px);
}

</style>
