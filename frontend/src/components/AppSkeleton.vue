<script setup lang="ts">
withDefaults(defineProps<{
  rows?: number
  avatar?: boolean
}>(), {
  rows: 4,
  avatar: false,
})

const widths = ['80%', '100%', '60%', '90%', '75%', '50%']
</script>

<template>
  <div class="app-skeleton">
    <div v-if="avatar" class="app-skeleton__avatar" />
    <div class="app-skeleton__body">
      <div
        v-for="i in rows"
        :key="i"
        class="app-skeleton__row"
        :style="{ width: widths[(i - 1) % widths.length] }"
      />
    </div>
  </div>
</template>

<style scoped>
.app-skeleton {
  display: flex;
  gap: 16px;
  padding: 16px;
}

.app-skeleton__avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--neutral-border);
  flex-shrink: 0;
  animation: app-skeleton-pulse 1.5s ease-in-out infinite;
}

.app-skeleton__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.app-skeleton__row {
  height: 14px;
  border-radius: 4px;
  background: var(--neutral-border);
  animation: app-skeleton-pulse 1.5s ease-in-out infinite;
}

@keyframes app-skeleton-pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}
</style>
