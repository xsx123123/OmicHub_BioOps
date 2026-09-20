import { describe, expect, it } from 'vitest'
import { approvalErrorText, isApprovalGone } from '../approvalErrors'

describe('approvalErrors', () => {
  it('surfaces the server detail when present', () => {
    const error = { response: { data: { detail: '审批不存在或无权访问' } } }
    expect(approvalErrorText(error, 'fallback')).toBe('审批不存在或无权访问')
  })

  it('maps the legacy stream-inactive marker', () => {
    expect(approvalErrorText(new Error('APPROVAL_STREAM_INACTIVE'), 'fallback')).toContain('执行流已结束')
  })

  it('falls back for unknown errors', () => {
    expect(approvalErrorText(new Error('network'), '批准失败，请重试')).toBe('批准失败，请重试')
    expect(approvalErrorText(undefined, '退回失败，请重试')).toBe('退回失败，请重试')
  })

  it('flags expired/consumed approvals as gone (404/409)', () => {
    expect(isApprovalGone({ response: { status: 404 } })).toBe(true)
    expect(isApprovalGone({ response: { status: 409 } })).toBe(true)
    expect(isApprovalGone({ response: { status: 500 } })).toBe(false)
    expect(isApprovalGone(new Error('network'))).toBe(false)
  })
})
