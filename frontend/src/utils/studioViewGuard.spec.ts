/**
 * 回归测试：流式期间用户手动打开的分屏/代码面板不得被服务端轮询打回（问题⑦）
 *
 * 场景还原：
 * 1. 用户在 AI 流式回复期间手动切到「分屏」→ viewModeTouched = true；
 * 2. PATCH /ui 因聊天事务行锁阻塞，服务端保存的仍是旧值 'chat'；
 * 3. 10 秒轮询 refreshStatus() 拿到旧值——修复前会无条件覆盖本地 viewMode，
 *    代码面板被自动关闭；修复后 shouldApplyServerViewMode 必须拒绝。
 */
import { describe, expect, it } from 'vitest'
import { shouldApplyServerUi, shouldApplyServerViewMode } from './studioViewGuard'

describe('studioViewGuard', () => {
  it('流式期间：服务端旧值不得覆盖用户手动打开的分屏视图', () => {
    // 用户流式中手动切到 split，服务端仍是旧的 chat
    expect(shouldApplyServerViewMode(true, true, 'chat')).toBe(false)
    // 即使用户尚未手动切换，流式中也不应用服务端任何 UI 状态
    expect(shouldApplyServerViewMode(true, false, 'chat')).toBe(false)
    expect(shouldApplyServerUi(true)).toBe(false)
  })

  it('用户手动接管视图后：流结束也不接受服务端回写（会话内粘性）', () => {
    expect(shouldApplyServerViewMode(false, true, 'chat')).toBe(false)
    expect(shouldApplyServerViewMode(false, true, 'split')).toBe(false)
  })

  it('新会话且未手动切换：正常同步服务端视图状态', () => {
    expect(shouldApplyServerViewMode(false, false, 'split')).toBe(true)
    expect(shouldApplyServerViewMode(false, false, 'code')).toBe(true)
    expect(shouldApplyServerViewMode(false, false, 'chat')).toBe(true)
    expect(shouldApplyServerUi(false)).toBe(true)
  })

  it('非法 view_mode 值一律忽略', () => {
    expect(shouldApplyServerViewMode(false, false, 'fullscreen')).toBe(false)
    expect(shouldApplyServerViewMode(false, false, undefined)).toBe(false)
    expect(shouldApplyServerViewMode(false, false, null)).toBe(false)
  })
})
