<template>
  <main class="memory-page" :aria-busy="isLoading">
    <div class="memory-page__content">
      <PageHeader title="我的记忆" subtitle="查看和管理从 AI 对话中沉淀的研究偏好、项目事实与对话摘要。">
        <template #actions>
          <NButton secondary @click="router.push('/profile')">
            <template #icon><NIcon><ArrowBackOutline /></NIcon></template>
            返回个人中心
          </NButton>
          <NButton secondary :loading="isRefreshing" @click="loadMemories(true)">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            刷新
          </NButton>
          <NButton v-if="memories.length" type="error" secondary @click="clearMemories">
            清空全部
          </NButton>
        </template>
      </PageHeader>

      <NCard :bordered="false" class="memory-card">
        <div class="memory-card__summary">
          <div>
            <span class="memory-card__eyebrow">长期记忆</span>
            <strong>{{ memories.length }}</strong>
            <span>条已保存</span>
          </div>
          <NButton v-if="!memories.length" :loading="isRebuilding" @click="rebuildMemories">
            整理已有对话
          </NButton>
        </div>

        <NSpace v-if="memories.length" size="small" class="memory-filter">
          <NButton
            v-for="option in memoryScopeOptions"
            :key="option.key"
            size="small"
            secondary
            :type="memoryScopeFilter === option.key ? 'primary' : 'default'"
            @click="memoryScopeFilter = option.key"
          >{{ option.label }}</NButton>
        </NSpace>

        <NSpin :show="isLoading">
          <div v-if="filteredMemories.length" class="memory-list">
            <div v-for="memory in filteredMemories" :key="memory.id" class="memory-row">
              <span><NTag size="small" round>{{ memoryScopeLabel(memory.scope) }}</NTag></span>
              <div>
                <strong>{{ memory.content }}</strong>
                <small>
                  {{ memoryAgentLabel(memory) }} · {{ formatRelative(memory.updated_at) }}
                  <template v-if="memory.source_session"> · <span :title="`来源会话 ${memory.source_session}`">对话沉淀</span></template>
                </small>
              </div>
              <NButton text type="error" size="small" @click="deleteMemory(memory.id)">删除</NButton>
            </div>
          </div>
          <NEmpty v-else size="small" description="暂无符合条件的记忆。" />
        </NSpin>
      </NCard>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NEmpty, NIcon, NSpin, NSpace, NTag, useMessage } from 'naive-ui'
import { ArrowBackOutline, RefreshOutline } from '@vicons/ionicons5'
import { formatDistanceToNow, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import apiClient from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'

interface AgentMemory {
  id: string
  agent_id: string | null
  scope: 'profile' | 'project' | 'preference' | 'summary'
  content: string
  updated_at: string | null
  source_session?: string | null
}

const router = useRouter()
const message = useMessage()
const memories = ref<AgentMemory[]>([])
const isLoading = ref(true)
const isRefreshing = ref(false)
const isRebuilding = ref(false)
const memoryScopeFilter = ref<'all' | AgentMemory['scope']>('all')
const memoryScopeOptions: Array<{ key: 'all' | AgentMemory['scope']; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'profile', label: '用户画像' },
  { key: 'preference', label: '偏好' },
  { key: 'project', label: '项目' },
  { key: 'summary', label: '对话沉淀' },
]
const filteredMemories = computed(() => memoryScopeFilter.value === 'all'
  ? memories.value
  : memories.value.filter((memory) => memory.scope === memoryScopeFilter.value))
const agentLabels: Record<string, string> = {
  'agent-general': '通用助手',
  'agent-rnaseq': 'RNA-seq 分析师',
  'agent-scrna': '单细胞分析师',
  'agent-scrna-upstream': '单细胞上游',
  'agent-scrna-integration': '单细胞整合',
  'agent-scrna-advanced': '单细胞进阶',
  'agent-code': '代码助手',
  'agent-viz': '可视化助手',
  'agent-mcp-builder': 'MCP 构建师',
  shania: '傻妞',
}

function memoryScopeLabel(scope: AgentMemory['scope']) {
  return ({ profile: '用户画像', project: '项目', preference: '偏好', summary: '摘要' }[scope])
}

function memoryAgentLabel(memory: AgentMemory) {
  return memory.agent_id ? (agentLabels[memory.agent_id] || memory.agent_id) : '全局记忆'
}

function formatRelative(value?: string | null) {
  if (!value) return '-'
  const date = parseISO(value)
  return Number.isNaN(date.getTime()) ? '-' : formatDistanceToNow(date, { addSuffix: true, locale: zhCN })
}

async function loadMemories(refresh = false) {
  if (refresh) isRefreshing.value = true
  else isLoading.value = true
  try {
    const { data } = await apiClient.get<AgentMemory[]>('/users/me/memories')
    memories.value = data
  } catch (error: any) {
    message.error(error.response?.data?.detail || '记忆加载失败')
  } finally {
    isLoading.value = false
    isRefreshing.value = false
  }
}

async function deleteMemory(memoryId: string) {
  try {
    await apiClient.delete(`/users/me/memories/${memoryId}`)
    memories.value = memories.value.filter((memory) => memory.id !== memoryId)
    message.success('记忆已删除')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '删除记忆失败')
  }
}

async function clearMemories() {
  if (!window.confirm('确定清空全部跨会话记忆吗？此操作不会影响聊天记录。')) return
  try {
    await apiClient.delete('/users/me/memories')
    memories.value = []
    message.success('已清空全部记忆')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '清空记忆失败')
  }
}

async function rebuildMemories() {
  isRebuilding.value = true
  try {
    const { data } = await apiClient.post<{ status: string; queued: number }>('/users/me/memories/rebuild')
    if (data.status === 'disabled') message.warning('平台记忆功能尚未启用，请联系管理员检查配置')
    else message.success(data.queued ? `已提交 ${data.queued} 个历史会话` : '暂时没有达到沉淀条件的历史会话')
  } catch (error: any) {
    message.error(error.response?.data?.detail || '历史记忆整理失败')
  } finally {
    isRebuilding.value = false
  }
}

onMounted(() => loadMemories())
</script>

<style scoped>
.memory-page {
  min-height: 100%;
  padding: var(--page-padding) var(--page-padding) var(--space-5xl);
  background: var(--neutral-bg);
}

.memory-page__content {
  width: 100%;
}

.memory-card {
  margin-top: var(--space-lg);
  background: var(--neutral-card);
}

.memory-card__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-lg);
  margin-bottom: var(--space-lg);
  padding-bottom: var(--space-lg);
  border-bottom: 1px solid var(--neutral-border);
  color: var(--neutral-text-3);
}

.memory-card__summary > div {
  display: flex;
  align-items: baseline;
  gap: var(--space-sm);
}

.memory-card__eyebrow {
  color: var(--neutral-text-2);
  font-weight: 600;
}

.memory-card__summary strong {
  color: var(--neutral-text-1);
  font-size: 28px;
  line-height: 1;
}

.memory-filter {
  margin-bottom: var(--space-lg);
}

.memory-list {
  display: grid;
  gap: 0;
}

.memory-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-md);
  padding: var(--space-md) 0;
  border-bottom: 1px solid var(--neutral-border);
}

.memory-row:last-child {
  border-bottom: 0;
}

.memory-row > div {
  min-width: 0;
  flex: 1;
}

.memory-row strong {
  display: block;
  color: var(--neutral-text-1);
  font-size: 14px;
  line-height: 1.6;
}

.memory-row small {
  display: block;
  margin-top: 5px;
  color: var(--neutral-text-3);
  font-size: 12px;
}

@media (max-width: 640px) {
  .memory-page {
    padding: var(--space-2xl) var(--space-lg) var(--space-5xl);
  }

  .memory-card__summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .memory-row {
    flex-wrap: wrap;
  }

  .memory-row > div {
    flex-basis: calc(100% - 40px);
  }
}
</style>
