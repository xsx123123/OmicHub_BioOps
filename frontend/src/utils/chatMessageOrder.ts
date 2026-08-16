export interface PersistedChatMessageOrderItem {
  message_id: string
  role: string
  created_at: string
}

const ROLE_ORDER: Record<string, number> = {
  user: 0,
  assistant: 1,
  tool: 2,
  system: 3,
}

/**
 * 给重开会话的历史消息提供稳定排序。
 *
 * PostgreSQL 会为同一事务中的多条记录赋予相同的 transaction timestamp；此时仅按
 * created_at 排序会让数据库返回未定义顺序。用户消息必须先于同一轮的助手回复。
 */
export function sortPersistedChatMessages<T extends PersistedChatMessageOrderItem>(messages: T[]): T[] {
  return [...messages].sort((left, right) => {
    const timeDifference = Date.parse(left.created_at) - Date.parse(right.created_at)
    if (timeDifference) return timeDifference

    const roleDifference = (ROLE_ORDER[left.role] ?? 4) - (ROLE_ORDER[right.role] ?? 4)
    if (roleDifference) return roleDifference

    return left.message_id.localeCompare(right.message_id)
  })
}
