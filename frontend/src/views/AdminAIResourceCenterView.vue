<script setup lang="ts">
import { NTabs, NTabPane } from 'naive-ui'
import McpResourceTab from '@/components/admin/McpResourceTab.vue'
import SkillResourceTab from '@/components/admin/SkillResourceTab.vue'
import AgentResourceTab from '@/components/admin/AgentResourceTab.vue'
import SearchProviderTab from '@/components/admin/SearchProviderTab.vue'
import KnowledgeResourceTab from '@/components/admin/KnowledgeResourceTab.vue'
import AgentTeamsBridgeTab from '@/components/admin/AgentTeamsBridgeTab.vue'
import PageHeader from '@/components/PageHeader.vue'

withDefaults(defineProps<{ embedded?: boolean }>(), {
  embedded: false,
})
</script>

<template>
  <div
    class="admin-config-section"
    :class="{ 'admin-config-section--standalone': !embedded }"
  >
    <PageHeader v-if="!embedded" title="AI 资源中心" subtitle="集中管理 MCP 服务、技能包、智能助手、联网搜索与知识库资源" />
    <NTabs type="line" animated class="admin-config-tabs">
      <NTabPane name="mcp" tab="MCP 服务">
        <McpResourceTab />
      </NTabPane>
      <NTabPane name="skill" tab="技能">
        <SkillResourceTab />
      </NTabPane>
      <NTabPane name="agent" tab="助手">
        <AgentResourceTab />
      </NTabPane>
      <NTabPane name="web-search" tab="联网搜索">
        <SearchProviderTab />
      </NTabPane>
      <NTabPane name="knowledge" tab="知识库">
        <KnowledgeResourceTab />
      </NTabPane>
      <NTabPane name="agentteams-bridge" tab="AgentTeams">
        <AgentTeamsBridgeTab />
      </NTabPane>
    </NTabs>
  </div>
</template>
