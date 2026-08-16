<script setup lang="ts">
import { ref, computed } from 'vue'
import { NCard, NTag, NButton } from 'naive-ui'
import { ChevronDownOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import BlastAlignmentBar from './BlastAlignmentBar.vue'
import BlastSequenceAlignment from './BlastSequenceAlignment.vue'
import type { BlastHit } from '@/types/blast'

const props = defineProps<{
  hit: BlastHit
  queryLen: number
}>()

const expanded = ref(false)

const identityColor = computed(() => {
  const v = props.hit.identity_percent
  if (v >= 90) return 'success'
  if (v >= 70) return 'info'
  if (v >= 40) return 'warning'
  return 'error'
})

const barHsps = computed(() => {
  return props.hit.hsps.map(h => ({
    hit_from: h.query_from,
    hit_to: h.query_to,
    identity_percent: h.identity_percent,
    evalue: h.evalue,
    bit_score: h.bit_score,
  }))
})

const statItems = computed(() => {
  const h = props.hit.best_hsp
  if (!h) return []
  return [
    { label: 'Subject', value: `${props.hit.hit_len.toLocaleString()} bp` },
    { label: 'E-value', value: h.evalue.toExponential(2) },
    { label: 'Bit Score', value: h.bit_score.toFixed(1) },
    { label: 'Align', value: `${h.align_length} bp` },
    { label: 'Query Coverage', value: `${props.hit.query_coverage.toFixed(1)}%` },
    { label: 'Query', value: `${h.query_from}-${h.query_to}` },
    { label: 'Subject', value: `${h.hit_from}-${h.hit_to}` },
    { label: 'Mismatch', value: String(h.mismatches) },
    { label: 'Gaps', value: String(h.gaps) },
    { label: 'Total', value: props.hit.total_score.toFixed(1) },
  ]
})
</script>

<template>
  <NCard :id="`blast-hit-${hit.hit_num}`" size="small" class="blast-hit-card">
    <template #header>
      <div class="hit-header">
        <span class="hit-title">Hit #{{ hit.hit_num }}</span>
        <NTag type="primary" size="small" class="hit-id-tag">{{ hit.hit_id }}</NTag>
        <span class="hit-desc" :title="hit.hit_def">{{ hit.hit_def || '无描述' }}</span>
        <NTag :type="identityColor" size="small">{{ hit.identity_percent.toFixed(1) }}%</NTag>
      </div>
    </template>

    <template #header-extra>
      <NButton text size="tiny" @click="expanded = !expanded">
        <template #icon>
          <ChevronDownOutline v-if="expanded" />
          <ChevronForwardOutline v-else />
        </template>
        {{ expanded ? '收起' : '对齐' }}
      </NButton>
    </template>

    <div class="stats-grid">
      <div v-for="(item, idx) in statItems" :key="idx" class="stat-item">
        <span class="stat-label">{{ item.label }}</span>
        <span class="stat-value">{{ item.value }}</span>
      </div>
    </div>

    <div class="bar-section">
      <div class="bar-label">Query 覆盖位置</div>
      <BlastAlignmentBar
        :hit-len="queryLen"
        :hsps="barHsps"
        :bar-height="12"
        @select="expanded = true"
      />
    </div>

    <BlastSequenceAlignment
      v-if="expanded && hit.best_hsp"
      :query-seq="hit.best_hsp.query_seq"
      :hit-seq="hit.best_hsp.hit_seq"
      :midline="hit.best_hsp.midline"
      :query-from="hit.best_hsp.query_from"
      :hit-from="hit.best_hsp.hit_from"
      :line-length="60"
    />
  </NCard>
</template>

<style scoped>
.blast-hit-card {
  min-width: 0;
  margin-bottom: 10px;
}
.blast-hit-card :deep(.n-card__content) {
  padding: 12px 16px;
}
.hit-header {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
  font-size: 13px;
}
.hit-title {
  font-weight: 600;
}
.hit-id-tag {
  font-size: 12px;
}
.hit-desc {
  font-size: 12px;
  color: var(--neutral-text-3);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}
.stat-item {
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--neutral-bg);
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-label {
  display: block;
  color: var(--neutral-text-3);
  font-size: 12px;
}
.stat-value {
  display: block;
  margin-top: 3px;
  color: var(--neutral-text-1);
  font-size: 14px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.bar-section {
  margin-bottom: 8px;
}
.bar-label {
  font-size: 11px;
  color: var(--neutral-text-3);
  margin-bottom: 4px;
}
@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
