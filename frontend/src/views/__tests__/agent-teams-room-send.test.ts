// @vitest-environment jsdom
/**
 * 协作室房间（已有 Case）内发送消息回归测试（jsdom 真实挂载）
 *
 * 背景 bug：P3 输入区改造后，进入一个 planning_running 状态的 Case，
 * 输入文本（可带 @ 工作区文件引用）按 Enter / 点发送均无法发出消息。
 * 这里挂载真实 AgentTeamsRoomView + KimiChatInput，mock API 层，
 * 驱动「选中 Case → 输入 → 发送」全流程，覆盖：
 * 1. planning_running（规划中）状态下输入框可用且 Enter 发送成功；
 * 2. @ 工作区文件引用 chip 正确映射为 context_refs；
 * 3. 发送失败时恢复草稿，不丢用户已输入内容。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { NDialogProvider, NMessageProvider } from 'naive-ui'
import type { AgentTeamsCase, AgentTeamsRoom } from '@/api/agentTeams'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))
const apiClientMocks = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: {} }),
  post: vi.fn().mockResolvedValue({ data: {} }),
}))
vi.mock('@/api/client', () => ({ default: apiClientMocks }))

const agentTeamsApiMocks = vi.hoisted(() => ({
  status: vi.fn(),
  listCases: vi.fn(),
  getCase: vi.fn(),
  getEvents: vi.fn(),
  postCaseMessage: vi.fn(),
  createCase: vi.fn(),
  submitCase: vi.fn(),
  rejectCase: vi.fn(),
  revisePlan: vi.fn(),
  retryCase: vi.fn(),
  cancelCase: vi.fn(),
  deleteCase: vi.fn(),
  getRoleLabels: vi.fn().mockResolvedValue({}),
  getManifest: vi.fn(),
  // 会话-工单解耦：房间端点；本测试聚焦旧 Case 房间路径，默认无房间
  // 注意必须每次返回新对象：组件会把 items 数组直接挂到本地状态并 push 新房间，
  // 共享同一个对象会把房间泄漏到后续用例
  listRooms: vi.fn().mockImplementation(async () => ({ items: [], total: 0 })),
  createRoom: vi.fn(),
  getRoom: vi.fn(),
  postRoomMessage: vi.fn(),
  confirmRoomProposal: vi.fn(),
  getRoomEvents: vi.fn(),
}))
vi.mock('@/api/agentTeams', () => ({ agentTeamsApi: agentTeamsApiMocks }))

import AgentTeamsRoomView from '@/views/AgentTeamsRoomView.vue'

const planningCase: AgentTeamsCase = {
  case_id: 'case-1',
  intent: '做一个系统发育树',
  display_title: '系统发育树',
  status: 'planning_running',
  created_at: '2026-08-13T10:00:00Z',
  updated_at: '2026-08-13T10:00:00Z',
} as AgentTeamsCase

const treefile = {
  id: '74a2448c-593a-4c9c-aa19-bb2214339c54',
  original_name: '74a2448c593a4c9caa19bb2214339c54.treefile',
  path: 'workspace/chat-uploads/74a2448c593a4c9caa19bb2214339c54.treefile',
  directory: 'workspace/chat-uploads',
  size: 2048,
  file_type: 'treefile',
}

function mountView() {
  setActivePinia(createPinia())
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render() {
      return h(NMessageProvider, null, {
        default: () =>
          h(NDialogProvider, null, {
            default: () => h(AgentTeamsRoomView),
          }),
      })
    },
  })
  app.mount(el)
  return { el, app }
}

async function flush(times = 10) {
  for (let index = 0; index < times; index += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

async function mountAndSelectCase() {
  const { el, app } = mountView()
  await flush()
  const entry = el.querySelector<HTMLButtonElement>('.case-entry')
  expect(entry).toBeTruthy()
  entry!.click()
  await flush()
  const textarea = el.querySelector<HTMLTextAreaElement>('.ai-composer-shell textarea')
  expect(textarea).toBeTruthy()
  return { el, app, textarea: textarea! }
}

function typeText(textarea: HTMLTextAreaElement, text: string) {
  textarea.value = text
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('协作室房间（已有 Case）发送消息', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    agentTeamsApiMocks.status.mockResolvedValue({ available: true })
    agentTeamsApiMocks.listCases.mockResolvedValue({ items: [planningCase] })
    agentTeamsApiMocks.getCase.mockResolvedValue(planningCase)
    agentTeamsApiMocks.getEvents.mockResolvedValue({ events: [], next_cursor: null })
    agentTeamsApiMocks.postCaseMessage.mockResolvedValue({ event_id: 'evt-user-1' })
    apiClientMocks.get.mockResolvedValue({ data: { items: [treefile], directories: [], total: 1 } })
    // SSE 事件流在 jsdom 下直接失败，组件会降级为轮询；避免真实 fetch
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no sse in jsdom')))
    // jsdom 无 matchMedia / 元素 scrollTo，补空实现
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia
    HTMLElement.prototype.scrollTo = (() => undefined) as typeof HTMLElement.prototype.scrollTo
  })

  it('planning_running（规划中）状态下输入框可用，Enter 发送成功', async () => {
    const { app, textarea } = await mountAndSelectCase()
    // 可发言条件未被收紧：规划中状态输入框不禁用
    expect(textarea.disabled).toBe(false)
    expect(textarea.placeholder).toContain('发送到协作房间')

    typeText(textarea, '帮我做一下系统发育树呀')
    await nextTick()
    const sendBtn = document.querySelector<HTMLButtonElement>('.send-btn')
    expect(sendBtn?.disabled).toBe(false)
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await nextTick()

    expect(document.body.textContent).toContain('帮我做一下系统发育树呀')
    await flush()

    expect(agentTeamsApiMocks.postCaseMessage).toHaveBeenCalledTimes(1)
    expect(agentTeamsApiMocks.postCaseMessage).toHaveBeenCalledWith('case-1', '帮我做一下系统发育树呀', [])
    expect(document.body.textContent?.match(/帮我做一下系统发育树呀/g)).toHaveLength(1)
    app.unmount()
  })

  it('列表与页头使用短标题，不直接展示完整首句', async () => {
    const fullIntent = '请帮我分析这个项目中的全部转录组样本并生成差异表达与富集分析报告'
    const titledCase = { ...planningCase, intent: fullIntent, display_title: '转录组差异与富集分析' }
    agentTeamsApiMocks.listCases.mockResolvedValue({ items: [titledCase] })
    agentTeamsApiMocks.getCase.mockResolvedValue(titledCase)

    const { el, app } = await mountAndSelectCase()

    expect(el.querySelector('.case-entry__intent')?.textContent).toBe('转录组差异与富集分析')
    expect(el.querySelector('.case-entry__intent')?.getAttribute('title')).toBe(fullIntent)
    expect(el.querySelector('.case-header__title')?.textContent).toBe('转录组差异与富集分析')
    app.unmount()
  })

  it('协作室标题栏提供全局设置入口', async () => {
    const { el, app } = mountView()
    await flush()

    const settingsButton = el.querySelector<HTMLButtonElement>('[aria-label="团队协作室设置"]')
    expect(settingsButton).toBeTruthy()
    settingsButton!.click()
    await flush()

    expect(document.body.textContent).toContain('团队协作室设置')
    expect(document.body.textContent).toContain('Manager 回复偏好')
    expect(document.body.textContent).toContain('协作室行为')
    app.unmount()
  })

  it('点击发送按钮发送，@ 工作区文件引用映射为 context_refs', async () => {
    const { el, app, textarea } = await mountAndSelectCase()
    // 模拟输入 @ 触发 mention 面板并用 Enter 选中文件
    typeText(textarea, '@workspace')
    await flush()
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    expect(textarea.value).toContain('@workspace/chat-uploads/74a2448c593a4c9caa19bb2214339c54.treefile')
    // 继续输入正文（含 chip 的消息）
    typeText(textarea, `${textarea.value} 帮我做一下系统发育树呀`)
    await flush()
    const sendBtn = el.querySelector<HTMLButtonElement>('.send-btn')
    expect(sendBtn?.disabled).toBe(false)
    sendBtn!.click()
    await flush()

    expect(agentTeamsApiMocks.postCaseMessage).toHaveBeenCalledTimes(1)
    const [, content, refs] = agentTeamsApiMocks.postCaseMessage.mock.calls[0]
    expect(content).toContain('帮我做一下系统发育树呀')
    expect(refs).toEqual([{
      kind: 'file',
      id: '74a2448c-593a-4c9c-aa19-bb2214339c54',
      location: 'workspace/chat-uploads/74a2448c593a4c9caa19bb2214339c54.treefile',
    }])
    app.unmount()
  })

  it('发送失败后恢复草稿，不丢失用户已输入内容', async () => {
    agentTeamsApiMocks.postCaseMessage.mockRejectedValueOnce({ response: { data: { detail: '桥接不可用' } } })
    const { app, textarea } = await mountAndSelectCase()
    typeText(textarea, '帮我做一下系统发育树呀')
    await nextTick()
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()

    expect(agentTeamsApiMocks.postCaseMessage).toHaveBeenCalledTimes(1)
    // 失败后草稿恢复，发送按钮复位可用
    expect(textarea.value).toBe('帮我做一下系统发育树呀')
    expect(document.querySelector<HTMLButtonElement>('.send-btn')?.disabled).toBe(false)
    app.unmount()
  })

  it('旧 Case 目标不相关时，带 treefile 的绘树请求自动创建独立 Case', async () => {
    const unrelatedCase = { ...planningCase, intent: '介绍一下 Manager 能做什么' }
    const createdCase = { ...planningCase, case_id: 'case-tree', intent: '帮我做一下系统发育树' }
    agentTeamsApiMocks.listCases
      .mockResolvedValueOnce({ items: [unrelatedCase] })
      .mockResolvedValueOnce({ items: [createdCase, unrelatedCase] })
    agentTeamsApiMocks.getCase.mockImplementation(async (caseId: string) =>
      caseId === 'case-tree' ? createdCase : unrelatedCase,
    )
    agentTeamsApiMocks.createCase.mockResolvedValue(createdCase)

    const { el, app, textarea } = await mountAndSelectCase()
    typeText(textarea, '@workspace')
    await flush()
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush()
    typeText(textarea, `${textarea.value} 帮我做一下系统发育树呀`)
    await flush()
    el.querySelector<HTMLButtonElement>('.send-btn')!.click()
    await flush(20)

    expect(agentTeamsApiMocks.createCase).toHaveBeenCalledWith(expect.objectContaining({
      intent: expect.stringContaining('系统发育树'),
      context_refs: [{
        kind: 'file',
        id: '74a2448c-593a-4c9c-aa19-bb2214339c54',
        location: 'workspace/chat-uploads/74a2448c593a4c9caa19bb2214339c54.treefile',
      }],
    }))
    expect(agentTeamsApiMocks.postCaseMessage).toHaveBeenCalledWith(
      'case-tree',
      expect.stringContaining('系统发育树'),
      expect.any(Array),
    )
    expect(agentTeamsApiMocks.postCaseMessage).not.toHaveBeenCalledWith(
      'case-1',
      expect.anything(),
      expect.anything(),
    )
    app.unmount()
  })

  it('空态直接发消息：先建轻量房间（不建 Case），首条消息落房间事件流', async () => {
    const room: AgentTeamsRoom = {
      room_id: 'room-1',
      title: '创建一个数据质控团队',
      status: 'active',
      origin: 'manual',
      case_id: null,
      matrix_room_provisioned: false,
      has_pending_proposal: false,
      created_at: '2026-08-13T10:00:00Z',
      updated_at: '2026-08-13T10:00:00Z',
    }
    // mockReset 清掉前序用例遗留的 mockResolvedValueOnce 队列，避免污染本用例的空态前置
    agentTeamsApiMocks.listCases.mockReset()
    agentTeamsApiMocks.listCases.mockResolvedValue({ items: [] })
    agentTeamsApiMocks.createRoom.mockResolvedValue(room)
    agentTeamsApiMocks.getRoom.mockResolvedValue(room)
    agentTeamsApiMocks.getRoomEvents.mockResolvedValue({ events: [], next_cursor: null })
    agentTeamsApiMocks.postRoomMessage.mockResolvedValue({ event_id: 'evt-user-1' })

    const { el, app } = mountView()
    await flush()
    const textarea = el.querySelector<HTMLTextAreaElement>('.ai-composer-shell textarea')!
    typeText(textarea, '创建一个数据质控团队')
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush(20)

    // 会话-工单解耦：空态首条消息走 POST /rooms 建房 + /rooms/{id}/messages 发言，
    // 不再隐式建 Case——立项由后续 room.proposal_confirm 卡片确认触发
    expect(agentTeamsApiMocks.createRoom).toHaveBeenCalledTimes(1)
    expect(agentTeamsApiMocks.createRoom).toHaveBeenCalledWith(expect.objectContaining({
      title: '创建一个数据质控团队',
      origin: 'manual',
    }))
    expect(agentTeamsApiMocks.createCase).not.toHaveBeenCalled()
    expect(agentTeamsApiMocks.postRoomMessage).toHaveBeenCalledWith(
      'room-1',
      '创建一个数据质控团队',
      [],
      expect.any(String),
    )
    expect(agentTeamsApiMocks.postCaseMessage).not.toHaveBeenCalled()

    // 用户消息乐观上屏；未立项房间显示轻量会话头（无五步进度条、无 onboarding）
    expect(el.querySelector('.room-stream')?.textContent).toContain('创建一个数据质控团队')
    expect(el.querySelector('.case-header__room-hint')?.textContent).toContain('尚未立项')
    expect(el.querySelector('.case-stage')).toBeNull()
    expect(el.querySelector('.onboarding')).toBeNull()
    app.unmount()
  })

  it('建房失败回退旧建 Case 路径：onboarding 显示在消息流顶部，稍后再说后不保留总结气泡', async () => {
    const createdCase = { ...planningCase, case_id: 'case-new', intent: '创建一个数据质控团队', display_title: '数据质控团队' }
    agentTeamsApiMocks.listCases.mockResolvedValueOnce({ items: [] }).mockResolvedValueOnce({ items: [createdCase] })
    agentTeamsApiMocks.createRoom.mockRejectedValueOnce({ response: { data: { detail: '房间服务不可用' } } })
    agentTeamsApiMocks.createCase.mockResolvedValue(createdCase)
    agentTeamsApiMocks.getCase.mockResolvedValue(createdCase)

    const { el, app } = mountView()
    await flush()
    const textarea = el.querySelector<HTMLTextAreaElement>('.ai-composer-shell textarea')!
    typeText(textarea, '创建一个数据质控团队')
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flush(20)

    // 建房接口不可用时回退旧的聊天式建 Case，保留 onboarding 引导
    expect(agentTeamsApiMocks.createCase).toHaveBeenCalledTimes(1)
    const stream = el.querySelector('.room-stream')!
    expect(stream.firstElementChild?.classList.contains('onboarding')).toBe(true)
    expect(stream.textContent).toContain('先认识一下')
    expect(stream.textContent).not.toContain('记下了：称呼')

    const onboardingButtons = el.querySelectorAll<HTMLButtonElement>('.onboarding__skip')
    onboardingButtons[onboardingButtons.length - 1].click()
    await flush()
    expect(el.querySelector('.onboarding')).toBeNull()
    expect(stream.textContent).not.toContain('记下了：称呼')
    app.unmount()
  })

  it('房间列表项可删除：确认后调用删除接口并移出列表', async () => {
    agentTeamsApiMocks.deleteCase.mockResolvedValue({ deleted: true })
    const { el, app } = mountView()
    await flush()

    const deleteTrigger = el.querySelector<HTMLElement>('.case-entry__delete')
    expect(deleteTrigger).toBeTruthy()
    deleteTrigger!.click()
    await flush()

    const confirmPanel = document.querySelector('.n-popconfirm')
    expect(confirmPanel?.textContent).toContain('删除该协作房间？')
    const confirmButton = Array.from(
      confirmPanel!.querySelectorAll<HTMLButtonElement>('.n-popconfirm__action .n-button'),
    ).find((button) => button.textContent?.trim() === '删除')
    expect(confirmButton).toBeTruthy()
    confirmButton!.click()
    await flush()

    expect(agentTeamsApiMocks.deleteCase).toHaveBeenCalledTimes(1)
    expect(agentTeamsApiMocks.deleteCase).toHaveBeenCalledWith('case-1')
    expect(el.querySelector('.case-entry')).toBeNull()
    expect(el.textContent).toContain('还没有协作房间')
    app.unmount()
  })
})
