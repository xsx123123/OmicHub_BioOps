/** 首页条幅通知类型定义（字段与后端 AnnouncementResponse 对齐，snake_case） */

export type AnnouncementType = 'info' | 'success' | 'warning' | 'feature'

export type DismissBehavior = 'daily' | 'forever' | 'none'

export interface Announcement {
  id: string
  title: string
  description: string
  type: AnnouncementType
  icon?: string | null
  link?: string | null
  button_text?: string | null
  start_time: string
  end_time?: string | null
  dismiss_behavior: DismissBehavior
  priority: number
  is_enabled: boolean
  created_at: string
  updated_at: string
}

/** 创建/更新请求体（与后端 AnnouncementCreate 对齐） */
export type AnnouncementPayload = Omit<
  Announcement,
  'id' | 'created_at' | 'updated_at'
>

/** 类型 → 默认图标映射（管理员未设 icon 时用） */
export const DEFAULT_ICON_BY_TYPE: Record<AnnouncementType, string> = {
  info: '📢',
  success: '🎉',
  warning: '⚠️',
  feature: '✨',
}
