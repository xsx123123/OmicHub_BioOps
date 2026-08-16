<script setup lang="ts">
/**
 * 数据类型分布 —— 轻量 NProgress 条，按 file_type 聚合存储占比（禁用 ECharts）
 */
import { computed } from 'vue'
import { NProgress } from 'naive-ui'
import type { DataFile } from '@/types'

const props = defineProps<{ files: DataFile[] }>()

const TYPE_META: Record<string, { label: string; color: string }> = {
  fastq: { label: 'FASTQ', color: '#165DFF' },
  bam: { label: 'BAM', color: '#00B42A' },
  vcf: { label: 'VCF', color: '#FF7D00' },
  count_matrix: { label: '表达矩阵', color: '#0FC6C2' },
  h5ad: { label: 'H5AD', color: '#8E54E9' },
  rds: { label: 'RDS', color: '#B96CD4' },
  meta: { label: '元数据', color: '#86909c' },
  report: { label: '报告', color: '#722ED1' },
  image: { label: '图片', color: '#EB2F96' },
  other: { label: '其他', color: '#C9CDD4' },
}

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`
}

const breakdown = computed(() => {
  const totals: Record<string, number> = {}
  let grand = 0
  for (const f of props.files) {
    totals[f.file_type] = (totals[f.file_type] || 0) + f.size
    grand += f.size
  }
  return Object.entries(totals)
    .map(([type, size]) => ({
      type,
      meta: TYPE_META[type] || TYPE_META.other,
      size,
      percent: grand > 0 ? Math.round((size / grand) * 100) : 0,
    }))
    .sort((a, b) => b.size - a.size)
    .slice(0, 6)
})
</script>

<template>
  <div class="widget">
    <h3 class="widget-title">数据类型分布</h3>
    <div v-if="breakdown.length" class="type-list">
      <div v-for="item in breakdown" :key="item.type" class="type-row">
        <div class="type-head">
          <span class="type-dot" :style="{ background: item.meta.color }" />
          <span class="type-name">{{ item.meta.label }}</span>
          <span class="type-size">{{ formatSize(item.size) }}</span>
          <span class="type-pct">{{ item.percent }}%</span>
        </div>
        <NProgress
          :percentage="item.percent"
          :height="5"
          :show-indicator="false"
          :color="item.meta.color"
          rail-color="rgba(0,0,0,0.06)"
        />
      </div>
    </div>
    <p v-else class="empty-hint">暂无文件数据</p>
  </div>
</template>

<style scoped>
.widget {
  background: var(--neutral-card, #fff);
  border: 1px solid var(--neutral-border, #e5e6eb);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.widget-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1, #1d2129);
  margin: 0 0 14px;
}
.type-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.type-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.type-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.type-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.type-name {
  color: var(--neutral-text-2, #4e5969);
  font-weight: 500;
}
.type-size {
  color: var(--neutral-text-3, #86909c);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
}
.type-pct {
  color: var(--neutral-text-1, #1d2129);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  width: 34px;
  text-align: right;
}
.empty-hint {
  font-size: 12px;
  color: var(--neutral-text-3, #86909c);
  margin: 0;
  text-align: center;
  padding: 12px 0;
}
</style>
