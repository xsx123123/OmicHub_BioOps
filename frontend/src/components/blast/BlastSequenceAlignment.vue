<script setup lang="ts">
import { computed } from 'vue'

interface AlignmentLine {
  q: string
  m: string
  s: string
  qStart: number
  sStart: number
}

const props = withDefaults(defineProps<{
  querySeq: string
  hitSeq: string
  midline: string
  queryFrom: number
  hitFrom: number
  lineLength?: number
}>(), {
  lineLength: 60,
})

const lines = computed<AlignmentLine[]>(() => {
  const result: AlignmentLine[] = []
  const { querySeq, hitSeq, midline, queryFrom, hitFrom, lineLength } = props
  for (let i = 0; i < querySeq.length; i += lineLength) {
    const qLine = querySeq.slice(i, i + lineLength)
    const mLine = midline.slice(i, i + lineLength)
    const sLine = hitSeq.slice(i, i + lineLength)

    const qGapsBefore = (querySeq.slice(0, i).match(/-/g) || []).length
    const sGapsBefore = (hitSeq.slice(0, i).match(/-/g) || []).length

    result.push({
      q: qLine,
      m: mLine,
      s: sLine,
      qStart: queryFrom + i - qGapsBefore,
      sStart: hitFrom + i - sGapsBefore,
    })
  }
  return result
})

function getBaseStyle(qBase: string, mChar: string): Record<string, string> {
  if (mChar === '|') {
    return { color: 'var(--arco-success)', fontWeight: '700', backgroundColor: 'var(--arco-success-light)' }
  }
  if (mChar === '+') {
    return { color: 'var(--arco-warning)', fontWeight: '600', backgroundColor: 'var(--arco-warning-light)' }
  }
  if (qBase === '-') {
    return { color: 'var(--neutral-text-3)', fontWeight: '400' }
  }
  return { color: 'var(--arco-danger)', fontWeight: '600', backgroundColor: 'var(--arco-danger-light)' }
}
</script>

<template>
  <div class="blast-sequence-alignment">
    <div class="alignment-title">序列比对详情</div>
    <div class="alignment-body">
      <div
        v-for="(line, idx) in lines"
        :key="idx"
        class="alignment-block"
      >
        <div class="alignment-row">
          <span class="row-label">Query {{ line.qStart }}</span>
          <span class="row-sequence">
            <span
              v-for="(base, i) in line.q.split('')"
              :key="i"
              class="base"
              :style="getBaseStyle(base, line.m[i])"
            >{{ base }}</span>
          </span>
          <span class="row-end">{{ line.qStart + line.q.replace(/-/g, '').length - 1 }}</span>
        </div>
        <div class="alignment-row midline-row">
          <span class="row-label" />
          <span class="row-sequence midline">{{ line.m }}</span>
        </div>
        <div class="alignment-row">
          <span class="row-label">Sbjct {{ line.sStart }}</span>
          <span class="row-sequence">
            <span
              v-for="(base, i) in line.s.split('')"
              :key="i"
              class="base"
              :style="getBaseStyle(base, line.m[i])"
            >{{ base }}</span>
          </span>
          <span class="row-end">{{ line.sStart + line.s.replace(/-/g, '').length - 1 }}</span>
        </div>
      </div>
    </div>
    <div class="alignment-legend">
      <span><span class="legend-match">AAA</span> 完全匹配 (|)</span>
      <span><span class="legend-similar">AAA</span> 相似匹配 (+)</span>
      <span><span class="legend-mismatch">AAA</span> 错配</span>
      <span><span class="legend-gap">---</span> Gap</span>
    </div>
  </div>
</template>

<style scoped>
.blast-sequence-alignment {
  margin-top: 8px;
  padding: 12px;
  background: var(--neutral-bg);
  border-radius: 8px;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
}
.alignment-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
  margin-bottom: 10px;
}
.alignment-body {
  overflow-x: auto;
}
.alignment-block {
  margin-bottom: 10px;
  line-height: 1.8;
}
.alignment-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  white-space: nowrap;
}
.midline-row {
  margin-left: 70px;
}
.row-label {
  width: 70px;
  text-align: right;
  color: var(--neutral-text-3);
  font-size: 11px;
  flex-shrink: 0;
}
.row-sequence {
  display: inline-flex;
  letter-spacing: 0.5px;
}
.midline {
  color: var(--neutral-text-3);
}
.base {
  padding: 0 1px;
}
.row-end {
  color: var(--neutral-text-3);
  font-size: 11px;
  margin-left: 4px;
}
.alignment-legend {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--neutral-border);
  font-size: 12px;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.legend-match {
  color: var(--arco-success);
  font-weight: 700;
  background-color: var(--arco-success-light);
  padding: 0 2px;
}
.legend-similar {
  color: var(--arco-warning);
  font-weight: 600;
  background-color: var(--arco-warning-light);
  padding: 0 2px;
}
.legend-mismatch {
  color: var(--arco-danger);
  font-weight: 600;
  background-color: var(--arco-danger-light);
  padding: 0 2px;
}
.legend-gap {
  color: var(--neutral-text-3);
  padding: 0 2px;
}
</style>
