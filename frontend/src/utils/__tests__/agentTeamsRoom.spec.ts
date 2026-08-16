import { describe, expect, it } from 'vitest'
import type { AgentTeamsEvent } from '@/api/agentTeams'
import {
  buildRoomCreateIntent,
  formatDuration,
  formatHardGate,
  groupRoomMessages,
  isContentTruncated,
  MANAGER_TYPING_TTL_MS,
  parseManagerReport,
  projectCaseEvent,
  projectCaseEvents,
  resolveElementRoomUrl,
  resolveManagerTyping,
  resolveRoomSender,
  shouldStartNewRoomCase,
  type RoomRoleMetadata,
} from '@/utils/agentTeamsRoom'

const METADATA: RoomRoleMetadata = {
  role_labels: {
    'bioops-manager': { agent_id: 'bioops-manager', name: '协作经理', avatar: '🧭', color: '#4f8ef7', role: 'manager' },
    'data-steward': { agent_id: 'agent-data', name: '数据管理员', avatar: '🗂️', color: '#2563eb', role: 'worker' },
    'quality-auditor': { agent_id: 'agent-qc', name: '质量审计员', avatar: '🛡️', color: '#d97706', role: 'worker' },
  },
  role_agent_map: {
    'bioops-manager': 'bioops-manager',
    'data-steward': 'agent-data',
    'agent-data': 'agent-data',
    'quality-auditor': 'agent-qc',
  },
}

function makeEvent(
  eventType: string,
  payload: Record<string, unknown> = {},
  actor = 'bioops-manager',
  recordedAt = '2026-08-12T08:00:00Z',
): AgentTeamsEvent {
  return {
    event_id: `evt-${eventType}`,
    recorded_at: recordedAt,
    case_id: 'case-1',
    actor,
    event_type: eventType,
    payload,
  }
}

describe('resolveRoomSender', () => {
  it('resolves identity directly via role_labels', () => {
    expect(resolveRoomSender('bioops-manager', METADATA)).toEqual({
      name: '协作经理', avatar: '🧭', color: '#4f8ef7', role: 'manager',
    })
  })

  it('resolves alias identity via role_agent_map back to the canonical label', () => {
    expect(resolveRoomSender('agent-data', METADATA)).toMatchObject({
      name: '数据管理员', role: 'worker',
    })
  })

  it('falls back to manager identity for manager-like actors', () => {
    expect(resolveRoomSender('manager', {}).role).toBe('manager')
  })

  it('falls back to a local identity for unknown actors', () => {
    const sender = resolveRoomSender('agent-rnaseq', {})
    expect(sender.name).toBe('RNA-seq 分析师')
    expect(sender.role).toBe('worker')
  })
})

describe('projectCaseEvent', () => {
  it('projects room.user_message as current-user speech from nested payload', () => {
    const message = projectCaseEvent(
      makeEvent('room.user_message', {
        summary: '请解释一下质控结果',
        payload: { actor: 'user-1', content: '请解释一下质控结果' },
      }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'speech', content: '请解释一下质控结果' })
    expect(message?.sender.name).toBe('我')
    expect(message?.sender.role).toBe('manager')
  })

  it('falls back to summary when room.user_message has no nested content', () => {
    const message = projectCaseEvent(makeEvent('room.user_message', { summary: '短消息' }), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '短消息' })
  })

  it('projects room.created as a collapsed system line', () => {
    const message = projectCaseEvent(
      makeEvent('room.created', { payload: { room_id: '!room:test' } }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'system', collapsed: true })
  })

  it('projects room.agent_message as manager speech', () => {
    const message = projectCaseEvent(
      makeEvent('room.agent_message', {
        summary: '质控已通过',
        payload: { content: '质控已通过，可以交付。', agent_id: 'agent-general', role: 'bioops-manager' },
      }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'speech', content: '质控已通过，可以交付。' })
    expect(message?.sender.name).toBe('协作经理')
    expect(message?.sender.role).toBe('manager')
  })

  it('falls back to summary when room.agent_message has no nested content', () => {
    const message = projectCaseEvent(makeEvent('room.agent_message', { summary: '收到。' }), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '收到。' })
  })

  it('keeps case.created out of the visible room stream', () => {
    const message = projectCaseEvent(makeEvent('case.created', { plan_description: '拆解为三个工作项' }), METADATA)
    expect(message).toBeNull()
  })

  it('projects planning.frozen as manager speech with fallback content', () => {
    const message = projectCaseEvent(makeEvent('planning.frozen'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '规划完成，正在执行分析与解读。' })
  })

  it('appends quality gate hint to planning.frozen fallback when required', () => {
    const message = projectCaseEvent(makeEvent('planning.frozen', { quality_gate_required: true }), METADATA)
    expect(message?.content).toContain('规划完成，正在执行分析与解读')
    expect(message?.content).toContain('并将进行质量检查')
  })

  it('projects work_item.assigned as a system line naming the target role', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.assigned', { target: 'data-steward', objective: '预检样本表' }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'system', content: 'Manager 将任务分派给 数据管理员：预检样本表' })
  })

  it('strips the plan contract tail from work_item.assigned objectives', () => {
    const objective =
      '对这个 treefile 进行可视化并解释\n\n' +
      '请输出 proposed_submission，结构为 {"name": "...", "parameters": {"work_items": []}}'
    const message = projectCaseEvent(
      makeEvent('work_item.assigned', { target: 'agent-code', objective }),
      METADATA,
    )
    expect(message?.kind).toBe('system')
    expect(message?.content).toContain('对这个 treefile 进行可视化并解释')
    expect(message?.content).not.toContain('proposed_submission')
  })

  it('strips the plan contract tail from work_item.claimed objectives', () => {
    const objective = '把 result.csv 画成热图\n\n请输出 proposed_submission，结构为 {...}'
    const message = projectCaseEvent(makeEvent('work_item.claimed', { objective }, 'agent-viz'), METADATA)
    expect(message?.kind).toBe('speech')
    expect(message?.content).toBe('开始处理：把 result.csv 画成热图')
  })

  it('maps known skill_name to display name in work_item.claimed fallback', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice' }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe('开始处理：生成执行计划')
  })

  it('projects work_item.claimed as worker card start', () => {
    const message = projectCaseEvent(makeEvent('work_item.claimed', { objective: '跑 QC' }, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '开始处理：跑 QC' })
    expect(message?.sender.name).toBe('数据管理员')
  })

  it('projects work_item.running with fallback content', () => {
    const message = projectCaseEvent(makeEvent('work_item.running', {}, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '已领取任务，开始处理。' })
  })

  it('projects agent.tool_call as a progress line with display name mapping', () => {
    const message = projectCaseEvent(makeEvent('agent.tool_call', { tool: 'workspace_file_preview' }, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'progress', content: '正在调用 读取文件' })
    expect(message?.tool).toMatchObject({ name: '读取文件', status: 'running' })
  })

  it('projects agent.tool_result as a completed progress line with duration', () => {
    const message = projectCaseEvent(
      makeEvent('agent.tool_result', { tool: 'sandbox_execute', duration_ms: 1234, status: 'ok' }, 'data-steward'),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'progress', content: '沙箱执行 调用完成（1234ms）' })
  })

  it('formats tool duration in seconds when >= 5s', () => {
    const message = projectCaseEvent(
      makeEvent('agent.tool_result', { tool: 'sandbox_execute', duration_ms: 5200, status: 'ok' }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toContain('（5.2s）')
  })

  it('projects agent.tool_result failure state', () => {
    const message = projectCaseEvent(
      makeEvent('agent.tool_result', { tool: 'pipeline_query', status: 'failed' }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe('查询流程 调用失败')
  })

  it('projects agent.tool_call from Bridge-wrapped nested payload', () => {
    // Bridge record_evidence 会把原始证据包进外层 payload.payload（同 room 消息事件）
    const message = projectCaseEvent(
      makeEvent('agent.tool_call', {
        work_item_id: 'wi-1',
        summary: 'Agent agent-data 调用工具 sandbox_execute',
        payload: { tool: 'sandbox_execute', args_summary: '{}', work_item_id: 'wi-1', agent_id: 'agent-data' },
      }, 'data-steward'),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'progress', content: '正在调用 沙箱执行' })
  })

  it('projects agent.tool_result from Bridge-wrapped nested payload with duration and failure', () => {
    const message = projectCaseEvent(
      makeEvent('agent.tool_result', {
        work_item_id: 'wi-1',
        summary: '工具 sandbox_execute 执行失败',
        payload: { tool: 'sandbox_execute', success: false, duration_ms: 432, work_item_id: 'wi-1', agent_id: 'agent-data' },
      }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe('沙箱执行 调用失败（432ms）')
    expect(message?.tool).toMatchObject({ name: '沙箱执行', status: 'failed', durationMs: 432 })
  })

  it('projects skill.finished as worker final speech using conclusion', () => {
    const message = projectCaseEvent(makeEvent('skill.finished', { conclusion: 'QC 全部通过' }, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: 'QC 全部通过' })
  })

  it('projects skill.failed as terminal worker speech carrying the error', () => {
    const message = projectCaseEvent(makeEvent('skill.failed', { error: '样本表缺少 group 列', work_item_id: 'wi-1' }, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', terminal: 'failed', workItemId: 'wi-1', content: '任务执行失败：样本表缺少 group 列' })
  })

  it('projects skill.manual_review as error-state action message', () => {
    const message = projectCaseEvent(makeEvent('skill.manual_review', {}, 'data-steward'), METADATA)
    expect(message).toMatchObject({ kind: 'action', content: '任务需要人工复核。' })
  })

  it('projects skill.finished with terminal marker and work item id', () => {
    const artifacts = [{ path: 'tree.png', download_url: '/api/v1/files/file-1/download' }]
    const message = projectCaseEvent(makeEvent('skill.finished', {
      conclusion: 'QC 全部通过',
      work_item_id: 'wi-1',
      artifacts,
    }, 'data-steward'), METADATA)
    expect(message).toMatchObject({
      kind: 'speech',
      terminal: 'finished',
      workItemId: 'wi-1',
      content: 'QC 全部通过',
      artifacts,
    })
  })

  it('projects skill.finished body from findings when no conclusion/summary exists', () => {
    const message = projectCaseEvent(
      makeEvent('skill.finished', {
        skill_name: 'project-preflight',
        status: 'blocked',
        findings: [
          { code: 'F1', severity: 'error', message: '样本表缺少 group 列' },
          { code: 'F2', severity: 'warning', message: '分组样本数不均衡' },
        ],
      }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe('样本表缺少 group 列；分组样本数不均衡')
  })

  it('falls back to a generic body for skill.finished without any result text', () => {
    const message = projectCaseEvent(makeEvent('skill.finished', { skill_name: 'artifact-inspect', artifact_count: 1 }, 'data-steward'), METADATA)
    expect(message?.content).toBe('已完成本阶段任务。')
  })

  it('projects work_item.lease_expired as interrupted terminal speech', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.lease_expired', { work_item_id: 'wi-1', reason: '心跳超时' }, 'data-steward'),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'speech', terminal: 'interrupted', workItemId: 'wi-1' })
    expect(message?.content).toContain('租约过期')
    expect(message?.content).toContain('心跳超时')
  })

  it('projects work_item.retry_scheduled as a system line with delay and attempt', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.retry_scheduled', { work_item_id: 'wi-1', attempt: 1, max_attempts: 3, delay_seconds: 30 }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'system', content: '任务将在 30 秒后重试（第 1/3 次尝试）' })
  })

  it('projects work_item.retry_exhausted as an action line', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.retry_exhausted', { work_item_id: 'wi-1', attempt: 3, max_attempts: 3 }),
      METADATA,
    )
    expect(message?.kind).toBe('action')
    expect(message?.content).toContain('重试已达上限')
  })

  it('projects planning.validation_failed retry as Chinese summary with technical detail', () => {
    const message = projectCaseEvent(
      makeEvent('planning.validation_failed', {
        error: 'planned sample_sheet is missing required sample values',
        attempt: 1,
        max_attempts: 3,
      }),
      METADATA,
    )
    expect(message?.kind).toBe('action')
    expect(message?.content).toBe('计划生成不完整，正在自动重试（第 1/3 次）')
    expect(message?.technicalDetail).toBe('planned sample_sheet is missing required sample values')
  })

  it('projects planning.validation_failed retry_exhausted with actions', () => {
    const message = projectCaseEvent(
      makeEvent('planning.validation_failed', {
        error: 'general plan work item lacks objective or skill_name',
        attempt: 3,
        max_attempts: 3,
        retry_exhausted: true,
      }),
      METADATA,
    )
    expect(message?.kind).toBe('action')
    expect(message?.content).toContain('计划自动修正已达上限')
    expect(message?.technicalDetail).toBe('general plan work item lacks objective or skill_name')
    expect(message?.actions).toEqual([
      { label: '重试', action: 'retry' },
      { label: '修改需求', action: 'revise' },
      { label: '终止 Case', action: 'cancel' },
    ])
  })

  it('projects correction events', () => {
    const started = projectCaseEvent(
      makeEvent('correction_started', {
        correction_target: 'wi-1',
        missing_fields: ['objective', 'skill_name'],
        attempt: 1,
        max_attempts: 3,
      }),
      METADATA,
    )
    expect(started?.kind).toBe('action')
    expect(started?.content).toBe('自动修正计划：缺少 objective/skill_name（第 1/3 次）')

    const applied = projectCaseEvent(
      makeEvent('correction_applied', { reason: '补全缺失字段', attempt: 1, max_attempts: 3 }),
      METADATA,
    )
    expect(applied?.kind).toBe('system')
    expect(applied?.content).toBe('已根据校验反馈重新生成计划（第 1/3 次）：补全缺失字段')

    const failed = projectCaseEvent(
      makeEvent('correction_failed', {
        reason: '字段仍缺失',
        attempt: 3,
        max_attempts: 3,
        next_actions: ['retry', 'revise', 'cancel'],
      }),
      METADATA,
    )
    expect(failed?.kind).toBe('action')
    expect(failed?.content).toContain('计划自动修正已达上限')
    expect(failed?.actions).toHaveLength(3)
  })

  it('projects case.auto_approved as a system line', () => {
    const message = projectCaseEvent(makeEvent('case.auto_approved'), METADATA)
    expect(message).toMatchObject({ kind: 'system', content: '已根据你的授权自动批准' })
  })

  it('projects node_timeout as an action with retry action', () => {
    const message = projectCaseEvent(
      makeEvent('node_timeout', { node: 'planning', elapsed_seconds: 125 }),
      METADATA,
    )
    expect(message?.kind).toBe('action')
    expect(message?.content).toContain('规划节点超时')
    expect(message?.content).toContain('125.0s')
    expect(message?.actions).toEqual([{ label: '重试', action: 'retry' }])
  })

  it('projects planning.revised / case.execution_failed / case.retry_queued / case.closed', () => {
    expect(projectCaseEvent(makeEvent('planning.revised', { plan_version: 2, reason: '调整分组' }), METADATA))
      .toMatchObject({ kind: 'system', content: '执行计划已修订（版本 2）：调整分组' })
    const failed = projectCaseEvent(
      makeEvent('case.execution_failed', { error_excerpt: 'OOM killed', recommendation: '检查失败日志与输入后，确认重试以复用冻结计划。' }),
      METADATA,
    )
    expect(failed?.kind).toBe('action')
    expect(failed?.content).toContain('Case 执行失败：OOM killed')
    expect(failed?.content).toContain('确认重试')
    expect(projectCaseEvent(makeEvent('case.retry_queued'), METADATA))
      .toMatchObject({ kind: 'system', content: '已按冻结计划重新排队，等待重试任务执行。' })
    expect(projectCaseEvent(makeEvent('case.closed'), METADATA))
      .toMatchObject({ kind: 'system', content: 'Case 已交付并关闭。' })
  })

  it('attaches a parsed manager report to manager room.agent_message envelopes', () => {
    const envelope = JSON.stringify({
      conclusion: '质控整体通过',
      recommendations: ['补充生物学重复'],
      risks: ['样本量偏小'],
      evidence_refs: ['omic://tasks/t1/result'],
      hard_gate: { decision: 'BLOCKED', reason: '比对率低于阈值' },
    })
    const message = projectCaseEvent(
      makeEvent('room.agent_message', { payload: { content: envelope, role: 'bioops-manager' } }),
      METADATA,
    )
    expect(message?.managerReport).toEqual({
      conclusion: '质控整体通过',
      recommendations: ['补充生物学重复'],
      risks: ['样本量偏小'],
      evidenceRefs: ['omic://tasks/t1/result'],
      hardGate: { decision: 'BLOCKED', reason: '比对率低于阈值' },
    })
  })

  it('leaves room.agent_message without managerReport when content is plain text', () => {
    const message = projectCaseEvent(
      makeEvent('room.agent_message', { payload: { content: '质控已通过，可以交付。' } }),
      METADATA,
    )
    expect(message?.managerReport).toBeUndefined()
  })
  it('projects quality.decision as agent-qc speech', () => {
    const message = projectCaseEvent(makeEvent('quality.decision', { decision: 'pass', summary: '质量通过' }, 'quality-auditor'), METADATA)
    expect(message).toMatchObject({ kind: 'speech', content: '质量通过' })
    expect(message?.sender.name).toBe('质量审计员')
  })

  it('projects quality.hard_gate with qc fallback sender when actor unknown', () => {
    const message = projectCaseEvent(makeEvent('quality.hard_gate', { reason: '比对率低于阈值' }, 'unknown-actor'), METADATA)
    expect(message?.sender.name).toBe('质量审计员')
    expect(message?.content).toBe('比对率低于阈值')
  })

  it('projects case.cancelled as a system line with reason', () => {
    const message = projectCaseEvent(makeEvent('case.cancelled', { reason: '用户撤销' }), METADATA)
    expect(message).toMatchObject({ kind: 'system', content: 'Case 已取消：用户撤销' })
  })

  it('projects case.state_changed as a system line with translated transition', () => {
    const message = projectCaseEvent(makeEvent('case.state_changed', { from: 'received', to: 'executing' }), METADATA)
    expect(message).toMatchObject({ kind: 'system', content: 'Case 状态更新：已接收 → 执行中' })
  })

  it('projects omic_task.* as collapsed system lines', () => {
    const message = projectCaseEvent(makeEvent('omic_task.completed', { summary: 'task-9 完成' }), METADATA)
    expect(message).toMatchObject({ kind: 'system', collapsed: true, content: '任务已完成，转入质量核验（task-9 完成）' })
  })

  it('drops events outside the projection table', () => {
    expect(projectCaseEvent(makeEvent('approval.requested'), METADATA)).toBeNull()
    expect(projectCaseEvent(makeEvent('heartbeat'), METADATA)).toBeNull()
    expect(projectCaseEvent(makeEvent('room.typing', { payload: { typing: true } }), METADATA)).toBeNull()
  })
})

describe('resolveManagerTyping', () => {
  const NOW = Date.parse('2026-08-13T12:00:00Z')

  function typingEvent(typing: boolean, recordedAt = '2026-08-13T11:59:50Z'): AgentTeamsEvent {
    return makeEvent('room.typing', { payload: { typing } }, 'bioops-manager', recordedAt)
  }

  it('is typing after a fresh typing:true event', () => {
    expect(resolveManagerTyping([typingEvent(true)], NOW)).toBe(true)
  })

  it('stops typing on typing:false or a manager reply', () => {
    expect(resolveManagerTyping([typingEvent(true), typingEvent(false)], NOW)).toBe(false)
    expect(
      resolveManagerTyping(
        [typingEvent(true), makeEvent('room.agent_message', { payload: { content: '回复' } })],
        NOW,
      ),
    ).toBe(false)
  })

  it('ignores stale typing events beyond the freshness window', () => {
    const stale = typingEvent(true, '2026-08-13T10:00:00Z')
    expect(NOW - Date.parse('2026-08-13T10:00:00Z')).toBeGreaterThan(MANAGER_TYPING_TTL_MS)
    expect(resolveManagerTyping([stale], NOW)).toBe(false)
  })

  it('is not typing without any typing event', () => {
    expect(resolveManagerTyping([], NOW)).toBe(false)
  })
})

describe('projectCaseEvents', () => {
  it('keeps order and drops unmapped events', () => {
    const messages = projectCaseEvents([
      makeEvent('case.created', { summary: '计划就绪' }),
      makeEvent('approval.requested'),
      makeEvent('work_item.assigned', { target: 'data-steward' }),
    ], METADATA)
    expect(messages.map((m) => m.kind)).toEqual(['system'])
  })

  it('attaches structured tool info to tool progress messages', () => {
    const [call, result] = projectCaseEvents([
      makeEvent('agent.tool_call', { tool: 'sandbox_execute' }, 'data-steward'),
      makeEvent('agent.tool_result', { tool: 'sandbox_execute', duration_ms: 1234.6, status: 'ok' }, 'data-steward'),
    ], METADATA)
    expect(call.tool).toEqual({ name: '沙箱执行', status: 'running', durationMs: undefined })
    expect(result.tool).toEqual({ name: '沙箱执行', status: 'ok', durationMs: 1235 })
  })

  it('sorts events by recorded_at so evidence precedes later conclusions', () => {
    const messages = projectCaseEvents([
      {
        ...makeEvent('room.agent_message', {
          payload: { content: '结论已生成', role: 'bioops-manager' },
        }),
        recorded_at: '2026-08-12T08:00:02Z',
      },
      {
        ...makeEvent('agent.tool_result', {
          tool: 'workspace_read_file', duration_ms: 1200, status: 'ok',
        }, 'data-steward'),
        recorded_at: '2026-08-12T08:00:01Z',
      },
    ], METADATA)
    expect(messages.map((m) => m.kind)).toEqual(['progress', 'speech'])
  })
})

describe('groupRoomMessages', () => {
  it('aggregates a worker run into a card with tool steps and final body', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { objective: '跑 QC' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'sandbox_execute' }, 'data-steward'),
      makeEvent('agent.tool_result', { tool: 'sandbox_execute', duration_ms: 1200, status: 'ok' }, 'data-steward'),
      makeEvent('skill.finished', { conclusion: 'QC 全部通过' }, 'data-steward'),
    ], METADATA))
    expect(blocks).toHaveLength(1)
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.intro?.content).toBe('开始处理：跑 QC')
    expect(card.steps).toHaveLength(1)
    expect(card.steps[0].tool.status).toBe('ok')
    expect(card.steps[0].count).toBe(2)
    expect(card.steps[0].details).toHaveLength(2)
    expect(card.body?.content).toBe('QC 全部通过')
    expect(card.active).toBe(false)
    expect(card.failed).toBe(false)
  })

  it('marks a card active while the run ends in progress', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { objective: '跑 QC' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'sandbox_execute' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.steps).toHaveLength(1)
    expect(card.steps[0].tool.status).toBe('running')
    expect(card.active).toBe(true)
    expect(card.body).toBeUndefined()
  })

  it('marks a card failed when any tool step fails', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('agent.tool_result', { tool: 'pipeline_query', status: 'failed' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.failed).toBe(true)
  })

  it('folds consecutive same-name tool calls into one step with count and details', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { objective: '跑 QC' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'workspace_file_preview' }, 'data-steward'),
      makeEvent('agent.tool_result', { tool: 'workspace_file_preview', duration_ms: 75, status: 'ok' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'workspace_file_preview' }, 'data-steward'),
      makeEvent('agent.tool_result', { tool: 'workspace_file_preview', duration_ms: 70, status: 'ok' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'workspace_file_preview' }, 'data-steward'),
      makeEvent('skill.finished', { conclusion: '完成' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.steps).toHaveLength(1)
    expect(card.steps[0].tool.name).toBe('读取文件')
    expect(card.steps[0].count).toBe(5)
    expect(card.steps[0].details).toHaveLength(5)
    expect(card.steps[0].tool.durationMs).toBe(145)
  })

  it('keeps manager speech, system lines and lone worker speech as standalone blocks', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('case.created', { summary: '计划就绪' }),
      makeEvent('work_item.assigned', { target: 'data-steward' }),
      makeEvent('quality.decision', { summary: '质量通过' }, 'quality-auditor'),
    ], METADATA))
    expect(blocks.map((block) => block.type)).toEqual(['timeline', 'speech'])
  })

  it('splits runs when the sender changes', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('agent.tool_call', { tool: 'a' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'b' }, 'quality-auditor'),
    ], METADATA))
    expect(blocks).toHaveLength(2)
    expect(blocks.every((block) => block.type === 'worker')).toBe(true)
  })
})

describe('resolveElementRoomUrl', () => {
  it('returns the Element deep link carried by the latest room.created event', () => {
    const events = [
      makeEvent('room.created', { payload: { room_id: '!a:test', room_url: 'http://element.test/#/room/!a:test' } }),
      makeEvent('room.user_message', { payload: { content: 'hi' } }),
      makeEvent('room.created', { payload: { room_id: '!b:test', room_url: 'https://element.example/#/room/!b:test' } }),
    ]
    expect(resolveElementRoomUrl(events)).toBe('https://element.example/#/room/!b:test')
  })

  it('returns null when no room.created event carries a room_url', () => {
    expect(resolveElementRoomUrl([])).toBeNull()
    expect(resolveElementRoomUrl([makeEvent('room.created', { payload: { room_id: '!a:test' } })])).toBeNull()
  })

  it('rejects non-http(s) room URLs', () => {
    const events = [
      makeEvent('room.created', { payload: { room_url: 'javascript:alert(1)' } }),
    ]
    expect(resolveElementRoomUrl(events)).toBeNull()
  })
})

describe('buildRoomCreateIntent', () => {
  it('trims and collapses whitespace into a single-line intent', () => {
    expect(buildRoomCreateIntent('  帮我分析\n这两组样本   的差异 ')).toBe('帮我分析 这两组样本 的差异')
  })

  it('caps the intent at 256 characters to match the backend contract', () => {
    expect(buildRoomCreateIntent('x'.repeat(400))).toHaveLength(256)
  })
})

describe('formatDuration', () => {
  it('shows milliseconds for short durations', () => {
    expect(formatDuration(1234)).toBe('1234ms')
    expect(formatDuration(4999)).toBe('4999ms')
  })

  it('shows seconds with one decimal for durations >= 5s', () => {
    expect(formatDuration(5200)).toBe('5.2s')
    expect(formatDuration(30000)).toBe('30.0s')
  })

  it('returns empty string for undefined duration', () => {
    expect(formatDuration(undefined)).toBe('')
  })
})

describe('isContentTruncated', () => {
  it('detects content not ending with sentence punctuation', () => {
    expect(isContentTruncated('以')).toBe(true)
    expect(isContentTruncated('This is incomplete')).toBe(true)
  })

  it('treats sentence-ending punctuation as complete', () => {
    expect(isContentTruncated('已完成。')).toBe(false)
    expect(isContentTruncated('Done!')).toBe(false)
  })
})

describe('shouldStartNewRoomCase', () => {
  const treeRef = [{
    kind: 'file',
    id: 'tree-1',
    location: 'workspace/chat-uploads/example.treefile',
  }]

  it('forks a tree plotting request away from an unrelated case goal', () => {
    expect(shouldStartNewRoomCase(
      '介绍一下 Manager 能做什么',
      '@workspace/chat-uploads/example.treefile 帮我做一下系统发育树',
      treeRef,
    )).toBe(true)
  })

  it('keeps follow-up tree requests in an existing phylogeny case', () => {
    expect(shouldStartNewRoomCase('使用 treefile 绘制系统发育树', '把标签字体调大一点', treeRef)).toBe(false)
  })

  it('does not fork a general question without a referenced tree file', () => {
    expect(shouldStartNewRoomCase('介绍一下 Manager 能做什么', '系统发育树一般怎么构建？', [])).toBe(false)
  })

  it('does not treat the @-mentioned file path itself as a phylogeny keyword', () => {
    expect(shouldStartNewRoomCase(
      'TnpD 系统发育树可视化',
      '@workspace/chat-uploads/example.treefile 帮我对这个文件进行可视化并解释',
      treeRef,
    )).toBe(false)
  })
})

describe('parseManagerReport', () => {
  it('parses a bare JSON envelope', () => {
    const report = parseManagerReport(JSON.stringify({
      conclusion: '结论',
      recommendations: ['建议一'],
      risks: [],
      evidence_refs: [],
    }))
    expect(report).toEqual({ conclusion: '结论', recommendations: ['建议一'], risks: [], evidenceRefs: [], hardGate: undefined })
  })

  it('parses a fenced ```json code block', () => {
    const report = parseManagerReport('好的，结果如下：\n```json\n{"conclusion": "通过", "risks": ["风险一"]}\n```')
    expect(report).toMatchObject({ conclusion: '通过', risks: ['风险一'] })
  })

  it('parses a JSON envelope embedded in surrounding text', () => {
    const report = parseManagerReport('前言 {"conclusion": "嵌入结论", "recommendations": ["x"]} 后记')
    expect(report).toMatchObject({ conclusion: '嵌入结论', recommendations: ['x'] })
  })

  it('returns null for plain text or JSON without any known field', () => {
    expect(parseManagerReport('质控已通过，可以交付。')).toBeNull()
    expect(parseManagerReport('{"foo": 1, "bar": 2}')).toBeNull()
    expect(parseManagerReport('{"conclusion": "未闭合"')).toBeNull()
  })
})

describe('formatHardGate', () => {
  it('combines decision with a top-level reason', () => {
    expect(formatHardGate({ decision: 'BLOCKED', reason: '比对率低于阈值' })).toBe('质量硬门禁 BLOCKED：比对率低于阈值')
  })

  it('falls back to audit_event.reason', () => {
    expect(formatHardGate({ decision: 'BLOCKED', audit_event: { reason: 'mapping_rate 30% 低于 70%' } }))
      .toBe('质量硬门禁 BLOCKED：mapping_rate 30% 低于 70%')
  })

  it('has a generic fallback when no fields are present', () => {
    expect(formatHardGate({})).toBe('质量硬门禁已触发')
  })
})

describe('projectCaseEvents work-item start dedup', () => {
  it('merges duplicate claim/running placeholders of the same work item into one start message', () => {
    const messages = projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice', attempt: 1 }, 'data-steward'),
      makeEvent('work_item.running', { work_item_id: 'wi-1' }, 'data-steward'),
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice', attempt: 1 }, 'data-steward'),
    ], METADATA)
    expect(messages).toHaveLength(1)
    expect(messages[0].content).toBe('开始处理：生成执行计划')
  })

  it('keeps a re-claim with a higher attempt (legitimate retry)', () => {
    const messages = projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice', attempt: 1 }, 'data-steward'),
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice', attempt: 2 }, 'data-steward'),
    ], METADATA)
    expect(messages).toHaveLength(2)
  })

  it('does not dedup starts of different work items', () => {
    const messages = projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'a', attempt: 1 }, 'data-steward'),
      makeEvent('work_item.claimed', { work_item_id: 'wi-2', skill_name: 'b', attempt: 1 }, 'data-steward'),
    ], METADATA)
    expect(messages).toHaveLength(2)
  })
})

describe('groupRoomMessages terminal-state cards', () => {
  it('keeps a claim+running-only card in progress instead of faking completion', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'planning_advice', attempt: 1 }, 'data-steward'),
      makeEvent('work_item.running', { work_item_id: 'wi-1' }, 'data-steward'),
    ], METADATA))
    // claim/running 占位合并后只剩孤立开场发言，不包卡片、不显示「已完成」。
    expect(blocks).toHaveLength(1)
    expect(blocks[0].type).toBe('speech')
  })

  it('marks the card done only when skill.finished arrives, with its body', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'qc', attempt: 1 }, 'data-steward'),
      makeEvent('skill.finished', { work_item_id: 'wi-1', summary: 'QC 全部通过' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.active).toBe(false)
    expect(card.failed).toBe(false)
    expect(card.interrupted).toBe(false)
    expect(card.body?.content).toBe('QC 全部通过')
  })

  it('marks the card failed with the skill.failed error as body', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'qc', attempt: 1 }, 'data-steward'),
      makeEvent('skill.failed', { work_item_id: 'wi-1', error: '样本表缺少 group 列' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.failed).toBe(true)
    expect(card.active).toBe(false)
    expect(card.body?.content).toBe('任务执行失败：样本表缺少 group 列')
  })

  it('marks the card interrupted on work_item.lease_expired', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('work_item.claimed', { work_item_id: 'wi-1', skill_name: 'qc', attempt: 1 }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'sandbox_execute' }, 'data-steward'),
      makeEvent('work_item.lease_expired', { work_item_id: 'wi-1', reason: '心跳超时' }, 'data-steward'),
    ], METADATA))
    const card = blocks[0]
    expect(card.type).toBe('worker')
    if (card.type !== 'worker') return
    expect(card.interrupted).toBe(true)
    expect(card.active).toBe(false)
    expect(card.body?.content).toContain('租约过期')
  })

  it('renders a lone terminal failure speech as an action line', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('skill.failed', { error: '网关不可用' }, 'data-steward'),
    ], METADATA))
    expect(blocks).toHaveLength(1)
    expect(blocks[0].type).toBe('action')
  })
})
