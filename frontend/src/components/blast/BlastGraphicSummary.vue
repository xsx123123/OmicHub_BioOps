<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NTooltip } from 'naive-ui'

interface HitData {
  hit_num: number
  hit_id: string
  hsps: Array<{
    query_from: number
    query_to: number
    identity_percent: number
    evalue: number
    bit_score: number
  }>
}

const props = defineProps<{
  queryLen: number
  hits: HitData[]
}>()

const emit = defineEmits<{ selectHit: [hitNum: number] }>()

const svgWidth = 800
const padding = { left: 96, right: 42, top: 28, bottom: 28 }
const barHeight = 16
const trackGap = 6
const trackHeight = barHeight + trackGap
const legendHeight = 20

const contentHeight = computed(() => 26 + props.hits.length * trackHeight)
const svgHeight = computed(() => padding.top + contentHeight.value + padding.bottom + legendHeight)

function scale(pos: number): number {
  return padding.left + (pos / props.queryLen) * (svgWidth - padding.left - padding.right)
}

function getColor(identity: number): string {
  if (identity >= 90) return '#10b981'
  if (identity >= 70) return '#3b82f6'
  if (identity >= 40) return '#f59e0b'
  return '#ef4444'
}

const rulerY = padding.top + 10
const firstHitY = rulerY + 24

const ticks = computed(() => {
  const roughStep = Math.max(1, props.queryLen / 6)
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude
  const values = [1]
  for (let value = step; value < props.queryLen; value += step) values.push(Math.round(value))
  if (props.queryLen > 1) values.push(props.queryLen)
  return [...new Set(values)]
})

const legendItems = [
  { c: '#10b981', l: '≥90%' },
  { c: '#3b82f6', l: '≥70%' },
  { c: '#f59e0b', l: '≥40%' },
  { c: '#ef4444', l: '<40%' },
]
</script>

<template>
  <NCard size="small" title="Graphic Summary" class="graphic-summary-card">
    <svg
      width="100%"
      :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
      style="font-family: monospace;"
    >
      <!-- Query 标尺标签 -->
      <text
        :x="padding.left - 10"
        :y="rulerY + 4"
        text-anchor="end"
        fill="#6b7280"
        font-size="11"
        font-weight="500"
      >Query</text>

      <!-- 标尺线 -->
      <line
        :x1="padding.left"
        :y1="rulerY"
        :x2="svgWidth - padding.right"
        :y2="rulerY"
        stroke="#d1d5db"
        stroke-width="2"
      />

      <g v-for="tick in ticks" :key="tick">
        <line :x1="scale(tick)" :x2="scale(tick)" :y1="rulerY - 5" :y2="rulerY + 5" stroke="#9ca3af" stroke-width="1" />
        <text :x="scale(tick)" :y="rulerY - 10" text-anchor="middle" fill="#6b7280" font-size="9">{{ tick.toLocaleString() }}</text>
      </g>

      <!-- Hit tracks -->
      <g
        v-for="(hit, idx) in hits"
        :key="hit.hit_num"
      >
        <text
          :x="padding.left - 10"
          :y="firstHitY + idx * trackHeight + barHeight - 3"
          text-anchor="end"
          fill="#374151"
          font-size="11"
        >{{ hit.hit_id }}</text>

        <NTooltip
          v-for="(hsp, hspIdx) in hit.hsps"
          :key="hspIdx"
          placement="top"
          trigger="hover"
        >
          <template #trigger>
            <rect
              :x="scale(hsp.query_from)"
              :y="firstHitY + idx * trackHeight"
              :width="Math.max(scale(hsp.query_to) - scale(hsp.query_from), 3)"
              :height="barHeight"
              rx="4"
              :fill="getColor(hsp.identity_percent)"
              opacity="0.9"
              style="cursor: pointer;"
              @click="emit('selectHit', hit.hit_num)"
            />
          </template>
          <div style="font-size: 12px; line-height: 1.5;">
            <div><strong>{{ hit.hit_id }}</strong> HSP #{{ hspIdx + 1 }}</div>
            <div>Query: {{ hsp.query_from }}-{{ hsp.query_to }}</div>
            <div>Identity: {{ hsp.identity_percent.toFixed(1) }}%</div>
            <div>E: {{ hsp.evalue.toExponential(2) }}</div>
          </div>
        </NTooltip>
      </g>

      <!-- 图例 - 固定在底部，不与任何元素重叠 -->
      <g :transform="`translate(${padding.left}, ${svgHeight - 18})`">
        <text x="0" y="0" font-size="12" fill="#6b7280" font-weight="500">Identity:</text>
        <g
          v-for="(item, i) in legendItems"
          :key="i"
          :transform="`translate(${55 + i * 60}, -8)`"
        >
          <rect width="12" height="12" rx="3" :fill="item.c" />
          <text x="16" y="10" font-size="12" fill="#6b7280">{{ item.l }}</text>
        </g>
      </g>
    </svg>
  </NCard>
</template>

<style scoped>
.graphic-summary-card {
  margin-bottom: 12px;
}
.graphic-summary-card :deep(.n-card__content) {
  padding: 10px 16px 12px;
}
</style>
