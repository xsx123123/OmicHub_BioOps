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
  NInput,
  NInputNumber,
  NModal,
  NRadioButton,
  NRadioGroup,
  NProgress,
  NSelect,
  NSpin,
  NTag,
  NSwitch,
  useMessage,
} from 'naive-ui'
import {
  CheckmarkOutline,
  CopyOutline,
  GitNetworkOutline,
  RefreshOutline,
  SaveOutline,
} from '@vicons/ionicons5'
import AdminTOTPConfirmModal from '@/components/AdminTOTPConfirmModal.vue'
import {
  agentTeamsBridgeAdminApi,
  type AgentTeamsBridgeConfig,
  type AgentTeamsBridgeHealth,
  type AgentTeamsBridgeMetrics,
  type AgentTeamsBridgeResourceSnapshot,
  type AgentTeamsBridgeTokenBundle,
  type AgentTeamsWorkerToken,
  type AgentTeamsWorkerTokenIssueResult,
} from '@/api/admin/agentTeamsBridge'
import apiClient from '@/api/client'
import { resolveWorkerTokenStatus, WORKER_TOKEN_STATUS_MAP } from '@/utils/agentTeamsWorkerToken'

const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const confirmVisible = ref(false)
const tokenConfirmVisible = ref(false)
const tokenGenerating = ref(false)
const generatedTokens = ref<AgentTeamsBridgeTokenBundle | null>(null)
const resources = ref<AgentTeamsBridgeResourceSnapshot | null>(null)
const bridgeMetrics = ref<Partial<AgentTeamsBridgeMetrics>>({})
const resourceLoading = ref(false)
const reconcileCaseId = ref('')
const reconcileConfirmVisible = ref(false)
const reconciling = ref(false)
const config = ref<AgentTeamsBridgeConfig>({
  enabled: false,
  bridge_url: '',
  timeout_seconds: 10,
  manager_token: '',
  data_steward_token: '',
  approval_token: '',
  workflow_operator_token: '',
  source: 'database',
  configured: false,
  connected: false,
})
type CollaborationPreset = 'custom' | 'light' | 'parallel' | 'full'
const preset = ref<CollaborationPreset>('custom')
const presetSaving = ref(false)
const presetConfirmVisible = ref(false)
const health = ref<AgentTeamsBridgeHealth | null>(null)
const degradationCounts = ref<Record<string, number>>({ fanout: 0, consult: 0, case: 0, dag: 0 })
const consultationQuality = ref({
  total: 0,
  parse_success_rate: 0,
  evidence_hit_rate: 0,
  qc_consistency_rate: 0,
  average_tool_calls: 0,
})
const degradationLocale = ref<'zh-CN' | 'en'>('zh-CN')
const degradationTemplateZh = ref('')
const degradationTemplateEn = ref('')
const templateSaving = ref(false)
const presetDescription = computed(() => ({
  light: '轻量协作：专家转交与多专家会诊。',
  parallel: '并行增强：轻量协作 + 对话内 Fan-out。',
  full: '全流程闭环：并行增强 + AgentTeams Case 入口；仍需保存并接通 Bridge。',
  custom: '自定义：保留当前各项开关组合。',
})[preset.value])
const presetDiff = computed(() => ({
  light: ['统一意图路由：开启', '多专家会诊：开启', '并行 Fan-out：关闭', '协作 Case 入口：关闭'],
  parallel: ['统一意图路由：开启', '多专家会诊：开启', '并行 Fan-out：开启', '协作 Case 入口：关闭'],
  full: ['统一意图路由：开启', '多专家会诊：开启', '并行 Fan-out：开启', '协作 Case 入口：开启'],
  custom: ['不改动现有功能开关，仅将档位标记为“自定义”。'],
})[preset.value])
const inactiveWorkers = computed(() => health.value?.workers.filter((worker) => !worker.active) || [])
const validIdentityCount = computed(() => health.value?.identities.filter((item) => item.valid).length || 0)
const activeWorkerCount = computed(() => health.value?.workers.filter((item) => item.active).length || 0)
const onboardingSteps = computed(() => [
  { title: '填写 Bridge 地址', complete: Boolean(config.value.bridge_url.trim()) },
  { title: '配置四个 Worker 令牌', complete: config.value.configured },
  { title: '保存并启用配置', complete: config.value.enabled },
  { title: '验证 Bridge 连接', complete: config.value.connected },
  { title: '确认 Worker 心跳', complete: Boolean(health.value?.workers.length) && !inactiveWorkers.value.length },
])

async function load() {
  loading.value = true
  try {
    config.value = await agentTeamsBridgeAdminApi.get()
    const [platform, healthResponse, observability, resourceSnapshot, metricsSnapshot] = await Promise.all([
      apiClient.get<{
        collaboration_preset?: CollaborationPreset
        collaboration_degradation_locale?: 'zh-CN' | 'en'
        collaboration_degradation_template_zh?: string
        collaboration_degradation_template_en?: string
      }>('/platform/config'),
      agentTeamsBridgeAdminApi.health(),
      apiClient.get<{
        degradation_counts?: Record<string, number>
        consultation_quality?: typeof consultationQuality.value
      }>('/admin/platform-config/collaboration-observability'),
      agentTeamsBridgeAdminApi.resources(),
      agentTeamsBridgeAdminApi.metrics(),
    ])
    preset.value = platform.data.collaboration_preset || 'custom'
    degradationLocale.value = platform.data.collaboration_degradation_locale || 'zh-CN'
    degradationTemplateZh.value = platform.data.collaboration_degradation_template_zh || ''
    degradationTemplateEn.value = platform.data.collaboration_degradation_template_en || ''
    health.value = healthResponse
    resources.value = resourceSnapshot
    bridgeMetrics.value = metricsSnapshot
    void loadWorkerTokens()
    degradationCounts.value = { ...degradationCounts.value, ...(observability.data.degradation_counts || {}) }
    consultationQuality.value = {
      ...consultationQuality.value,
      ...(observability.data.consultation_quality || {}),
    }
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '无法读取 AgentTeams Bridge 配置。')
  } finally {
    loading.value = false
  }
}

async function loadResources() {
  resourceLoading.value = true
  try {
    resources.value = await agentTeamsBridgeAdminApi.resources()
    health.value = resources.value.health
    void loadWorkerTokens()
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '读取 AgentTeams 资源失败。')
  } finally {
    resourceLoading.value = false
  }
}

async function saveDegradationTemplates() {
  templateSaving.value = true
  try {
    await apiClient.patch('/admin/platform-config', {
      collaboration_degradation_locale: degradationLocale.value,
      collaboration_degradation_template_zh: degradationTemplateZh.value,
      collaboration_degradation_template_en: degradationTemplateEn.value,
    })
    message.success('协作降级文案已保存。')
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '保存协作降级文案失败。')
  } finally {
    templateSaving.value = false
  }
}

function requestApplyPreset() {
  presetConfirmVisible.value = true
}

async function applyPreset() {
  presetSaving.value = true
  try {
    await apiClient.patch('/admin/platform-config', { collaboration_preset: preset.value })
    presetConfirmVisible.value = false
    message.success(`已应用“${presetDescription.value.split('：')[0]}”档位。`)
    if (preset.value === 'full' && !config.value.connected) {
      message.warning('全流程闭环还需要保存并接通下方 Bridge 配置。')
    }
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '应用协作档位失败。')
  } finally {
    presetSaving.value = false
  }
}

function requestSave() {
  if (config.value.enabled && !config.value.bridge_url.trim()) {
    message.warning('启用前请填写 Bridge 地址。')
    return
  }
  confirmVisible.value = true
}

async function save(totpCode: string) {
  saving.value = true
  try {
    config.value = await agentTeamsBridgeAdminApi.update(config.value, totpCode)
    confirmVisible.value = false
    message.success(config.value.connected ? 'Bridge 已保存并接通。' : 'Bridge 配置已保存，当前尚未接通。')
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '保存 AgentTeams Bridge 配置失败。')
  } finally {
    saving.value = false
  }
}

async function generateTokens(totpCode: string) {
  tokenGenerating.value = true
  try {
    const tokens = await agentTeamsBridgeAdminApi.generateTokens(totpCode)
    generatedTokens.value = tokens
    config.value = { ...config.value, ...tokens }
    tokenConfirmVisible.value = false
    message.success('已生成新令牌并填入表单；请复制到 Worker 部署配置后保存。')
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '生成 Worker 令牌失败。')
  } finally {
    tokenGenerating.value = false
  }
}

async function copyGeneratedTokens() {
  if (!generatedTokens.value) return
  const content = [
    `bioops-manager:${generatedTokens.value.manager_token}`,
    `data-steward:${generatedTokens.value.data_steward_token}`,
    `approval-authority:${generatedTokens.value.approval_token}`,
    `workflow-operator:${generatedTokens.value.workflow_operator_token}`,
  ].join('\n')
  try {
    await navigator.clipboard.writeText(content)
    message.success('已复制 Worker 身份令牌清单。')
  } catch {
    message.error('复制失败，请手动复制。')
  }
}

function requestReconcile(caseId: string) {
  reconcileCaseId.value = caseId
  reconcileConfirmVisible.value = true
}

async function reconcileCase(totpCode: string) {
  if (!reconcileCaseId.value) return
  reconciling.value = true
  try {
    await agentTeamsBridgeAdminApi.reconcileCase(reconcileCaseId.value, totpCode)
    reconcileConfirmVisible.value = false
    message.success(`已重协调 Case ${reconcileCaseId.value}。`)
    await loadResources()
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '重协调协作 Case 失败。')
  } finally {
    reconciling.value = false
  }
}

const CASE_STATUS_MAP: Record<string, { label: string; type: 'default' | 'info' | 'success' | 'warning' | 'error' }> = {
  received: { label: '已接收', type: 'default' },
  waiting_for_correction: { label: '待修正', type: 'warning' },
  planning_failed: { label: '规划失败', type: 'error' },
  preflight_blocked: { label: '预检拦截', type: 'error' },
  approval_pending: { label: '待审批', type: 'warning' },
  executing: { label: '执行中', type: 'info' },
  execution_failed: { label: '执行失败', type: 'error' },
  completed: { label: '已完成', type: 'success' },
  blocked: { label: '已阻塞', type: 'error' },
}

function caseStatusTag(status: string) {
  return CASE_STATUS_MAP[status] || { label: status || '未知', type: 'default' as const }
}

const resourceColumns = [
  { title: 'Case', key: 'case_id', width: 240, ellipsis: { tooltip: true } },
  { title: 'Team', key: 'team_id', width: 150, ellipsis: { tooltip: true } },
  {
    title: '状态',
    key: 'status',
    width: 110,
    align: 'center' as const,
    render: (row: { status: string }) => {
      const tag = caseStatusTag(row.status)
      return h(NTag, { size: 'small', type: tag.type, bordered: false }, { default: () => tag.label })
    },
  },
  {
    title: '项目',
    key: 'project',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row: { project_ref: { id: string } }) => row.project_ref?.id || '-',
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    align: 'center' as const,
    render: (row: { case_id: string }) => h(NButton, { size: 'tiny', secondary: true, onClick: () => requestReconcile(row.case_id) }, { default: () => '重协调' }),
  },
]

function resourceCaseRowKey(row: { case_id: string }) {
  return row.case_id
}

// --- Worker token 管理（M6：可吊销 per-worker 凭证） ---
const workerTokens = ref<AgentTeamsWorkerToken[]>([])
const workerTokenLoading = ref(false)
const issueDialogVisible = ref(false)
const issueForm = ref<{ identity: string | null; ttlDays: number; note: string }>({
  identity: null,
  ttlDays: 0,
  note: '',
})
const issueTotpVisible = ref(false)
const issuing = ref(false)
const issuedToken = ref<AgentTeamsWorkerTokenIssueResult | null>(null)
const revokeTarget = ref<AgentTeamsWorkerToken | null>(null)
const revokeTotpVisible = ref(false)
const revoking = ref(false)
const workerIdentityOptions = computed(() =>
  (health.value?.identities || []).map((item) => ({ label: item.identity, value: item.identity })),
)

async function loadWorkerTokens() {
  workerTokenLoading.value = true
  try {
    workerTokens.value = await agentTeamsBridgeAdminApi.listWorkerTokens()
  } catch {
    workerTokens.value = []
  } finally {
    workerTokenLoading.value = false
  }
}

function requestIssueWorkerToken() {
  issueForm.value = { identity: null, ttlDays: 0, note: '' }
  issueDialogVisible.value = true
}

function confirmIssueForm() {
  if (!issueForm.value.identity) {
    message.warning('请选择要签发的 Worker 身份。')
    return
  }
  issueDialogVisible.value = false
  issueTotpVisible.value = true
}

async function issueWorkerToken(totpCode: string) {
  if (!issueForm.value.identity) return
  issuing.value = true
  try {
    issuedToken.value = await agentTeamsBridgeAdminApi.issueWorkerToken(
      {
        identity: issueForm.value.identity,
        ttl_seconds: issueForm.value.ttlDays > 0 ? issueForm.value.ttlDays * 86400 : null,
        note: issueForm.value.note.trim(),
      },
      totpCode,
    )
    issueTotpVisible.value = false
    message.success('令牌已签发，仅本次展示，请立即复制。')
    await loadWorkerTokens()
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '签发 Worker 令牌失败。')
  } finally {
    issuing.value = false
  }
}

async function copyIssuedToken() {
  if (!issuedToken.value) return
  try {
    await navigator.clipboard.writeText(issuedToken.value.token)
    message.success('已复制令牌。')
  } catch {
    message.error('复制失败，请手动复制。')
  }
}

function requestRevokeWorkerToken(record: AgentTeamsWorkerToken) {
  revokeTarget.value = record
  revokeTotpVisible.value = true
}

async function revokeWorkerToken(totpCode: string) {
  if (!revokeTarget.value) return
  revoking.value = true
  try {
    await agentTeamsBridgeAdminApi.revokeWorkerToken(revokeTarget.value.token_id, totpCode)
    revokeTotpVisible.value = false
    message.success(`已吊销 ${revokeTarget.value.identity} 的令牌。`)
    await loadWorkerTokens()
  } catch (cause: any) {
    message.error(cause?.response?.data?.detail || '吊销 Worker 令牌失败。')
  } finally {
    revoking.value = false
  }
}

function workerTokenStatusTag(record: AgentTeamsWorkerToken) {
  return WORKER_TOKEN_STATUS_MAP[resolveWorkerTokenStatus(record)]
}

const workerTokenColumns = [
  { title: '身份', key: 'identity', width: 160, ellipsis: { tooltip: true } },
  { title: '备注', key: 'note', ellipsis: { tooltip: true }, render: (row: AgentTeamsWorkerToken) => row.note || '-' },
  {
    title: '状态',
    key: 'status',
    width: 90,
    align: 'center' as const,
    render: (row: AgentTeamsWorkerToken) => {
      const tag = workerTokenStatusTag(row)
      return h(NTag, { size: 'small', type: tag.type, bordered: false }, { default: () => tag.label })
    },
  },
  {
    title: '过期时间',
    key: 'expires_at',
    width: 170,
    render: (row: AgentTeamsWorkerToken) =>
      row.expires_at ? new Date(row.expires_at).toLocaleString() : '永不过期',
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    align: 'center' as const,
    render: (row: AgentTeamsWorkerToken) =>
      resolveWorkerTokenStatus(row) === 'active'
        ? h(NButton, { size: 'tiny', secondary: true, type: 'error', onClick: () => requestRevokeWorkerToken(row) }, { default: () => '吊销' })
        : null,
  },
]

function workerTokenRowKey(row: AgentTeamsWorkerToken) {
  return row.token_id
}

onMounted(() => { void load() })
</script>

<template>
  <div class="agentteams-bridge-tab">
    <div class="tab-header">
      <span class="tab-hint">配置协作中心的多 Agent 编排接入地址与加密身份令牌，保存需 TOTP 二次验证。</span>
    </div>

    <NSpin :show="loading">
      <div class="bridge-body">
        <section class="bridge-overview" aria-label="AgentTeams Bridge 概览">
          <div class="bridge-avatar" aria-hidden="true">
            <NIcon :component="GitNetworkOutline" />
          </div>
          <div class="bridge-overview-text">
            <div class="bridge-overview-title">
              <h3>AgentTeams Bridge</h3>
              <NTag :type="config.connected ? 'success' : config.enabled ? 'warning' : 'default'" size="small" :bordered="false">
                {{ config.connected ? '已接通' : config.enabled ? '等待接通' : '未启用' }}
              </NTag>
            </div>
            <p>为协作 Case 提供隔离的多 Agent 编排、审批与审计通道。</p>
          </div>
          <NButton secondary :loading="loading" @click="load">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            一键检测
          </NButton>
        </section>

        <NAlert type="info" :show-icon="true" class="bridge-note">
          此配置仅限管理员。四个身份令牌以加密形式保存，读取时始终脱敏；保存、启用和切换地址均需 TOTP 二次验证。
        </NAlert>
        <NAlert v-if="config.source === 'environment'" type="warning" :show-icon="true" class="bridge-note">
          当前配置来自服务端环境变量。保存后会迁移为数据库加密配置，并覆盖该运行实例的环境变量回退值。
        </NAlert>

        <div class="bridge-grid">
          <main class="bridge-main">
            <NCard class="bridge-card" :segmented="{ content: true, footer: true }">
              <template #header><span class="card-title">接入配置</span></template>
              <NForm label-placement="top" class="bridge-form">
                <div class="bridge-status-row">
                  <div class="bridge-status-text">
                    <span class="bridge-status-label">启用协作中心</span>
                    <p>关闭后所有用户都会看到“尚未接通”，并且无法创建或提交 Case。</p>
                  </div>
                  <NSwitch v-model:value="config.enabled" />
                </div>
                <div class="bridge-field-grid">
                  <NFormItem label="Bridge 地址" class="field-span-main">
                    <NInput v-model:value="config.bridge_url" placeholder="例如 http://agentteams-bridge:8080" />
                  </NFormItem>
                  <NFormItem label="请求超时（秒）" class="field-span-side timeout-item">
                    <NInputNumber v-model:value="config.timeout_seconds" :min="1" :max="120" :precision="0" />
                  </NFormItem>
                </div>
                <div class="bridge-secret-grid">
                  <NFormItem label="Manager 令牌"><NInput v-model:value="config.manager_token" type="password" show-password-on="click" placeholder="未填写则保留已配置令牌" /></NFormItem>
                  <NFormItem label="Data Steward 令牌"><NInput v-model:value="config.data_steward_token" type="password" show-password-on="click" placeholder="未填写则保留已配置令牌" /></NFormItem>
                  <NFormItem label="审批身份令牌"><NInput v-model:value="config.approval_token" type="password" show-password-on="click" placeholder="未填写则保留已配置令牌" /></NFormItem>
                  <NFormItem label="Workflow Operator 令牌"><NInput v-model:value="config.workflow_operator_token" type="password" show-password-on="click" placeholder="未填写则保留已配置令牌" /></NFormItem>
                </div>
              </NForm>
              <template #footer>
                <div class="bridge-actions">
                  <NButton secondary :loading="loading" @click="load">
                    <template #icon><NIcon><RefreshOutline /></NIcon></template>
                    重新检查
                  </NButton>
                  <NButton type="primary" @click="requestSave">
                    <template #icon><NIcon><SaveOutline /></NIcon></template>
                    保存并检查连接
                  </NButton>
                </div>
              </template>
            </NCard>

            <NCard class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">AgentTeams 资源管理</span></template>
              <template #header-extra>
                <NButton size="small" secondary :loading="resourceLoading" @click="loadResources">
                  <template #icon><NIcon><RefreshOutline /></NIcon></template>
                  刷新资源
                </NButton>
              </template>
              <NAlert v-if="!resources?.health.connection.connected" type="warning" :show-icon="true" class="bridge-note bridge-note--flush">
                Bridge 未接通时无法读取真实资源。请先完成接入向导并检查 Worker 部署。
              </NAlert>
              <template v-else>
                <div class="resource-summary" aria-label="AgentTeams 资源概览">
                  <div class="rs-item">
                    <span class="rs-value" :class="{ 'rs-value--danger': activeWorkerCount < resources.health.workers.length }">
                      {{ activeWorkerCount }}/{{ resources.health.workers.length }}
                    </span>
                    <span class="rs-label">活跃 Worker</span>
                  </div>
                  <div class="rs-item">
                    <span class="rs-value">{{ resources.teams.length }}</span>
                    <span class="rs-label">Team</span>
                  </div>
                  <div class="rs-item">
                    <span class="rs-value">{{ resources.total_cases }}</span>
                    <span class="rs-label">Case</span>
                  </div>
                  <div v-if="resources.teams.length" class="team-chips">
                    <NTag v-for="team in resources.teams" :key="team.team_id" size="small" :bordered="false">{{ team.team_id }} · {{ team.case_count }} Case</NTag>
                  </div>
                </div>
                <NDataTable
                  v-if="resources.cases.length"
                  class="resource-case-table"
                  :columns="resourceColumns"
                  :data="resources.cases"
                  :row-key="resourceCaseRowKey"
                  :bordered="false"
                  :scroll-x="780"
                />
                <NEmpty v-else class="resource-empty" description="当前没有可管理的协作 Case。" />
                <p class="resource-note">Worker 生命周期由独立 Worker 部署管理；此处仅显示心跳。Case 重协调会由 Bridge 重新同步其受控任务状态，需 TOTP 二次验证。</p>
              </template>
            </NCard>

            <NCard class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">Worker 令牌管理</span></template>
              <template #header-extra>
                <div class="bridge-actions">
                  <NButton size="small" secondary :loading="workerTokenLoading" @click="loadWorkerTokens">
                    <template #icon><NIcon><RefreshOutline /></NIcon></template>
                    刷新
                  </NButton>
                  <NButton size="small" type="primary" @click="requestIssueWorkerToken">签发令牌</NButton>
                </div>
              </template>
              <NAlert type="info" :show-icon="true" class="bridge-note bridge-note--flush">
                可吊销的 per-worker 令牌逐步替代静态共享密钥；静态 BRIDGE_IDENTITIES 令牌在迁移期内继续有效。令牌仅在签发时展示一次，Bridge 只保存哈希。
              </NAlert>
              <NDataTable
                v-if="workerTokens.length"
                :columns="workerTokenColumns"
                :data="workerTokens"
                :row-key="workerTokenRowKey"
                :bordered="false"
                :scroll-x="640"
              />
              <NEmpty v-else class="resource-empty" description="尚未签发任何 Worker 令牌。" />
            </NCard>
          </main>

          <aside class="bridge-side">
            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">AgentTeams 运行指标</span></template>
              <NAlert v-if="(bridgeMetrics.stale_nonterminal_case_count || 0) > 0" type="warning" :show-icon="true" class="bridge-note bridge-note--flush">
                {{ bridgeMetrics.stale_nonterminal_case_count }} 个 Case 已在非终态停留超过 2 小时。
              </NAlert>
              <NAlert v-if="(bridgeMetrics.room_provision_failure_count || 0) > 0" type="warning" :show-icon="true" class="bridge-note">
                {{ bridgeMetrics.room_provision_failure_count }} 次 Matrix 建房失败；请检查 Gateway 配置、网络和 Matrix 服务。
              </NAlert>
              <div class="agentteams-metric-grid">
                <div><span>Case 总数</span><strong>{{ bridgeMetrics.case_count || 0 }}</strong></div>
                <div><span>已关闭</span><strong>{{ bridgeMetrics.closed_case_count || 0 }}</strong></div>
                <div><span>取消率</span><strong>{{ ((bridgeMetrics.case_cancel_rate_bps || 0) / 100).toFixed(1) }}%</strong></div>
                <div><span>工单失败 / 重试</span><strong>{{ bridgeMetrics.work_item_failure_count || 0 }} / {{ bridgeMetrics.work_item_retry_count || 0 }}</strong></div>
                <div><span>Case P95</span><strong>{{ Math.round((bridgeMetrics.case_end_to_end_p95_ms || 0) / 1000) }}s</strong></div>
                <div><span>审批等待 P95</span><strong>{{ Math.round((bridgeMetrics.approval_wait_p95_ms || 0) / 1000) }}s</strong></div>
                <div><span>建房成功率</span><strong>{{ ((bridgeMetrics.room_provision_success_rate_bps || 0) / 100).toFixed(1) }}%</strong></div>
              </div>
              <p class="resource-note">指标来自 Bridge 审计事件；非终态超过 2 小时会在此告警。</p>
            </NCard>
            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">近 7 天会诊质量</span></template>
              <div class="quality-metrics">
                <div><span>信封解析成功率</span><NProgress type="line" :percentage="Math.round(consultationQuality.parse_success_rate * 100)" :height="8" /></div>
                <div><span>证据引用命中率</span><NProgress type="line" :percentage="Math.round(consultationQuality.evidence_hit_rate * 100)" :height="8" /></div>
                <div><span>QC 与硬规则一致性</span><NProgress type="line" :percentage="Math.round(consultationQuality.qc_consistency_rate * 100)" :height="8" /></div>
              </div>
              <p class="resource-note">{{ consultationQuality.total }} 次会诊 · 平均 {{ consultationQuality.average_tool_calls.toFixed(1) }} 次工具调用</p>
            </NCard>
            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">协作能力档位</span></template>
              <p class="preset-hint">{{ presetDescription }}</p>
              <NRadioGroup v-model:value="preset" name="collaboration-preset" class="preset-options">
                <NRadioButton value="light">轻量协作</NRadioButton>
                <NRadioButton value="parallel">并行增强</NRadioButton>
                <NRadioButton value="full">全流程闭环</NRadioButton>
                <NRadioButton value="custom">自定义</NRadioButton>
              </NRadioGroup>
              <div class="degradation-counts" aria-label="近七天协作降级次数">
                <span class="deg-label">近 7 天降级</span>
                <span class="deg-chip">并行 <b>{{ degradationCounts.fanout || 0 }}</b></span>
                <span class="deg-chip">会诊 <b>{{ degradationCounts.consult || 0 }}</b></span>
                <span class="deg-chip">Case <b>{{ degradationCounts.case || 0 }}</b></span>
                <span class="deg-chip">MAS <b>{{ degradationCounts.dag || 0 }}</b></span>
              </div>
              <div class="preset-actions">
                <NButton size="small" type="primary" :loading="presetSaving" @click="requestApplyPreset">查看变更并应用</NButton>
              </div>
            </NCard>

            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">协作部署健康检查</span></template>
              <NAlert v-if="!health?.connection.connected" type="error" :show-icon="true" class="bridge-note bridge-note--flush">
                Bridge 尚未接通，无法验证身份令牌和外部 Worker。仅修改平台配置不会启动外部 Worker。
              </NAlert>
              <template v-else>
                <div class="health-rows">
                  <div class="health-row">
                    <span class="health-label">
                      <span
                        class="health-dot" aria-hidden="true"
                        :class="validIdentityCount === health.identities.length ? 'health-dot--success' : 'health-dot--error'"
                      />
                      Bridge 与身份令牌
                    </span>
                    <NTag
                      size="small" :bordered="false"
                      :type="validIdentityCount === health.identities.length ? 'success' : 'error'"
                    >
                      {{ validIdentityCount }}/{{ health.identities.length }} 有效
                    </NTag>
                  </div>
                  <div class="health-row">
                    <span class="health-label">
                      <span
                        class="health-dot" aria-hidden="true"
                        :class="inactiveWorkers.length ? 'health-dot--error' : 'health-dot--success'"
                      />
                      外部 Worker
                    </span>
                    <NTag size="small" :bordered="false" :type="inactiveWorkers.length ? 'error' : 'success'">
                      {{ activeWorkerCount }}/{{ health.workers.length }} 活跃
                    </NTag>
                  </div>
                </div>
                <NAlert v-if="inactiveWorkers.length" type="error" :show-icon="true" class="bridge-note">
                  {{ inactiveWorkers.map((worker) => worker.identity).join('、') }} 未在心跳窗口内轮询任务。请按 `deploy/agentteams/README.md` 部署对应 Worker。
                </NAlert>
                <NAlert :type="health.scrna_submit_available ? 'success' : 'warning'" :show-icon="true" class="bridge-note bridge-note--flush">
                  {{ health.scrna_submit_available ? 'Bridge 白名单已包含 scrna_seq。' : `当前白名单：${health.allowed_flows.join(', ') || '未读取'}；scrna 流程暂不可提交。` }}
                </NAlert>
                <NAlert :type="health.room_gateway?.connected ? 'success' : 'warning'" :show-icon="true" class="bridge-note bridge-note--flush">
                  {{ health.room_gateway?.connected ? 'Matrix Gateway 已接通。' : `Matrix Gateway 不可用：${health.room_gateway?.reason || 'unknown'}。Case 将降级为平台事件流。` }}
                </NAlert>
              </template>
            </NCard>

            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">Bridge 接入向导</span></template>
              <p class="preset-hint">按顺序完成配置。检测只读取 Bridge 健康状态，不会改动运行中的 Worker。</p>
              <ol class="onboarding-list">
                <li v-for="(step, index) in onboardingSteps" :key="step.title" :class="{ complete: step.complete }">
                  <span class="step-marker" aria-hidden="true">
                    <NIcon v-if="step.complete" :component="CheckmarkOutline" />
                    <template v-else>{{ index + 1 }}</template>
                  </span>
                  <span class="step-title">{{ step.title }}</span>
                  <NTag :type="step.complete ? 'success' : 'default'" size="tiny" :bordered="false">
                    {{ step.complete ? '已完成' : '待完成' }}
                  </NTag>
                </li>
              </ol>
              <NAlert v-if="generatedTokens" type="warning" :show-icon="true" class="bridge-note">
                新令牌仅在本次页面会话中显示。复制到 Worker 环境变量后立即保存，离开页面前请妥善保管。
              </NAlert>
              <div class="onboarding-actions">
                <NButton size="small" secondary @click="tokenConfirmVisible = true">生成四个 Worker 令牌</NButton>
                <NButton v-if="generatedTokens" size="small" secondary @click="copyGeneratedTokens">
                  <template #icon><NIcon><CopyOutline /></NIcon></template>
                  复制身份令牌
                </NButton>
              </div>
            </NCard>

            <NCard size="small" class="bridge-card" :segmented="{ content: true }">
              <template #header><span class="card-title">协作降级文案</span></template>
              <p class="preset-hint">可使用占位符：<code>{intent}</code>、<code>{setting}</code>、<code>{alternative}</code>。</p>
              <NForm label-placement="top">
                <NFormItem label="默认展示语言" class="locale-item">
                  <NSelect
                    v-model:value="degradationLocale"
                    :options="[{ label: '中文', value: 'zh-CN' }, { label: 'English', value: 'en' }]"
                  />
                </NFormItem>
                <NFormItem label="中文模板">
                  <NInput v-model:value="degradationTemplateZh" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
                </NFormItem>
                <NFormItem label="English template">
                  <NInput v-model:value="degradationTemplateEn" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
                </NFormItem>
                <div class="preset-actions"><NButton size="small" :loading="templateSaving" @click="saveDegradationTemplates">保存文案</NButton></div>
              </NForm>
            </NCard>
          </aside>
        </div>
      </div>
    </NSpin>

    <AdminTOTPConfirmModal
      v-model:show="confirmVisible"
      title="保存 AgentTeams Bridge 配置"
      description="该操作会更新全局多 Agent 编排接入和加密凭证。请输入当前 6 位 TOTP 验证码后继续。"
      confirm-text="保存配置"
      :loading="saving"
      @confirm="save"
    />
    <AdminTOTPConfirmModal
      v-model:show="tokenConfirmVisible"
      title="生成 AgentTeams Worker 令牌"
      description="将生成四个新的高熵 Worker 令牌，仅回显一次且不会自动保存。确认后请部署 Worker，再保存 Bridge 配置。"
      confirm-text="生成令牌"
      :loading="tokenGenerating"
      @confirm="generateTokens"
    />
    <AdminTOTPConfirmModal
      v-model:show="reconcileConfirmVisible"
      title="重协调协作 Case"
      :description="'将请求 Bridge 重新同步 Case ' + reconcileCaseId + ' 的受控任务状态；不会绕过审批或创建新计算任务。'"
      confirm-text="确认重协调"
      :loading="reconciling"
      @confirm="reconcileCase"
    />
    <AdminTOTPConfirmModal
      v-model:show="issueTotpVisible"
      title="签发 Worker 令牌"
      :description="'将为 ' + (issueForm.identity || '') + ' 签发一个可吊销的 Bridge 访问令牌；原始令牌仅回显一次。'"
      confirm-text="确认签发"
      :loading="issuing"
      @confirm="issueWorkerToken"
    />
    <AdminTOTPConfirmModal
      v-model:show="revokeTotpVisible"
      title="吊销 Worker 令牌"
      :description="'将立即吊销 ' + (revokeTarget?.identity || '') + ' 的令牌，使用该令牌的 Worker 会立刻失去访问能力。'"
      confirm-text="确认吊销"
      :loading="revoking"
      @confirm="revokeWorkerToken"
    />
    <NModal v-model:show="issueDialogVisible" preset="dialog" title="签发 Worker 令牌" positive-text="下一步" negative-text="取消" @positive-click="confirmIssueForm">
      <NForm label-placement="top" style="margin-top: 8px">
        <NFormItem label="Worker 身份" required>
          <NSelect
            v-model:value="issueForm.identity"
            :options="workerIdentityOptions"
            placeholder="选择要签发的身份"
            filterable
          />
        </NFormItem>
        <NFormItem label="有效期（天，0 表示永不过期）">
          <NInputNumber v-model:value="issueForm.ttlDays" :min="0" :max="365" :precision="0" style="width: 100%" />
        </NFormItem>
        <NFormItem label="备注">
          <NInput v-model:value="issueForm.note" placeholder="例如：worker-pool-01" maxlength="256" />
        </NFormItem>
      </NForm>
    </NModal>
    <NModal :show="Boolean(issuedToken)" preset="dialog" title="令牌已签发（仅展示一次）" positive-text="我已保存" @positive-click="issuedToken = null" :show-close="false" :closable="false" :mask-closable="false">
      <NAlert type="warning" :show-icon="true" style="margin-bottom: 12px">
        关闭后无法再次查看该令牌。请立即复制到 Worker 部署的环境变量（如 AGENTTEAMS_BRIDGE_TOKEN）。
      </NAlert>
        <NInput :value="issuedToken?.token || ''" readonly>
          <template #suffix>
            <NButton text size="small" @click="copyIssuedToken">
              <template #icon><NIcon><CopyOutline /></NIcon></template>
            </NButton>
          </template>
        </NInput>
    </NModal>
    <NModal v-model:show="presetConfirmVisible" preset="dialog" title="确认应用协作档位" positive-text="确认应用" negative-text="取消" @positive-click="applyPreset">
      <p>将应用“{{ presetDescription.split('：')[0] }}”，并原子性写入以下开关：</p>
      <ul class="preset-diff">
        <li v-for="item in presetDiff" :key="item">{{ item }}</li>
      </ul>
    </NModal>
  </div>
</template>

<style scoped>
.tab-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.tab-hint { font-size: 12px; color: var(--neutral-text-3); }
.bridge-body { min-height: 240px; }

/* 概览卡：页面状态锚点 */
.bridge-overview { display: flex; align-items: center; gap: 14px; padding: 20px 24px; margin-bottom: 16px; background: var(--neutral-card); border: 1px solid var(--neutral-border); border-radius: 12px; }
.bridge-avatar { flex-shrink: 0; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--arco-primary-light); color: var(--arco-primary); font-size: 20px; }
.bridge-overview-text { flex: 1; min-width: 0; }
.bridge-overview-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.bridge-overview-title h3 { margin: 0; font-size: 16px; line-height: 24px; font-weight: 600; color: var(--neutral-text-1); }
.bridge-overview-text p { margin: 4px 0 0; font-size: 12px; line-height: 18px; color: var(--neutral-text-3); }

.bridge-note { margin-bottom: 16px; }
.bridge-note--flush { margin-bottom: 12px; }

/* 主侧双栏：填满配置中心内容边界 */
.bridge-grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; align-items: start; }
.bridge-main, .bridge-side { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.bridge-card { border-radius: 12px; }
.card-title { font-size: 14px; font-weight: 600; color: var(--neutral-text-1); }
.agentteams-metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.agentteams-metric-grid div { padding: 10px; border: 1px solid var(--neutral-border); border-radius: 8px; background: var(--neutral-fill-1); }
.agentteams-metric-grid span { display: block; font-size: 11px; color: var(--neutral-text-3); }
.agentteams-metric-grid strong { display: block; margin-top: 4px; font-size: 16px; color: var(--neutral-text-1); }
/* 接入配置表单 */
.bridge-status-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-bottom: 20px; margin-bottom: 20px; border-bottom: 1px solid var(--neutral-border); }
.bridge-status-text { min-width: 0; }
.bridge-status-label { font-size: 13px; line-height: 20px; font-weight: 500; color: var(--neutral-text-1); }
.bridge-status-text p { max-width: 700px; margin: 4px 0 0; font-size: 12px; line-height: 18px; color: var(--neutral-text-3); }
.bridge-field-grid { display: grid; grid-template-columns: minmax(0, 1fr) 160px; gap: 0 16px; }
.timeout-item :deep(.n-input-number) { width: 100%; }
.bridge-secret-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.bridge-actions { display: flex; justify-content: flex-end; gap: 8px; }
/* 资源管理 */
.resource-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 16px 28px; margin-bottom: 14px; }
.rs-item { display: flex; flex-direction: column; gap: 2px; }
.rs-value { font-size: 18px; line-height: 26px; font-weight: 600; color: var(--neutral-text-1); }
.rs-value--danger { color: var(--arco-danger); }
.rs-label { font-size: 12px; line-height: 18px; color: var(--neutral-text-3); }
.team-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.resource-case-table { margin-top: 4px; }
.resource-empty { padding: 24px 0; }
.resource-note { margin: 12px 0 0; font-size: 12px; line-height: 18px; color: var(--neutral-text-3); }
/* 档位与降级计数 */
.preset-hint { margin: 0 0 12px; font-size: 12px; line-height: 18px; color: var(--neutral-text-3); }
.preset-options { display: flex; flex-wrap: wrap; }
.preset-actions { display: flex; justify-content: flex-end; margin-top: 12px; }
.degradation-counts { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--neutral-border); }
.quality-metrics { display: grid; gap: 12px; }
.quality-metrics > div { display: grid; gap: 6px; }
.quality-metrics span { color: var(--neutral-text-2); font-size: 12px; }
.deg-label { font-size: 12px; color: var(--neutral-text-3); }
.deg-chip { font-size: 12px; line-height: 18px; color: var(--neutral-text-2); background: var(--neutral-hover); border-radius: 9999px; padding: 1px 10px; }
.deg-chip b { font-weight: 600; color: var(--neutral-text-1); }
/* 健康检查 */
.health-rows { display: flex; flex-direction: column; margin-bottom: 12px; }
.health-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; }
.health-row + .health-row { border-top: 1px solid var(--neutral-border); }
.health-label { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; color: var(--neutral-text-1); }
.health-dot { width: 8px; height: 8px; border-radius: 9999px; flex-shrink: 0; }
.health-dot--success { background: var(--arco-success); }
.health-dot--error { background: var(--arco-danger); }
/* 接入向导步骤条 */
.onboarding-list { display: flex; flex-direction: column; margin: 0 0 12px; padding: 0; list-style: none; }
.onboarding-list li { position: relative; display: flex; align-items: center; gap: 10px; padding: 6px 0; }
.onboarding-list li:not(:last-child)::before { content: ''; position: absolute; left: 10px; top: 32px; bottom: -6px; width: 2px; background: var(--neutral-border); }
.step-marker { position: relative; z-index: 1; flex-shrink: 0; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; border-radius: 9999px; border: 1px solid var(--neutral-border); background: var(--neutral-card); font-size: 12px; color: var(--neutral-text-3); }
.onboarding-list li.complete .step-marker { border-color: var(--arco-success); background: var(--arco-success); color: var(--text-on-primary); }
.step-title { flex: 1; min-width: 0; font-size: 13px; color: var(--neutral-text-2); }
.onboarding-list li.complete .step-title { color: var(--neutral-text-1); }
.onboarding-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
/* 降级文案与其他 */
.locale-item :deep(.n-select) { max-width: 240px; }
.preset-hint code { font-size: 12px; color: var(--neutral-text-2); background: var(--neutral-hover); border-radius: 4px; padding: 1px 5px; }
.preset-diff { margin: 8px 0 0; padding-left: 20px; line-height: 1.8; color: var(--neutral-text-2); }

@media (max-width: 1024px) {
  .bridge-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 768px) {
  .bridge-overview { flex-wrap: wrap; }
  .bridge-status-row { align-items: flex-start; }
  .bridge-field-grid, .bridge-secret-grid { grid-template-columns: minmax(0, 1fr); }
  .bridge-actions { flex-direction: column-reverse; }
  .bridge-actions :deep(.n-button) { width: 100%; }
}
</style>
