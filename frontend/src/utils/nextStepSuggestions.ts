/**
 * 建议追问 Chips（Suggested Follow-ups）阶段 1 的正则解析兜底：
 * 从 assistant 回复的 Markdown 中定位"可选下一步"章节，提取其下有序列表项，
 * 拆出短标签（label）与可直接发送的完整文案（prompt），并按关键词判定点击行为
 * （action：需要用户补充文件/路径等信息的条目用 prefill，其余直接 send）。
 *
 * 解析不到任何条目时返回空数组——调用方据此不渲染组件，静默降级。
 * 阶段 2 上线结构化 suggestions 字段后，本函数仅作降级路径。
 */

export interface SuggestedFollowUp {
  /** 胶囊上展示的短标签（≤12 字，超出截断） */
  label: string
  /** 点击后发送 / 填入输入框的完整文案（条目全文） */
  prompt: string
  /** send=直接作为用户消息发送；prefill=填入输入框待用户补充 */
  action: 'send' | 'prefill'
}

/** 单个消息最多渲染的建议条数 */
export const MAX_SUGGESTIONS = 4

/** label 最大长度（超出截断并加省略号） */
const LABEL_MAX_LENGTH = 12

/** 章节标题变体（正则特殊字符已转义，用于 includes 匹配） */
const SECTION_TITLES = [
  '可选下一步',
  '下一步建议',
  '可选的下一步',
  '下一步可选',
  '后续建议',
  '后续可选',
  '接下来可以',
]

/** 命中任一关键词即判定为 prefill（需要用户提供文件/路径等补充信息） */
const PREFILL_KEYWORDS = ['提供', '上传', '文件', '路径']

/** 有序列表项行：`1. xxx`、`2、xxx`、`3) xxx`，允许引用/列表前缀与全角括号 */
const ORDERED_ITEM_RE = /^\s*(?:>\s*)?\d{1,2}\s*[.、)）]\s*(.+?)\s*$/

/** 章节标题行允许的最大长度（去掉 Markdown 装饰后），避免把正文长句误判为标题 */
const SECTION_TITLE_MAX_LENGTH = 24

/** 去掉一行的 Markdown 装饰（标题/加粗/引用/横线符号与首尾冒号），用于标题匹配 */
function normalizeHeadingLine(line: string): string {
  return line
    .replace(/^[#>\s*-]+/, '')
    .replace(/[*_`]/g, '')
    .replace(/[:：\s]+$/, '')
    .trim()
}

/** 去掉条目文本中的行内 Markdown（加粗、行内代码、链接保留文字） */
function stripInlineMarkdown(text: string): string {
  return text
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`]/g, '')
    .trim()
}

/** label 取冒号/破折号前的短名；无分隔符或前缀超长时截断前 12 字 */
function extractLabel(text: string): string {
  let cut = -1
  for (const separator of ['：', ':', '—', '–', ' - ']) {
    const idx = text.indexOf(separator)
    if (idx > 0 && (cut < 0 || idx < cut)) cut = idx
  }
  const base = cut > 0 ? text.slice(0, cut).trim() : text
  if (!base) return text.slice(0, LABEL_MAX_LENGTH)
  return base.length > LABEL_MAX_LENGTH ? `${base.slice(0, LABEL_MAX_LENGTH)}…` : base
}

function extractItems(sectionLines: string[]): string[] {
  const items: string[] = []
  for (const line of sectionLines) {
    const trimmed = line.trim()
    const itemMatch = ORDERED_ITEM_RE.exec(line)
    if (itemMatch) {
      const text = stripInlineMarkdown(itemMatch[1])
      if (text) items.push(text)
      continue
    }
    if (!trimmed) continue // 允许条目间空行
    // 命中下一个标题 / 分割线 / 已开始收集后的普通段落：章节列表到此结束
    if (/^#{1,6}\s/.test(trimmed) || /^(-{3,}|\*{3,})$/.test(trimmed)) break
    if (items.length > 0) break
  }
  return items
}

/**
 * 解析 assistant 回复 Markdown 末尾的"可选下一步"编号列表。
 * 任何解析失败（无该章节、无有效条目、异常输入）都返回空数组，不抛错。
 */
export function parseNextStepSuggestions(markdown: string): SuggestedFollowUp[] {
  try {
    if (!markdown || typeof markdown !== 'string') return []
    const lines = markdown.split('\n')

    // 定位"可选下一步"章节标题行（取最后一个，正文引用前文标题时以末尾章节为准）
    let headerIndex = -1
    for (let i = 0; i < lines.length; i++) {
      const normalized = normalizeHeadingLine(lines[i])
      if (
        normalized.length > 0 &&
        normalized.length <= SECTION_TITLE_MAX_LENGTH &&
        SECTION_TITLES.some((title) => normalized.includes(title))
      ) {
        headerIndex = i
      }
    }
    if (headerIndex < 0) return []

    const items = extractItems(lines.slice(headerIndex + 1))
    return items.slice(0, MAX_SUGGESTIONS).map((text) => ({
      label: extractLabel(text),
      prompt: text,
      action: PREFILL_KEYWORDS.some((keyword) => text.includes(keyword)) ? 'prefill' : 'send',
    }))
  } catch {
    return []
  }
}

/**
 * 阶段 2 结构化通道：校验后端 done 事件 / 历史消息 metadata 里的 suggestions 字段。
 * 只接受形状完整的条目（label/prompt 非空、action 合法），action 以字段值为准，
 * 不再走关键词判定；任何异常输入返回空数组，不抛错。
 */
export function normalizeSuggestions(value: unknown): SuggestedFollowUp[] {
  try {
    if (!Array.isArray(value)) return []
    return value.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const raw = item as Record<string, unknown>
      const label = typeof raw.label === 'string' ? raw.label.trim() : ''
      const prompt = typeof raw.prompt === 'string' ? raw.prompt.trim() : ''
      if (!label || !prompt) return []
      const action: SuggestedFollowUp['action'] = raw.action === 'prefill' ? 'prefill' : 'send'
      return [{ label, prompt, action }]
    }).slice(0, MAX_SUGGESTIONS)
  } catch {
    return []
  }
}
