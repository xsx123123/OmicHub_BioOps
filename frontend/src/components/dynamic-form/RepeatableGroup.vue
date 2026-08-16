<script setup lang="ts">
import type { FormValues, Parameter } from '@/types/schema'
import { NButton, NCard, NFormItem, NSpace } from 'naive-ui'
import { computed } from 'vue'
import DynamicForm from './DynamicForm.vue'

const props = defineProps<{
  parameter: Parameter
  modelValue: unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: FormValues[]]
}>()

const config = computed(() => props.parameter.group_config!)

const items = computed({
  get: () => (Array.isArray(props.modelValue) ? (props.modelValue as FormValues[]) : []),
  set: (v) => emit('update:modelValue', v),
})

const minItems = computed(() => config.value.min_items ?? 1)
const maxItems = computed(() => config.value.max_items)
const itemLabel = computed(() => config.value.item_label || '条目')
const addButtonText = computed(() => config.value.add_button_text || '+ 添加')

function addItem() {
  if (maxItems.value !== undefined && items.value.length >= maxItems.value) {
    return
  }
  const newItem: FormValues = {}
  for (const p of config.value.parameters) {
    if (p.default !== undefined) {
      newItem[p.name] = p.default
    }
  }
  items.value = [...items.value, newItem]
}

function removeItem(index: number) {
  if (items.value.length <= minItems.value) {
    return
  }
  items.value = items.value.filter((_, i) => i !== index)
}

function updateItem(index: number, value: FormValues) {
  const next = [...items.value]
  next[index] = value
  items.value = next
}
</script>

<template>
  <div class="repeatable-group">
    <NCard
      v-for="(item, index) in items"
      :key="index"
      :title="`${itemLabel} ${index + 1}`"
      size="small"
      class="group-item"
    >
      <template #header-extra>
        <NButton
          v-if="items.length > minItems"
          text
          type="error"
          size="small"
          @click="removeItem(index)"
        >
          删除
        </NButton>
      </template>
      <DynamicForm
        :parameters="config.parameters"
        :model-value="item"
        @update:model-value="(v) => updateItem(index, v as FormValues)"
      />
    </NCard>

    <NSpace>
      <NButton
        type="primary"
        dashed
        :disabled="maxItems !== undefined && items.length >= maxItems"
        @click="addItem"
      >
        {{ addButtonText }}
      </NButton>
    </NSpace>
  </div>
</template>

<style scoped>
.repeatable-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-item {
  background-color: var(--n-action-color);
}
</style>
