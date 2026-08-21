import type { AgentTeamsCaseStatus } from '@/api/agentTeams'

export type AgentTeamsStatusFormatter = (payload?: { attempt?: number; max_attempts?: number }) => string

export const agentTeamsStatusLabel: Record<AgentTeamsCaseStatus, string | AgentTeamsStatusFormatter> = {
  queued: '排队中',
  received: '已接收',
  planning_running: '规划中',
  preflight_running: '预检中',
  preflight_blocked: '预检阻断',
  waiting_for_correction: (payload) => {
    if (payload?.attempt !== undefined && payload?.max_attempts !== undefined) {
      return `自动修正中（第 ${payload.attempt}/${payload.max_attempts} 次）`
    }
    return '等待修正'
  },
  approval_pending: '待审批',
  approved: '已批准',
  executing: '执行中',
  execution_failed: '执行失败',
  quality_running: '质量检查中',
  quality_blocked: '质量阻断',
  remediation_pending: '等待修复',
  delivery_ready: '可交付',
  closed: '已关闭',
  cancelled: '已取消',
}

/**
 * 格式化 Case 状态枚举为用户可见中文文案。
 * 支持参数化映射（如自动修正中的第 n/3 次）。
 * 开发阶段若发现字典中不存在的状态，console.error 提示并返回兜底文案。
 */
export function formatAgentTeamsStatus(
  status: string,
  payload?: { attempt?: number; max_attempts?: number },
): string {
  if (!status) return ''
  const mapping = (agentTeamsStatusLabel as Record<string, string | AgentTeamsStatusFormatter>)[status]
  if (mapping === undefined) {
    if (import.meta.env.DEV) {
      console.error(`[AgentTeams] 缺失状态文案映射：${status}`)
    }
    return `未知状态（${status}）`
  }
  if (typeof mapping === 'function') return mapping(payload)
  return mapping
}

export const agentTeamsNextActor: Partial<Record<AgentTeamsCaseStatus, string>> = {
  queued: '协作资源队列',
  received: '数据管理员',
  preflight_running: '数据管理员',
  preflight_blocked: '请求人',
  waiting_for_correction: '请求人',
  approval_pending: '审批人',
  approved: '流程执行者',
  executing: '流程执行者',
  execution_failed: '流程执行者',
  quality_running: '质量控制',
  quality_blocked: '流程执行者',
  remediation_pending: '流程执行者',
  delivery_ready: '请求人',
}

/** Case 状态机五段：计划 → 审批 → 执行 → 质控 → 交付（房间顶部状态条使用）。 */
export type AgentTeamsCaseStage = 'plan' | 'approval' | 'execution' | 'quality' | 'delivery'

export const agentTeamsCaseStageMap: Record<AgentTeamsCaseStatus, AgentTeamsCaseStage> = {
  queued: 'plan',
  received: 'plan',
  planning_running: 'plan',
  preflight_running: 'plan',
  preflight_blocked: 'plan',
  waiting_for_correction: 'plan',
  approval_pending: 'approval',
  approved: 'approval',
  executing: 'execution',
  execution_failed: 'execution',
  quality_running: 'quality',
  quality_blocked: 'quality',
  remediation_pending: 'quality',
  delivery_ready: 'delivery',
  closed: 'delivery',
  cancelled: 'delivery',
}

/** 阻塞/失败/需人工介入的状态：状态条当前段用错误样式表达。 */
export const agentTeamsFailedStatuses: ReadonlySet<AgentTeamsCaseStatus> = new Set([
  'preflight_blocked',
  'waiting_for_correction',
  'execution_failed',
  'quality_blocked',
  'remediation_pending',
])

/** 尚未进入流程的状态（§1.7 真实状态优先）：房间头部步骤条对这些状态不激活任何
 *  步骤（全部未开始弱态），避免 received 被误表达为「计划进行中」。 */
export const agentTeamsPreStartStatuses: ReadonlySet<AgentTeamsCaseStatus> = new Set([
  'queued',
  'received',
])

/** 房间头部五步进度条的固定顺序（计划 → 审批 → 执行 → 质控 → 交付）。 */
export const AGENT_TEAMS_STAGE_SEQUENCE: Array<{ key: AgentTeamsCaseStage; label: string }> = [
  { key: 'plan', label: '计划' },
  { key: 'approval', label: '审批' },
  { key: 'execution', label: '执行' },
  { key: 'quality', label: '质控' },
  { key: 'delivery', label: '交付' },
]

export interface AgentTeamsStageViewItem {
  key: AgentTeamsCaseStage
  label: string
  index: number
  state: 'done' | 'current' | 'failed' | 'todo'
}

/** 五步进度条投影：Case 不存在（未立项房间）或状态缺失时返回 null（不渲染进度条），
 *  由会话头引导文案承接；激活步骤由 Case 状态映射单一事实源派生。 */
export function buildAgentTeamsStageView(
  status: AgentTeamsCaseStatus | '' | null | undefined,
): AgentTeamsStageViewItem[] | null {
  if (!status) return null
  const cancelled = status === 'cancelled'
  // queued/received 尚未进入流程，步骤条保持「未开始」弱态（全部未激活），
  // 不与「已接收」状态标签互相矛盾（§1.7）
  const preStart = agentTeamsPreStartStatuses.has(status)
  const currentIndex = AGENT_TEAMS_STAGE_SEQUENCE.findIndex((stage) => stage.key === agentTeamsCaseStageMap[status])
  const failed = agentTeamsFailedStatuses.has(status)
  return AGENT_TEAMS_STAGE_SEQUENCE.map((stage, index) => {
    let state: AgentTeamsStageViewItem['state']
    if (cancelled || preStart || index > currentIndex) state = 'todo'
    else if (index < currentIndex || status === 'closed') state = 'done'
    else state = failed ? 'failed' : 'current'
    return { ...stage, index, state }
  })
}

/** 终态 Case（房间同步与部分自动化的边界；发言不受限，见 canSendRoomMessage）。 */
export const agentTeamsTerminalStatuses: ReadonlySet<AgentTeamsCaseStatus> = new Set([
  'closed',
  'cancelled',
])

/** 房间输入框可发送条件：已选中 Case 即可发言（含终态——取消/关闭后仍可继续提问）。 */
export function canSendRoomMessage(status: AgentTeamsCaseStatus | '' | null | undefined): boolean {
  return !!status
}

/** 房间左栏过滤 chips 的四类归并。 */
export type AgentTeamsCaseCategory = 'active' | 'approval' | 'done' | 'failed'

export function agentTeamsCaseCategory(status: AgentTeamsCaseStatus): AgentTeamsCaseCategory {
  if (status === 'approval_pending') return 'approval'
  if (status === 'delivery_ready' || status === 'closed') return 'done'
  if (status === 'cancelled' || agentTeamsFailedStatuses.has(status)) return 'failed'
  return 'active'
}
