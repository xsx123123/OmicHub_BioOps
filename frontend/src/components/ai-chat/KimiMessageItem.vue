<script setup lang="ts">
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import DOMPurify from 'dompurify'
import { NButton, NIcon, NTag, NDataTable, useMessage } from 'naive-ui'
import {
  DocumentOutline,
  FolderOpenOutline,
  ThumbsUpOutline,
  ThumbsDownOutline,
  CopyOutline,
} from '@vicons/ionicons5'
import { Vue3Lottie } from 'vue3-lottie'
import { useRouter } from 'vue-router'
import md, { VChart } from './setup'
import { stripFakeToolCallMarkup } from './messageSanitize'
import { usePyodide } from '@/composables/usePyodide'
import UserAvatar from '@/components/UserAvatar.vue'
import MessageActionBar from './MessageActionBar.vue'
import AiLoading from './AiLoading.vue'
import TaskProgressCard from './TaskProgressCard.vue'
import PipelineTaskCard from './PipelineTaskCard.vue'
import ExpertConsultationCard from './ExpertConsultationCard.vue'
import CollaborationRouteNotice from './CollaborationRouteNotice.vue'
import RouteTransitionCard from './RouteTransitionCard.vue'
import MessageArtifactGallery from './MessageArtifactGallery.vue'
import AgentTeamsCaseCard from './AgentTeamsCaseCard.vue'
import ChartPreviewModal from './ChartPreviewModal.vue'
import AskUserCard from './AskUserCard.vue'
import PlanConfirmationCard from './PlanConfirmationCard.vue'
import OverdriveApprovalCard from './OverdriveApprovalCard.vue'
import OverdriveProgressCard from './OverdriveProgressCard.vue'
import ToolCallEntry from './ToolCallEntry.vue'
import SkillInvocationCardView from './SkillInvocationCard.vue'
import { useAgentHubStore } from '@/stores/agentHub'
import apiClient from '@/api/client'
import { chatApi } from '@/api/chat'
import { reportChatDiagnostic } from '@/utils/chatDiagnostics'
import type {
  ChatMessage,
  CollaborationRouteInfo,
  CopyMode,
  ChartData,
  KnowledgeCitationSource,
  ToolCall,
  SkillInvocationCard,
  FileAttachment,
} from './types'

interface Props {
  message: ChatMessage
  isStreaming?: boolean
  streamingContent?: string
  streamingThought?: string
  userAvatar?: string
  /** 用户显示名 */
  userName?: string
  /** Agent 显示名 */
  agentName?: string
  /** Agent 头像/emoji */
  agentAvatar?: string
  /** Agent 主题色 */
  agentColor?: string
  modelName?: string
  sessionId?: string
}

const props = withDefaults(defineProps<Props>(), {
  isStreaming: false,
  streamingContent: '',
  streamingThought: '',
  userAvatar: '',
  userName: '我',
  agentName: 'OmicHub AI',
  agentAvatar: '🤖',
  agentColor: '#4f8ef7',
  modelName: 'AI 助手',
  sessionId: '',
})

const emit = defineEmits<{
  feedback: [messageId: string, type: 'like' | 'dislike']
  copy: [mode: CopyMode]
  regenerate: [messageId: string]
  retryWithModel: [messageId: string]
  translate: [messageId: string]
  delete: [messageId: string]
  edit: [messageId: string]
  confirmTool: [toolName: string, args: Record<string, unknown>]
  openToolPage: [route: string, args: Record<string, unknown>]
  createCaseFromConsultation: [summary: string, consultationId?: string]
  correctCollaborationRoute: [route: CollaborationRouteInfo]
}>()

const router = useRouter()
const messageApi = useMessage()
const attachmentPreviewUrls = ref<Record<string, string>>({})

function attachmentKey(attachment: FileAttachment, index: number): string {
  return attachment.file_id || attachment.url || `${attachment.name}-${index}`
}

function isImageAttachment(attachment: FileAttachment): boolean {
  return attachment.type.startsWith('image/')
}

function attachmentPreviewUrl(attachment: FileAttachment, index: number): string {
  return attachmentPreviewUrls.value[attachmentKey(attachment, index)] || ''
}

async function loadAttachmentPreview(attachment: FileAttachment, index: number): Promise<void> {
  if (!isImageAttachment(attachment) || !attachment.url) return
  const key = attachmentKey(attachment, index)
  if (attachmentPreviewUrls.value[key]) return
  try {
    const response = await apiClient.get<Blob>(attachment.url, { responseType: 'blob' })
    attachmentPreviewUrls.value[key] = URL.createObjectURL(response.data)
  } catch (error) {
    reportChatDiagnostic({
      phase: 'attachment-preview',
      messageId: props.message.id,
      contentPreview: attachment.name,
      error,
    })
  }
}

watch(
  () => props.message.attachments,
  (attachments) => {
    void Promise.all((attachments || []).map(loadAttachmentPreview))
  },
  { immediate: true, deep: true },
)

const hovered = ref(false)
const lottieRef = ref<InstanceType<typeof Vue3Lottie> | null>(null)
const thoughtExpanded = ref(false)
const workerExpanded = ref(false)
const plotlyContainers = ref<Record<string, HTMLDivElement | null>>({})
const plotlyRenderError = ref<string>('')

function extractPlotlyFigure(tool: ToolCall): Record<string, unknown> | undefined {
  // 1. 优先走专用 uiPayload 通道
  const fromUi = tool.uiPayload?.plotly_figure as Record<string, unknown> | undefined
  if (fromUi) return fromUi
  // 2. 兼容 result 里仍包着 ui_payload 的旧/异常封装
  const result = tool.result as Record<string, unknown> | undefined
  if (!result || typeof result !== 'object') return undefined
  const nestedUi = (result.ui_payload as Record<string, unknown> | undefined)
    || (result.uiPayload as Record<string, unknown> | undefined)
  if (nestedUi?.plotly_figure) return nestedUi.plotly_figure as Record<string, unknown>
  // 3. 兜底：result 直接就是 figure
  if (result.data && result.layout) return result
  return undefined
}

// 优先从工具结果的 uiPayload.plotly_figure 取图，fallback 到 message.charts
const plotlyCharts = computed(() => {
  const fromToolCalls: ChartData[] = []
  for (const tool of props.message.toolCalls || []) {
    const figure = extractPlotlyFigure(tool)
    if (figure) {
      fromToolCalls.push({
        id: `tool-plotly-${tool.id}`,
        type: 'plotly',
        option: figure,
      })
    }
  }
  const fromCharts = (props.message.charts || []).filter((c) => c.type === 'plotly')
  return [...fromToolCalls, ...fromCharts]
})

function setPlotlyContainer(chartId: string) {
  return (el: unknown) => {
    if (el) plotlyContainers.value[chartId] = el as HTMLDivElement
  }
}

async function renderPlotlyCharts() {
  if (!plotlyCharts.value.length) return
  plotlyRenderError.value = ''
  try {
    const Plotly = await import('plotly.js-dist-min')
    await nextTick()
    for (const chart of plotlyCharts.value) {
      const el = plotlyContainers.value[chart.id]
      if (!el) continue
      try {
        await Plotly.newPlot(
          el,
          (chart.option.data || []) as Plotly.Data[],
          (chart.option.layout || {}) as Partial<Plotly.Layout>,
          {
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
            // 默认 600 DPI 导出（scale = 600/96）
            toImageButtonOptions: {
              format: 'png',
              filename: 'omichub_plot_600dpi',
              scale: 6.25,
            } as Plotly.Config['toImageButtonOptions'],
          },
        )
      } catch (e) {
        el.textContent = `Plotly 渲染失败: ${e instanceof Error ? e.message : String(e)}`
      }
    }
  } catch (e) {
    plotlyRenderError.value = `Plotly 加载失败: ${e instanceof Error ? e.message : String(e)}`
  }
}

watch(() => [props.message.toolCalls, props.message.charts], renderPlotlyCharts, { deep: true })
watch(
  () => props.message.id,
  () => {
    workerExpanded.value = false
  },
)
watch(workerExpanded, (expanded) => {
  if (expanded) void nextTick(renderPlotlyCharts)
})

// 表格数据（取第一个含 table_data 的 tool result）
const tableData = computed(() => {
  const tc = props.message.toolCalls?.find(
    (t) => t.uiPayload && (t.uiPayload.table_data || t.uiPayload.tableData),
  )
  const raw = tc?.uiPayload?.table_data || tc?.uiPayload?.tableData
  if (!raw || !Array.isArray(raw) || !raw.length) return null
  return (raw as Record<string, unknown>[]).map((row, index) => ({
    ...row,
    __omicHubRowKey: `${props.message.id}-${index}`,
  }))
})

const tableColumns = computed(() => {
  if (!tableData.value) return []
  return Object.keys(tableData.value[0])
    .filter((key) => key !== '__omicHubRowKey')
    .map((key) => ({
      title: key,
      key,
      ellipsis: { tooltip: true },
    }))
})

const displayContent = computed(() =>
  props.isStreaming ? props.streamingContent : props.message.content,
)

const displayThought = computed(() =>
  props.isStreaming ? props.streamingThought : props.message.thought || '',
)

/** 超频/多智能体专家发言：内容由前端打字机渐进写入 message.content，
 *  复用普通助手消息的流式动效（呼吸光标 / 加速头像 / 生成指示）。 */
const isRoomStreaming = computed(() =>
  !props.isStreaming && !!props.message.senderAgent && props.message.status === 'streaming',
)
const streamingActive = computed(() => props.isStreaming || isRoomStreaming.value)
const isWorkerSpeech = computed(() => props.message.senderAgent?.role === 'worker')
const isWorkerCollapsed = computed(() =>
  isWorkerSpeech.value && !workerExpanded.value,
)
const workerPreview = computed(() => {
  const plain = (props.message.overdriveSummary || displayContent.value)
    .replace(/```[\s\S]*?```/g, ' [代码块] ')
    .replace(/[#>*_`|\[\]()~-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!plain) return '该专家已完成本阶段任务。'
  return plain.length > 140 ? `${plain.slice(0, 140)}…` : plain
})

const streamingHasContent = computed(() => displayContent.value.length > 0)

const hasThought = computed(() => displayThought.value.length > 0)

const isThinking = computed(() =>
  streamingActive.value && hasThought.value && !streamingHasContent.value,
)

const showStarAnimation = computed(() =>
  streamingActive.value && !streamingHasContent.value,
)

const showThinkingIndicator = computed(() =>
  streamingActive.value && isThinking.value,
)

// 流式中、正文尚未开始生成（典型：工具调用已全部返回「成功」，模型仍在酝酿正文）。
// 此时尾部不再放孤零零的闪烁光标，而是显示一个优雅的「正在生成回复」行内指示；
// 正文首个 token 一到 streamingHasContent 变 true，该指示即平滑淡出，由正文接管。
const showGeneratingTail = computed(() =>
  streamingActive.value && !streamingHasContent.value,
)

const isError = computed(() =>
  props.message.status === 'error'
  || (props.message.content?.startsWith('生成失败') ?? false),
)

// 错误是否属于用户无法自行处理的平台侧问题（密钥/配置/授权），用于提示联系管理员
const isAdminConfigError = computed(() =>
  /API Key|密钥|过期|授权|权限|配置|403|permission|unauthor/i.test(props.message.content || ''),
)

const isAuthExpiredError = computed(() =>
  /401|令牌无效|已过期|请重新登录|登录态失效|refresh/i.test(props.message.content || ''),
)

const hasOutputTokens = computed(() => (props.message.tokens?.output ?? 0) > 0)

const webSources = computed(() => {
  const sources: Array<{ title: string; url: string; snippet: string }> = [
    ...(props.message.webSources || []),
  ]
  for (const tool of props.message.toolCalls || []) {
    if (tool.name !== 'web_search' || !tool.result || typeof tool.result !== 'object') continue
    const result = tool.result as { results?: unknown; result?: { results?: unknown } }
    const resultRows = Array.isArray(result.results) ? result.results : result.result?.results
    if (!Array.isArray(resultRows)) continue
    for (const source of resultRows) {
      if (!source || typeof source !== 'object') continue
      const item = source as Record<string, unknown>
      if (typeof item.title === 'string' && typeof item.url === 'string') {
        sources.push({ title: item.title, url: item.url, snippet: typeof item.snippet === 'string' ? item.snippet : '' })
      }
    }
  }
  return sources.filter((source, index) => sources.findIndex((item) => item.url === source.url) === index)
})

function asKnowledgeCitationSource(value: unknown): KnowledgeCitationSource | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const citationId = typeof item.citation_id === 'string' ? item.citation_id : ''
  const docId = typeof item.doc_id === 'string' ? item.doc_id : ''
  const title = typeof item.title === 'string' ? item.title : ''
  const url = typeof item.url === 'string' ? item.url : ''
  if (!citationId || !docId || !title || !url) return null
  return {
    citationId,
    docId,
    title,
    category: typeof item.category === 'string' ? item.category : '',
    excerpt: typeof item.excerpt === 'string' ? item.excerpt : '',
    sectionPath: typeof item.section_path === 'string' ? item.section_path : '',
    url,
  }
}

const knowledgeSources = computed<KnowledgeCitationSource[]>(() => {
  const sources: KnowledgeCitationSource[] = [...(props.message.knowledgeSources || [])]
  for (const tool of props.message.toolCalls || []) {
    if (tool.name !== 'knowledge_search' || !tool.result || typeof tool.result !== 'object') continue
    const result = tool.result as { results?: unknown; result?: { results?: unknown } }
    const rows = Array.isArray(result.results) ? result.results : result.result?.results
    if (!Array.isArray(rows)) continue
    for (const row of rows) {
      const source = asKnowledgeCitationSource(row)
      if (source) sources.push(source)
    }
  }
  return sources.filter(
    (source, index) => sources.findIndex((item) => item.citationId === source.citationId) === index,
  )
})

function sourceDomain(url: string): string {
  try { return new URL(url).hostname } catch { return url }
}

function sourceHref(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : ''
  } catch {
    return ''
  }
}

function knowledgeHref(url: string): string {
  return /^\/knowledge\/[a-z0-9][a-z0-9-]*$/i.test(url) ? url : ''
}

function knowledgeAssetUrl(excerpt: string): string {
  const match = excerpt.match(/(\/docs-static\/[^\s)]+)/)
  return match?.[1] || ''
}

function isImageAsset(url: string): boolean {
  return /\.(?:png|jpe?g|webp|gif|bmp|tiff?|svg)(?:[?#].*)?$/i.test(url)
}

function sourceFavicon(url: string): string {
  const domain = sourceDomain(url)
  return domain ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32` : ''
}

function hideSourceFavicon(event: Event) {
  ;(event.currentTarget as HTMLImageElement).style.display = 'none'
}

const isEmptyWithThought = computed(() =>
  !streamingActive.value
  && !props.message.content?.trim().length
  && !!(props.message.thought?.trim().length)
  && !props.message.toolCalls?.length
  && !props.message.charts?.length
  && !props.message.agentTeamsCases?.length
  && !props.message.askRequest
  && !props.message.routedAgent?.transition?.visible
  && !isError.value,
)

const isEmpty = computed(() =>
  !streamingActive.value
  && !props.message.content?.trim().length
  && !(props.message.thought?.trim().length)
  && !props.message.toolCalls?.length
  && !props.message.charts?.length
  && !props.message.agentTeamsCases?.length
  && !props.message.askRequest
  && !props.message.routedAgent?.transition?.visible
  && !isError.value,
)

const systemCase = computed(() => props.message.agentTeamsCases?.[0])

const formattedTime = computed(() => {
  const d = new Date(props.message.createdAt)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

const lottieUrl = `${import.meta.env.BASE_URL}lottie/ai-avatar.json`

watch(
  () => streamingActive.value,
  (streaming) => {
    lottieRef.value?.setSpeed(streaming ? 2 : 1)
    if (!streaming) {
      thoughtExpanded.value = false
    }
  },
)

const tokenText = computed(() => {
  if (props.message.role !== 'assistant') return ''
  const t = props.message.tokens
  if (!t) return ''
  const input = t.input ?? 0
  const output = t.output ?? 0
  const total = t.total ?? input + output
  if (total <= 0 && input <= 0 && output <= 0) return ''
  return `Tokens: ${total} ↑${input} ↓${output}`
})

const aiIdentityName = computed(() => {
  if (props.message.senderAgent?.name) return props.message.senderAgent.name
  if (props.message.modelName) return props.message.modelName
  return props.agentName
})
const displayAgentAvatar = computed(() => props.message.senderAgent?.avatar || props.agentAvatar)
const displayAgentColor = computed(() => props.message.senderAgent?.color || props.agentColor)

const renderedContent = ref('')
/** 交错时间线中各 text 段的渲染结果（与 message.timeline 按下标对齐） */
const renderedTimelineHtml = ref<string[]>([])
let renderRafId: number | null = null

/** Markdown → 安全 HTML（含联网引用 [n] 角标重写）；渲染失败降级为纯文本并上报 */
function markdownToHtml(source: string): string {
  if (!source) return ''
  source = stripFakeToolCallMarkup(source)
  if (!source) return ''
  try {
    const container = document.createElement('div')
    container.innerHTML = DOMPurify.sanitize(md.render(source))
    const sources = webSources.value
    if (sources.length) {
      const nodes: Text[] = []
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
      let node = walker.nextNode()
      while (node) {
        const parent = node.parentElement
        if (!parent?.closest('a, code, pre') && /\[(\d+)\]/.test(node.textContent || '')) {
          nodes.push(node as Text)
        }
        node = walker.nextNode()
      }
      for (const textNode of nodes) {
        const fragment = document.createDocumentFragment()
        const value = textNode.textContent || ''
        let cursor = 0
        for (const match of value.matchAll(/\[(\d+)\]/g)) {
          const index = Number(match[1]) - 1
          const sourceItem = sources[index]
          if (!sourceItem || match.index === undefined) continue
          fragment.append(value.slice(cursor, match.index))
          const href = sourceHref(sourceItem.url)
          if (href) {
            const anchor = document.createElement('a')
            anchor.className = 'web-citation'
            anchor.href = href
            anchor.target = '_blank'
            anchor.rel = 'noopener noreferrer'
            anchor.title = sourceItem.snippet || sourceItem.title
            anchor.setAttribute('aria-label', `来源 ${index + 1}：${sourceItem.title}`)
            anchor.textContent = match[0]
            fragment.append(anchor)
          } else {
            fragment.append(match[0])
          }
          cursor = match.index + match[0].length
        }
        fragment.append(value.slice(cursor))
        textNode.replaceWith(fragment)
      }
    }
    const citations = new Map(knowledgeSources.value.map((item) => [item.citationId, item]))
    if (citations.size) {
      const nodes: Text[] = []
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
      let node = walker.nextNode()
      while (node) {
        const parent = node.parentElement
        if (!parent?.closest('a, button, code, pre') && /\[\[citation:kb-[a-f0-9]{16}\]\]/i.test(node.textContent || '')) {
          nodes.push(node as Text)
        }
        node = walker.nextNode()
      }
      for (const textNode of nodes) {
        const value = textNode.textContent || ''
        const fragment = document.createDocumentFragment()
        let cursor = 0
        for (const match of value.matchAll(/\[\[citation:(kb-[a-f0-9]{16})\]\]/ig)) {
          const citation = citations.get(match[1])
          if (!citation || match.index === undefined) continue
          const citationIndex = knowledgeSources.value.findIndex(
            (item) => item.citationId === citation.citationId,
          ) + 1
          fragment.append(value.slice(cursor, match.index))
          const wrapper = document.createElement('span')
          wrapper.className = 'knowledge-citation-wrap'
          const button = document.createElement('button')
          button.type = 'button'
          button.className = 'knowledge-citation'
          button.dataset.knowledgeUrl = knowledgeHref(citation.url)
          button.setAttribute('aria-label', `知识库来源 ${citationIndex}：${citation.title}`)
          button.textContent = `[${citationIndex}]`
          const preview = document.createElement('span')
          preview.className = 'knowledge-citation-preview'
          const assetUrl = knowledgeAssetUrl(citation.excerpt)
          if (assetUrl && isImageAsset(assetUrl)) {
            const image = document.createElement('img')
            image.className = 'knowledge-citation-preview__image'
            image.src = assetUrl
            image.alt = `${citation.title} 图片预览`
            preview.append(image)
          }
          const title = document.createElement('strong')
          title.className = 'knowledge-citation-preview__title'
          title.textContent = citation.title
          preview.append(title)
          const context = [citation.category, citation.sectionPath].filter(Boolean).join(' · ')
          if (context) {
            const meta = document.createElement('span')
            meta.className = 'knowledge-citation-preview__meta'
            meta.textContent = context
            preview.append(meta)
          }
          const excerpt = document.createElement('span')
          excerpt.className = 'knowledge-citation-preview__excerpt'
          excerpt.textContent = citation.excerpt.slice(0, 280)
          preview.append(excerpt)
          const action = document.createElement('span')
          action.className = 'knowledge-citation-preview__action'
          action.textContent = assetUrl && !isImageAsset(assetUrl) ? '点击打开原文与附件' : '点击打开知识库原文'
          preview.append(action)
          wrapper.append(button, preview)
          fragment.append(wrapper)
          cursor = match.index + match[0].length
        }
        fragment.append(value.slice(cursor))
        textNode.replaceWith(fragment)
      }
    }
    return DOMPurify.sanitize(container.innerHTML)
  } catch (e) {
    reportChatDiagnostic({
      phase: 'markdown-render',
      messageId: props.message.id,
      contentPreview: source.slice(0, 500),
      error: e,
    })
    return `<p>${escapeHtml(source)}</p>`
  }
}

/** 统一渲染入口：有时间线则逐段渲染（正文/工具交错），否则渲染整段正文 blob */
function renderAll() {
  const tl = props.message.timeline
  if (tl?.length) {
    renderedTimelineHtml.value = tl.map((seg) =>
      seg.kind === 'text' ? markdownToHtml(seg.text || '') : '',
    )
    renderedContent.value = ''
  } else {
    renderedTimelineHtml.value = []
    renderedContent.value = markdownToHtml(displayContent.value)
  }
}

type TimelineViewSegment =
  | { kind: 'text'; html: string }
  | { kind: 'tool'; tool: ToolCall }
  | { kind: 'skill'; card: SkillInvocationCard }

/** 时间线视图：text 段用渲染后的 HTML，tool 段按 toolCallId 找回 ToolCall；
 *  引用缺失（空文本段 / 历史消息未落库的工具调用）的段直接跳过 */
const timelineView = computed<TimelineViewSegment[]>(() => {
  const tl = props.message.timeline
  if (!tl?.length) return []
  const tools = props.message.toolCalls || []
  const skillCards = props.message.skillInvocations || []
  return tl
    .map((seg, i): TimelineViewSegment | null => {
      if (seg.kind === 'text') {
        const html = renderedTimelineHtml.value[i] || ''
        return html ? { kind: 'text', html } : null
      }
      if (seg.kind === 'skill') {
        const card = skillCards.find((c) => c.id === seg.skillCardId)
        return card ? { kind: 'skill', card } : null
      }
      const tool = tools.find((t) => t.id === seg.toolCallId)
      if (!tool) return null
      // ask_user 由 AskUserCard 呈现，跳过对应工具卡片避免重复
      if (props.message.askRequest && tool.name === 'ask_user') return null
      return { kind: 'tool', tool }
    })
    .filter((s): s is TimelineViewSegment => s !== null)
})

watch(
  () => [displayContent.value, webSources.value, knowledgeSources.value, props.message.timeline] as const,
  () => {
    if (streamingActive.value) {
      if (renderRafId) return
      renderRafId = requestAnimationFrame(() => {
        // 先复位句柄再渲染：渲染抛异常时 rAF 不会重排，
        // 不复位会导致后续所有正文更新被 `if (renderRafId) return` 永久吞掉
        renderRafId = null
        renderAll()
      })
    } else {
      renderAll()
    }
  },
  { immediate: true, deep: true },
)

onUnmounted(() => {
  if (renderRafId) {
    cancelAnimationFrame(renderRafId)
    renderRafId = null
  }
  if (copyBtnTimer) clearTimeout(copyBtnTimer)
  Object.values(attachmentPreviewUrls.value).forEach((url) => URL.revokeObjectURL(url))
})

const { execute } = usePyodide()

const previewChart = ref<ChartData | null>(null)
const showChartPreview = ref(false)

function openChartPreview(chart: ChartData) {
  previewChart.value = chart
  showChartPreview.value = true
}

function handleConfirmTool(toolName: string, args: Record<string, unknown>) {
  emit('confirmTool', toolName, { ...args, _confirmed: true })
}

function handleOpenToolPage(route: string, args: Record<string, unknown>) {
  if (route.startsWith('/')) {
    router.push(route)
  } else {
    emit('openToolPage', route, args)
  }
}

const confirmToolCalls = computed(() =>
  (props.message.toolCalls || []).filter(
    (t) => t.uiPayload?.confirm_card === true,
  ),
)

const openPageToolCalls = computed(() =>
  (props.message.toolCalls || []).filter(
    (t) => t.uiPayload?.route,
  ),
)

const taskToolCalls = computed(() =>
  (props.message.toolCalls || []).filter(
    (t) => t.uiPayload?.task_id,
  ),
)

const agentHubStore = useAgentHubStore()

/** Studio ask_user 澄清提交：把分页收集的答案数组交给 store 拼成下一条用户消息 */
const answeringAsk = ref(false)
async function handleAskSubmit(answers: string[]) {
  if (answeringAsk.value) return
  answeringAsk.value = true
  try {
    await agentHubStore.answerAskRequest(answers)
  } finally {
    answeringAsk.value = false
  }
}

/** ask_user 由 AskUserCard 呈现，过滤掉对应的工具卡片避免重复（历史重载无 askRequest 时仍显示工具卡） */
const visibleToolCalls = computed(() => {
  const tools = props.message.toolCalls || []
  if (props.message.askRequest) return tools.filter((t) => t.name !== 'ask_user')
  return tools
})

/** 气泡内是否有任何可渲染内容：消息只携带 askRequest（澄清弹窗）时正文为空，
 *  不渲染空气泡，避免弹窗卡片上方出现一条空白圆角长条 */
const hasBodyContent = computed(() =>
  streamingHasContent.value
  || !!props.message.content?.trim().length
  || timelineView.value.length > 0
  || !!props.message.agentTeamsCases?.length
  || visibleToolCalls.value.length > 0
  || plotlyCharts.value.length > 0
  || (props.message.charts?.length ?? 0) > 0
  || !!tableData.value
  || (props.message.consultation?.experts.length ?? 0) > 0
  || webSources.value.length > 0
  || Object.keys(props.message.overdriveArtifacts || {}).length > 0
  || !!props.message.routedAgent?.transition?.visible,
)

let copyBtnTimer: ReturnType<typeof setTimeout> | null = null

const OVERDRIVE_ARTIFACT_PATH_RE = /^\/api\/v1\/chat\/sessions\/([^/]+)\/overdrive-runs\/([^/]+)\/artifacts$/

/** 超频发言正文里的产物链接需要登录态，拦截默认跳转改走认证 blob 下载 */
async function downloadOverdriveArtifactLink(sessionId: string, runId: string, path: string) {
  try {
    const blob = await chatApi.downloadOverdriveArtifact(sessionId, runId, path)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = path.split('/').pop() || 'artifact'
    anchor.click()
    URL.revokeObjectURL(url)
  } catch {
    messageApi.error('产物下载失败')
  }
}

function handleBodyClick(e: MouseEvent) {
  const anchor = (e.target as HTMLElement).closest('a') as HTMLAnchorElement | null
  const anchorHref = anchor?.getAttribute('href') || ''
  if (anchorHref) {
    let url: URL | null = null
    try {
      // href 可能是后端写的绝对地址，也可能是相对路径，统一归一化后按路径匹配
      url = new URL(anchorHref, window.location.origin)
    } catch {
      url = null
    }
    const match = url?.pathname.match(OVERDRIVE_ARTIFACT_PATH_RE)
    const artifactPath = url?.searchParams.get('path')
    if (match && artifactPath) {
      e.preventDefault()
      void downloadOverdriveArtifactLink(match[1], match[2], artifactPath)
      return
    }
  }
  const citation = (e.target as HTMLElement).closest('.knowledge-citation') as HTMLElement | null
  if (citation) {
    const href = citation.dataset.knowledgeUrl || ''
    if (href) void router.push(href)
    return
  }
  const t = (e.target as HTMLElement).closest('.copy-btn') as HTMLElement | null
  if (t) {
    navigator.clipboard.writeText(decodeURIComponent(t.dataset.code || ''))
    t.textContent = '已复制!'
    if (copyBtnTimer) clearTimeout(copyBtnTimer)
    copyBtnTimer = setTimeout(() => {
      t.textContent = '复制'
    }, 1500)
    return
  }

  const runBtn = (e.target as HTMLElement).closest('.run-btn') as HTMLElement | null
  if (runBtn) {
    const code = decodeURIComponent(runBtn.dataset.code || '')
    if (!code) return
    runBtn.textContent = '运行中...'
    runBtn.setAttribute('disabled', 'true')
    execute(code).then((res) => {
      runBtn.textContent = '▶ 运行'
      runBtn.removeAttribute('disabled')
      // 在当前 pre 后插入结果面板
      const pre = runBtn.closest('pre')
      if (!pre) return
      let resultPanel = pre.nextElementSibling as HTMLElement | null
      if (!resultPanel || !resultPanel.classList.contains('execution-result')) {
        resultPanel = document.createElement('div')
        resultPanel.className = 'execution-result'
        pre.parentNode?.insertBefore(resultPanel, pre.nextSibling)
      }
      const outputHtml = res.error
        ? `<div class="exec-error">${escapeHtml(res.error)}</div>`
        : `<pre class="exec-output">${escapeHtml(res.output || '（无输出）')}</pre>`
      const imagesHtml = res.images.map((img) => `<img src="${img}" class="exec-image" />`).join('')
      resultPanel.innerHTML = outputHtml + imagesHtml
    })
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function handleCopy(mode: CopyMode) {
  emit('copy', mode)
}
function handleRegenerate() {
  emit('regenerate', props.message.id)
}
function handleRetryWithModel() {
  emit('retryWithModel', props.message.id)
}
function handleTranslate() {
  emit('translate', props.message.id)
}
function handleDelete() {
  emit('delete', props.message.id)
}
function handleEdit() {
  emit('edit', props.message.id)
}
</script>

<template>
  <div
    class="kimi-message-item"
    :class="message.role"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <template v-if="message.role === 'user'">
      <div class="message-header user-header">
        <div class="message-meta">
          <span v-if="tokenText" class="meta-item tokens">{{ tokenText }}</span>
          <span v-if="tokenText && formattedTime" class="meta-separator">|</span>
          <span v-if="formattedTime" class="meta-item">{{ formattedTime }}</span>
        </div>
        <div class="message-identity">
          <span class="message-name">{{ userName }}</span>
          <UserAvatar
            :nickname="userName"
            :src="userAvatar"
            :size="28"
            class="message-avatar"
          />
        </div>
      </div>

      <div class="message-content user-bubble">
        {{ message.content }}
        <div v-if="message.attachments?.length" class="attachments">
          <div v-for="(file, idx) in message.attachments" :key="idx" class="attachment-tag">
            <template v-if="isImageAttachment(file)">
              <img
                v-if="attachmentPreviewUrl(file, idx)"
                class="attachment-image-preview"
                :src="attachmentPreviewUrl(file, idx)"
                :alt="file.name"
              />
              <span v-else class="attachment-image-loading" role="status">图片加载中</span>
            </template>
            <n-icon v-else size="14">
              <component :is="file.type === 'directory' ? FolderOpenOutline : DocumentOutline" />
            </n-icon>
            <span class="attachment-name">{{ file.name }}</span>
            <span v-if="file.type === 'directory'" class="attachment-directory-state">只读 · 递归</span>
          </div>
        </div>
      </div>

      <MessageActionBar
        :visible="hovered"
        :is-user="true"
        :content="message.content"
        :model-name="modelName"
        @copy="handleCopy"
        @delete="handleDelete"
        @regenerate="handleRegenerate"
        @edit="handleEdit"
      />
    </template>

    <template v-else-if="message.role === 'assistant'">
      <div class="message-header assistant-header">
        <div class="message-identity">
          <div class="ai-avatar">
            <Vue3Lottie
              v-if="displayAgentAvatar === '🤖' || !displayAgentAvatar"
              ref="lottieRef"
              :animation-link="lottieUrl"
              :loop="true"
              :auto-play="true"
              :width="32"
              :height="32"
            />
            <div
              v-else
              class="avatar-fallback"
              :style="{ background: displayAgentColor }"
            >
              {{ displayAgentAvatar }}
            </div>
          </div>
          <span class="message-name ai-name">{{ aiIdentityName }}</span>
          <span
            v-if="message.routedAgent"
            class="routed-agent-badge"
            :style="{ borderColor: message.routedAgent.color || undefined }"
            :title="message.routedAgent.reason || '由该专家回答'"
          >
            <span class="routed-agent-avatar">{{ message.routedAgent.avatar }}</span>
            <span class="routed-agent-name">{{ message.routedAgent.name }}</span>
          </span>
          <transition name="fade">
            <span v-if="showThinkingIndicator" class="thinking-badge">✨ 思考中...</span>
          </transition>
        </div>
        <div class="message-meta">
          <span v-if="tokenText" class="meta-item tokens">{{ tokenText }}</span>
          <span v-if="tokenText && formattedTime" class="meta-separator">|</span>
          <span v-if="formattedTime" class="meta-item">{{ formattedTime }}</span>
        </div>
      </div>

      <!-- 错误态 -->
      <div v-if="isError" class="ai-empty-state error">
        <div class="empty-icon">💫</div>
        <div class="empty-title">星尘信号受到了干扰</div>
        <div class="empty-desc">{{ message.content || '生成失败，请稍后重试或切换模型' }}</div>
        <div class="error-admin-hint">
          {{ isAuthExpiredError
            ? '当前登录态已失效，请先重新登录后再重试。'
            : isAdminConfigError
            ? '此问题通常由模型密钥或配置失效引起，用户侧无法自行修复，请联系管理员解决。'
            : '若重试或切换模型后仍失败，请联系管理员解决。' }}
        </div>
        <div class="empty-actions">
          <n-button size="small" type="primary" @click="handleRegenerate">🔄 重试</n-button>
          <n-button size="small" @click="handleRetryWithModel">⚙️ 切换模型</n-button>
        </div>
      </div>

      <!-- 空内容但有思考过程 -->
      <div v-else-if="isEmptyWithThought" class="ai-empty-state">
        <div class="empty-icon">💭</div>
        <div class="empty-title">
          {{ hasOutputTokens ? '回复内容加载异常' : '思考完成，但未生成正式回复' }}
        </div>
        <div v-if="message.finishReason === 'length'" class="empty-desc">
          模型的思考过程已耗尽 max_tokens 输出预算（finish_reason=length），未能输出正文。<br>
          请在「系统设置 → AI 模型配置」中调大该模型的 max_tokens 后重新发送。
        </div>
        <div v-else-if="hasOutputTokens" class="empty-desc">
          已收到模型的 Token 用量，但正文未能正确加载。问题已记录，请点击重试。
        </div>
        <div v-else class="empty-desc">模型完成了推理，但未输出正式回复内容，请重试或切换模型。</div>
        <details class="thought-details">
          <summary class="thought-summary">🔍 查看思考过程</summary>
          <div class="thought-text">{{ message.thought }}</div>
        </details>
        <div class="empty-actions">
          <n-button size="small" type="primary" @click="handleRegenerate">
            🔄 {{ hasOutputTokens ? '点击重试' : '重新生成' }}
          </n-button>
          <n-button size="small" @click="handleRetryWithModel">⚙️ 切换模型</n-button>
        </div>
      </div>

      <!-- 完全空内容 -->
      <div v-else-if="isEmpty" class="ai-empty-state">
        <div class="empty-icon">🌌</div>
        <div class="empty-title">{{ hasOutputTokens ? '回复内容加载异常' : '这片星域暂时没有回应' }}</div>
        <div v-if="hasOutputTokens" class="empty-desc">
          已收到模型的 Token 用量，但正文未能正确加载。问题已记录，请点击重试。
        </div>
        <div v-else class="empty-desc">
          当前模型响应为空，请重新发送或切换模型。<br>
          · 可能是网络连接出现波动<br>
          · 模型在当前上下文中无法生成回复
        </div>
        <div class="empty-actions">
          <n-button size="small" type="primary" @click="handleRegenerate">
            🔄 {{ hasOutputTokens ? '点击重试' : '重新发送' }}
          </n-button>
          <n-button size="small" @click="handleRetryWithModel">⚙️ 切换模型</n-button>
        </div>
      </div>

      <!-- 正常内容区 -->
      <template v-else>
        <RouteTransitionCard
          v-if="message.routedAgent?.transition?.visible"
          :route="message.routedAgent"
        />
        <CollaborationRouteNotice
          v-if="message.collaborationRoute && !(message.routedAgent?.transition?.visible && message.collaborationRoute.intent === 'chat')"
          :route="message.collaborationRoute"
          @correct="(route) => emit('correctCollaborationRoute', route)"
        />

        <!-- 可折叠的思考过程 -->
        <div v-if="hasThought" class="thought-block">
          <button class="thought-toggle" @click="thoughtExpanded = !thoughtExpanded">
            <span v-if="showThinkingIndicator" class="thinking-label">✨ 思考中...</span>
            <span v-else class="thinking-label">🔍 思考过程</span>
            <span class="thought-arrow" :class="{ rotated: thoughtExpanded }">▾</span>
          </button>
          <transition name="thought-expand">
            <div v-show="thoughtExpanded" class="thought-content">
              {{ displayThought }}
            </div>
          </transition>
        </div>

        <!-- 首 Token 前加载态；按等待时长轮换动画与文案。
             不套外层 transition：AiLoading 内部已有 out-in 过渡，外层 leave 过渡
             会在其内部过渡进行时移除节点，触发 Vue parentNode null 崩溃。 -->
        <AiLoading
          v-if="showStarAnimation"
          type="auto"
          :stage="isThinking ? '正在梳理思考过程…' : ''"
        />

        <!-- 内容气泡（常驻元素，不套外层 transition：流式→done 切换时与相邻加载态
             同帧 enter/leave 曾触发 Vue parentNode null 补丁崩溃，导致正文/tokens
             刷新前不渲染）。 -->
        <div
          v-if="streamingActive ? streamingHasContent : hasBodyContent"
          class="message-content ai-card"
          :class="{
            'streaming-active': streamingActive,
            'worker-result-card': isWorkerSpeech,
            'is-collapsed': isWorkerCollapsed,
          }"
        >
          <button
            v-if="isWorkerSpeech"
            type="button"
            class="worker-result-toggle"
            :aria-expanded="workerExpanded"
            @click="workerExpanded = !workerExpanded"
          >
            <span class="worker-result-toggle__meta">
              <span class="worker-result-toggle__label">
                {{ streamingActive ? '专家正在生成' : '专家阶段产物' }}
              </span>
              <span v-if="message.senderAgent?.round" class="worker-result-toggle__round">
                第 {{ message.senderAgent.round }} 阶段
              </span>
              <span class="worker-result-toggle__count">{{ message.content.length }} 字</span>
            </span>
            <span class="worker-result-toggle__action">
              {{ workerExpanded ? '收起内容' : '展开查看' }}
              <span class="worker-result-toggle__chevron" :class="{ 'is-expanded': workerExpanded }" aria-hidden="true">⌄</span>
            </span>
          </button>
          <p v-if="isWorkerCollapsed" class="worker-result-preview">{{ workerPreview }}</p>
          <template v-else>
          <!-- 生成中指示置于气泡内容之前：流式生成图片等大块内容时，
               动画不会被已生成内容压到可视区之外。 -->
          <!-- 正文尚未生成时的优雅行内指示：替代孤立的闪烁光标，
               正文首个 token 到达后平滑淡出（不套 out-in：避免卸载竞态）。 -->
          <transition name="gen-tail">
            <div v-if="showGeneratingTail" class="generating-tail" role="status" aria-live="polite">
              <span class="gen-spark" aria-hidden="true">✨</span>
              <span class="gen-text">正在生成回复</span>
              <span class="gen-dots" aria-hidden="true"><i /><i /><i /></span>
            </div>
          </transition>

          <!-- 流式光标 + typing 指示：正文流式输出时显示在内容之前，结束后 200ms 淡出 -->
          <transition name="cursor-fade">
            <span v-if="streamingActive && streamingHasContent" class="stream-tail">
              <span class="stream-cursor" />
              <span class="stream-dots" aria-hidden="true"><i /><i /><i /></span>
            </span>
          </transition>

          <!-- 交错时间线：正文与工具调用按实际发生顺序渲染（内容→工具→内容），
               最终结论永远在最底部，不用翻回顶部看结果 -->
          <template v-if="timelineView.length">
            <template v-for="(seg, segIdx) in timelineView" :key="segIdx">
              <div
                v-if="seg.kind === 'text'"
                class="message-body markdown-body"
                v-html="seg.html"
                @click="handleBodyClick"
              />
              <div
                v-else-if="seg.kind === 'tool'"
                class="timeline-tool-entry"
              >
                <ToolCallEntry
                  :tool="seg.tool"
                  @confirm-tool="handleConfirmTool"
                  @open-tool-page="handleOpenToolPage"
                />
              </div>
              <SkillInvocationCardView
                v-else-if="seg.kind === 'skill'"
                :card="seg.card"
              />
            </template>
          </template>
          <div v-else class="message-body markdown-body" v-html="renderedContent" @click="handleBodyClick" />

          <div v-if="plotlyCharts.length" class="chart-results">
            <div
              v-for="chart in plotlyCharts"
              :key="chart.id"
              class="chart-wrapper"
            >
              <div class="chart-actions">
                <n-button size="tiny" @click="openChartPreview(chart)">🔍 预览</n-button>
              </div>
              <div
                :ref="setPlotlyContainer(chart.id)"
                class="plotly-container"
              />
            </div>
            <div v-if="plotlyRenderError" class="plotly-render-error">{{ plotlyRenderError }}</div>
          </div>

          <div v-if="message.charts?.some((c) => c.type === 'echarts')" class="chart-results">
            <div
              v-for="(chart, idx) in message.charts.filter((c) => c.type === 'echarts')"
              :key="idx"
              class="chart-wrapper"
            >
              <div class="chart-actions">
                <n-button size="tiny" @click="openChartPreview(chart)">🔍 预览</n-button>
              </div>
              <VChart :option="chart.option" autoresize style="height: 300px" />
            </div>
          </div>

          <div v-if="tableData" class="table-results">
            <n-data-table
              :data="tableData"
              :columns="tableColumns"
              :row-key="(row) => String(row.__omicHubRowKey)"
              :max-height="300"
              size="small"
            />
          </div>

          <!-- 无时间线的历史消息：沿用旧的"底部工具列表"布局 -->
          <div v-if="!timelineView.length && visibleToolCalls.length" class="tool-results">
            <ToolCallEntry
              v-for="(tool, idx) in visibleToolCalls"
              :key="idx"
              :tool="tool"
              @confirm-tool="handleConfirmTool"
              @open-tool-page="handleOpenToolPage"
            />
          </div>

          <MessageArtifactGallery
            :session-id="sessionId"
            :tools="message.toolCalls"
            :artifacts="message.overdriveArtifacts"
          />

          <ExpertConsultationCard
            v-if="message.consultation?.experts.length"
            :experts="message.consultation.experts"
            :consultation-id="message.consultation.consultationId"
            :consultation-summary="message.consultation.consultationSummary"
            :case-available="message.consultation.caseAvailable"
            @create-case="(summary, consultationId) => emit('createCaseFromConsultation', summary, consultationId)"
          />

          <AgentTeamsCaseCard
            v-for="caseInfo in message.agentTeamsCases || []"
            :key="caseInfo.case_id"
            :case-info="caseInfo"
          />

          <details v-if="webSources.length" class="web-sources">
            <summary class="web-sources-title">来源（{{ webSources.length }}）</summary>
            <div class="web-source-list">
              <a
                v-for="(source, index) in webSources"
                :key="source.url"
                class="web-source"
                :href="sourceHref(source.url) || undefined"
                target="_blank"
                rel="noopener noreferrer"
                :title="source.snippet"
              >
                <span class="source-index">[{{ index + 1 }}]</span>
                <img
                  v-if="sourceFavicon(source.url)"
                  class="source-favicon"
                  :src="sourceFavicon(source.url)"
                  :alt="`${sourceDomain(source.url)} favicon`"
                  loading="lazy"
                  @error="hideSourceFavicon"
                >
                <span class="source-title">{{ source.title }}</span>
                <span class="source-domain">{{ sourceDomain(source.url) }}</span>
              </a>
            </div>
          </details>
          </template>
        </div>

        <!-- Studio ask_user 澄清卡片：分页交互收集（选项/自由输入/跳过），回答后折叠为工具卡片样式 -->
        <PlanConfirmationCard
          v-if="message.askRequest?.kind === 'plan_confirmation' && message.askRequest.planConfirmation"
          :plan="message.askRequest.planConfirmation"
          :session-id="sessionId"
        />
        <AskUserCard
          v-else-if="message.askRequest"
          :ask="message.askRequest"
          @submit="handleAskSubmit"
        />
        <OverdriveApprovalCard
          v-if="message.overdriveApproval"
          :approval="message.overdriveApproval"
        />
      </template>

      <!-- AI 回复操作栏：点赞 / 点踩 / 复制（完成且非错误/空态时展示） -->
      <div
        v-if="!streamingActive && !isError && !isEmpty && !isEmptyWithThought"
        class="assistant-feedback-bar"
      >
        <button
          type="button"
          class="feedback-btn"
          :class="{ active: message.feedback === 'like' }"
          title="回答有帮助"
          aria-label="点赞该回复"
          @click="emit('feedback', message.id, 'like')"
        >
          <NIcon :component="ThumbsUpOutline" size="15" />
        </button>
        <button
          type="button"
          class="feedback-btn"
          :class="{ active: message.feedback === 'dislike' }"
          title="回答需改进"
          aria-label="点踩该回复"
          @click="emit('feedback', message.id, 'dislike')"
        >
          <NIcon :component="ThumbsDownOutline" size="15" />
        </button>
        <button
          type="button"
          class="feedback-btn"
          title="复制回复"
          aria-label="复制该回复"
          @click="handleCopy('markdown')"
        >
          <NIcon :component="CopyOutline" size="15" />
        </button>
      </div>

      <!-- 错误/空内容态下直接显示操作栏 -->
      <MessageActionBar
        v-if="(isError || isEmpty || isEmptyWithThought)"
        :visible="true"
        :is-user="false"
        :content="message.content"
        :model-name="modelName"
        @copy="handleCopy"
        @regenerate="handleRegenerate"
        @retry-with-model="handleRetryWithModel"
        @translate="handleTranslate"
        @delete="handleDelete"
      />
    </template>

    <template v-else-if="message.role === 'system'">
      <OverdriveProgressCard v-if="message.overdriveProgress" :progress="message.overdriveProgress" />
      <PlanConfirmationCard
        v-else-if="message.askRequest?.kind === 'plan_confirmation' && message.askRequest.planConfirmation"
        :plan="message.askRequest.planConfirmation"
        :session-id="sessionId"
      />
      <OverdriveApprovalCard v-else-if="message.overdriveApproval" :approval="message.overdriveApproval" />
      <div v-else class="system-message" role="status" aria-live="polite">
        <span>{{ message.content }}</span>
        <a v-if="systemCase?.case_url" :href="systemCase.case_url">查看协作</a>
      </div>
    </template>

    <ChartPreviewModal v-model:show="showChartPreview" :chart="previewChart" />
  </div>
</template>

<style scoped lang="scss">
.kimi-message-item {
  padding: 20px 24px;
}

/* AI 回复操作栏：点赞 / 点踩 / 复制 */
.assistant-feedback-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;

  .feedback-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    color: var(--text-tertiary, #9aa3b2);
    background: transparent;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: color 0.15s ease, background-color 0.15s ease;

    &:hover {
      color: var(--chat-accent, #4f8ef7);
      background: rgba(79, 142, 247, 0.08);
    }

    &.active {
      color: var(--chat-accent, #4f8ef7);
      background: rgba(79, 142, 247, 0.12);
    }
  }
}

/* 头部：身份 + 元信息 */
.message-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.message-header.user-header {
  flex-direction: row-reverse;
  justify-content: flex-start;
}
.message-header.assistant-header {
  justify-content: flex-start;
}

.message-identity {
  display: flex;
  align-items: center;
  gap: 8px;
}
.message-header.user-header .message-identity {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}
.message-name {
  font-size: 13px;
  font-weight: 600;
}
.ai-name {
  color: var(--chat-accent, #4f8ef7);
}

.thinking-badge {
  font-size: 12px;
  color: var(--chat-accent, #4f8ef7);
  opacity: 0.7;
  animation: thinking-pulse 2s ease-in-out infinite;
  white-space: nowrap;
}

/* 智能路由：当前由哪位专家回答的徽标 */
.routed-agent-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  font-size: 11px;
  line-height: 18px;
  border: 1px solid var(--chat-border, #ddd);
  border-radius: 999px;
  background: var(--chat-bg-soft, rgba(127, 127, 127, 0.08));
  color: var(--chat-text-muted, #666);
  white-space: nowrap;
  cursor: default;
}
.routed-agent-avatar {
  font-size: 12px;
}
.routed-agent-name {
  font-weight: 500;
}
@keyframes thinking-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.9; }
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--chat-text-muted, #999);
}
.web-sources { margin-top:16px; padding-top:12px; border-top:1px solid var(--neutral-border); }
.web-sources-title { cursor:pointer; font-size:12px; font-weight:600; color:var(--neutral-text-2); }
.web-source-list { display:flex; flex-direction:column; gap:7px; margin-top:9px; }
.web-source { display:flex; align-items:center; gap:7px; min-width:0; font-size:12px; text-decoration:none; color:var(--neutral-text-2); }
.web-source:hover .source-title, .web-citation:hover { color:var(--arco-primary); text-decoration:underline; }
.source-index { flex:0 0 auto; color:var(--arco-primary); }
.source-favicon { width:14px; height:14px; flex:0 0 auto; border-radius:3px; }
.source-title { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.source-domain { margin-left:auto; flex:0 0 auto; color:var(--neutral-text-3); font-size:11px; }
:deep(.web-citation) { color:var(--arco-primary); font-weight:600; text-decoration:none; }
:deep(.knowledge-citation-wrap) { position:relative; display:inline-flex; vertical-align:baseline; }
:deep(.knowledge-citation) { margin:0 2px; padding:0; border:0; border-radius:var(--radius-sm); color:var(--arco-primary); background:transparent; font:inherit; font-weight:650; line-height:inherit; cursor:pointer; text-decoration:none; }
:deep(.knowledge-citation:hover), :deep(.knowledge-citation:focus-visible) { color:var(--color-primary-hover, var(--arco-primary)); text-decoration:underline; outline:none; }
:deep(.knowledge-citation:focus-visible) { box-shadow:0 0 0 2px var(--focus-ring, color-mix(in srgb, var(--arco-primary) 28%, transparent)); }
:deep(.knowledge-citation-preview) { position:absolute; z-index:30; bottom:calc(100% + 8px); left:50%; display:none; width:min(320px, 72vw); padding:12px; border:1px solid var(--neutral-border); border-radius:var(--radius-md); color:var(--neutral-text-1); background:var(--neutral-card); box-shadow:var(--shadow-3); transform:translateX(-50%); text-align:left; white-space:normal; }
:deep(.knowledge-citation-wrap:hover .knowledge-citation-preview), :deep(.knowledge-citation-wrap:focus-within .knowledge-citation-preview) { display:grid; gap:5px; }
:deep(.knowledge-citation-preview__image) { width:100%; max-height:160px; border-radius:var(--radius-sm); object-fit:contain; background:var(--neutral-fill-1); }
:deep(.knowledge-citation-preview__title) { overflow:hidden; color:var(--neutral-text-1); font-size:13px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }
:deep(.knowledge-citation-preview__meta), :deep(.knowledge-citation-preview__action) { color:var(--neutral-text-3); font-size:11px; line-height:1.4; }
:deep(.knowledge-citation-preview__excerpt) { display:-webkit-box; overflow:hidden; color:var(--neutral-text-2); font-size:12px; line-height:1.55; -webkit-box-orient:vertical; -webkit-line-clamp:4; }
@media (max-width: 767px) { :deep(.knowledge-citation-preview) { display:none !important; } }
@media (prefers-reduced-transparency: reduce) { :deep(.knowledge-citation-preview) { background:var(--neutral-card); } }
.message-header.user-header .message-meta {
  justify-content: flex-end;
}
.message-header.assistant-header .message-meta {
  justify-content: flex-start;
}
.meta-separator {
  color: var(--chat-border, #ddd);
  font-size: 10px;
}
.meta-item.tokens {
  display: flex;
  align-items: center;
  gap: 4px;
}
.token-arrow {
  font-size: 11px;
  margin-left: 2px;
}
.token-arrow.up {
  color: var(--chat-status-ready, #52c41a);
}
.token-arrow.down {
  color: var(--chat-accent, #1890ff);
}

/* 用户消息气泡（右对齐语义表面） */
.kimi-message-item.user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.kimi-message-item.user .message-content.user-bubble {
  max-width: 70%;
  padding: 12px 16px;
  background: var(--chat-user-bubble, var(--chat-surface-hover));
  color: var(--chat-user-text, var(--chat-text-primary));
  border: 1px solid var(--chat-border, transparent);
  border-radius: 16px 16px 4px 16px;
  font-size: 14px;
  line-height: 1.7;
  box-shadow: none;
  word-break: break-word;
  white-space: pre-wrap;
}
.kimi-message-item.user .attachments {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.kimi-message-item.user .attachment-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
}
.kimi-message-item.user .attachment-directory-state {
  color: rgba(255, 255, 255, 0.72);
  font-size: 11px;
}

/* AI 消息卡片 */
.kimi-message-item.assistant {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.kimi-message-item.assistant .ai-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
}
.kimi-message-item.assistant .avatar-fallback {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
}
.kimi-message-item.assistant .message-content.ai-card {
  position: relative;
  width: 100%;
  box-sizing: border-box;
  padding: 16px 20px;
  background: var(--chat-ai-card, #ffffff);
  border: 1px solid var(--bubble-border, var(--chat-border, #e5e7eb));
  border-radius: var(--card-radius, 12px);
  box-shadow: none;
  font-size: 14px;
  line-height: 1.8;
  color: var(--chat-text-primary, #1a1a1a);
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}
.kimi-message-item.assistant .message-content.ai-card.streaming-active {
  border-color: color-mix(in srgb, var(--chat-accent, #6366f1) 42%, transparent);
  box-shadow: none;
  contain: layout paint;
  overflow-anchor: none;
}

.worker-result-card {
  padding-top: 12px !important;
}

.worker-result-card.is-collapsed {
  background: color-mix(in srgb, var(--chat-ai-card, #fff) 92%, var(--chat-accent, #6366f1));
}

.worker-result-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0;
  padding: 2px 0 10px;
  color: var(--chat-text-primary, #1a1a1a);
  font: inherit;
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--bubble-border, var(--chat-border, #e5e7eb));
  cursor: pointer;
}

.worker-result-toggle:focus-visible {
  outline: 2px solid var(--chat-accent, #6366f1);
  outline-offset: 4px;
  border-radius: 6px;
}

.kimi-message-item.user .attachment-image-preview {
  display: block;
  width: min(220px, 100%);
  max-height: 180px;
  border: 1px solid var(--chat-border, var(--neutral-border));
  border-radius: 8px;
  background: var(--neutral-fill-1);
  object-fit: contain;
}

.kimi-message-item.user .attachment-image-loading {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  color: var(--neutral-text-3);
  font-size: 12px;
}

.kimi-message-item.user .attachment-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.worker-result-toggle__meta,
.worker-result-toggle__action {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.worker-result-toggle__label {
  font-weight: 650;
}

.worker-result-toggle__round,
.worker-result-toggle__count {
  color: var(--chat-text-tertiary, #7b8494);
  font-size: 12px;
}

.worker-result-toggle__action {
  flex: none;
  color: var(--chat-accent, #6366f1);
  font-size: 12px;
  font-weight: 600;
}

.worker-result-toggle__chevron {
  display: inline-block;
  transition: transform 160ms ease;
}

.worker-result-toggle__chevron.is-expanded {
  transform: rotate(180deg);
}

.worker-result-preview {
  display: -webkit-box;
  overflow: hidden;
  margin: 12px 0 0;
  color: var(--chat-text-secondary, #555);
  font-size: 13px;
  line-height: 1.65;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

@media (prefers-reduced-motion: reduce) {
  .worker-result-toggle__chevron {
    transition: none;
  }
}

@keyframes stream-breathe {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(99, 102, 241, 0.12),
      0 0 20px rgba(168, 85, 247, 0.10),
      0 0 40px rgba(99, 102, 241, 0.06);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(99, 102, 241, 0.22),
      0 0 28px rgba(168, 85, 247, 0.18),
      0 0 56px rgba(99, 102, 241, 0.12);
  }
}

/* 流式光标：呼吸闪烁（opacity 1 ↔ 0.2，ease-in-out），替代生硬硬闪 */
.stream-tail {
  display: inline-flex;
  align-items: center;
}
.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 1.2em;
  margin-left: 3px;
  vertical-align: text-bottom;
  background: linear-gradient(180deg, #6366f1, #a855f7);
  border-radius: 2px;
  animation: cursor-breathe 1s ease-in-out infinite;
}
/* 光标旁三点 typing 指示：相位错开 0.15s，配色沿用浅紫强调色 */
.stream-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 6px;
}
.stream-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--chat-accent, #6366f1);
  animation: gen-dot-bounce 1.2s ease-in-out infinite;
}
.stream-dots i:nth-child(2) { animation-delay: 0.15s; }
.stream-dots i:nth-child(3) { animation-delay: 0.3s; }

/* 流式结束后光标与指示 200ms 淡出，不闪跳 */
.cursor-fade-leave-active {
  transition: opacity 0.2s ease;
}
.cursor-fade-leave-to {
  opacity: 0;
}

/* Markdown 表格和代码块横向滚动 */
.kimi-message-item.assistant :deep(.markdown-body table),
.kimi-message-item.assistant :deep(.markdown-body pre) {
  overflow-x: auto;
  min-width: 320px;
  max-width: 100%;
}

@keyframes cursor-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}

/* 生成中的优雅行内指示：呼吸微光 + 跳动点，明确「仍在生成」而非「卡住/没完成」；
   置于气泡内容之前，与下方正文保持 14px 间距 */
.generating-tail {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  padding: 8px 14px;
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
  background: linear-gradient(
    100deg,
    color-mix(in srgb, var(--arco-primary, #6366f1) 7%, transparent),
    color-mix(in srgb, #a855f7 9%, transparent),
    color-mix(in srgb, var(--arco-primary, #6366f1) 7%, transparent)
  );
  background-size: 200% 100%;
  animation: gen-shimmer 2.2s ease-in-out infinite;
  color: var(--chat-text-secondary, #555);
  font-size: 13px;
  line-height: 1;
}
.generating-tail .gen-spark {
  font-size: 13px;
  animation: gen-spark-pulse 1.8s ease-in-out infinite;
}
.generating-tail .gen-text {
  font-weight: 500;
  letter-spacing: 0.2px;
}
.generating-tail .gen-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.generating-tail .gen-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--chat-accent, #6366f1);
  animation: gen-dot-bounce 1.2s ease-in-out infinite;
}
.generating-tail .gen-dots i:nth-child(2) { animation-delay: 0.16s; }
.generating-tail .gen-dots i:nth-child(3) { animation-delay: 0.32s; }

@keyframes gen-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@keyframes gen-spark-pulse {
  0%, 100% { opacity: 0.5; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.12); }
}
@keyframes gen-dot-bounce {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
}

/* 行内指示平滑淡入/淡出（正文出现时优雅退场） */
.gen-tail-enter-active,
.gen-tail-leave-active {
  transition: opacity 0.32s ease, transform 0.32s ease;
}
.gen-tail-enter-from { opacity: 0; transform: translateY(6px); }
.gen-tail-leave-to { opacity: 0; transform: translateY(-4px); }

.content-swap-enter-active,
.content-swap-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.content-swap-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.content-swap-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .content-swap-enter-active,
  .content-swap-leave-active,
  .stream-cursor,
  .stream-dots i,
  .generating-tail,
  .generating-tail .gen-spark,
  .generating-tail .gen-dots i,
  .gen-tail-enter-active,
  .gen-tail-leave-active,
  .cursor-fade-leave-active,
  .kimi-message-item.assistant .message-content.ai-card.streaming-active {
    animation: none;
    transition: none;
  }
}

/* 思考过程折叠块 */
.thought-block {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  margin-bottom: 8px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--chat-border, #f0f0f0);
  background: var(--chat-surface, #f8f9fa);
}
.thought-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: var(--chat-text-secondary, #666);
  transition: background 0.2s ease;
}
.thought-toggle:hover {
  background: var(--chat-surface-hover, rgba(0, 0, 0, 0.03));
}
.thinking-label {
  color: var(--chat-accent, #4f8ef7);
  opacity: 0.8;
}
.thought-arrow {
  margin-left: auto;
  font-size: 10px;
  transition: transform 0.2s ease;
}
.thought-arrow.rotated {
  transform: rotate(180deg);
}
.thought-content {
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--chat-text-secondary, #666);
  font-style: italic;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
  border-top: 1px solid var(--chat-border, #f0f0f0);
  background: var(--chat-surface, #f8f9fa);
}
:root[data-theme="dark"] .thought-content {
  background: rgba(255, 255, 255, 0.03);
}
.thought-expand-enter-active,
.thought-expand-leave-active {
  transition: opacity 0.2s ease, max-height 0.3s ease;
}
.thought-expand-enter-from,
.thought-expand-leave-to {
  opacity: 0;
  max-height: 0;
}

/* 空内容态中的思考过程详情 */
.thought-details {
  width: 100%;
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--chat-border, #e0e0e0);
}
.thought-summary {
  padding: 8px 14px;
  font-size: 12px;
  cursor: pointer;
  color: var(--chat-text-secondary, #666);
  background: var(--chat-surface, #f8f9fa);
}
.thought-text {
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--chat-text-secondary, #666);
  font-style: italic;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 250px;
  overflow-y: auto;
}

/* thinking-badge fade transition */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 空内容 / 错误态 */
.ai-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 90%;
  padding: 28px 20px;
  background: var(--chat-ai-card, #ffffff);
  border: 1px dashed var(--chat-border, #e0e0e0);
  border-radius: 12px;
  text-align: center;
}
.ai-empty-state.error {
  border-style: solid;
  border-color: rgba(208, 48, 80, 0.25);
  background: linear-gradient(180deg, #fff8f9 0%, #ffffff 100%);
}
.empty-icon {
  font-size: 36px;
  margin-bottom: 10px;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.08));
}
.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--chat-text-primary, #1a1a1a);
  margin-bottom: 6px;
}
.empty-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--chat-text-secondary, #666);
  max-width: 420px;
}
.error-admin-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--chat-text-tertiary, #999);
  max-width: 420px;
}
.empty-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.kimi-message-item .system-message {
  text-align: center;
  padding: 8px 0;
  font-size: 13px;
  color: var(--chat-text-muted);

  a {
    margin-left: 8px;
    color: var(--chat-accent);
    text-decoration: none;
  }

  a:hover,
  a:focus-visible {
    text-decoration: underline;
  }
}

:deep(.code-header) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--chat-surface, #f5f5f5);
  border-bottom: 1px solid var(--chat-border);
  font-size: 12px;
}

:deep(.code-lang) {
  color: var(--chat-text-muted);
  text-transform: uppercase;
  margin-right: auto;
}

:deep(.copy-btn),
:deep(.run-btn) {
  background: transparent;
  border: 1px solid var(--chat-border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--chat-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.copy-btn:hover),
:deep(.run-btn:hover) {
  color: var(--chat-accent);
  border-color: var(--chat-accent);
}

:deep(.run-btn:disabled) {
  opacity: 0.6;
  cursor: not-allowed;
}

:deep(.execution-result) {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--chat-surface-hover, rgba(0,0,0,0.03));
  border-radius: 6px;
  font-size: 13px;
}

:deep(.exec-output) {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: monospace;
}

:deep(.exec-error) {
  color: var(--chat-error, #d03050);
  white-space: pre-wrap;
}

:deep(.exec-image) {
  max-width: 100%;
  margin-top: 8px;
  border-radius: 4px;
}

/* 图表结果 */
.chart-results {
  width: 100%;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chart-wrapper {
  position: relative;
  border: 1px solid var(--chat-border, #f0f0f0);
  border-radius: 8px;
  overflow: hidden;
  background: var(--chat-ai-card, #ffffff);
}
.chart-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.chart-wrapper:hover .chart-actions {
  opacity: 1;
}

/* Plotly 图表容器 */
.plotly-container {
  width: 100%;
  min-height: 400px;
}
.plotly-render-error {
  color: var(--chat-error, #d03050);
  font-size: 13px;
  padding: 8px 12px;
  background: var(--chat-surface, #fff8f9);
  border: 1px solid rgba(208, 48, 80, 0.15);
  border-radius: 6px;
}

/* 表格结果 */
.table-results {
  width: 100%;
  margin-top: 12px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--chat-border, #f0f0f0);
}

/* 工具调用结果卡 */
.tool-results {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}
.timeline-tool-entry + .timeline-tool-entry {
  margin-top: 10px;
}
.artifact-register-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid rgba(24, 160, 88, 0.25);
  border-radius: 10px;
  background: rgba(24, 160, 88, 0.08);
}
.artifact-register-icon {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #18a058;
  font-weight: 700;
}
.artifact-register-title {
  font-size: 13px;
  font-weight: 600;
}
.artifact-register-sub {
  margin-top: 2px;
  font-size: 11px;
  color: var(--chat-text-muted, #888);
}

@media (max-width: 640px) {
  .thought-block {
    width: 100%;
  }
  .plotly-container {
    min-height: 280px;
  }
}

.kimi-message-item {
  padding-block: 24px;
}

.kimi-message-item.assistant .message-name,
.kimi-message-item.assistant .ai-name {
  color: var(--stardust-blue);
  font-weight: 600;
}

.kimi-message-item.assistant .message-content.ai-card {
  border: 1px solid var(--bubble-border, var(--chat-border, #e5e7eb));
  border-radius: var(--radius-card, 12px);
  box-shadow: none;
  line-height: 1.75;
}

.kimi-message-item.assistant .thought-block,
.kimi-message-item.assistant .thought-details {
  border-color: rgba(46, 91, 255, 0.08);
  border-radius: 8px;
  background: var(--stardust-bg-soft);
}

.kimi-message-item.assistant .thought-toggle,
.kimi-message-item.assistant .thought-summary {
  background: var(--stardust-bg-soft);
  color: var(--stardust-blue);
}

.kimi-message-item.assistant :deep(.markdown-body table) {
  overflow: hidden;
  border: 1px solid rgba(46, 91, 255, 0.08);
  border-radius: 8px;
  border-collapse: separate;
  border-spacing: 0;
}

.kimi-message-item.assistant :deep(.markdown-body th) {
  background: var(--stardust-bg-soft);
  color: #3b4262;
  font-weight: 600;
}

.kimi-message-item.assistant :deep(.markdown-body th),
.kimi-message-item.assistant :deep(.markdown-body td) {
  padding: 12px 16px;
  min-height: 48px;
}

.kimi-message-item.assistant :deep(.markdown-body tbody tr:hover) {
  background: #f8f9ff;
}

:root[data-theme="dark"] .kimi-message-item.assistant :deep(.markdown-body th) {
  color: var(--text-primary);
}
:root[data-theme="dark"] .kimi-message-item.assistant :deep(.markdown-body tbody tr:hover) {
  background: rgba(118, 145, 255, 0.08);
}
</style>
