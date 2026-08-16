/** 节日彩蛋类型定义 */

export interface PopupButton {
  text: string
  action: string
  link?: string | null
}

export interface AnimationConfig {
  enabled: boolean
  type: string
  duration: number
}

export interface PopupConfig {
  enabled: boolean
  title: string
  content: string
  description?: string
  primaryButton?: PopupButton | null
  secondaryButton?: PopupButton | null
  animation?: AnimationConfig | null
}

export interface QuotaBonusConfig {
  enabled: boolean
  amount: number
  unit: string
  description: string
}

export interface FestivalConfig {
  id: string
  name: string
  nameEn?: string | null
  description?: string
  category: string
  calendarType: string
  lunarDate?: { month: number; day: number; leap?: boolean } | null
  solarDate?: { month: number; day: number } | null
  solarTerm?: { name: string; index: number } | null
  activeRange: { year?: number | null; offsetDays: number; durationDays: number }
  popup: PopupConfig
  quotaBonus: QuotaBonusConfig
  priority: number
  enabled: boolean
}

export interface FestivalTodayResponse {
  hasFestival: boolean
  festival: FestivalConfig | null
  claimed: boolean
}

export interface FestivalClaimResponse {
  success: boolean
  amount: number
  balance: number
  message: string
}

export interface FestivalAdminListResponse {
  globalEnabled: boolean
  festivals: FestivalConfig[]
}

export interface FestivalAdminUpdateRequest {
  enabled?: boolean
  priority?: number
  popup?: Partial<PopupConfig>
  quotaBonus?: Partial<QuotaBonusConfig>
}
