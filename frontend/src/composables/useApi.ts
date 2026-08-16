import { ref, type Ref } from 'vue'
import { useMessage } from 'naive-ui'

export interface UseApiOptions {
  /** 请求出错时是否自动 toast（默认 true） */
  autoToast?: boolean
  /** 自定义错误提示文案 */
  errorMessage?: string
  /** 初始数据 */
  initialData?: any
}

export interface UseApiReturn<T> {
  data: Ref<T | undefined>
  loading: Ref<boolean>
  error: Ref<string>
  execute: () => Promise<T | undefined>
  reset: () => void
}

/**
 * 统一 API 请求组合式函数
 *
 * 封装请求生命周期：loading / error / data，自动 toast 错误，
 * 让页面组件从繁琐的 try/catch/finally 中解放出来。
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  options: UseApiOptions = {},
): UseApiReturn<T> {
  const { autoToast = true, errorMessage, initialData } = options

  const data = ref<T | undefined>(initialData) as Ref<T | undefined>
  const loading = ref(false)
  const error = ref('')
  let messageApi: ReturnType<typeof useMessage> | null = null

  // useMessage 必须在 setup 中调用；这里延迟初始化，若不在 setup 调用则静默失败
  try {
    messageApi = useMessage()
  } catch {
    messageApi = null
  }

  async function execute(): Promise<T | undefined> {
    loading.value = true
    error.value = ''
    try {
      const result = await fetcher()
      data.value = result
      return result
    } catch (e: any) {
      const msg =
        errorMessage ||
        e?.response?.data?.detail ||
        e?.message ||
        '请求失败，请稍后重试'
      error.value = msg
      if (autoToast && messageApi) {
        messageApi.error(msg)
      }
      return undefined
    } finally {
      loading.value = false
    }
  }

  function reset() {
    data.value = initialData
    error.value = ''
    loading.value = false
  }

  return {
    data,
    loading,
    error,
    execute,
    reset,
  }
}
