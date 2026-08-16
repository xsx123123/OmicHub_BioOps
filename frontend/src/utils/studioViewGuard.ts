/**
 * Studio 工作台视图状态守卫（问题⑦防回归）
 *
 * 根因：refreshStatus() 10 秒轮询无条件用服务端 ui.view_mode 覆盖本地，
 * 而流式期间 PATCH /ui 会被聊天事务行锁阻塞，GET 拿到的是旧值，
 * 用户手动打开的分屏/代码面板最多 10 秒内被打回 chat。
 *
 * 策略：用户手动操作优先——流式期间一律不应用服务端 UI 状态；
 * 用户手动切换视图后，会话内不再接受服务端 view_mode 回写。
 */

export type StudioViewMode = 'chat' | 'split' | 'code'

/** 服务端 UI 状态（follow_ai / terminal_collapsed / split_ratio 等）是否允许覆盖本地 */
export function shouldApplyServerUi(isStreaming: boolean): boolean {
  return !isStreaming
}

/** 服务端 view_mode 是否允许覆盖本地视图模式 */
export function shouldApplyServerViewMode(
  isStreaming: boolean,
  viewModeTouched: boolean,
  serverMode: unknown,
): serverMode is StudioViewMode {
  return (
    !isStreaming
    && !viewModeTouched
    && (serverMode === 'chat' || serverMode === 'split' || serverMode === 'code')
  )
}
