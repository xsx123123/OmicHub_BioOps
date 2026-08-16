<script setup lang="ts">
import { NCard, NTag, NTooltip } from 'naive-ui'

const props = defineProps<{
  params: Record<string, unknown>
}>()

const items = [
  { label: 'E-value', key: 'evalue', desc: '随机出现同等匹配的期望次数，越小越严格。' },
  { label: '最大匹配数', key: 'max_target_seqs', desc: '限制返回的目标序列数量，避免结果过大。' },
  { label: 'Word Size', key: 'word_size', desc: '初始种子长度；越小越敏感，但计算更慢。' },
  { label: 'Gap Open/Extend', key: 'gap', desc: '控制插入缺失的开启和延伸罚分。' },
]

function getValue(item: typeof items[number]): string {
  if (item.key === 'gap') {
    const open = props.params.gapopen
    const extend = props.params.gapextend
    return open ? `${open}/${extend}` : '默认'
  }
  const value = props.params[item.key]
  return value !== undefined && value !== null ? String(value) : '默认'
}
</script>

<template>
  <NCard size="small" title="查询参数" class="params-info-card">
    <div class="params-row">
      <NTooltip
        v-for="item in items"
        :key="item.key"
        trigger="hover"
        placement="top"
      >
        <template #trigger>
          <div class="param-item">
            <span class="param-label">{{ item.label }}:</span>
            <NTag size="small" class="param-value">{{ getValue(item) }}</NTag>
          </div>
        </template>
        <span style="font-size: 12px;">{{ item.desc }}</span>
      </NTooltip>
    </div>
  </NCard>
</template>

<style scoped>
.params-info-card {
  margin-bottom: 12px;
}
.params-info-card :deep(.n-card__content) {
  padding: 8px 12px;
}
.params-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.param-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  cursor: help;
}
.param-label {
  color: #6b7280;
}
.param-value {
  font-size: 12px;
}
</style>
