<script setup lang="ts">
import { computed, reactive } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NIcon, NInput, NInputNumber, NSwitch, NTag } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { AddOutline, CopyOutline, SparklesOutline, TrashOutline } from '@vicons/ionicons5'
import {
  computeMasterMix, formatNum, genSampleMasterMix,
  type MasterMixComponent, type MasterMixRow,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const sample = genSampleMasterMix()
const state = reactive({
  components: sample.components.map((c) => ({ ...c })) as MasterMixComponent[],
  reactionCount: sample.reactionCount as number | null,
  extraPercent: sample.extraPercent as number | null,
})

const result = computed(() =>
  computeMasterMix({
    components: state.components,
    reactionCount: state.reactionCount ?? 0,
    extraPercent: state.extraPercent ?? 0,
  }),
)

const columns: DataTableColumns<MasterMixRow> = [
  { title: '组分', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '类型', key: 'isTemplate', width: 78,
    render: (r) => (r.isTemplate ? '模板' : '预混'),
  },
  {
    title: '每孔 (µL)', key: 'perReaction', width: 96,
    render: (r) => formatNum(r.perReaction),
  },
  {
    title: '总配制量 (µL)', key: 'total', width: 120,
    render: (r) => formatNum(r.total),
  },
]

function addComponent() {
  state.components.push({ name: '', perReaction: 0, isTemplate: false })
}

function removeComponent(idx: number) {
  state.components.splice(idx, 1)
}

function loadSample() {
  const s = genSampleMasterMix()
  state.components = s.components.map((c) => ({ ...c }))
  state.reactionCount = s.reactionCount
  state.extraPercent = s.extraPercent
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const lines = r.rows.map(
    (row) => `- ${row.name}${row.isTemplate ? '（模板）' : ''}：每孔 ${formatNum(row.perReaction)} µL，总 ${formatNum(row.total)} µL`,
  )
  return [
    `【PCR Master Mix 批量配制】${state.reactionCount} 个反应 + ${state.extraPercent ?? 0}% 损耗`,
    ...lines,
    `预混液每孔合计：${formatNum(r.mixPerReaction)} µL；预混液总配制量：${formatNum(r.mixTotal)} µL`,
    `单反应体系总体积：${formatNum(r.totalReactionVolume)} µL`,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">PCR 体系与 Master Mix 批量配制</div>
        <div class="wlc-desc">按反应数与损耗余量计算预混液各组分总添加量，模板单独列出、不计损耗。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-stack">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">反应样品数 N</span>
          <NInputNumber v-model:value="state.reactionCount" size="small" :show-button="false" :min="1" placeholder="如 96" style="flex: 1" />
          <span class="wlc-unit-fixed">个反应</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">预损耗百分比 P</span>
          <NInputNumber v-model:value="state.extraPercent" size="small" :show-button="false" :min="0" placeholder="如 10" style="flex: 1" />
          <span class="wlc-unit-fixed">%</span>
        </div>
        <div>
          <div class="wlc-panel-title">各组分单孔用量</div>
          <div class="wlc-dyn">
            <div v-for="(c, idx) in state.components" :key="idx" class="wlc-dyn-row">
              <NInput v-model:value="c.name" size="small" class="grow" placeholder="组分名称，如 2× Master Mix" />
              <NInputNumber v-model:value="c.perReaction" size="small" :show-button="false" :min="0" placeholder="µL" style="width: 96px" />
              <NTag size="small" :bordered="false" :type="c.isTemplate ? 'warning' : 'info'">模板</NTag>
              <NSwitch v-model:value="c.isTemplate" size="small" />
              <NButton size="tiny" quaternary type="error" :disabled="state.components.length <= 1" @click="removeComponent(idx)">
                <template #icon><NIcon><TrashOutline /></NIcon></template>
              </NButton>
            </div>
            <NButton size="tiny" text type="primary" @click="addComponent">
              <template #icon><NIcon><AddOutline /></NIcon></template>
              添加组分
            </NButton>
          </div>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              预混液每孔 <b>{{ formatNum(result.mixPerReaction) }} µL</b>，总配制 <b>{{ formatNum(result.mixTotal) }} µL</b>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '配制方案')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">单反应体系总体积 {{ formatNum(result.totalReactionVolume) }} µL（含模板）；已计入 {{ state.extraPercent ?? 0 }}% 损耗余量。</div>
          <NDataTable size="small" class="wlc-table" :columns="columns" :data="result.rows" :bordered="false" :pagination="false" />
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          单组分总配制量 = 单孔用量 × N × (1 + P%)。模板不计入预混液、不加损耗，单独按 N 倍准备。
        </div>
      </div>
    </div>
  </NCard>
</template>
