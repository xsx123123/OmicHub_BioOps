<script setup lang="ts">
import { computed } from 'vue'
import { NTooltip } from 'naive-ui'

interface HspData {
  hit_from: number
  hit_to: number
  identity_percent: number
  evalue: number
  bit_score: number
}

const props = withDefaults(defineProps<{
  hitLen: number
  hsps: HspData[]
  barHeight?: number
  showRuler?: boolean
}>(), {
  barHeight: 14,
  showRuler: true,
})

const emit = defineEmits<{ select: [] }>()

const svgWidth = 700
const padding = computed(() => ({
  left: props.showRuler ? 50 : 10,
  right: 30,
}))
const svgHeight = computed(() => props.barHeight + 32)

const ticks = computed(() => {
  const targetCount = 6
  const roughStep = Math.max(1, props.hitLen / targetCount)
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  const step = nice * magnitude
  const values = [1]
  for (let value = step; value < props.hitLen; value += step) values.push(Math.round(value))
  if (props.hitLen > 1) values.push(props.hitLen)
  return [...new Set(values)]
})

function scale(pos: number): number {
  return padding.value.left + (pos / props.hitLen) * (svgWidth - padding.value.left - padding.value.right)
}

function getColor(identity: number): string {
  if (identity >= 90) return '#10b981'
  if (identity >= 70) return '#3b82f6'
  if (identity >= 40) return '#f59e0b'
  return '#ef4444'
}
</script>

<template>
  <svg
    width="100%"
    :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
    style="font-family: monospace; font-size: 10px;"
  >
    <g v-if="showRuler">
      <line
        :x1="padding.left"
        :y1="barHeight + 14"
        :x2="svgWidth - padding.right"
        :y2="barHeight + 14"
        stroke="var(--neutral-border)"
        stroke-width="1.5"
      />
      <g v-for="tick in ticks" :key="tick">
        <line :x1="scale(tick)" :x2="scale(tick)" :y1="barHeight + 10" :y2="barHeight + 18" stroke="var(--neutral-text-3)" stroke-width="1" />
        <text :x="scale(tick)" :y="barHeight + 30" text-anchor="middle" fill="var(--neutral-text-3)" font-size="9">{{ tick.toLocaleString() }}</text>
      </g>
    </g>

    <NTooltip
      v-for="(hsp, idx) in hsps"
      :key="idx"
      placement="top"
      trigger="hover"
    >
      <template #trigger>
        <rect
          :x="scale(hsp.hit_from)"
          y="6"
          :width="Math.max(scale(hsp.hit_to) - scale(hsp.hit_from), 2)"
          :height="barHeight"
          rx="3"
          :fill="getColor(hsp.identity_percent)"
          opacity="0.9"
          style="cursor: pointer;"
          @click="emit('select')"
        />
      </template>
      <div style="font-size: 12px; line-height: 1.5;">
        <div>Range: {{ hsp.hit_from }}-{{ hsp.hit_to }}</div>
        <div>Identity: {{ hsp.identity_percent.toFixed(1) }}%</div>
        <div>E: {{ hsp.evalue.toExponential(2) }}</div>
      </div>
    </NTooltip>
  </svg>
</template>
