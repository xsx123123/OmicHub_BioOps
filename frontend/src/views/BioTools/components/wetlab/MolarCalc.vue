<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NRadioButton, NRadioGroup, NSelect } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import {
  CONC_FACTORS, MASS_FACTORS, VOL_FACTORS, formatNum, friendlySI, solveMolar, type MolarTarget,
} from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const target = ref<MolarTarget>('mass')
const mw = ref<number | null>(180.16)
const mass = ref<number | null>(18)
const massUnit = ref('mg')
const vol = ref<number | null>(100)
const volUnit = ref('mL')
const conc = ref<number | null>(1)
const concUnit = ref('mM')

const massUnitOptions = Object.keys(MASS_FACTORS).map((u) => ({ label: u, value: u }))
const volUnitOptions = Object.keys(VOL_FACTORS).map((u) => ({ label: u, value: u }))
const concUnitOptions = Object.keys(CONC_FACTORS).map((u) => ({ label: u, value: u }))

const result = computed(() =>
  solveMolar({
    target: target.value,
    mw: target.value === 'mw' ? null : mw.value,
    mass: target.value === 'mass' ? null : mass.value,
    massUnit: massUnit.value,
    volume: target.value === 'volume' ? null : vol.value,
    volUnit: volUnit.value,
    conc: target.value === 'conc' ? null : conc.value,
    concUnit: concUnit.value,
  }),
)

const friendly = computed(() => (result.value.valid ? friendlySI(result.value.value, target.value) : '—'))

function loadSample() {
  target.value = 'mass'
  mw.value = 180.16
  mass.value = 18
  massUnit.value = 'mg'
  vol.value = 100
  volUnit.value = 'mL'
  conc.value = 1
  concUnit.value = 'mM'
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  return `【摩尔浓度换算】${r.label} = ${friendly.value}（${formatNum(r.value)} ${r.unit}）`
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">摩尔浓度 / 质量 / 体积换算</div>
        <div class="wlc-desc">已知分子量、质量、体积、浓度中任意三项，求解第四项。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">要求解的量</span>
          <NRadioGroup v-model:value="target" size="small">
            <NRadioButton value="mass">质量</NRadioButton>
            <NRadioButton value="volume">体积</NRadioButton>
            <NRadioButton value="conc">浓度</NRadioButton>
            <NRadioButton value="mw">分子量</NRadioButton>
          </NRadioGroup>
        </div>
        <div v-if="target !== 'mw'" class="wlc-row">
          <span class="wlc-label">分子量</span>
          <NInputNumber v-model:value="mw" size="small" :show-button="false" :min="0" placeholder="如 180.16" style="flex: 1" />
          <span class="wlc-unit-fixed">g/mol</span>
        </div>
        <div v-if="target !== 'mass'" class="wlc-row">
          <span class="wlc-label">质量</span>
          <NInputNumber v-model:value="mass" size="small" :show-button="false" :min="0" placeholder="如 18" style="flex: 1" />
          <NSelect v-model:value="massUnit" size="small" class="wlc-unit" :options="massUnitOptions" />
        </div>
        <div v-if="target !== 'volume'" class="wlc-row">
          <span class="wlc-label">体积</span>
          <NInputNumber v-model:value="vol" size="small" :show-button="false" :min="0" placeholder="如 100" style="flex: 1" />
          <NSelect v-model:value="volUnit" size="small" class="wlc-unit" :options="volUnitOptions" />
        </div>
        <div v-if="target !== 'conc'" class="wlc-row">
          <span class="wlc-label">浓度</span>
          <NInputNumber v-model:value="conc" size="small" :show-button="false" :min="0" placeholder="如 1" style="flex: 1" />
          <NSelect v-model:value="concUnit" size="small" class="wlc-unit" :options="concUnitOptions" />
        </div>
      </div>

      <div class="wlc-result">
        <NAlert v-if="result.error" type="warning" :bordered="false">{{ result.error }}</NAlert>
        <template v-else-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">{{ result.label }} = <b>{{ friendly }}</b></div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '换算结果')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">SI 值：{{ formatNum(result.value) }} {{ result.unit }}</div>
        </template>
        <div v-else class="wlc-empty">输入其余三项后自动求解</div>
        <div class="wlc-formula">
          n = m / MW（物质的量 = 质量 ÷ 分子量），c = n / V（浓度 = 物质的量 ÷ 体积）。
          已知任意三项即可求解第四项，单位内部统一换算为 SI 后计算。
        </div>
      </div>
    </div>
  </NCard>
</template>
