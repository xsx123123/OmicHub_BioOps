/**
 * 站点配置 store —— 登录/注册页所需的公开系统配置
 *
 * 两类配置、两个公开接口：
 *   - 注册开关：GET /site-settings → registration_enabled（DB 驱动，/auth/register 强制校验）
 *   - 提示文案 + 管理员联系方式：GET /site-content → registration（data/CygnusX.yaml 驱动，改文件即生效）
 *
 * 任一接口失败都回退到“允许注册 + 默认文案”，保证登录页永不卡死。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '@/api/client'
import type { RegistrationContent, ActivationContent, EasterEggContent, PlatformContent, AIAssistantContent } from '@/types/site-content'

// 文案兜底：site-content 拉取失败时使用
const DEFAULT_REGISTRATION: RegistrationContent = {
  disabled_message: '当前平台暂停自助注册，需由管理员创建账号。',
  admin_contact: '',
}
const DEFAULT_ACTIVATION: ActivationContent = {
  message: '喵喵！检测到账号还在沉睡中，快找管理员大大帮忙激活一下吧！开通后就能开心逛平台啦～',
  admin_contact: '',
  title: '账号还在星尘中沉睡 ✨',
  button_text: '收到喵！',
  title_urgent: '喵～ 你好像很着急呢 ⏳',
  message_urgent: '(｡•́︿•̀｡) 再戳管理员一下嘛！开通后就能开心逛平台啦～ ✨',
  button_text_urgent: '我这就去！',
}
const DEFAULT_EASTER_EGG: EasterEggContent = {
  message: '🎉 恭喜你发现了 CygnusX 的隐藏星际守护者！',
  button_text: '🐾 召唤星际猫咪',
  toast: '🎉 星际守护者已响应召唤！快看看屏幕上留下的足迹吧～ ✨',
}
const DEFAULT_PLATFORM: PlatformContent = {
  title: 'CygnusX · 天鹅座智能科研平台',
  author: '',
  email: '',
  github: '',
}
const DEFAULT_AI_ASSISTANT: AIAssistantContent = {
  input_hint: '星尘由硅基演算，请以你的判断为准。',
}

export const useSiteConfigStore = defineStore('site-config', () => {
  // 注册开关（true=开放自助注册）。默认 true：接口异常时不阻断登录页注册入口。
  const registrationEnabled = ref(true)
  // 注册提示文案与管理员联系方式（来自 YAML）。
  const registrationContent = ref<RegistrationContent>({ ...DEFAULT_REGISTRATION })
  // 账户未激活提示文案（来自 YAML activation 段）
  const activationContent = ref<ActivationContent>({ ...DEFAULT_ACTIVATION })
  // 关于页彩蛋文案（来自 YAML easter_egg 段）
  const easterEggContent = ref<EasterEggContent>({ ...DEFAULT_EASTER_EGG })
  // 平台元信息（来自 YAML platform 段）
  const platformContent = ref<PlatformContent>({ ...DEFAULT_PLATFORM })
  // AI 助手页文案（来自 YAML ai_assistant 段）
  const aiAssistantContent = ref<AIAssistantContent>({ ...DEFAULT_AI_ASSISTANT })
  // 配置是否已就绪（首次拉取完成后置 true，供点击时判断是否需等待）
  const loaded = ref(false)

  /** 当前是否允许自助注册 */
  const allowRegistration = computed(() => registrationEnabled.value)

  /** 关闭注册时的提示文案（纯文本，用于 message/dialog 标题） */
  const registrationDisabledMessage = computed(
    () => registrationContent.value.disabled_message,
  )

  /** 关闭注册时联系管理员的方式（邮箱/说明，trim 后；空串表示未配置） */
  const adminContact = computed(() => registrationContent.value.admin_contact.trim())

  /** 账户未激活弹窗的正文文案（正常版） */
  const activationMessage = computed(() => activationContent.value.message)
  /** 账户未激活弹窗标题（正常版） */
  const activationTitle = computed(() => activationContent.value.title)
  /** 账户未激活弹窗按钮文案（正常版） */
  const activationButtonText = computed(() => activationContent.value.button_text)
  /** 着急版标题（第 3 次起） */
  const activationTitleUrgent = computed(() => activationContent.value.title_urgent)
  /** 着急版正文（第 3 次起） */
  const activationMessageUrgent = computed(() => activationContent.value.message_urgent)
  /** 着急版按钮文案（第 3 次起） */
  const activationButtonTextUrgent = computed(() => activationContent.value.button_text_urgent)

  /** 关于页彩蛋弹窗的庆祝文案 */
  const easterEggMessage = computed(() => easterEggContent.value.message)

  /** 关于页右下角召唤按钮文案 */
  const easterEggButtonText = computed(() => easterEggContent.value.button_text)

  /** 召唤按钮点击后的 Toast 提示文案 */
  const easterEggToast = computed(() => easterEggContent.value.toast)

  /** 平台 GitHub 链接 */
  const platformGithub = computed(() => platformContent.value.github)
  /** 平台作者 */
  const platformAuthor = computed(() => platformContent.value.author)
  /** 平台联系邮箱 */
  const platformEmail = computed(() => platformContent.value.email)

  /** AI 助手输入框底部提示小字 */
  const aiInputHint = computed(() => aiAssistantContent.value.input_hint)

  /** 未激活弹窗联系管理员的方式；后端缺省回退到 registration.admin_contact */
  const activationContact = computed(() => {
    const c = activationContent.value.admin_contact.trim()
    return c || adminContact.value
  })

  /** 关闭注册时的完整提示文案（若配置了管理员联系方式则附带，用于 message 兜底场景） */
  const registrationDisabledTip = computed(() =>
    adminContact.value
      ? `${registrationDisabledMessage.value}（联系管理员：${adminContact.value}）`
      : registrationDisabledMessage.value,
  )

  // 并发去重：同一时刻只发一次请求，复用同一个 Promise
  let loadingPromise: Promise<void> | null = null

  /** 拉取站点配置；并发调用会复用同一个请求。 */
  function fetchSiteConfig(): Promise<void> {
    if (loadingPromise) return loadingPromise
    const p = (async () => {
      const [enabled, content] = await Promise.all([
        // 注册开关：接口异常默认允许注册
        apiClient
          .get<{ registration_enabled: boolean }>('/site-settings')
          .then((res) => res.data.registration_enabled)
          .catch(() => true),
        // 提示文案 + 管理员联系方式：接口异常保留默认文案
        apiClient
          .get<{ registration?: RegistrationContent; activation?: ActivationContent; easter_egg?: EasterEggContent; platform?: PlatformContent; ai_assistant?: AIAssistantContent }>('/site-content')
          .then((res) => res.data)
          .catch(() => undefined),
      ])
      registrationEnabled.value = enabled
      if (content?.registration) registrationContent.value = content.registration
      if (content?.activation) activationContent.value = content.activation
      if (content?.easter_egg) easterEggContent.value = content.easter_egg
      if (content?.platform) platformContent.value = content.platform
      if (content?.ai_assistant) aiAssistantContent.value = content.ai_assistant
      loaded.value = true
    })()
    loadingPromise = p
    // 结束后清掉 in-flight 标记，下次调用可重新拉取（保证管理员切换开关后刷新可见）
    p.finally(() => {
      loadingPromise = null
    })
    return p
  }

  return {
    registrationEnabled,
    registrationContent,
    activationContent,
    easterEggContent,
    platformContent,
    aiAssistantContent,
    loaded,
    allowRegistration,
    registrationDisabledMessage,
    adminContact,
    activationMessage,
    activationTitle,
    activationButtonText,
    activationTitleUrgent,
    activationMessageUrgent,
    activationButtonTextUrgent,
    activationContact,
    easterEggMessage,
    easterEggButtonText,
    easterEggToast,
    platformGithub,
    platformAuthor,
    platformEmail,
    aiInputHint,
    registrationDisabledTip,
    fetchSiteConfig,
  }
})
