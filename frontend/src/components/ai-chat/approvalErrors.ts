/**
 * Studio HITL 审批 API 错误的统一解读。
 * 后端语义：404 = 审批记录不存在（Redis TTL 300s 过期或执行流已结束清理），
 * 409 = 决议已被消费（重复提交/他处已处理）。
 * 这两种情况下卡片应转入终态（已超时）而不是永远留在"待你处理"列表。
 */

/** 提取审批 API 错误的用户可读文案（优先服务端 detail） */
export function approvalErrorText(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (error instanceof Error && error.message === 'APPROVAL_STREAM_INACTIVE') {
    return '该审批所属执行流已结束，请重新发送任务后再操作'
  }
  return fallback
}

/** 审批记录是否已消失/被消费（404 过期、409 已消费）——调用方据此转入终态 */
export function isApprovalGone(error: unknown): boolean {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 404 || status === 409
}
