import { describe, expect, it, vi } from 'vitest'
import { createTokenRefreshCoordinator } from './authRefresh'

describe('createTokenRefreshCoordinator', () => {
  it('shares one refresh request across concurrent 401 recoveries', async () => {
    let resolveRefresh: ((tokens: { accessToken: string; refreshToken: string }) => void) | undefined
    const refresh = vi.fn(() => new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
      resolveRefresh = resolve
    }))
    const persist = vi.fn()
    const coordinator = createTokenRefreshCoordinator({ refresh, persist })

    const first = coordinator.refreshAccessToken()
    const second = coordinator.refreshAccessToken()

    expect(refresh).toHaveBeenCalledTimes(1)
    resolveRefresh?.({ accessToken: 'new-access', refreshToken: 'new-refresh' })

    await expect(first).resolves.toBe('new-access')
    await expect(second).resolves.toBe('new-access')
    expect(persist).toHaveBeenCalledTimes(1)
    expect(persist).toHaveBeenCalledWith({ accessToken: 'new-access', refreshToken: 'new-refresh' })
  })

  it('allows a later retry when the previous refresh fails', async () => {
    const refresh = vi
      .fn<() => Promise<{ accessToken: string; refreshToken: string }>>()
      .mockRejectedValueOnce(new Error('expired'))
      .mockResolvedValueOnce({ accessToken: 'new-access', refreshToken: 'new-refresh' })
    const persist = vi.fn()
    const coordinator = createTokenRefreshCoordinator({ refresh, persist })

    await expect(coordinator.refreshAccessToken()).resolves.toBeNull()
    await expect(coordinator.refreshAccessToken()).resolves.toBe('new-access')

    expect(refresh).toHaveBeenCalledTimes(2)
    expect(persist).toHaveBeenCalledTimes(1)
  })

  it('classifies server failures without treating them as logout', async () => {
    const refresh = vi.fn().mockRejectedValue({ response: { status: 503 } })
    const coordinator = createTokenRefreshCoordinator({ refresh, persist: vi.fn() })

    await expect(coordinator.refreshAccessToken()).resolves.toBeNull()
    expect(coordinator.getLastFailureKind()).toBe('server')
  })
})
