type MessageRecord = {
  role?: unknown
  type?: unknown
  message_type?: unknown
  content?: unknown
  visible?: unknown
  agent_name?: unknown
  agentName?: unknown
  metadata?: unknown
  metadata_json?: unknown
}

const INTERNAL_MESSAGE_TYPES = new Set([
  'suggestion',
  'routing',
  'tool_call',
  'system_notice_internal',
])

const INTERNAL_SUGGESTION_KEYWORDS = [
  '建议升级为协作室协作',
  '该需求命中',
  '审批与质量闸门',
  '多步骤真实计算',
]

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? value as Record<string, unknown> : undefined
}

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === 'string' && value.length > 0)
}

/**
 * Single visibility policy shared by live messages and persisted history.
 * The policy intentionally does not hide ordinary user-facing system notices.
 */
export function isUserVisibleMessage(message: MessageRecord): boolean {
  const metadata = asRecord(message.metadata) || asRecord(message.metadata_json)
  if (message.visible === false || metadata?.visible === false) return false

  const type = firstString(message.type, message.message_type, metadata?.type, metadata?.message_type)
    ?.trim()
    .toLowerCase()
  if (type && INTERNAL_MESSAGE_TYPES.has(type)) return false

  const role = typeof message.role === 'string' ? message.role.toLowerCase() : ''
  const agentName = firstString(message.agent_name, message.agentName, metadata?.agent_name, metadata?.agentName)
    ?.trim()
    .toLowerCase()
  const content = typeof message.content === 'string' ? message.content : ''
  const isOmicHubInternalAgent = agentName === 'omichub ai'
  const hasInternalSuggestion = INTERNAL_SUGGESTION_KEYWORDS.some((keyword) => content.includes(keyword))

  if (role === 'system' && isOmicHubInternalAgent) return false
  // 内容兜底覆盖旧实时协议：这几组短语只属于内部协作建议，且不应影响用户原话。
  if (hasInternalSuggestion && role !== 'user') return false

  return true
}

export function filterUserVisibleMessages<T extends MessageRecord>(messages: T[]): T[] {
  return messages.filter(isUserVisibleMessage)
}
