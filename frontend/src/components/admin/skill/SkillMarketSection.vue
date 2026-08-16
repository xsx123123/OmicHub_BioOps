<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NInput, NIcon, NEmpty, NSkeleton, NButton, NTag, NSwitch, NTooltip, NPopconfirm,
  NDataTable, useMessage, useDialog, type DataTableColumns,
} from 'naive-ui'
import {
  RefreshOutline, TimeOutline, TrashOutline, TerminalOutline, CloudOutline, SearchOutline,
  ListOutline,
} from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { SkillItem } from '@/types/agent'
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
const marketplace = ref<SkillMarketplaceItem[]>([])
const marketplaceLoading = ref(false)
const installingId = ref('')
const aliyunStatus = ref<AliyunMarketStatus | null>(null)
const aliyunSyncing = ref(false)
const invocationStats = ref<Record<string, SkillInvocationStat>>({})

const SOURCE_LABELS: Record<string, string> = {
  builtin: '平台内置', aliyun_official: '阿里云官方', github: 'GitHub',
  zip: 'ZIP', markdown: 'Markdown', json: 'JSON', market: '市场', url: 'URL',
}

// ---------- Computed ----------
const filteredMarket = computed(() => {
  let items = marketplace.value
  if (sourceFilter.value === 'builtin') {
    items = items.filter((i) => (i.source ?? 'builtin') !== 'aliyun_official')
  } else if (sourceFilter.value === 'aliyun') {
    items = items.filter((i) => i.source === 'aliyun_official')
  }
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
      if (status.value && status.value.last_synced_at === null && !aliyunSyncing.value) {
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

async function handleSyncAliyun(force: boolean) {
  if (aliyunSyncing.value) return
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
      <div class="omichub-segmented-toggle" role="group" aria-label="来源筛选">
        <button :class="{ active: sourceFilter === 'all' }" :aria-pressed="sourceFilter === 'all'" @click="sourceFilter = 'all'">全部</button>
        <button :class="{ active: sourceFilter === 'builtin' }" :aria-pressed="sourceFilter === 'builtin'" @click="sourceFilter = 'builtin'">平台内置</button>
        <button :class="{ active: sourceFilter === 'aliyun' }" :aria-pressed="sourceFilter === 'aliyun'" @click="sourceFilter = 'aliyun'">阿里云官方</button>
      </div>
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
        <div v-if="aliyunStatus" class="aliyun-sync-meta">
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
        <div v-if="filteredMarket.length" class="market-grid">
          <SkillMarketCard
            v-for="item in filteredMarket"
            :key="item.skill_id"
            :item="item"
            :installing="installingId === item.skill_id"
            @install="handleInstall(item)"
          />
        </div>
        <NEmpty v-else description="未找到相关技能，换个关键词试试" class="market-empty" />

        <div v-if="aliyunStatus && !aliyunStatus.available && aliyunStatus.error" class="aliyun-warning">
          <NTag size="small" type="warning" :bordered="false">
            <NIcon :component="CloudOutline" /> 官方源暂不可用：{{ aliyunStatus.error }}
          </NTag>
          <NButton size="tiny" :loading="aliyunSyncing" @click="handleSyncAliyun(true)">重试同步</NButton>
        </div>
      </template>
    </div>
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

.section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.section-title { font-size: 14px; font-weight: 600; color: var(--text-primary, #333); }

.installed-section { display: flex; flex-direction: column; }
.installed-table :deep(.n-data-table-th) { font-size: 12px; }
.installed-table :deep(.n-data-table-td) { font-size: 13px; }

.market-section { display: flex; flex-direction: column; }
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
