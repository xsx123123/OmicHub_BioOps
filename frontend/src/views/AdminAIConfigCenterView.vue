<script setup lang="ts">
import { computed } from 'vue'
import { NTabs, NTabPane } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import AdminAIProvidersView from '@/views/AdminAIProvidersView.vue'
import AdminAIResourceCenterView from '@/views/AdminAIResourceCenterView.vue'

const route = useRoute()
const router = useRouter()

const activeTab = computed({
  get: () => route.name === 'admin-ai-config-resources' ? 'resources' : 'providers',
  set: (tab: string) => {
    void router.push({ name: tab === 'resources' ? 'admin-ai-config-resources' : 'admin-ai-config-providers' })
  },
})
</script>

<template>
  <div class="admin-config-center">
    <PageHeader title="AI 配置中心" subtitle="统一维护模型 Provider、MCP 服务、技能包、智能助手与联网搜索资源" />
    <NTabs v-model:value="activeTab" type="line" animated class="admin-config-tabs">
      <NTabPane name="providers" tab="模型配置">
        <AdminAIProvidersView embedded />
      </NTabPane>
      <NTabPane name="resources" tab="资源中心">
        <AdminAIResourceCenterView embedded />
      </NTabPane>
    </NTabs>
  </div>
</template>
