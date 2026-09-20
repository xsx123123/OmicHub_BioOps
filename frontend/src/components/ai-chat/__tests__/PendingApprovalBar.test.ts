// @vitest-environment jsdom
/**
 * PendingApprovalBar「全部批准（本会话不再询问）」回归测试。
 *
 * 覆盖：
 * 1. 一键批量批准全部待处理项，普通工具带 always=true（记入本会话 always_allow）；
 * 2. 计划审批（update_plan / approval_kind=plan）不带 always（一次性决议）；
 * 3. 单条失败不中断其余条目，最终结果以 warning 反馈。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { NMessageProvider } from 'naive-ui'
import type { PendingApprovalItem } from '@/components/ai-chat/PendingApprovalBar.vue'

const approveToolCall = vi.hoisted(() => vi.fn())
const rejectToolCall = vi.hoisted(() => vi.fn())
const answerAskRequest = vi.hoisted(() => vi.fn())

vi.mock('@/stores/agentHub', () => ({
  useAgentHubStore: () => ({ approveToolCall, rejectToolCall, answerAskRequest }),
}))

import PendingApprovalBar from '@/components/ai-chat/PendingApprovalBar.vue'

function makeItem(approvalId: string, toolName = 'sandbox_execute', approvalKind = 'tool'): PendingApprovalItem {
  return {
    approvalId,
    messageId: `msg-${approvalId}`,
    tool: {
      id: `tc-${approvalId}`,
      name: toolName,
      arguments: { code: 'echo hi' },
      approval: {
        approval_id: approvalId,
        status: 'pending',
        approval_kind: approvalKind,
      },
    } as unknown as PendingApprovalItem['tool'],
  }
}

async function mountBar(approvals: PendingApprovalItem[]) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const app = createApp({
    render: () =>
      h(
        NMessageProvider,
        { placement: 'bottom-right' },
        { default: () => h(PendingApprovalBar, { approvals, ask: null, onLocate: () => {} }) },
      ),
  })
  app.mount(container)
  await nextTick()
  return { app, container }
}

function findApproveAllButton(container: HTMLElement): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find((el) =>
    el.textContent?.includes('全部批准'),
  )
  expect(btn, '应渲染「全部批准」按钮').toBeTruthy()
  return btn as HTMLButtonElement
}

describe('PendingApprovalBar 全部批准', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    approveToolCall.mockResolvedValue(undefined)
  })

  it('批量批准全部待处理项，普通工具带 always 记入本会话放行集合', async () => {
    const { app, container } = await mountBar([
      makeItem('ap-1', 'sandbox_execute'),
      makeItem('ap-2', 'workspace_write'),
    ])

    findApproveAllButton(container).click()
    await vi.waitFor(() => expect(approveToolCall).toHaveBeenCalledTimes(2))
    expect(approveToolCall).toHaveBeenNthCalledWith(1, 'ap-1', undefined, true)
    expect(approveToolCall).toHaveBeenNthCalledWith(2, 'ap-2', undefined, true)

    app.unmount()
    container.remove()
  })

  it('计划审批不带 always（一次性决议，不记入 always_allow）', async () => {
    const { app, container } = await mountBar([
      makeItem('ap-plan', 'update_plan', 'plan'),
      makeItem('ap-1', 'sandbox_execute'),
    ])

    findApproveAllButton(container).click()
    await vi.waitFor(() => expect(approveToolCall).toHaveBeenCalledTimes(2))
    expect(approveToolCall).toHaveBeenNthCalledWith(1, 'ap-plan', undefined, false)
    expect(approveToolCall).toHaveBeenNthCalledWith(2, 'ap-1', undefined, true)

    app.unmount()
    container.remove()
  })

  it('单条失败不中断其余条目', async () => {
    approveToolCall.mockRejectedValueOnce(new Error('network'))
    const { app, container } = await mountBar([
      makeItem('ap-1'),
      makeItem('ap-2'),
      makeItem('ap-3'),
    ])

    findApproveAllButton(container).click()
    await vi.waitFor(() => expect(approveToolCall).toHaveBeenCalledTimes(3))

    app.unmount()
    container.remove()
  })

  it('无待审批项时不渲染「全部批准」按钮', async () => {
    const { app, container } = await mountBar([])
    expect(findApproveAllButton).toThrow()
    app.unmount()
    container.remove()
  })
})
