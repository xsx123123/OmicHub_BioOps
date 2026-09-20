<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NInput, NIcon, NEmpty, NSkeleton, NButton, NTag, NSwitch, NTooltip, NPopconfirm,
  NDataTable, NSelect, NCheckbox, NModal, useMessage, useDialog, type DataTableColumns,
} from 'naive-ui'
import {
  RefreshOutline, TimeOutline, TrashOutline, TerminalOutline, CloudOutline, SearchOutline,
  ListOutline, PeopleOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import { adminAgentApi } from '@/api/agent'
import type { AgentTemplate, SkillItem } from '@/types/agent'
import type { AliyunMarketStatus, SkillMarketplaceItem, SkillInvocationStat } from '@/types/skill'
import SkillMarketCard from './SkillMarketCard.vue'

const message = useMessage()
const dialog = useDialog()
const store = useAgentHubStore()

const emit = defineEmits<{
  openVersions: [skill: SkillItem]
  openInvocations: [skill: SkillItem]
}>()

// ---------- State ----------
const searchQuery = ref('')
const sourceFilter = ref<'all' | 'builtin' | 'aliyun'>('all')
const categoryFilter = ref('all')
const installFilter = ref<'all' | 'installed' | 'available'>('all')
const scriptsOnly = ref(false)
const marketplace = ref<SkillMarketplaceItem[]>([])
const marketplaceLoading = ref(false)
const installingId = ref('')
const aliyunStatus = ref<AliyunMarketStatus | null>(null)
const aliyunSyncing = ref(false)
const invocationStats = ref<Record<string, SkillInvocationStat>>({})
const agents = ref<AgentTemplate[]>([])
const assignmentOpen = ref(false)
const assignmentGroup = ref<{ category: string; items: SkillMarketplaceItem[] } | null>(null)
const assignmentAgentId = ref('')
const assignmentLoading = ref(false)

const SOURCE_LABELS: Record<string, string> = {
  builtin: '平台内置', aliyun_official: '阿里云官方', github: 'GitHub',
  zip: 'ZIP', markdown: 'Markdown', json: 'JSON', market: '市场', url: 'URL',
}

const INSTALL_OPTIONS = [
  { label: '全部状态', value: 'all' },
  { label: '已安装', value: 'installed' },
  { label: '待安装', value: 'available' },
]

// ---------- Computed ----------
/** 阿里云官方源总开关（后端 ALIYUN_SKILLS_ENABLED）；关闭时隐藏官方源分组与同步入口 */
const aliyunEnabled = computed(() => aliyunStatus.value?.enabled !== false)

const filteredMarket = computed(() => {
  let items = marketplace.value
  if (sourceFilter.value === 'builtin') {
    items = items.filter((i) => (i.source ?? 'builtin') !== 'aliyun_official')
  } else if (sourceFilter.value === 'aliyun') {
    items = items.filter((i) => i.source === 'aliyun_official')
  }
  if (categoryFilter.value && categoryFilter.value !== 'all') {
    items = items.filter((i) => (i.category || 'general') === categoryFilter.value)
  }
  if (installFilter.value === 'installed') items = items.filter((i) => i.installed)
  if (installFilter.value === 'available') items = items.filter((i) => !i.installed)
  if (scriptsOnly.value) items = items.filter((i) => i.has_scripts)
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    items = items.filter(
      (i) =>
        i.name.toLowerCase().includes(q) ||
        i.description.toLowerCase().includes(q) ||
        (i.category ?? '').toLowerCase().includes(q) ||
        i.skill_id.toLowerCase().includes(q),
    )
  }
  return items
})

const categoryEntries = computed(() => {
  const counts = new Map<string, number>()
  for (const item of marketplace.value) {
    const category = item.category || 'general'
    counts.set(category, (counts.get(category) || 0) + 1)
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([value, count]) => ({ value, count, label: formatCategory(value) }))
})

const categoryOptions = computed(() => [
  { label: '全部分类', value: 'all' },
  ...categoryEntries.value.map(({ label, value, count }) => ({ label: `${label} · ${count}`, value })),
])

const marketGroups = computed(() => {
  const groups = new Map<string, SkillMarketplaceItem[]>()
  for (const item of filteredMarket.value) {
    const category = item.category || 'general'
    const group = groups.get(category) || []
    group.push(item)
    groups.set(category, group)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, items]) => ({ category, items }))
})

const filteredInstalled = computed(() => {
  let items = store.skills as SkillItem[]
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    items = items.filter(
      (i) =>
        i.name.toLowerCase().includes(q) ||
        i.description.toLowerCase().includes(q) ||
        (i.category ?? '').toLowerCase().includes(q),
    )
  }
  return items
})

// ---------- Installed skills table columns ----------
const installedColumns: DataTableColumns<SkillItem> = [
  {
    title: '技能',
    key: 'name',
    minWidth: 220,
    render: (row) =>
      h('div', { class: 'tbl-skill-cell' }, [
        h('span', { class: 'tbl-skill-icon' }, row.icon || '📦'),
        h('div', { class: 'tbl-skill-info' }, [
          h('div', { class: 'tbl-skill-name' }, [
            row.name,
            row.has_scripts
              ? h(NTag, { size: 'tiny', type: 'warning', round: true, bordered: false, style: 'margin-left:6px' }, { default: () => '含脚本' })
              : null,
          ]),
          h('div', { class: 'tbl-skill-desc' }, row.description),
        ]),
      ]),
  },
  {
    title: '版本',
    key: 'version',
    width: 80,
    render: (row) => (row.version ? `v${row.version}` : '-'),
  },
  {
    title: '来源',
    key: 'source',
    width: 110,
    render: (row) =>
      h(NTag, {
        size: 'tiny',
        bordered: false,
        type: row.source === 'aliyun_official' ? 'info' : row.source === 'github' ? 'success' : 'default',
      }, { default: () => SOURCE_LABELS[row.source] ?? row.source }),
  },
  {
    title: '分类',
    key: 'category',
    width: 100,
    render: (row) => (row.category ? h(NTag, { size: 'tiny', round: true, bordered: false }, { default: () => row.category }) : '-'),
  },
  {
    title: '调用',
    key: 'invocations',
    width: 130,
    render: (row) => {
      const stat = invocationStats.value[row.id]
      if (!stat) return h('span', { class: 'tbl-muted' }, '-')
      return h('div', { class: 'tbl-invocation' }, [
        h('span', null, `${stat.total} 次`),
        stat.last_invoked_at
          ? h('span', { class: 'tbl-muted' }, ` · ${formatRelativeTime(stat.last_invoked_at)}`)
          : null,
      ])
    },
  },
  {
    title: '状态',
    key: 'is_active',
    width: 70,
    render: (row) =>
      h(NSwitch, {
        size: 'small',
        value: row.is_active,
        'onUpdate:value': () => handleToggle(row),
      }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 160,
    render: (row) =>
      h('div', { class: 'tbl-actions' }, [
        h(NTooltip, { trigger: 'hover' }, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => emit('openInvocations', row) }, { icon: () => h(NIcon, { component: ListOutline }) }),
          default: () => '调用记录',
        }),
        h(NTooltip, { trigger: 'hover' }, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => emit('openVersions', row) }, { icon: () => h(NIcon, { component: TimeOutline }) }),
          default: () => '版本历史',
        }),
        (row.source === 'github' || row.source === 'aliyun_official')
          ? h(NTooltip, { trigger: 'hover' }, {
              trigger: () => h(NButton, { size: 'tiny', quaternary: true, onClick: () => handleCheckUpdate(row) }, { icon: () => h(NIcon, { component: RefreshOutline }) }),
              default: () => '检查上游更新',
            })
          : null,
        h(NPopconfirm, { onPositiveClick: () => handleDelete(row) }, {
          trigger: () => h(NButton, { size: 'tiny', quaternary: true, type: 'error' }, { icon: () => h(NIcon, { component: TrashOutline }) }),
          default: () => '确定删除该技能？',
        }),
      ]),
  },
]

// ---------- Lifecycle ----------
onMounted(() => {
  void loadMarketplace()
  void loadInvocationStats()
  void loadAgents()
})

// ---------- Methods ----------
async function loadMarketplace() {
  marketplaceLoading.value = true
  try {
    const [items, status] = await Promise.allSettled([
      store.fetchSkillMarketplace(),
      store.fetchAliyunMarketStatus(),
    ])
    if (items.status === 'fulfilled') marketplace.value = items.value
    if (status.status === 'fulfilled') {
      aliyunStatus.value = status.value
      if (status.value.enabled === false) {
        if (sourceFilter.value === 'aliyun') sourceFilter.value = 'all'
      } else if (status.value.last_synced_at === null && !aliyunSyncing.value) {
        void handleSyncAliyun(false)
      }
    }
  } finally {
    marketplaceLoading.value = false
  }
}

async function loadInvocationStats() {
  try {
    const stats = await store.fetchSkillInvocationStats()
    const map: Record<string, SkillInvocationStat> = {}
    for (const s of stats) map[s.skill_id] = s
    invocationStats.value = map
  } catch {
    // non-critical
  }
}

async function loadAgents() {
  try {
    agents.value = await adminAgentApi.list()
    if (!assignmentAgentId.value) assignmentAgentId.value = agents.value[0]?.id || ''
  } catch (e) {
    message.error(apiErrorMessage(e))
  }
}

async function handleSyncAliyun(force: boolean) {
  if (aliyunSyncing.value || !aliyunEnabled.value) return
  aliyunSyncing.value = true
  try {
    aliyunStatus.value = await store.syncAliyunMarket(force)
    marketplace.value = await store.fetchSkillMarketplace()
    if (aliyunStatus.value?.error && !aliyunStatus.value.available) {
      message.warning(`官方源同步失败：${aliyunStatus.value.error}`)
    } else {
      message.success(`阿里云官方源已同步（${aliyunStatus.value?.count ?? 0} 项）`)
    }
  } catch (e) {
    message.error(apiErrorMessage(e))
  } finally {
    aliyunSyncing.value = false
  }
}

async function handleInstall(item: SkillMarketplaceItem) {
  installingId.value = item.skill_id
  try {
    if (item.source === 'aliyun_official') {
      await store.installAliyunMarketSkill(item.skill_id, item.installed)
    } else {
      await store.installMarketplaceSkill(item.skill_id, item.installed)
    }
    message.success(`已安装「${item.name}」`)
    await loadMarketplace()
    await store.fetchSkills(true)
    await loadInvocationStats()
  } catch (e) {
    message.error(apiErrorMessage(e))
  } finally {
    installingId.value = ''
  }
}

function openGroupAssignment(group: { category: string; items: SkillMarketplaceItem[] }) {
  assignmentGroup.value = group
  assignmentAgentId.value = agents.value[0]?.id || ''
  assignmentOpen.value = true
}

async function handleAssignGroup() {
  const group = assignmentGroup.value
  const agent = agents.value.find((item) => item.id === assignmentAgentId.value)
  if (!group || !agent) {
    message.warning('请选择目标 Agent')
    return
  }
  assignmentLoading.value = true
  try {
    const skillIds = new Set(agent.skill_ids)
    for (const item of group.items) {
      if (!item.installed) {
        if (item.source === 'aliyun_official') {
          await store.installAliyunMarketSkill(item.skill_id, false, false)
        } else {
          await store.installMarketplaceSkill(item.skill_id, false, false)
        }
      }
      skillIds.add(item.skill_id)
    }
    const updated = await adminAgentApi.update(agent.id, { skill_ids: [...skillIds] })
    agents.value = agents.value.map((item) => item.id === updated.id ? updated : item)
    assignmentOpen.value = false
    message.success(`已将「${formatCategory(group.category)}」的 ${group.items.length} 个技能安装并挂载到 ${agent.name}`)
    await loadMarketplace()
    await store.fetchSkills(true)
  } catch (e) {
    message.error(apiErrorMessage(e))
  } finally {
    assignmentLoading.value = false
  }
}

function handleToggle(skill: SkillItem) {
  store.toggleSkill(skill.id)
}

async function handleDelete(skill: SkillItem) {
  try {
    const refs = await store.fetchSkillReferences(skill.id)
    if (refs.length) {
      dialog.warning({
        title: '删除保护',
        content: `该技能正被 ${refs.length} 个助手引用（${refs.map((r) => r.name).join('、')}）。强制删除后这些助手将失去该技能（版本快照保留），确定继续？`,
        positiveText: '强制删除',
        negativeText: '取消',
        onPositiveClick: async () => {
          try {
            await store.deleteSkill(skill.id, true)
            message.success('已删除')
          } catch (e) {
            message.error(apiErrorMessage(e))
          }
        },
      })
      return
    }
    await store.deleteSkill(skill.id)
    message.success('已删除')
  } catch (e) {
    message.error(apiErrorMessage(e))
  }
}

async function handleCheckUpdate(skill: SkillItem) {
  try {
    const info = await store.checkSkillUpdate(skill.id)
    if (info.has_update) {
      message.info(`发现上游更新（${info.latest_commit}），重新导入即可升级`)
    } else {
      message.success(info.message || '已是最新')
    }
  } catch (e) {
    message.error(apiErrorMessage(e))
  }
}

function apiErrorMessage(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err?.response?.data?.detail || err?.message || '操作失败'
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${Math.floor(diff / 86_400_000)} 天前`
}

function formatCategory(value: string): string {
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

defineExpose({ refresh: loadMarketplace })
</script>

<template>
  <div class="skill-market-section">
    <!-- Toolbar -->
    <div class="market-toolbar">
      <NInput
        v-model:value="searchQuery"
        clearable
        placeholder="搜索技能名称或描述"
        class="market-search"
      >
        <template #prefix><NIcon :component="SearchOutline" /></template>
      </NInput>
      <div class="cygnusx-segmented-toggle" role="group" aria-label="来源筛选">
        <button :class="{ active: sourceFilter === 'all' }" :aria-pressed="sourceFilter === 'all'" @click="sourceFilter = 'all'">全部</button>
        <button :class="{ active: sourceFilter === 'builtin' }" :aria-pressed="sourceFilter === 'builtin'" @click="sourceFilter = 'builtin'">平台内置</button>
        <button v-if="aliyunEnabled" :class="{ active: sourceFilter === 'aliyun' }" :aria-pressed="sourceFilter === 'aliyun'" @click="sourceFilter = 'aliyun'">阿里云官方</button>
      </div>
      <NSelect
        v-model:value="categoryFilter"
        :options="categoryOptions"
        filterable
        placeholder="按分类筛选"
        class="market-filter-select"
        aria-label="按分类筛选"
      />
      <NSelect
        v-model:value="installFilter"
        :options="INSTALL_OPTIONS"
        class="market-filter-select market-status-select"
        aria-label="按安装状态筛选"
      />
      <NCheckbox v-model:checked="scriptsOnly">仅显示含脚本</NCheckbox>
    </div>

    <div class="category-tags" role="group" aria-label="技能分类快捷筛选">
      <button
        class="category-chip"
        :class="{ active: categoryFilter === 'all' }"
        :aria-pressed="categoryFilter === 'all'"
        @click="categoryFilter = 'all'"
      >
        全部 <span>{{ marketplace.length }}</span>
      </button>
      <button
        v-for="entry in categoryEntries"
        :key="entry.value"
        class="category-chip"
        :class="{ active: categoryFilter === entry.value }"
        :aria-pressed="categoryFilter === entry.value"
        @click="categoryFilter = entry.value"
      >
        {{ entry.label }} <span>{{ entry.count }}</span>
      </button>
    </div>

    <!-- Installed Skills Table -->
    <div class="installed-section">
      <div class="section-header">
        <span class="section-title">已安装技能</span>
        <NTag size="tiny" :bordered="false">{{ filteredInstalled.length }}</NTag>
      </div>
      <NDataTable
        v-if="filteredInstalled.length"
        :columns="installedColumns"
        :data="filteredInstalled"
        :row-key="(row: SkillItem) => row.id"
        size="small"
        :bordered="false"
        class="installed-table"
      />
      <NEmpty v-else description="暂无已安装技能，从下方市场安装或切换到「导入技能」标签页" />
    </div>

    <!-- Market Grid -->
    <div class="market-section">
      <div class="section-header">
        <span class="section-title">技能市场</span>
        <div v-if="aliyunStatus && aliyunEnabled" class="aliyun-sync-meta">
          <NIcon :component="CloudOutline" size="13" />
          <template v-if="aliyunStatus.last_synced_at">
            同步于 {{ formatRelativeTime(aliyunStatus.last_synced_at) }}
            <NTag v-if="aliyunStatus.stale" size="tiny" type="warning" :bordered="false">可更新</NTag>
          </template>
          <template v-else>未同步</template>
          <NTooltip trigger="hover">
            <template #trigger>
              <NButton size="tiny" quaternary :loading="aliyunSyncing" @click="handleSyncAliyun(aliyunStatus?.stale ?? false)">
                <template #icon><NIcon :component="RefreshOutline" /></template>
              </NButton>
            </template>
            同步阿里云官方 Skills 源
          </NTooltip>
        </div>
      </div>

      <div v-if="marketplaceLoading" class="market-grid">
        <div v-for="i in 4" :key="i" class="skeleton-card">
          <NSkeleton circle :width="48" :height="48" />
          <div class="skeleton-body">
            <NSkeleton text :width="'60%'" />
            <NSkeleton text :width="'90%'" style="margin-top: 8px" />
            <NSkeleton text :width="'75%'" style="margin-top: 6px" />
            <NSkeleton :width="72" :height="28" style="margin-top: 12px; border-radius: 6px" />
          </div>
        </div>
      </div>

      <template v-else>
        <div v-if="filteredMarket.length" class="market-groups">
          <section v-for="group in marketGroups" :key="group.category" class="market-group">
            <div class="group-header">
              <div class="group-heading">
                <span class="group-title">{{ formatCategory(group.category) }}</span>
                <NTag size="tiny" round :bordered="false">{{ group.items.length }} 个</NTag>
              </div>
              <NButton size="small" secondary @click="openGroupAssignment(group)">
                <template #icon><NIcon :component="PeopleOutline" /></template>
                安装到 Agent
              </NButton>
            </div>
            <div class="market-grid">
              <SkillMarketCard
                v-for="item in group.items"
                :key="item.skill_id"
                :item="item"
                :installing="installingId === item.skill_id"
                @install="handleInstall(item)"
              />
            </div>
          </section>
        </div>
        <NEmpty v-else description="未找到相关技能，换个关键词试试" class="market-empty" />

        <div v-if="aliyunStatus && aliyunEnabled && !aliyunStatus.available && aliyunStatus.error" class="aliyun-warning">
          <NTag size="small" type="warning" :bordered="false">
            <NIcon :component="CloudOutline" /> 官方源暂不可用：{{ aliyunStatus.error }}
          </NTag>
          <NButton size="tiny" :loading="aliyunSyncing" @click="handleSyncAliyun(true)">重试同步</NButton>
        </div>
      </template>
    </div>

    <NModal v-model:show="assignmentOpen" preset="card" style="width: min(520px, calc(100vw - 32px))" title="将分类安装到 Agent">
      <div v-if="assignmentGroup" class="assignment-content">
        <div class="assignment-summary">
          <strong>{{ formatCategory(assignmentGroup.category) }}</strong>
          <span>{{ assignmentGroup.items.length }} 个技能将被安装并挂载</span>
        </div>
        <NSelect
          v-model:value="assignmentAgentId"
          :options="agents.map((agent) => ({ label: `${agent.name} · 已挂载 ${agent.skill_ids.length} 个`, value: agent.id }))"
          placeholder="选择目标 Agent"
          aria-label="选择目标 Agent"
        />
        <div class="assignment-hint">已安装的技能会直接复用；未安装技能将先写入技能库，再追加到 Agent 的挂载列表。</div>
        <div class="assignment-actions">
          <NButton @click="assignmentOpen = false">取消</NButton>
          <NButton type="primary" :loading="assignmentLoading" :disabled="!assignmentAgentId" @click="handleAssignGroup">确认安装并挂载</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.skill-market-section { display: flex; flex-direction: column; gap: 24px; }

.market-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
  flex-wrap: wrap;
}
.market-search { max-width: 320px; }
.market-filter-select { width: 180px; }
.market-status-select { width: 140px; }

.category-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 4px;
}
.category-chip {
  border: 1px solid var(--neutral-border);
  border-radius: 999px;
  padding: 5px 10px;
  background: var(--neutral-card);
  color: var(--neutral-text-2, #666);
  font-size: 12px;
  cursor: pointer;
  transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease;
}
.category-chip span { margin-left: 3px; color: var(--neutral-text-3, #999); }
.category-chip:hover,
.category-chip:focus-visible { border-color: var(--arco-primary, #4c6fff); color: var(--arco-primary, #4c6fff); outline: none; }
.category-chip.active { border-color: var(--arco-primary, #4c6fff); background: var(--arco-primary-light-1, rgba(76, 111, 255, 0.1)); color: var(--arco-primary, #4c6fff); }

.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary, #333); }

.installed-section { display: flex; flex-direction: column; }
.installed-table :deep(.n-data-table-th) { font-size: 12px; }
.installed-table :deep(.n-data-table-td) { font-size: 13px; }

.market-section { display: flex; flex-direction: column; }
.market-groups { display: flex; flex-direction: column; gap: 28px; }
.market-group { display: flex; flex-direction: column; gap: 12px; }
.group-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.group-heading { display: flex; align-items: center; gap: 8px; min-width: 0; }
.group-title { font-size: 16px; font-weight: 650; color: var(--text-primary, #333); }
.market-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}
@media (max-width: 767px) {
  .market-grid { grid-template-columns: 1fr; }
}

.skeleton-card {
  display: flex;
  gap: 14px;
  padding: 20px 24px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 12px;
}
.skeleton-body { flex: 1; }

.market-empty { padding: 40px 0; }

.aliyun-warning {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  margin-top: 12px;
  background: var(--neutral-card);
  border: 1px solid var(--neutral-border);
  border-radius: 8px;
}

.aliyun-sync-meta {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--neutral-text-3, #999);
}
.assignment-content { display: flex; flex-direction: column; gap: 16px; }
.assignment-summary { display: flex; flex-direction: column; gap: 4px; color: var(--neutral-text-2, #666); }
.assignment-summary strong { color: var(--text-primary, #333); font-size: 16px; }
.assignment-hint { font-size: 12px; line-height: 1.6; color: var(--neutral-text-3, #888); }
.assignment-actions { display: flex; justify-content: flex-end; gap: 8px; }

@media (max-width: 767px) {
  .market-toolbar { padding: 14px; }
  .market-search, .market-filter-select, .market-status-select { width: 100%; max-width: none; }
  .group-header { align-items: flex-start; }
  .group-header :deep(.n-button) { flex-shrink: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .category-chip { transition: none; }
}
</style>

<style>
/* Table cell styles (unscoped for render functions) */
.tbl-skill-cell { display: flex; align-items: center; gap: 10px; }
.tbl-skill-icon {
  font-size: 22px;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand-primary-light, rgba(76, 111, 255, 0.08));
  border-radius: 8px;
  flex-shrink: 0;
}
.tbl-skill-info { min-width: 0; }
.tbl-skill-name { font-weight: 600; font-size: 13px; display: flex; align-items: center; }
.tbl-skill-desc {
  font-size: 12px;
  color: var(--neutral-text-3, #888);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
.tbl-muted { font-size: 11px; color: var(--neutral-text-3, #999); }
.tbl-invocation { font-size: 12px; }
.tbl-actions { display: flex; align-items: center; gap: 2px; }
</style>
