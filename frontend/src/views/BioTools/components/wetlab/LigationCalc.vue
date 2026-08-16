<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NIcon, NInputNumber, NSelect } from 'naive-ui'
import { CopyOutline, SparklesOutline } from '@vicons/ionicons5'
import { computeLigation, formatNum } from '@/utils/wetLabProcessor'
import { useWlcCopy } from './useWlcCopy'

const { copy } = useWlcCopy()

const vectorLength = ref<number | null>(5000)
const vectorMass = ref<number | null>(100)
const insertLength = ref<number | null>(1000)
const molarRatio = ref<number | null>(3)
const insertConc = ref<number | null>(50)

const ratioOptions = [3, 5, 10, 1].map((v) => ({ label: `载体:插入 = 1:${v}`, value: v }))

const result = computed(() =>
  computeLigation({
    vectorLength: vectorLength.value ?? 0,
    vectorMass: vectorMass.value ?? 0,
    insertLength: insertLength.value ?? 0,
    molarRatio: molarRatio.value ?? 0,
    insertConc: insertConc.value,
  }),
)

function loadSample() {
  vectorLength.value = 5000
  vectorMass.value = 100
  insertLength.value = 1000
  molarRatio.value = 3
  insertConc.value = 50
}

function buildSummary(): string {
  const r = result.value
  if (!r.valid) return ''
  const lines = [
    `【连接反应摩尔比计算】载体:插入 = 1:${molarRatio.value}`,
    `载体：${formatNum(vectorLength.value)} bp，${formatNum(vectorMass.value)} ng`,
    `插入片段：${formatNum(insertLength.value)} bp`,
    `需插入片段质量：${formatNum(r.insertMass)} ng`,
  ]
  if (r.insertVolume !== null) {
    lines.push(`按 ${formatNum(insertConc.value)} ng/µL 浓度吸取：${formatNum(r.insertVolume)} µL`)
  }
  return lines.join('\n')
}
</script>

<template>
  <NCard class="wlc-card" :bordered="false">
    <div class="wlc-title-row">
      <div>
        <div class="wlc-title">载体/片段连接反应摩尔比计算</div>
        <div class="wlc-desc">根据载体与插入片段长度、载体用量与目标摩尔比，计算插入片段加量与吸取体积。</div>
      </div>
      <NButton text size="tiny" class="wlc-sample-link" @click="loadSample">
        <template #icon><NIcon><SparklesOutline /></NIcon></template>
        试试示例数据
      </NButton>
    </div>

    <div class="wlc-grid">
      <div class="wlc-form">
        <div class="wlc-row">
          <span class="wlc-label">载体长度</span>
          <NInputNumber v-model:value="vectorLength" size="small" :show-button="false" :min="0" placeholder="如 5000" style="flex: 1" />
          <span class="wlc-unit-fixed">bp</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">载体用量</span>
          <NInputNumber v-model:value="vectorMass" size="small" :show-button="false" :min="0" placeholder="如 100" style="flex: 1" />
          <span class="wlc-unit-fixed">ng</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">插入片段长度</span>
          <NInputNumber v-model:value="insertLength" size="small" :show-button="false" :min="0" placeholder="如 1000" style="flex: 1" />
          <span class="wlc-unit-fixed">bp</span>
        </div>
        <div class="wlc-row">
          <span class="wlc-label">目标摩尔比</span>
          <NSelect v-model:value="molarRatio" size="small" :options="ratioOptions" style="flex: 1" />
        </div>
        <div class="wlc-row">
          <span class="wlc-label">插入片段浓度</span>
          <NInputNumber v-model:value="insertConc" size="small" :show-button="false" :min="0" placeholder="选填" style="flex: 1" />
          <span class="wlc-unit-fixed">ng/µL</span>
        </div>
      </div>

      <div class="wlc-result">
        <template v-if="result.valid">
          <div class="wlc-result-head">
            <div class="wlc-hero">
              需插入片段 <b>{{ formatNum(result.insertMass) }} ng</b>
              <template v-if="result.insertVolume !== null">
                ，吸取 <b>{{ formatNum(result.insertVolume) }} µL</b>
              </template>
            </div>
            <NButton size="tiny" secondary class="wlc-copy" @click="copy(buildSummary(), '连接方案')">
              <template #icon><NIcon><CopyOutline /></NIcon></template>复制
            </NButton>
          </div>
          <div class="wlc-sub">
            <template v-if="result.insertVolume !== null">按当前浓度 {{ formatNum(insertConc) }} ng/µL 换算吸取体积。</template>
            <template v-else>填写插入片段浓度可进一步换算吸取体积。</template>
          </div>
        </template>
        <NAlert v-else type="warning" :bordered="false">{{ result.error }}</NAlert>
        <div class="wlc-formula">
          插入片段用量 (ng) = 载体用量 × (插入片段长度 / 载体长度) × 摩尔比。等摩尔换算基于双链 DNA 平均分子量一致的前提。
        </div>
      </div>
    </div>
  </NCard>
</template>
