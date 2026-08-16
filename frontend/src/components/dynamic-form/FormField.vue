<script setup lang="ts">
import type { Parameter } from '@/types/schema'
import {
  NButton,
  NIcon,
  NInput,
  NInputNumber,
  NSelect,
  NSlider,
  NSwitch,
  NUpload,
} from 'naive-ui'
import { CloudUploadOutline, FolderOpenOutline } from '@vicons/ionicons5'
import { computed } from 'vue'

const props = defineProps<{
  parameter: Parameter
  modelValue: unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
  openPathPicker: [paramName: string]
}>()

const value = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const placeholder = computed(() =>
  props.parameter.ui?.placeholder || props.parameter.placeholder || '',
)

const widgetType = computed(() => {
  if (props.parameter.ui?.widget) return props.parameter.ui.widget
  if (props.parameter.type === 'boolean') return 'switch'
  if (props.parameter.type === 'select') return 'select'
  const n = props.parameter.name.toLowerCase()
  if (props.parameter.type === 'string' && /dir|path/.test(n)) return 'path'
  if (props.parameter.type === 'string' && props.parameter.string_config?.multiline)
    return 'textarea'
  return props.parameter.type
})

const isTextarea = computed(() => widgetType.value === 'textarea')
const isPath = computed(() => widgetType.value === 'path')

const numberConfig = computed(() => props.parameter.number_config)

const selectOptions = computed(() => {
  return (
    props.parameter.select_config?.options.map((opt) => ({
      label: opt.label,
      value: opt.value as string | number,
    })) || []
  )
})

function handleFileChange(options: { fileList: unknown[] }) {
  const config = props.parameter.file_config
  if (config?.multiple) {
    value.value = options.fileList
  } else {
    value.value = options.fileList[0] || null
  }
}

function emitOpenPathPicker() {
  emit('openPathPicker', props.parameter.name)
}
</script>

<template>
  <div class="form-field">
    <template v-if="parameter.type === 'string' && isPath">
      <div class="path-input-wrap">
        <NInput
          v-model:value="value as string"
          :placeholder="placeholder"
          class="path-input"
        />
        <NButton quaternary size="small" title="选择目录" @click="emitOpenPathPicker">
          <template #icon><NIcon><FolderOpenOutline /></NIcon></template>
        </NButton>
      </div>
    </template>

    <template v-else-if="parameter.type === 'string'">
      <NInput
        v-if="isTextarea"
        v-model:value="value as string"
        type="textarea"
        :rows="parameter.string_config?.rows || 3"
        :placeholder="placeholder"
      />
      <NInput v-else v-model:value="value as string" :placeholder="placeholder" />
    </template>

    <NInputNumber
      v-else-if="parameter.type === 'int'"
      v-model:value="value as number | null"
      :min="numberConfig?.min"
      :max="numberConfig?.max"
      :step="numberConfig?.step ?? 1"
      :placeholder="placeholder"
      clearable
    />

    <template v-else-if="parameter.type === 'float'">
      <NSlider
        v-if="numberConfig?.use_slider"
        v-model:value="value as number"
        :min="numberConfig?.min ?? 0"
        :max="numberConfig?.max ?? 100"
        :step="numberConfig?.step ?? 0.1"
      />
      <NInputNumber
        v-else
        v-model:value="value as number | null"
        :min="numberConfig?.min"
        :max="numberConfig?.max"
        :step="numberConfig?.step ?? 0.1"
        :precision="numberConfig?.precision ?? 2"
        :placeholder="placeholder"
        clearable
      />
    </template>

    <NSelect
      v-else-if="parameter.type === 'select'"
      v-model:value="value as string | number | string[] | number[] | null"
      :options="selectOptions"
      :multiple="parameter.select_config?.multi"
      :clearable="parameter.select_config?.allow_clear"
      :filterable="parameter.select_config?.searchable"
      :placeholder="placeholder"
    />

    <NSwitch v-else-if="parameter.type === 'boolean'" v-model:value="value as boolean" />

    <NUpload
      v-else-if="parameter.type === 'file'"
      :multiple="parameter.file_config?.multiple"
      :accept="parameter.file_config?.accept"
      @change="handleFileChange"
    >
      <NButton>
        <template #icon>
          <NIcon><CloudUploadOutline /></NIcon>
        </template>
        上传文件
      </NButton>
    </NUpload>
  </div>
</template>

<style scoped>
.form-field {
  width: 100%;
}
.path-input-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
}
.path-input :deep(.n-input__input-el) {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
}
</style>
