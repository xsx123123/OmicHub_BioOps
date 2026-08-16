<script setup lang="ts">
import { NIcon, NSwitch, NTooltip } from 'naive-ui'
import { FlashOutline } from '@vicons/ionicons5'

const props = withDefaults(defineProps<{
  modelValue: boolean
  disabled?: boolean
  compact?: boolean
}>(), {
  disabled: false,
  compact: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <NTooltip trigger="hover">
    <template #trigger>
      <span class="overdrive-toggle" :class="{ 'is-active': props.modelValue, 'is-compact': props.compact }">
        <NIcon size="16"><FlashOutline /></NIcon>
        <span v-if="!props.compact" class="toggle-label">团队协作模式</span>
        <NSwitch
          :value="props.modelValue"
          size="small"
          :disabled="props.disabled"
          aria-label="启用超频模式"
          @update:value="emit('update:modelValue', $event)"
        />
      </span>
    </template>
    {{ props.modelValue
    ? '团队协作模式已开启：复杂任务可由多个专家共同推进，并在对话中汇报进度'
      : '开启后，复杂任务可由 Manager 分派专家并在同一对话中协作；普通问题仍由当前助手处理' }}
  </NTooltip>
</template>

<style scoped>
.overdrive-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 3px 7px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--card-color);
  transition: color 160ms ease, border-color 160ms ease, background-color 160ms ease;
}

.overdrive-toggle.is-active {
  color: var(--primary-color);
  border-color: color-mix(in srgb, var(--primary-color) 46%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 8%, var(--card-color));
}

.overdrive-toggle.is-compact { padding: 2px 5px; }
.toggle-label { font-size: 12px; font-weight: 600; white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { .overdrive-toggle { transition: none; } }
</style>
