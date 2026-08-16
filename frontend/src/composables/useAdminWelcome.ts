/**
 * useAdminWelcome —— 管理员登录欢迎小彩蛋
 *
 * 触发条件：role === 'admin' 的用户进入仪表板后，后台异步拉取一段带颜文字的
 *           欢迎词，并以 Naive UI Notification 在右上角弹出。
 * 优雅降级：LLM 接口 3s 超时或任意异常时，静默回退默认文案，保证一定有弹窗。
 * 节流策略：一次浏览器会话（sessionStorage）只弹一次，避免反复进出仪表板刷屏。
 */
import { nextTick, watch } from 'vue'
import type { WatchStopHandle } from 'vue'
import { useNotification } from 'naive-ui'
import apiClient from '@/api/client'
import { useAuthStore } from '@/stores/auth'

/** 默认兜底文案：LLM 接口超时或报错时使用（务必保证弹窗弹出） */
const DEFAULT_WELCOME_TEXT = '晚上好，root 👋 欢迎使用 OmicHub！'

/** LLM 欢迎词接口超时（毫秒）—— 需求要求 3 秒 */
const WELCOME_TIMEOUT_MS = 3_000

/** 一次会话只弹一次的标记键 */
const SESSION_FLAG_KEY = 'omichub:adminWelcomeShown'

/**
 * 模拟调用 LLM 欢迎词接口。
 *
 * - 复用全局 apiClient：自动携带 JWT，路径解析为 /api/v1/llm/generate-welcome
 *   （后端实现该路由即可，需校验登录态/管理员身份）
 * - 单独将本次请求超时覆盖为 3s（apiClient 默认 30s，彩蛋不应久等）
 * - 兼容两种返回形态：纯字符串 `"…"` 或 `{ content: "…" }`
 * - 任意失败（超时 / 网络错误 / 空文案）都抛出，交由调用方走兜底
 */
async function fetchWelcomeText(): Promise<string> {
  const { data } = await apiClient.post<string | { content?: string }>(
    '/llm/generate-welcome',
    {}, // POST 体；如需个性化可传 { username: authStore.user?.username }
    { timeout: WELCOME_TIMEOUT_MS },
  )

  const text = typeof data === 'string' ? data : data?.content
  if (!text || !text.trim()) {
    throw new Error('welcome payload is empty')
  }
  return text.trim()
}

export function useAdminWelcome() {
  // useNotification 必须在 setup 同步阶段调用（依赖上层 NNotificationProvider 注入）
  const notification = useNotification()
  const authStore = useAuthStore()

  /** 弹出欢迎通知（右上角由 Provider 决定、success 主题、6 秒后自动消失，悬停时计时暂停） */
  function showWelcome(text: string) {
    notification.create({
      title: '欢迎回来 ✨',
      content: text,
      type: 'success',
      duration: 6000,
      keepAliveOnHover: true,
    })
  }

  /** 真正执行：拉取文案（失败回退）→ 弹窗。一次会话只执行一次。 */
  async function fire() {
    // 先占位标记，避免并发 / 重复触发导致重复弹窗
    if (sessionStorage.getItem(SESSION_FLAG_KEY)) return
    sessionStorage.setItem(SESSION_FLAG_KEY, '1')

    let text = DEFAULT_WELCOME_TEXT
    try {
      text = await fetchWelcomeText()
    } catch {
      // 超时 / 网络错误 / 接口异常 —— 静默回退默认文案，依旧保证弹窗
    }
    showWelcome(text)
  }

  /**
   * 在 onMounted 中调用。通过 watch 兼容两种时序：
   * 1) 刚登录跳转过来：user 已是管理员 → immediate 立即触发；
   * 2) 刷新页面进入：DefaultLayout 正在异步 fetchUser，user 暂为 null
   *    → 等 user 变为管理员后再触发（fire 内部有会话标记防重复）。
   * 触发后立即取消监听，避免内存泄漏。
   */
  function triggerAdminWelcome() {
    // 注意：这里不能用 const stop = watch(..., () => { stop() }, { immediate: true })。
    // immediate 回调会在 watch 返回 stop handle 之前同步执行，此时 stop 仍处于 TDZ，
    // 生产环境压缩后变量名变成 $，会抛出 "Cannot access '$' before initialization"。
    let stop: WatchStopHandle | null = null
    stop = watch(
      () => authStore.user?.role,
      (role) => {
        if (role === 'admin') {
          void fire()
          // 推迟到 nextTick，确保 stop 已经被赋值
          nextTick(() => stop?.())
        }
      },
      { immediate: true },
    )
  }

  return { triggerAdminWelcome }
}
