import type { StudioSessionDTO } from '@/api/studio'
import type { ChatMessage, ToolCall } from '@/components/ai-chat/types'

export type StudioTaskKind = 'transcriptomics' | 'single-cell' | 'generic'
export type StudioTaskStatus = 'completed' | 'running' | 'waiting'

export interface StudioTaskUnderstanding {
  task: string
  domain: string
  goal: string
  status: '已理解' | '执行中'
}

const DOMAIN_PATTERNS: Array<{ label: string; pattern: RegExp }> = [
  { label: '单细胞组学', pattern: /单细胞|scRNA|cell type|细胞亚群|细胞注释/i },
  { label: '转录组学', pattern: /RNA[- ]?seq|转录组|差异表达|DEG|表达矩阵/i },
  { label: '蛋白质与序列分析', pattern: /蛋白|protein|序列|fasta|结构域|功能预测/i },
  { label: '比较基因组学', pattern: /物种|比较基因组|同源基因|ortholog|基因差异/i },
]

export function inferStudioTaskKind(title: string): StudioTaskKind {
  if (/单细胞|scRNA|细胞亚群|细胞注释/i.test(title)) return 'single-cell'
  if (/RNA[- ]?seq|转录组|差异表达|表达矩阵/i.test(title)) return 'transcriptomics'
  return 'generic'
}

export function inferStudioTaskStatus(
  session: StudioSessionDTO,
  currentSessionId: string,
  isStreaming: boolean,
): StudioTaskStatus {
  if (session.session_id === currentSessionId && isStreaming) return 'running'
  const status = String(session.status || '').toLowerCase()
  if (['completed', 'complete', 'finished', 'success', 'succeeded', 'done'].includes(status)) return 'completed'
  if (['running', 'processing', 'streaming', 'active'].includes(status)) return 'running'
  return 'waiting'
}

export function parseTaskUnderstanding(
  messages: ChatMessage[],
  isStreaming: boolean,
  fallbackDomain = '',
): StudioTaskUnderstanding | null {
  const content = messages.find((message) => message.role === 'user')?.content.trim()
  if (!content) return null
  const domain = DOMAIN_PATTERNS.find(({ pattern }) => pattern.test(content))?.label || fallbackDomain
  if (!domain) return null

  const normalized = content.replace(/\s+/g, ' ').trim()
  if (normalized.length < 8) return null
  const task = normalized.length > 52 ? `${normalized.slice(0, 52)}…` : normalized
  const goalMatch = normalized.match(/(?:请|帮我|需要|目标是|希望)(.+?)(?:[。！？]|$)/)
  const goal = (goalMatch?.[1] || normalized).trim()
  if (goal.length < 4) return null

  return {
    task,
    domain,
    goal: goal.length > 80 ? `${goal.slice(0, 80)}…` : goal,
    status: isStreaming ? '执行中' : '已理解',
  }
}

const TOOL_LABELS: Array<{ pattern: RegExp; label: string; icon: string }> = [
  { pattern: /read_file|readfile|file_read/i, label: '读取数据文件', icon: '▤' },
  { pattern: /write_file|writefile|file_write|artifact_register/i, label: '生成分析结果', icon: '◇' },
  { pattern: /shell|bash|terminal|execute|run_code|python|rscript/i, label: '执行分析命令', icon: '⌘' },
  { pattern: /studio|sandbox|workspace/i, label: '沙盒分析环境', icon: '▣' },
  { pattern: /ask_user|clarif/i, label: '向用户确认信息', icon: '?' },
  { pattern: /knowledge_search|search_knowledge/i, label: '检索平台知识库', icon: '⌕' },
  { pattern: /web_search|search_web|literature|pubmed/i, label: '检索文献与资料', icon: '⌕' },
]

export function researchToolMeta(tool: ToolCall) {
  const matched = TOOL_LABELS.find(({ pattern }) => pattern.test(tool.name))
  const durationMs = Number(tool.uiPayload?.duration_ms ?? tool.uiPayload?.elapsed_ms ?? 0)
  return {
    label: matched?.label || tool.name,
    icon: matched?.icon || '·',
    duration: durationMs > 0
      ? durationMs >= 1000 ? `${(durationMs / 1000).toFixed(1)} 秒` : `${Math.round(durationMs)} 毫秒`
      : tool.status === 'running' || tool.status === 'pending' ? '计时中' : '耗时未记录',
  }
}

export function summarizeToolResult(result: unknown): string {
  if (result === undefined || result === null || result === '') return '暂无结果摘要'
  const value = typeof result === 'string' ? result : JSON.stringify(result)
  return value.length > 240 ? `${value.slice(0, 240)}…` : value
}
