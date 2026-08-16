<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NSelect } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import {
  DIL_CONC_UNITS, DIL_VOL_UNITS, formatNum, solveDilution,
  type DilConcUnit, type DilVolUnit,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const c1 = ref<number | null>(100)
const c2 = ref<number | null>(10)
const v2 = ref<number | null>(100)
const concUnit = ref<DilConcUnit>('µM')
const volUnit = ref<DilVolUnit>('µL')

const result = computed(() =>
  solveDilution({ c1: c1.value, c2: c2.value, v2: v2.value, concUnit: concUnit.value, volUnit: volUnit.value }),
)

function loadSample() {
  c1.value = 100
  c2.value = 10
  v2.value = 100
  concUnit.value = 'µM'
  volUnit.value = 'µL'
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  return [
    `【母液稀释】${formatNum(c1.value)} ${concUnit.value} → ${formatNum(c2.value)} ${concUnit.value}，终体积 ${formatNum(v2.value)} ${volUnit.value}`,
    `取母液 ${formatNum(r.v1uL)} µL + 水/溶剂 ${formatNum(r.solventuL)} µL`,
  ].join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">母液稀释计算 (C1V1 = C2V2)</div>
        <div class="wlc-desc">由母液浓度、目标浓度与目标体积，计算需取母液体积与补加溶剂量。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">母液浓度 C1</span>
          <NInputNumber v-model:value="c1" size="small" :show-button="false" :min="0" placeholder="如 100" style="flex: 1" />
          <NSelect v-model:value="concUnit" size="small" class="wlc-unit" :options="DIL_CONC_UNITS.map((u) => ({ label: u, value: u }))" />
        </div>
        <div class="wlc-row">
          <span class="wlc-label">目标浓度 C2</span>
          <NInputNumber v-model:value="c2" size="small" :show-button="false" :min="0" placeholder="如 10" style="flex: 1" />
          <span class="wlc-unit-fixed">{{ concUnit }}</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">目标体积 V2</span>
          <NInputNumber v-model:value="v2" size="small" :show-button="false" :min="0" placeholder="如 100" style="flex: 1" />
          <NSelect v-model:value="volUnit" size="small" class="wlc-unit" :options="DIL_VOL_UNITS.map((u) => ({ label: u, value: u }))" />
        </div>
      </div>

      <div class="wlc-result">
        <NAlert v-if="result.error" type="warning" :bordered="false">{{ result.error }}</NAlert>
        <template v-else-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              取母液 <b>{{ formatNum(result.v1uL) }} µL</b> + 水/溶剂 <b>{{ formatNum(result.solventuL) }} µL</b>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '稀释方案')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">母液占终体积 {{ formatNum(result.ratio, 3) }}%（稀释 {{ formatNum((c1 ?? 0) / (c2 ?? 1), 3) }} 倍）。</div>
        </template>
        <div v-else class="wlc-empty">输入 C1、C2、V2 后自动计算</div>
        <div class="wlc-formula">
          C1·V1 = C2·V2 → V1 = C2·V2 / C1，溶剂量 = V2 − V1。目标浓度高于母液浓度（C2 &gt; C1）时无法通过稀释达成。
        </div>
      </div>
    </div>
  </NCard>
</template>
