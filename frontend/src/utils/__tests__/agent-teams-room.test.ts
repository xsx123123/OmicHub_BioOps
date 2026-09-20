import { describe, expect, it } from 'vitest'
import { parseManagerReport, projectCaseEvent, projectCaseEvents } from '@/utils/agentTeamsRoom'

describe('AgentTeams room manager report', () => {
  it('hides internal capability metadata while preserving real risks', () => {
    const report = parseManagerReport(JSON.stringify({
      conclusion: '这是正常的分析说明。',
      risks: [
        '未获准调用能力目录类只读工具：内部元数据',
        '样本量较小，统计效能有限',
      ],
    }))

    expect(report?.risks).toEqual(['样本量较小，统计效能有限'])
  })

  it('removes the internal risk section from legacy conclusions', () => {
    const report = parseManagerReport(JSON.stringify({
      conclusion: '这是正常的分析说明。\n\n风险\n本轮未获准调用能力目录类只读工具，本回复仅描述固定边界；具体领域能力以平台能力目录实况为准。',
      risks: [],
    }))

    expect(report?.conclusion).toBe('这是正常的分析说明。')
  })

  it('uses worker identity from the event payload instead of the audit actor', () => {
    const message = projectCaseEvent({
      event_id: 'worker-reply',
      recorded_at: '2026-08-25T00:00:00Z',
      case_id: 'case-1',
      actor: 'bioops-manager',
      event_type: 'room.agent_message',
      payload: {
        payload: {
          agent_id: 'agent-code',
          role: 'worker',
          content: '代码助手的结论',
        },
      },
    }, {
      role_labels: {
        'agent-code': {
          agent_id: 'agent-code', name: '代码助手', avatar: '💻', color: '#a855f7', role: 'worker',
        },
      },
    })

    expect(message?.sender.name).toBe('代码助手')
    expect(message?.sender.role).toBe('worker')
  })

  it('keeps worker reasoning under the worker identity in streamed events', () => {
    const messages = projectCaseEvents([
      {
        event_id: 'worker-thought',
        recorded_at: '2026-08-25T00:00:00Z',
        case_id: 'case-1',
        actor: 'bioops-manager',
        event_type: 'room.agent_stream',
        payload: {
          payload: {
            stream_id: 'stream-1', agent_id: 'agent-scrna', role: 'worker',
            channel: 'reasoning', delta: '先检查样本设计',
          },
        },
      },
    ], {
      role_labels: {
        'agent-scrna': {
          agent_id: 'agent-scrna', name: '单细胞分析师', avatar: '🧬', color: '#16a34a', role: 'worker',
        },
      },
    })

    expect(messages[0]?.sender.name).toBe('单细胞分析师')
    expect(messages[0]?.thought).toBe('先检查样本设计')
  })
})
