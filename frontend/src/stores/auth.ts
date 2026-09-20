import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import type {
  User,
  TokenResponse,
  LoginResponse,
  LoginRequest,
  RegisterRequest,
  TwoFactorSetupResponse,
  TwoFactorStatusResponse,
  TwoFactorLoginRequest,
  TwoFactorCodeRequest,
} from '@/types'

// sessionStorage key：首次登录迎新标记。镜像 pendingOnboarding，
// 以便 LoginView 的 window.location.href 兜底跳转（整页刷新丢失 Pinia）后仍可恢复。
const FIRST_LOGIN_KEY = 'cygnusx_first_login'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<User | null>(null)
  const loading = ref(false)
  // 本次登录是否为首次登录（后端 TokenResponse.first_login），用于触发迎新弹窗
  const pendingOnboarding = ref<boolean>(sessionStorage.getItem(FIRST_LOGIN_KEY) === '1')

  const isLoggedIn = computed(() => accessToken.value !== null)
  // 管理员视角感知位：role 由 /auth/me 返回并随 user 持久化
  const isAdmin = computed(() => user.value?.role === 'admin')

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  function clearTokens() {
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    sessionStorage.removeItem(FIRST_LOGIN_KEY)
    pendingOnboarding.value = false
  }

  /** 标记首次登录迎新待展示（同步写入 sessionStorage 以抗整页刷新） */
  function markOnboardingPending(pending: boolean) {
    pendingOnboarding.value = pending
    if (pending) sessionStorage.setItem(FIRST_LOGIN_KEY, '1')
    else sessionStorage.removeItem(FIRST_LOGIN_KEY)
  }

  /** 消费迎新待展示标记：返回是否需要展示，并清除标记 */
  function consumeOnboarding(): boolean {
    const pending = pendingOnboarding.value || sessionStorage.getItem(FIRST_LOGIN_KEY) === '1'
    markOnboardingPending(false)
    return pending
  }

  async function login(username: string, password: string): Promise<LoginResponse> {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)

    const response = await apiClient.post<LoginResponse>('/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    const data = response.data
    if (!data.requires_2fa) {
      setTokens(data.access_token, data.refresh_token)
      markOnboardingPending(!!data.first_login)
      await fetchUser()
    }
    return data
  }

  async function complete2FALogin(challengeToken: string, code: string): Promise<TokenResponse> {
    const req: TwoFactorLoginRequest = { challenge_token: challengeToken, code }
    const response = await apiClient.post<TokenResponse>('/auth/2fa/login', req)
    const data = response.data
    setTokens(data.access_token, data.refresh_token)
    markOnboardingPending(!!data.first_login)
    await fetchUser()
    return data
  }

  async function fetch2FAStatus(): Promise<TwoFactorStatusResponse> {
    const response = await apiClient.get<TwoFactorStatusResponse>('/auth/2fa/status')
    return response.data
  }

  async function setup2FA(): Promise<TwoFactorSetupResponse> {
    const response = await apiClient.post<TwoFactorSetupResponse>('/auth/2fa/setup')
    return response.data
  }

  async function confirmEnable2FA(code: string): Promise<TwoFactorStatusResponse> {
    const req: TwoFactorCodeRequest = { code }
    const response = await apiClient.post<TwoFactorStatusResponse>('/auth/2fa/verify', req)
    return response.data
  }

  async function disable2FA(code: string): Promise<TwoFactorStatusResponse> {
    const req: TwoFactorCodeRequest = { code }
    const response = await apiClient.post<TwoFactorStatusResponse>('/auth/2fa/disable', req)
    return response.data
  }

  async function register(req: RegisterRequest): Promise<void> {
    await apiClient.post('/auth/register', req)
  }

  async function setupFirstAdmin(req: RegisterRequest): Promise<void> {
    const response = await apiClient.post<TokenResponse>('/auth/setup', req)
    setTokens(response.data.access_token, response.data.refresh_token)
    // 首位管理员也是新用户，同样展示迎新引导
    markOnboardingPending(true)
    await fetchUser()
  }

  async function checkSetupRequired(): Promise<boolean> {
    const response = await apiClient.get<{ setup_required: boolean }>('/auth/setup-required')
    return response.data.setup_required
  }

  async function fetchUser(): Promise<void> {
    if (!accessToken.value) return
    const response = await apiClient.get<User>('/auth/me')
    user.value = response.data
  }

  async function refreshAccessToken(): Promise<boolean> {
    if (!refreshToken.value) return false

    try {
      const response = await apiClient.post<TokenResponse>('/auth/refresh', {
        refresh_token: refreshToken.value,
      })
      setTokens(response.data.access_token, response.data.refresh_token)
      return true
    } catch {
      clearTokens()
      return false
    }
  }

  function logout() {
    clearTokens()
    // 确保 Pinia 中的用户状态同步清空
    user.value = null
  }

  return {
    accessToken,
    refreshToken,
    user,
    loading,
    isLoggedIn,
    isAdmin,
    pendingOnboarding,
    setTokens,
    clearTokens,
    login,
    complete2FALogin,
    fetch2FAStatus,
    setup2FA,
    confirmEnable2FA,
    disable2FA,
    register,
    setupFirstAdmin,
    checkSetupRequired,
    fetchUser,
    refreshAccessToken,
    logout,
    markOnboardingPending,
    consumeOnboarding,
  }
})
