"""节日彩蛋领域模块"""

from omichub.domain.festival.entities import FestivalClaim, FestivalConfig
from omichub.domain.festival.repositories import (
    FestivalClaimRepository,
    FestivalConfigRepository,
)
from omichub.domain.festival.services import FestivalCalendarService
from omichub.domain.festival.solar_term_calendar import (
    get_solar_term_date,
    get_solar_term_date_by_name,
)
from omichub.domain.festival.value_objects import (
    ActiveRange,
    AnimationConfig,
    AnimationType,
    AnimationTypeDef,
    CalendarType,
    FestivalCategory,
    FestivalGlobalConfig,
    LunarDate,
    PopupButton,
    PopupConfig,
    QuotaBonusConfig,
    SolarDate,
    SolarTerm,
)

__all__ = [
    "FestivalClaim",
    "FestivalConfig",
    "FestivalCalendarService",
    "FestivalConfigRepository",
    "FestivalClaimRepository",
    "get_solar_term_date",
    "get_solar_term_date_by_name",
    "ActiveRange",
    "AnimationConfig",
    "AnimationType",
    "AnimationTypeDef",
    "CalendarType",
    "FestivalCategory",
    "FestivalGlobalConfig",
    "LunarDate",
    "PopupButton",
    "PopupConfig",
    "QuotaBonusConfig",
    "SolarDate",
    "SolarTerm",
]
