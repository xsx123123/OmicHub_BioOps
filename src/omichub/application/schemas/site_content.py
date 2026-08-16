"""站点首页文案 DTO（外置 YAML 驱动）"""

from omichub.application.schemas.base import OmicsHubBaseSchema


class HeroContent(OmicsHubBaseSchema):
    """Hero 欢迎区文案"""

    title: str
    description: str


class QuickEntryContent(OmicsHubBaseSchema):
    """快捷入口兜底文案。

    首页实际展示优先使用 site_settings.home_quick_entries；
    当 DB 配置不可用时，前端按 key 回退到默认路由与图标。
    """

    key: str
    title: str
    desc: str


class GuideStepContent(OmicsHubBaseSchema):
    """使用引导步骤文案"""

    title: str
    desc: str


class RegistrationContent(OmicsHubBaseSchema):
    """注册策略提示文案（公开读取）。

    真正的注册开关由后台 site-settings（DB）控制并在 /auth/register 强制校验；
    这里只提供“关闭注册时告诉用户联系谁”的文案，由 data/OmicHub.yaml 驱动。
    """

    disabled_message: str
    admin_contact: str


class ActivationContent(OmicsHubBaseSchema):
    """账户未激活提示文案（公开读取）。

    用户登录未激活账户时（auth_service 抛“账户未激活”），前端弹出友好提示，
    引导用户联系管理员激活。文案由 data/OmicHub.yaml 的 activation 段驱动，改文件即生效。
    admin_contact 缺省时回退到 registration.admin_contact，避免重复配置。

    支持“点击计数 + 文案切换”彩蛋：第 1-2 次显示正常版（title/button_text/message），
    第 3 次及以后切换为着急版（title_urgent/button_text_urgent/message_urgent），
    第 5 次点击关闭时触发全局猫爪彩蛋事件。
    """

    message: str
    admin_contact: str = ""
    title: str = "账号还在星尘中沉睡 ✨"
    button_text: str = "收到喵！"
    title_urgent: str = "喵～ 你好像很着急呢 ⏳"
    message_urgent: str = "(｡•́︿•̀｡) 再戳管理员一下嘛！开通后就能开心逛平台啦～ ✨"
    button_text_urgent: str = "我这就去！"


class EasterEggContent(OmicsHubBaseSchema):
    """关于页彩蛋文案（公开读取）。

    在「关于」页点击蓝色星球触发的隐藏弹窗，文案由 data/OmicHub.yaml 的
    easter_egg 段驱动，改文件即生效。
    """

    message: str = "🎉 恭喜你发现了 OmicHub 的隐藏星际守护者！"
    button_text: str = "🐾 召唤星际猫咪"
    toast: str = "🎉 星际守护者已响应召唤！快看看屏幕上留下的足迹吧～ ✨"


class PlatformContent(OmicsHubBaseSchema):
    """平台元信息（公开读取）。

    由 data/OmicHub.yaml 的 platform 段驱动，提供作者、联系方式、GitHub 等。
    """

    title: str = "OmicHub"
    author: str = ""
    email: str = ""
    github: str = ""


class AIAssistantContent(OmicsHubBaseSchema):
    """AI 助手页文案（公开读取）。

    由 data/OmicHub.yaml 的 ai_assistant 段驱动，改文件即生效。
    """

    input_hint: str = "内容由 AI 生成，请仔细甄别"


class SiteContentDTO(OmicsHubBaseSchema):
    """首页文案（公开读取）"""

    hero: HeroContent
    quick_entries: list[QuickEntryContent]
    guide_steps: list[GuideStepContent]
    registration: RegistrationContent
    activation: ActivationContent = ActivationContent(
        message="你的账号尚未激活，暂无法登录。请联系管理员为你开通激活，开通后即可正常使用平台～",
        admin_contact="",
    )
    easter_egg: EasterEggContent = EasterEggContent()
    platform: PlatformContent = PlatformContent()
    ai_assistant: AIAssistantContent = AIAssistantContent()
