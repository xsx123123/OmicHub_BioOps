<script setup lang="ts">
import { computed, h, type VNodeChild } from 'vue'
import { NSlider, NInputNumber } from 'naive-ui'
import { formatMemoryMb, parseMemoryMb } from '@/utils/terminal'

interface Props {
  memoryMb: number
  cpuCores: number
  memoryMin?: number
  memoryMax?: number
  memoryStep?: number
  cpuMin?: number
  cpuMax?: number
  cpuStep?: number
  recommendedMemoryMb?: number
  recommendedCpuCores?: number
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  memoryMin: 256,
  memoryMax: 4096,
  memoryStep: 128,
  cpuMin: 0.5,
  cpuMax: 4.0,
  cpuStep: 0.5,
  recommendedMemoryMb: undefined,
  recommendedCpuCores: undefined,
  disabled: false,
})

const emit = defineEmits<{
  'update:memoryMb': [value: number]
  'update:cpuCores': [value: number]
}>()

const memoryModel = computed({
  get: () => props.memoryMb,
  set: (val) => emit('update:memoryMb', val),
})

const cpuModel = computed({
  get: () => props.cpuCores,
  set: (val) => emit('update:cpuCores', val),
})

function formatCpuLabel(value: number) {
  return `${value} 核`
}

function compactMemoryLabel(value: number) {
  const gigabytes = value / 1024
  return `${Number.isInteger(gigabytes) ? gigabytes : gigabytes.toFixed(1)}G`
}

function buildMarks(
  values: number[],
  recommendedValue: number | undefined,
  formatter: (value: number) => string,
) {
  return values.reduce<Record<string, () => VNodeChild>>((marks, value, index) => {
    const isRecommended = value === recommendedValue
    marks[String(index)] = () => h(
      'span',
      { class: ['slider-mark-label', { 'is-recommended': isRecommended }] },
      `${formatter(value)}${isRecommended ? '·推荐' : ''}`,
    )
    return marks
  }, {})
}

function buildPresetValues(values: number[], currentValue: number, min: number, max: number) {
  const presets = values.filter((value) => value >= min && value <= max)
  if (!presets.includes(currentValue)) presets.push(currentValue)
  return presets.sort((a, b) => a - b)
}

const memoryPresetValues = computed(() =>
  buildPresetValues([512, 1024, 2048, 4096, 8192], props.memoryMb, props.memoryMin, props.memoryMax),
)

const cpuPresetValues = computed(() =>
  buildPresetValues([0.5, 1, 2, 4, 8], props.cpuCores, props.cpuMin, props.cpuMax),
)

const memorySliderModel = computed({
  get: () => memoryPresetValues.value.indexOf(props.memoryMb),
  set: (index: number) => emit('update:memoryMb', memoryPresetValues.value[index]),
})

const cpuSliderModel = computed({
  get: () => cpuPresetValues.value.indexOf(props.cpuCores),
  set: (index: number) => emit('update:cpuCores', cpuPresetValues.value[index]),
})

const memoryMarks = computed(() =>
  buildMarks(memoryPresetValues.value, props.recommendedMemoryMb, compactMemoryLabel),
)

const cpuMarks = computed(() =>
  buildMarks(cpuPresetValues.value, props.recommendedCpuCores, (value) => `${value}核`),
)
</script>

<template>
  <section class="resource-settings">
    <div class="resource-section">
      <div class="resource-label">
        <span>分配内存</span>
        <div class="resource-value">
          <NInputNumber
            v-model:value="memoryModel"
            :min="memoryMin"
            :max="memoryMax"
            :step="memoryStep"
            :disabled="disabled"
            :format="formatMemoryMb"
            :parse="parseMemoryMb"
            size="small"
            class="resource-input"
          />
        </div>
      </div>
      <NSlider
        v-model:value="memorySliderModel"
        :min="0"
        :max="memoryPresetValues.length - 1"
        :step="1"
        :marks="memoryMarks"
        :disabled="disabled"
        :format-tooltip="(index) => formatMemoryMb(memoryPresetValues[index])"
        class="resource-slider"
      />
      <div class="resource-range" aria-hidden="true">
        <span>{{ formatMemoryMb(memoryMin) }}</span>
        <span>上限 {{ formatMemoryMb(memoryMax, { ceiling: true }) }}</span>
      </div>
    </div>

    <div class="resource-section">
      <div class="resource-label">
        <span>分配 CPU</span>
        <div class="resource-value">
          <NInputNumber
            v-model:value="cpuModel"
            :min="cpuMin"
            :max="cpuMax"
            :step="cpuStep"
            :disabled="disabled"
            size="small"
            class="resource-input"
          >
            <template #suffix>核</template>
          </NInputNumber>
        </div>
      </div>
      <NSlider
        v-model:value="cpuSliderModel"
        :min="0"
        :max="cpuPresetValues.length - 1"
        :step="1"
        :marks="cpuMarks"
        :disabled="disabled"
        :format-tooltip="(index) => formatCpuLabel(cpuPresetValues[index])"
        class="resource-slider"
      />
      <div class="resource-range" aria-hidden="true">
        <span>{{ cpuMin }} 核</span>
        <span>上限 {{ cpuMax }} 核</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.resource-settings {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.resource-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.resource-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--neutral-text-1);
}

.resource-value {
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-input {
  width: 114px;
}

.resource-slider {
  --n-rail-height: 5px;
  --n-fill-color: var(--arco-primary);
  --n-fill-color-hover: var(--arco-primary);
  --n-rail-color: var(--neutral-border);
  --n-rail-color-hover: var(--neutral-border);
  --n-handle-size: 16px;
  --n-handle-color: var(--neutral-card);
  --n-handle-box-shadow: 0 0 0 2px var(--arco-primary);
  --n-handle-box-shadow-hover: 0 0 0 2px var(--arco-primary);
}

.resource-range {
  display: flex;
  justify-content: space-between;
  color: var(--neutral-text-3);
  font-size: 11px;
}

:deep(.n-slider-mark) {
  margin-top: 8px;
  font-size: 11px;
  white-space: nowrap;
}

:deep(.slider-mark-label) {
  color: var(--neutral-text-3);
}

:deep(.slider-mark-label.is-recommended) {
  color: var(--arco-primary);
  font-weight: 700;
}
</style>
