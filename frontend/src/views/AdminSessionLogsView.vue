<script setup lang="ts">
/**
 * 会话日志排查（管理员）— 按会话聚合对话 / AI 工作台 / 超频模式的可观测日志与调用链。
 * Phase 1：事件分类 / 级别过滤 / 会话内搜索 / SQL 脱敏（揭示需审计）/ 抽屉可用性。
 * Phase 2：Trace 调用链列表 + span 瀑布图；列表用户名、复制、排序、重置。
 */
import { h, nextTick, onMounted, ref } from 'vue'
import {
  NButton, NCard, NCheckbox, NDataTable, NDrawer, NDrawerContent, NEmpty, NGrid, NGi, NIcon,
  NInput, NSelect, NSpace, NSpin, NStatistic, NTabPane, NTabs, NTag, NTimeline, NTimelineItem,
  NTooltip, useDialog, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import {
  SparklesOutline, GitNetworkOutline, ConstructOutline, FlashOutline,
  DocumentTextOutline, RefreshOutline, SearchOutline, CopyOutline, ServerOutline,
  CogOutline, DownloadOutline, ThumbsUpOutline, ThumbsDownOutline,
} from '@vicons/ionicons5'
import PageHeader from '@/components/PageHeader.vue'
import {
  adminSessionLogsApi,
  type SessionFeedback,
  type SessionLogEvent,
  type SessionReport,
  type SessionSummary,
  type SpanNode,
  type TraceSummary,
} from '@/api/admin/sessionLogs'

const message = useMessage()
const dialog = useDialog()

// ===== 会话列表 =====
const search = ref('')
const modeFilter = ref<string>('')
const sessions = ref<SessionSummary[]>([])
const loadingSessions = ref(false)

const modeOptions = [
  { label: '全部模式', value: '' },
  { label: '对话 · 单助手 (chat)', value: 'chat' },
  { label: 'AI 工作台 · 工具执行 (studio)', value: 'studio' },
  { label: '超频模式 · 多 Agent 编排 (overdrive)', value: 'overdrive' },
]

const executionModeMeta = {
  chat: { label: '对话', type: 'default' as const },
  studio: { label: 'AI 工作台', type: 'info' as const },
  overdrive: { label: '超频模式', type: 'warning' as const },
}

function executionModeOf(row: SessionSummary) {
  return executionModeMeta[row.execution_mode] || executionModeMeta.chat
}

async function fetchSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await adminSessionLogsApi.listSessions({
      search: search.value.trim() || undefined,
      mode: modeFilter.value || undefined,
      limit: 100,
    })
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载会话列表失败')
  } finally {
    loadingSessions.value = false
  }
}

function resetFilters() {
  search.value = ''
  modeFilter.value = ''
  fetchSessions()
}

async function copyText(text: string, tip = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    message.success(tip)
    return
  } catch {
    // HTTP / 嵌入式 WebView 等非安全上下文无法使用 Clipboard API 时，
    // 回退到浏览器仍支持的选区复制。
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    if (ok) message.success(tip)
    else message.error('复制失败')
  } catch {
    message.error('复制失败')
  }
}

const sessionColumns: DataTableColumns<SessionSummary> = [
  {
    title: '会话标题',
    key: 'title',
    width: 340,
    ellipsis: { tooltip: true },
    render: (row) =>
      h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
        h('span', { style: 'font-weight:500' }, row.title),
        h('div', { style: 'display:flex;align-items:center;gap:4px' }, [
          h('span', { class: 'mono dim' }, row.session_id),
          h(
            NButton,
            {
              quaternary: true,
              circle: true,
              size: 'tiny',
              onClick: () => copyText(row.session_id, '已复制 session_id'),
            },
            { icon: () => h(NIcon, { component: CopyOutline }) },
          ),
        ]),
      ]),
  },
  {
    title: '用户',
    key: 'user_name',
    width: 180,
    ellipsis: { tooltip: true },
    render: (row) =>
      h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
        h('span', {}, row.user_name || '—'),
        h('span', { class: 'mono dim' }, row.user_id),
      ]),
  },
  {
    title: '执行模式',
    key: 'execution_mode',
    width: 156,
    align: 'center',
    render: (row) => {
      const mode = executionModeOf(row)
      return h(NTag, { size: 'small', type: mode.type, bordered: false }, { default: () => mode.label })
    },
  },
  {
    title: '消息数',
    key: 'message_count',
    width: 90,
    align: 'center',
    sorter: (a, b) => a.message_count - b.message_count,
  },
  {
    title: '最近活跃',
    key: 'last_message_at',
    width: 180,
    sorter: (a, b) =>
      new Date(a.last_message_at || 0).getTime() - new Date(b.last_message_at || 0).getTime(),
    render: (row) => fmtDateTime(row.last_message_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    align: 'center',
    render: (row) =>
      h(NButton, { size: 'small', tertiary: true, onClick: () => openEvents(row) },
        { default: () => '排查' }),
  },
]

// ===== 抽屉（日志 / Trace 两个 Tab） =====
const drawerShow = ref(false)
const activeSession = ref<SessionSummary | null>(null)
const drawerTab = ref<'logs' | 'traces' | 'report'>('logs')
const includeArchives = ref(false)
const logDir = ref('')

// --- 运行报告 ---
const report = ref<SessionReport | null>(null)
const loadingReport = ref(false)
const exporting = ref(false)
const exportingList = ref(false)

const reportModelColumns = [
  { title: '模型', key: 'model' },
  { title: '调用', key: 'calls' },
  { title: 'tokens', key: 'tokens' },
  { title: '错误', key: 'errors' },
]
const reportToolColumns = [
  { title: '工具', key: 'tool' },
  { title: '次数', key: 'count' },
]
const reportSkillColumns = [
  { title: '技能', key: 'skill' },
  { title: '次数', key: 'count' },
]
const reportErrorColumns = [
  { title: '节点', key: 'name', width: 160 },
  { title: '错误信息', key: 'message', ellipsis: { tooltip: true } },
  { title: '时间', key: 'time', width: 120, render: (r: { time: string }) => fmtTime(r.time) },
]

// --- 日志时间线 ---
const events = ref<SessionLogEvent[]>([])
const loadingEvents = ref(false)
const activeCategories = ref<string[]>(['semantic'])
const activeLevels = ref<string[]>([])
const innerSearch = ref('')
const revealSensitive = ref(false)
const tailMode = ref(false)
const timelineBox = ref<HTMLElement | null>(null)

const levelOptions = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((l) => ({
  label: l,
  value: l,
}))

const categoryMeta: Record<string, { label: string; icon: any }> = {
  semantic: { label: '语义事件', icon: SparklesOutline },
  sql: { label: 'SQL', icon: ServerOutline },
  system: { label: '系统', icon: CogOutline },
}

// --- Trace 调用链 ---
const traces = ref<TraceSummary[]>([])
const loadingTraces = ref(false)
const waterfallShow = ref(false)
const loadingWaterfall = ref(false)
const waterfallTraceId = ref('')
const waterfallRows = ref<{ node: SpanNode; depth: number }[]>([])
const waterfallTotalNs = ref(1)
const waterfallStartNs = ref(0)
const expandedSpans = ref<Set<string>>(new Set())

function confirmDialog(title: string, content: string): Promise<boolean> {
  return new Promise((resolve) => {
    let done = false
    const finish = (v: boolean) => {
      if (!done) {
        done = true
        resolve(v)
      }
    }
    dialog.warning({
      title,
      content,
      positiveText: '确认继续',
      negativeText: '取消',
      onPositiveClick: () => finish(true),
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

async function onToggleCategory(cat: string, checked: boolean) {
  if (cat === 'sql' && checked) {
    const ok = await confirmDialog(
      '查看 SQL 日志',
      'SQL 日志的绑定参数可能包含用户聊天内容，默认已脱敏。查看与揭示动作会被审计记录（操作者 / 时间 / 会话）。确认纳入 SQL 日志？',
    )
    if (!ok) return
  }
  const set = new Set(activeCategories.value)
  if (checked) set.add(cat)
  else set.delete(cat)
  activeCategories.value = [...set]
  if (!activeCategories.value.includes('sql') && revealSensitive.value) {
    revealSensitive.value = false
  }
  fetchEvents()
}

async function onToggleReveal(checked: boolean) {
  if (checked) {
    const ok = await confirmDialog(
      '揭示敏感原文',
      '将显示 SQL 绑定参数中的原始内容（可能含用户聊天明文）。该动作会被审计记录。确认揭示？',
    )
    if (!ok) return
  }
  revealSensitive.value = checked
  fetchEvents()
}

async function openEvents(session: SessionSummary) {
  activeSession.value = session
  drawerShow.value = true
  drawerTab.value = 'logs'
  await Promise.all([fetchEvents(), fetchTraces()])
}

function onTabChange(tab: string) {
  drawerTab.value = tab as 'logs' | 'traces' | 'report'
  if (tab === 'report' && !report.value && !loadingReport.value) {
    fetchReport()
  }
}

async function fetchReport() {
  if (!activeSession.value) return
  loadingReport.value = true
  try {
    report.value = await adminSessionLogsApi.getReport(activeSession.value.session_id, {
      include_archives: includeArchives.value,
    })
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载运行报告失败')
  } finally {
    loadingReport.value = false
  }
}

async function exportEvents(format: 'json' | 'csv') {
  if (!activeSession.value) return
  exporting.value = true
  try {
    const blob = await adminSessionLogsApi.exportEvents(activeSession.value.session_id, {
      format,
      categories: activeCategories.value.join(',') || undefined,
      levels: activeLevels.value.join(',') || undefined,
      search: innerSearch.value.trim() || undefined,
      include_archives: includeArchives.value,
      limit: 2000,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${activeSession.value.session_id.slice(0, 8)}.${format}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    message.success(`已导出 ${format.toUpperCase()}`)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function exportSessionsCsv() {
  if (!sessions.value.length) {
    message.warning('当前没有可导出的会话')
    return
  }
  exportingList.value = true
  try {
    const header = ['会话标题', 'session_id', '用户', 'user_id', '模式', '状态', '消息数', 'tokens', '最近活跃']
    const rows = sessions.value.map((s) => [
      s.title,
      s.session_id,
      s.user_name || '',
      s.user_id,
      s.mode === 'studio' ? 'AI 工作台' : '对话',
      s.status,
      s.message_count,
      s.total_tokens,
      fmtDateTime(s.last_message_at),
    ])
    const csv = [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `sessions_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    message.success(`已导出 ${sessions.value.length} 条会话`)
  } catch {
    message.error('导出失败')
  } finally {
    exportingList.value = false
  }
}

async function fetchEvents() {
  if (!activeSession.value) return
  loadingEvents.value = true
  try {
    const res = await adminSessionLogsApi.getEvents(activeSession.value.session_id, {
      categories: activeCategories.value.join(',') || undefined,
      levels: activeLevels.value.join(',') || undefined,
      search: innerSearch.value.trim() || undefined,
      reveal_sensitive: revealSensitive.value,
      include_archives: includeArchives.value,
      limit: 1000,
    })
    events.value = res.events
    logDir.value = res.log_dir
    if (tailMode.value) {
      await nextTick()
      scrollBottom()
    }
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载会话日志失败')
  } finally {
    loadingEvents.value = false
  }
}

async function fetchTraces() {
  if (!activeSession.value) return
  loadingTraces.value = true
  try {
    const res = await adminSessionLogsApi.getTraces(activeSession.value.session_id, {
      include_archives: includeArchives.value,
      limit: 100,
    })
    traces.value = res.traces
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载调用链失败')
  } finally {
    loadingTraces.value = false
  }
}

function flattenTree(nodes: SpanNode[], depth: number, out: { node: SpanNode; depth: number }[]) {
  for (const n of nodes) {
    out.push({ node: n, depth })
    if (n.children?.length) flattenTree(n.children, depth + 1, out)
  }
}

async function openWaterfall(traceId: string) {
  waterfallTraceId.value = traceId
  waterfallShow.value = true
  loadingWaterfall.value = true
  expandedSpans.value = new Set()
  try {
    const res = await adminSessionLogsApi.getTraceDetail(traceId, {
      include_archives: includeArchives.value,
    })
    const rows: { node: SpanNode; depth: number }[] = []
    flattenTree(res.tree, 0, rows)
    waterfallRows.value = rows
    const starts = rows.map((r) => r.node.start_ns || 0)
    const ends = rows.map((r) => (r.node.start_ns || 0) + (r.node.duration_ms || 0) * 1e6)
    const minStart = Math.min(...starts)
    const maxEnd = Math.max(...ends)
    waterfallStartNs.value = minStart
    waterfallTotalNs.value = Math.max(maxEnd - minStart, 1)
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载 Trace 详情失败')
  } finally {
    loadingWaterfall.value = false
  }
}

function barLeft(node: SpanNode): string {
  return `${(((node.start_ns || 0) - waterfallStartNs.value) / waterfallTotalNs.value) * 100}%`
}

function barWidth(node: SpanNode): string {
  const pct = ((node.duration_ms || 0) * 1e6 / waterfallTotalNs.value) * 100
  return `${Math.max(pct, 0.6)}%`
}

function toggleSpan(spanId: string) {
  const s = new Set(expandedSpans.value)
  if (s.has(spanId)) s.delete(spanId)
  else s.add(spanId)
  expandedSpans.value = s
}

function scrollBottom() {
  const el = timelineBox.value
  if (el) el.scrollTop = el.scrollHeight
}

// ===== 展示辅助 =====
function pad(n: number, w = 2): string {
  return String(n).padStart(w, '0')
}

function fmtDateTime(s: string | null): string {
  return s ? new Date(s).toLocaleString('zh-CN') : '—'
}

function fmtTime(s: string): string {
  if (!s) return ''
  const d = new Date(s)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function fmtDur(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`
  return `${ms.toFixed(1)}ms`
}

function levelType(level: string): 'error' | 'warning' | 'default' {
  const lv = (level || '').toUpperCase()
  if (lv === 'ERROR' || lv === 'CRITICAL') return 'error'
  if (lv === 'WARNING') return 'warning'
  return 'default'
}

const eventMeta: Record<string, { label: string; icon: any; color: string }> = {
  'ai.chat': { label: 'AI 调用', icon: SparklesOutline, color: 'var(--kimi-chart-4)' },
  'ai.embedding': { label: 'AI 向量', icon: SparklesOutline, color: 'var(--kimi-chart-4)' },
  'mcp.call_tool': { label: 'MCP 工具', icon: GitNetworkOutline, color: 'var(--kimi-chart-1)' },
  'mcp.sandbox.call_tool': { label: '工作台 MCP', icon: GitNetworkOutline, color: 'var(--kimi-chart-1)' },
  'skill.execute': { label: '技能执行', icon: ConstructOutline, color: 'var(--kimi-chart-6)' },
  'agent.run': { label: 'Agent 编排', icon: FlashOutline, color: 'var(--kimi-chart-5)' },
  'agent.tool_dispatch': { label: '工具分发', icon: FlashOutline, color: 'var(--kimi-chart-5)' },
}

function metaOf(ev: string | null) {
  return (
    (ev && eventMeta[ev]) || { label: ev || '日志', icon: DocumentTextOutline, color: 'var(--neutral-text-3)' }
  )
}

function spanColor(node: SpanNode): string {
  if ((node.status_code || '') === 'ERROR') return 'var(--arco-danger)'
  return metaOf(node.name)?.color || 'var(--neutral-text-3)'
}

function perfOf(msg: string): string | null {
  const m = /generated in ([\d.]+\s*s)/.exec(msg)
  return m ? m[1] : null
}

function dataEntries(data: Record<string, unknown>): [string, string][] {
  return Object.entries(data || {}).map(([k, v]) => [k, stringify(v)])
}

function stringify(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function copyEvent(ev: SessionLogEvent) {
  copyText(JSON.stringify(ev, null, 2), '已复制该条日志')
}

onMounted(fetchSessions)

// ===== 页面级 Tabs：会话日志 / 用户会话反馈 =====
const pageTab = ref<'logs' | 'feedback'>('logs')

// ===== 用户会话反馈 =====
const feedbacks = ref<SessionFeedback[]>([])
const feedbackTotal = ref(0)
const loadingFeedbacks = ref(false)
const feedbackRating = ref<string>('')
const feedbackSearch = ref('')

const feedbackRatingOptions = [
  { label: '全部评价', value: '' },
  { label: '仅点踩（需优化）', value: 'dislike' },
  { label: '仅点赞', value: 'like' },
]

async function fetchFeedbacks() {
  loadingFeedbacks.value = true
  try {
    const res = await adminSessionLogsApi.listFeedbacks({
      rating: (feedbackRating.value || undefined) as 'like' | 'dislike' | undefined,
      search: feedbackSearch.value.trim() || undefined,
      limit: 100,
    })
    feedbacks.value = res.items
    feedbackTotal.value = res.total
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载用户反馈失败')
  } finally {
    loadingFeedbacks.value = false
  }
}

function onPageTabChange(tab: string) {
  pageTab.value = tab as 'logs' | 'feedback'
  if (tab === 'feedback') fetchFeedbacks()
}

function resetFeedbackFilters() {
  feedbackRating.value = ''
  feedbackSearch.value = ''
  fetchFeedbacks()
}

/** 从反馈行跳转到该会话的日志排查抽屉 */
function investigateFromFeedback(row: SessionFeedback) {
  openEvents({
    session_id: row.session_id,
    user_id: row.user_id,
    user_name: row.user_name,
    title: row.session_title || row.session_id,
    mode: '',
    execution_mode: row.execution_mode,
    agent_id: null,
    assistant_id: null,
    status: '',
    message_count: 0,
    total_tokens: 0,
    last_message_at: row.created_at,
  })
}

function feedbackContextLines(row: SessionFeedback): Array<{ label: string; value: string }> {
  const ctx = row.context || {}
  const hint = ctx.execution_hint || {}
  const lines: Array<{ label: string; value: string }> = []
  if (ctx.user_question_excerpt) lines.push({ label: '用户提问', value: ctx.user_question_excerpt })
  if (ctx.message_excerpt) lines.push({ label: 'AI 回复摘录', value: ctx.message_excerpt })
  if (row.comment) lines.push({ label: '用户备注', value: row.comment })
  const agentBits = [
    ctx.model ? `模型: ${ctx.model}` : '',
    hint.agent_id ? `Agent: ${hint.agent_id}` : '',
    hint.assistant_id ? `助手: ${hint.assistant_id}` : '',
    hint.sender_agent ? `发言专家: ${String((hint.sender_agent as any)?.name || hint.sender_agent)}` : '',
    hint.overdrive ? '超频编排: 是' : '',
  ].filter(Boolean)
  if (agentBits.length) lines.push({ label: '执行信息', value: agentBits.join(' · ') })
  return lines
}

const feedbackColumns: DataTableColumns<SessionFeedback> = [
  {
    title: '评价',
    key: 'rating',
    width: 90,
    align: 'center',
    render: (row) =>
      h(
        NTag,
        {
          size: 'small',
          type: row.rating === 'dislike' ? 'error' : 'success',
          bordered: false,
        },
        {
          icon: () => h(NIcon, { component: row.rating === 'dislike' ? ThumbsDownOutline : ThumbsUpOutline }),
          default: () => (row.rating === 'dislike' ? '点踩' : '点赞'),
        },
      ),
  },
  {
    title: '用户',
    key: 'user_name',
    width: 140,
    ellipsis: { tooltip: true },
    render: (row) => row.user_name || row.user_id,
  },
  {
    title: '会话',
    key: 'session_title',
    width: 220,
    ellipsis: { tooltip: true },
    render: (row) =>
      h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
        h('span', { style: 'font-weight:500' }, row.session_title || '—'),
        h('span', { class: 'mono dim' }, row.session_id),
      ]),
  },
  {
    title: '问题 / 回复摘录',
    key: 'context',
    minWidth: 260,
    ellipsis: { tooltip: true },
    render: (row) => {
      const q = row.context?.user_question_excerpt || ''
      const a = row.context?.message_excerpt || ''
      return h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
        q ? h('span', {}, `问：${q.slice(0, 80)}${q.length > 80 ? '…' : ''}`) : null,
        a ? h('span', { class: 'dim' }, `答：${a.slice(0, 80)}${a.length > 80 ? '…' : ''}`) : null,
        !q && !a ? h('span', { class: 'dim' }, '—') : null,
      ])
    },
  },
  {
    title: '备注',
    key: 'comment',
    width: 160,
    ellipsis: { tooltip: true },
    render: (row) => row.comment || '—',
  },
  {
    title: '时间',
    key: 'created_at',
    width: 170,
    render: (row) => fmtDateTime(row.created_at),
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    align: 'center',
    render: (row) =>
      h(NButton, { size: 'small', tertiary: true, onClick: () => investigateFromFeedback(row) },
        { default: () => '排查会话' }),
  },
]
</script>

<template>
  <div class="session-logs">
    <PageHeader
      title="会话日志排查"
      subtitle="按对话、AI 工作台、超频模式聚合可观测日志与调用链，避免多 Agent 协作被误归为普通会话"
    >
      <template #actions>
        <NButton secondary :loading="exportingList" @click="exportSessionsCsv">
          <template #icon><NIcon :component="DownloadOutline" /></template>
          导出会话 CSV
        </NButton>
      </template>
    </PageHeader>

    <NTabs :value="pageTab" type="line" class="page-tabs" @update:value="onPageTabChange">
      <NTabPane name="logs" tab="会话日志">
        <section class="mode-guide" aria-label="AI 助手执行模式说明">
          <div class="mode-guide-item mode-guide-item--chat">
            <NIcon :component="SparklesOutline" aria-hidden="true" />
            <div><strong>对话</strong><span>单助手直接响应，适合问答与轻量协助。</span></div>
          </div>
          <div class="mode-guide-item mode-guide-item--studio">
            <NIcon :component="ConstructOutline" aria-hidden="true" />
            <div><strong>AI 工作台</strong><span>面向文件、工具与可追踪任务执行。</span></div>
          </div>
          <div class="mode-guide-item mode-guide-item--overdrive">
            <NIcon :component="FlashOutline" aria-hidden="true" />
            <div><strong>超频模式</strong><span>由 Manager 调度多个专家协作完成复杂任务。</span></div>
          </div>
        </section>

        <NCard size="small" class="filter-bar">
          <NSpace align="center" :wrap="false">
            <NInput
              v-model:value="search"
              placeholder="搜索 session_id / 标题 / 用户"
              clearable
              style="width: 280px"
              @keyup.enter="fetchSessions"
            >
              <template #prefix><NIcon :component="SearchOutline" /></template>
            </NInput>
            <NSelect
              v-model:value="modeFilter"
              :options="modeOptions"
              style="width: 200px"
              @update:value="fetchSessions"
            />
            <NButton type="primary" :loading="loadingSessions" @click="fetchSessions">查询</NButton>
            <NButton @click="resetFilters">重置</NButton>
          </NSpace>
        </NCard>

        <NCard size="small" class="table-card">
          <template #header>
            <span class="card-title">会话列表</span>
          </template>
          <template #header-extra>
            <span class="card-count">共 {{ sessions.length }} 条</span>
          </template>
          <NDataTable
            :columns="sessionColumns"
            :data="sessions"
            :loading="loadingSessions"
            :pagination="{ pageSize: 20 }"
            :scroll-x="1000"
            size="small"
          />
        </NCard>
      </NTabPane>

      <NTabPane name="feedback" tab="用户会话反馈">
        <NCard size="small" class="filter-bar">
          <NSpace align="center" :wrap="false">
            <NInput
              v-model:value="feedbackSearch"
              placeholder="搜索 session_id / 标题 / 用户 / 备注"
              clearable
              style="width: 280px"
              @keyup.enter="fetchFeedbacks"
            >
              <template #prefix><NIcon :component="SearchOutline" /></template>
            </NInput>
            <NSelect
              v-model:value="feedbackRating"
              :options="feedbackRatingOptions"
              style="width: 200px"
              @update:value="fetchFeedbacks"
            />
            <NButton type="primary" :loading="loadingFeedbacks" @click="fetchFeedbacks">查询</NButton>
            <NButton @click="resetFeedbackFilters">重置</NButton>
          </NSpace>
        </NCard>

        <NCard size="small" class="table-card">
          <template #header>
            <span class="card-title">用户会话反馈</span>
          </template>
          <template #header-extra>
            <span class="card-count">
              共 {{ feedbackTotal }} 条 · 点踩自动快照模型 / Agent / 问答上下文，用于提示词与架构优化
            </span>
          </template>
          <NDataTable
            :columns="feedbackColumns"
            :data="feedbacks"
            :loading="loadingFeedbacks"
            :pagination="{ pageSize: 20 }"
            :scroll-x="1140"
            :row-key="(row: SessionFeedback) => row.feedback_id"
            :render-expand="(row: SessionFeedback) => h('div', { class: 'feedback-expand' }, feedbackContextLines(row).map((line) => h('div', { class: 'feedback-expand-line' }, [h('span', { class: 'feedback-expand-label' }, `${line.label}：`), h('span', {}, line.value)])))"
            size="small"
          />
          <NEmpty
            v-if="!loadingFeedbacks && !feedbacks.length"
            description="暂无用户反馈；用户在 AI 回复下点赞 / 点踩后会汇聚到这里"
            style="margin-top: 24px"
          />
        </NCard>
      </NTabPane>
    </NTabs>

    <!-- 会话排查抽屉 -->
    <NDrawer v-model:show="drawerShow" :width="640" placement="right" resizable>
      <NDrawerContent closable>
        <template #header>
          <div class="drawer-head">
            <div class="drawer-title">{{ activeSession?.title || '会话排查' }}</div>
            <div class="drawer-meta">
              <NTag v-if="activeSession" size="small" :type="executionModeOf(activeSession).type" :bordered="false">
                {{ executionModeOf(activeSession).label }}
              </NTag>
              <span class="drawer-sub mono">{{ activeSession?.session_id }}</span>
            </div>
          </div>
        </template>

        <NTabs :value="drawerTab" type="line" @update:value="onTabChange">
          <!-- 日志时间线 -->
          <NTabPane name="logs" tab="日志时间线">
            <div class="filters">
              <NInput
                v-model:value="innerSearch"
                placeholder="会话内搜索（消息 / 数据）"
                clearable
                size="small"
                @keyup.enter="fetchEvents"
              >
                <template #prefix><NIcon :component="SearchOutline" /></template>
              </NInput>
              <div class="filter-row">
                <span class="filter-label">类型</span>
                <NTag
                  v-for="cat in ['semantic', 'sql', 'system']"
                  :key="cat"
                  size="small"
                  checkable
                  :checked="activeCategories.includes(cat)"
                  @update:checked="(v: boolean) => onToggleCategory(cat, v)"
                >
                  <template #icon><NIcon :component="categoryMeta[cat].icon" /></template>
                  {{ categoryMeta[cat].label }}
                </NTag>
              </div>
              <div class="filter-row">
                <span class="filter-label">级别</span>
                <NSelect
                  v-model:value="activeLevels"
                  :options="levelOptions"
                  multiple
                  clearable
                  size="small"
                  placeholder="全部级别"
                  style="flex: 1; min-width: 220px"
                  @update:value="fetchEvents"
                />
              </div>
              <div class="filter-row toggles">
                <NCheckbox v-model:checked="includeArchives" @update:checked="fetchEvents">
                  包含轮转归档
                </NCheckbox>
                <NCheckbox v-model:checked="tailMode">Tail 置底</NCheckbox>
                <NCheckbox
                  v-if="activeCategories.includes('sql')"
                  :checked="revealSensitive"
                  @update:checked="(v: boolean) => onToggleReveal(v)"
                >
                  揭示 SQL 敏感原文
                </NCheckbox>
                <NButton size="small" :loading="loadingEvents" @click="fetchEvents">
                  <template #icon><NIcon :component="RefreshOutline" /></template>
                  刷新
                </NButton>
                <NButton size="small" :loading="exporting" @click="exportEvents('json')">
                  <template #icon><NIcon :component="DownloadOutline" /></template>
                  导出 JSON
                </NButton>
                <NButton size="small" :loading="exporting" @click="exportEvents('csv')">
                  <template #icon><NIcon :component="DownloadOutline" /></template>
                  导出 CSV
                </NButton>
              </div>
              <div v-if="revealSensitive" class="audit-note">已揭示敏感原文 — 本次查看已被审计记录。</div>
            </div>

            <NSpin v-if="loadingEvents" size="small" style="margin-top: 24px" />
            <div v-else-if="events.length" ref="timelineBox" class="timeline-box">
              <NTimeline class="timeline">
                <NTimelineItem
                  v-for="(ev, i) in events"
                  :key="i"
                  :type="levelType(ev.level)"
                  :time="fmtTime(ev.timestamp)"
                >
                  <template #icon>
                    <NIcon :component="metaOf(ev.event).icon" :color="metaOf(ev.event).color" />
                  </template>
                  <div class="ev-row" :class="{ 'ev-row--error': levelType(ev.level) === 'error' }">
                    <div class="ev-top">
                      <NTag
                        size="tiny"
                        :bordered="false"
                        :color="{
                          color: `color-mix(in srgb, ${metaOf(ev.event).color} 12%, transparent)`,
                          textColor: metaOf(ev.event).color,
                        }"
                      >
                        {{ metaOf(ev.event).label }}
                      </NTag>
                      <NTag v-if="ev.category !== 'semantic'" size="tiny" :bordered="false">
                        {{ categoryMeta[ev.category]?.label || ev.category }}
                      </NTag>
                      <span class="ev-level" :class="'lv-' + levelType(ev.level)">{{ ev.level }}</span>
                      <span v-if="ev.event" class="ev-name mono">{{ ev.event }}</span>
                      <NTag v-if="perfOf(ev.message)" size="tiny" type="success" :bordered="false">
                        {{ perfOf(ev.message) }}
                      </NTag>
                      <NTooltip trigger="hover">
                        <template #trigger>
                          <NButton quaternary circle size="tiny" @click="copyEvent(ev)">
                            <template #icon><NIcon :component="CopyOutline" /></template>
                          </NButton>
                        </template>
                        复制该条日志 JSON
                      </NTooltip>
                    </div>
                    <div
                      v-if="ev.message"
                      class="ev-msg"
                      :class="{ 'ev-msg--sql': ev.category === 'sql', 'ev-msg--redacted': ev.redacted }"
                    >
                      {{ ev.message }}
                    </div>
                    <div v-if="dataEntries(ev.data).length" class="ev-data">
                      <div v-for="[k, v] in dataEntries(ev.data)" :key="k" class="ev-kv">
                        <span class="ev-k">{{ k }}</span>
                        <span class="ev-v mono">{{ v }}</span>
                      </div>
                    </div>
                    <div v-if="ev.trace_id" class="ev-trace mono">trace: {{ ev.trace_id }}</div>
                  </div>
                </NTimelineItem>
              </NTimeline>
            </div>
            <NEmpty v-else description="当前过滤条件下暂无日志" style="margin-top: 48px">
              <template #extra>
                <span class="empty-hint">默认仅显示语义事件；可勾选 SQL / 系统类别扩大范围。</span>
                <br />
                <span class="empty-hint mono">日志目录：{{ logDir }}</span>
              </template>
            </NEmpty>
          </NTabPane>

          <!-- Trace 调用链 -->
          <NTabPane name="traces" tab="Trace 调用链">
            <div class="filter-row toggles" style="margin-bottom: 12px">
              <span class="trace-count">共 {{ traces.length }} 条调用链</span>
              <NButton size="small" :loading="loadingTraces" @click="fetchTraces">
                <template #icon><NIcon :component="RefreshOutline" /></template>
                刷新
              </NButton>
            </div>
            <NSpin v-if="loadingTraces" size="small" style="margin-top: 24px" />
            <div v-else-if="traces.length" class="trace-list">
              <div v-for="t in traces" :key="t.trace_id" class="trace-item" @click="openWaterfall(t.trace_id)">
                <div class="trace-item-main">
                  <NTag size="small" :type="t.has_error ? 'error' : 'success'" :bordered="false">
                    {{ t.has_error ? 'ERROR' : 'OK' }}
                  </NTag>
                  <span class="trace-root">{{ t.root_name || '(trace)' }}</span>
                  <span class="trace-meta">{{ t.span_count }} spans · {{ fmtDur(t.duration_ms) }}</span>
                </div>
                <div class="trace-item-sub">
                  <span class="mono dim">{{ t.trace_id }}</span>
                  <span class="dim">{{ fmtDateTime(t.start_time) }}</span>
                </div>
              </div>
            </div>
            <NEmpty v-else description="该会话暂无调用链" style="margin-top: 48px">
              <template #extra>
                <span class="empty-hint">仅记录 span 持久化启用后产生的 AI/Agent 调用；该会话可能早于启用时间，或期间未发生 AI 调用。</span>
              </template>
            </NEmpty>
          </NTabPane>

          <!-- 运行报告 -->
          <NTabPane name="report" tab="运行报告">
            <div class="filters">
              <div class="filter-row toggles">
                <NCheckbox v-model:checked="includeArchives" @update:checked="fetchReport">
                  包含轮转归档
                </NCheckbox>
                <NButton size="small" :loading="loadingReport" @click="fetchReport">
                  <template #icon><NIcon :component="RefreshOutline" /></template>
                  刷新
                </NButton>
              </div>
            </div>
            <NSpin v-if="loadingReport" size="small" style="margin-top: 24px" />
            <div v-else-if="report" class="report">
              <NGrid :x-gap="10" :y-gap="10" :cols="4" responsive="screen" item-responsive>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="Trace 数" :value="report.summary.trace_count" /></NCard></NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="Span 数" :value="report.summary.span_count" /></NCard></NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="AI 调用" :value="report.summary.ai_calls" /></NCard></NGi>
                <NGi span="2 m:1">
                  <NCard size="small">
                    <NStatistic label="错误数">
                      <template #default>
                        <span :style="{ color: report.summary.error_count ? 'var(--arco-danger)' : undefined }">
                          {{ report.summary.error_count }}
                        </span>
                      </template>
                    </NStatistic>
                  </NCard>
                </NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="总 tokens" :value="report.summary.total_tokens" /></NCard></NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="成本（🥫）" :value="report.summary.cost_cookie" /></NCard></NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="AI 耗时" :value="fmtDur(report.summary.ai_duration_ms)" /></NCard></NGi>
                <NGi span="2 m:1"><NCard size="small"><NStatistic label="墙钟耗时" :value="fmtDur(report.summary.wall_duration_ms)" /></NCard></NGi>
              </NGrid>

              <NCard size="small" title="模型用量" class="report-block">
                <NDataTable :columns="reportModelColumns" :data="report.models" :bordered="false" size="small" :row-key="(r) => r.model" />
                <NEmpty v-if="!report.models.length" description="无 AI 调用" size="small" />
              </NCard>

              <NGrid :x-gap="10" :cols="2" responsive="screen" item-responsive class="report-block">
                <NGi span="2 m:1">
                  <NCard size="small" title="工具调用">
                    <NDataTable :columns="reportToolColumns" :data="report.tool_calls" :bordered="false" size="small" :row-key="(r) => r.tool" />
                    <NEmpty v-if="!report.tool_calls.length" description="无工具调用" size="small" />
                  </NCard>
                </NGi>
                <NGi span="2 m:1">
                  <NCard size="small" title="技能调用">
                    <NDataTable :columns="reportSkillColumns" :data="report.skill_calls" :bordered="false" size="small" :row-key="(r) => r.skill" />
                    <NEmpty v-if="!report.skill_calls.length" description="无技能调用" size="small" />
                  </NCard>
                </NGi>
              </NGrid>

              <NCard size="small" title="错误摘要" class="report-block">
                <NDataTable :columns="reportErrorColumns" :data="report.errors" :bordered="false" size="small" :row-key="(r) => r.name + r.time" />
                <NEmpty v-if="!report.errors.length" description="无错误" size="small" />
              </NCard>
            </div>
            <NEmpty v-else description="暂无运行报告数据" style="margin-top: 48px" />
          </NTabPane>
        </NTabs>
      </NDrawerContent>
    </NDrawer>

    <!-- 瀑布图抽屉 -->
    <NDrawer v-model:show="waterfallShow" :width="720" placement="right" resizable>
      <NDrawerContent title="Trace 瀑布图" closable>
        <template #header>
          <div class="drawer-head">
            <div class="drawer-title">Trace 瀑布图</div>
            <div class="drawer-sub mono">{{ waterfallTraceId }}</div>
          </div>
        </template>
        <NSpin v-if="loadingWaterfall" size="small" style="margin-top: 24px" />
        <div v-else-if="waterfallRows.length" class="waterfall">
          <div class="wf-header">
            <span>Span</span>
            <span class="wf-header-bar">时间轴（相对 Trace 起点，总时长 {{ fmtDur(waterfallTotalNs / 1e6) }}）</span>
          </div>
          <div v-for="row in waterfallRows" :key="row.node.span_id" class="wf-row-wrap">
            <div class="wf-row" @click="toggleSpan(row.node.span_id)">
              <div class="wf-name" :style="{ paddingLeft: row.depth * 16 + 'px' }">
                <NIcon :component="metaOf(row.node.name).icon" :color="spanColor(row.node)" />
                <span class="wf-span-name" :class="{ 'wf-err': row.node.status_code === 'ERROR' }">
                  {{ row.node.name }}
                </span>
                <span class="wf-dur">{{ fmtDur(row.node.duration_ms) }}</span>
              </div>
              <div class="wf-bar-track">
                <div
                  class="wf-bar"
                  :style="{ left: barLeft(row.node), width: barWidth(row.node), background: spanColor(row.node) }"
                />
              </div>
            </div>
            <div v-if="expandedSpans.has(row.node.span_id)" class="wf-detail">
              <div v-if="row.node.status_message" class="ev-kv">
                <span class="ev-k">status</span>
                <span class="ev-v mono">{{ row.node.status_message }}</span>
              </div>
              <div v-for="[k, v] in dataEntries(row.node.attributes)" :key="k" class="ev-kv">
                <span class="ev-k">{{ k }}</span>
                <span class="ev-v mono">{{ v }}</span>
              </div>
              <div v-for="(ev, i) in row.node.events" :key="'e' + i" class="ev-kv">
                <span class="ev-k">event:{{ ev.name }}</span>
                <span class="ev-v mono">{{ stringify(ev.attributes) }}</span>
              </div>
              <div class="ev-kv">
                <span class="ev-k">span_id</span>
                <span class="ev-v mono">{{ row.node.span_id }}</span>
              </div>
            </div>
          </div>
        </div>
        <NEmpty v-else description="该 Trace 无 span 数据" style="margin-top: 48px" />
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.session-logs { display: flex; flex-direction: column; gap: var(--space-xl); }

.page-tabs :deep(.n-tab-pane) {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding-top: var(--space-md);
}

.feedback-expand { display: flex; flex-direction: column; gap: 6px; padding: 10px 18px; }
.feedback-expand-line {
  display: flex;
  gap: 4px;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}
.feedback-expand-label { flex-shrink: 0; color: var(--text-color-3, #8a93a6); }

.filter-bar :deep(.n-card__content) { padding: var(--space-md) var(--space-lg); }
.table-card { border-radius: var(--radius-md); }
.card-title { font-size: var(--font-card-title-size); font-weight: var(--font-card-title-weight); color: var(--neutral-text-1); }
.card-count { font-size: var(--font-caption-size); color: var(--neutral-text-3); font-variant-numeric: tabular-nums; }

.mode-guide { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-md); }
.mode-guide-item {
  display: flex; gap: 10px; align-items: flex-start; min-width: 0; padding: 12px 14px;
  border: 1px solid var(--neutral-border); border-radius: var(--radius-md); background: var(--neutral-card);
}
.mode-guide-item :deep(.n-icon) { flex: 0 0 auto; margin-top: 2px; font-size: 18px; }
.mode-guide-item div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mode-guide-item strong { font-size: var(--font-small-size); color: var(--neutral-text-1); }
.mode-guide-item span { font-size: var(--font-caption-size); line-height: 1.5; color: var(--neutral-text-3); }
.mode-guide-item--chat :deep(.n-icon) { color: var(--kimi-chart-4); }
.mode-guide-item--studio :deep(.n-icon) { color: var(--kimi-chart-1); }
.mode-guide-item--overdrive { border-color: color-mix(in srgb, var(--arco-warning) 38%, var(--neutral-border)); }
.mode-guide-item--overdrive :deep(.n-icon) { color: var(--arco-warning); }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dim { font-size: var(--font-caption-size); color: var(--neutral-text-3); }

.drawer-head { display: flex; flex-direction: column; gap: 4px; }
.drawer-title { font-size: 15px; font-weight: 600; color: var(--neutral-text-1); }
.drawer-meta { display: flex; align-items: center; gap: var(--space-sm); min-width: 0; }
.drawer-sub { font-size: var(--font-caption-size); color: var(--neutral-text-3); }

.filters { display: flex; flex-direction: column; gap: var(--space-md); margin-bottom: var(--space-lg); }
.filter-row { display: flex; align-items: center; gap: var(--space-sm); flex-wrap: wrap; }
.filter-row.toggles { gap: var(--space-lg); }
.filter-label { font-size: var(--font-caption-size); color: var(--neutral-text-3); min-width: 32px; }
.audit-note {
  font-size: var(--font-caption-size);
  color: var(--arco-warning);
  background: var(--arco-warning-light);
  border: 1px solid color-mix(in srgb, var(--arco-warning) 30%, transparent);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
}

.report { display: flex; flex-direction: column; }
.report-block { margin-top: var(--space-md); }

.timeline-box { max-height: calc(100vh - 360px); overflow-y: auto; padding-right: 4px; }
.timeline { margin-top: var(--space-sm); }
.ev-row { display: flex; flex-direction: column; gap: 6px; padding: 2px 8px; border-radius: var(--radius-sm); }
.ev-row--error { background: var(--arco-danger-light); box-shadow: inset 3px 0 0 var(--arco-danger); }
.ev-top { display: flex; align-items: center; gap: var(--space-sm); flex-wrap: wrap; }
.ev-level { font-size: var(--font-micro-size); font-weight: 600; }
.lv-error { color: var(--arco-danger); }
.lv-warning { color: var(--arco-warning); }
.lv-default { color: var(--neutral-text-3); }
.ev-name { font-size: var(--font-caption-size); color: var(--neutral-text-2); }
.ev-msg { font-size: var(--font-small-size); color: var(--neutral-text-1); line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
.ev-msg--sql { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: var(--font-caption-size); }
.ev-msg--redacted { color: var(--neutral-text-3); font-style: italic; }
.ev-data {
  display: flex; flex-direction: column; gap: 2px;
  background: var(--neutral-bg);
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  padding: var(--space-sm) 10px;
}
.ev-kv { display: flex; gap: var(--space-sm); font-size: var(--font-caption-size); line-height: 1.6; }
.ev-k { color: var(--neutral-text-3); min-width: 110px; flex: 0 0 auto; }
.ev-v { color: var(--neutral-text-1); word-break: break-all; }
.ev-trace { font-size: var(--font-micro-size); color: var(--neutral-text-4); }
.empty-hint { font-size: var(--font-caption-size); color: var(--neutral-text-3); }

.trace-count { font-size: var(--font-small-size); color: var(--neutral-text-2); }
.trace-list { display: flex; flex-direction: column; gap: var(--space-sm); }
.trace-item {
  border: 1px solid var(--neutral-border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color var(--motion-quick) ease-out, background-color var(--motion-quick) ease-out;
}
.trace-item:hover { border-color: var(--arco-primary); background-color: var(--neutral-hover); }
.trace-item-main { display: flex; align-items: center; gap: 10px; }
.trace-root { font-weight: 600; font-size: var(--font-small-size); color: var(--neutral-text-1); }
.trace-meta { font-size: var(--font-caption-size); color: var(--neutral-text-3); margin-left: auto; }
.trace-item-sub { display: flex; justify-content: space-between; margin-top: 6px; }

.waterfall { display: flex; flex-direction: column; }
.wf-header { display: flex; font-size: var(--font-caption-size); color: var(--neutral-text-3); padding: 4px 0 var(--space-sm); border-bottom: 1px solid var(--neutral-border); }
.wf-header-bar { flex: 1; text-align: center; }
.wf-row-wrap { border-bottom: 1px solid var(--neutral-border); }
.wf-row { display: flex; align-items: center; gap: var(--space-md); padding: 6px 0; cursor: pointer; }
.wf-row:hover { background: var(--neutral-hover); }
.wf-name { display: flex; align-items: center; gap: 6px; width: 240px; flex: 0 0 auto; min-width: 0; }
.wf-span-name { font-size: var(--font-small-size); color: var(--neutral-text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wf-err { color: var(--arco-danger); font-weight: 600; }
.wf-dur { font-size: var(--font-micro-size); color: var(--neutral-text-3); margin-left: auto; white-space: nowrap; }
.wf-bar-track { position: relative; flex: 1; height: 14px; background: var(--neutral-bg); border-radius: 3px; }
.wf-bar { position: absolute; top: 2px; bottom: 2px; border-radius: 3px; min-width: 3px; }
.wf-detail { padding: 6px 8px 10px 24px; background: var(--neutral-bg); display: flex; flex-direction: column; gap: 2px; }

@media (max-width: 900px) {
  .mode-guide { grid-template-columns: 1fr; }
}
</style>
