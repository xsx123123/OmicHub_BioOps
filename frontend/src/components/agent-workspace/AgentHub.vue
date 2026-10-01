<script setup lang="ts">
import { computed } from 'vue'
import { NEmpty, NGrid, NGridItem } from 'naive-ui'
import AgentCard from './AgentCard.vue'
import { useAgentHubStore } from '@/stores/agentHub'
import type { AgentTemplate } from '@/types/agent'
import { agentDomainLabel } from '@/utils/agentDomainMap'

const props = withDefaults(defineProps<{ compact?: boolean; excludeAgentIds?: string[]; searchQuery?: string; categoryFilter?: string; highlightedAgentId?: string }>(), {
  compact: false,
  excludeAgentIds: () => [],
  searchQuery: '',
  categoryFilter: '',
  highlightedAgentId: '',
})
const store = useAgentHubStore()
defineEmits<{ select: [agentId: string] }>()

const filteredAgents = computed(() => store.activeAgents.filter((agent) => {
  if (props.excludeAgentIds.includes(agent.id)) return false
  if (props.categoryFilter && agentDomainLabel(agent.category) !== props.categoryFilter) return false
  const query = props.searchQuery.trim().toLocaleLowerCase()
  if (!query) return true
  const caps = [...store.mcpsByIds(agent.mcp_ids).map((m) => m.name), ...store.skillsByIds(agent.skill_ids).map((s) => s.name)]
  return [agent.name, agent.description, ...caps].some((value) => value.toLocaleLowerCase().includes(query))
}))

const groupedAgents = computed(() => {
  const groups: { key: string; label: string; agents: AgentTemplate[] }[] = []
  const buckets = new Map<string, AgentTemplate[]>()
  for (const agent of filteredAgents.value) {
    const key = agentDomainLabel(agent.category)
    const list = buckets.get(key) || []
    list.push(agent)
    buckets.set(key, list)
  }
  const ordered = [...buckets.keys()].sort((a, b) => (buckets.get(b)?.length || 0) - (buckets.get(a)?.length || 0))
  for (const key of ordered) {
    groups.push({
      key,
      label: key,
      agents: buckets.get(key) || [],
    })
  }
  return groups
})

const visibleGroups = computed(() => props.categoryFilter ? groupedAgents.value.slice(0, 1) : groupedAgents.value)
</script>

<template>
  <div class="agent-hub" :class="{ compact: props.compact }">
    <div class="hub-inner">
      <header v-if="!props.compact" class="hub-header">
        <h1 class="hub-title">今天需要哪位专家为您服务？</h1>
        <p class="hub-sub">选择一位搭载专属能力组合的智能体，进入按需隔离的对话沙盒</p>
      </header>

      <NEmpty
        v-if="!groupedAgents.length"
        description="暂无可用智能体"
        class="hub-empty"
      />

      <section v-for="group in visibleGroups" :key="group.key" class="hub-section">
        <h2 v-if="!props.categoryFilter && !props.searchQuery" class="section-label">{{ group.label }} · {{ group.agents.length }}</h2>
        <NGrid
          :cols="props.compact ? 3 : 4"
          :x-gap="props.compact ? 12 : 18"
          :y-gap="props.compact ? 12 : 18"
          responsive="screen"
          item-responsive
          class="card-grid"
        >
          <NGridItem
            v-for="agent in group.agents"
            :key="agent.id"
            :span="props.compact ? '3 s:3 m:1' : '4 s:2 m:2 l:1'"
          >
            <AgentCard :agent="agent" :compact="props.compact" :class="{ 'is-highlighted': props.highlightedAgentId === agent.id }" @select="$emit('select', agent.id)" />
          </NGridItem>
        </NGrid>
      </section>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 布局要点：容器为 flex，内容用 margin:auto 居中——内容少时垂直居中；
   内容超出时从顶部自然起始并可滚动，不会像 align-items:center 那样把页头裁出可视区 */
.agent-hub {
  flex: 1;
  overflow-y: auto;
  display: flex;
  padding: 40px var(--page-padding, 32px) 80px;
}
.agent-hub.compact {
  display: block;
  flex: none;
  min-height: 100%;
  padding: 0;
  overflow: visible;
}
.hub-inner {
  width: 100%;
  max-width: 1100px;
  margin: 0 auto;
}
.hub-header {
  text-align: center;
  margin-bottom: 40px;
}
.hub-title {
  font-size: 28px; line-height: 36px; font-weight: 600;
  letter-spacing: -0.02em; margin: 0 0 8px;
  color: var(--chat-text-primary, var(--neutral-text-1));
}
.hub-sub {
  font-size: 14px; line-height: 22px; margin: 0;
  color: var(--chat-text-muted, var(--neutral-text-3));
}
.hub-empty { padding: 48px 0; }
.hub-section { margin-bottom: 32px; }
.agent-hub.compact .hub-section { margin-bottom: 22px; }
.hub-section:last-child { margin-bottom: 0; }
.section-label {
  font-size: 13px; line-height: 20px; font-weight: 600; margin: 0 0 12px 4px;
  color: var(--chat-text-muted, var(--neutral-text-3));
}
.card-grid { justify-content: center; }

@media (max-width: 768px) {
  .agent-hub { padding: 24px 16px 64px; }
  .hub-header { margin-bottom: 24px; }
  .agent-category-tabs :deep(.n-tabs-nav-scroll-content) { gap: 10px; }
}
</style>
