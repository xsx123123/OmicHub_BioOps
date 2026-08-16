import { describe, expect, it } from 'vitest'
import { normalizeAgentStreamEvent, normalizePlanConfirmation } from '@/composables/useAgentChatStream'

describe('Agent SSE 事件归一化', () => {
  it.each([
    [{ type: 'text', content: 'content 字段' }, 'content 字段'],
    [{ event: 'delta', delta: 'delta 字段' }, 'delta 字段'],
    [{ type: 'message', text: 'text 字段' }, 'text 字段'],
    [{ type: 'done', answer: 'answer 字段' }, 'answer 字段'],
    [{ choices: [{ delta: { content: 'OpenAI delta' } }] }, 'OpenAI delta'],
    [{ data: { message: { content: '嵌套 message' } } }, '嵌套 message'],
  ])('兼容正文别名 %#', (raw, expected) => {
    expect(normalizeAgentStreamEvent(raw).content).toBe(expected)
  })

  it('将 reasoning_content 与正文分离', () => {
    const event = normalizeAgentStreamEvent({
      type: 'reasoning',
      delta: { reasoning_content: '推理内容' },
    })
    expect(event.reasoning).toBe('推理内容')
    expect(event.content).toBe('')
    expect(event.isReasoning).toBe(true)
  })
})

describe('计划确认事件归一化', () => {
  it('保留冻结版本、hash 与计划摘要字段', () => {
    expect(normalizePlanConfirmation({
      kind: 'plan_confirmation',
      run_id: 'run-42',
      plan_path: 'output/overdrive/session/run-42/plan.md',
      plan_version: 3,
      plan_hash: 'sha256:abc',
      actions: ['approve', 'revise', 'cancel', 'invalid'],
      summary: {
        title: 'RNA-seq 执行计划',
        summary: '先核验样本，再按依赖波次执行。',
        estimated_waves: 2,
        agents: [{ agent_id: 'agent-data', name: '数据管家', reason: '核验输入' }],
        manager_tasks: ['核验样本表'],
        risks: ['分组信息可能缺失'],
        approval_points: ['安装额外依赖'],
        deliverables: ['差异表达结果', '质控报告'],
      },
    })).toEqual({
      runId: 'run-42',
      title: 'RNA-seq 执行计划',
      summary: '先核验样本，再按依赖波次执行。',
      planPath: 'output/overdrive/session/run-42/plan.md',
      planVersion: 3,
      planHash: 'sha256:abc',
      waveCount: 2,
      agents: [{ agentId: 'agent-data', name: '数据管家', reason: '核验输入' }],
      serialPreflight: ['核验样本表'],
      risks: ['分组信息可能缺失'],
      approvalPoints: ['安装额外依赖'],
      deliverables: ['差异表达结果', '质控报告'],
      actions: ['approve', 'revise', 'cancel'],
      status: 'pending',
    })
  })

  it('只对 plan_confirmation 类型启用专用卡契约', () => {
    expect(normalizePlanConfirmation({ kind: 'questions', question: '请选择分组' })).toBeUndefined()
  })
})
