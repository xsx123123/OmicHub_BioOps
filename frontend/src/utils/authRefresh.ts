export interface RefreshedTokens {
  accessToken: string
  refreshToken: string
}

export interface TokenRefreshCoordinatorOptions {
  refresh: () => Promise<RefreshedTokens>
  persist: (tokens: RefreshedTokens) => void
}

export type RefreshFailureKind = 'unauthorized' | 'server' | 'network' | null

/**
 * 将并发出现的 401 合并为一次刷新请求，避免第二个请求误判为登录失效。
 */
export function createTokenRefreshCoordinator({
  refresh,
  persist,
}: TokenRefreshCoordinatorOptions) {
  let inFlight: Promise<string | null> | null = null
  let lastFailureKind: RefreshFailureKind = null

  async function refreshAccessToken(): Promise<string | null> {
    if (!inFlight) {
      inFlight = refresh()
        .then((tokens) => {
          lastFailureKind = null
          persist(tokens)
          return tokens.accessToken
        })
        .catch((error: { response?: { status?: number } }) => {
          const status = error?.response?.status
          lastFailureKind = status === 401
            ? 'unauthorized'
            : status !== undefined && status >= 500
              ? 'server'
              : 'network'
          return null
        })
        .finally(() => {
          inFlight = null
        })
    }
    return inFlight
  }

  return {
    refreshAccessToken,
    getLastFailureKind: () => lastFailureKind,
  }
}
