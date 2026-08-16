// @vitest-environment jsdom
/**
 * 回归测试：任务中心整页崩溃
 *
 * 根因：「重新运行」按钮的 NTooltip 把 v-if 写在 #trigger 内部的根元素上，
 * 非终态任务（pending/queued/running）时 trigger slot 仅剩 Comment 占位节点，
 * vueuc VTarget 的 getFirstVNode('follower', $slots) flatten 后子节点数为 0，
 * 直接 throw "[vueuc/follower]: slot[default] should have exactly one child."，
 * 被 AppErrorBoundary 捕获 → 整个任务中心显示错误页。
 *
 * 修复：把 v-if 上移到 <NTooltip> 组件本身（与「查看报告」tooltip 同一模式）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h } from 'vue'
import type { App } from 'vue'
import type { Task } from '@/types'
import TaskTable from './TaskTable.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    flow_id: 'rna_seq',
    user_id: 'u1',
    username: 'tester',
    name: 'RNA-seq 演示任务',
    status: 'running',
    execution_mode: 'flow',
    parameters: {},
    work_dir: '/tmp/demo',
    result_path: '',
    error_message: '',
    progress: 0.42,
    logs: [],
    created_at: '2026-07-28T00:00:00Z',
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

const mounted: Array<{ app: App; host: HTMLElement }> = []

function mount(tasks: Task[], showUser = false) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(
    defineComponent({
      render: () => h(TaskTable, { tasks, showUser }),
    }),
  )
  const errors: unknown[] = []
  app.config.errorHandler = (err) => {
    errors.push(err)
  }
  app.config.warnHandler = () => {}
  app.mount(host)
  mounted.push({ app, host })
  return { host, errors }
}

beforeEach(() => {
  // naive-ui / vueuc 依赖但 jsdom 未实现的浏览器 API
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
  }
  if (!(globalThis as Record<string, unknown>).ResizeObserver) {
    ;(globalThis as Record<string, unknown>).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

afterEach(() => {
  for (const { app, host } of mounted.splice(0)) {
    app.unmount()
    host.remove()
  }
})

describe('TaskTable', () => {
  it('非终态任务列表可正常渲染（不触发 vueuc/follower 崩溃）', () => {
    const { host, errors } = mount([
      makeTask({ id: 't1', status: 'pending', progress: 0 }),
      makeTask({ id: 't2', status: 'queued', progress: 0 }),
      makeTask({ id: 't3', status: 'running', progress: 0.5 }),
    ])

    const followerError = errors.find(
      (e) => e instanceof Error && e.message.includes('[vueuc/follower]'),
    )
    expect(followerError).toBeUndefined()
    expect(errors).toEqual([])
    // 三行任务均渲染
    expect(host.querySelectorAll('.task-table__row')).toHaveLength(3)
    expect(host.textContent).toContain('运行中')
  })

  it('「重新运行」按钮仅在终态任务出现', () => {
    const { host: runningHost } = mount([makeTask({ status: 'running' })])
    expect(runningHost.querySelector('[aria-label="重新运行"]')).toBeNull()
    // 其余操作按钮不受影响
    expect(runningHost.querySelector('[aria-label="查看详情"]')).not.toBeNull()
    expect(runningHost.querySelector('[aria-label="删除任务"]')).not.toBeNull()

    const { host: doneHost } = mount([
      makeTask({ id: 't2', status: 'success', progress: 1 }),
    ])
    expect(doneHost.querySelector('[aria-label="重新运行"]')).not.toBeNull()
  })

  it('终态与失败任务渲染不崩溃', () => {
    const { errors } = mount([
      makeTask({ id: 't1', status: 'success', progress: 1 }),
      makeTask({ id: 't2', status: 'failed', progress: 0.7, error_message: 'boom' }),
      makeTask({ id: 't3', status: 'cancelled', progress: 0 }),
    ])
    expect(errors).toEqual([])
  })

  it('用户列优先展示昵称，空昵称回退用户名', () => {
    const { host } = mount([
      makeTask({ id: 'nickname-task', username: 'account-name', nickname: '实验室小王' }),
      makeTask({ id: 'username-task', username: 'fallback-account', nickname: '   ' }),
    ], true)

    expect(host.textContent).toContain('实验室小王')
    expect(host.textContent).toContain('fallback-account')
    expect(host.textContent).not.toContain('account-name')
  })
})
