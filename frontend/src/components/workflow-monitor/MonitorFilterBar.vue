<script setup lang="ts">
import { NButton, NIcon, NInput, NSelect } from 'naive-ui'
import { RefreshOutline, SearchOutline } from '@vicons/ionicons5'
import type { MonitorFilter } from '@/types/workflowMonitor'

defineProps<{
  filters: MonitorFilter[]
  values: Record<string, unknown>
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update', key: string, value: unknown): void
  (e: 'refresh'): void
}>()
</script>

<template>
  <div class="monitor-filter-bar">
    <template v-for="filter in filters" :key="filter.key">
      <NInput
        v-if="filter.type === 'search'"
        :value="String(values[filter.key] || '')"
        :placeholder="filter.placeholder || filter.label"
        clearable
        class="filter-search"
        @update:value="(value) => emit('update', filter.key, value)"
      >
        <template #prefix>
          <NIcon :size="14"><SearchOutline /></NIcon>
        </template>
      </NInput>
      <NSelect
        v-else
        :value="String(values[filter.key] ?? filter.default ?? 'all')"
        :options="filter.options || [{ label: '全部', value: 'all' }]"
        class="filter-select"
        @update:value="(value) => emit('update', filter.key, value)"
      />
    </template>
    <NButton :loading="loading" @click="emit('refresh')">
      <template #icon>
        <NIcon><RefreshOutline /></NIcon>
      </template>
      刷新
    </NButton>
  </div>
</template>

<style scoped>
.monitor-filter-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-search {
  width: 260px;
}

.filter-select {
  width: 132px;
}

@media (max-width: 768px) {
  .monitor-filter-bar,
  .filter-search,
  .filter-select {
    width: 100%;
  }
}
</style>
