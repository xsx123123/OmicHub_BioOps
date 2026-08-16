"""节日彩蛋域值对象 — 枚举与类型定义"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CalendarType(StrEnum):
    """日历类型"""

    LUNAR = "lunar"
    SOLAR = "solar"
    SOLAR_TERM = "solar_term"


class FestivalCategory(StrEnum):
    """节日分类"""

    TRADITIONAL = "traditional"
    MODERN = "modern"
    SOLAR_TERM = "solar_term"
    CUSTOM = "custom"
    SPECIAL = "special"


class AnimationType(StrEnum):
    """动画类型"""

    FIREWORKS = "fireworks"
    SNOW = "snow"
    CONFETTI = "confetti"
    STAR_HEART = "star_heart"
    MOON_GLOW = "moon_glow"
    PETAL = "petal"
    CODE_RAIN = "code_rain"
    LANTERN = "lantern"


class LunarDate(BaseModel):
    """农历日期"""

    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=30)
    leap: bool = False


class SolarDate(BaseModel):
    """公历日期"""

    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)


class SolarTerm(BaseModel):
    """24 节气"""

    name: str
    index: int = Field(..., ge=0, le=23)


class ActiveRange(BaseModel):
    """生效时间范围"""

    year: int | None = None
    offsetDays: int = 0
    durationDays: int = 1


class PopupButton(BaseModel):
    """弹窗按钮"""

    text: str = ""
    action: str = ""
    link: str | None = None


class AnimationConfig(BaseModel):
    """动画配置"""

    enabled: bool = False
    type: str = "confetti"
    duration: int = 10


class PopupConfig(BaseModel):
    """弹窗配置"""

    enabled: bool = False
    title: str = ""
    content: str = ""
    description: str = ""
    primaryButton: PopupButton | None = None
    secondaryButton: PopupButton | None = None
    animation: AnimationConfig | None = None


class QuotaBonusConfig(BaseModel):
    """额度赠送配置"""

    enabled: bool = False
    amount: float = 0
    unit: str = "cookie"
    description: str = ""


class FestivalGlobalConfig(BaseModel):
    """全局配置"""

    enabled: bool = True
    defaultActiveWindow: dict[str, Any] = Field(default_factory=dict)
    popupDefaults: dict[str, Any] = Field(default_factory=dict)
    quotaDefaults: dict[str, Any] = Field(default_factory=dict)


class AnimationTypeDef(BaseModel):
    """动画类型定义"""

    name: str
    description: str = ""
    library: str = ""


__all__ = [
    "CalendarType",
    "FestivalCategory",
    "AnimationType",
    "LunarDate",
    "SolarDate",
    "SolarTerm",
    "ActiveRange",
    "PopupButton",
    "AnimationConfig",
    "PopupConfig",
    "QuotaBonusConfig",
    "FestivalGlobalConfig",
    "AnimationTypeDef",
]
