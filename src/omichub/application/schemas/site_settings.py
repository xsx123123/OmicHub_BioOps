"""站点设置 DTO"""

from typing import Literal

from pydantic import Field, field_validator

from omichub.application.schemas.base import OmicsHubBaseSchema

TOTPPolicy = Literal["off", "optional", "required"]
CollaborationPreset = Literal["custom", "light", "parallel", "full"]
CollaborationDegradationLocale = Literal["zh-CN", "en"]
QuickEntryColor = Literal["blue", "purple", "violet", "cyan", "green", "orange", "teal", "gray"]


class HomeQuickEntryDTO(OmicsHubBaseSchema):
    """首页快捷入口配置"""

    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=24)
    desc: str = Field(default="", max_length=80)
    to: str = Field(min_length=1, max_length=200)
    icon: str = Field(default="DocumentTextOutline", max_length=64)
    icon_bg: QuickEntryColor = "blue"

    @field_validator("to")
    @classmethod
    def validate_internal_route(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("快捷入口路由必须是站内绝对路径")
        return value

    @field_validator("icon")
    @classmethod
    def validate_icon_key(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("图标 key 只能包含字母、数字、下划线或短横线")
        return value


class SiteSettingsDTO(OmicsHubBaseSchema):
    """站点设置（公开）"""

    registration_enabled: bool
    totp_policy: TOTPPolicy
    home_quick_entries: list[HomeQuickEntryDTO]
    subagent_fanout_enabled: bool = False
    agentteams_chat_entry_enabled: bool = False
    multi_expert_consultation_enabled: bool = False
    unified_intent_router_enabled: bool = False
    collaboration_preset: CollaborationPreset = "custom"
    collaboration_degradation_locale: CollaborationDegradationLocale = "zh-CN"
    collaboration_degradation_template_zh: str = ""
    collaboration_degradation_template_en: str = ""
    agent_memory_enabled: bool = True


class UpdateSiteSettingsDTO(OmicsHubBaseSchema):
    """更新站点设置（管理员）"""

    registration_enabled: bool | None = None
    totp_policy: TOTPPolicy | None = None
    subagent_fanout_enabled: bool | None = None
    agentteams_chat_entry_enabled: bool | None = None
    multi_expert_consultation_enabled: bool | None = None
    unified_intent_router_enabled: bool | None = None
    collaboration_preset: CollaborationPreset | None = None
    collaboration_degradation_locale: CollaborationDegradationLocale | None = None
    collaboration_degradation_template_zh: str | None = Field(default=None, max_length=1_000)
    collaboration_degradation_template_en: str | None = Field(default=None, max_length=1_000)
    agent_memory_enabled: bool | None = None
    home_quick_entries: list[HomeQuickEntryDTO] | None = Field(
        default=None,
        min_length=1,
        max_length=8,
    )
