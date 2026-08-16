<script setup lang="ts">
import { computed, h, ref } from 'vue'
import {
  NButton, NIcon, NTabs, NTabPane, NTag, NModal, NScrollbar, NDataTable,
  useMessage, type DataTableColumns,
} from 'naive-ui'
import { RefreshOutline, StorefrontOutline, CloudUploadOutline } from '@vicons/ionicons5'
import { useAgentHubStore } from '@/stores/agentHub'
import type { SkillItem, SkillVersion } from '@/types/agent'
import type { SkillInvocationRecord, SkillVersionDetail } from '@/types/skill'
import VersionHistoryDrawer, { type VersionHistoryItem } from './VersionHistoryDrawer.vue'
import SkillMarketSection from './skill/SkillMarketSection.vue'
import SkillImportSection from './skill/SkillImportSection.vue'

const message = useMessage()
const store = useAgentHubStore()

const activeTab = ref<'market' | 'import'>('market')
const refreshing = ref(false)
const marketRef = ref<InstanceType<typeof SkillMarketSection> | null>(null)

async function handleRefresh() {
  refreshing.value = true
  try {
    await store.fetchSkills(true)
    marketRef.value?.refresh()
    message.success('列表已刷新')
  } catch {
    message.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

// ---------- Version history ----------
const showVersionDrawer = ref(false)
const versionLoading = ref(false)
const versionRollingBack = ref(false)
const versionSkill = ref<SkillItem | null>(null)
const versionItems = ref<SkillVersion[]>([])

const VERSION_SOURCE_LABELS: Record<string, string> = { admin: '手工更新', import: '导入升级', rollback: '回滚' }
const VERSION_SOURCE_TYPES: Record<string, 'info' | 'default' | 'warning'> = { admin: 'default', import: 'info', rollback: 'warning' }

const versionDrawerItems = computed<VersionHistoryItem[]>(() =>
  versionItems.value.map((v) => ({
    label: `r${v.revision}`,
    subLabel: v.version ? `v${v.version}` : undefined,
    sourceLabel: VERSION_SOURCE_LABELS[v.source] ?? v.source,
    sourceType: VERSION_SOURCE_TYPES[v.source] ?? 'default',
    changelog: v.changelog ?? '',
    createdBy: v.created_by,
    createdAt: v.created_at,
    rollbackTarget: `r${v.revision}`,
    raw: v,
  })),
)

async function openVersions(skill: SkillItem) {
  versionSkill.value = skill
  showVersionDrawer.value = true
  versionLoading.value = true
  try {
    versionItems.value = await store.fetchSkillVersions(skill.id)
  } catch (e) {
    message.error(apiErrorMessage(e))
    versionItems.value = []
  } finally {
    versionLoading.value = false
  }
}

async function handleVersionRollback(item: VersionHistoryItem) {
  const v = item.raw as SkillVersion
  if (!versionSkill.value) return
  versionRollingBack.value = true
  try {
    await store.rollbackSkill(versionSkill.value.id, v.revision)
    message.success(`已回滚到 r${v.revision}`)
    versionItems.value = await store.fetchSkillVersions(versionSkill.value.id)
  } catch (e) {
    message.error(apiErrorMessage(e))
  } finally {
    versionRollingBack.value = false
  }
}

// ---------- Version diff ----------
const showDiff = ref(false)
const diffLoading = ref(false)
const diffTitle = ref('')
const diffLines = ref<Array<{ type: 'same' | 'add' | 'del'; text: string }>>([])

function versionDoc(d: SkillVersionDetail): string {
  return `# ${d.name}\n\n${d.description}\n\n---\n\n${d.prompt}`
}

function computeLineDiff(oldText: string, newText: string) {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: Array<{ type: 'same' | 'add' | 'del'; text: string }> = []
  let i = 0, j = 0
  while (i < m && j < n) {
    if (a[i] === b[j]) { out.push({ type: 'same', text: a[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ type: 'del', text: a[i] }); i++ }
    else { out.push({ type: 'add', text: b[j] }); j++ }
  }
  while (i < m) out.push({ type: 'del', text: a[i++] })
  while (j < n) out.push({ type: 'add', text: b[j++] })
  return out
}

async function openVersionDiff(item: VersionHistoryItem) {
  const v = item.raw as SkillVersion
  const skill = versionSkill.value
  const latest = versionItems.value[0]
  if (!skill || !latest) return
  showDiff.value = true
  diffLoading.value = true
  diffTitle.value = `版本对比 · r${v.revision} → 当前 r${latest.revision}`
  diffLines.value = []
  try {
    const [oldDetail, newDetail] = await Promise.all([
      store.fetchSkillVersionDetail(skill.id, v.revision),
      store.fetchSkillVersionDetail(skill.id, latest.revision),
    ])
    diffLines.value = computeLineDiff(versionDoc(oldDetail), versionDoc(newDetail))
  } catch (e) {
    message.error(apiErrorMessage(e))
    showDiff.value = false
  } finally {
    diffLoading.value = false
  }
}

// ---------- Invocation records ----------
const showInvocations = ref(false)
const invocationsSkill = ref<SkillItem | null>(null)
const invocations = ref<SkillInvocationRecord[]>([])
const invocationsLoading = ref(false)

async function openInvocations(skill: SkillItem) {
  invocationsSkill.value = skill
  showInvocations.value = true
  invocationsLoading.value = true
  try {
    invocations.value = await store.fetchSkillInvocations(skill.id, 50)
  } catch (e) {
    message.error(apiErrorMessage(e))
    invocations.value = []
  } finally {
    invocationsLoading.value = false
  }
}

const invocationColumns: DataTableColumns<SkillInvocationRecord> = [
  { title: '时间', key: 'created_at', width: 160, render: (row) => new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) },
  { title: '状态', key: 'status', width: 80, render: (row) => h(NTag, { size: 'tiny', type: row.status === 'completed' ? 'success' : 'error', bordered: false }, { default: () => (row.status === 'completed' ? '成功' : '失败') }) },
  { title: '版本', key: 'skill_version', width: 70, render: (row) => (row.skill_version ? `v${row.skill_version}` : '-') },
  { title: '耗时', key: 'duration_ms', width: 80, render: (row) => row.duration_ms == null ? '-' : row.duration_ms < 1000 ? `${Math.round(row.duration_ms)}ms` : `${(row.duration_ms / 1000).toFixed(1)}s` },
  { title: '结果', key: 'summary', ellipsis: { tooltip: true }, render: (row) => row.error || row.summary || '-' },
]

function apiErrorMessage(e: unknown): string {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err?.response?.data?.detail || err?.message || '操作失败'
}
</script>

<template>
  <div class="resource-tab">
    <div class="tab-header">
      <span class="tab-hint">
        管理可挂载到 Agent 的 SKILL.md 标准技能：市场浏览安装、GitHub / ZIP / Markdown / JSON 多通道导入。
      </span>
      <NButton secondary size="small" :loading="refreshing" @click="handleRefresh">
        <template #icon><NIcon :component="RefreshOutline" /></template>
        刷新列表
      </NButton>
    </div>

    <NTabs v-model:value="activeTab" type="line" animated class="skill-tabs">
      <NTabPane name="market">
        <template #tab><NIcon :component="StorefrontOutline" /> 技能市场</template>
        <SkillMarketSection
          ref="marketRef"
          @open-versions="openVersions"
          @open-invocations="openInvocations"
        />
      </NTabPane>
      <NTabPane name="import">
        <template #tab><NIcon :component="CloudUploadOutline" /> 导入技能</template>
        <SkillImportSection />
      </NTabPane>
    </NTabs>

    <!-- Version history drawer -->
    <VersionHistoryDrawer
      v-model:show="showVersionDrawer"
      :title="`版本历史 · ${versionSkill?.name || ''}`"
      :items="versionDrawerItems"
      :loading="versionLoading"
      :rolling-back="versionRollingBack"
      @rollback="handleVersionRollback"
      @diff="openVersionDiff"
    />

    <!-- Version diff modal -->
    <NModal v-model:show="showDiff" preset="card" :title="diffTitle" style="width: 760px">
      <div v-if="diffLoading" class="diff-loading">加载中…</div>
      <NScrollbar v-else style="max-height: 480px">
        <pre class="diff-view"><template
          v-for="(line, i) in diffLines"
          :key="i"
        ><span class="diff-line" :class="`diff-${line.type}`">{{ line.type === 'add' ? '+ ' : line.type === 'del' ? '- ' : '  ' }}{{ line.text }}
</span></template></pre>
      </NScrollbar>
    </NModal>

    <!-- Invocation records modal -->
    <NModal v-model:show="showInvocations" preset="card" :title="`调用记录 · ${invocationsSkill?.name || ''}`" style="width: 760px">
      <NDataTable
        :columns="invocationColumns"
        :data="invocations"
        :loading="invocationsLoading"
        :row-key="(row: SkillInvocationRecord) => row.id"
        size="small"
        :max-height="420"
      />
    </NModal>
  </div>
</template>

<style scoped>
.tab-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.tab-hint { font-size: 12px; color: var(--n-text-color-3, #999); }
.skill-tabs > :deep(.n-tabs-nav) { margin-bottom: 16px; }

.diff-loading { padding: 24px; text-align: center; color: var(--n-text-color-3, #999); font-size: 12px; }
.diff-view { margin: 0; font-family: var(--n-font-family-mono, monospace); font-size: 12px; line-height: 1.7; white-space: pre-wrap; word-break: break-all; }
.diff-line { display: block; padding: 0 8px; }
.diff-add { background: rgba(24, 160, 88, 0.12); color: #18a058; }
.diff-del { background: rgba(208, 48, 80, 0.10); color: #d03050; }
.diff-same { color: var(--n-text-color-2, #666); }
</style>
