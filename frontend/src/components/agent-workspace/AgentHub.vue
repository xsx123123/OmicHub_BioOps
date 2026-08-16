<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NBadge, NEmpty, NGrid, NGridItem, NTabPane, NTabs } from 'naive-ui'
import AgentCard from './AgentCard.vue'
import { useAgentHubStore, CATEGORY_LABELS } from '@/stores/agentHub'
import type { AgentCategory, AgentTemplate } from '@/types/agent'

const props = withDefaults(defineProps<{ compact?: boolean; excludeAgentIds?: string[] }>(), {
  compact: false,
  excludeAgentIds: () => [],
})
const store = useAgentHubStore()
defineEmits<{ select: [agentId: string] }>()

/** 按分类分组展示（分类顺序固定，未知分类归入末尾） */
const CATEGORY_ORDER: AgentCategory[] = ['general', 'analysis', 'code', 'visualization']

const groupedAgents = computed(() => {
  const groups: { key: string; label: string; agents: AgentTemplate[] }[] = []
  const buckets = new Map<string, AgentTemplate[]>()
  for (const agent of store.activeAgents) {
    if (props.excludeAgentIds.includes(agent.id)) continue
    const list = buckets.get(agent.category) || []
    list.push(agent)
    buckets.set(agent.category, list)
  }
  const ordered = [
    ...CATEGORY_ORDER.filter((c) => buckets.has(c)).map((c) => c as string),
    ...[...buckets.keys()].filter((k) => !CATEGORY_ORDER.includes(k as AgentCategory)),
  ]
  for (const key of ordered) {
    groups.push({
      key,
      label: CATEGORY_LABELS[key as AgentCategory] || key,
      agents: buckets.get(key) || [],
    })
  }
  return groups
})

const activeCategory = ref('')

watch(
  groupedAgents,
  (groups) => {
    if (!groups.some((group) => group.key === activeCategory.value)) {
      activeCategory.value = groups[0]?.key || ''
    }
  },
  { immediate: true },
)
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

      <NTabs
        v-if="props.compact && groupedAgents.length"
        v-model:value="activeCategory"
        type="line"
        animated
        class="agent-category-tabs"
      >
        <NTabPane
          v-for="group in groupedAgents"
          :key="group.key"
          :name="group.key"
        >
          <template #tab>
            <span class="category-tab-label">
              {{ group.label }}
              <NBadge :value="group.agents.length" :max="99" />
            </span>
          </template>
          <NGrid :cols="4" :x-gap="12" :y-gap="12" responsive="screen" item-responsive class="card-grid">
            <NGridItem v-for="agent in group.agents" :key="agent.id" span="4 s:2 m:1">
              <AgentCard :agent="agent" compact @select="$emit('select', agent.id)" />
            </NGridItem>
          </NGrid>
        </NTabPane>
      </NTabs>

      <section v-for="group in props.compact ? [] : groupedAgents" :key="group.key" class="hub-section">
        <h2 class="section-label">{{ group.label }}</h2>
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
            <AgentCard :agent="agent" :compact="props.compact" @select="$emit('select', agent.id)" />
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
  padding: 0;
  overflow: visible;
}
.hub-inner {
  width: 100%;
  max-width: 1100px;
  margin: auto;
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
.agent-category-tabs :deep(.n-tabs-nav) { margin-bottom: var(--space-lg, 16px); }
.agent-category-tabs :deep(.n-tabs-tab) { padding-inline: 4px 14px; }
.category-tab-label { display: inline-flex; align-items: center; gap: 6px; }
.category-tab-label :deep(.n-badge) { font-size: 11px; }

@media (max-width: 768px) {
  .agent-hub { padding: 24px 16px 64px; }
  .hub-header { margin-bottom: 24px; }
  .agent-category-tabs :deep(.n-tabs-nav-scroll-content) { gap: 10px; }
}
</style>
