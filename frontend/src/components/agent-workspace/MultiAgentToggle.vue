<script setup lang="ts">
import { NIcon, NSwitch, NTooltip } from 'naive-ui'
import { GitNetworkOutline } from '@vicons/ionicons5'

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

function update(value: boolean) {
  emit('update:modelValue', value)
}
</script>

<template>
  <NTooltip trigger="hover">
    <template #trigger>
      <span class="multi-agent-toggle" :class="{ 'is-active': props.modelValue, 'is-compact': props.compact }">
        <NIcon size="16"><GitNetworkOutline /></NIcon>
        <span v-if="!props.compact" class="toggle-label">Multi-agent</span>
        <NSwitch
          :value="props.modelValue"
          size="small"
          :disabled="props.disabled"
          aria-label="启用 multi-agent 协作"
          @update:value="update"
        />
      </span>
    </template>
    {{ props.modelValue
      ? '已开启：复杂任务可由 AgentTeams 并行协作，必要时创建受确认的协作 Case'
      : '开启后，复杂任务可由 AgentTeams 并行协作；普通问题仍由当前助手直接处理' }}
  </NTooltip>
</template>

<style scoped>
.multi-agent-toggle {
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

.multi-agent-toggle.is-active {
  color: var(--primary-color);
  border-color: color-mix(in srgb, var(--primary-color) 46%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 8%, var(--card-color));
}

.multi-agent-toggle.is-compact {
  padding: 2px 5px;
}

.toggle-label {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .multi-agent-toggle { transition: none; }
}
</style>
