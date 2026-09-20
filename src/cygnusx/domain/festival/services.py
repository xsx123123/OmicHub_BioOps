"""节日彩蛋域服务 — 日期计算与节日检测"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

from lunardate import LunarDate as _LunarDate

from cygnusx.domain.festival.solar_term_calendar import (
    get_solar_term_date,
    get_solar_term_date_by_name,
)
from cygnusx.domain.festival.value_objects import (
    ActiveRange,
    CalendarType,
)

if TYPE_CHECKING:
    from cygnusx.domain.festival.entities import FestivalConfig


class FestivalCalendarService:
    """节日日历服务：负责农历/公历/节气日期解析与生效区间计算。"""

    def resolve_reference_date(self, reference: datetime | date | None = None) -> date:
        """解析参考日期，默认返回今天。"""
        if reference is None:
            reference = datetime.now()
        if isinstance(reference, datetime):
            return reference.date()
        return reference

    def resolve_festival_date(self, festival: FestivalConfig, year: int) -> date | None:
        """根据节日配置，解析出指定年份的公历日期。"""
        if festival.calendarType == CalendarType.SOLAR:
            solar = festival.solarDate
            if solar is None:
                return None
            try:
                return date(year, solar.month, solar.day)
            except ValueError:
                return None

        if festival.calendarType == CalendarType.LUNAR:
            lunar = festival.lunarDate
            if lunar is None:
                return None
            try:
                ld = _LunarDate(year, lunar["month"], lunar["day"], lunar.get("leap", False))
                return cast(date, ld.to_solar_date())
            except ValueError:
                return None

        if festival.calendarType == CalendarType.SOLAR_TERM:
            term = festival.solarTerm
            if term is None:
                return None
            by_name = get_solar_term_date_by_name(year, term.name)
            if by_name is not None:
                return by_name
            return get_solar_term_date(year, term.index)

        return None

    def active_window(
        self,
        festival: FestivalConfig,
        year: int,
    ) -> tuple[datetime, datetime] | None:
        """计算节日在指定年份的生效时间窗口。

        Returns:
            (start, end) 或 None（无法解析日期）
        """
        ref_date = self.resolve_festival_date(festival, year)
        if ref_date is None:
            return None

        active_range = festival.activeRange or ActiveRange()

        # 自定义 activeRange 可限定特定年份
        if active_range.year is not None and active_range.year != year:
            return None

        start_date = ref_date + timedelta(days=active_range.offsetDays)
        end_date = start_date + timedelta(days=active_range.durationDays - 1)

        start = datetime.combine(start_date, time.min)
        end = datetime.combine(end_date, time.max)
        return start, end

    def is_active_on(
        self,
        festival: FestivalConfig,
        reference: datetime | date | None = None,
    ) -> bool:
        """判断节日在参考日期是否处于生效区间。"""
        if not festival.enabled:
            return False

        ref = self.resolve_reference_date(reference)
        window = self.active_window(festival, ref.year)
        if window is None:
            return False
        start, end = window
        ref_dt = datetime.combine(ref, time.min)
        return start <= ref_dt <= end

    def select_active_festival(
        self,
        festivals: list[FestivalConfig],
        reference: datetime | date | None = None,
    ) -> FestivalConfig | None:
        """从节日列表中选出当前生效且优先级最高的节日。"""
        active = [f for f in festivals if self.is_active_on(f, reference)]
        if not active:
            return None
        return max(active, key=lambda f: (f.priority, f.name))


__all__ = ["FestivalCalendarService"]
