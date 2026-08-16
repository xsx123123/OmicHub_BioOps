/** 首页文案（来自 /site-content） */

export interface HeroContent {
  title: string
  description: string
}

/** 快捷入口兜底文案：实际首页入口优先使用 site_settings.home_quick_entries */
export interface QuickEntryContent {
  key: string
  title: string
  desc: string
}

export interface GuideStepContent {
  title: string
  desc: string
}

/** 注册策略提示文案：开关由后台 site-settings 控制，这里仅提供关闭时的提示文案与管理员联系方式 */
export interface RegistrationContent {
  /** 注册关闭时的提示文案 */
  disabled_message: string
  /** 暂停注册时提示联系的管理员（可空） */
  admin_contact: string
}

/** 账户未激活提示文案：登录未激活账户时弹窗展示。
 *  支持点击计数彩蛋：第 1-2 次正常版，第 3 次起着急版，第 5 次触发猫爪彩蛋。 */
export interface ActivationContent {
  /** 未激活弹窗的正文文案（正常版） */
  message: string
  /** 联系管理员的方式（可空，后端缺省时回退到 registration.admin_contact） */
  admin_contact: string
  /** 标题（正常版） */
  title: string
  /** 按钮文案（正常版） */
  button_text: string
  /** 标题（着急版，第 3 次起） */
  title_urgent: string
  /** 正文文案（着急版） */
  message_urgent: string
  /** 按钮文案（着急版） */
  button_text_urgent: string
}

/** 关于页彩蛋文案：点击蓝色星球触发的隐藏弹窗 */
export interface EasterEggContent {
  /** 彩蛋弹窗的庆祝文案 */
  message: string
  /** 悬浮召唤按钮文案（关于页右下角”召唤星际猫咪”） */
  button_text: string
  /** 点击召唤按钮后的 Toast 提示文案 */
  toast: string
}

/** 平台元信息：作者、联系方式、GitHub 等 */
export interface PlatformContent {
  title: string
  author: string
  email: string
  github: string
}

/** AI 助手页文案 */
export interface AIAssistantContent {
  /** 输入框底部提示小字 */
  input_hint: string
}

export interface SiteContent {
  hero: HeroContent
  quick_entries: QuickEntryContent[]
  guide_steps: GuideStepContent[]
  /** 注册策略提示文案（可选：后端未返回时不阻断 HomeView 默认文案） */
  registration?: RegistrationContent
  /** 账户未激活提示文案（可选） */
  activation?: ActivationContent
  /** 关于页彩蛋文案（可选） */
  easter_egg?: EasterEggContent
  /** 平台元信息（可选） */
  platform?: PlatformContent
  /** AI 助手页文案（可选） */
  ai_assistant?: AIAssistantContent
}
