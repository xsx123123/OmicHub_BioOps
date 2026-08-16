<script setup lang="ts">
import { computed, ref } from 'vue'

interface Highlight {
  start: number
  end: number
  color: string
  label: string
}

const props = withDefaults(defineProps<{
  sequence: string
  highlights?: Highlight[]
}>(), {
  highlights: () => [],
})

const BASES_PER_ROW = 80
const ROW_HEIGHT = 28
const VIEWPORT_HEIGHT = 360
const BUFFER_ROWS = 6
const scrollTop = ref(0)

const totalRows = computed(() => Math.ceil(props.sequence.length / BASES_PER_ROW))
const startRow = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER_ROWS))
const visibleCount = Math.ceil(VIEWPORT_HEIGHT / ROW_HEIGHT) + BUFFER_ROWS * 2
const endRow = computed(() => Math.min(totalRows.value, startRow.value + visibleCount))
const visibleRows = computed(() => Array.from({ length: Math.max(0, endRow.value - startRow.value) }, (_, index) => {
  const rowIndex = startRow.value + index
  const start = rowIndex * BASES_PER_ROW
  return { rowIndex, start, end: Math.min(props.sequence.length, start + BASES_PER_ROW), text: props.sequence.slice(start, start + BASES_PER_ROW) }
}))
const rulerStep = computed(() => {
  if (props.sequence.length <= 500) return 50
  const roughStep = Math.max(50, Math.ceil(props.sequence.length / 10))
  return Math.ceil(roughStep / 50) * 50
})
const rulerTicks = computed(() => {
  const ticks: number[] = [1]
  for (let position = rulerStep.value; position < props.sequence.length; position += rulerStep.value) ticks.push(position)
  if (props.sequence.length > 1) ticks.push(props.sequence.length)
  return [...new Set(ticks)]
})

function highlightForPosition(position: number): Highlight | undefined {
  return props.highlights.find((highlight) => position >= highlight.start && position <= highlight.end)
}

function baseClass(base: string): string {
  const normalized = base.toUpperCase()
  return ['A', 'T', 'U', 'C', 'G'].includes(normalized) ? `base-${normalized}` : 'base-other'
}

function onScroll(event: Event) {
  scrollTop.value = (event.currentTarget as HTMLElement).scrollTop
}
</script>

<template>
  <section class="sequence-viewer" aria-label="带坐标标尺的序列查看器">
    <div class="viewer-legend">
      <span><i class="base-A" />A</span><span><i class="base-T" />T/U</span><span><i class="base-C" />C</span><span><i class="base-G" />G</span>
    </div>
    <div class="overview-ruler" aria-label="全序列坐标标尺">
      <div class="ruler-line">
        <span
          v-for="tick in rulerTicks"
          :key="tick"
          class="ruler-tick"
          :style="{ left: `${Math.max(0, (tick - 1) / Math.max(1, sequence.length - 1) * 100)}%` }"
        >{{ tick.toLocaleString() }}</span>
      </div>
      <div class="highlight-track" aria-label="ORF 与 Motif 高亮轨道">
        <span
          v-for="highlight in highlights"
          :key="`${highlight.label}-${highlight.start}-${highlight.end}`"
          :title="`${highlight.label}: ${highlight.start.toLocaleString()}–${highlight.end.toLocaleString()}`"
          :style="{
            left: `${(highlight.start - 1) / Math.max(1, sequence.length) * 100}%`,
            width: `${Math.max(0.35, (highlight.end - highlight.start + 1) / Math.max(1, sequence.length) * 100)}%`,
            background: highlight.color,
          }"
        />
      </div>
    </div>
    <div class="viewer-viewport" :style="{ height: `${VIEWPORT_HEIGHT}px` }" tabindex="0" @scroll="onScroll">
      <div class="viewer-spacer" :style="{ height: `${totalRows * ROW_HEIGHT}px` }">
        <div
          v-for="row in visibleRows"
          :key="row.rowIndex"
          class="sequence-row"
          :style="{ transform: `translateY(${row.rowIndex * ROW_HEIGHT}px)` }"
        >
          <span class="coordinate">{{ (row.start + 1).toLocaleString() }}</span>
          <span class="bases">
            <span
              v-for="(base, offset) in row.text"
              :key="`${row.start}-${offset}`"
              :class="baseClass(base)"
              :title="highlightForPosition(row.start + offset + 1)?.label"
              :style="highlightForPosition(row.start + offset + 1) ? { background: highlightForPosition(row.start + offset + 1)?.color } : undefined"
            >{{ base }}</span>
          </span>
          <span class="coordinate coordinate-end">{{ row.end.toLocaleString() }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sequence-viewer {
  min-width: 0;
}

.viewer-legend {
  display: flex;
  gap: var(--space-md);
  margin-bottom: var(--space-sm);
  color: var(--neutral-text-3);
  font-size: 11px;
}

.viewer-legend span {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
}

.viewer-legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}

.viewer-viewport {
  position: relative;
  overflow: auto;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
}

.overview-ruler {
  margin-bottom: var(--space-sm);
  padding: 0 6px;
}

.ruler-line {
  position: relative;
  height: 28px;
  border-bottom: 1px solid var(--neutral-border);
}

.ruler-tick {
  position: absolute;
  bottom: 5px;
  color: var(--neutral-text-3);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 9px;
  font-variant-numeric: tabular-nums;
  transform: translateX(-50%);
  white-space: nowrap;
}

.ruler-tick::after {
  position: absolute;
  bottom: -6px;
  left: 50%;
  width: 1px;
  height: 5px;
  background: var(--neutral-border);
  content: '';
}

.highlight-track {
  position: relative;
  height: 10px;
  margin-top: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--neutral-hover);
}

.highlight-track span {
  position: absolute;
  top: 2px;
  height: 6px;
  border-radius: 999px;
  cursor: help;
}

.viewer-spacer {
  position: relative;
  min-width: 860px;
}

.sequence-row {
  position: absolute;
  top: 0;
  left: 0;
  display: grid;
  grid-template-columns: 72px minmax(640px, 1fr) 72px;
  align-items: center;
  width: 100%;
  height: 28px;
  padding: 0 var(--space-sm);
  box-sizing: border-box;
  border-bottom: 1px solid color-mix(in srgb, var(--neutral-border) 65%, transparent);
}

.coordinate {
  color: var(--neutral-text-3);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.coordinate-end {
  text-align: right;
}

.bases {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.bases > span {
  border-radius: 2px;
}

.base-A { color: var(--success-color, var(--arco-success)); background-color: color-mix(in srgb, var(--success-color, var(--arco-success)) 14%, transparent); }
.base-T, .base-U { color: var(--error-color, var(--arco-danger)); background-color: color-mix(in srgb, var(--error-color, var(--arco-danger)) 12%, transparent); }
.base-C { color: var(--primary-color, var(--arco-primary)); background-color: color-mix(in srgb, var(--primary-color, var(--arco-primary)) 12%, transparent); }
.base-G { color: var(--warning-color, var(--arco-warning)); background-color: color-mix(in srgb, var(--warning-color, var(--arco-warning)) 14%, transparent); }
.base-other { color: var(--neutral-text-2); }
</style>
