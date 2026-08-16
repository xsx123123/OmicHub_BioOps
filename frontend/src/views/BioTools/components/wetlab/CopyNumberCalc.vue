<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NSelect } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import {
  computeCopyNumber, formatNum, NUC_MW_PER_NT, type NucleicType,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const conc = ref<number | null>(50)
const length = ref<number | null>(3000)
const nucType = ref<NucleicType>('dsDNA')

const typeOptions = [
  { label: `双链 DNA（${NUC_MW_PER_NT.dsDNA} g/mol/bp）`, value: 'dsDNA' },
  { label: `单链 DNA（${NUC_MW_PER_NT.ssDNA} g/mol/nt）`, value: 'ssDNA' },
  { label: `单链 RNA（${NUC_MW_PER_NT.ssRNA} g/mol/nt）`, value: 'ssRNA' },
]

const result = computed(() => computeCopyNumber(conc.value ?? 0, length.value ?? 0, nucType.value))

function loadSample() {
  conc.value = 50
  length.value = 3000
  nucType.value = 'dsDNA'
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const typeLabel = nucType.value === 'dsDNA' ? '双链 DNA' : nucType.value === 'ssDNA' ? '单链 DNA' : '单链 RNA'
  return [
    `【核酸绝对拷贝数计算】${typeLabel}`,
    `浓度：${formatNum(conc.value)} ng/µL；长度：${formatNum(length.value)} ${nucType.value === 'dsDNA' ? 'bp' : 'nt'}`,
    `绝对拷贝数：${formatNum(r.copiesPerUl)} copies/µL`,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">DNA / RNA 绝对拷贝数计算</div>
        <div class="wlc-desc">用于 qPCR 绝对定量、病毒载量与质粒标准品拷贝数换算。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">核酸浓度</span>
          <NInputNumber v-model:value="conc" size="small" :show-button="false" :min="0" placeholder="如 50" style="flex: 1" />
          <span class="wlc-unit-fixed">ng/µL</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">片段长度</span>
          <NInputNumber v-model:value="length" size="small" :show-button="false" :min="0" placeholder="如 3000" style="flex: 1" />
          <span class="wlc-unit-fixed">bp/nt</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">核酸类型</span>
          <NSelect v-model:value="nucType" size="small" :options="typeOptions" style="flex: 1" />
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              <b>{{ formatNum(result.copiesPerUl) }}</b> copies/µL
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '拷贝数结果')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">分子量 ≈ {{ formatNum(result.mw) }} g/mol。</div>
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          Copies/µL = C(ng/µL) × 6.022×10²³ / (长度 × 10⁹ × 每 bp/nt 平均分子量)。
          双链 DNA 660、单链 DNA 330、单链 RNA 340 g/mol。
        </div>
      </div>
    </div>
  </NCard>
</template>
