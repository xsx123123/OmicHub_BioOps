import type { AxiosError } from 'axios'

export type RequestErrorKind = 'unauthorized' | 'business' | 'server' | 'network'

export interface RequestErrorPresentation {
  kind: RequestErrorKind
  message: string
  retryable: boolean
}

export function presentRequestError(error: unknown, fallback: string): RequestErrorPresentation {
  const axiosError = error as AxiosError<{ detail?: unknown; message?: unknown }>
  const status = axiosError.response?.status
  const detail = axiosError.response?.data?.detail
  const serverMessage = typeof detail === 'string'
    ? detail
    : typeof axiosError.response?.data?.message === 'string'
      ? axiosError.response.data.message
      : null

  if (status === 401) {
    return { kind: 'unauthorized', message: '登录状态已失效，请重新登录。', retryable: false }
  }
  if (typeof status === 'number' && status >= 400 && status < 500) {
    return { kind: 'business', message: serverMessage || fallback, retryable: false }
  }
  if (typeof status === 'number' && status >= 500) {
    return { kind: 'server', message: '服务暂时不可用，请稍后重试。', retryable: true }
  }
  return { kind: 'network', message: '网络连接异常，请检查网络后重试。', retryable: true }
}
