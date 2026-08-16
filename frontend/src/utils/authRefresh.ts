export interface RefreshedTokens {
  accessToken: string
  refreshToken: string
}

export interface TokenRefreshCoordinatorOptions {
  refresh: () => Promise<RefreshedTokens>
  persist: (tokens: RefreshedTokens) => void
}

/**
 * 将并发出现的 401 合并为一次刷新请求，避免第二个请求误判为登录失效。
 */
export function createTokenRefreshCoordinator({
  refresh,
  persist,
}: TokenRefreshCoordinatorOptions) {
  let inFlight: Promise<string | null> | null = null

  async function refreshAccessToken(): Promise<string | null> {
    if (!inFlight) {
      inFlight = refresh()
        .then((tokens) => {
          persist(tokens)
          return tokens.accessToken
        })
        .catch(() => null)
        .finally(() => {
          inFlight = null
        })
    }
    return inFlight
  }

  return { refreshAccessToken }
}
