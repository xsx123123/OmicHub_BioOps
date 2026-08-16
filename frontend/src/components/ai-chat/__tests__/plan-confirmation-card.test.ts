// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NMessageProvider } from 'naive-ui'
import PlanConfirmationCard from '@/components/ai-chat/PlanConfirmationCard.vue'
import type { PlanConfirmation } from '@/components/ai-chat/types'

vi.mock('@/api/chat', () => ({
  chatApi: {
    getOverdrivePlan: vi.fn().mockResolvedValue('# 完整计划\n\n1. 核验输入\n2. 执行分析'),
  },
}))

let cleanup: (() => void) | undefined
afterEach(() => cleanup?.())
beforeEach(() => vi.clearAllMocks())

function mountCard(plan: PlanConfirmation) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const root = document.createElement('div')
  document.body.appendChild(root)
  const app = createApp({
    render: () => h(NMessageProvider, null, {
      default: () => h(PlanConfirmationCard, { plan, sessionId: 'session-1' }),
    }),
  })
  app.use(pinia)
  app.mount(root)
  cleanup = () => { app.unmount(); root.remove() }
  return root
}

const plan: PlanConfirmation = {
  runId: 'run-1',
  title: '转录组分析执行计划',
  summary: '先完成输入核验，再进入两个执行波次。',
  planPath: 'output/overdrive/session-1/run-1/plan.md',
  planVersion: 1,
  planHash: 'sha256:test',
  planningMode: 'llm',
  waveCount: 2,
  agents: [{ agentId: 'agent-data', name: '数据管家', reason: '核验输入' }],
  serialPreflight: ['检查样本表与 FASTQ 配对'],
  risks: ['分组元数据可能不完整'],
  approvalPoints: ['安装缺失的分析依赖'],
  deliverables: ['质控报告', '差异表达结果'],
  actions: ['approve', 'revise', 'cancel'],
  status: 'pending',
}

describe('PlanConfirmationCard', () => {
  it('默认加载并呈现计划全文、摘要和三个决策入口', async () => {
    const root = mountCard({ ...plan })
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()
    expect(root.textContent).toContain('转录组分析执行计划')
    expect(root.textContent).toContain('预计波次')
    expect(root.textContent).toContain('数据管家')
    expect(root.textContent).toContain('分组元数据可能不完整')
    expect(root.textContent).toContain('差异表达结果')
    expect(root.textContent).toContain('完整执行计划（请审阅后确认）')
    expect(root.textContent).toContain('核验输入')
    expect(root.textContent).toContain('在大窗口阅读完整 plan.md')
    expect(root.textContent).toContain('确认并执行')
    expect(root.textContent).toContain('提出修改')
    expect(root.textContent).toContain('取消任务')
  })

  it('提出修改后显示具有可访问名称的意见输入框', async () => {
    const root = mountCard({ ...plan })
    const revise = [...root.querySelectorAll('button')].find((button) => button.textContent?.includes('提出修改'))
    revise?.click()
    await nextTick()
    expect(root.querySelector('textarea[aria-label="计划修改意见"]')).not.toBeNull()
    expect(root.textContent).toContain('提交修改意见')
  })

  it.each([
    ['llm', 'AI 规划'],
    ['llm_repaired', 'AI 规划（已自动校正）'],
    ['rule_merge', '领域标准流程辅助'],
  ] as const)('显示 %s 对应的规划来源标记', (planningMode, label) => {
    const root = mountCard({ ...plan, planningMode })
    expect(root.textContent).toContain(label)
  })

  it('未知来源不伪装成 AI 规划', () => {
    const root = mountCard({ ...plan, planningMode: undefined })
    expect(root.textContent).not.toContain('AI 规划')
    expect(root.textContent).not.toContain('领域标准流程辅助')
  })
})
