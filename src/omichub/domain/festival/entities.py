"""节日彩蛋域实体"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.festival.value_objects import (
    ActiveRange,
    CalendarType,
    FestivalCategory,
    PopupConfig,
    QuotaBonusConfig,
    SolarDate,
    SolarTerm,
)


class FestivalConfig(BaseModel):
    """节日配置实体"""

    id: str
    name: str
    nameEn: str | None = None
    description: str = ""
    category: FestivalCategory
    calendarType: CalendarType
    lunarDate: dict[str, Any] | None = None
    solarDate: SolarDate | None = None
    solarTerm: SolarTerm | None = None
    activeRange: ActiveRange = Field(default_factory=lambda: ActiveRange())
    popup: PopupConfig = Field(default_factory=PopupConfig)
    quotaBonus: QuotaBonusConfig = Field(default_factory=QuotaBonusConfig)
    priority: int = 0
    enabled: bool = True

    def bonus_amount_display(self) -> str:
        """用于替换 {{bonusAmount}} 的展示字符串"""
        if not self.quotaBonus.enabled:
            return "0"
        return str(int(self.quotaBonus.amount))


class FestivalClaim(BaseModel):
    """节日领取记录实体"""

    id: int | None = None
    user_id: UUID
    festival_id: str
    year: int
    amount: float = 0
    transaction_id: int | None = None
    claimed_at: datetime = Field(default_factory=datetime.now)

    model_config = {"arbitrary_types_allowed": True}


__all__ = ["FestivalConfig", "FestivalClaim"]
