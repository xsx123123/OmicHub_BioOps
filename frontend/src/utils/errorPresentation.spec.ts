import { describe, expect, it } from 'vitest'
import { presentRequestError } from './errorPresentation'

describe('presentRequestError', () => {
  it('separates business, server, and network failures', () => {
    expect(presentRequestError({ response: { status: 422, data: { detail: '输入无效' } } }, '失败')).toMatchObject({ kind: 'business', message: '输入无效', retryable: false })
    expect(presentRequestError({ response: { status: 503 } }, '失败')).toMatchObject({ kind: 'server', retryable: true })
    expect(presentRequestError(new Error('offline'), '失败')).toMatchObject({ kind: 'network', retryable: true })
  })
})
