import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig } from 'axios'
import { createDiscreteApi } from 'naive-ui'
import { createTokenRefreshCoordinator } from '@/utils/authRefresh'

const apiClient: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 文件级单例：MODULE_LOCKED 拦截弹窗用（脱离组件树，拦截器内无法 useDialog）
const { dialog: moduleLockedDialog } = createDiscreteApi(['dialog'])

/**
 * 模块未开通（403 + MODULE_LOCKED）：会话级去重弹一次提示，不当普通错误 toast。
 * 与占位页首弹共用 sessionStorage「module_locked_seen_」去重规则。
 */
async function notifyModuleLocked(url?: string): Promise<void> {
  // 未登录（登录页等场景）不弹
  if (!localStorage.getItem('access_token')) return
  try {
    // 动态引入避免与 stores/modules 产生静态循环依赖（modules store 依赖本模块）
    const [{ useModulesStore }, { consumeModuleLockedNotice }] = await Promise.all([
      import('@/stores/modules'),
      import('@/utils/moduleGuard'),
    ])
    const modulesStore = useModulesStore()
    const mod = url ? modulesStore.moduleForApiUrl(url) : null
    const key = mod?.key ?? 'unknown'
    if (!consumeModuleLockedNotice(key)) return
    moduleLockedDialog.warning({
      title: '模块未开通',
      content: `您暂无「${mod?.name ?? '该模块'}」模块的使用权限，请联系管理员解锁后使用。`,
      positiveText: '我知道了',
    })
  } catch {
    // 弹窗失败不影响原始错误流转
  }
}

// 请求拦截器 - 附加 JWT Token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

const tokenRefreshCoordinator = createTokenRefreshCoordinator({
  refresh: async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) throw new Error('缺少刷新令牌')
    const response = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
    return {
      accessToken: response.data.access_token,
      refreshToken: response.data.refresh_token,
    }
  },
  persist: ({ accessToken, refreshToken }) => {
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('refresh_token', refreshToken)
  },
})

function clearAuthAndRedirectToLogin() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  if (window.location.pathname !== '/login') {
    const redirect = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.href = `/login?redirect=${redirect}`
  }
}

// 响应拦截器 - 统一错误处理 + 自动刷新令牌
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // 401 且未重试过 → 尝试刷新令牌
    if (error.response?.status === 401 && !originalRequest._retry) {
      // 登录/注册/刷新接口本身返回 401 → 不刷新，直接跳登录
      if (originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/register')) {
        return Promise.reject(error)
      }

      originalRequest._retry = true

      if (!localStorage.getItem('refresh_token')) {
        clearAuthAndRedirectToLogin()
        return Promise.reject(error)
      }

      const accessToken = await tokenRefreshCoordinator.refreshAccessToken()
      if (!accessToken) {
        if (tokenRefreshCoordinator.getLastFailureKind() === 'unauthorized') {
          clearAuthAndRedirectToLogin()
        }
        return Promise.reject(error)
      }

      // 重放原始请求
      originalRequest.headers.Authorization = `Bearer ${accessToken}`
      return apiClient(originalRequest)
    }

    // 模块未开通：统一占位/弹窗逻辑（会话级去重），随后照常 reject 让调用方拿到错误
    if (error.response?.status === 403 && error.response?.data?.code === 'MODULE_LOCKED') {
      void notifyModuleLocked(originalRequest?.url)
      return Promise.reject(error)
    }

    return Promise.reject(error)
  },
)

export default apiClient
