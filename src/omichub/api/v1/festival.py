"""节日彩蛋 — 用户端路由"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.festival import (
    FestivalClaimRequest,
    FestivalClaimResponse,
    FestivalTodayResponse,
)
from omichub.application.services.cookie_service import CookieService
from omichub.application.services.festival_service import FestivalService
from omichub.infrastructure.database.repositories.festival_repository import (
    SqlAlchemyFestivalClaimRepository,
)
from omichub.infrastructure.yaml.festival_config_loader import FestivalConfigYamlLoader

router = APIRouter()


def get_festival_service(db: DbSession) -> FestivalService:
    return FestivalService(
        config_loader=FestivalConfigYamlLoader(),
        claim_repo=SqlAlchemyFestivalClaimRepository(db),
        cookie_service=CookieService(db),
    )


FestivalServiceDep = Annotated[FestivalService, Depends(get_festival_service)]


@router.get("/today", response_model=FestivalTodayResponse, summary="今日节日")
async def get_today_festival(
    current_user_id: CurrentUserId,
    service: FestivalServiceDep,
) -> FestivalTodayResponse:
    """获取今日节日配置及当前用户领取状态。"""
    return await service.get_today_festival(UUID(current_user_id))


@router.post("/claim", response_model=FestivalClaimResponse, summary="领取节日额度")
async def claim_festival(
    req: FestivalClaimRequest,
    current_user_id: CurrentUserId,
    service: FestivalServiceDep,
) -> FestivalClaimResponse:
    """领取当前生效节日的饼干额度。"""
    return await service.claim_festival(UUID(current_user_id), req.festivalId)


__all__ = ["router"]
