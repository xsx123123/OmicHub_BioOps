import type { AgentTeamsEvent, AgentTeamsRoleLabel } from '@/api/agentTeams'
import { formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'
import { resolveRoleIdentity } from '@/utils/roleIdentity'

export interface RoomSender {
  name: string
  avatar: string
  color: string
  role: 'manager' | 'worker'
}

export type RoomMessageKind = 'speech' | 'progress' | 'action' | 'system'

export interface RoomMessageAction {
  label: string
  action: string
}

export interface RoomToolInfo {
  name: string
  status: 'running' | 'ok' | 'failed'
  durationMs?: number
}

/** Manager 回复中的结构化 JSON 信封（解析自 ```json 代码块或裸 JSON）。 */
export interface ManagerReport {
  conclusion: string
  recommendations: string[]
  risks: string[]
  evidenceRefs: string[]
  hardGate?: Record<string, unknown>
  /** Manager 派单时携带的 proposed_submission 结构化信封（如代码/可视化任务工单）。 */
  proposedSubmission?: Record<string, unknown>
}

/** worker 卡片终态：由真实终态事件投影而来，决定卡片状态徽标。 */
export type RoomWorkItemTerminal = 'finished' | 'failed' | 'interrupted'

export interface RoomMessage {
  id: string
  sender: RoomSender
  kind: RoomMessageKind
  content: string
  round?: number
  collapsed?: boolean
  /** progress 行对应的结构化工具调用信息（用于房间卡片内联进度行）。 */
  tool?: RoomToolInfo
  /** 关联的工作项 ID（claim / running / 终态事件携带）。 */
  workItemId?: string
  /** 工作项开场占位消息（claim / running），按 workItemId 去重合并。 */
  workItemStart?: boolean
  /** 工作项真实终态（skill.finished / skill.failed / 租约过期重排队）。 */
  terminal?: RoomWorkItemTerminal
  /** Manager 回复解析出的结构化信封；存在时前端做结构化渲染。 */
  managerReport?: ManagerReport
  /** 当前用户本人的发言（room.user_message 投影）：时间线上右对齐渲染。 */
  isUser?: boolean
  /** worker 执行产生的图片、PDF、表格等工作区产物。 */
  artifacts?: unknown
  /** 技术详情：原始错误、英文 schema 校验信息等，折叠展示。 */
  technicalDetail?: string
  /** 动作按钮：重试 / 修改需求 / 终止 Case 等。 */
  actions?: RoomMessageAction[]
}

/** role_labels / role_agent_map 均可选：端点未接通时用本地兜底身份渲染。 */
export interface RoomRoleMetadata {
  role_labels?: Record<string, AgentTeamsRoleLabel>
  role_agent_map?: Record<string, string>
}

const SYSTEM_SENDER: RoomSender = { name: '系统', avatar: '⚙️', color: '#64748b', role: 'worker' }
const MANAGER_FALLBACK: RoomSender = { name: 'Manager', avatar: '🧭', color: '#4f8ef7', role: 'manager' }
const QC_FALLBACK: RoomSender = { name: '质量审计员', avatar: '🛡️', color: '#d97706', role: 'worker' }
const USER_SENDER: RoomSender = { name: '我', avatar: '🧑‍💻', color: '#4f8ef7', role: 'manager' }

/** 工具 display name 映射：命中时展示中文，未命中时保留原始工具名。 */
const TOOL_DISPLAY_NAMES: Record<string, string> = {
  workspace_file_preview: '读取文件',
  workspace_read_file: '读取文件',
  sandbox_execute: '沙箱执行',
  pipeline_query: '查询流程',
}

/** 技能 display name 映射：避免 planning_advice 等内部 snake_case 名直出。 */
const SKILL_DISPLAY_NAMES: Record<string, string> = {
  planning_advice: '生成执行计划',
  project_preflight: '项目预检',
  artifact_inspect: '产物检查',
}

function pickString(payload: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = payload[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

/**
 * 聊天 Case 执行意图触发时，后端会在 objective 尾部拼接通用计划契约
 * （以"请输出 proposed_submission"开头，见 agentteams_execution_intent.py）。
 * 房间内只展示用户原话部分，契约 JSON 不外泄。
 */
const PLAN_CONTRACT_MARKER = '请输出 proposed_submission'

function stripPlanContract(objective: string): string {
  const index = objective.indexOf(PLAN_CONTRACT_MARKER)
  return (index >= 0 ? objective.slice(0, index) : objective).trim()
}

function normalizeRole(role: string | undefined): 'manager' | 'worker' {
  return role === 'manager' ? 'manager' : 'worker'
}

/** actor 是 role identity（如 agent-data / data-steward）；先查 role_labels，
 *  再经 role_agent_map 归并别名到 canonical role，最后用本地兜底身份。 */
export function resolveRoomSender(actor: string, metadata: RoomRoleMetadata = {}): RoomSender {
  const labels = metadata.role_labels || {}
  const direct = labels[actor]
  if (direct) {
    return {
      name: direct.name || actor,
      avatar: direct.avatar || '💬',
      color: direct.color || '#64748b',
      role: normalizeRole(direct.role),
    }
  }
  const agentId = metadata.role_agent_map?.[actor]
  if (agentId) {
    const viaAgent = Object.values(labels).find((label) => label.agent_id === agentId)
    if (viaAgent) {
      return {
        name: viaAgent.name || agentId,
        avatar: viaAgent.avatar || '💬',
        color: viaAgent.color || '#64748b',
        role: normalizeRole(viaAgent.role),
      }
    }
    return resolveRoleIdentity(agentId)
  }
  if (/manager|planner|router/i.test(actor)) return MANAGER_FALLBACK
  return resolveRoleIdentity(actor)
}

function resolveQualitySender(actor: string, metadata: RoomRoleMetadata): RoomSender {
  if (actor && (metadata.role_labels?.[actor] || metadata.role_agent_map?.[actor])) {
    return resolveRoomSender(actor, metadata)
  }
  const labels = metadata.role_labels || {}
  const qc = Object.values(labels).find((label) => label.agent_id === 'agent-qc')
  if (qc) {
    return {
      name: qc.name || QC_FALLBACK.name,
      avatar: qc.avatar || QC_FALLBACK.avatar,
      color: qc.color || QC_FALLBACK.color,
      role: 'worker',
    }
  }
  return actor ? resolveRoomSender(actor, metadata) : QC_FALLBACK
}

const OMIC_TASK_LABELS: Record<string, string> = {
  'omic_task.submitted': 'OmicHub 任务已提交',
  'omic_task.status_changed': '任务状态已回传',
  'omic_task.completed': '任务已完成，转入质量核验',
  'omic_task.failed': '任务执行失败',
  'omic_task.cancelled': '任务已取消',
}

function truncate(text: string, limit = 200): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0)
}

/** 从 Manager 回复文本中抽取 JSON 候选并解析：优先 ```json 代码块，
 *  其次整段裸 JSON，最后尝试文本中首个 { 到末个 } 的子串。 */
function extractJsonEnvelope(content: string): Record<string, unknown> | null {
  const candidates: string[] = []
  const fenced = content.match(/```(?:json)?\s*\n?([\s\S]*?)```/i)
  if (fenced) candidates.push(fenced[1].trim())
  const trimmed = content.trim()
  candidates.push(trimmed)
  const start = trimmed.indexOf('{')
  const end = trimmed.lastIndexOf('}')
  if (start !== -1 && end > start) candidates.push(trimmed.slice(start, end + 1))
  for (const candidate of candidates) {
    if (!candidate.startsWith('{')) continue
    try {
      const parsed: unknown = JSON.parse(candidate)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // 尝试下一个候选
    }
  }
  return null
}

/** 解析 Manager 回复里的结构化信封（conclusion / recommendations / risks /
 *  evidence_refs / hard_gate / proposed_submission）；解析不出任何有效字段时返回 null，调用方回退纯文本。 */
export function parseManagerReport(content: string): ManagerReport | null {
  const envelope = extractJsonEnvelope(content)
  if (!envelope) return null
  const conclusion = pickString(envelope, ['conclusion'])
  const recommendations = toStringList(envelope.recommendations)
  const risks = toStringList(envelope.risks)
  const evidenceRefs = toStringList(envelope.evidence_refs)
  const hardGate =
    envelope.hard_gate && typeof envelope.hard_gate === 'object' && !Array.isArray(envelope.hard_gate)
      ? (envelope.hard_gate as Record<string, unknown>)
      : undefined
  const proposedSubmission =
    envelope.proposed_submission &&
    typeof envelope.proposed_submission === 'object' &&
    !Array.isArray(envelope.proposed_submission)
      ? (envelope.proposed_submission as Record<string, unknown>)
      : undefined
  if (
    !conclusion &&
    !recommendations.length &&
    !risks.length &&
    !evidenceRefs.length &&
    !hardGate &&
    !proposedSubmission
  ) {
    return null
  }
  return { conclusion, recommendations, risks, evidenceRefs, hardGate, proposedSubmission }
}

/** hard_gate 信封的醒目提示文案：优先 decision + reason（含 audit_event.reason）。 */
export function formatHardGate(hardGate: Record<string, unknown>): string {
  const decision = pickString(hardGate, ['decision'])
  const audit =
    hardGate.audit_event && typeof hardGate.audit_event === 'object'
      ? (hardGate.audit_event as Record<string, unknown>)
      : undefined
  const reason = pickString(hardGate, ['reason', 'summary']) || (audit ? pickString(audit, ['reason', 'summary']) : '')
  const head = decision ? `质量硬门禁 ${decision}` : '质量硬门禁已触发'
  return reason ? `${head}：${reason}` : head
}

/** skill.finished payload 没有 conclusion/summary 时，从 findings 列表提炼正文。 */
function summarizeFindings(value: unknown): string {
  if (!Array.isArray(value)) return ''
  const messages = value
    .map((item) =>
      item && typeof item === 'object' ? pickString(item as Record<string, unknown>, ['message', 'title', 'summary']) : '',
    )
    .filter((item) => item.length > 0)
  if (!messages.length) return ''
  const head = messages.slice(0, 3).join('；')
  return messages.length > 3 ? `${head}；等 ${messages.length} 项发现` : head
}

/** 将工具名映射为用户可见文案；未命中时返回原始工具名。 */
export function formatToolName(tool: string): string {
  return TOOL_DISPLAY_NAMES[tool] || tool
}

/** 将技能名映射为用户可见文案；未命中时返回通用描述，避免 snake_case 直出。 */
export function formatSkillName(skillName: string): string {
  return SKILL_DISPLAY_NAMES[skillName] || '处理子任务'
}

/** 把 @workspace/path/file.treefile 这类引用渲染为高亮 pill（HTML）。 */
export function formatMentions(content: string): string {
  const escaped = content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped.replace(/@(\S+)/g, '<span class="mention-chip">@$1</span>')
}

/** 格式化耗时：≥5s 显示为秒，否则显示毫秒。 */
export function formatDuration(durationMs?: number): string {
  if (durationMs === undefined || Number.isNaN(durationMs)) return ''
  if (durationMs >= 5000) {
    return `${(durationMs / 1000).toFixed(1)}s`
  }
  return `${Math.round(durationMs)}ms`
}

const SENTENCE_END_RE = /[。！？.!?]$/

/** 判断发言内容是否可能已被截断（非句末标点结尾）。 */
export function isContentTruncated(content: string): boolean {
  return !!content && !SENTENCE_END_RE.test(content.trim())
}

/** 把 Bridge case event 投影成房间消息；不在投影表内的事件返回 null（丢弃）。 */
export function projectCaseEvent(
  event: AgentTeamsEvent,
  metadata: RoomRoleMetadata = {},
): RoomMessage | null {
  const { event_id, event_type, actor, payload } = event
  const body = payload || {}

  if (event_type === 'room.user_message') {
    // 证据事件的内容嵌套在 audit payload.payload 内；summary 是截断兜底。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const content = pickString(inner, ['content']) || pickString(body, ['summary'])
    if (!content) return null
    return { id: event_id, sender: USER_SENDER, kind: 'speech', content, isUser: true }
  }

  if (event_type === 'room.agent_message') {
    // Manager 回复：audit actor 是 bioops-manager，经 role_labels/兜底渲染为协作经理气泡。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const content = pickString(inner, ['content']) || pickString(body, ['summary'])
    if (!content) return null
    const sender = resolveRoomSender(actor || 'bioops-manager', metadata)
    // Manager 回复链路可能把整段 JSON 信封塞进 content；能解析出结构化字段时
    // 交给前端做结论/建议/风险/硬门禁的结构化展示，解析失败回退纯文本气泡。
    const managerReport = sender.role === 'manager' ? parseManagerReport(content) : null
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: truncate(content, 2_000),
      ...(managerReport ? { managerReport } : {}),
    }
  }

  if (event_type === 'room.created') {
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: '协作房间已创建，房间进展将同步到 Matrix。',
      collapsed: true,
    }
  }

  if (event_type === 'case.created') return null

  if (event_type === 'planning.frozen') {
    const plan = pickString(body, ['plan_description', 'summary', 'description', 'objective'])
    const qualityGate = body.quality_gate_required === true
    return {
      id: event_id,
      sender: resolveRoomSender(actor || 'manager', metadata),
      kind: 'speech',
      content: plan || `规划完成，正在执行分析与解读。${qualityGate ? '并将进行质量检查。' : ''}`,
    }
  }

  if (event_type === 'work_item.assigned') {
    const target = pickString(body, ['target', 'assignee', 'role'])
    const targetName = target ? resolveRoomSender(target, metadata).name : '协作成员'
    const rawObjective = stripPlanContract(pickString(body, ['objective']))
    const rawSkillName = pickString(body, ['skill_name'])
    const objective = rawObjective || (rawSkillName ? formatSkillName(rawSkillName) : '')
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: `Manager 将任务分派给 ${targetName}${objective ? `：${objective}` : ''}`,
    }
  }

  if (event_type === 'work_item.claimed' || event_type === 'work_item.running' || event_type === 'agent.started') {
    const rawObjective = stripPlanContract(pickString(body, ['objective', 'summary']))
    const rawSkillName = pickString(body, ['skill_name'])
    const objective = rawObjective || (rawSkillName ? formatSkillName(rawSkillName) : '')
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'speech',
      content: objective ? `开始处理：${objective}` : '已领取任务，开始处理。',
      ...(workItemId ? { workItemId, workItemStart: true } : {}),
    }
  }

  if (event_type === 'agent.tool_call') {
    // 证据事件经 Bridge 审计包装，工具字段在内层 payload.payload（同 room 消息事件）
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const rawTool = pickString(inner, ['tool', 'tool_name', 'name']) || pickString(body, ['tool', 'tool_name', 'name'])
    const tool = rawTool ? formatToolName(rawTool) : ''
    if (!tool) return null
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'progress',
      content: `正在调用 ${tool}`,
      tool: { name: tool, status: 'running' },
    }
  }

  if (event_type === 'agent.tool_result' || event_type === 'agent.finished') {
    // 同上：tool/status/success/duration_ms 均在内层 payload.payload
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const rawTool = pickString(inner, ['tool', 'tool_name', 'name']) || pickString(body, ['tool', 'tool_name', 'name'])
    const tool = rawTool ? formatToolName(rawTool) : ''
    if (!tool) return null
    const status = pickString(inner, ['status']) || pickString(body, ['status'])
    const failed = status === 'failed' || status === 'error' || inner.success === false || body.success === false
    const rawDuration = typeof inner.duration_ms === 'number' ? inner.duration_ms : body.duration_ms
    const durationMs = typeof rawDuration === 'number' ? Math.round(rawDuration) : undefined
    const duration = durationMs !== undefined ? `（${formatDuration(durationMs)}）` : ''
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'progress',
      content: `${tool} ${failed ? '调用失败' : '调用完成'}${duration}`,
      tool: { name: tool, status: failed ? 'failed' : 'ok', durationMs },
    }
  }

  if (event_type === 'skill.finished') {
    const conclusion =
      pickString(body, ['conclusion', 'summary', 'result']) || summarizeFindings(body.findings)
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'speech',
      content: truncate(conclusion || '已完成本阶段任务。'),
      terminal: 'finished',
      ...(body.artifacts !== undefined ? { artifacts: body.artifacts } : {}),
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'skill.failed') {
    // 投影为带终态标记的 worker 发言：进入同一 work_item 的卡片并把错误信息作为卡片正文。
    const reason = pickString(body, ['error', 'reason', 'summary'])
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'speech',
      content: truncate(reason ? `任务执行失败：${reason}` : '任务执行失败。'),
      terminal: 'failed',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'skill.manual_review') {
    const reason = pickString(body, ['error', 'reason', 'summary'])
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'action',
      content: truncate(reason ? `任务需要人工复核：${reason}` : '任务需要人工复核。'),
    }
  }

  if (event_type === 'work_item.lease_expired') {
    // 租约过期、工作项被重新排队：卡片进入「已中断/重新排队」态。
    const reason = pickString(body, ['reason', 'error', 'summary'])
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: actor ? resolveRoomSender(actor, metadata) : SYSTEM_SENDER,
      kind: 'speech',
      content: truncate(reason ? `任务租约过期，已中断并重新排队：${reason}` : '任务租约过期，已中断并重新排队。'),
      terminal: 'interrupted',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'work_item.retry_scheduled') {
    const delay = typeof body.delay_seconds === 'number' ? Math.round(body.delay_seconds) : undefined
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const timing = delay !== undefined ? `将在 ${delay} 秒后重试` : '已安排稍后重试'
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（第 ${attempt}/${maxAttempts} 次尝试）` : ''
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: `任务${timing}${progress}`,
    }
  }

  if (event_type === 'work_item.retry_exhausted') {
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（${attempt}/${maxAttempts}）` : ''
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'action',
      content: `任务重试已达上限${progress}，请人工选择重试、跳过或终止。`,
    }
  }

  if (event_type === 'correction_started') {
    const missingFields = toStringList(body.missing_fields)
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（第 ${attempt}/${maxAttempts} 次）` : ''
    const fieldsText = missingFields.length ? `：缺少 ${missingFields.join('/')}${progress}` : progress
    return {
      id: event_id,
      sender: resolveRoomSender(actor || 'bioops-manager', metadata),
      kind: 'action',
      content: `自动修正计划${fieldsText}`,
    }
  }

  if (event_type === 'correction_applied') {
    const reason = pickString(body, ['reason'])
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（第 ${attempt}/${maxAttempts} 次）` : ''
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: reason ? `已根据校验反馈重新生成计划${progress}：${reason}` : `已根据校验反馈重新生成计划${progress}`,
    }
  }

  if (event_type === 'correction_failed') {
    const reason = pickString(body, ['reason'])
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（${attempt}/${maxAttempts}）` : ''
    const nextActions = toStringList(body.next_actions)
    const availableActions: RoomMessageAction[] = []
    if (nextActions.includes('retry')) availableActions.push({ label: '重试', action: 'retry' })
    if (nextActions.includes('revise')) availableActions.push({ label: '修改需求', action: 'revise' })
    if (nextActions.includes('cancel')) availableActions.push({ label: '终止 Case', action: 'cancel' })
    return {
      id: event_id,
      sender: resolveRoomSender(actor || 'bioops-manager', metadata),
      kind: 'action',
      content: `计划自动修正已达上限${progress}：${reason || '未知原因'}。请重试、修改需求或终止 Case。`,
      technicalDetail: reason || undefined,
      actions: availableActions.length ? availableActions : [
        { label: '重试', action: 'retry' },
        { label: '修改需求', action: 'revise' },
        { label: '终止 Case', action: 'cancel' },
      ],
    }
  }

  if (event_type === 'planning.validation_failed') {
    // Case 会停在 waiting_for_correction；时间线必须解释原因。
    const reason = pickString(body, ['error', 'reason', 'summary'])
    const attempt = typeof body.attempt === 'number' ? body.attempt : undefined
    const maxAttempts = typeof body.max_attempts === 'number' ? body.max_attempts : undefined
    const retryExhausted = body.retry_exhausted === true
    if (retryExhausted) {
      const progress = attempt !== undefined && maxAttempts !== undefined ? `（${attempt}/${maxAttempts}）` : ''
      return {
        id: event_id,
        sender: resolveRoomSender(actor || 'bioops-manager', metadata),
        kind: 'action',
        content: `计划自动修正已达上限${progress}：${reason || '未知原因'}。请重试、修改需求或终止 Case。`,
        technicalDetail: reason || undefined,
        actions: [
          { label: '重试', action: 'retry' },
          { label: '修改需求', action: 'revise' },
          { label: '终止 Case', action: 'cancel' },
        ],
      }
    }
    const progress = attempt !== undefined && maxAttempts !== undefined ? `（第 ${attempt}/${maxAttempts} 次）` : ''
    return {
      id: event_id,
      sender: resolveRoomSender(actor || 'bioops-manager', metadata),
      kind: 'action',
      content: `计划生成不完整，正在自动重试${progress}`,
      technicalDetail: reason || undefined,
    }
  }

  if (event_type === 'planning.revised') {
    const version = typeof body.plan_version === 'number' ? body.plan_version : undefined
    const reason = pickString(body, ['reason'])
    const head = version !== undefined ? `执行计划已修订（版本 ${version}）` : '执行计划已修订'
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: truncate(reason ? `${head}：${reason}` : head),
    }
  }

  if (event_type === 'case.execution_failed') {
    const error = pickString(body, ['error_excerpt', 'error', 'summary'])
    const recommendation = pickString(body, ['recommendation'])
    const head = error ? `Case 执行失败：${error}` : 'Case 执行失败。'
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'action',
      content: truncate(recommendation ? `${head}。${recommendation}` : head, 400),
    }
  }

  if (event_type === 'case.retry_queued') {
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: '已按冻结计划重新排队，等待重试任务执行。',
    }
  }

  if (event_type === 'case.auto_approved') {
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: '已根据你的授权自动批准',
    }
  }

  if (event_type === 'node_timeout') {
    const node = pickString(body, ['node'])
    const elapsed = typeof body.elapsed_seconds === 'number' ? body.elapsed_seconds : undefined
    const nodeLabel = node === 'planning' ? '规划' : node === 'execution' ? '执行' : node || '当前'
    const elapsedText = elapsed !== undefined ? `，已耗时 ${formatDuration(Math.round(elapsed * 1000))}` : ''
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'action',
      content: `${nodeLabel}节点超时${elapsedText}，请检查网络或重试。`,
      actions: [{ label: '重试', action: 'retry' }],
    }
  }

  if (event_type === 'case.closed') {
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: 'Case 已交付并关闭。',
    }
  }

  if (event_type === 'quality.decision' || event_type === 'quality.hard_gate') {
    const conclusion = pickString(body, ['conclusion', 'summary', 'decision', 'reason'])
    const fallback = event_type === 'quality.decision' ? '质量门禁已给出结论。' : '质量硬门禁已触发。'
    return {
      id: event_id,
      sender: resolveQualitySender(actor, metadata),
      kind: 'speech',
      content: truncate(conclusion || fallback),
    }
  }

  if (event_type === 'case.cancelled' || event_type === 'case.state_changed') {
    let content: string
    if (event_type === 'case.cancelled') {
      const reason = pickString(body, ['reason'])
      content = `Case 已取消${reason ? `：${reason}` : ''}`
    } else {
      const from = pickString(body, ['from', 'previous_status'])
      const to = pickString(body, ['to', 'status', 'new_status'])
      content = to
        ? `Case 状态更新：${from ? `${formatAgentTeamsStatus(from)} → ` : ''}${formatAgentTeamsStatus(to)}`
        : 'Case 状态已更新'
    }
    return { id: event_id, sender: SYSTEM_SENDER, kind: 'system', content }
  }

  if (event_type.startsWith('omic_task.')) {
    const label = OMIC_TASK_LABELS[event_type] || 'OmicHub 任务状态变更'
    const detail = pickString(body, ['summary', 'status', 'omic_task_id'])
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: detail ? `${label}（${detail}）` : label,
      collapsed: true,
    }
  }

  return null
}

/** 将一批事件投影为房间消息列表（丢弃不在投影表内的事件，保持原顺序）。
 *  同一 work_item_id 的重复 claim/running 占位消息在此去重：保留首次认领
 *  （attempt 变化视为合法重试，予以保留），其余重复占位合并掉，避免时间线上
 *  出现两张几乎相同的 worker 卡片。 */
export function projectCaseEvents(
  events: AgentTeamsEvent[],
  metadata: RoomRoleMetadata = {},
): RoomMessage[] {
  const messages: RoomMessage[] = []
  const startAttempts = new Map<string, number>()
  // 按 recorded_at 排序：Bridge 事件可能因并发投递或分页合并导致顺序与发生顺序不一致，
  // 前端按时间戳归位后再投影，确保工具调用证据出现在最终结论之前。
  const sorted = [...events].sort((a, b) => {
    const timeA = Date.parse(a.recorded_at) || 0
    const timeB = Date.parse(b.recorded_at) || 0
    if (timeA !== timeB) return timeA - timeB
    // 时间戳相同时保持原始数组顺序，避免打乱同一毫秒内的逻辑先后。
    return events.indexOf(a) - events.indexOf(b)
  })
  for (const event of sorted) {
    const message = projectCaseEvent(event, metadata)
    if (!message) continue
    if (message.workItemStart && message.workItemId) {
      const rawAttempt = event.payload?.attempt
      const attempt = typeof rawAttempt === 'number' ? rawAttempt : -1
      const seen = startAttempts.get(message.workItemId)
      // attempt 缺失（running 占位）或与首次认领相同 → 视为重复认领，合并。
      if (seen !== undefined && (attempt === -1 || attempt === seen)) continue
      startAttempts.set(message.workItemId, attempt)
    }
    messages.push(message)
  }
  return messages
}

/** 从事件流解析当前 Case 的 Element 房间深链（Gateway 建房时随 room.created
 *  证据事件下发，已含 #/room/{room_id} 定位 fragment）。仅接受 http/https 绝对
 *  URL，取最新一条；未建房或 Gateway 未配置 Element 地址时返回 null。 */
export function resolveElementRoomUrl(events: AgentTeamsEvent[]): string | null {
  let url: string | null = null
  for (const event of events) {
    if (event.event_type !== 'room.created') continue
    const body = event.payload || {}
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const candidate = pickString(inner, ['room_url'])
    if (candidate && /^https?:\/\//i.test(candidate)) url = candidate
  }
  return url
}

/** typing 事件新鲜度窗口：超出后视为残留事件（进程崩溃等未闭环场景），不再显示。 */
export const MANAGER_TYPING_TTL_MS = 3 * 60_000

/** 聊天式创建的 intent 归一化：收敛空白并对齐后端 intent 上限（256 字符）。 */
export function buildRoomCreateIntent(content: string): string {
  return content.trim().replace(/\s+/g, ' ').slice(0, 256)
}

const PHYLOGENY_MARKERS = ['系统发育树', '系统进化树', '进化树', 'treeplot', 'phylogenetic', 'treefile', 'newick']
const PHYLOGENY_ACTION_MARKERS = ['做', '画', '绘制', '构建', '建树', '分析', '可视化', '美化']

/** 当前房间目标与新的树文件执行请求明显不一致时，另起 Case，避免旧目标污染规划。 */
export function shouldStartNewRoomCase(
  currentIntent: string,
  content: string,
  contextRefs: Array<{ kind: string; id: string; location?: string }> = [],
): boolean {
  const normalizedIntent = currentIntent.toLowerCase()
  // @ 引用会把文件路径（含 .treefile 后缀）替换进正文；先剥离 mention 路径再匹配关键词，
  // 否则"引用任意 treefile + 可视化"这类普通发言几乎必中 treefile 标记而被误拆分。
  const normalizedContent = content.toLowerCase().replace(/@\S+/g, ' ')
  if (PHYLOGENY_MARKERS.some((marker) => normalizedIntent.includes(marker))) return false
  const asksForPhylogeny = PHYLOGENY_MARKERS.some((marker) => normalizedContent.includes(marker))
  const asksForExecution = PHYLOGENY_ACTION_MARKERS.some((marker) => normalizedContent.includes(marker))
  const referencesTreeFile = contextRefs.some((ref) =>
    /\.(treefile|nwk|newick|tree|contree)$/i.test(ref.location || ref.id),
  )
  return asksForPhylogeny && asksForExecution && referencesTreeFile
}

/** 从原始事件流推导 Manager "正在输入"态：最后一条 room.typing 为 true 且未过期，
 *  且其间没有 room.agent_message（回复到达即输入结束）。 */
export function resolveManagerTyping(events: AgentTeamsEvent[], now: number = Date.now()): boolean {
  let typing = false
  let typingAt = 0
  for (const event of events) {
    if (event.event_type === 'room.typing') {
      const body = event.payload || {}
      const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
      typing = inner.typing === true
      typingAt = Date.parse(event.recorded_at) || 0
    } else if (event.event_type === 'room.agent_message') {
      typing = false
    }
  }
  return typing && typingAt > 0 && now - typingAt < MANAGER_TYPING_TTL_MS
}

export interface RoomWorkerStep {
  id: string
  tool: RoomToolInfo
  count: number
  collapsed: boolean
  details: Array<{ id: string; tool: RoomToolInfo }>
}

/** worker 卡片块：同一成员的连续 progress / 终态发言聚合为一张卡片。 */
export interface RoomWorkerBlock {
  type: 'worker'
  key: string
  sender: RoomSender
  /** 任务开场发言（如「开始处理：xxx」）。 */
  intro?: RoomMessage
  steps: RoomWorkerStep[]
  /** 无工具结构的 progress 行，按原样文本渲染。 */
  extraProgress: RoomMessage[]
  /** 终态发言（skill.finished / skill.failed / 租约过期等），作为卡片正文。 */
  body?: RoomMessage
  /** 进行中：尚未投影到任何真实终态事件。 */
  active: boolean
  /** 失败：收到 skill.failed 终态，或有工具步骤调用失败。 */
  failed: boolean
  /** 中断：租约过期等原因被重新排队。 */
  interrupted: boolean
}

export type RoomBlock =
  | { type: 'timeline'; message: RoomMessage }
  | { type: 'speech'; message: RoomMessage }
  | { type: 'action'; message: RoomMessage }
  | RoomWorkerBlock

/** 合并同一 worker 卡片内相邻的同名工具调用，点击可展开明细。 */
function foldWorkerSteps(steps: RoomWorkerStep[]): RoomWorkerStep[] {
  const folded: RoomWorkerStep[] = []
  for (const step of steps) {
    const last = folded[folded.length - 1]
    if (last && last.tool.name === step.tool.name) {
      last.count += 1
      last.details.push({ id: step.id, tool: step.tool })
      const statuses = last.details.map((d) => d.tool.status)
      if (statuses.includes('failed')) {
        last.tool.status = 'failed'
      } else if (statuses.includes('ok')) {
        last.tool.status = 'ok'
      } else {
        last.tool.status = 'running'
      }
      const totalDuration = last.details.reduce((sum, d) => (d.tool.durationMs !== undefined ? sum + d.tool.durationMs : sum), 0)
      if (last.details.some((d) => d.tool.durationMs !== undefined)) {
        last.tool.durationMs = totalDuration
      }
    } else {
      folded.push({
        id: step.id,
        tool: { ...step.tool },
        count: 1,
        collapsed: true,
        details: [{ id: step.id, tool: step.tool }],
      })
    }
  }
  return folded
}

/** 把扁平房间消息流聚合为渲染块：system → 时间轴节点，manager 发言 → 气泡，
 *  同一 worker 的连续 progress / 发言 → 工具进度卡片。 */
export function groupRoomMessages(messages: RoomMessage[]): RoomBlock[] {
  const blocks: RoomBlock[] = []
  let i = 0
  while (i < messages.length) {
    const message = messages[i]
    if (message.kind === 'system') {
      blocks.push({ type: 'timeline', message })
      i += 1
      continue
    }
    if (message.kind === 'action') {
      blocks.push({ type: 'action', message })
      i += 1
      continue
    }
    if (message.kind === 'speech' && message.sender.role === 'manager') {
      blocks.push({ type: 'speech', message })
      i += 1
      continue
    }
    if (message.kind === 'progress' || message.kind === 'speech') {
      const senderName = message.sender.name
      const run: RoomMessage[] = []
      while (i < messages.length) {
        const current = messages[i]
        const isWorkerItem = current.kind === 'progress' || (current.kind === 'speech' && current.sender.role === 'worker')
        if (!isWorkerItem || current.sender.name !== senderName) break
        run.push(current)
        i += 1
      }
      const rawSteps = run
        .filter((item) => item.kind === 'progress' && item.tool)
        .map((item) => ({
          id: item.id,
          tool: item.tool as RoomToolInfo,
          count: 1,
          collapsed: false,
          details: [{ id: item.id, tool: item.tool as RoomToolInfo }],
        }))
      const steps = foldWorkerSteps(rawSteps)
      const extraProgress = run.filter((item) => item.kind === 'progress' && !item.tool)
      const speeches = run.filter((item) => item.kind === 'speech')
      if (!steps.length && !extraProgress.length && speeches.length === 1) {
        // 孤立 worker 发言（如质量结论）不包卡片，直接气泡呈现；
        // 孤立终态发言（失败/中断）用红色 action 行突出。
        const only = speeches[0]
        blocks.push(only.terminal === 'failed' || only.terminal === 'interrupted'
          ? { type: 'action', message: only }
          : { type: 'speech', message: only })
        continue
      }
      // 卡片完成状态只认真实终态事件（skill.finished / skill.failed / 租约过期），
      // 不再以「最后一条是发言」推断完成，避免占位开场白造成假「已完成」。
      const terminalSpeeches = speeches.filter((item) => item.terminal !== undefined)
      const terminalSpeech = terminalSpeeches[terminalSpeeches.length - 1]
      const last = run[run.length - 1]
      const firstIsSpeech = run[0].kind === 'speech'
      const lastIsSpeech = last.kind === 'speech'
      const fallbackBody = lastIsSpeech && (!firstIsSpeech || speeches.length > 1)
        ? speeches[speeches.length - 1]
        : undefined
      blocks.push({
        type: 'worker',
        key: run[0].id,
        sender: message.sender,
        intro: firstIsSpeech && !run[0].terminal ? speeches[0] : undefined,
        steps,
        extraProgress,
        body: terminalSpeech ?? fallbackBody,
        failed: terminalSpeech?.terminal === 'failed' || steps.some((step) => step.tool.status === 'failed'),
        interrupted: terminalSpeech?.terminal === 'interrupted',
        active: terminalSpeech === undefined,
      })
      continue
    }
    i += 1
  }
  return blocks
}
