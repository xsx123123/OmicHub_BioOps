"""节日彩蛋系统 DTO"""

from __future__ import annotations

from typing import Any

from omichub.application.schemas.base import OmicsHubBaseSchema


class PopupButtonDTO(OmicsHubBaseSchema):
    """弹窗按钮 DTO"""

    text: str = ""
    action: str = ""
    link: str | None = None


class AnimationConfigDTO(OmicsHubBaseSchema):
    """动画配置 DTO"""

    enabled: bool = False
    type: str = "confetti"
    duration: int = 10


class PopupConfigDTO(OmicsHubBaseSchema):
    """弹窗配置 DTO"""

    enabled: bool = False
    title: str = ""
    content: str = ""
    description: str = ""
    primaryButton: PopupButtonDTO | None = None
    secondaryButton: PopupButtonDTO | None = None
    animation: AnimationConfigDTO | None = None


class QuotaBonusDTO(OmicsHubBaseSchema):
    """额度赠送 DTO"""

    enabled: bool = False
    amount: float = 0
    unit: str = "cookie"
    description: str = ""


class FestivalDTO(OmicsHubBaseSchema):
    """节日配置 DTO"""

    id: str
    name: str
    nameEn: str | None = None
    description: str = ""
    category: str
    calendarType: str
    lunarDate: dict[str, Any] | None = None
    solarDate: dict[str, Any] | None = None
    solarTerm: dict[str, Any] | None = None
    activeRange: dict[str, Any] = {}
    popup: PopupConfigDTO
    quotaBonus: QuotaBonusDTO
    priority: int = 0
    enabled: bool = True


class FestivalTodayResponse(OmicsHubBaseSchema):
    """今日节日响应"""

    hasFestival: bool
    festival: FestivalDTO | None = None
    claimed: bool = False


class FestivalClaimRequest(OmicsHubBaseSchema):
    """领取节日额度请求"""

    festivalId: str


class FestivalClaimResponse(OmicsHubBaseSchema):
    """领取节日额度响应"""

    success: bool
    amount: float = 0
    balance: float = 0
    message: str = ""


class FestivalAdminUpdateRequest(OmicsHubBaseSchema):
    """管理员更新节日请求"""

    enabled: bool | None = None
    popup: PopupConfigDTO | None = None
    quotaBonus: QuotaBonusDTO | None = None
    priority: int | None = None


class FestivalAdminListResponse(OmicsHubBaseSchema):
    """管理员节日列表响应"""

    globalEnabled: bool
    festivals: list[FestivalDTO]


__all__ = [
    "PopupButtonDTO",
    "AnimationConfigDTO",
    "PopupConfigDTO",
    "QuotaBonusDTO",
    "FestivalDTO",
    "FestivalTodayResponse",
    "FestivalClaimRequest",
    "FestivalClaimResponse",
    "FestivalAdminUpdateRequest",
    "FestivalAdminListResponse",
]
