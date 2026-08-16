/**
 * 用户展示名统一工具。
 *
 * 全平台「需要显示用户名称」的位置一律走这里：优先昵称（nickname），
 * 空则降级为用户名（username），再空则空串。后端 UserResponse 已返回 nickname
 * （nickname 可空），管理员用户列表 / 存储监控等 DTO 也已对齐。
 *
 * 用法：displayName(user) 或 displayName({ nickname, username })
 */
export interface DisplayNameSource {
  nickname?: string | null
  username?: string | null
}

export function displayName(user: DisplayNameSource | null | undefined): string {
  if (!user) return ''
  return (user.nickname && user.nickname.trim()) || user.username || ''
}
