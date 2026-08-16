<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NPagination,
  NSelect,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import { AddOutline, CopyOutline, RefreshOutline, SearchOutline } from '@vicons/ionicons5'
import {
  agentTeamsApi,
  type AgentTeamsCase,
  type AgentTeamsCaseStatus,
} from '@/api/agentTeams'
import { formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'
import { displayName } from '@/utils/displayName'

const PAGE_SIZE = 20
const message = useMessage()
const router = useRouter()
const loading = ref(false)
const available = ref(false)
const cases = ref<AgentTeamsCase[]>([])
const total = ref(0)
const nextCursor = ref<string | null>(null)
const cursorHistory = ref<(string | undefined)[]>([undefined])
const page = ref(1)
const error = ref('')
const selectedStatus = ref<AgentTeamsCaseStatus | null>(null)
const projectId = ref('')
const createVisible = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref({
  case_kind: 'flow',
  project_id: '',
  intent: '',
  flow_id: 'scrna_seq',
  sample_sheet: '[\n  {\n    "sample_id": "sample-001",\n    "group": "control"\n  }\n]',
  comparisons: '',
  context_refs: '[\n  {\n    "kind": "file",\n    "id": "file-001"\n  }\n]',
})

const caseKindOptions = [
  { label: '平台流程分析', value: 'flow' },
  { label: '通用工作区任务', value: 'general' },
]
const isFlowCase = computed(() => createForm.value.case_kind === 'flow')

const STATUS_OPTIONS: AgentTeamsCaseStatus[] = [
  'queued', 'received', 'planning_running', 'preflight_running', 'preflight_blocked', 'waiting_for_correction',
  'approval_pending', 'approved', 'executing', 'execution_failed', 'quality_running', 'quality_blocked',
  'remediation_pending', 'delivery_ready', 'closed', 'cancelled',
]
const statusOptions = STATUS_OPTIONS.map((value) => ({ value, label: formatAgentTeamsStatus(value) }))

const tagType = (status: AgentTeamsCaseStatus) => {
  if (['closed', 'delivery_ready'].includes(status)) return 'success'
  if (['preflight_blocked', 'quality_blocked', 'execution_failed'].includes(status)) return 'error'
  if (['approval_pending', 'waiting_for_correction', 'remediation_pending'].includes(status)) return 'warning'
  return 'info'
}

const stats = computed(() => {
  const list = cases.value
  return {
    total: total.value,
    executing: list.filter((c) => ['executing', 'preflight_running', 'quality_running'].includes(c.status)).length,
    failed: list.filter((c) => ['execution_failed', 'preflight_blocked', 'quality_blocked'].includes(c.status)).length,
  }
})

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function copyIdentifier(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    message.success(`${label}已复制`)
  } catch {
    message.error(`${label}复制失败，请手动复制`)
  }
}

function renderIdentifier(value: string, label: string, className: string) {
  return h('div', { class: className }, [
    h('span', { class: `${className}__value`, title: value }, value),
    h(
      'button',
      {
        class: 'case-id-copy',
        type: 'button',
        title: `复制${label}`,
        'aria-label': `复制${label}`,
        onClick: () => void copyIdentifier(value, label),
      },
      [h(NIcon, { size: 14 }, { default: () => h(CopyOutline) })],
    ),
  ])
}

// §33.2 ③：全部列固定 width，无弹性列；scroll-x = 列宽之和（1110）
const columns = [
  {
    title: 'Case',
    key: 'case_id',
    width: 400,
    render: (row: AgentTeamsCase) => h('div', { class: 'case-identity' }, [
      h(
        RouterLink,
        { to: `/agent-teams/cases/${row.case_id}`, class: 'case-link', title: row.intent },
        { default: () => row.intent },
      ),
      renderIdentifier(row.case_id, 'Case ID', 'case-identity__id'),
    ]),
  },
  {
    title: '用户',
    key: 'requester',
    width: 220,
    render: (row: AgentTeamsCase) => h('div', { class: 'case-user' }, [
      h('span', { class: 'case-user__name' }, displayName({
        nickname: row.requester_nickname,
        username: row.requester_username,
      }) || '未知用户'),
      renderIdentifier(row.requester_ref, '用户 ID', 'case-user__id'),
    ]),
  },
  {
    title: '当前阶段',
    key: 'status',
    width: 140,
    align: 'center' as const,
    render: (row: AgentTeamsCase) => h(
      NTag,
      { type: tagType(row.status), bordered: false, round: true, size: 'small' },
      { default: () => formatAgentTeamsStatus(row.status) },
    ),
  },
  {
    title: '关联执行',
    key: 'tasks',
    width: 130,
    align: 'center' as const,
    render: (row: AgentTeamsCase) => h(
      'span',
      { class: 'case-tasks' },
      row.omic_task_ids.length ? `${row.omic_task_ids.length} 个任务` : '尚未提交',
    ),
  },
  {
    title: '最近更新',
    key: 'updated_at',
    width: 220,
    align: 'center' as const,
    render: (row: AgentTeamsCase) => h('span', { class: 'case-time' }, formatTime(row.updated_at)),
  },
]

async function loadCases(targetPage = 1) {
  loading.value = true
  error.value = ''
  try {
    const state = await agentTeamsApi.status()
    available.value = state.available
    if (!state.available) {
      cases.value = []
      total.value = 0
      return
    }
    for (let pageToResolve = 1; pageToResolve < targetPage; pageToResolve += 1) {
      if (cursorHistory.value[pageToResolve] !== undefined) continue
      const cursorForPage = cursorHistory.value[pageToResolve - 1]
      if (cursorForPage === undefined) return
      const intermediate = await agentTeamsApi.listCases({
        status: selectedStatus.value ?? undefined,
        project_id: projectId.value.trim() || undefined,
        cursor: cursorForPage,
        limit: PAGE_SIZE,
      })
      if (!intermediate.next_cursor) return
      cursorHistory.value[pageToResolve] = intermediate.next_cursor
    }
    const cursor = cursorHistory.value[targetPage - 1]
    if (targetPage > 1 && cursor === undefined) return
    const result = await agentTeamsApi.listCases({
      status: selectedStatus.value ?? undefined,
      project_id: projectId.value.trim() || undefined,
      cursor,
      limit: PAGE_SIZE,
    })
    cases.value = result.items
    total.value = result.total
    nextCursor.value = result.next_cursor ?? null
    page.value = targetPage
    cursorHistory.value = cursorHistory.value.slice(0, targetPage)
    if (nextCursor.value) cursorHistory.value[targetPage] = nextCursor.value
  } catch (cause: any) {
    error.value = cause?.response?.data?.detail || '无法获取协作案例，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function openCreateCase() {
  createError.value = ''
  createVisible.value = true
}

function parseJsonArray(value: string, label: string, required: boolean): Array<Record<string, unknown>> | undefined {
  const normalized = value.trim()
  if (!normalized && !required) return undefined
  if (!normalized) throw new Error(`请填写${label}。`)
  const parsed: unknown = JSON.parse(normalized)
  if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== 'object' || Array.isArray(item))) {
    throw new Error(`${label}必须是对象数组 JSON。`)
  }
  return parsed as Array<Record<string, unknown>>
}

async function createCase() {
  createError.value = ''
  const projectIdValue = createForm.value.project_id.trim()
  const intent = createForm.value.intent.trim()
  const flowId = createForm.value.flow_id.trim()
  if (!intent) {
    createError.value = '请填写分析目标。'
    return
  }
  if (isFlowCase.value && (!projectIdValue || !flowId)) {
    createError.value = '平台流程分析必须填写项目引用和流程 ID。'
    return
  }
  let sampleSheet: Array<Record<string, unknown>> | undefined
  let comparisons: Array<Record<string, unknown>> | undefined
  let contextRefs: Array<{ kind: 'workspace' | 'file'; id: string; location?: string }> | undefined
  try {
    if (isFlowCase.value) {
      sampleSheet = parseJsonArray(createForm.value.sample_sheet, '样本表', true)
      comparisons = parseJsonArray(createForm.value.comparisons, '分组对比', false)
    } else {
      const parsed = parseJsonArray(createForm.value.context_refs, '上下文引用', true)!
      if (parsed.some((item) => (item.kind !== 'file' && item.kind !== 'workspace') || typeof item.id !== 'string' || !item.id.trim())) {
        throw new Error('上下文引用只允许 kind=file 或 workspace，且必须包含 id。')
      }
      contextRefs = parsed as Array<{ kind: 'workspace' | 'file'; id: string; location?: string }>
    }
  } catch (cause: any) {
    createError.value = cause instanceof SyntaxError ? '样本表或分组对比不是有效 JSON。' : cause.message
    return
  }

  creating.value = true
  try {
    const created = await agentTeamsApi.createCase({
      project_id: isFlowCase.value ? projectIdValue : undefined,
      context_refs: contextRefs,
      intent,
      flow_id: isFlowCase.value ? flowId : undefined,
      sample_sheet: sampleSheet,
      comparisons,
    })
    createVisible.value = false
    message.success(isFlowCase.value ? '协作 Case 已创建，正在进入预检。' : '通用协作 Case 已创建，正在生成执行计划。')
    await router.push(`/agent-teams/cases/${created.case_id}`)
  } catch (cause: any) {
    createError.value = cause?.response?.data?.detail || '创建协作 Case 失败。'
  } finally {
    creating.value = false
  }
}

function resetAndLoad() {
  cursorHistory.value = [undefined]
  void loadCases(1)
}

onMounted(() => { void loadCases() })
</script>

<template>
  <div class="agent-teams-panel">
    <NAlert v-if="!loading && !available && !error" type="info" title="AgentTeams 尚未接通" :show-icon="true" class="panel-alert">
      配置 AgentTeams Bridge 后，这里会显示当前用户的真实协作 Case；可在 AI 助手页面对话中发起协作 Case。
    </NAlert>
    <template v-else-if="error">
      <NAlert type="error" title="无法加载协作 Case" :show-icon="true" class="panel-alert">{{ error }}</NAlert>
      <NButton size="small" @click="resetAndLoad">重试</NButton>
    </template>
    <template v-else>
      <!-- 统计摘要条：与「分析任务」tab 的 TaskTable 统计胶囊同款 -->
      <div class="case-stats" aria-label="协作 Case 统计">
        <div class="case-stat-chip case-stat-chip--total">
          <span class="case-stat-chip__dot"></span>
          共 <strong>{{ stats.total }}</strong> 个 Case
        </div>
        <div class="case-stat-chip case-stat-chip--executing">
          <span class="case-stat-chip__dot"></span>
          <strong>{{ stats.executing }}</strong> 进行中
        </div>
        <div class="case-stat-chip case-stat-chip--failed">
          <span class="case-stat-chip__dot"></span>
          <strong>{{ stats.failed }}</strong> 失败/阻断
        </div>
      </div>

      <div class="case-filters" aria-label="协作 Case 筛选">
        <NButton type="primary" @click="openCreateCase">
          <template #icon><NIcon><AddOutline /></NIcon></template>新建 Case
        </NButton>
        <NSelect
          v-model:value="selectedStatus"
          clearable
          :options="statusOptions"
          placeholder="全部阶段"
          class="case-filters__status"
          @update:value="resetAndLoad"
        />
        <NInput
          v-model:value="projectId"
          clearable
          placeholder="按项目引用筛选"
          class="case-filters__project"
          @keyup.enter="resetAndLoad"
          @clear="resetAndLoad"
        >
          <template #prefix>
            <NIcon :size="14"><SearchOutline /></NIcon>
          </template>
        </NInput>
        <NButton secondary @click="resetAndLoad">应用筛选</NButton>
        <NButton secondary :loading="loading" @click="resetAndLoad">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>刷新
        </NButton>
      </div>

      <div class="case-table-card omichub-card">
        <NSpin :show="loading">
          <NDataTable
            v-if="cases.length"
            :columns="columns"
            :data="cases"
            :row-key="(row: AgentTeamsCase) => row.case_id"
            :bordered="false"
            :scroll-x="1110"
          />
          <div v-else class="case-empty">
            <NEmpty description="当前筛选条件下没有可见的协作 Case">
              <template #extra>
                <span class="case-empty__hint">在 AI 助手对话中描述分析目标，即可发起协作 Case</span>
              </template>
            </NEmpty>
          </div>
        </NSpin>
        <div v-if="total > PAGE_SIZE" class="case-pagination">
          <NPagination
            :page="page"
            :page-size="PAGE_SIZE"
            :item-count="total"
            :page-slot="5"
            :disabled="loading"
            @update:page="loadCases"
          />
        </div>
      </div>
    </template>
    <NModal v-model:show="createVisible" preset="card" title="新建协作 Case" :style="{ width: 'min(94vw, 720px)' }" :mask-closable="!creating">
      <NAlert type="info" :show-icon="true" class="create-case-note">
        平台流程会对项目、样本表和分组对比执行预检；通用工作区任务以文件或工作区引用启动。所有执行仍需在审批阶段人工确认。
      </NAlert>
      <NAlert v-if="createError" type="error" :show-icon="true" class="create-case-note">{{ createError }}</NAlert>
      <NForm label-placement="top" @submit.prevent="createCase">
        <NFormItem label="Case 类型"><NSelect v-model:value="createForm.case_kind" :options="caseKindOptions" /></NFormItem>
        <NFormItem label="分析目标" required><NInput v-model:value="createForm.intent" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="描述本次分析问题与预期产出" /></NFormItem>
        <template v-if="isFlowCase">
          <NFormItem label="项目引用" required><NInput v-model:value="createForm.project_id" placeholder="例如 project-001" /></NFormItem>
          <NFormItem label="流程 ID" required><NInput v-model:value="createForm.flow_id" placeholder="例如 scrna_seq" /></NFormItem>
          <NFormItem label="样本表 JSON" required><NInput v-model:value="createForm.sample_sheet" type="textarea" :autosize="{ minRows: 7, maxRows: 12 }" /></NFormItem>
          <NFormItem label="分组对比 JSON（可选）"><NInput v-model:value="createForm.comparisons" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" placeholder='例如 [{"name":"treated-vs-control","numerator":"treated","denominator":"control"}]' /></NFormItem>
        </template>
        <NFormItem v-else label="文件或工作区引用 JSON" required><NInput v-model:value="createForm.context_refs" type="textarea" :autosize="{ minRows: 5, maxRows: 10 }" /></NFormItem>
        <div class="create-case-actions"><NButton :disabled="creating" @click="createVisible = false">取消</NButton><NButton type="primary" attr-type="submit" :loading="creating">{{ isFlowCase ? '创建并预检' : '创建并规划' }}</NButton></div>
      </NForm>
    </NModal>
  </div>
</template>

<style scoped>
.agent-teams-panel {
  min-width: 0;
}

.panel-alert {
  margin-bottom: 24px;
}

/* 统计胶囊：对齐 TaskTable 的 task-stat-chip 视觉 */
.case-stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0 0 16px;
}

.case-stat-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 30px;
  padding: 0 11px;
  border-radius: 999px;
  background: #f3f4f6;
  color: var(--neutral-text-2);
  font-size: 13px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.case-stat-chip strong {
  color: var(--neutral-text-1);
  font-weight: 650;
}

.case-stat-chip__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: #9ca3af;
}

.case-stat-chip--executing .case-stat-chip__dot { background: var(--arco-primary); }
.case-stat-chip--failed .case-stat-chip__dot { background: #ef4444; }

/* 筛选行：与「分析任务」工具栏一致，右对齐、按钮自适应不拉伸 */
.case-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.case-filters__status { width: 160px; }
.case-filters__project { width: 260px; }
.create-case-note { margin-bottom: 16px; }
.create-case-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }

/* 表格卡片：复用 omichub-card 表面（global.css「卡片内数据表格」规则自动接管表头/分隔线/悬停） */
.case-table-card {
  overflow: hidden;
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-card);
  background: var(--neutral-card);
  box-shadow: var(--shadow-card);
}

/* Case 列：标题为主文本，稳定 ID 为可复制的等宽辅助文本。 */
.case-identity,
.case-user {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.case-link {
  text-decoration: none;
  overflow: hidden;
  color: var(--neutral-text-1);
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--motion-quick, 160ms) ease-out;
}

.case-link:hover,
.case-link:focus-visible {
  color: var(--arco-primary);
  outline: none;
}

.case-identity__id,
.case-user__id {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
  color: var(--neutral-text-3);
}

.case-identity__id__value,
.case-user__id__value {
  overflow: hidden;
  min-width: 0;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-tasks,
.case-time {
  color: var(--neutral-text-2);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.case-user__name {
  overflow: hidden;
  color: var(--neutral-text-1);
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-id-copy {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--neutral-text-3);
  cursor: pointer;
  opacity: 0;
  transition: color var(--motion-quick, 160ms) ease-out, background var(--motion-quick, 160ms) ease-out, opacity var(--motion-quick, 160ms) ease-out;
}

.case-identity:hover .case-id-copy,
.case-user:hover .case-id-copy,
.case-id-copy:focus-visible {
  opacity: 1;
}

.case-id-copy:hover,
.case-id-copy:focus-visible {
  background: var(--neutral-hover);
  color: var(--arco-primary);
  outline: none;
}

@media (hover: none) {
  .case-id-copy { opacity: 1; }
}

.case-empty {
  padding: 48px 24px;
}

.case-empty__hint {
  color: var(--neutral-text-3);
  font-size: 12px;
}

.case-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--neutral-border);
}

:global(:root[data-theme='dark']) .case-stat-chip { background: var(--neutral-bg); }

@media (max-width: 768px) {
  .case-filters {
    justify-content: flex-start;
  }
  .case-filters :deep(.n-input),
  .case-filters :deep(.n-select) {
    width: 100% !important;
  }
  .case-filters__project {
    flex: 1 1 220px;
  }
  .case-pagination {
    justify-content: center;
  }
}
</style>
