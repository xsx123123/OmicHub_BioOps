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
const visibleCaps = computed(() => caps.value.slice(0, 3))
const extraCaps = computed(() => caps.value.slice(3))
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
        <div class="desc" :title="agent.description">{{ agent.description }}</div>
        <div v-if="visibleCaps.length" class="capability-chips">
          <span v-for="cap in visibleCaps" :key="cap" class="cap-chip">{{ cap }}</span>
          <span v-if="extraCaps.length" class="cap-chip cap-more">+{{ extraCaps.length }}</span>
        </div>
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
  min-height: 76px;
  padding: 12px;
  color: inherit;
  text-align: left;
  background: var(--chat-surface, var(--neutral-card));
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 12px;
  cursor: pointer;
  transition: border-color .16s ease, box-shadow .16s ease, background-color .16s ease;
  height: 100%;
}
.agent-card:hover {
  border-color: var(--agent-color);
  background: color-mix(in srgb, var(--agent-color) 5%, var(--chat-surface, var(--neutral-card)));
}
.agent-card.is-highlighted { border-color: var(--arco-primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--arco-primary) 20%, transparent); }
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
  overflow: hidden; margin: 8px 0 0;
  text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; color: var(--chat-text-secondary, var(--neutral-text-2)); line-height: 1.6;
}
.capability-chips { display: flex; gap: 4px; margin-top: 7px; overflow: hidden; }
.cap-chip { max-width: 140px; overflow: hidden; padding: 2px 6px; border-radius: 4px; color: var(--chat-text-muted, var(--neutral-text-3)); background: var(--neutral-hover); font-size: 11px; line-height: 15px; text-overflow: ellipsis; white-space: nowrap; }
.cap-more { flex: 0 0 auto; color: var(--arco-primary); }

.agent-card.compact { min-height: 76px; padding: 12px; border-radius: 10px; }
.agent-card.compact .desc { margin-top: 8px; }

.cap-pop { font-size: 13px; }
.cap-title { font-weight: 600; margin-bottom: 8px; }
.cap-list { display: flex; flex-direction: column; gap: 4px; }
.cap-item { font-size: 12px; color: var(--neutral-text-2, #666); }
.cap-empty { font-size: 12px; color: var(--neutral-text-3, #aaa); }

@media (prefers-reduced-motion: reduce) {
  .agent-card { transition: none; }
}
</style>
