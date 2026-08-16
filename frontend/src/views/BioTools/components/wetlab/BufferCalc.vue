<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NIcon, NInputNumber, NSelect } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import {
  BUFFER_RECIPES, formatNum, generateBufferRecipe, type BufferResultRow,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const bufferKey = ref('tae50x')
const volumeMl = ref<number | null>(500)

const recipeOptions = BUFFER_RECIPES.map((r) => ({ label: r.label, value: r.key }))

const result = computed(() => generateBufferRecipe(bufferKey.value, volumeMl.value ?? 0))

const columns: DataTableColumns<BufferResultRow> = [
  { title: '组分', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '称量 / 量取', key: 'amount', width: 130,
    render: (r) => `${formatNum(r.amount)} ${r.unit}`,
  },
]

function loadSample() {
  bufferKey.value = 'tae50x'
  volumeMl.value = 500
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const lines = r.rows.map((row) => `- ${row.name}：${formatNum(row.amount)} ${row.unit}`)
  return [
    `【${r.label} 配方】配制 ${formatNum(volumeMl.value)} mL`,
    ...lines,
    r.note,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">常用缓冲液配方生成器</div>
        <div class="wlc-desc">选择预设缓冲液与目标体积，自动计算各固体（g）与液体（mL）称量值。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">缓冲液类型</span>
          <NSelect v-model:value="bufferKey" size="small" :options="recipeOptions" style="flex: 1" />
        </div>
        <div class="wlc-row">
          <span class="wlc-label">拟配制体积</span>
          <NInputNumber v-model:value="volumeMl" size="small" :show-button="false" :min="0" placeholder="如 500" style="flex: 1" />
          <span class="wlc-unit-fixed">mL</span>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              {{ result.label }} · <b>{{ formatNum(volumeMl) }} mL</b>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '配方')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <NDataTable size="small" class="wlc-table" :columns="columns" :data="result.rows" :bordered="false" :pagination="false" />
          <div class="wlc-sub">{{ result.note }}</div>
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          按每 1 L 标准配方 × (目标体积 / 1000 mL) 等比缩放。具体定容与调 pH 步骤以配方说明为准。
        </div>
      </div>
    </div>
  </NCard>
</template>
