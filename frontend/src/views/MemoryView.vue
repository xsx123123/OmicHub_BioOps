<template>
  <main class="page-container memory-page">
    <PageHeader
      title="我的记忆"
      subtitle="查看和管理从 AI 对话中沉淀的研究偏好、项目事实与命名记忆块。"
    >
      <template #actions>
        <NButton secondary @click="router.push('/profile')">返回个人中心</NButton>
      </template>
    </PageHeader>
    <MemoryManagementPanel />
  </main>
</template>

<script setup lang="ts">
import { NButton } from 'naive-ui'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import MemoryManagementPanel from '@/components/agent-workspace/MemoryManagementPanel.vue'

const router = useRouter()
</script>

<style scoped>
.memory-page {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  gap: var(--space-lg);
}
</style>
