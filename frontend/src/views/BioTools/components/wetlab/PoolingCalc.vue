<script setup lang="ts">
import { computed, reactive } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NIcon, NInput, NInputNumber } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { AddOutline, CopyOutline, SparklesOutline, TrashOutline } from '@vicons/ionicons5'
import {
  computePooling, formatNum, genSamplePooling, type PoolLibrary, type PoolRow,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const sample = genSamplePooling()
const state = reactive({
  libraries: sample.libraries.map((l) => ({ ...l })) as PoolLibrary[],
  targetConc: sample.targetConc as number | null,
  targetVolume: sample.targetVolume as number | null,
})

const result = computed(() =>
  computePooling({
    libraries: state.libraries,
    targetConc: state.targetConc ?? 0,
    targetVolume: state.targetVolume ?? 0,
  }),
)

const columns: DataTableColumns<PoolRow> = [
  { title: '文库', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '摩尔浓度 (nM)', key: 'molarConc', width: 128,
    render: (r) => formatNum(r.molarConc),
  },
  {
    title: '需吸取 (µL)', key: 'volume', width: 110,
    render: (r) => formatNum(r.volume),
  },
]

function addLibrary() {
  state.libraries.push({ name: '', massConc: 0, avgSize: 0 })
}

function removeLibrary(idx: number) {
  state.libraries.splice(idx, 1)
}

function loadSample() {
  const s = genSamplePooling()
  state.libraries = s.libraries.map((l) => ({ ...l }))
  state.targetConc = s.targetConc
  state.targetVolume = s.targetVolume
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const lines = r.rows.map(
    (row) => `- ${row.name}：${formatNum(row.molarConc)} nM，吸取 ${formatNum(row.volume)} µL`,
  )
  return [
    `【NGS 文库等摩尔 Pooling】目标 ${formatNum(state.targetConc)} nM / ${formatNum(state.targetVolume)} µL`,
    ...lines,
    `补加 EB/水：${formatNum(r.diluentVolume)} µL`,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">NGS 文库等摩尔 Pooling 计算</div>
        <div class="wlc-desc">按各文库质量浓度与平均片段大小换算摩尔浓度，等摩尔混合至目标浓度与体积。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-stack">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">目标总摩尔浓度</span>
          <NInputNumber v-model:value="state.targetConc" size="small" :show-button="false" :min="0" placeholder="如 4" style="flex: 1" />
          <span class="wlc-unit-fixed">nM</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">目标总体积</span>
          <NInputNumber v-model:value="state.targetVolume" size="small" :show-button="false" :min="0" placeholder="如 20" style="flex: 1" />
          <span class="wlc-unit-fixed">µL</span>
        </div>
        <div>
          <div class="wlc-panel-title">各文库（名称 / 质量浓度 ng/µL / 平均片段大小 bp）</div>
          <div class="wlc-dyn">
            <div v-for="(l, idx) in state.libraries" :key="idx" class="wlc-dyn-row">
              <NInput v-model:value="l.name" size="small" class="grow" placeholder="文库名称" />
              <NInputNumber v-model:value="l.massConc" size="small" :show-button="false" :min="0" placeholder="ng/µL" style="width: 96px" />
              <NInputNumber v-model:value="l.avgSize" size="small" :show-button="false" :min="0" placeholder="bp" style="width: 96px" />
              <NButton size="tiny" quaternary type="error" :disabled="state.libraries.length <= 1" @click="removeLibrary(idx)">
                <template #icon><NIcon><TrashOutline /></NIcon></template>
              </NButton>
            </div>
            <NButton size="tiny" text type="primary" @click="addLibrary">
              <template #icon><NIcon><AddOutline /></NIcon></template>
              添加文库
            </NButton>
          </div>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              各文库等摩尔混合，需补加 EB/水 <b>{{ formatNum(result.diluentVolume) }} µL</b>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), 'Pooling 方案')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <NDataTable size="small" class="wlc-table" :columns="columns" :data="result.rows" :bordered="false" :pagination="false" />
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          摩尔浓度 (nM) = 质量浓度 (ng/µL) × 10⁶ / (平均片段大小 × 660)；
          等摩尔混合时每个文库贡献总摩尔数的 1/N，吸取体积 = 目标摩尔数 / 文库摩尔浓度。
        </div>
      </div>
    </div>
  </NCard>
</template>
