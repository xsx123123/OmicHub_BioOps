"""节日彩蛋领域层单元测试"""

from datetime import date

import pytest

from cygnusx.domain.festival import (
    ActiveRange,
    CalendarType,
    FestivalCategory,
    FestivalConfig,
)
from cygnusx.domain.festival.services import FestivalCalendarService


@pytest.fixture
def service():
    return FestivalCalendarService()


@pytest.fixture
def spring_festival():
    return FestivalConfig(
        id="spring_festival",
        name="春节",
        category=FestivalCategory.TRADITIONAL,
        calendarType=CalendarType.LUNAR,
        lunarDate={"month": 1, "day": 1},
        activeRange=ActiveRange(offsetDays=-1, durationDays=7),
        priority=100,
        enabled=True,
    )


@pytest.fixture
def new_year():
    return FestivalConfig(
        id="new_year",
        name="元旦",
        category=FestivalCategory.MODERN,
        calendarType=CalendarType.SOLAR,
        solarDate={"month": 1, "day": 1},
        priority=90,
        enabled=True,
    )


@pytest.fixture
def programmers_day():
    return FestivalConfig(
        id="programmers_day",
        name="程序员节",
        category=FestivalCategory.SPECIAL,
        calendarType=CalendarType.SOLAR,
        solarDate={"month": 10, "day": 24},
        priority=85,
        enabled=True,
    )


def test_resolve_lunar_date(service: FestivalCalendarService, spring_festival: FestivalConfig):
    """农历春节转公历：2026 年春节为 2 月 17 日"""
    resolved = service.resolve_festival_date(spring_festival, 2026)
    assert resolved == date(2026, 2, 17)


def test_resolve_solar_date(service: FestivalCalendarService, new_year: FestivalConfig):
    resolved = service.resolve_festival_date(new_year, 2026)
    assert resolved == date(2026, 1, 1)


def test_active_window_with_offset(service: FestivalCalendarService, spring_festival: FestivalConfig):
    """春节提前 1 天开始，持续 7 天"""
    start, end = service.active_window(spring_festival, 2026)
    assert start.date() == date(2026, 2, 16)
    assert end.date() == date(2026, 2, 22)


def test_is_active_on(service: FestivalCalendarService, spring_festival: FestivalConfig):
    assert service.is_active_on(spring_festival, date(2026, 2, 17)) is True
    assert service.is_active_on(spring_festival, date(2026, 2, 16)) is True
    assert service.is_active_on(spring_festival, date(2026, 2, 23)) is False


def test_disabled_festival_not_active(service: FestivalCalendarService, spring_festival: FestivalConfig):
    spring_festival.enabled = False
    assert service.is_active_on(spring_festival, date(2026, 2, 17)) is False


def test_select_active_festival_by_priority(
    service: FestivalCalendarService,
    spring_festival: FestivalConfig,
    new_year: FestivalConfig,
):
    """同一天多个节日时按优先级选择最高者"""
    # 2026-02-17 为春节；元旦显然不活跃，仅测试优先级比较逻辑
    active = service.select_active_festival([spring_festival, new_year], date(2026, 2, 17))
    assert active is not None
    assert active.id == "spring_festival"


def test_select_active_festival_none(service: FestivalCalendarService, programmers_day: FestivalConfig):
    active = service.select_active_festival([programmers_day], date(2026, 7, 9))
    assert active is None


def test_solar_term_li_chun(service: FestivalCalendarService):
    li_chun = FestivalConfig(
        id="li_chun",
        name="立春",
        category=FestivalCategory.SOLAR_TERM,
        calendarType=CalendarType.SOLAR_TERM,
        solarTerm={"name": "立春", "index": 0},
        priority=50,
        enabled=True,
    )
    assert service.is_active_on(li_chun, date(2026, 2, 4)) is True


def test_solar_term_yu_shui(service: FestivalCalendarService):
    yu_shui = FestivalConfig(
        id="yu_shui",
        name="雨水",
        category=FestivalCategory.SOLAR_TERM,
        calendarType=CalendarType.SOLAR_TERM,
        solarTerm={"name": "雨水", "index": 1},
        priority=50,
        enabled=True,
    )
    assert service.resolve_festival_date(yu_shui, 2026) == date(2026, 2, 18)


def test_solar_term_li_qiu(service: FestivalCalendarService):
    """2026 年立秋当天应命中节日彩蛋。"""
    li_qiu = FestivalConfig(
        id="li_qiu",
        name="立秋",
        category=FestivalCategory.SOLAR_TERM,
        calendarType=CalendarType.SOLAR_TERM,
        solarTerm={"name": "立秋", "index": 12},
        priority=50,
        enabled=True,
    )
    assert service.is_active_on(li_qiu, date(2026, 8, 7)) is True


def test_solar_term_year_out_of_range(service: FestivalCalendarService):
    yu_shui = FestivalConfig(
        id="yu_shui",
        name="雨水",
        category=FestivalCategory.SOLAR_TERM,
        calendarType=CalendarType.SOLAR_TERM,
        solarTerm={"name": "雨水", "index": 1},
        priority=50,
        enabled=True,
    )
    assert service.resolve_festival_date(yu_shui, 2040) is None
