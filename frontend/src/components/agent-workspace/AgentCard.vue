<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'
import { useAgentHubStore } from '@/stores/agentHub'
import { CATEGORY_LABELS } from '@/stores/agentHub'
import type { AgentTemplate } from '@/types/agent'

const props = withDefaults(defineProps<{ agent: AgentTemplate; compact?: boolean }>(), {
  compact: false,
})
defineEmits<{ select: [] }>()

const store = useAgentHubStore()

const mountedMcps = computed(() => store.mcpsByIds(props.agent.mcp_ids))
const mountedSkills = computed(() => store.skillsByIds(props.agent.skill_ids))
const caps = computed(() => [
  ...mountedMcps.value.map((m) => `搭载 ${m.name}`),
  ...mountedSkills.value.map((s) => s.name),
])
const capabilityLabel = computed(() => {
  if (caps.value.length) return `${caps.value.length} 项专属能力`
  return '通用会话能力'
})
</script>

<template>
  <NPopover trigger="hover" placement="top" :width="240">
    <template #trigger>
      <button
        class="agent-card cygnusx-selectable-card"
        :class="{ compact: props.compact }"
        :style="{ '--agent-color': agent.color }"
        type="button"
        :aria-label="`选择 ${agent.name}`"
        @click="$emit('select')"
      >
        <div class="card-heading">
          <div class="avatar" :style="{ background: agent.color }">{{ agent.avatar }}</div>
          <div class="identity">
            <div class="name">{{ agent.name }}</div>
            <div class="category">{{ CATEGORY_LABELS[agent.category] }}</div>
          </div>
          <span class="enter-mark" aria-hidden="true">↗</span>
        </div>
        <div class="desc">{{ agent.description }}</div>
        <div class="capability">{{ capabilityLabel }}</div>
      </button>
    </template>
    <div class="cap-pop">
      <div class="cap-title">{{ agent.avatar }} {{ agent.name }} 搭载的能力</div>
      <div v-if="caps.length" class="cap-list">
        <div v-for="c in caps" :key="c" class="cap-item">· {{ c }}</div>
      </div>
      <div v-else class="cap-empty">通用助手，未挂载额外能力</div>
    </div>
  </NPopover>
</template>

<style scoped lang="scss">
.agent-card {
  width: 100%;
  position: relative;
  display: flex; flex-direction: column;
  min-height: 174px;
  padding: 20px;
  color: inherit;
  text-align: left;
  background: var(--chat-surface, var(--neutral-card));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 16px;
  cursor: pointer;
  transition: border-color .16s ease, box-shadow .16s ease, background-color .16s ease;
  height: 100%;
}
.agent-card:hover {
  border-color: var(--agent-color);
  background: color-mix(in srgb, var(--agent-color) 5%, var(--chat-surface, var(--neutral-card)));
}
.agent-card:focus-visible {
  outline: 2px solid var(--agent-color);
  outline-offset: 3px;
}
.card-heading { display: flex; align-items: center; gap: 10px; }
.avatar {
  width: 42px; height: 42px; border-radius: 13px;
  display: flex; align-items: center; justify-content: center;
  flex: 0 0 auto;
  font-size: 21px;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--agent-color) 24%, transparent);
}
.identity { min-width: 0; }
.name { font-size: 14px; font-weight: 650; color: var(--chat-text-primary, var(--neutral-text-1)); }
.category { margin-top: 2px; font-size: 12px; color: var(--chat-text-muted, var(--neutral-text-3)); }
.enter-mark { margin-left: auto; color: var(--chat-text-muted, var(--neutral-text-3)); font-size: 16px; line-height: 1; }
.desc {
  display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  margin: 16px 0 auto; min-height: 38px;
  font-size: 12px; color: var(--chat-text-secondary, var(--neutral-text-2)); line-height: 1.6;
}
.capability { margin-top: 14px; font-size: 12px; color: var(--chat-text-muted, var(--neutral-text-3)); }

.agent-card.compact { min-height: 128px; padding: 16px; border-radius: var(--radius-lg, 14px); }
.agent-card.compact .desc { margin-top: 11px; min-height: 34px; }
.agent-card.compact .capability { margin-top: 9px; }

.cap-pop { font-size: 13px; }
.cap-title { font-weight: 600; margin-bottom: 8px; }
.cap-list { display: flex; flex-direction: column; gap: 4px; }
.cap-item { font-size: 12px; color: var(--neutral-text-2, #666); }
.cap-empty { font-size: 12px; color: var(--neutral-text-3, #aaa); }

@media (prefers-reduced-motion: reduce) {
  .agent-card { transition: none; }
}
</style>
