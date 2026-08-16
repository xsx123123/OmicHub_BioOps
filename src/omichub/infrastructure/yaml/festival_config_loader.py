"""节日彩蛋 YAML 配置加载器

支持从外置 YAML 文件加载节日配置，基于 mtime 热重载。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

import yaml
from loguru import logger

from omichub.core.config import get_settings
from omichub.domain.festival.entities import FestivalConfig
from omichub.domain.festival.value_objects import (
    ActiveRange,
    AnimationConfig,
    AnimationTypeDef,
    CalendarType,
    FestivalCategory,
    FestivalGlobalConfig,
    PopupButton,
    PopupConfig,
    QuotaBonusConfig,
    SolarDate,
    SolarTerm,
)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """递归替换字符串中的 ${ENV} / ${ENV:-default}"""
    if isinstance(value, str):

        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default = match.group(2)
            return os.environ.get(var_name, default if default is not None else "")

        return _ENV_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


def _parse_popup(data: dict[str, Any]) -> PopupConfig:
    anim = data.get("animation") or {}
    return PopupConfig(
        enabled=bool(data.get("enabled", False)),
        title=str(data.get("title", "")),
        content=str(data.get("content", "")),
        description=str(data.get("description", "")),
        primaryButton=_parse_button(data.get("primaryButton") or {}),
        secondaryButton=_parse_button(data.get("secondaryButton") or {}),
        animation=AnimationConfig(
            enabled=bool(anim.get("enabled", False)),
            type=str(anim.get("type", "confetti")),
            duration=int(anim.get("duration", 10)),
        ),
    )


def _parse_button(data: dict[str, Any]) -> PopupButton | None:
    if not data:
        return None
    return PopupButton(
        text=str(data.get("text", "")),
        action=str(data.get("action", "")),
        link=data.get("link"),
    )


def _parse_quota(data: dict[str, Any]) -> QuotaBonusConfig:
    return QuotaBonusConfig(
        enabled=bool(data.get("enabled", False)),
        amount=float(data.get("amount", 0)),
        unit=str(data.get("unit", "cookie")),
        description=str(data.get("description", "")),
    )


def _parse_active_range(data: dict[str, Any] | None) -> ActiveRange:
    if not data:
        return ActiveRange()
    return ActiveRange(
        year=data.get("year"),
        offsetDays=int(data.get("offsetDays", 0)),
        durationDays=int(data.get("durationDays", 1)),
    )


def _build_festival(item: dict[str, Any]) -> FestivalConfig:
    calendar_type = CalendarType(item.get("calendarType", "solar"))
    solar_date = None
    solar_term = None
    lunar_date = None

    if calendar_type == CalendarType.SOLAR:
        sd = item.get("solarDate") or {}
        solar_date = SolarDate(month=int(sd.get("month", 1)), day=int(sd.get("day", 1)))
    elif calendar_type == CalendarType.SOLAR_TERM:
        st = item.get("solarTerm") or {}
        solar_term = SolarTerm(name=str(st.get("name", "")), index=int(st.get("index", 0)))
    elif calendar_type == CalendarType.LUNAR:
        ld = item.get("lunarDate") or {}
        lunar_date = {
            "month": int(ld.get("month", 1)),
            "day": int(ld.get("day", 1)),
            "leap": bool(ld.get("leap", False)),
        }

    popup_data = item.get("popup") or {}
    quota_data = item.get("quotaBonus") or {}

    return FestivalConfig(
        id=str(item["id"]),
        name=str(item["name"]),
        nameEn=item.get("nameEn"),
        description=str(item.get("description", "")),
        category=FestivalCategory(item.get("category", "modern")),
        calendarType=calendar_type,
        lunarDate=lunar_date,
        solarDate=solar_date,
        solarTerm=solar_term,
        activeRange=_parse_active_range(item.get("activeRange")),
        popup=_parse_popup(popup_data),
        quotaBonus=_parse_quota(quota_data),
        priority=int(item.get("priority", 0)),
        enabled=bool(item.get("enabled", True)),
    )


def _festival_to_dict(festival: FestivalConfig) -> dict[str, Any]:
    """将节日实体序列化为 YAML 字典。"""
    data: dict[str, Any] = {
        "id": festival.id,
        "name": festival.name,
        "category": festival.category.value,
        "calendarType": festival.calendarType.value,
        "activeRange": festival.activeRange.model_dump(),
        "priority": festival.priority,
        "enabled": festival.enabled,
    }
    if festival.nameEn:
        data["nameEn"] = festival.nameEn
    if festival.description:
        data["description"] = festival.description

    if festival.calendarType == CalendarType.SOLAR and festival.solarDate:
        data["solarDate"] = {"month": festival.solarDate.month, "day": festival.solarDate.day}
    elif festival.calendarType == CalendarType.LUNAR and festival.lunarDate:
        data["lunarDate"] = festival.lunarDate
    elif festival.calendarType == CalendarType.SOLAR_TERM and festival.solarTerm:
        data["solarTerm"] = festival.solarTerm.model_dump()

    popup = festival.popup
    popup_dict: dict[str, Any] = {"enabled": popup.enabled}
    if popup.title:
        popup_dict["title"] = popup.title
    if popup.content:
        popup_dict["content"] = popup.content
    if popup.description:
        popup_dict["description"] = popup.description
    if popup.primaryButton:
        popup_dict["primaryButton"] = popup.primaryButton.model_dump()
    if popup.secondaryButton:
        popup_dict["secondaryButton"] = popup.secondaryButton.model_dump()
    if popup.animation:
        popup_dict["animation"] = popup.animation.model_dump()
    data["popup"] = popup_dict

    qb = festival.quotaBonus
    data["quotaBonus"] = {
        "enabled": qb.enabled,
        "amount": qb.amount,
        "unit": qb.unit,
    }
    if qb.description:
        data["quotaBonus"]["description"] = qb.description

    return data


class FestivalConfigYamlLoader:
    """节日配置 YAML 加载器，支持 mtime 热重载。"""

    def __init__(self, path: str | None = None):
        self._path = path or get_settings().festival_config_yaml
        self._cache: dict[str, Any] | None = None
        self._mtime: float = 0.0

    def _load_raw(self) -> dict[str, Any]:
        file_path = Path(self._path)
        if not file_path.exists():
            logger.warning(f"节日彩蛋配置文件不存在: {self._path}")
            return {"version": "1.0", "global": {}, "festivals": [], "animationTypes": {}}

        with open(file_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return cast(dict[str, Any], _interpolate_env(raw))

    def load(self, force: bool = False) -> tuple[FestivalGlobalConfig, list[FestivalConfig], dict[str, AnimationTypeDef]]:
        """加载配置。若文件 mtime 未变且非 force，则返回缓存。"""
        file_path = Path(self._path)
        current_mtime = file_path.stat().st_mtime if file_path.exists() else 0.0

        if not force and self._cache is not None and current_mtime == self._mtime:
            return self._from_cache()

        raw = self._load_raw()
        self._cache = raw
        self._mtime = current_mtime

        return self._from_cache()

    def _from_cache(
        self,
    ) -> tuple[FestivalGlobalConfig, list[FestivalConfig], dict[str, AnimationTypeDef]]:
        assert self._cache is not None
        global_cfg = FestivalGlobalConfig(**self._cache.get("global", {}))

        festivals = [
            _build_festival(item)
            for item in self._cache.get("festivals", [])
            if item and item.get("id")
        ]

        animation_types = {
            key: AnimationTypeDef(**value)
            for key, value in (self._cache.get("animationTypes") or {}).items()
        }

        return global_cfg, festivals, animation_types

    def save_all(self, festivals: list[FestivalConfig]) -> None:
        """保存节日列表回 YAML，保留 global 与 animationTypes 不变。"""
        raw = self._load_raw()
        raw["festivals"] = [_festival_to_dict(f) for f in festivals]
        file_path = Path(self._path)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True, sort_keys=False)
        self._cache = raw
        self._mtime = file_path.stat().st_mtime


__all__ = ["FestivalConfigYamlLoader"]
