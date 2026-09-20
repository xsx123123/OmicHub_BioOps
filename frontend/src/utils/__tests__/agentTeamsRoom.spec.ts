import { describe, expect, it } from 'vitest'
import type { AgentTeamsEvent } from '@/api/agentTeams'
import {
  buildRoomCreateIntent,
  formatDuration,
  formatHardGate,
  formatRoomAskReply,
  groupRoomMessages,
  MANAGER_TYPING_TTL_MS,
  parseManagerReport,
  projectCaseEvent,
  projectCaseEvents,
  resolveElementRoomUrl,
  resolveManagerTyping,
  resolveRoomSender,
  resolveRoomTyping,
  ROOM_ASK_REPLY_MARKER,
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

  it('projects a structured domain-agent handoff', () => {
    const message = projectCaseEvent(
      makeEvent('room.agent_handoff', {
        payload: {
          from_agent_id: 'agent-data',
          to_agent_id: 'bioops-manager',
          work_item_ids: ['qc-1'],
          summary: '样本表核验已完成。',
          risks: ['缺少一个批次字段'],
          artifact_refs: ['output/sample-sheet.json'],
          recommended_next_action: 'request_user_review',
        },
      }, 'agent-data'),
      METADATA,
    )
    expect(message?.handoff).toMatchObject({
      fromAgentId: 'agent-data',
      toAgentId: 'bioops-manager',
      workItemIds: ['qc-1'],
      risks: ['缺少一个批次字段'],
      artifactRefs: ['output/sample-sheet.json'],
    })
    expect(message?.content).toBe('样本表核验已完成。')
  })

  it('projects a change assessment with decision options', () => {
    const message = projectCaseEvent(
      makeEvent('room.change_assessment', {
        payload: {
          agent_id: 'agent-scrna',
          work_item_ids: ['scrna-deg-1'],
          conclusion: '下游 DEG 需要重算。',
          risks: ['3v3 统计效能有限'],
          decision_options: ['resume', 'replan', 'branch', 'cancel'],
          decision: 'pending_user_confirmation',
        },
      }, 'agent-scrna'),
      METADATA,
    )
    expect(message?.changeAssessment?.workItemIds).toEqual(['scrna-deg-1'])
    expect(message?.changeAssessment?.decisionOptions).toEqual(['resume', 'replan', 'branch', 'cancel'])
    expect(message?.content).toBe('下游 DEG 需要重算。')
  })

  it('projects room.created as a collapsed system line', () => {
    const message = projectCaseEvent(
      makeEvent('room.created', { payload: { room_id: '!room:test' } }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'system', collapsed: true })
  })

  it('projects Matrix room provisioning failure as a visible fallback event', () => {
    const message = projectCaseEvent(
      makeEvent('room.provisioning_failed', {
        payload: {
          detail: 'connection refused',
          recovery: '检查 Gateway 网络后重试',
        },
      }),
      METADATA,
    )
    expect(message).toMatchObject({
      kind: 'system',
      content: 'Matrix 协作房间创建失败，已降级为平台事件流；分析任务不受影响。',
      technicalDetail: 'connection refused',
    })
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

  it('projects work_item.assigned as a manager dispatch card', () => {
    const message = projectCaseEvent(
      makeEvent('work_item.assigned', { target: 'data-steward', objective: '预检样本表' }),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'speech', content: 'Manager 将任务分派给 数据管理员：预检样本表' })
    expect(message?.sender.role).toBe('manager')
    expect(message?.dispatch).toEqual({ targetName: '数据管理员', objective: '预检样本表' })
  })

  it('strips the plan contract tail from work_item.assigned objectives', () => {
    const objective =
      '对这个 treefile 进行可视化并解释\n\n' +
      '请输出 proposed_submission，结构为 {"name": "...", "parameters": {"work_items": []}}'
    const message = projectCaseEvent(
      makeEvent('work_item.assigned', { target: 'agent-code', objective }),
      METADATA,
    )
    expect(message?.kind).toBe('speech')
    expect(message?.content).toContain('对这个 treefile 进行可视化并解释')
    expect(message?.content).not.toContain('proposed_submission')
    expect(message?.dispatch?.objective).toBe('对这个 treefile 进行可视化并解释')
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

  it('projects tool lifecycle while collapsing internal reinjection events', () => {
    const started = projectCaseEvent(
      makeEvent('agent.tool_started', { tool: 'workspace_read_file' }, 'data-steward'),
      METADATA,
    )
    expect(started).toMatchObject({ kind: 'progress', content: '工具执行中：读取文件', tool: { status: 'running' } })

    const reinjected = projectCaseEvent(
      makeEvent('agent.context_reinjected', { round: 2 }, 'data-steward'),
      METADATA,
    )
    expect(reinjected).toBeNull()

    const continued = projectCaseEvent(
      makeEvent('agent.turn_continued', { round: 3 }, 'data-steward'),
      METADATA,
    )
    expect(continued).toBeNull()
  })

  it('preserves correlated debug trace fields without expanding them into content', () => {
    const message = projectCaseEvent(
      makeEvent('agent.tool_result', {
        tool: 'workspace_read_file',
        tool_call_id: 'call-42',
        round: 2,
        execution_path: 'agentteams_worker_react',
        result_summary: '读取到 3 个样本',
        status: 'ok',
      }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe('读取文件 调用完成')
    expect(message?.debugTrace).toEqual({
      toolCallId: 'call-42',
      round: 2,
      executionPath: 'agentteams_worker_react',
      resultSummary: '读取到 3 个样本',
    })
  })

  it('projects loop guard as recoverable progress rather than an error card', () => {
    const message = projectCaseEvent(
      makeEvent('agent.loop_guard_triggered', {
        reason: 'duplicate_tool_call',
        tool: 'workspace_read_file',
        execution_path: 'agentteams_worker_react',
      }, 'data-steward'),
      METADATA,
    )
    expect(message).toMatchObject({ kind: 'progress', content: '已停止重复调用（读取文件），正在整理已有结果' })
    expect(message?.technicalDetail).toBe('agentteams_worker_react')
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

describe('room.agent_stream projection', () => {
  it('merges reasoning and text deltas into one live message, then settles on the final reply', () => {
    const streamId = 'manager-reply-1'
    const messages = projectCaseEvents(
      [
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'reasoning', delta: '先检查输入。', agent_id: 'agent-general' },
        }, 'bioops-manager', '2026-08-12T08:00:00Z'),
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'content', delta: '我已完成检查', agent_id: 'agent-general' },
        }, 'bioops-manager', '2026-08-12T08:00:01Z'),
        makeEvent('room.agent_message', {
          summary: '我已完成检查。',
          payload: { stream_id: streamId, content: '我已完成检查。', agent_id: 'agent-general' },
        }, 'bioops-manager', '2026-08-12T08:00:02Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({
      id: `stream:${streamId}`,
      content: '我已完成检查。',
      thought: '先检查输入。',
      streaming: false,
      streamId,
    })
  })

  it('shows an envelope conclusion while streaming and places its clarification card on the same message', () => {
    const streamId = 'manager-envelope-1'
    const pastedTextNotice = 'pasted text file: /tmp/pasted-text-1.txt. Read this file before continuing.'
    const messages = projectCaseEvents(
      [
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'content', delta: '{"conclusion":"收到需求。', agent_id: 'agent-general' },
        }, 'bioops-manager', '2026-08-12T08:00:00Z'),
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'content', delta: '请确认输入文件。","recommendations":["上传文件"]}', agent_id: 'agent-general' },
        }, 'bioops-manager', '2026-08-12T08:00:01Z'),
        makeEvent('room.ask_user', {
          payload: {
            stream_id: streamId,
            content: '收到需求。请确认输入文件。',
            manager_report: {
              conclusion: '收到需求。请确认输入文件。',
              recommendations: ['上传文件'],
              risks: ['尚未收到数据'],
            },
            questions: [{ question: '请上传输入文件。', options: [] }],
          },
        }, 'bioops-manager', '2026-08-12T08:00:02Z'),
        makeEvent('room.agent_message', { payload: { content: pastedTextNotice } }, 'bioops-manager', '2026-08-12T08:00:03Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({
      id: `stream:${streamId}`,
      content: '收到需求。请确认输入文件。',
      streaming: false,
      managerReport: {
        recommendations: ['上传文件'],
        risks: ['尚未收到数据'],
      },
      askRequest: { questions: [{ question: '请上传输入文件。', options: [] }] },
    })
    expect(messages[0].content).not.toContain('{"conclusion"')
  })

  it('attaches tool call events carrying stream_id to the speech bubble instead of progress rows', () => {
    const streamId = 'manager-tools-1'
    const messages = projectCaseEvents(
      [
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'reasoning', delta: '先查能力目录。', agent_id: 'bioops-manager' },
        }, 'bioops-manager', '2026-08-12T08:00:00Z'),
        makeEvent('agent.tool_call', {
          payload: { stream_id: streamId, tool: 'ability_catalog_query', tool_call_id: 'tc-1', args_summary: '{"scene":"phylo"}' },
        }, 'bioops-manager', '2026-08-12T08:00:01Z'),
        makeEvent('agent.tool_started', {
          payload: { stream_id: streamId, tool: 'ability_catalog_query', tool_call_id: 'tc-1' },
        }, 'bioops-manager', '2026-08-12T08:00:02Z'),
        makeEvent('agent.tool_result', {
          payload: { stream_id: streamId, tool: 'ability_catalog_query', tool_call_id: 'tc-1', success: true, duration_ms: 123, result_summary: '3 位专家' },
        }, 'bioops-manager', '2026-08-12T08:00:03Z'),
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'content', delta: '已确认专家能力。', agent_id: 'bioops-manager' },
        }, 'bioops-manager', '2026-08-12T08:00:04Z'),
        makeEvent('room.agent_message', {
          payload: { stream_id: streamId, content: '已确认专家能力。', agent_id: 'bioops-manager' },
        }, 'bioops-manager', '2026-08-12T08:00:05Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0].kind).toBe('speech')
    expect(messages[0].toolCalls).toEqual([
      {
        id: 'tc-1',
        name: 'ability_catalog_query',
        status: 'ok',
        durationMs: 123,
        argsSummary: '{"scene":"phylo"}',
        resultSummary: '3 位专家',
      },
    ])
  })

  it('attaches tool events that arrive before the first stream delta once the bubble is created', () => {
    const streamId = 'manager-tools-early'
    const messages = projectCaseEvents(
      [
        makeEvent('agent.tool_call', {
          payload: { stream_id: streamId, tool: 'room_messages_read', tool_call_id: 'tc-9' },
        }, 'bioops-manager', '2026-08-12T08:00:00Z'),
        makeEvent('agent.tool_result', {
          payload: { stream_id: streamId, tool: 'room_messages_read', tool_call_id: 'tc-9', success: false },
        }, 'bioops-manager', '2026-08-12T08:00:01Z'),
        makeEvent('room.agent_stream', {
          payload: { stream_id: streamId, channel: 'content', delta: '读取失败，改用已有上下文。', agent_id: 'bioops-manager' },
        }, 'bioops-manager', '2026-08-12T08:00:02Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0].toolCalls).toEqual([
      { id: 'tc-9', name: 'room_messages_read', status: 'failed' },
    ])
  })

  it('restores thought and tool cards from aggregation-injected payload when stream deltas are lost', () => {
    // 房间重开后 room.agent_stream 瞬态增量已丢失：后端把持久化的思考链/工具
    // 事件注入 room.agent_message 载荷，投影层直接取用。
    const streamId = 'manager-reload-1'
    const messages = projectCaseEvents(
      [
        makeEvent('room.agent_message', {
          payload: {
            stream_id: streamId,
            content: '已完成分析。',
            agent_id: 'bioops-manager',
            thought: '先读取房间消息，再汇总结论。',
            tool_calls: [
              { id: 'tc-1', name: 'room_messages_read', status: 'ok', duration_ms: 45, args_summary: '{}', result_summary: '61 条事件' },
            ],
          },
        }, 'bioops-manager', '2026-08-12T08:00:05Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0].thought).toBe('先读取房间消息，再汇总结论。')
    expect(messages[0].toolCalls).toEqual([
      { id: 'tc-1', name: 'room_messages_read', status: 'ok', durationMs: 45, argsSummary: '{}', resultSummary: '61 条事件' },
    ])
  })

  it('attaches orphan tool events to the final message when the stream bubble is gone after reload', () => {
    const streamId = 'manager-orphan-1'
    const messages = projectCaseEvents(
      [
        makeEvent('agent.tool_call', {
          payload: { stream_id: streamId, tool: 'room_messages_read', tool_call_id: 'tc-2', args_summary: '{"limit":100}' },
        }, 'bioops-manager', '2026-08-12T08:00:01Z'),
        makeEvent('agent.tool_result', {
          payload: { stream_id: streamId, tool: 'room_messages_read', tool_call_id: 'tc-2', success: true, duration_ms: 88, result_summary: '61 条事件' },
        }, 'bioops-manager', '2026-08-12T08:00:02Z'),
        makeEvent('room.agent_message', {
          payload: { stream_id: streamId, content: '已读取历史消息。', agent_id: 'bioops-manager' },
        }, 'bioops-manager', '2026-08-12T08:00:05Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0].toolCalls).toEqual([
      { id: 'tc-2', name: 'room_messages_read', status: 'ok', durationMs: 88, argsSummary: '{"limit":100}', resultSummary: '61 条事件' },
    ])
  })

  it('keeps worker tool events without stream_id as progress rows', () => {
    const messages = projectCaseEvents(
      [
        makeEvent('agent.tool_call', {
          payload: { tool: 'workspace_read', tool_call_id: 'tc-w1' },
        }, 'agent-data', '2026-08-12T08:00:00Z'),
      ],
      METADATA,
    )

    expect(messages).toHaveLength(1)
    expect(messages[0].kind).toBe('progress')
    expect(messages[0].tool).toMatchObject({ name: 'workspace_read', status: 'running' })
  })
})

describe('malformed manager envelope recovery', () => {
  it('renders a trailing-comma envelope as a structured report', () => {
    const content = `{
      "conclusion": "收到需求。在制定分析方案前，需要确认数据状态。",
      "recommendations": ["完成注释后进行 pseudobulk 差异分析"],
      "risks": ["3v3 设计的统计效能有限"],
      "ask_user": [{"question": "来自什么组织？", "options": [],}],
    }`
    const message = projectCaseEvent(
      makeEvent('room.agent_message', { payload: { content } }, 'bioops-manager'),
      METADATA,
    )

    expect(message?.managerReport).toMatchObject({
      conclusion: '收到需求。在制定分析方案前，需要确认数据状态。',
      recommendations: ['完成注释后进行 pseudobulk 差异分析'],
      risks: ['3v3 设计的统计效能有限'],
    })
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
    expect(resolveManagerTyping([typingEvent(true), typingEvent(false, '2026-08-13T11:59:55Z')], NOW)).toBe(false)
    expect(
      resolveManagerTyping(
        [typingEvent(true), makeEvent('room.agent_message', { payload: { content: '回复' } }, 'bioops-manager', '2026-08-13T11:59:55Z')],
        NOW,
      ),
    ).toBe(false)
  })

  it('stops typing when a stream chunk arrives', () => {
    expect(
      resolveManagerTyping(
        [typingEvent(true), makeEvent('room.agent_stream', { payload: { delta: '…' } }, 'bioops-manager', '2026-08-13T11:59:55Z')],
        NOW,
      ),
    ).toBe(false)
  })

  it('orders by recorded_at so a late-delivered typing:true cannot resurrect the indicator', () => {
    // SSE 丢失 typing:true 后由轮询补回：数组顺序中它在回复事件之后，但时间戳更早
    const reply = makeEvent('room.agent_message', { payload: { content: '回复' } }, 'bioops-manager', '2026-08-13T11:59:55Z')
    expect(resolveManagerTyping([typingEvent(true), reply], NOW)).toBe(false)
    expect(resolveManagerTyping([reply, typingEvent(true)], NOW)).toBe(false)
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

describe('resolveRoomTyping', () => {
  const NOW = Date.parse('2026-08-13T12:00:00Z')

  function agentTypingEvent(typing: boolean, agentName?: string, recordedAt = '2026-08-13T11:59:50Z'): AgentTeamsEvent {
    return makeEvent('room.typing', { payload: { typing, agent_name: agentName } }, 'agent-coder', recordedAt)
  }

  it('returns the agent_name carried by a domain-agent typing event', () => {
    expect(resolveRoomTyping([agentTypingEvent(true, '代码助手')], NOW)).toEqual({ active: true, agentName: '代码助手' })
  })

  it('returns null agentName for manager typing events without agent_name', () => {
    const managerTyping = makeEvent('room.typing', { payload: { typing: true } }, 'bioops-manager', '2026-08-13T11:59:50Z')
    expect(resolveRoomTyping([managerTyping], NOW)).toEqual({ active: true, agentName: null })
  })

  it('clears agentName once the reply event arrives', () => {
    const reply = makeEvent('room.agent_message', { payload: { content: '回复' } }, 'agent-coder', '2026-08-13T11:59:55Z')
    expect(resolveRoomTyping([agentTypingEvent(true, '代码助手'), reply], NOW)).toEqual({ active: false, agentName: null })
  })

  it('clears agentName on typing:false', () => {
    expect(
      resolveRoomTyping([agentTypingEvent(true, '代码助手'), agentTypingEvent(false, '代码助手', '2026-08-13T11:59:55Z')], NOW),
    ).toEqual({ active: false, agentName: null })
  })
})

describe('projectCaseEvents', () => {
  it('keeps order and drops unmapped events', () => {
    const messages = projectCaseEvents([
      makeEvent('case.created', { summary: '计划就绪' }),
      makeEvent('approval.requested'),
      makeEvent('work_item.assigned', { target: 'data-steward' }),
    ], METADATA)
    expect(messages.map((m) => m.kind)).toEqual(['speech'])
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

  it('closes open streams when a typing:false event arrives', () => {
    const messages = projectCaseEvents([
      makeEvent('room.agent_stream', { payload: { stream_id: 's-1', channel: 'content', delta: '正在分析' } }),
      makeEvent('room.typing', { payload: { typing: false } }),
    ], METADATA)
    expect(messages).toHaveLength(1)
    expect(messages[0].streaming).toBe(false)
    expect(messages[0].content).toBe('正在分析')
  })

  it('closes an orphan stream when the final reply arrives without stream_id', () => {
    const messages = projectCaseEvents([
      makeEvent('room.agent_stream', { payload: { stream_id: 's-1', channel: 'content', delta: '部分回复' } }),
      makeEvent('room.agent_message', { payload: { content: '完整回复' } }),
    ], METADATA)
    expect(messages).toHaveLength(2)
    expect(messages[0].streaming).toBe(false)
    expect(messages[1].content).toBe('完整回复')
  })

  it('keeps long skill.finished conclusions up to the 2k cap', () => {
    const conclusion = '结论'.repeat(300)
    const message = projectCaseEvent(
      makeEvent('skill.finished', { conclusion, work_item_id: 'wi-1' }, 'data-steward'),
      METADATA,
    )
    expect(message?.content).toBe(conclusion)
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
    expect(blocks.map((block) => block.type)).toEqual(['speech', 'speech'])
  })

  it('splits runs when the sender changes', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('agent.tool_call', { tool: 'a' }, 'data-steward'),
      makeEvent('agent.tool_call', { tool: 'b' }, 'quality-auditor'),
    ], METADATA))
    expect(blocks).toHaveLength(2)
    expect(blocks.every((block) => block.type === 'worker')).toBe(true)
  })

  it('closes a manager tool card when the final reply bubble follows', () => {
    const blocks = groupRoomMessages(projectCaseEvents([
      makeEvent('agent.tool_call', { tool: 'sandbox_execute' }, 'bioops-manager'),
      makeEvent('agent.tool_result', { tool: 'sandbox_execute', duration_ms: 100, status: 'ok' }, 'bioops-manager'),
      makeEvent('room.agent_message', { payload: { content: '会诊结论' } }),
    ], METADATA))
    expect(blocks.map((block) => block.type)).toEqual(['worker', 'speech'])
    const card = blocks[0]
    if (card.type !== 'worker') throw new Error('expected a worker card')
    expect(card.active).toBe(false)
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

describe('room.ask_user clarification card', () => {
  const askEvent = () =>
    makeEvent('room.ask_user', {
      summary: '启动规划前需要你确认几个关键信息。',
      payload: {
        content: '启动规划前需要你确认几个关键信息。',
        role: 'bioops-manager',
        questions: [
          { question: '输入数据是计数矩阵还是 FASTQ？', options: ['已有计数矩阵', '从 FASTQ 开始'] },
          { question: '物种与参考基因组版本？', options: [] },
        ],
      },
    })

  it('projects a room.ask_user event into a speech message with an interactive ask card', () => {
    const message = projectCaseEvent(askEvent(), METADATA)
    expect(message).not.toBeNull()
    expect(message?.kind).toBe('speech')
    expect(message?.sender.role).toBe('manager')
    expect(message?.content).toBe('启动规划前需要你确认几个关键信息。')
    expect(message?.askRequest?.questions).toEqual([
      { question: '输入数据是计数矩阵还是 FASTQ？', options: ['已有计数矩阵', '从 FASTQ 开始'] },
      { question: '物种与参考基因组版本？', options: [] },
    ])
    expect(message?.askRequest?.answered).toBeFalsy()
  })

  it('drops room.ask_user events without any valid question', () => {
    const message = projectCaseEvent(
      makeEvent('room.ask_user', { payload: { content: '无问题', questions: [] } }),
      METADATA,
    )
    expect(message).toBeNull()
  })

  it('ends the manager typing indicator when the ask card arrives', () => {
    const now = Date.parse('2026-08-12T08:01:00Z')
    expect(
      resolveManagerTyping(
        [
          makeEvent('room.typing', { payload: { typing: true } }),
          askEvent(),
        ],
        now,
      ),
    ).toBe(false)
  })

  it('marks the card unanswered while no later user message exists', () => {
    const messages = projectCaseEvents([askEvent()], METADATA)
    expect(messages[0].askRequest?.answered).toBeFalsy()
  })

  it('marks the card answered and backfills answers from the formatted reply message', () => {
    const questions = [
      { question: '输入数据是计数矩阵还是 FASTQ？', options: ['已有计数矩阵', '从 FASTQ 开始'] },
      { question: '物种与参考基因组版本？', options: [] },
    ]
    const reply = formatRoomAskReply(questions, ['从 FASTQ 开始', ''])
    expect(reply).toContain(ROOM_ASK_REPLY_MARKER)
    const messages = projectCaseEvents(
      [
        askEvent(),
        makeEvent(
          'room.user_message',
          { summary: reply.slice(0, 80), payload: { actor: 'current-user', content: reply } },
          'current-user',
          '2026-08-12T08:02:00Z',
        ),
      ],
      METADATA,
    )
    expect(messages[0].askRequest?.answered).toBe(true)
    expect(messages[0].askRequest?.answers).toEqual(['从 FASTQ 开始', '无偏好，由你决定'])
  })

  it('folds the consumed clarification reply into the card instead of a separate user bubble', () => {
    const questions = [
      { question: '输入数据是计数矩阵还是 FASTQ？', options: ['已有计数矩阵', '从 FASTQ 开始'] },
      { question: '物种与参考基因组版本？', options: [] },
    ]
    const reply = formatRoomAskReply(questions, ['从 FASTQ 开始', ''])
    const messages = projectCaseEvents(
      [
        askEvent(),
        makeEvent(
          'room.user_message',
          { summary: reply.slice(0, 80), payload: { actor: 'current-user', content: reply } },
          'current-user',
          '2026-08-12T08:02:00Z',
        ),
      ],
      METADATA,
    )
    // 回复被卡片消费：时间线上只剩 ask 卡片，不再出现蓝色用户气泡
    expect(messages).toHaveLength(1)
    expect(messages[0].askRequest?.answered).toBe(true)
    expect(messages.some((item) => item.isUser)).toBe(false)
  })

  it('degrades an unconsumed clarification reply to plain text without the internal marker', () => {
    // 历史落库缺卡片（room.ask_user 无有效问题被丢弃）：回复剥离标记后纯文本展示，不崩
    const questions = [{ question: '物种？', options: [] }]
    const reply = formatRoomAskReply(questions, ['人'])
    const messages = projectCaseEvents(
      [
        makeEvent('room.ask_user', { payload: { content: '无问题', questions: [] } }),
        makeEvent(
          'room.user_message',
          { summary: reply.slice(0, 80), payload: { actor: 'current-user', content: reply } },
          'current-user',
          '2026-08-12T08:02:00Z',
        ),
      ],
      METADATA,
    )
    expect(messages).toHaveLength(1)
    expect(messages[0].isUser).toBe(true)
    expect(messages[0].content).not.toContain(ROOM_ASK_REPLY_MARKER)
    expect(messages[0].content).toContain('人')
  })

  it('keeps a normal later user message visible without marking the card answered', () => {
    const messages = projectCaseEvents(
      [
        askEvent(),
        makeEvent(
          'room.user_message',
          { summary: '继续', payload: { actor: 'current-user', content: '继续' } },
          'current-user',
          '2026-08-12T08:02:00Z',
        ),
      ],
      METADATA,
    )
    expect(messages[0].askRequest?.answered).toBeFalsy()
    expect(messages).toHaveLength(2)
    expect(messages[1].content).toBe('继续')
  })
})

describe('room.route_decision routing card', () => {
  const decisionPayload = (overrides: Record<string, unknown> = {}) => ({
    path: 'bridge_workflow',
    flow_id: 'rnaseq',
    flow_label: 'bulk RNA-seq 差异分析',
    matched_hints: ['RNA-seq'],
    lead_planner: 'agent-rnaseq',
    planner_scores: { 'agent-rnaseq': 1 },
    estimated_stages: [
      { key: 'quantify', title: '定量' },
      { key: 'differential', title: '差异分析' },
    ],
    participants: ['agent-rnaseq'],
    confidence: 'high',
    ...overrides,
  })
  const routeEvent = (payload: Record<string, unknown>) =>
    makeEvent('room.route_decision', { summary: '路由决策', payload })

  it('projects a high-confidence decision into a collapsible route card message', () => {
    const message = projectCaseEvent(routeEvent(decisionPayload()), METADATA)
    expect(message).not.toBeNull()
    expect(message?.kind).toBe('speech')
    expect(message?.sender.role).toBe('manager')
    expect(message?.content).toBe('已选择「bulk RNA-seq 差异分析」 · 规划者 agent-rnaseq · 预计 2 个阶段')
    expect(message?.askRequest).toBeUndefined()
    expect(message?.routeDecision).toMatchObject({
      path: 'bridge_workflow',
      flowId: 'rnaseq',
      flowLabel: 'bulk RNA-seq 差异分析',
      matchedHints: ['RNA-seq'],
      leadPlanner: 'agent-rnaseq',
      plannerScores: { 'agent-rnaseq': 1 },
      confidence: 'high',
    })
    expect(message?.routeDecision?.estimatedStages).toEqual([
      { key: 'quantify', title: '定量' },
      { key: 'differential', title: '差异分析' },
    ])
  })

  it('upgrades an ambiguous decision into an option-style confirmation card', () => {
    const message = projectCaseEvent(
      routeEvent(
        decisionPayload({
          path: 'overdrive',
          flow_id: null,
          flow_label: '通用分析',
          matched_hints: [],
          lead_planner: 'agent-general',
          confidence: 'ambiguous',
          options: [
            { flow_id: 'rnaseq', label: 'bulk RNA-seq 差异分析', lead_planner: 'agent-rnaseq', stages: 2 },
            { flow_id: null, label: '通用分析(由 Manager 自由规划)', lead_planner: 'agent-general', stages: 3 },
          ],
        }),
      ),
      METADATA,
    )
    expect(message).not.toBeNull()
    expect(message?.routeDecision?.confidence).toBe('ambiguous')
    expect(message?.content).toContain('请点选裁决')
    expect(message?.askRequest?.questions).toEqual([
      {
        question: '检测到多种可能的执行路径，请点选裁决：',
        options: [
          'bulk RNA-seq 差异分析（规划者 agent-rnaseq · 2 个阶段）',
          '通用分析(由 Manager 自由规划)（规划者 agent-general · 3 个阶段）',
        ],
      },
    ])
  })

  it('consumes the option reply into the ambiguous card via the ask-answer backfill chain', () => {
    const event = routeEvent(
      decisionPayload({
        confidence: 'ambiguous',
        options: [
          { flow_id: 'rnaseq', label: 'bulk RNA-seq 差异分析', lead_planner: 'agent-rnaseq', stages: 2 },
          { flow_id: null, label: '通用分析(由 Manager 自由规划)', lead_planner: 'agent-general', stages: 3 },
        ],
      }),
    )
    const questions = [
      {
        question: '检测到多种可能的执行路径，请点选裁决：',
        options: ['bulk RNA-seq 差异分析（规划者 agent-rnaseq · 2 个阶段）'],
      },
    ]
    const reply = formatRoomAskReply(questions, ['bulk RNA-seq 差异分析（规划者 agent-rnaseq · 2 个阶段）'])
    const messages = projectCaseEvents(
      [
        event,
        makeEvent(
          'room.user_message',
          { summary: reply.slice(0, 80), payload: { actor: 'current-user', content: reply } },
          'current-user',
          '2026-08-12T08:02:00Z',
        ),
      ],
      METADATA,
    )
    // 回复被卡片消费：卡片标记已答，时间线上不再出现单独的用户气泡
    expect(messages).toHaveLength(1)
    expect(messages[0].askRequest?.answered).toBe(true)
    expect(messages[0].askRequest?.answers).toEqual(['bulk RNA-seq 差异分析（规划者 agent-rnaseq · 2 个阶段）'])
    expect(messages.some((item) => item.isUser)).toBe(false)
  })

  it('drops route_decision events without a valid path', () => {
    expect(projectCaseEvent(routeEvent({ flow_id: 'rnaseq' }), METADATA)).toBeNull()
  })
})

describe('room.route_transition 咨询分诊转场卡投影', () => {
  const transitionPayload = (overrides: Record<string, unknown> = {}) => ({
    from_agent_id: 'agentteams-manager',
    from_name: '生物信息部门经理',
    target_agent_id: 'agent-rnaseq',
    target_name: 'RNA-seq 专家',
    reason: 'RNA-seq 原理属转录组领域',
    confidence: 0.92,
    trigger: 'consultation_triage',
    causation_event_id: 'evt-room.user_message',
    ...overrides,
  })
  const transitionEvent = (payload: Record<string, unknown>) =>
    makeEvent('room.route_transition', { summary: '咨询分诊', payload }, 'agentteams-manager')

  it('projects a triage transition into a card-only speech message', () => {
    const message = projectCaseEvent(transitionEvent(transitionPayload()), METADATA)
    expect(message).not.toBeNull()
    expect(message?.kind).toBe('speech')
    expect(message?.sender.role).toBe('manager')
    expect(message?.content).toBe('')
    expect(message?.hideContent).toBe(true)
    expect(message?.routeTransition).toEqual({
      fromAgentId: 'agentteams-manager',
      fromName: '生物信息部门经理',
      targetAgentId: 'agent-rnaseq',
      targetName: 'RNA-seq 专家',
      reason: 'RNA-seq 原理属转录组领域',
      confidence: 0.92,
      trigger: 'consultation_triage',
      causationEventId: 'evt-room.user_message',
    })
  })

  it('resolves missing display names via role metadata', () => {
    const message = projectCaseEvent(
      transitionEvent(transitionPayload({ from_name: '', target_name: '', target_agent_id: 'data-steward' })),
      METADATA,
    )
    expect(message?.routeTransition?.fromName).toBe('生物信息部门经理')
    expect(message?.routeTransition?.targetName).toBe('数据管理员')
  })

  it('drops route_transition events without any target identity', () => {
    expect(
      projectCaseEvent(transitionEvent(transitionPayload({ target_agent_id: '', target_name: '' })), METADATA),
    ).toBeNull()
  })

  it('marks expert replies routed by manager triage with routedBy', () => {
    const message = projectCaseEvent(
      makeEvent('room.agent_message', {
        payload: {
          role: 'worker',
          agent_id: 'agent-rnaseq',
          content: 'RNA-seq 通过测序 reads 定量基因表达……',
          routed_by: 'manager_triage',
        },
      }),
      METADATA,
    )
    expect(message?.routedBy).toBe('manager_triage')
  })

  it('leaves routedBy undefined for legacy messages without routed_by', () => {
    const message = projectCaseEvent(
      makeEvent('room.agent_message', {
        payload: { role: 'worker', agent_id: 'agent-rnaseq', content: '常规回复' },
      }),
      METADATA,
    )
    expect(message?.routedBy).toBeUndefined()
  })
})

describe('room.proposal_confirm 立项确认卡投影', () => {
  function proposalPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      agent_id: 'bioops-manager',
      role: 'bioops-manager',
      causation_event_id: 'evt-room.user_message',
      confirm_token: 'tok-test-0123456789abcdef',
      proposal_kind: 'new_case',
      status: 'pending',
      objective: '我有 6 个小鼠样本 3vs3 要做差异分析',
      flow_id: 'rnaseq',
      flow_label: 'bulk RNA-seq 差异分析',
      lead_planner: 'agent-rnaseq',
      route_path: 'bridge_workflow',
      participants: ['data-steward', 'quality-auditor'],
      estimated_stages: [
        { key: 'plan', title: '计划' },
        { key: 'execution', title: '执行' },
      ],
      confidence: 'high',
      origin_content: '我有 6 个小鼠样本 3vs3 要做差异分析',
      context_refs: [],
      source_case_id: null,
      options: ['confirm', 'modify', 'cancel'],
      created_at: '2026-08-20T08:00:00Z',
      ...overrides,
    }
  }

  function proposalEvent(
    overrides: Record<string, unknown> = {},
    recordedAt = '2026-08-12T08:00:00Z',
    eventId = 'evt-room.proposal_confirm',
  ): AgentTeamsEvent {
    // 房间级事件挂在 room-<room_id> 命名空间记录下，与 Case 事件同一渲染
    return {
      ...makeEvent('room.proposal_confirm', { summary: '立项确认：小鼠差异分析', payload: proposalPayload(overrides) }, 'bioops-manager', recordedAt),
      event_id: eventId,
      case_id: 'room-room-1',
    }
  }

  it('projects a pending new_case proposal into an interactive card message', () => {
    const message = projectCaseEvent(proposalEvent(), METADATA)
    expect(message?.kind).toBe('speech')
    expect(message?.hideContent).toBe(true)
    expect(message?.proposal).toMatchObject({
      proposalKind: 'new_case',
      confirmToken: 'tok-test-0123456789abcdef',
      status: 'pending',
      objective: '我有 6 个小鼠样本 3vs3 要做差异分析',
      flowLabel: 'bulk RNA-seq 差异分析',
      participants: ['data-steward', 'quality-auditor'],
      options: ['confirm', 'modify', 'cancel'],
    })
    expect(message?.proposal?.estimatedStages).toHaveLength(2)
  })

  it('projects a followup proposal with continue/new/cancel options and source case', () => {
    const message = projectCaseEvent(proposalEvent({
      proposal_kind: 'followup',
      source_case_id: 'bioops_prev1',
      options: ['continue', 'new', 'cancel'],
    }), METADATA)
    expect(message?.proposal?.proposalKind).toBe('followup')
    expect(message?.proposal?.sourceCaseId).toBe('bioops_prev1')
    expect(message?.proposal?.options).toEqual(['continue', 'new', 'cancel'])
  })

  it('keeps proposal events without a confirm_token (B1: token 不再经事件流分发)', () => {
    const message = projectCaseEvent(proposalEvent({ confirm_token: null }), METADATA)
    expect(message?.proposal).toMatchObject({
      proposalKind: 'new_case',
      confirmToken: '',
      status: 'pending',
      objective: '我有 6 个小鼠样本 3vs3 要做差异分析',
    })
  })

  it('marks the card confirmed when room.case_bound lands after it', () => {
    const messages = projectCaseEvents([
      proposalEvent(),
      {
        ...makeEvent('room.case_bound', { summary: '立项已确认，协作 Case 创建完成', payload: { case_id: 'bioops_new1' } }, 'bioops-manager', '2026-08-12T08:01:00Z'),
        case_id: 'room-room-1',
      },
    ], METADATA)
    const card = messages.find((item) => item.proposal)
    expect(card?.proposal?.status).toBe('confirmed')
    // case_bound 自身投影为系统时间轴行
    expect(messages.some((item) => item.kind === 'system' && item.content.includes('立项已确认'))).toBe(true)
  })

  it('marks the card cancelled / modify_requested from the close events', () => {
    const cancelled = projectCaseEvents([
      proposalEvent(),
      { ...makeEvent('room.proposal_cancelled', { summary: '用户取消了本次立项' }, 'bioops-manager', '2026-08-12T08:01:00Z'), case_id: 'room-room-1' },
    ], METADATA)
    expect(cancelled.find((item) => item.proposal)?.proposal?.status).toBe('cancelled')

    const modified = projectCaseEvents([
      proposalEvent(),
      { ...makeEvent('room.proposal_modify_requested', { summary: '用户要求调整立项内容，请补充说明' }, 'bioops-manager', '2026-08-12T08:01:00Z'), case_id: 'room-room-1' },
    ], METADATA)
    expect(modified.find((item) => item.proposal)?.proposal?.status).toBe('modify_requested')
  })

  it('marks an earlier pending card superseded when a newer proposal replaces it', () => {
    const messages = projectCaseEvents([
      proposalEvent({ confirm_token: 'tok-old-0123456789abcdef' }, '2026-08-12T08:00:00Z', 'evt-proposal-old'),
      proposalEvent({ confirm_token: 'tok-new-0123456789abcdef' }, '2026-08-12T08:02:00Z', 'evt-proposal-new'),
    ], METADATA)
    const cards = messages.filter((item) => item.proposal)
    expect(cards).toHaveLength(2)
    expect(cards[0].proposal?.status).toBe('superseded')
    expect(cards[1].proposal?.status).toBe('pending')
  })

  it('merges room-namespace and case events by recorded_at into one timeline', () => {
    const messages = projectCaseEvents([
      // Case 流事件先到达但时间更晚；房间命名空间事件应在它之前
      makeEvent('room.agent_message', { payload: { content: 'Case 侧回复' } }, 'bioops-manager', '2026-08-12T08:00:02Z'),
      { ...makeEvent('room.user_message', { payload: { actor: 'current-user', content: '房间侧发言' } }, 'current-user', '2026-08-12T08:00:01Z'), case_id: 'room-room-1' },
      proposalEvent({}, '2026-08-12T08:00:03Z'),
    ], METADATA)
    expect(messages.map((item) => (item.proposal ? 'proposal' : item.content))).toEqual([
      '房间侧发言',
      'Case 侧回复',
      'proposal',
    ])
  })
})
