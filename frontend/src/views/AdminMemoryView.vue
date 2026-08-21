<template>
  <main class="page-container admin-config-center admin-memory-page">
    <PageHeader title="记忆审计" subtitle="按用户和 Agent 查看 v2 命名记忆块、语义事实及归档状态。">
      <template #actions>
        <NButton secondary :loading="loading" :disabled="!selectedUserId" @click="loadOverview">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          刷新记忆
        </NButton>
      </template>
    </PageHeader>

    <NCard :bordered="false" class="admin-memory-filter">
      <NForm inline label-placement="left">
        <NFormItem label="用户">
          <NSelect
            v-model:value="selectedUserId"
            filterable
            clearable
            placeholder="选择要审计的用户"
            :options="userOptions"
            :loading="usersLoading"
            style="min-width: 280px"
            @update:value="loadOverview"
          />
        </NFormItem>
        <NFormItem label="Agent">
          <NSelect
            v-model:value="selectedAgentId"
            clearable
            placeholder="全部 Agent"
            :options="agentOptions"
            style="min-width: 220px"
            @update:value="loadOverview"
          />
        </NFormItem>
        <NFormItem label="范围">
          <NSelect
            v-model:value="selectedScope"
            clearable
            placeholder="全部范围"
            :options="scopeOptions"
            style="min-width: 160px"
            @update:value="loadOverview"
          />
        </NFormItem>
      </NForm>
    </NCard>

    <NAlert v-if="!selectedUserId" type="info" :show-icon="false">
      请选择用户后查看其记忆。管理员只能查看，不能替用户直接修改记忆内容。
    </NAlert>

    <NSpin :show="loading">
      <template v-if="overview && selectedUserId">
        <NAlert v-if="overview.mode === 'legacy'" type="warning" :show-icon="false" class="admin-memory-alert">
          当前用户仍处于旧记忆模式，以下旧记忆仅用于审计；v2 blocks/facts 已提供时会同时展示。
        </NAlert>

        <div class="admin-memory-summary">
          <NCard size="small" :bordered="false"><span>命名记忆块</span><strong>{{ overview.blocks.length }}</strong></NCard>
          <NCard size="small" :bordered="false"><span>语义事实</span><strong>{{ overview.facts.length }}</strong></NCard>
          <NCard size="small" :bordered="false"><span>旧版记忆</span><strong>{{ overview.legacy_memories.length }}</strong></NCard>
        </div>

        <NCard title="命名记忆块" :bordered="false" class="admin-memory-card">
          <NEmpty v-if="!overview.blocks.length" description="暂无命名记忆块" />
          <div v-else class="admin-block-grid">
            <article v-for="block in overview.blocks" :key="block.id" class="admin-block">
              <div class="admin-block__title">
                <strong>{{ blockLabels[block.block_name] || block.block_name }}</strong>
                <NTag size="tiny" round>{{ block.agent_id }} · v{{ block.version }}</NTag>
              </div>
              <p>{{ block.content || '空' }}</p>
              <small>{{ block.content.length }} / {{ block.char_limit }} 字符</small>
            </article>
          </div>
        </NCard>

        <NCard title="语义事实" :bordered="false" class="admin-memory-card">
          <NDataTable
            :columns="factColumns"
            :data="overview.facts"
            :bordered="false"
            :row-key="(row: MemoryFact) => row.id"
            :pagination="{ pageSize: 15, showSizePicker: true, pageSizes: [15, 30, 50] }"
            :scroll-x="1150"
            size="small"
          />
        </NCard>

        <NCard v-if="overview.legacy_memories.length" title="旧版记忆" :bordered="false" class="admin-memory-card">
          <NDataTable
            :columns="legacyColumns"
            :data="overview.legacy_memories"
            :bordered="false"
            :row-key="(row: LegacyMemory) => row.id"
            :pagination="{ pageSize: 15, showSizePicker: true, pageSizes: [15, 30, 50] }"
            :scroll-x="710"
            size="small"
          />
        </NCard>
      </template>
    </NSpin>
  </main>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NSelect,
  NSpin,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import apiClient from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

interface AdminUser { id: string; username: string; nickname?: string | null; email?: string | null }
interface MemoryBlock { id: number; agent_id: string; block_name: string; content: string; char_limit: number; version: number }
interface MemoryFact { id: number; agent_id: string; scope: string; content: string; confidence: number; status: string; created_at: string | null; last_recalled_at: string | null }
interface LegacyMemory { id: string; scope: string; content: string }
interface MemoryOverview { mode: 'legacy' | 'v2'; agent_ids: string[]; blocks: MemoryBlock[]; facts: MemoryFact[]; legacy_memories: LegacyMemory[] }

const message = useMessage()
const users = ref<AdminUser[]>([])
const usersLoading = ref(false)
const loading = ref(false)
const selectedUserId = ref<string | null>(null)
const selectedAgentId = ref<string | null>(null)
const selectedScope = ref<string | null>(null)
const overview = ref<MemoryOverview | null>(null)
const blockLabels: Record<string, string> = { profile: '用户画像', preferences: '长期偏好', current_focus: '当前焦点' }
const scopeLabels: Record<string, string> = { profile: '用户画像', preference: '偏好', project: '项目', summary: '摘要' }
const scopeOptions = Object.entries(scopeLabels).map(([value, label]) => ({ value, label }))
const userOptions = computed(() => users.value.map((user) => ({ value: user.id, label: `${user.nickname || user.username} · ${user.email || user.username}` })))
const agentOptions = computed(() => [...new Set([
  ...(overview.value?.agent_ids || []),
  ...(overview.value?.blocks || []).map((item) => item.agent_id),
  ...(overview.value?.facts || []).map((item) => item.agent_id),
])].map((value) => ({ value, label: value })))

function formatDate(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

const factColumns: DataTableColumns<MemoryFact> = [
  { title: 'Agent', key: 'agent_id', width: 160, align: 'center', ellipsis: { tooltip: true } },
  { title: '范围', key: 'scope', width: 100, align: 'center', render: (row) => h(NTag, { size: 'small', round: true }, { default: () => scopeLabels[row.scope] || row.scope }) },
  { title: '事实内容', key: 'content', width: 360, ellipsis: { tooltip: true } },
  { title: '状态', key: 'status', width: 100, align: 'center', render: (row) => h(NTag, { size: 'small', type: row.status === 'active' ? 'success' : 'warning', round: true }, { default: () => row.status }) },
  { title: '置信度', key: 'confidence', width: 90, align: 'center', render: (row) => `${Math.round(row.confidence * 100)}%` },
  { title: '记录时间', key: 'created_at', width: 170, align: 'center', render: (row) => formatDate(row.created_at) },
  { title: '最近召回', key: 'last_recalled_at', width: 170, align: 'center', render: (row) => formatDate(row.last_recalled_at) },
]

const legacyColumns: DataTableColumns<LegacyMemory> = [
  { title: '范围', key: 'scope', width: 120, align: 'center', render: (row) => h(NTag, { size: 'small', round: true }, { default: () => scopeLabels[row.scope] || row.scope }) },
  { title: '记忆内容', key: 'content', width: 500, ellipsis: { tooltip: true } },
  { title: '标识', key: 'id', width: 90, align: 'center', ellipsis: { tooltip: true } },
]

async function loadUsers() {
  usersLoading.value = true
  try {
    const { data } = await apiClient.get<AdminUser[]>('/admin/users')
    users.value = data
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '用户列表加载失败')
  } finally {
    usersLoading.value = false
  }
}

async function loadOverview() {
  if (!selectedUserId.value) {
    overview.value = null
    return
  }
  loading.value = true
  try {
    const { data } = await apiClient.get<MemoryOverview>(`/admin/users/${selectedUserId.value}/memory-overview`, {
      params: {
        agent_id: selectedAgentId.value || undefined,
        scope: selectedScope.value || undefined,
        include_archived: true,
      },
    })
    overview.value = data
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '记忆审计数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadUsers()
  const queryUserId = new URLSearchParams(window.location.search).get('user_id')
  if (queryUserId && users.value.some((user) => user.id === queryUserId)) {
    selectedUserId.value = queryUserId
    await loadOverview()
  }
})
</script>

<style scoped>
.admin-memory-page { display: flex; min-height: 100%; flex-direction: column; gap: var(--space-lg); }
.admin-memory-filter, .admin-memory-card { background: var(--neutral-card); }
.admin-memory-alert { margin-bottom: var(--space-lg); }
.admin-memory-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--card-gap); }
.admin-memory-summary span { display: block; color: var(--neutral-text-3); font-size: 13px; }
.admin-memory-summary strong { display: block; margin-top: 6px; color: var(--neutral-text-1); font-size: 26px; }
.admin-block-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--card-gap); }
.admin-block { min-height: 140px; padding: var(--space-md); border: 1px solid var(--neutral-border); border-radius: var(--radius-md); }
.admin-block__title { display: flex; align-items: center; justify-content: space-between; gap: var(--space-sm); }
.admin-block p { min-height: 70px; margin: var(--space-md) 0; color: var(--neutral-text-2); line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.admin-block small { color: var(--neutral-text-3); }
@media (max-width: 900px) { .admin-memory-summary, .admin-block-grid { grid-template-columns: 1fr; } }
</style>
