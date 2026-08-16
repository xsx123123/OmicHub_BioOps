<script setup lang="ts">
import type { Component } from 'vue'
import { NIcon } from 'naive-ui'
import { FolderOpenOutline } from '@vicons/ionicons5'

withDefaults(defineProps<{
  icon?: string | Component
  title: string
  description?: string
}>(), {
  icon: FolderOpenOutline,
  description: '',
})
</script>

<template>
  <section class="empty-state" role="status">
    <div class="empty-state-icon" aria-hidden="true">
      <NIcon v-if="typeof icon !== 'string'" :component="icon" :size="26" />
      <span v-else>{{ icon }}</span>
    </div>
    <h3>{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.actions" class="empty-state-actions">
      <slot name="actions" />
    </div>
  </section>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  padding: 28px 24px;
  color: var(--text-secondary);
  text-align: center;
}

.empty-state-icon {
  display: grid;
  width: 52px;
  height: 52px;
  margin-bottom: 14px;
  place-items: center;
  border-radius: 16px;
  background: var(--brand-primary-light);
  font-size: 26px;
}

h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
}

p {
  max-width: 360px;
  margin: 6px 0 0;
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1.6;
}

.empty-state-actions {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
