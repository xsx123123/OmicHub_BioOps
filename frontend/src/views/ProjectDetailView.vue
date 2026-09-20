<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NCard, NDataTable, NDescriptions, NDescriptionsItem, NEmpty, NInput, NModal,
  NIcon, NPopconfirm, NSkeleton, NSpace, NSpin, NSwitch, NTabPane, NTabs, NTag, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { ChatbubblesOutline, FolderOpenOutline, GitBranchOutline, TimeOutline } from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import { chatApi } from '@/api/chat'
import {
  projectsApi,
  type ProjectOverview,
  type ProjectRunItem,
  type ProjectSessionItem,
  type ProjectSessionStatus,
} from '@/api/projects'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const projectId = computed(() => String(route.params.projectId || ''))
/** 首次加载整页骨架；切换会话状态分组只对会话表区域 NSpin 局部刷新（§5.4） */
const initialLoading = ref(true)
const sessionsLoading = ref(false)
const overview = ref<ProjectOverview | null>(null)
const sessionStatus = ref<ProjectSessionStatus>('active')

const renameTarget = ref<ProjectSessionItem | null>(null)
const renameTitle = ref('')
const renameSaving = ref(false)

/** 项目级科研模式默认值（WP3 任务 3 可选项）：项目内新会话默认开启科研模式。
 *  后端项目设置端点可能稍后到位：PATCH 失败时回滚开关并提示，不阻塞页面。 */
const projectResearchDefault = ref(false)
const togglingProjectResearch = ref(false)

async function handleProjectResearchToggle(value: boolean) {
  if (togglingProjectResearch.value) return
  const previous = projectResearchDefault.value
  projectResearchDefault.value = value
  togglingProjectResearch.value = true
  try {
    await projectsApi.updateProjectSettings(projectId.value, {
      research_mode: {
        enabled: value,
        render_mode: 'message_flow',
        workspace_protocol: 'standard',
        ptc_llm_query: false,
      },
    })
    message.success(value ? '已开启：项目内新会话将默认开启科研模式' : '已关闭项目级科研模式默认开关')
  } catch (e: any) {
    projectResearchDefault.value = previous
    message.error(e?.response?.data?.detail || '项目设置保存失败（后端端点可能尚未上线），已恢复开关状态')
  } finally {
    togglingProjectResearch.value = false
  }
}

function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '—'
}

function formatSize(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

function mutedText(value: string | null | undefined) {
  return value
    ? value
    : h('span', { class: 'cell-muted' }, '—')
}

function sessionModeLabel(mode: string) {
  if (mode === 'studio') return '工作台'
  if (mode === 'agentteams') return '协作室'
  return '对话'
}

function openSession(row: ProjectSessionItem) {
  if (row.mode === 'agentteams') {
    // AgentTeams 协作会话：优先按 room_id 直达协作房间，其次 case_id，兜底进入协作室首页
    if (row.room_id) {
      void router.push({ name: 'agent-teams-room', query: { room: row.room_id } })
    } else if (row.case_id) {
      void router.push({ name: 'agent-teams-room', query: { case: row.case_id } })
    } else {
      void router.push({ name: 'agent-teams-room' })
    }
    return
  }
  if (row.mode === 'studio') {
    void router.push({ name: 'studio', params: { sessionId: row.id } })
  } else {
    void router.push({ name: 'ai', params: { sessionId: row.id } })
  }
}

function startRename(row: ProjectSessionItem) {
  renameTarget.value = row
  renameTitle.value = row.title
}

async function saveRename() {
  const target = renameTarget.value
  const title = renameTitle.value.trim()
  if (!target || !title) return
  renameSaving.value = true
  try {
    await chatApi.renameSession(target.id, title)
    message.success('会话已重命名')
    renameTarget.value = null
    await loadSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '重命名失败，请稍后重试')
  } finally {
    renameSaving.value = false
  }
}

async function removeSession(row: ProjectSessionItem) {
  try {
    await chatApi.deleteSession(row.id)
    message.success('会话已删除，可在回收站中恢复')
    await loadSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '删除失败，请稍后重试')
  }
}

async function archiveSession(row: ProjectSessionItem) {
  try {
    await chatApi.archiveSession(row.id)
    message.success('会话已归档')
    await loadSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '归档失败，请稍后重试')
  }
}

async function unarchiveSession(row: ProjectSessionItem) {
  try {
    await chatApi.unarchiveSession(row.id)
    message.success('已取消归档，会话回到活跃列表')
    await loadSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '取消归档失败，请稍后重试')
  }
}

async function restoreSession(row: ProjectSessionItem) {
  try {
    await chatApi.restoreSession(row.id)
    message.success('会话已恢复到活跃列表')
    await loadSessions()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '恢复失败，请稍后重试')
  }
}

function renderOpenButton(row: ProjectSessionItem) {
  return h(
    NButton,
    { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openSession(row) },
    { default: () => '打开' },
  )
}

function renderSessionActions(row: ProjectSessionItem) {
  // AgentTeams 协作会话由另一套后端体系管理，这里只提供「打开」入口
  if (row.mode === 'agentteams') {
    return h(NSpace, { size: 4, wrap: false }, () => [renderOpenButton(row)])
  }
  if (sessionStatus.value === 'archived') {
    return h(NSpace, { size: 4, wrap: false }, () => [
      renderOpenButton(row),
      h(
        NButton,
        { size: 'tiny', quaternary: true, onClick: () => unarchiveSession(row) },
        { default: () => '取消归档' },
      ),
    ])
  }
  if (sessionStatus.value === 'deleted') {
    return h(NSpace, { size: 4, wrap: false }, () => [
      h(
        NPopconfirm,
        { onPositiveClick: () => restoreSession(row) },
        {
          trigger: () =>
            h(
              NButton,
              { size: 'tiny', quaternary: true, type: 'primary' },
              { default: () => '恢复' },
            ),
          default: () => `恢复「${row.title}」到活跃会话列表？`,
        },
      ),
    ])
  }
  return h(NSpace, { size: 4, wrap: false }, () => [
    renderOpenButton(row),
    h(
      NButton,
      { size: 'tiny', quaternary: true, onClick: () => startRename(row) },
      { default: () => '重命名' },
    ),
    h(
      NPopconfirm,
      { onPositiveClick: () => archiveSession(row) },
      {
        trigger: () =>
          h(
            NButton,
            { size: 'tiny', quaternary: true },
            { default: () => '归档' },
          ),
        default: () => `归档「${row.title}」？归档后可在「已归档」分组中找回。`,
      },
    ),
    h(
      NPopconfirm,
      { onPositiveClick: () => removeSession(row) },
      {
        trigger: () =>
          h(
            NButton,
            { size: 'tiny', quaternary: true, type: 'error' },
            { default: () => '删除' },
          ),
        default: () => `确定删除「${row.title}」吗？删除后进入回收站，可恢复。`,
      },
    ),
  ])
}

// 列全部固定宽（§33.2③），scroll-x = 列宽之和；操作列随状态分组变化，故 columns 用 computed
const sessionColumns = computed<DataTableColumns<ProjectSessionItem>>(() => [
  { title: '会话标题', key: 'title', width: 260, ellipsis: { tooltip: true } },
  {
    title: 'Agent',
    key: 'agent_id',
    width: 140,
    ellipsis: { tooltip: true },
    render: (row) => mutedText(row.agent_id),
  },
  {
    title: '模式',
    key: 'mode',
    width: 90,
    align: 'center',
    render: (row) => sessionModeLabel(row.mode),
  },
  { title: '消息数', key: 'message_count', width: 80, align: 'center' },
  {
    title: '最后消息',
    key: 'last_message_at',
    width: 170,
    align: 'center',
    render: (row) => formatDate(row.last_message_at || row.updated_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 210,
    align: 'center',
    render: renderSessionActions,
  },
])
const sessionScrollX = 260 + 140 + 90 + 80 + 170 + 210

const runColumns: DataTableColumns<ProjectRunItem> = [
  { title: '运行目录', key: 'name', width: 280, ellipsis: { tooltip: true } },
  {
    title: '运行时间',
    key: 'timestamp',
    width: 180,
    align: 'center',
    render: (row) => formatDate(row.timestamp),
  },
  {
    title: '交付物齐备度',
    key: 'artifacts',
    width: 280,
    render(row) {
      const tags = [
        { label: 'AGENTS.md', ok: row.has_agents_md },
        { label: 'README', ok: row.has_readme },
        { label: '环境快照', ok: row.has_environment },
      ]
      return tags.map((tag) =>
        h(
          NTag,
          {
            size: 'small',
            type: tag.ok ? 'success' : 'default',
            bordered: false,
            style: 'margin-right: 6px',
          },
          { default: () => `${tag.ok ? '✓' : '✗'} ${tag.label}` },
        ),
      )
    },
  },
  { title: '文件数', key: 'file_count', width: 90, align: 'center' },
  {
    title: '总大小',
    key: 'total_size_bytes',
    width: 110,
    align: 'center',
    render: (row) => formatSize(row.total_size_bytes),
  },
]
const runScrollX = 280 + 180 + 280 + 90 + 110

const sessionEmptyText: Record<ProjectSessionStatus, string> = {
  active: '当前项目还没有活跃会话',
  archived: '没有已归档的会话',
  deleted: '回收站为空',
}

async function loadOverview() {
  if (!projectId.value) return
  initialLoading.value = true
  try {
    overview.value = await projectsApi.getProjectOverview(projectId.value, {
      session_limit: 100,
      session_status: sessionStatus.value,
    })
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载项目总览失败')
  } finally {
    initialLoading.value = false
  }
}

/** 会话状态分组切换：只局部刷新 sessions 段，不重载路由、不重置项目信息（§5.4） */
async function loadSessions() {
  if (!projectId.value || !overview.value) return
  sessionsLoading.value = true
  try {
    const data = await projectsApi.getProjectOverview(projectId.value, {
      session_limit: 100,
      session_status: sessionStatus.value,
    })
    overview.value.sessions = data.sessions
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载会话列表失败')
  } finally {
    sessionsLoading.value = false
  }
}

function handleSessionStatusChange(value: string | number) {
  sessionStatus.value = value as ProjectSessionStatus
  void loadSessions()
}

onMounted(loadOverview)
</script>

<template>
  <div class="project-detail-view">
    <PageHeader
      :title="overview?.project.name || '项目详情'"
      subtitle="项目元信息、会话管理与历史分析运行"
      back-to="/projects"
      back-label="返回项目列表"
    >
      <template #leading>
        <div class="project-header-mark"><NIcon :size="19"><FolderOpenOutline /></NIcon></div>
      </template>
    </PageHeader>

    <template v-if="initialLoading">
      <NSkeleton height="200px" :sharp="false" class="skeleton-card" />
      <NSkeleton height="320px" :sharp="false" class="skeleton-card" />
      <NSkeleton height="280px" :sharp="false" class="skeleton-card" />
    </template>

    <template v-else-if="overview">
      <section class="detail-summary" aria-label="项目摘要">
        <div class="detail-summary-copy">
          <span class="summary-eyebrow">PROJECT SPACE</span>
          <div class="summary-identity">
            <span class="summary-slug">{{ overview.project.slug }}</span>
            <NTag size="small" :bordered="false" type="info">当前项目</NTag>
          </div>
          <p>{{ overview.project.description || '为这个项目补充一句描述，团队成员会更快了解当前分析目标。' }}</p>
        </div>
        <div class="detail-summary-stats">
          <div class="summary-stat">
            <NIcon :size="17"><ChatbubblesOutline /></NIcon>
            <span><strong>{{ overview.sessions.total }}</strong><small>个会话</small></span>
          </div>
          <div class="summary-stat">
            <NIcon :size="17"><GitBranchOutline /></NIcon>
            <span><strong>{{ overview.runs.length }}</strong><small>次运行</small></span>
          </div>
          <div class="summary-stat">
            <NIcon :size="17"><TimeOutline /></NIcon>
            <span><strong>{{ formatDate(overview.project.updated_at).split(' ')[0] }}</strong><small>最近更新</small></span>
          </div>
        </div>
      </section>
      <NCard title="项目信息" :bordered="false" class="detail-card">
        <NDescriptions label-placement="left" bordered :column="2">
          <NDescriptionsItem label="项目名称">{{ overview.project.name }}</NDescriptionsItem>
          <NDescriptionsItem label="客户">
            <span v-if="overview.project.customer">{{ overview.project.customer }}</span>
            <span v-else class="cell-muted">—</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="描述">
            <span v-if="overview.project.description">{{ overview.project.description }}</span>
            <span v-else class="cell-muted">—</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="目录标识">{{ overview.project.slug }}</NDescriptionsItem>
          <NDescriptionsItem label="创建时间">{{ formatDate(overview.project.created_at) }}</NDescriptionsItem>
          <NDescriptionsItem label="更新时间">{{ formatDate(overview.project.updated_at) }}</NDescriptionsItem>
        </NDescriptions>
        <div class="project-default-row">
          <div class="project-default-label">
            <span class="project-default-title">新会话默认开启科研模式</span>
            <span class="project-default-desc">项目内新建会话自动套用科研模式设置（工作台会话可在会话设置中再调整）</span>
          </div>
          <n-switch
            :value="projectResearchDefault"
            :loading="togglingProjectResearch"
            data-test="project-research-default"
            @update:value="handleProjectResearchToggle"
          />
        </div>
      </NCard>

      <NCard :bordered="false" class="detail-card">
        <template #header>
          会话管理
          <span class="card-header-count">{{ overview.sessions.total }}</span>
        </template>
        <NTabs
          :value="sessionStatus"
          type="line"
          class="session-status-tabs"
          @update:value="handleSessionStatusChange"
        >
          <NTabPane name="active" tab="活跃" />
          <NTabPane name="archived" tab="已归档" />
          <NTabPane name="deleted" tab="回收站" />
        </NTabs>
        <p v-if="sessionStatus === 'deleted'" class="bin-note">
          删除的会话保留在回收站中，可通过「恢复」找回至活跃列表。
        </p>
        <NSpin :show="sessionsLoading">
          <NEmpty
            v-if="!overview.sessions.items.length"
            :description="sessionEmptyText[sessionStatus]"
            class="table-empty"
          />
          <NDataTable
            v-else
            :columns="sessionColumns"
            :data="overview.sessions.items"
            :row-key="(row: ProjectSessionItem) => row.id"
            :pagination="{ pageSize: 10 }"
            :bordered="false"
            :scroll-x="sessionScrollX"
          />
        </NSpin>
      </NCard>

      <NCard :bordered="false" class="detail-card">
        <template #header>
          历史分析运行
          <span class="card-header-count">{{ overview.runs.length }}</span>
        </template>
        <NEmpty
          v-if="!overview.runs.length"
          description="当前项目还没有历史分析运行记录"
          class="table-empty"
        />
        <NDataTable
          v-else
          :columns="runColumns"
          :data="overview.runs"
          :row-key="(row: ProjectRunItem) => row.name"
          :pagination="{ pageSize: 10 }"
          :bordered="false"
          :scroll-x="runScrollX"
        />
      </NCard>
    </template>

    <n-modal
      :show="renameTarget !== null"
      preset="card"
      title="重命名会话"
      style="width: 420px"
      @update:show="(v: boolean) => { if (!v) renameTarget = null }"
    >
      <n-input
        v-model:value="renameTitle"
        placeholder="请输入会话标题"
        maxlength="200"
        @keyup.enter="saveRename"
      />
      <template #footer>
        <n-space justify="end">
          <n-button @click="renameTarget = null">取消</n-button>
          <n-button
            type="primary"
            :loading="renameSaving"
            :disabled="!renameTitle.trim()"
            @click="saveRename"
          >
            保存
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
/* 与项目列表同一条内容边界：min(100%, 1440px) 居中 + --page-padding（§3.4/§4.3），替换旧的 max-width: 1200px 居中壳 */
.project-detail-view {
  width: min(100%, 1440px);
  margin-inline: auto;
  padding: var(--page-padding);
}

.project-header-mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  color: var(--arco-primary);
  border: 1px solid color-mix(in srgb, var(--arco-primary) 20%, var(--neutral-border));
  border-radius: 11px;
  background: var(--brand-primary-light);
}

.detail-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: var(--space-2xl);
  padding: 20px 24px;
  border: 1px solid color-mix(in srgb, var(--arco-primary) 20%, var(--neutral-border));
  border-radius: var(--radius-card);
  background: linear-gradient(115deg, var(--brand-primary-light), var(--neutral-card) 56%);
}
.summary-eyebrow { color: var(--arco-primary); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
.summary-identity { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.summary-slug { color: var(--neutral-text-1); font-size: 18px; line-height: 26px; font-weight: 600; }
.detail-summary-copy p { max-width: 620px; margin: 5px 0 0; color: var(--neutral-text-2); font-size: 13px; line-height: 20px; }
.detail-summary-stats { display: flex; flex: 0 0 auto; align-items: stretch; }
.summary-stat { display: flex; align-items: center; gap: 9px; min-width: 104px; padding: 0 18px; color: var(--arco-primary); border-left: 1px solid var(--neutral-border); }
.summary-stat span { display: flex; flex-direction: column; }
.summary-stat strong { color: var(--neutral-text-1); font-size: 17px; line-height: 22px; font-weight: 650; }
.summary-stat small { color: var(--neutral-text-3); font-size: 11px; line-height: 16px; }

/* 卡片垂直节奏 24px（§33.2⑤），卡片标题 16px/24px/500（§5.2） */
.detail-card {
  margin-bottom: var(--space-2xl);
}

.detail-card :deep(.n-card-header__main) {
  font-size: var(--font-card-title-size);
  line-height: var(--font-card-title-height);
  font-weight: var(--font-card-title-weight);
}

.detail-card :deep(.n-descriptions-table) { border-radius: 10px; overflow: hidden; }
.detail-card :deep(.n-descriptions-table-header) { color: var(--neutral-text-2); font-weight: 500; }

/* 项目级科研模式默认值开关（WP3 任务 3 可选项） */
.project-default-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--n-border-color, #e5e7eb);
}
.project-default-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.project-default-title {
  font-size: 14px;
  font-weight: 500;
}
.project-default-desc {
  font-size: 12px;
  color: var(--n-text-color-3, #999);
}

.card-header-count {
  margin-left: 4px;
  color: var(--neutral-text-3);
  font-size: var(--font-small-size);
  font-weight: 400;
}

/* 状态分组标签页与下方表格之间保留统一间距（沿用 .admin-config-tabs 的 --space-xl 约定） */
.session-status-tabs :deep(.n-tabs-nav) {
  margin-bottom: var(--space-lg);
}

.bin-note {
  margin: 0 0 var(--space-md);
  color: var(--neutral-text-3);
  font-size: var(--font-small-size);
  line-height: var(--font-small-height);
}

.table-empty {
  padding: var(--space-4xl) 0;
}

.cell-muted {
  color: var(--neutral-text-3);
}

.skeleton-card {
  display: block;
  margin-bottom: var(--space-2xl);
  border-radius: var(--radius-card);
}

@media (max-width: 768px) {
  .project-detail-view {
    padding: var(--space-lg);
  }
  .detail-summary { align-items: stretch; flex-direction: column; gap: 18px; }
  .detail-summary-stats { width: 100%; }
  .summary-stat { flex: 1; min-width: 0; padding: 0 12px; }
}

@media (max-width: 480px) {
  .detail-summary { padding: 18px; }
  .detail-summary-stats { display: grid; grid-template-columns: repeat(3, 1fr); }
  .summary-stat { gap: 5px; padding: 0 8px; }
  .summary-stat strong { font-size: 14px; }
}
</style>
