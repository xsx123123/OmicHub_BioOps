<script setup lang="ts">
import { h } from 'vue'
import { NButton, NDataTable, NEmpty, NTag, type DataTableColumns } from 'naive-ui'
import type { OrfMatch } from '@/engine/types'

const props = defineProps<{
  rows: OrfMatch[]
}>()

const emit = defineEmits<{
  export: [row: OrfMatch, type: 'dna' | 'protein']
  select: [row: OrfMatch]
}>()

const columns: DataTableColumns<OrfMatch> = [
  { title: 'ID', key: 'id', width: 92, ellipsis: { tooltip: true } },
  { title: 'Frame', key: 'frame', width: 72, align: 'center', render: (row) => h(NTag, { size: 'small', type: row.frame > 0 ? 'success' : 'warning', bordered: false }, { default: () => `${row.frame > 0 ? '+' : ''}${row.frame}` }) },
  { title: 'Start', key: 'start', width: 84, align: 'center' },
  { title: 'End', key: 'end', width: 84, align: 'center' },
  { title: 'Length', key: 'length', width: 132, align: 'center', render: (row) => `${row.lengthNt} nt / ${row.lengthAa} aa` },
  {
    title: '操作', key: 'actions', width: 210, align: 'center', render: (row) => h('div', { class: 'orf-actions' }, [
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => emit('select', row) }, { default: () => '定位' }),
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => emit('export', row, 'dna') }, { default: () => 'DNA' }),
      h(NButton, { size: 'tiny', tertiary: true, onClick: () => emit('export', row, 'protein') }, { default: () => 'Protein' }),
    ]) },
]
</script>

<template>
  <section class="orf-panel" aria-labelledby="orf-panel-title">
    <header>
      <div>
        <span>ORF finder</span>
        <h2 id="orf-panel-title">开放阅读框</h2>
      </div>
      <NTag size="small" :type="rows.length ? 'success' : 'default'">{{ rows.length }} 个 ORF</NTag>
    </header>
    <NDataTable
      v-if="rows.length"
      :columns="columns"
      :data="props.rows"
      :pagination="rows.length > 10 ? { pageSize: 10 } : false"
      :row-key="(row: OrfMatch) => row.id"
      :scroll-x="674"
      size="small"
      :bordered="false"
    />
    <NEmpty v-else description="当前阈值下未检测到 ORF" />
  </section>
</template>

<style scoped>
.orf-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.orf-panel header span {
  color: var(--primary-color, var(--arco-primary));
  font-size: var(--font-micro-size);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.orf-panel h2 {
  margin: 2px 0 0;
  color: var(--neutral-text-1);
  font-size: 16px;
}

.orf-panel :deep(.orf-actions) {
  display: flex;
  justify-content: center;
  gap: var(--space-xs);
}
</style>
