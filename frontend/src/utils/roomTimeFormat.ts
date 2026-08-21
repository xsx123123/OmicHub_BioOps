/**
 * 协作室（AgentTeams）统一时间格式化（§3.5，全页单一事实源）。
 *
 * 规则：
 * - 当天：HH:mm
 * - 当年：MM/DD HH:mm
 * - 跨年：YYYY/MM/DD
 * - hover 完整时间：YYYY年M月D日 HH:mm:ss
 * - 左栏列表保留 IM 惯例相对时间（"2 天前"），由 formatRoomRelativeTime 承载
 *
 * 项目未安装 dayjs，沿用既有 date-fns + zhCN 方案（与 ProfileView / MemoryView 同约定）。
 * 头部元信息、消息时间戳、左栏列表三处一律消费本模块，禁止另起格式化逻辑。
 */
import { format, formatDistanceToNow, isToday, isThisYear, parseISO } from 'date-fns'
import { zhCN } from 'date-fns/locale'

/** 解析 ISO 时间串；空值 / 非法输入返回 null，调用方据此不渲染。 */
function parseRoomTime(raw?: string | null): Date | null {
  if (!raw) return null
  const date = parseISO(raw)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 统一三档：当天 HH:mm / 当年 MM/dd HH:mm / 跨年 yyyy/MM/dd。 */
export function formatRoomTime(raw?: string | null): string {
  const date = parseRoomTime(raw)
  if (!date) return ''
  if (isToday(date)) return format(date, 'HH:mm')
  if (isThisYear(date)) return format(date, 'MM/dd HH:mm')
  return format(date, 'yyyy/MM/dd')
}

/** hover 完整时间：yyyy年M月d日 HH:mm:ss。 */
export function formatRoomFullTime(raw?: string | null): string {
  const date = parseRoomTime(raw)
  return date ? format(date, 'yyyy年M月d日 HH:mm:ss') : ''
}

/** 左栏相对时间（IM 惯例保留）；未来时间（时钟漂移）与非法输入返回空串。 */
export function formatRoomRelativeTime(raw?: string | null): string {
  const date = parseRoomTime(raw)
  if (!date || date.getTime() > Date.now()) return ''
  return formatDistanceToNow(date, { locale: zhCN, addSuffix: true })
}
