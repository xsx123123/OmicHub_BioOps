<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCard, NIcon, NInputNumber, NRadioButton, NRadioGroup } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import { formatNum, rcfToRpm, rpmToRcf, type RcfDirection } from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const direction = ref<RcfDirection>('rpm2rcf')
const radius = ref<number | null>(10)
const rpm = ref<number | null>(12000)
const rcf = ref<number | null>(13000)

const output = computed(() => {
  const r = radius.value
  if (r === null || r <= 0) return null
  if (direction.value === 'rpm2rcf') {
    if (rpm.value === null || rpm.value <= 0) return null
    return { label: '相对离心力 RCF', value: rpmToRcf(rpm.value, r), unit: '× g' }
  }
  if (rcf.value === null || rcf.value <= 0) return null
  return { label: '所需转速 RPM', value: rcfToRpm(rcf.value, r), unit: 'rpm' }
})

function loadSample() {
  direction.value = 'rpm2rcf'
  radius.value = 10
  rpm.value = 12000
  rcf.value = 13000
}

function buildSummary(): string {
  if (!output.value) return ''
  return direction.value === 'rpm2rcf'
    ? `【RPM → RCF】转头半径 ${formatNum(radius.value)} cm，${formatNum(rpm.value)} rpm ≈ ${formatNum(output.value.value)} × g`
    : `【RCF → RPM】转头半径 ${formatNum(radius.value)} cm，${formatNum(rcf.value)} × g ≈ ${formatNum(output.value.value)} rpm`
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">离心机转速 RPM ↔ 相对离心力 RCF</div>
        <div class="wlc-desc">文献给出 × g 而离心机只能设 RPM，或更换不同转头半径时互相换算。</div>
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
            <NRadioButton value="rpm2rcf">RPM → RCF</NRadioButton>
            <NRadioButton value="rcf2rpm">RCF → RPM</NRadioButton>
          </NRadioGroup>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">转头半径</span>
          <NInputNumber v-model:value="radius" size="small" :show-button="false" :min="0" placeholder="如 10" style="flex: 1" />
          <span class="wlc-unit-fixed">cm</span>
        </div>
        <div v-if="direction === 'rpm2rcf'" class="wlc-row">
          <span class="wlc-label">转速</span>
          <NInputNumber v-model:value="rpm" size="small" :show-button="false" :min="0" placeholder="如 12000" style="flex: 1" />
          <span class="wlc-unit-fixed">rpm</span>
        </div>
        <div v-else class="wlc-row">
          <span class="wlc-label">离心力</span>
          <NInputNumber v-model:value="rcf" size="small" :show-button="false" :min="0" placeholder="如 13000" style="flex: 1" />
          <span class="wlc-unit-fixed">× g</span>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="output">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              {{ output.label }} = <b>{{ formatNum(output.value) }}</b> {{ output.unit }}
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '换算结果')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
        </template>
        <div v-else class="wlc-empty">输入转头半径与{{ direction === 'rpm2rcf' ? '转速' : '离心力' }}后自动换算</div>
        <div class="wlc-formula">
          RCF = 1.118 × 10⁻⁵ × r(cm) × RPM²；反向换算 RPM = √(RCF / (1.118 × 10⁻⁵ × r))。
        </div>
      </div>
    </div>
  </NCard>
</template>
