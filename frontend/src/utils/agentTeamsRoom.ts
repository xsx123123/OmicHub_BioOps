import type { AgentTeamsEvent, AgentTeamsRoleLabel } from '@/api/agentTeams'
import { formatAgentTeamsStatus } from '@/utils/agentTeamsStatus'
import { resolveRoleIdentity } from '@/utils/roleIdentity'

/** Manager 澄清卡片（room.ask_user 事件投影）：与 ai-chat 的 AskRequest 结构对齐，
 *  直接在房间时间线内复用 AskUserCard 交互组件。 */
export interface RoomAskQuestion {
  question: string
  options: string[]
}

export interface RoomAskRequest {
  questions: RoomAskQuestion[]
  /** 用户按问题顺序给出的答案；空串表示该问题被跳过。 */
  answers?: string[]
  answered?: boolean
  eventId?: string
  clarifyKind?: string
  objectRequired?: boolean
  submitting?: boolean
  submitted?: boolean
  answerStatus?: 'collected' | 'waiting_upload' | 'missing_object'
  workspaceCandidates?: Array<{ kind: 'workspace' | 'file'; id: string; location: string }>
}

/** 澄清回复用户消息的前缀标记：投影时据此把答案回填到对应 ask_user 卡片。 */
export const ROOM_ASK_REPLY_MARKER = '【澄清回复】'

/** 路由决策卡（room.route_decision 事件投影，优化项 O1）：后端只外显决策结果，不改路由逻辑。 */
export interface RoomRouteDecisionStage {
  key: string
  title: string
}

export interface RoomRouteDecisionOption {
  flowId: string | null
  label: string
  leadPlanner: string
  stages: number
}

export interface RoomRouteDecision {
  /** 编排路径：bridge_workflow（命中标准流程）/ overdrive（通用规划）。 */
  path: string
  flowId: string | null
  flowLabel: string
  matchedHints: string[]
  leadPlanner: string
  plannerScores: Record<string, number>
  estimatedStages: RoomRouteDecisionStage[]
  participants: string[]
  confidence: 'high' | 'ambiguous'
  options: RoomRouteDecisionOption[]
}

/** 咨询分诊转场卡（room.route_transition 事件投影）：纯咨询问题（CHAT 意图）由经理
 *  分诊给领域专家直答。与 room.route_decision（流程路径决策）语义隔离，不复用。 */
export interface RoomRouteTransition {
  fromAgentId: string
  fromName: string
  targetAgentId: string
  targetName: string
  reason: string
  /** 分诊置信度（0~1 或 0~100）；缺省/非数字时为 null，卡片不展示百分比。 */
  confidence: number | null
  trigger: string
  causationEventId: string
}

/** 回复来源标记：manager_triage 为经理分诊直答，direct_mention 为用户直接点名。
 *  旧消息无 routed_by 字段时为 undefined。 */
export type RoomRoutedBy = 'manager_triage' | 'direct_mention'

/** 立项确认卡（room.proposal_confirm 房间级事件投影，会话-工单解耦）：
 *  execute 意图不直接建 Case，先出卡；confirm 后才创建 Case 并绑定房间。 */
export interface RoomProposal {
  /** new_case：首次立项；followup：上一 Case 终态后的再立项。 */
  proposalKind: 'new_case' | 'followup'
  /** 一次性确认令牌。B1 起 token 不再经事件流分发（写入后即全出口脱敏），
   *  确认改凭 owner + pending 状态；本字段仅兼容旧事件，通常为 ''。 */
  confirmToken: string
  /** pending 可交互；其余为已消费只读态（superseded：被同一房间的更新提案覆盖）。 */
  status: 'pending' | 'confirmed' | 'modify_requested' | 'cancelled' | 'superseded'
  objective: string
  flowId: string
  flowLabel: string
  leadPlanner: string
  routePath: string
  participants: string[]
  estimatedStages: RoomRouteDecisionStage[]
  confidence: 'high' | 'ambiguous' | ''
  /** 修改需求时回填输入框的原始需求文本。 */
  originContent: string
  /** followup 卡关联的上一 Case id。 */
  sourceCaseId: string
  /** 后端下发的可选项：new_case 为 confirm/modify/cancel，followup 为 continue/new/cancel。 */
  options: string[]
  createdAt: string
  /** 本地提交中标记（不回投影，仅防重复点击）。 */
  submitting?: boolean
}

export interface RoomSender {
  name: string
  avatar: string
  color: string
  role: 'manager' | 'worker'
  /** 人格副标题（archetype），在发言头部以弱化样式展示。 */
  archetype?: string
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

/** 挂接在 speech 气泡上的单条工具/MCP 调用（Manager/直答专家应答过程）。 */
export interface RoomToolCall {
  id: string
  name: string
  status: 'running' | 'ok' | 'failed'
  durationMs?: number
  argsSummary?: string
  resultSummary?: string
}

/** 仅在技术事件视图中展示的、已截断的执行追踪字段。 */
export interface RoomDebugTrace {
  toolCallId?: string
  round?: number
  executionPath?: string
  argsSummary?: string
  resultSummary?: string
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

export interface RoomAgentHandoff {
  fromAgentId: string
  toAgentId: string
  workItemIds: string[]
  risks: string[]
  artifactRefs: string[]
  recommendedNextAction?: string
}

/** Manager 分派卡片（work_item.assigned 事件投影）：标题 + 接收方 + 任务说明结构化展示。 */
export interface RoomDispatchInfo {
  targetName: string
  objective: string
  skillName?: string
}

export interface RoomChangeAssessment {
  agentId: string
  workItemIds: string[]
  conclusion: string
  recommendations: string[]
  risks: string[]
  evidenceRefs: string[]
  decisionOptions: string[]
  decision?: string
}

/** worker 卡片终态：由真实终态事件投影而来，决定卡片状态徽标。 */
export type RoomWorkItemTerminal = 'finished' | 'failed' | 'interrupted'

export interface RoomMessage {
  id: string
  sender: RoomSender
  kind: RoomMessageKind
  content: string
  /** 模型推理增量；与 AI 助手的可折叠思考框一致。 */
  thought?: string
  /** 当前消息仍在接收模型增量。 */
  streaming?: boolean
  /** 增量事件与最终消息的关联标识。 */
  streamId?: string
  /** 增量期间保留的模型原始内容，仅用于提取可读的结构化正文。 */
  streamRawContent?: string
  round?: number
  collapsed?: boolean
  /** progress 行对应的结构化工具调用信息（用于房间卡片内联进度行）。 */
  tool?: RoomToolInfo
  /** 该发言气泡内联展示的工具/MCP 调用列表（与 AI 助手气泡内工具卡片一致）。 */
  toolCalls?: RoomToolCall[]
  /** 用于调试模式的调用关联信息，默认不展开。 */
  debugTrace?: RoomDebugTrace
  /** 关联的工作项 ID（claim / running / 终态事件携带）。 */
  workItemId?: string
  /** 工作项开场占位消息（claim / running），按 workItemId 去重合并。 */
  workItemStart?: boolean
  /** 工作项真实终态（skill.finished / skill.failed / 租约过期重排队）。 */
  terminal?: RoomWorkItemTerminal
  /** Manager 回复解析出的结构化信封；存在时前端做结构化渲染。 */
  managerReport?: ManagerReport
  /** Manager 澄清卡片（room.ask_user）：存在时渲染可交互问答卡片。 */
  askRequest?: RoomAskRequest
  hideContent?: boolean
  /** 路由决策卡（room.route_decision）：高置信渲染折叠卡片，模糊时升级为选项确认卡。 */
  routeDecision?: RoomRouteDecision
  /** 咨询分诊转场卡（room.route_transition）：经理把纯咨询问题分诊给领域专家直答。 */
  routeTransition?: RoomRouteTransition
  /** 领域专家回复的来源标记：manager_triage 时在气泡头部展示「经理分诊」标识。 */
  routedBy?: RoomRoutedBy
  /** 立项确认卡（room.proposal_confirm）：未立项/终态后续聊的 execute 意图投影。 */
  proposal?: RoomProposal
  /** 当前用户本人的发言（room.user_message 投影）：时间线上右对齐渲染。 */
  isUser?: boolean
  /** worker 执行产生的图片、PDF、表格等工作区产物。 */
  artifacts?: unknown
  /** 技术详情：原始错误、英文 schema 校验信息等，折叠展示。 */
  technicalDetail?: string
  /** 动作按钮：重试 / 修改需求 / 终止 Case 等。 */
  actions?: RoomMessageAction[]
  /** 领域 Agent 完成后交给 Manager 的结构化交接。 */
  handoff?: RoomAgentHandoff
  /** Manager 派单（work_item.assigned）：分派正文渲染为结构化卡片。 */
  dispatch?: RoomDispatchInfo
  /** 运行中任务的只读变更影响评估。 */
  changeAssessment?: RoomChangeAssessment
}

/** role_labels / role_agent_map 均可选：端点未接通时用本地兜底身份渲染。 */
export interface RoomRoleMetadata {
  role_labels?: Record<string, AgentTeamsRoleLabel>
  role_agent_map?: Record<string, string>
}

const SYSTEM_SENDER: RoomSender = { name: '系统', avatar: '⚙️', color: '#64748b', role: 'worker' }
const MANAGER_FALLBACK: RoomSender = { name: '生物信息部门经理', avatar: '🧑‍🔬', color: '#4f8ef7', role: 'manager' }
const QC_FALLBACK: RoomSender = { name: '质量审计员', avatar: '🛡️', color: '#d97706', role: 'worker' }
const USER_SENDER: RoomSender = { name: '我', avatar: '🧑‍💻', color: '#4f8ef7', role: 'manager' }

/** 工具 display name 映射：命中时展示中文，未命中时保留原始工具名。 */
const TOOL_DISPLAY_NAMES: Record<string, string> = {
  cygnusx_search_memory: '检索长期记忆',
  cygnusx_save_memory: '保存长期记忆',
  cygnusx_update_memory: '更新长期记忆',
  cygnusx_forget_memory: '遗忘长期记忆',
  cygnusx_update_memory_block: '更新记忆块',
  workspace_file_preview: '读取文件',
  workspace_read_file: '读取文件',
  sandbox_execute: '沙箱执行',
  pipeline_query: '查询流程',
  task_result_summary: '整理任务结果',
  task_file_preview: '预览任务文件',
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
      archetype: direct.archetype || undefined,
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
        archetype: viaAgent.archetype || undefined,
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
      archetype: qc.archetype || undefined,
    }
  }
  return actor ? resolveRoomSender(actor, metadata) : QC_FALLBACK
}

const OMIC_TASK_LABELS: Record<string, string> = {
  'omic_task.submitted': 'CygnusX 任务已提交',
  'omic_task.status_changed': '任务状态已回传',
  'omic_task.completed': '任务已完成，转入质量核验',
  'omic_task.failed': '任务执行失败',
  'omic_task.cancelled': '任务已取消',
}

function truncate(text: string, limit = 200): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

const PASTED_TEXT_NOTICE_RE = /^pasted text file:\s*.+pasted-text-\d+\.txt\.\s*read this file before continuing\.?$/is

function isPastedTextNotice(content: string): boolean {
  return PASTED_TEXT_NOTICE_RE.test(content.trim())
}

function decodePartialJsonString(raw: string, start: number): string {
  let value = ''
  for (let index = start; index < raw.length; index += 1) {
    const char = raw[index]
    if (char === '"') return value
    if (char !== '\\') {
      value += char
      continue
    }
    const escaped = raw[index + 1]
    if (!escaped) break
    index += 1
    value += ({ n: '\n', r: '\r', t: '\t', '"': '"', '\\': '\\', '/': '/' }[escaped] || escaped)
  }
  return value
}

/** 流式响应实际是 ConsultationEnvelope JSON 时，仅显示已到达的 conclusion 文本。 */
function displayStreamingContent(raw: string): string {
  if (isPastedTextNotice(raw)) return ''
  const match = /["']conclusion["']\s*:\s*"/.exec(raw)
  if (match) return decodePartialJsonString(raw, match.index + match[0].length)
  const trimmed = raw.trimStart()
  return trimmed.startsWith('{') || trimmed.startsWith('```json') ? '' : raw
}

function normalizeManagerReport(value: unknown): ManagerReport | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  const conclusion = sanitizeManagerText(pickString(payload, ['conclusion']))
  if (!conclusion) return null
  const hardGate = payload.hard_gate || payload.hardGate
  const proposedSubmission = payload.proposed_submission || payload.proposedSubmission
  return {
    conclusion,
    recommendations: toStringList(payload.recommendations),
    risks: visibleManagerRisks(payload.risks),
    evidenceRefs: toStringList(payload.evidence_refs || payload.evidenceRefs),
    ...(hardGate && typeof hardGate === 'object' ? { hardGate: hardGate as Record<string, unknown> } : {}),
    ...(proposedSubmission && typeof proposedSubmission === 'object'
      ? { proposedSubmission: proposedSubmission as Record<string, unknown> }
      : {}),
  }
}

const INTERNAL_CAPABILITY_RISK_MARKER = '未获准调用能力目录类只读工具'

function sanitizeManagerText(value: string): string {
  if (!value.includes(INTERNAL_CAPABILITY_RISK_MARKER)) return value
  return value
    .replace(
      /(?:^|\n)\s*(?:#{1,6}\s*)?风险\s*[:：]?\s*本轮未获准调用能力目录类只读工具，.*?平台能力目录实况为准。?\s*(?=\n|$)/is,
      '\n',
    )
    .replace(/\s*本轮未获准调用能力目录类只读工具，.*?平台能力目录实况为准。?/is, '')
    .trim()
}

function visibleManagerRisks(value: unknown): string[] {
  return toStringList(value).filter((item) => !item.includes(INTERNAL_CAPABILITY_RISK_MARKER))
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter((item) => item.length > 0)
}

/** 归一化 room.ask_user 事件的 questions 载荷：仅保留非空问题，最多 5 个。 */
function normalizeAskQuestions(value: unknown): RoomAskQuestion[] {
  if (!Array.isArray(value)) return []
  const questions: RoomAskQuestion[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const question = pickString(item as Record<string, unknown>, ['question'])
    if (!question) continue
    questions.push({ question, options: toStringList((item as Record<string, unknown>).options) })
  }
  return questions.slice(0, 5)
}

function normalizeWorkspaceCandidates(
  value: unknown,
): Array<{ kind: 'workspace' | 'file'; id: string; location: string }> {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const record = item as Record<string, unknown>
      const kind = pickString(record, ['kind'])
      const id = pickString(record, ['id'])
      const location = pickString(record, ['location'])
      if ((kind !== 'workspace' && kind !== 'file') || !id || !location) return null
      return { kind, id, location }
    })
    .filter((item): item is { kind: 'workspace' | 'file'; id: string; location: string } => item !== null)
}

/** 归一化 room.route_decision 的预计阶段列表。 */
function normalizeRouteStages(value: unknown): RoomRouteDecisionStage[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const record = item as Record<string, unknown>
      const key = pickString(record, ['key'])
      if (!key) return null
      return { key, title: pickString(record, ['title']) || key }
    })
    .filter((item): item is RoomRouteDecisionStage => item !== null)
}

/** 归一化 room.route_decision 的候选项（ambiguous 时的点选裁决项）。 */
function normalizeRouteOptions(value: unknown): RoomRouteDecisionOption[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const record = item as Record<string, unknown>
      const label = pickString(record, ['label'])
      if (!label) return null
      const rawFlowId = pickString(record, ['flow_id'])
      const rawStages = record.stages
      return {
        flowId: rawFlowId || null,
        label,
        leadPlanner: pickString(record, ['lead_planner']),
        stages: typeof rawStages === 'number' ? rawStages : 0,
      }
    })
    .filter((item): item is RoomRouteDecisionOption => item !== null)
}

/** 归一化 room.route_decision 事件载荷；缺关键字段时返回 null（事件丢弃）。 */
function normalizeRouteDecision(value: unknown): RoomRouteDecision | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const path = pickString(record, ['path'])
  if (!path) return null
  const rawScores = record.planner_scores
  const plannerScores: Record<string, number> = {}
  if (rawScores && typeof rawScores === 'object' && !Array.isArray(rawScores)) {
    for (const [agent, score] of Object.entries(rawScores as Record<string, unknown>)) {
      if (typeof score === 'number') plannerScores[agent] = score
    }
  }
  return {
    path,
    flowId: pickString(record, ['flow_id']) || null,
    flowLabel: pickString(record, ['flow_label']) || '通用分析',
    matchedHints: toStringList(record.matched_hints),
    leadPlanner: pickString(record, ['lead_planner']),
    plannerScores,
    estimatedStages: normalizeRouteStages(record.estimated_stages),
    participants: toStringList(record.participants),
    confidence: record.confidence === 'ambiguous' ? 'ambiguous' : 'high',
    options: normalizeRouteOptions(record.options),
  }
}

/** 归一化 room.route_transition 事件载荷；缺目标专家（id 与名称同时缺失）时返回 null（事件丢弃）。 */
function normalizeRouteTransition(value: unknown): RoomRouteTransition | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const targetAgentId = pickString(record, ['target_agent_id'])
  const targetName = pickString(record, ['target_name'])
  if (!targetAgentId && !targetName) return null
  const rawConfidence = record.confidence
  return {
    fromAgentId: pickString(record, ['from_agent_id']),
    fromName: pickString(record, ['from_name']),
    targetAgentId,
    targetName,
    reason: pickString(record, ['reason']),
    confidence: typeof rawConfidence === 'number' ? rawConfidence : null,
    trigger: pickString(record, ['trigger']),
    causationEventId: pickString(record, ['causation_event_id']),
  }
}

/** 归一化 room.proposal_confirm 事件载荷。
 *  B1 起 confirm_token 全出口脱敏（可能缺省/为 null），不再作为必要条件——
 *  确认动作凭 owner + pending 状态走 confirm-proposal 端点，token 仅作可选二次校验。 */
function normalizeRoomProposal(value: unknown): RoomProposal | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const confirmToken = pickString(record, ['confirm_token'])
  const rawStatus = pickString(record, ['status'])
  const rawConfidence = pickString(record, ['confidence'])
  return {
    proposalKind: pickString(record, ['proposal_kind']) === 'followup' ? 'followup' : 'new_case',
    confirmToken,
    status: rawStatus === 'pending' ? 'pending' : 'cancelled',
    objective: pickString(record, ['objective']),
    flowId: pickString(record, ['flow_id']),
    flowLabel: pickString(record, ['flow_label']) || '通用分析',
    leadPlanner: pickString(record, ['lead_planner']),
    routePath: pickString(record, ['route_path']),
    participants: toStringList(record.participants),
    estimatedStages: normalizeRouteStages(record.estimated_stages),
    confidence: rawConfidence === 'ambiguous' ? 'ambiguous' : rawConfidence === 'high' ? 'high' : '',
    originContent: pickString(record, ['origin_content']) || pickString(record, ['objective']),
    sourceCaseId: pickString(record, ['source_case_id']),
    options: toStringList(record.options),
    createdAt: pickString(record, ['created_at']),
  }
}

/** 路由决策卡的一行摘要（与后端 summarize_route_decision 同一措辞）。 */
export function formatRouteDecisionSummary(decision: RoomRouteDecision): string {
  const stageCount = decision.estimatedStages.length
  if (decision.confidence === 'ambiguous') {
    return `路由待确认：存在多种可能路径（倾向「${decision.flowLabel}」 · 规划者 ${decision.leadPlanner}），请点选裁决`
  }
  return `已选择「${decision.flowLabel}」 · 规划者 ${decision.leadPlanner} · 预计 ${stageCount} 个阶段`
}

/** 模糊路由的候选项文案：作为澄清卡片的可点选选项。 */
function formatRouteOptionLabel(option: RoomRouteDecisionOption): string {
  const detail = [option.leadPlanner ? `规划者 ${option.leadPlanner}` : '', option.stages ? `${option.stages} 个阶段` : '']
    .filter((item) => item)
    .join(' · ')
  return detail ? `${option.label}（${detail}）` : option.label
}

/** 把用户对澄清卡片的回答格式化为房间发言：带标记前缀，投影时可回填到卡片。 */
export function formatRoomAskReply(questions: RoomAskQuestion[], answers: string[]): string {
  const lines = questions.map((q, i) => {
    const answer = (answers[i] || '').trim() || '无偏好，由你决定'
    return `${i + 1}. ${q.question}：${answer}`
  })
  return [ROOM_ASK_REPLY_MARKER, ...lines].join('\n')
}

/** 从澄清回复发言中按问题顺序解析答案；行格式不匹配时该题留空（卡片回退兜底文案）。 */
function parseRoomAskReply(content: string, questions: RoomAskQuestion[]): string[] | undefined {
  if (!content.startsWith(ROOM_ASK_REPLY_MARKER)) return undefined
  const lines = content
    .slice(ROOM_ASK_REPLY_MARKER.length)
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
  return questions.map((q, i) => {
    const line = (lines[i] || '').replace(/^\d+[.、)]\s*/, '')
    const prefix = `${q.question}：`
    if (line.startsWith(prefix)) return line.slice(prefix.length).trim()
    const colonIndex = line.indexOf('：')
    return colonIndex >= 0 ? line.slice(colonIndex + 1).trim() : line
  })
}

function stripJsonTrailingCommas(value: string): string {
  let result = ''
  let inString = false
  let escaped = false
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index]
    if (char === '"' && !escaped) inString = !inString
    if (char === ',' && !inString) {
      let nextIndex = index + 1
      while (nextIndex < value.length && /\s/.test(value[nextIndex])) nextIndex += 1
      if (nextIndex < value.length && (value[nextIndex] === '}' || value[nextIndex] === ']')) {
        escaped = false
        continue
      }
    }
    result += char
    escaped = char === '\\' && !escaped
    if (char !== '\\') escaped = false
  }
  return result
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
      const parsed: unknown = JSON.parse(stripJsonTrailingCommas(candidate))
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
  const conclusion = sanitizeManagerText(pickString(envelope, ['conclusion']))
  const recommendations = toStringList(envelope.recommendations)
  const risks = visibleManagerRisks(envelope.risks)
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
    if (!content || isPastedTextNotice(content)) return null
    return { id: event_id, sender: USER_SENDER, kind: 'speech', content, isUser: true }
  }

  if (event_type === 'room.agent_message') {
    // Bridge 的 audit actor 可能固定为内部 Manager 身份；worker 回复必须优先
    // 使用事件载荷里的 agent_id，否则所有领域 Agent 都会显示成 Manager。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const content = pickString(inner, ['content']) || pickString(body, ['summary'])
    if (!content || isPastedTextNotice(content)) return null
    const role = pickString(inner, ['role'])
    const senderActor = role === 'worker'
      ? pickString(inner, ['agent_id']) || actor || 'unknown-agent'
      : actor || 'bioops-manager'
    const sender = resolveRoomSender(senderActor, metadata)
    const streamId = pickString(inner, ['stream_id'])
    const routedBy = pickString(inner, ['routed_by']) || pickString(body, ['routed_by'])
    // Manager 回复链路可能把整段 JSON 信封塞进 content；能解析出结构化字段时
    // 交给前端做结论/建议/风险/硬门禁的结构化展示，解析失败回退纯文本气泡。
    const managerReport = normalizeManagerReport(inner.manager_report) || parseManagerReport(content)
    // 房间重开后瞬态流式增量已丢失：后端聚合时把持久化的思考链/工具事件
    // 注入最终消息载荷（thought / tool_calls），这里直接取用。
    const thought = pickString(inner, ['thought'])
    const injectedToolCalls = normalizeInjectedToolCalls(inner.tool_calls)
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: truncate(sender.role === 'manager' ? sanitizeManagerText(content) : content, 2_000),
      ...(streamId ? { streamId } : {}),
      ...(thought ? { thought } : {}),
      ...(injectedToolCalls.length ? { toolCalls: injectedToolCalls } : {}),
      ...(routedBy === 'manager_triage' || routedBy === 'direct_mention' ? { routedBy } : {}),
      ...(managerReport ? { managerReport } : {}),
    }
  }

  if (event_type === 'room.agent_handoff') {
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : body) as Record<string, unknown>
    const fromAgentId = pickString(inner, ['from_agent_id']) || actor || 'unknown-agent'
    const toAgentId = pickString(inner, ['to_agent_id']) || 'bioops-manager'
    const workItemIds = toStringList(inner.work_item_ids)
    const risks = toStringList(inner.risks)
    const artifactRefs = toStringList(inner.artifact_refs)
    const summary = pickString(inner, ['summary']) || '领域 Agent 已完成工作并提交交接。'
    return {
      id: event_id,
      sender: resolveRoomSender(fromAgentId, metadata),
      kind: 'speech',
      content: summary,
      handoff: { fromAgentId, toAgentId, workItemIds, risks, artifactRefs, recommendedNextAction: pickString(inner, ['recommended_next_action']) },
    }
  }

  if (event_type === 'room.change_assessment') {
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : body) as Record<string, unknown>
    const agentId = pickString(inner, ['agent_id']) || actor || 'unknown-agent'
    return {
      id: event_id,
      sender: resolveRoomSender(agentId, metadata),
      kind: 'speech',
      content: pickString(inner, ['conclusion']) || '领域 Agent 已完成变更影响评估。',
      changeAssessment: {
        agentId,
        workItemIds: toStringList(inner.work_item_ids),
        conclusion: pickString(inner, ['conclusion']),
        recommendations: toStringList(inner.recommendations),
        risks: toStringList(inner.risks),
        evidenceRefs: toStringList(inner.evidence_refs),
        decisionOptions: toStringList(inner.decision_options),
        decision: pickString(inner, ['decision']),
      },
    }
  }

  if (event_type === 'room.ask_user') {
    // Manager 澄清卡片：content 为简短引导语，questions 渲染为可交互问答卡片；
    // 答案以带 ROOM_ASK_REPLY_MARKER 前缀的 room.user_message 回传。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const content = pickString(inner, ['content']) || pickString(body, ['summary'])
    const questions = normalizeAskQuestions(inner.questions)
    if (!questions.length) return null
    const sender = resolveRoomSender(actor || 'bioops-manager', metadata)
    const streamId = pickString(inner, ['stream_id'])
    const managerReport = normalizeManagerReport(inner.manager_report)
    const clarifyKind = pickString(inner, ['clarify_kind'])
    // 同 room.agent_message：后端注入的历史思考链/工具卡直接取用。
    const thought = pickString(inner, ['thought'])
    const injectedToolCalls = normalizeInjectedToolCalls(inner.tool_calls)
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: clarifyKind === 'execution_object' ? '' : truncate(content, 2_000),
      hideContent: clarifyKind === 'execution_object',
      ...(streamId ? { streamId } : {}),
      ...(thought ? { thought } : {}),
      ...(injectedToolCalls.length ? { toolCalls: injectedToolCalls } : {}),
      ...(managerReport ? { managerReport } : {}),
      askRequest: {
        questions,
        eventId: event_id,
        clarifyKind: clarifyKind || undefined,
        objectRequired: clarifyKind === 'execution_object',
        workspaceCandidates: normalizeWorkspaceCandidates(inner.workspace_candidates),
      },
    }
  }

  if (event_type === 'room.route_decision') {
    // 路由决策卡（O1）：证据事件载荷在内层 payload.payload（同 room 消息事件）。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const decision = normalizeRouteDecision(inner)
    if (!decision) return null
    const sender = resolveRoomSender(actor || 'bioops-manager', metadata)
    // 模糊决策升级为选项式确认卡：复用澄清卡片的点选-回传链路，
    // 答案作为下一条 room.user_message 回到响应回路，不阻断已启动的流程。
    const askRequest =
      decision.confidence === 'ambiguous' && decision.options.length
        ? {
            questions: [
              {
                question: '检测到多种可能的执行路径，请点选裁决：',
                options: decision.options.map(formatRouteOptionLabel),
              },
            ],
          }
        : undefined
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: formatRouteDecisionSummary(decision),
      routeDecision: decision,
      ...(askRequest ? { askRequest } : {}),
    }
  }

  if (event_type === 'room.route_transition') {
    // 咨询分诊转场卡：CHAT 意图由经理分诊给领域专家直答，载荷在内层 payload.payload
    // （同 room 消息事件）。与 room.route_decision（流程路径决策）语义隔离。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const transition = normalizeRouteTransition(inner) || normalizeRouteTransition(body)
    if (!transition) return null
    const sender = resolveRoomSender(transition.fromAgentId || actor || 'bioops-manager', metadata)
    // 名称缺省时按角色元数据兜底解析，保证旧事件也能渲染出可读卡片。
    if (!transition.fromName && transition.fromAgentId) {
      transition.fromName = resolveRoomSender(transition.fromAgentId, metadata).name
    }
    if (!transition.targetName) {
      transition.targetName = resolveRoomSender(transition.targetAgentId, metadata).name
    }
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: '',
      hideContent: true,
      routeTransition: transition,
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

  if (event_type === 'room.proposal_confirm') {
    // 立项确认卡：execute 意图不直接建 Case，先出卡等用户裁决；payload 在内层 payload.payload。
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const proposal = normalizeRoomProposal(inner)
    if (!proposal) return null
    const sender = resolveRoomSender(pickString(inner, ['agent_id']) || actor || 'bioops-manager', metadata)
    return {
      id: event_id,
      sender,
      kind: 'speech',
      content: '',
      hideContent: true,
      proposal,
    }
  }

  if (event_type === 'room.case_bound') {
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: pickString(body, ['summary']) || '立项已确认，协作 Case 创建完成。',
    }
  }

  if (event_type === 'room.proposal_modify_requested' || event_type === 'room.proposal_cancelled') {
    const fallback = event_type === 'room.proposal_modify_requested'
      ? '用户要求调整立项内容，请补充说明。'
      : '本次立项已取消。'
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: pickString(body, ['summary']) || fallback,
    }
  }

  if (event_type === 'room.provisioning_failed') {
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: 'Matrix 协作房间创建失败，已降级为平台事件流；分析任务不受影响。',
      technicalDetail: pickString(inner, ['detail', 'recovery']),
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
    // 分派从系统时间轴行升级为 Manager 的结构化卡片：长分派正文不再挤进一行时间轴文案。
    return {
      id: event_id,
      sender: resolveRoomSender(actor || 'bioops-manager', metadata),
      kind: 'speech',
      content: `Manager 将任务分派给 ${targetName}${objective ? `：${objective}` : ''}`,
      dispatch: {
        targetName,
        objective,
        ...(rawSkillName ? { skillName: formatSkillName(rawSkillName) } : {}),
      },
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

  if (event_type === 'agent.tool_call' || event_type === 'agent.tool_started') {
    // 证据事件经 Bridge 审计包装，工具字段在内层 payload.payload（同 room 消息事件）
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const rawTool = pickString(inner, ['tool', 'tool_name', 'name']) || pickString(body, ['tool', 'tool_name', 'name'])
    const tool = rawTool ? formatToolName(rawTool) : ''
    if (!tool) return null
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'progress',
      content: event_type === 'agent.tool_started' ? `工具执行中：${tool}` : `正在调用 ${tool}`,
      tool: { name: tool, status: 'running' },
      debugTrace: extractDebugTrace(body, inner),
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
      debugTrace: extractDebugTrace(body, inner),
    }
  }

  if (
    event_type === 'agent.context_reinjected'
    || event_type === 'agent.turn_continued'
  ) {
    return null
  }

  if (event_type === 'agent.loop_guard_triggered') {
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
    const reason = pickString(inner, ['reason']) || pickString(body, ['reason']) || '运行保护'
    const tool = pickString(inner, ['tool']) || pickString(body, ['tool'])
    return {
      id: event_id,
      sender: resolveRoomSender(actor, metadata),
      kind: 'progress',
      content: `已停止重复调用${tool ? `（${formatToolName(tool)}）` : ''}，正在整理已有结果`,
      technicalDetail: pickString(inner, ['execution_path']) || pickString(body, ['execution_path']) || undefined,
      debugTrace: extractDebugTrace(body, inner),
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
      // 终态正文是 worker 卡片主体内容：上限对齐 Manager 回复（2k），避免规划结论被截断。
      content: truncate(conclusion || '已完成本阶段任务。', 2_000),
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
      content: truncate(reason ? `任务执行失败：${reason}` : '任务执行失败。', 2_000),
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
      content: `任务重试已达上限${progress}，依赖它的下游任务已跳过；请人工选择重试、跳过或终止。`,
    }
  }

  if (event_type === 'work_item.retry_requeued') {
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: '任务已到重试时间，已重新进入待派发队列。',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'work_item.timeout') {
    // Worker 反复失联、重试预算耗尽：卡片进入终态并明确告知。
    const reason = pickString(body, ['summary'])
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: actor ? resolveRoomSender(actor, metadata) : SYSTEM_SENDER,
      kind: 'speech',
      content: truncate(reason || '任务多次失联，重试预算已耗尽，判定超时终止。'),
      terminal: 'failed',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'work_item.skipped') {
    const cause = pickString(body, ['cause_work_item_id'])
    const reason = pickString(body, ['summary'])
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: truncate(
        reason || `任务因上游 ${cause || '任务'} 不可恢复而被跳过；如需继续，请人工重试上游或终止 Case。`,
      ),
      terminal: 'interrupted',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'work_item.manual_retry') {
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: '任务已手动重试，重新进入待派发队列。',
      ...(workItemId ? { workItemId } : {}),
    }
  }

  if (event_type === 'work_item.cancelled') {
    const reason = pickString(body, ['summary'])
    const workItemId = pickString(body, ['work_item_id'])
    return {
      id: event_id,
      sender: SYSTEM_SENDER,
      kind: 'system',
      content: truncate(reason || '任务已被手动终止。'),
      terminal: 'interrupted',
      ...(workItemId ? { workItemId } : {}),
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
    const label = OMIC_TASK_LABELS[event_type] || 'CygnusX 任务状态变更'
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

function extractDebugTrace(
  body: Record<string, unknown>,
  inner: Record<string, unknown>,
): RoomDebugTrace | undefined {
  const read = (key: string) => pickString(inner, [key]) || pickString(body, [key])
  const rawRound = inner.round ?? body.round
  const round = typeof rawRound === 'number'
    ? rawRound
    : typeof rawRound === 'string' && /^\d+$/.test(rawRound) ? Number(rawRound) : undefined
  const trace: RoomDebugTrace = {
    toolCallId: read('tool_call_id') || undefined,
    round,
    executionPath: read('execution_path') || undefined,
    argsSummary: read('args_summary') || undefined,
    resultSummary: read('result_summary') || undefined,
  }
  return Object.values(trace).some((value) => value !== undefined) ? trace : undefined
}

/** 把携带 stream_id 的工具事件归并到对应发言气泡的 toolCalls 列表。
 *  工具事件可能早于首个流式增量到达（气泡尚未创建），先按 stream_id 暂存，
 *  气泡创建时一次性挂上；同一 tool_call_id 的 call/started/result 合并为一条。 */
function attachStreamToolCall(
  pending: Map<string, RoomToolCall[]>,
  streams: Map<string, RoomMessage>,
  streamId: string,
  event: AgentTeamsEvent,
  inner: Record<string, unknown>,
): void {
  const rawTool = pickString(inner, ['tool', 'tool_name', 'name'])
  const tool = rawTool ? formatToolName(rawTool) : ''
  if (!tool) return
  let list = pending.get(streamId)
  if (!list) {
    list = []
    pending.set(streamId, list)
  }
  const callId = pickString(inner, ['tool_call_id']) || event.event_id
  let entry = list.find((item) => item.id === callId)
  if (!entry) {
    entry = { id: callId, name: tool, status: 'running' }
    list.push(entry)
  }
  if (event.event_type === 'agent.tool_result') {
    entry.status = inner.success === false ? 'failed' : 'ok'
    if (typeof inner.duration_ms === 'number') entry.durationMs = Math.round(inner.duration_ms)
    const resultSummary = pickString(inner, ['result_summary'])
    if (resultSummary) entry.resultSummary = resultSummary
  } else {
    entry.status = 'running'
    const argsSummary = pickString(inner, ['args_summary'])
    if (argsSummary) entry.argsSummary = argsSummary
  }
  const stream = streams.get(streamId)
  if (stream) stream.toolCalls = list
}

/** 归一化后端在 room.agent_message / room.ask_user 载荷里注入的历史工具调用。
 *  房间重开后 room.agent_stream 瞬态增量已丢失，后端聚合时把审计链中持久化的
 *  工具事件合并成 tool_calls（snake_case 字段），这里映射为 RoomToolCall。 */
function normalizeInjectedToolCalls(value: unknown): RoomToolCall[] {
  if (!Array.isArray(value)) return []
  const calls: RoomToolCall[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const raw = item as Record<string, unknown>
    const id = pickString(raw, ['id'])
    const name = pickString(raw, ['name'])
    if (!id || !name) continue
    const call: RoomToolCall = {
      id,
      name,
      status: raw.status === 'ok' || raw.status === 'failed' ? raw.status : 'running',
    }
    if (typeof raw.duration_ms === 'number') call.durationMs = Math.round(raw.duration_ms)
    const argsSummary = pickString(raw, ['args_summary'])
    if (argsSummary) call.argsSummary = argsSummary
    const resultSummary = pickString(raw, ['result_summary'])
    if (resultSummary) call.resultSummary = resultSummary
    calls.push(call)
  }
  return calls
}

/** 将一批事件投影为房间消息列表（丢弃不在投影表内的事件，保持原顺序）。
 *  同一 work_item_id 的重复 claim/running 占位消息在此去重：保留首次认领
 *  （attempt 变化视为合法重试，予以保留），其余重复占位合并掉，避免时间线上
 *  出现两张几乎相同的 worker 卡片。
 *  已被澄清卡片消费的【澄清回复】发言不再单独上屏（§18.4.2 已回答态折叠：
 *  问答明细收进卡片展开态回看），解析失败或找不到卡片的回复保留原文气泡降级。 */
export function projectCaseEvents(
  events: AgentTeamsEvent[],
  metadata: RoomRoleMetadata = {},
): RoomMessage[] {
  const messages: RoomMessage[] = []
  const startAttempts = new Map<string, number>()
  const streams = new Map<string, RoomMessage>()
  // Manager/直答专家应答过程中的工具调用事件携带 stream_id，
  // 归并到对应发言气泡内联展示（对齐 AI 助手气泡内工具卡片），不再生成独立 progress 行。
  const streamToolCalls = new Map<string, RoomToolCall[]>()
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
    if (event.event_type === 'room.agent_stream') {
      const body = event.payload || {}
      const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
      const streamId = pickString(inner, ['stream_id'])
      const channel = pickString(inner, ['channel'])
      const delta = pickString(inner, ['delta'])
      if (!streamId || !delta || (channel !== 'reasoning' && channel !== 'content')) continue
      let stream = streams.get(streamId)
      if (!stream) {
        const streamRole = pickString(inner, ['role'])
        const streamActor = streamRole === 'worker'
          ? pickString(inner, ['agent_id']) || event.actor || 'unknown-agent'
          : event.actor || pickString(inner, ['agent_id']) || 'bioops-manager'
        const sender = resolveRoomSender(streamActor, metadata)
        stream = {
          id: `stream:${streamId}`,
          sender,
          kind: 'speech',
          content: '',
          thought: '',
          streaming: true,
          streamId,
          streamRawContent: '',
        }
        streams.set(streamId, stream)
        const pendingCalls = streamToolCalls.get(streamId)
        if (pendingCalls) stream.toolCalls = pendingCalls
        messages.push(stream)
      }
      if (channel === 'reasoning') stream.thought = `${stream.thought || ''}${delta}`
      else {
        stream.streamRawContent = `${stream.streamRawContent || ''}${delta}`
        stream.content = displayStreamingContent(stream.streamRawContent)
      }
      continue
    }
    if (event.event_type === 'room.typing') {
      // typing 结束兜底收尾所有未闭环的流式气泡：最终回复事件即使在 SSE 中丢失，
      // 气泡也不会永远停在「正在生成」。
      const body = event.payload || {}
      const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
      if (inner.typing === false) {
        for (const stream of streams.values()) {
          if (stream.streaming) stream.streaming = false
        }
      }
      continue
    }
    if (
      event.event_type === 'agent.tool_call'
      || event.event_type === 'agent.tool_started'
      || event.event_type === 'agent.tool_result'
    ) {
      const body = event.payload || {}
      const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
      const streamId = pickString(inner, ['stream_id'])
      if (streamId) {
        attachStreamToolCall(streamToolCalls, streams, streamId, event, inner)
        continue
      }
    }
    const message = projectCaseEvent(event, metadata)
    if (!message) continue
    if (message.streamId) {
      const stream = streams.get(message.streamId)
      if (stream && event.event_type === 'room.agent_message') {
        Object.assign(stream, message, {
          id: stream.id,
          // 流式增量还在时以气泡上的思考链/工具卡为准；增量丢失（房间重开）
          // 时回退到后端注入进最终消息载荷的 thought / toolCalls。
          thought: stream.thought || message.thought,
          toolCalls: stream.toolCalls?.length ? stream.toolCalls : message.toolCalls,
          streaming: false,
          streamId: message.streamId,
          streamRawContent: undefined,
        })
        continue
      }
      if (stream && event.event_type === 'room.ask_user') {
        stream.streaming = false
        if (message.managerReport) {
          stream.content = message.managerReport.conclusion
          stream.managerReport = message.managerReport
        }
        stream.askRequest = message.askRequest
        stream.streamRawContent = undefined
        continue
      }
    }
    if (event.event_type === 'room.agent_message' || event.event_type === 'room.ask_user') {
      // 最终回复未匹配到流（stream_id 缺失或增量事件丢失）：按发送者收尾未闭环的流式气泡。
      for (const open of streams.values()) {
        if (open.streaming && open.streamId !== message.streamId && open.sender.name === message.sender.name) {
          open.streaming = false
        }
      }
    }
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
  // 房间重开兜底：room.agent_stream 瞬态增量不持久化，历史工具事件失去可挂的
  // 流式气泡（或工具事件与最终消息分属不同分页/时钟微差导致顺序颠倒）。全部
  // 事件投影完成后，把仍孤儿的工具调用按 stream_id 挂到最终消息气泡上。
  for (const message of messages) {
    if (!message.streamId || message.toolCalls?.length) continue
    const pendingCalls = streamToolCalls.get(message.streamId)
    if (pendingCalls?.length) message.toolCalls = pendingCalls
  }
  applyAskAnswerEvidence(sorted, messages)
  const consumedReplyIds = markAskRequestsAnswered(messages)
  applyProposalOutcomes(sorted, messages)
  const visible: RoomMessage[] = []
  for (const message of messages) {
    if (consumedReplyIds.has(message.id)) continue
    if (message.isUser && message.content.startsWith(ROOM_ASK_REPLY_MARKER)) {
      // 未被任何卡片消费的残留澄清回复（历史落库缺卡片字段或格式不匹配）：
      // 剥掉内部标记、按「无载荷」降级为纯文本，不崩（§18.4.3）
      message.content = message.content.slice(ROOM_ASK_REPLY_MARKER.length).trim()
      if (!message.content) continue
    }
    visible.push(message)
  }
  return visible
}

/** 澄清卡片的兼容回填：只接受可解析的【澄清回复】格式，不再把任意后续用户发言视为已答。
 *  返回被卡片消费的回复消息 id（这些回复不再单独渲染为用户气泡）；
 *  解析不出答案的回复不消费，保留原文气泡作为降级形态。 */
function markAskRequestsAnswered(messages: RoomMessage[]): Set<string> {
  const consumedReplyIds = new Set<string>()
  for (let i = 0; i < messages.length; i += 1) {
    const ask = messages[i].askRequest
    if (!ask) continue
    const reply = messages.slice(i + 1).find((item) =>
      item.isUser
      && item.content.startsWith(ROOM_ASK_REPLY_MARKER)
      && !consumedReplyIds.has(item.id),
    )
    if (!reply) continue
    const answers = parseRoomAskReply(reply.content, ask.questions)
    if (answers) {
      ask.answers = answers
      ask.answered = true
      consumedReplyIds.add(reply.id)
    }
  }
  return consumedReplyIds
}

/** 立项确认卡消费态回填：房间同时只有一张 pending 卡（新卡覆盖旧卡）。
 *  后续 room.case_bound / room.proposal_modify_requested / room.proposal_cancelled
 *  事件即卡片的消费结果；更早的 pending 卡在新卡出现时标记为 superseded（已失效）。 */
function applyProposalOutcomes(events: AgentTeamsEvent[], messages: RoomMessage[]): void {
  const proposals = messages.filter((message) => message.proposal)
  if (!proposals.length) return
  const eventTimes = new Map(events.map((event) => [event.event_id, Date.parse(event.recorded_at) || 0]))
  const outcomes = events.filter((event) =>
    event.event_type === 'room.case_bound'
    || event.event_type === 'room.proposal_modify_requested'
    || event.event_type === 'room.proposal_cancelled',
  )
  for (const outcome of outcomes) {
    const status: RoomProposal['status'] = outcome.event_type === 'room.case_bound'
      ? 'confirmed'
      : outcome.event_type === 'room.proposal_modify_requested'
        ? 'modify_requested'
        : 'cancelled'
    const outcomeAt = Date.parse(outcome.recorded_at) || 0
    // 消费该结果之前最近的一张 pending 卡（token 一次性，结果事件不携带 token 时按时间归位）。
    const target = [...proposals]
      .reverse()
      .find((message) =>
        message.proposal!.status === 'pending'
        && (eventTimes.get(message.id) || 0) <= outcomeAt,
      )
    if (target) target.proposal!.status = status
  }
  const pendingCards = proposals.filter((message) => message.proposal!.status === 'pending')
  for (const stale of pendingCards.slice(0, -1)) stale.proposal!.status = 'superseded'
}

function applyAskAnswerEvidence(events: AgentTeamsEvent[], messages: RoomMessage[]): void {  const asks = new Map(
    messages
      .filter((message) => message.askRequest?.eventId)
      .map((message) => [message.askRequest!.eventId!, message.askRequest!] as const),
  )
  for (const event of events) {
    if (event.event_type !== 'room.ask_user_answered') continue
    const body = event.payload || {}
    const inner = (body.payload && typeof body.payload === 'object' ? body.payload : body) as Record<string, unknown>
    const ask = asks.get(pickString(inner, ['answer_to_event_id']))
    if (!ask) continue
    const answer = pickString(inner, ['answer'])
    const parsedAnswers = answer ? parseRoomAskReply(answer, ask.questions) : null
    if (parsedAnswers) ask.answers = parsedAnswers
    const status = pickString(inner, ['answer_status']) as RoomAskRequest['answerStatus']
    if (status === 'collected' || status === 'waiting_upload' || status === 'missing_object') {
      ask.answerStatus = status
      ask.answered = status === 'collected' || status === 'waiting_upload'
      ask.submitted = !ask.answered
    }
  }
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

/** typing 事件新鲜度窗口：超出后视为残留事件（进程崩溃等未闭环场景），不再显示。
 *  需覆盖一次 LLM 会诊的典型耗时（含排队），避免回复未到指示器先消失。 */
export const MANAGER_TYPING_TTL_MS = 60_000

/** 聊天式创建的 intent 归一化：收敛空白并对齐后端 intent 上限（256 字符）。 */
export function buildRoomCreateIntent(content: string): string {
  return content.trim().replace(/\s+/g, ' ').slice(0, 256)
}

/**
 * 从用户需求文本生成协作 Case 的项目目录名称：
 * 取内容前 30 个字符，剥除不可用于目录名的字符，供 _prepare_case_run 做 run dir。
 * 后端 project_name 最长 200 字符，中文 30 字符完全够用。
 */
export function buildCaseProjectName(content: string): string {
  return content.trim().replace(/\s+/g, ' ').replace(/[/\\:*?"<>|]/g, '').slice(0, 30) || 'agentteams-case'
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
 *  且其间没有 room.agent_message / room.ask_user / room.agent_stream（回复到达即输入结束）。
 *  事件可能乱序到达（SSE 断线后由轮询补回），以 recorded_at 排序后再取末态，
 *  避免迟到的 typing:true 盖过已到达的回复事件导致指示器残留。 */
export function resolveManagerTyping(events: AgentTeamsEvent[], now: number = Date.now()): boolean {
  return resolveRoomTyping(events, now).active
}

/** 同 resolveManagerTyping，但额外返回 typing 事件携带的响应者名字：
 *  领域 Agent 直答时后端会在 payload 里带 agent_name，指示器据此显示真实响应者；
 *  未携带（经理路径）时返回 null，由调用方回退到经理显示名。 */
export function resolveRoomTyping(
  events: AgentTeamsEvent[],
  now: number = Date.now(),
): { active: boolean; agentName: string | null } {
  const ordered = [...events].sort((a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at))
  let typing = false
  let typingAt = 0
  let agentName: string | null = null
  for (const event of ordered) {
    if (event.event_type === 'room.typing') {
      const body = event.payload || {}
      const inner = (body.payload && typeof body.payload === 'object' ? body.payload : {}) as Record<string, unknown>
      typing = inner.typing === true
      typingAt = Date.parse(event.recorded_at) || 0
      agentName = typeof inner.agent_name === 'string' && inner.agent_name ? inner.agent_name : null
    } else if (
      event.event_type === 'room.agent_message'
      || event.event_type === 'room.ask_user'
      || event.event_type === 'room.agent_stream'
    ) {
      typing = false
      agentName = null
    }
  }
  const active = typing && typingAt > 0 && now - typingAt < MANAGER_TYPING_TTL_MS
  return { active, agentName: active ? agentName : null }
}

export interface RoomWorkerStep {
  id: string
  tool: RoomToolInfo
  count: number
  collapsed: boolean
  details: Array<{ id: string; tool: RoomToolInfo; debugTrace?: RoomDebugTrace }>
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
      last.details.push({ id: step.id, tool: step.tool, debugTrace: step.details[0]?.debugTrace })
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
        details: [{ id: step.id, tool: step.tool, debugTrace: step.details[0]?.debugTrace }],
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
          details: [{ id: item.id, tool: item.tool as RoomToolInfo, debugTrace: item.debugTrace }],
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
      // 兜底收尾：该成员的最终发言（如 Manager 工具调用后的 room.agent_message 气泡）
      // 会打断 run 成为独立气泡；此时工具卡不应再停在「进行中」动画。
      const followedByFinalSpeech =
        i < messages.length
        && messages[i].kind === 'speech'
        && messages[i].sender.name === senderName
        && !messages[i].streaming
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
        active: terminalSpeech === undefined && !followedByFinalSpeech,
      })
      continue
    }
    i += 1
  }
  return blocks
}
