<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NRadioButton, NRadioGroup } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import { computeBeads, formatNum, type BeadsMode } from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const mode = ref<BeadsMode>('single')
const sampleVolume = ref<number | null>(50)
const ratio1 = ref<number | null>(0.8)
const ratio2 = ref<number | null>(0.8)

const result = computed(() =>
  computeBeads({
    mode: mode.value,
    sampleVolume: sampleVolume.value ?? 0,
    ratio1: ratio1.value ?? 0,
    ratio2: ratio2.value ?? 0,
  }),
)

function loadSample() {
  mode.value = 'double'
  sampleVolume.value = 50
  ratio1.value = 0.6
  ratio2.value = 0.8
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const lines = [`【磁珠纯化与选段】样品 ${formatNum(sampleVolume.value)} µL`]
  if (mode.value === 'single') {
    lines.push(`加入磁珠：${formatNum(r.beads1)} µL（${formatNum(ratio1.value)}×）`)
  } else {
    lines.push(
      `第一步磁珠：${formatNum(r.beads1)} µL（${formatNum(ratio1.value)}×），转移上清 ${formatNum(r.supernatant)} µL`,
      `第二步补加磁珠：${formatNum(r.beads2)} µL（至 ${formatNum(ratio2.value)}×）`,
    )
  }
  lines.push(r.elutionHint)
  return lines.join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">磁珠纯化与选段比例计算 (AMPure XP)</div>
        <div class="wlc-desc">DNA 建库磁珠纯化及双向选段，按比例计算磁珠加入量与上清转移体积。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">选段类型</span>
          <NRadioGroup v-model:value="mode" size="small">
            <NRadioButton value="single">单向纯化</NRadioButton>
            <NRadioButton value="double">双向选段</NRadioButton>
          </NRadioGroup>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">样品总体积</span>
          <NInputNumber v-model:value="sampleVolume" size="small" :show-button="false" :min="0" placeholder="如 50" style="flex: 1" />
          <span class="wlc-unit-fixed">µL</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">{{ mode === 'single' ? '磁珠比例' : '第一步比例' }}</span>
          <NInputNumber v-model:value="ratio1" size="small" :show-button="false" :min="0" :step="0.1" placeholder="如 0.8" style="flex: 1" />
          <span class="wlc-unit-fixed">×</span>
        </div>
        <div v-if="mode === 'double'" class="wlc-row">
          <span class="wlc-label">目标总比例</span>
          <NInputNumber v-model:value="ratio2" size="small" :show-button="false" :min="0" :step="0.1" placeholder="如 0.8" style="flex: 1" />
          <span class="wlc-unit-fixed">×</span>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              <template v-if="mode === 'single'">
                加入磁珠 <b>{{ formatNum(result.beads1) }} µL</b>
              </template>
              <template v-else>
                第一步磁珠 <b>{{ formatNum(result.beads1) }} µL</b>，第二步补加 <b>{{ formatNum(result.beads2) }} µL</b>
              </template>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '磁珠方案')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">
            <template v-if="mode === 'double'">第一步磁吸后转移上清 {{ formatNum(result.supernatant) }} µL。</template>
            {{ result.elutionHint }}
          </div>
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          单向：磁珠体积 = 样品体积 × 比例。双向选段：第一步按比例 1 结合大片段并转移上清，
          第二步补加磁珠使总比例达到比例 2 以结合目标片段。
        </div>
      </div>
    </div>
  </NCard>
</template>
