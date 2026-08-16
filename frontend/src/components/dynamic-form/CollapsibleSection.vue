<script setup lang="ts">
import type { FormValues, Parameter } from '@/types/schema'
import { NCollapse, NCollapseItem } from 'naive-ui'
import { computed } from 'vue'
import DynamicForm from './DynamicForm.vue'

const props = defineProps<{
  parameter: Parameter
  modelValue: unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: FormValues]
}>()

const config = computed(() => props.parameter.section_config!)

const value = computed({
  get: () => (props.modelValue as FormValues) || {},
  set: (v) => emit('update:modelValue', v),
})
</script>

<template>
  <NCollapse :default-expanded-names="config.default_expanded ? ['section'] : []">
    <NCollapseItem :title="config.title || parameter.label" name="section">
      <template v-if="config.description" #header-extra>
        <span class="section-description">{{ config.description }}</span>
      </template>
      <DynamicForm
        :parameters="config.parameters"
        :model-value="value"
        @update:model-value="(v) => (value = v as FormValues)"
      />
    </NCollapseItem>
  </NCollapse>
</template>

<style scoped>
.section-description {
  color: var(--n-text-color-disabled);
  font-size: 12px;
  margin-left: 8px;
}
</style>
