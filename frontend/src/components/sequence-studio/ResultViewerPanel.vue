<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NTabPane, NTabs, NTag } from 'naive-ui'
import { CopyOutline, DownloadOutline, ExpandOutline } from '@vicons/ionicons5'
import type { SequenceResultItem } from '@/engine/types'

const props = defineProps<{
  title: string
  items: SequenceResultItem[]
  durationMs: number
}>()

const emit = defineEmits<{
  copy: [item?: SequenceResultItem]
  download: [format: 'fasta' | 'txt' | 'json']
}>()

const activeId = ref('')
const expanded = ref(false)

watch(() => props.items, (items) => {
  activeId.value = items[0]?.id || ''
  expanded.value = false
}, { immediate: true })

const activeItem = computed(() => props.items.find((item) => item.id === activeId.value) || props.items[0])
</script>

<template>
  <section class="result-panel" aria-labelledby="result-panel-title">
    <header class="result-heading">
      <div>
        <span class="panel-kicker">Result viewer</span>
        <h2 id="result-panel-title">{{ title }}</h2>
        <div v-if="items.length" class="result-meta">
          <NTag size="small" :bordered="false">{{ items.length }} 条结果</NTag>
          <span>{{ durationMs.toFixed(1) }} ms</span>
        </div>
      </div>
      <div class="result-actions">
        <NButton size="tiny" tertiary :disabled="!items.length" @click="emit('copy')">
          <template #icon><NIcon><CopyOutline /></NIcon></template>
          全部复制
        </NButton>
        <NButton size="tiny" tertiary :disabled="!items.length" @click="emit('download', 'fasta')">
          <template #icon><NIcon><DownloadOutline /></NIcon></template>
          FASTA
        </NButton>
        <NButton size="tiny" tertiary :disabled="!items.length" @click="emit('download', 'txt')">TXT</NButton>
        <NButton size="tiny" tertiary :disabled="!items.length" @click="emit('download', 'json')">JSON</NButton>
      </div>
    </header>

    <NEmpty v-if="!items.length" description="选择左侧工具运行分析">
      <template #extra>
        <span class="empty-hint">支持多 FASTA 批量处理，结果不会离开浏览器</span>
      </template>
    </NEmpty>

    <template v-else>
      <NTabs v-if="items.length > 1" v-model:value="activeId" type="line" size="small" class="result-tabs">
        <NTabPane v-for="item in items" :key="item.id" :name="item.id" :tab="item.id" />
      </NTabs>
      <div class="record-heading">
        <div>
          <strong>{{ activeItem?.header }}</strong>
          <span>{{ activeItem?.sequence.length.toLocaleString() }} {{ activeItem?.type === 'protein' ? 'aa' : 'nt' }}</span>
        </div>
        <NButton size="tiny" quaternary @click="expanded = !expanded">
          <template #icon><NIcon><ExpandOutline /></NIcon></template>
          {{ expanded ? '收起' : '展开' }}
        </NButton>
      </div>
      <pre :class="['result-sequence', { 'is-expanded': expanded }]">{{ activeItem?.sequence }}</pre>
    </template>
  </section>
</template>

<style scoped>
.result-panel {
  min-width: 0;
}

.result-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.panel-kicker {
  color: var(--primary-color, var(--arco-primary));
  font-size: var(--font-micro-size);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin: 2px 0 0;
  color: var(--neutral-text-1);
  font-size: 16px;
  line-height: 1.4;
}

.result-meta,
.result-actions,
.record-heading,
.record-heading > div {
  display: flex;
  align-items: center;
}

.result-meta {
  gap: var(--space-sm);
  margin-top: var(--space-xs);
  color: var(--neutral-text-3);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.result-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-xs);
}

.empty-hint {
  color: var(--neutral-text-3);
  font-size: 12px;
}

.result-tabs {
  margin-bottom: var(--space-sm);
}

.record-heading {
  justify-content: space-between;
  gap: var(--space-md);
  margin-bottom: var(--space-sm);
}

.record-heading > div {
  min-width: 0;
  gap: var(--space-sm);
}

.record-heading strong {
  overflow: hidden;
  color: var(--neutral-text-1);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-heading span {
  flex: 0 0 auto;
  color: var(--neutral-text-3);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.result-sequence {
  max-height: 360px;
  min-height: 260px;
  margin: 0;
  padding: var(--space-lg);
  overflow: auto;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
  color: var(--neutral-text-1);
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.result-sequence.is-expanded {
  max-height: 680px;
}

@media (max-width: 720px) {
  .result-heading {
    flex-direction: column;
  }

  .result-actions {
    justify-content: flex-start;
  }
}
</style>
