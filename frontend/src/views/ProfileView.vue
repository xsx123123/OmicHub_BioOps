<template>
  <main class="page-container profile-page-wrapper" :aria-busy="isLoading">
    <div class="profile-content">
      <PageHeader title="个人中心" subtitle="查看工作概览，管理个人偏好与账户安全。">
        <template #actions>
          <NButton secondary :loading="isRefreshing" @click="refreshProfile">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            刷新资料
          </NButton>
        </template>
      </PageHeader>

      <NSpin :show="isLoading">
        <section class="profile-grid" aria-label="个人中心概览">
          <NCard :bordered="false" class="arco-card profile-card profile-card--hero">
            <div class="profile-hero">
              <NAvatar round :size="64" :src="user?.avatar_url || undefined" class="profile-avatar">
                {{ userInitial }}
              </NAvatar>
              <div class="profile-identity">
                <div class="profile-name-row">
                  <h2>{{ displayName(user) }}</h2>
                  <NTag :type="user?.role === 'admin' ? 'warning' : 'default'" size="small" round>
                    {{ user?.role === 'admin' ? '管理员' : '普通用户' }}
                  </NTag>
                  <NTag :type="statusTagType" size="small" round>{{ statusLabel }}</NTag>
                </div>
                <p>{{ user?.email || '未设置邮箱' }}</p>
                <span>ID: <code class="profile-id-code" :title="user?.id">{{ user?.id || '-' }}</code> · 创建于 {{ formatDateOnly(user?.created_at) }}</span>
              </div>
              <NButton text size="small" @click="router.push('/settings')">
                <template #icon><NIcon><CreateOutline /></NIcon></template>
                编辑资料
              </NButton>
            </div>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card profile-card--wide">
            <template #header><CardTitle :icon="ListOutline" title="最近任务" /></template>
            <template #header-extra><NButton text size="small" @click="router.push('/tasks')">查看全部</NButton></template>
            <div class="task-summary" aria-label="任务与存储概览">
              <div v-for="stat in statistics" :key="stat.label" class="task-summary-item">
                <span>{{ stat.label }}</span>
                <strong :style="{ color: stat.color }">{{ stat.value }}<em>{{ stat.unit }}</em></strong>
                <NProgress v-if="stat.total" type="line" :percentage="stat.label === '存储空间' ? (storageQuotaInfo?.percent ?? 0) : percentage(stat.value, stat.total)" :show-indicator="false" :color="stat.color" />
              </div>
            </div>
            <NDataTable
              v-if="recentTasks.length"
              :columns="profileTaskColumns"
              :data="recentTasks"
              :row-key="profileTaskRowKey"
              :bordered="false"
              size="small"
              :single-line="false"
              :scroll-x="780"
              class="recent-table recent-table-surface"
            />
            <NEmpty v-else description="还没有分析任务，提交流程后会在这里显示。"><template #extra><NButton size="small" type="primary" @click="router.push('/flows')">浏览流程</NButton></template></NEmpty>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card profile-card--wide">
            <template #header>
              <NSpace align="center" :size="8">
                <CardTitle :icon="SparklesOutline" title="我的记忆" />
                <NTag v-if="memories.length" size="small" round type="info">{{ memories.length }} 条</NTag>
              </NSpace>
            </template>
            <template #header-extra>
              <NButton text size="small" @click="router.push('/profile/memories')">
                查看全部
              </NButton>
            </template>
            <p class="memory-hint">这些记忆来自你与 AI 助手的对话：研究偏好、项目事实与对话沉淀，跨会话生效并加密存储；可随时删除。</p>
            <div v-if="previewMemories.length" class="memory-list">
              <div v-for="memory in previewMemories" :key="memory.id" class="memory-row">
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
            <NEmpty v-else size="small" :description="'暂无记忆。与 AI 助手对话累计约 6 条消息后，研究偏好与项目事实会自动沉淀到这里（需要平台 AI 模型密钥有效）。'">
              <template #extra>
                <NSpace justify="center">
                  <NButton size="small" :loading="isMemorySyncing" @click="rebuildMemories">整理已有对话</NButton>
                  <NButton size="small" type="primary" @click="router.push('/ai')">继续对话</NButton>
                </NSpace>
              </template>
            </NEmpty>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card">
            <template #header><CardTitle :icon="FlashOutline" title="常用流程" /></template>
            <div class="quick-flow-list">
              <NButton v-for="flow in favoriteFlows" :key="flow.id" quaternary size="small" class="quick-flow" @click="router.push(`/flows/${flow.id}/submit`)">
                <NIcon :component="flow.icon" />{{ flow.name }}
              </NButton>
            </div>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card">
            <template #header><CardTitle :icon="ShieldCheckmarkOutline" title="安全与登录" /></template>
            <div class="detail-list">
              <div><span>最后登录</span><strong>{{ formatDateTime(user?.last_login_at) }}</strong></div>
              <div><span>二次验证</span><NTag :type="twoFactorEnabled ? 'success' : 'warning'" size="small" round>{{ twoFactorEnabled ? '已开启' : '未开启' }}</NTag></div>
              <div><span>账户状态</span><NTag :type="statusTagType" size="small" round>{{ statusLabel }}</NTag></div>
            </div>
            <NButton block secondary @click="router.push('/settings')">管理安全设置</NButton>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card profile-card--audit">
            <template #header><CardTitle :icon="LockClosedOutline" title="审计记录" /></template>
            <div v-if="auditLogs.length" class="audit-list">
              <div v-for="log in auditLogs.slice(0, 3)" :key="`${log.created_at}-${log.description}`" class="audit-row">
                <NTag :type="auditTagType(log.type)" size="small" round>{{ log.type_label }}</NTag>
                <span>
                  <NTooltip :disabled="log.description.length <= 40">
                    <template #trigger><strong class="audit-description">{{ log.description }}</strong></template>
                    {{ log.description }}
                  </NTooltip>
                  <small>{{ formatRelative(log.created_at) }}</small>
                </span>
              </div>
            </div>
            <NEmpty v-else size="small" description="暂无可显示的审计记录" />
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card profile-card--wide">
            <template #header><CardTitle :icon="SettingsOutline" title="平台偏好" /></template>
            <NGrid cols="1 m:2" responsive="screen" :x-gap="20" :y-gap="20">
              <NGridItem><label class="field-label">默认首页<NSelect v-model:value="preferences.default_page" :options="defaultPageOptions" :loading="savingPreferences" @update:value="savePreferences" /></label></NGridItem>
              <NGridItem><label class="field-label">语言<NSelect v-model:value="preferences.language" :options="languageOptions" :loading="savingPreferences" @update:value="savePreferences" /></label></NGridItem>
              <NGridItem span="1 m:2"><span class="field-label">主题</span><NRadioGroup v-model:value="preferences.theme" size="small" @update:value="onThemeChange"><NRadioButton value="system">跟随系统</NRadioButton><NRadioButton value="light">亮色</NRadioButton><NRadioButton value="dark">深色</NRadioButton></NRadioGroup></NGridItem>
              <NGridItem span="1 m:2"><span class="field-label">通知渠道</span><NSpace><NCheckbox v-model:checked="preferences.notifications.email" @update:checked="savePreferences">邮件</NCheckbox><NCheckbox v-model:checked="preferences.notifications.in_app" @update:checked="savePreferences">站内消息</NCheckbox><NCheckbox v-model:checked="preferences.notifications.webhook" @update:checked="savePreferences">Webhook</NCheckbox></NSpace></NGridItem>
            </NGrid>
          </NCard>

          <NCard :bordered="false" class="arco-card profile-card profile-card--wide">
            <template #header><CardTitle :icon="ShieldOutline" title="数据与隐私" /></template>
            <div class="privacy-row"><div><strong>导出个人数据</strong><p>下载账户资料、已加载的任务清单与平台偏好。</p></div><NButton :loading="exporting" @click="exportProfileData">导出数据</NButton></div>
            <div class="privacy-row"><div><strong>账户资料</strong><p>修改昵称、邮箱、头像和登录密码。</p></div><NButton secondary @click="router.push('/settings')">前往设置</NButton></div>
          </NCard>

        </section>
      </NSpin>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NAvatar, NButton, NCard, NCheckbox, NDataTable, NEmpty, NGrid, NGridItem, NIcon, NProgress, NRadioButton, NRadioGroup, NSelect, NSpace, NSpin, NTag, NTooltip, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  BeakerOutline,
  CreateOutline,
  EarthOutline,
  EyeOutline,
  FlashOutline,
  ListOutline,
  LockClosedOutline,
  RefreshOutline,
  SettingsOutline,
  ShieldCheckmarkOutline,
  ShieldOutline,
  SparklesOutline,
  StatsChartOutline,
} from '@vicons/ionicons5'
import { format, formatDistanceToNow, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { displayName } from '@/utils/displayName'
import { presentRequestError } from '@/utils/errorPresentation'
import apiClient from '@/api/client'
import type { QuotaInfo, Task, User } from '@/types'
import PageHeader from '@/components/PageHeader.vue'

interface AuditLog { type: string; type_label: string; description: string; created_at: string }
interface AgentMemory { id: string; agent_id: string | null; scope: 'profile' | 'project' | 'preference' | 'summary'; content: string; updated_at: string | null; source_session?: string | null; project_id?: string | null; created_at?: string | null }
interface UserPreferences { default_page: string; theme: 'system' | 'light' | 'dark'; language: string; notifications: { email: boolean; in_app: boolean; webhook: boolean } }

const CardTitle = defineComponent({ props: { icon: { type: Object, required: true }, title: { type: String, required: true } }, setup: props => () => h(NSpace, { align: 'center', size: 8 }, { default: () => [h(NIcon, { size: 18 }, { default: () => h(props.icon as never) }), h('span', props.title)] }) })
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const message = useMessage()
const tasks = ref<Task[]>([])
const storageQuotaInfo = ref<QuotaInfo | null>(null)
const auditLogs = ref<AuditLog[]>([])
const memories = ref<AgentMemory[]>([])
const isLoading = ref(true)
const isRefreshing = ref(false)
const isMemorySyncing = ref(false)
const exporting = ref(false)
const savingPreferences = ref(false)
const twoFactorEnabled = ref(false)
const preferences = ref<UserPreferences>({ default_page: 'dashboard', theme: 'system', language: 'zh-CN', notifications: { email: true, in_app: true, webhook: false } })
const favoriteFlows = [
  { id: 'rna-seq', name: 'RNA-seq', icon: BeakerOutline },
  { id: 'atac-seq', name: 'ATAC-seq', icon: BeakerOutline },
  { id: 'scrna-seq', name: '单细胞', icon: StatsChartOutline },
  { id: 'literature', name: '文献检索', icon: EarthOutline },
]
const defaultPageOptions = [{ label: '控制台', value: 'dashboard' }, { label: '分析中心', value: 'analysis' }, { label: '任务中心', value: 'tasks' }, { label: '数据管理', value: 'data' }]
const languageOptions = [{ label: '简体中文', value: 'zh-CN' }, { label: 'English', value: 'en-US' }]
const user = computed(() => authStore.user)
const userInitial = computed(() => displayName(user.value).charAt(0).toUpperCase() || 'U')
const statusLabel = computed(() => {
  const labels: Record<string, string> = { active: '正常', inactive: '已禁用', locked: '已锁定' }
  return labels[user.value?.status || ''] || '未知'
})
const statusTagType = computed(() => user.value?.status === 'active' ? 'success' : user.value?.status === 'locked' ? 'error' : 'warning')
const recentTasks = computed(() => tasks.value.slice(0, 3))
const storageQuota = computed(() => Number(storageQuotaInfo.value?.total ?? user.value?.storage_quota ?? 0) / 1024 ** 3)
function formatStorage(bytes: number) {
  if (!bytes) return { value: '0', unit: 'B' }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return { value: (bytes / 1024 ** index).toFixed(2), unit: units[index] }
}
const storageDisplay = computed(() => formatStorage(storageQuotaInfo.value?.used ?? user.value?.used_storage ?? 0))
const statistics = computed(() => { const month = new Date().getMonth(); const analyses = tasks.value.filter(task => parseDate(task.created_at)?.getMonth() === month).length; const running = tasks.value.filter(task => ['pending', 'queued', 'running'].includes(task.status)).length; return [{ label: '本月分析', value: analyses, unit: '次', color: 'var(--arco-primary)' }, { label: '运行中', value: running, unit: '个', color: 'var(--arco-success)' }, { label: '存储空间', value: storageDisplay.value.value, unit: storageDisplay.value.unit, total: storageQuota.value, color: 'var(--icon-visualization)' }] })

function parseDate(value?: string | null) { if (!value) return null; const date = parseISO(value); return Number.isNaN(date.getTime()) ? null : date }
function formatDateOnly(value?: string | null) { const date = parseDate(value); return date ? format(date, 'yyyy/MM/dd') : '-' }
function formatDateTime(value?: string | null) { const date = parseDate(value); return date ? format(date, 'yyyy/MM/dd HH:mm') : '暂无登录记录' }
function formatRelative(value?: string | null) { const date = parseDate(value); return date ? formatDistanceToNow(date, { addSuffix: true, locale: zhCN }) : '-' }
function percentage(value: string | number, total: number) { return total > 0 ? Math.min(Math.round((Number(value) / total) * 100), 100) : 0 }
function taskStatus(status: string) { return ({ pending: '等待中', queued: '排队中', running: '运行中', success: '已完成', failed: '失败', cancelled: '已取消' }[status] || status) }
function taskTagType(status: string) { return ({ success: 'success', running: 'success', failed: 'error', pending: 'warning', queued: 'warning', cancelled: 'default' }[status] || 'default') as 'success' | 'error' | 'warning' | 'default' }
function auditTagType(type: string) { return ({ password: 'warning', security: 'success', delete: 'error', email: 'default' }[type] || 'default') as 'success' | 'error' | 'warning' | 'default' }
function pct(value: number | null | undefined): number { const n = Number(value) || 0; return Math.round(n > 1 ? n : n * 100) }
function profileTaskRowKey(row: Task) { return row.id }
const profileTaskColumns: DataTableColumns<Task> = [
  { title: '任务名称', key: 'name', width: 200, align: 'center', ellipsis: { tooltip: true } },
  { title: '分析流程', key: 'flow_id', width: 130, align: 'center' },
  { title: '提交时间', key: 'created_at', width: 140, align: 'center', render: (row) => formatRelative(row.created_at) },
  { title: '状态', key: 'status', width: 90, align: 'center', render: (row) => h(NTag, { type: taskTagType(row.status), size: 'small', round: true }, { default: () => taskStatus(row.status) }) },
  { title: '进度', key: 'progress', width: 150, render: (row) => h('div', { class: 'recent-task-progress' }, [h(NProgress, { type: 'line', percentage: pct(row.progress), height: 6, railColor: 'var(--neutral-border)', showIndicator: false }), h('span', { class: 'recent-task-progress__value' }, `${pct(row.progress)}%`)]) },
  { title: '操作', key: 'actions', width: 70, align: 'center', render: (row) => h(NTooltip, null, { trigger: () => h(NButton, { size: 'tiny', quaternary: true, circle: true, onClick: () => router.push(`/tasks/${row.id}`) }, { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) }), default: () => '查看任务详情' }) },
]
function memoryScopeLabel(scope: AgentMemory['scope']) { return ({ profile: '用户画像', project: '项目', preference: '偏好', summary: '摘要' }[scope]) }
const memoryScopeFilter = ref<'all' | AgentMemory['scope']>('all')
const previewMemories = computed(() => memories.value.slice(0, 4))
const AGENT_LABELS: Record<string, string> = { 'agent-general': '通用助手', 'agent-rnaseq': 'RNA-seq 分析师', 'agent-scrna': '单细胞分析师', 'agent-scrna-upstream': '单细胞上游', 'agent-scrna-integration': '单细胞整合', 'agent-scrna-advanced': '单细胞进阶', 'agent-code': '代码助手', 'agent-viz': '可视化助手', 'agent-mcp-builder': 'MCP 构建师', shania: '傻妞' }
function memoryAgentLabel(memory: AgentMemory) { if (!memory.agent_id) return '全局记忆'; return AGENT_LABELS[memory.agent_id] || memory.agent_id }
function applyTheme(theme: UserPreferences['theme']) {
  const resolved = theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme
  themeStore.setTheme(resolved)
}

async function loadProfile() {
  await authStore.fetchUser()
  try {
    const { data } = await apiClient.get<QuotaInfo>('/files/quota')
    storageQuotaInfo.value = data
  } catch {
    storageQuotaInfo.value = null
  }
  const saved = user.value?.preferences?.profile
  const savedTheme = saved && typeof saved === 'object' ? (saved as Partial<UserPreferences>).theme : undefined
  if (saved && typeof saved === 'object') {
    preferences.value = {
      ...preferences.value,
      ...(saved as Partial<UserPreferences>),
      notifications: {
        ...preferences.value.notifications,
        ...((saved as Partial<UserPreferences>).notifications || {}),
      },
    }
  }
  if (themeStore.hasStoredPreference) {
    if (savedTheme !== 'system') preferences.value.theme = themeStore.theme
  } else if (savedTheme === 'dark' || savedTheme === 'light' || savedTheme === 'system') {
    preferences.value.theme = savedTheme
    applyTheme(savedTheme)
  } else {
    preferences.value.theme = themeStore.theme
  }
}
async function loadTasks() { const { data } = await apiClient.get<{ items: Task[] }>('/tasks'); tasks.value = data.items || [] }
async function loadAuditLogs() { const { data } = await apiClient.get<AuditLog[]>('/users/me/audit-logs', { params: { limit: 5 } }); auditLogs.value = data }
async function loadMemories() { const { data } = await apiClient.get<AgentMemory[]>('/users/me/memories'); memories.value = data }
async function rebuildMemories() {
  isMemorySyncing.value = true
  try {
    const { data } = await apiClient.post<{ status: string; queued: number }>('/users/me/memories/rebuild')
    if (data.status === 'disabled') {
      message.warning('平台记忆功能尚未启用，请联系管理员检查记忆引擎配置')
    } else if (data.queued > 0) {
      message.success(`已提交 ${data.queued} 个历史会话，稍后刷新即可查看记忆`)
    } else {
      message.info('暂时没有达到沉淀条件的历史会话')
    }
  } catch (error: any) {
    message.error(error.response?.data?.detail || '历史记忆整理失败')
  } finally {
    isMemorySyncing.value = false
  }
}
async function loadSecurity() { twoFactorEnabled.value = (await authStore.fetch2FAStatus()).enabled }
async function loadAll(refresh = false) { refresh ? isRefreshing.value = true : isLoading.value = true; try { await Promise.all([loadProfile(), loadTasks(), loadAuditLogs(), loadMemories(), loadSecurity()]) } catch (error: unknown) { const presentation = presentRequestError(error, '个人中心加载失败，请稍后重试'); if (presentation.kind === 'unauthorized') { authStore.logout(); await router.push('/login') } else message.error(presentation.message) } finally { isLoading.value = false; isRefreshing.value = false } }
async function deleteMemory(memoryId: string) { try { await apiClient.delete(`/users/me/memories/${memoryId}`); memories.value = memories.value.filter(memory => memory.id !== memoryId); message.success('记忆已删除') } catch (error: any) { message.error(error.response?.data?.detail || '删除记忆失败') } }
async function refreshProfile() { await loadAll(true); message.success('个人中心已刷新') }
async function savePreferences() { if (!user.value) return; savingPreferences.value = true; try { await apiClient.put(`/users/${user.value.id}`, { preferences: { ...(user.value.preferences || {}), profile: preferences.value } }); await authStore.fetchUser(); message.success('偏好已保存') } catch (error: any) { message.error(error.response?.data?.detail || '保存偏好失败') } finally { savingPreferences.value = false } }
async function onThemeChange(theme: UserPreferences['theme']) { applyTheme(theme); await savePreferences() }
async function exportProfileData() { exporting.value = true; try { const payload = { exported_at: new Date().toISOString(), user: user.value, preferences: preferences.value, tasks: tasks.value }; const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = `omichub-profile-${format(new Date(), 'yyyyMMdd')}.json`; link.click(); URL.revokeObjectURL(url); message.success('个人数据已导出') } finally { exporting.value = false } }
let mediaQuery: MediaQueryList | null = null
let handleSystemThemeChange: ((event: MediaQueryListEvent) => void) | null = null
watch(() => preferences.value.theme, theme => { if (mediaQuery && handleSystemThemeChange) mediaQuery.removeEventListener('change', handleSystemThemeChange); if (theme === 'system') { mediaQuery = window.matchMedia('(prefers-color-scheme: dark)'); handleSystemThemeChange = event => themeStore.setTheme(event.matches ? 'dark' : 'light'); mediaQuery.addEventListener('change', handleSystemThemeChange) } }, { immediate: true })
onMounted(() => { if (!authStore.isLoggedIn) router.push('/login'); else loadAll() })
onUnmounted(() => { if (mediaQuery && handleSystemThemeChange) mediaQuery.removeEventListener('change', handleSystemThemeChange) })
</script>

<style scoped>
.profile-page-wrapper { min-height: 100%; padding: var(--page-padding) var(--page-padding) var(--space-5xl); background: var(--neutral-bg); }
.profile-content { width: 100%; min-width: 0; }
.profile-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--section-gap); }
.profile-card { min-width: 0; padding: var(--card-padding); }
.profile-card--hero, .profile-card--wide { grid-column: span 3; }
.profile-card--hero { background: linear-gradient(135deg, var(--neutral-card) 55%, color-mix(in srgb, var(--arco-primary) 7%, var(--neutral-card))); }
.profile-hero, .profile-name-row, .detail-list > div, .privacy-row, .audit-row { display: flex; align-items: center; }
.profile-hero { gap: 20px; }.profile-identity { min-width: 0; flex: 1; }.profile-name-row { gap: 8px; flex-wrap: wrap; }.profile-name-row h2 { margin: 0; color: var(--neutral-text-1); font-size: 20px; letter-spacing: -0.015em; }.profile-identity p, .profile-identity span, .privacy-row p, .audit-row small { display: block; margin: 4px 0 0; color: var(--neutral-text-3); font-size: 13px; }.profile-avatar { flex: 0 0 auto; background: var(--arco-primary-light); color: var(--arco-primary); font-size: 28px; }.profile-id-code { padding: 1px 4px; border-radius: var(--radius-xs, 4px); background: var(--neutral-bg); color: var(--neutral-text-2); font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace); font-size: 12px; word-break: break-all; }
.task-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: -4px 0 20px; border: 1px solid var(--neutral-border); border-radius: var(--radius-sm); background: var(--neutral-bg); }.task-summary-item { min-width: 0; padding: 14px 16px; border-right: 1px solid var(--neutral-border); }.task-summary-item:last-child { border-right: 0; }.task-summary-item > span { display: block; color: var(--neutral-text-3); font-size: 12px; line-height: 18px; }.task-summary-item strong { display: block; margin-top: 4px; font-size: 22px; font-weight: 600; line-height: 28px; letter-spacing: -0.015em; }.task-summary-item em { margin-left: 4px; color: var(--neutral-text-3); font-size: 12px; font-style: normal; font-weight: 400; letter-spacing: 0; }
.quick-flow-list { gap: 8px; }.quick-flow { justify-content: flex-start; gap: 8px; }.detail-list { margin-bottom: 20px; }.detail-list > div { justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--neutral-border); color: var(--neutral-text-2); font-size: 13px; }.detail-list > div:last-child { border-bottom: 0; }.detail-list strong { color: var(--neutral-text-1); font-weight: 500; }.field-label { display: grid; gap: 8px; color: var(--neutral-text-2); font-size: 13px; }.privacy-row { justify-content: space-between; gap: 20px; padding: 16px 0; border-bottom: 1px solid var(--neutral-border); }.privacy-row:last-child { border-bottom: 0; }.privacy-row strong, .audit-row strong, .memory-row strong { color: var(--neutral-text-1); font-size: 14px; }.audit-row { align-items: flex-start; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--neutral-border); }.audit-row:last-child { border-bottom: 0; }.audit-row > span { min-width: 0; flex: 1; overflow: hidden; }.audit-row :deep(.n-tag) { flex-shrink: 0; }.audit-description { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }.memory-hint { margin: 0 0 20px; color: var(--neutral-text-3); font-size: 13px; }.memory-filter { margin-bottom: 10px; }.memory-row { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--neutral-border); }.memory-row:last-child { border-bottom: 0; }.memory-row > div { min-width: 0; flex: 1; }.memory-row small { display: block; margin-top: 4px; color: var(--neutral-text-3); font-size: 12px; }
.recent-table :deep(th) { font-size: 12px; color: var(--neutral-text-3); font-weight: 500; background: transparent; border-bottom: 1px solid var(--neutral-border); }
.recent-table :deep(td) { font-size: 13px; color: var(--neutral-text-1); border-bottom: 1px solid var(--neutral-border); }
.recent-table-surface :deep(th) { background: var(--neutral-bg); }
.recent-table-surface :deep(.n-data-table-wrapper), .recent-table-surface :deep(.n-data-table-base-table) { background: var(--neutral-card); }
.recent-table-surface :deep(td) { background: var(--neutral-card); }
.recent-table :deep(tr:hover td) { background: var(--neutral-hover); }
.recent-table :deep(.n-progress-graph) { min-width: 0; }
.recent-table :deep(.n-progress-graph-line-indicator) { white-space: nowrap; }
.recent-task-progress { display: flex; align-items: center; gap: 8px; min-width: 0; white-space: nowrap; }
.recent-task-progress .n-progress { flex: 1 1 auto; min-width: 60px; }
.recent-task-progress__value { flex: 0 0 44px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; font-size: 13px; color: var(--neutral-text-1); }
@media (max-width: 900px) { .profile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--card-gap); }.profile-card--hero, .profile-card--wide, .profile-card--audit { grid-column: span 2; } }
@media (max-width: 640px) { .profile-page-wrapper { padding: var(--space-2xl) var(--space-lg) var(--space-5xl); }.profile-grid { grid-template-columns: 1fr; gap: var(--card-gap); }.profile-card, .profile-card--hero, .profile-card--wide, .profile-card--audit { grid-column: span 1; padding: var(--card-padding); }.profile-hero { align-items: flex-start; flex-wrap: wrap; }.task-summary { grid-template-columns: 1fr; }.task-summary-item { border-right: 0; border-bottom: 1px solid var(--neutral-border); }.task-summary-item:last-child { border-bottom: 0; }.privacy-row { align-items: flex-start; flex-direction: column; gap: 12px; } }
</style>
