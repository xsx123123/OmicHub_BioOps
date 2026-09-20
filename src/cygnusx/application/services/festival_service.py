"""节日彩蛋应用服务"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from cygnusx.application.schemas.festival import (
    FestivalClaimResponse,
    FestivalDTO,
    FestivalTodayResponse,
)
from cygnusx.application.services.cookie_service import CookieService
from cygnusx.domain.cookie.value_objects import TransactionType
from cygnusx.domain.festival.entities import FestivalClaim, FestivalConfig
from cygnusx.domain.festival.repositories import FestivalClaimRepository
from cygnusx.domain.festival.services import FestivalCalendarService
from cygnusx.infrastructure.yaml.festival_config_loader import FestivalConfigYamlLoader


class FestivalService:
    """节日彩蛋应用服务 — 节日检测、弹窗、额度领取编排。"""

    def __init__(
        self,
        config_loader: FestivalConfigYamlLoader,
        claim_repo: FestivalClaimRepository,
        cookie_service: CookieService,
    ):
        self._loader = config_loader
        self._claim_repo = claim_repo
        self._cookie_service = cookie_service
        self._calendar = FestivalCalendarService()

    async def get_today_festival(self, user_id: UUID | None = None) -> FestivalTodayResponse:
        """获取今日节日及用户领取状态。"""
        global_cfg, festivals, _ = self._loader.load()

        if not global_cfg.enabled:
            return FestivalTodayResponse(hasFestival=False, festival=None, claimed=False)

        active = self._calendar.select_active_festival(festivals)
        if active is None:
            return FestivalTodayResponse(hasFestival=False, festival=None, claimed=False)

        claimed = False
        if user_id is not None:
            year = datetime.now().year
            existing = await self._claim_repo.get_claim(user_id, active.id, year)
            claimed = existing is not None

        return FestivalTodayResponse(
            hasFestival=True,
            festival=_to_dto(active),
            claimed=claimed,
        )

    async def claim_festival(self, user_id: UUID, festival_id: str) -> FestivalClaimResponse:
        """领取节日额度。"""
        global_cfg, festivals, _ = self._loader.load()

        if not global_cfg.enabled:
            return FestivalClaimResponse(success=False, message="节日彩蛋系统已关闭")

        festival = next((f for f in festivals if f.id == festival_id), None)
        if festival is None:
            return FestivalClaimResponse(success=False, message="节日不存在")

        if not self._calendar.is_active_on(festival):
            return FestivalClaimResponse(success=False, message="该节日当前未生效")

        if not festival.quotaBonus.enabled or festival.quotaBonus.amount <= 0:
            return FestivalClaimResponse(success=False, message="该节日未配置额度赠送")

        year = datetime.now().year
        existing = await self._claim_repo.get_claim(user_id, festival_id, year)
        if existing is not None:
            return FestivalClaimResponse(success=False, message="您已领取过该节日额度")

        amount = Decimal(str(festival.quotaBonus.amount))
        account = await self._cookie_service.get_or_create_account(user_id)
        txn = await self._cookie_service._record_transaction(
            account,
            TransactionType.EARN,
            amount,
            source_type="festival",
            source_id=f"{festival_id}:{year}",
            description=f"{festival.name} 节日赠送 {amount} 🥫",
        )

        claim = FestivalClaim(
            user_id=user_id,
            festival_id=festival_id,
            year=year,
            amount=float(amount),
            transaction_id=txn.id,
        )
        await self._claim_repo.save_claim(claim)

        account_after = await self._cookie_service.get_account(user_id)
        return FestivalClaimResponse(
            success=True,
            amount=float(amount),
            balance=float(account_after.balance),
            message=f"成功领取 {festival.name} {amount} 饼干！",
        )

    async def list_all(self) -> tuple[bool, list[FestivalDTO]]:
        """管理员列表：返回全局开关与全部节日。"""
        global_cfg, festivals, _ = self._loader.load()
        return global_cfg.enabled, [_to_dto(f) for f in festivals]

    async def update_festival(
        self, festival_id: str, payload: dict[str, Any]
    ) -> FestivalDTO:
        """管理员更新节日配置（写回 YAML）。

        MVP 仅支持修改 enabled / priority / popup / quotaBonus；
        日期与 ID 等核心字段仍建议直接编辑 YAML。
        """
        global_cfg, festivals, _ = self._loader.load()
        festival = next((f for f in festivals if f.id == festival_id), None)
        if festival is None:
            raise ValueError(f"节日 {festival_id} 不存在")

        if "enabled" in payload:
            festival.enabled = bool(payload["enabled"])
        if "priority" in payload:
            festival.priority = int(payload["priority"])
        if "popup" in payload:
            popup_data = payload["popup"] or {}
            if "enabled" in popup_data:
                festival.popup.enabled = bool(popup_data["enabled"])
            if "title" in popup_data:
                festival.popup.title = str(popup_data["title"])
            if "content" in popup_data:
                festival.popup.content = str(popup_data["content"])
            if "description" in popup_data:
                festival.popup.description = str(popup_data["description"])
            if "animation" in popup_data and festival.popup.animation:
                anim = popup_data["animation"] or {}
                if "enabled" in anim:
                    festival.popup.animation.enabled = bool(anim["enabled"])
                if "type" in anim:
                    festival.popup.animation.type = str(anim["type"])
                if "duration" in anim:
                    festival.popup.animation.duration = int(anim["duration"])
        if "quotaBonus" in payload:
            qb_data = payload["quotaBonus"] or {}
            if "enabled" in qb_data:
                festival.quotaBonus.enabled = bool(qb_data["enabled"])
            if "amount" in qb_data:
                festival.quotaBonus.amount = float(qb_data["amount"])
            if "description" in qb_data:
                festival.quotaBonus.description = str(qb_data["description"])

        self._loader.save_all(festivals)
        return _to_dto(festival)


def _to_dto(festival: FestivalConfig) -> FestivalDTO:
    from cygnusx.application.schemas.festival import (
        AnimationConfigDTO,
        PopupButtonDTO,
        PopupConfigDTO,
        QuotaBonusDTO,
    )

    popup = festival.popup
    anim = popup.animation
    animation_dto = None
    if anim:
        animation_dto = AnimationConfigDTO(
            enabled=anim.enabled,
            type=anim.type,
            duration=anim.duration,
        )

    primary = popup.primaryButton
    secondary = popup.secondaryButton
    primary_dto = None
    secondary_dto = None
    if primary:
        primary_dto = PopupButtonDTO(text=primary.text, action=primary.action, link=primary.link)
    if secondary:
        secondary_dto = PopupButtonDTO(
            text=secondary.text, action=secondary.action, link=secondary.link
        )

    return FestivalDTO(
        id=festival.id,
        name=festival.name,
        nameEn=festival.nameEn,
        description=festival.description,
        category=festival.category.value,
        calendarType=festival.calendarType.value,
        lunarDate=festival.lunarDate,
        solarDate=festival.solarDate.model_dump() if festival.solarDate else None,
        solarTerm=festival.solarTerm.model_dump() if festival.solarTerm else None,
        activeRange=festival.activeRange.model_dump(),
        popup=PopupConfigDTO(
            enabled=popup.enabled,
            title=popup.title,
            content=popup.content,
            description=popup.description,
            primaryButton=primary_dto,
            secondaryButton=secondary_dto,
            animation=animation_dto,
        ),
        quotaBonus=QuotaBonusDTO(
            enabled=festival.quotaBonus.enabled,
            amount=festival.quotaBonus.amount,
            unit=festival.quotaBonus.unit,
            description=festival.quotaBonus.description,
        ),
        priority=festival.priority,
        enabled=festival.enabled,
    )


__all__ = ["FestivalService"]
