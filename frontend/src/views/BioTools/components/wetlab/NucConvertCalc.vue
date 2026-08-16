<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NRadioButton, NRadioGroup, NSelect } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import {
  NUC_MW_PER_NT, formatNum, ngUlToNm, nmToNgUl, type NucleicType,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const direction = ref<'ng2nm' | 'nm2ng'>('ng2nm')
const conc = ref<number | null>(50)
const length = ref<number | null>(3000)
const nucType = ref<NucleicType>('dsDNA')

const typeOptions = [
  { label: `双链 DNA（${NUC_MW_PER_NT.dsDNA} g/mol/bp）`, value: 'dsDNA' },
  { label: `单链 DNA（${NUC_MW_PER_NT.ssDNA} g/mol/nt）`, value: 'ssDNA' },
  { label: `单链 RNA（${NUC_MW_PER_NT.ssRNA} g/mol/nt）`, value: 'ssRNA' },
]

const result = computed(() => {
  const c = conc.value
  const len = length.value
  if (c === null || len === null) return null
  return direction.value === 'ng2nm' ? ngUlToNm(c, len, nucType.value) : nmToNgUl(c, len, nucType.value)
})

function loadSample() {
  direction.value = 'ng2nm'
  conc.value = 50
  length.value = 3000
  nucType.value = 'dsDNA'
}

function buildSummary(): string {
  const r = result.value
  if (!r || !r.valid) return ''
  return `【核酸浓度换算】${formatNum(r.ngPerUl)} ng/µL ⇌ ${formatNum(r.nM)} nM（${formatNum(length.value)} ${nucType.value === 'dsDNA' ? 'bp' : 'nt'}，MW ≈ ${formatNum(r.mw)} g/mol）`
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">核酸浓度换算 (ng/µL ↔ nM)</div>
        <div class="wlc-desc">按核酸类型与长度在质量浓度与摩尔浓度之间互换。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">换算方向</span>
          <NRadioGroup v-model:value="direction" size="small">
            <NRadioButton value="ng2nm">ng/µL → nM</NRadioButton>
            <NRadioButton value="nm2ng">nM → ng/µL</NRadioButton>
          </NRadioGroup>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">{{ direction === 'ng2nm' ? '浓度 (ng/µL)' : '浓度 (nM)' }}</span>
          <NInputNumber v-model:value="conc" size="small" :show-button="false" :min="0" placeholder="如 50" style="flex: 1" />
        </div>
        <div class="wlc-row">
          <span class="wlc-label">长度</span>
          <NInputNumber v-model:value="length" size="small" :show-button="false" :min="0" placeholder="如 3000" style="flex: 1" />
          <span class="wlc-unit-fixed">bp/nt</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">核酸类型</span>
          <NSelect v-model:value="nucType" size="small" :options="typeOptions" style="flex: 1" />
        </div>
      </div>

      <div class="wlc-result">
        <NAlert v-if="result && result.error" type="warning" :bordered="false">{{ result.error }}</NAlert>
        <template v-else-if="result && result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              <b>{{ formatNum(result.ngPerUl) }}</b> ng/µL ⇌ <b>{{ formatNum(result.nM) }}</b> nM
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '换算结果')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">分子量 ≈ {{ formatNum(result.mw) }} g/mol。</div>
        </template>
        <div v-else class="wlc-empty">输入浓度与长度后自动换算</div>
        <div class="wlc-formula">
          平均分子量：双链 DNA ≈ 660、单链 DNA ≈ 330、单链 RNA ≈ 340 g/mol/bp(nt)。
          分子量 = 长度 × 常数；nM = (ng/µL × 10⁶) / 分子量，ng/µL = nM × 分子量 / 10⁶。
        </div>
      </div>
    </div>
  </NCard>
</template>
