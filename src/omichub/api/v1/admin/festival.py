"""节日彩蛋 — 管理端路由"""

from typing import Annotated

from fastapi import APIRouter, Depends

from omichub.api.deps import DbSession
from omichub.application.schemas.festival import (
    FestivalAdminListResponse,
    FestivalAdminUpdateRequest,
    FestivalDTO,
)
from omichub.application.services.cookie_service import CookieService
from omichub.application.services.festival_service import FestivalService
from omichub.infrastructure.database.repositories.festival_repository import (
    SqlAlchemyFestivalClaimRepository,
)
from omichub.infrastructure.yaml.festival_config_loader import FestivalConfigYamlLoader
from omichub.middleware.rbac import AdminRequired

router = APIRouter()


def get_festival_service(db: DbSession) -> FestivalService:
    return FestivalService(
        config_loader=FestivalConfigYamlLoader(),
        claim_repo=SqlAlchemyFestivalClaimRepository(db),
        cookie_service=CookieService(db),
    )


FestivalServiceDep = Annotated[FestivalService, Depends(get_festival_service)]


@router.get("/festivals", response_model=FestivalAdminListResponse, summary="节日列表")
async def list_festivals(
    _admin: AdminRequired,
    service: FestivalServiceDep,
) -> FestivalAdminListResponse:
    """列出全部节日配置与全局开关。"""
    enabled, festivals = await service.list_all()
    return FestivalAdminListResponse(globalEnabled=enabled, festivals=festivals)


@router.put("/festivals/{festival_id}", response_model=FestivalDTO, summary="更新节日")
async def update_festival(
    festival_id: str,
    req: FestivalAdminUpdateRequest,
    _admin: AdminRequired,
    service: FestivalServiceDep,
) -> FestivalDTO:
    """更新节日配置（启用状态、优先级、弹窗、额度）。"""
    payload = req.model_dump(exclude_unset=True)
    return await service.update_festival(festival_id, payload)


@router.post("/festivals/reload", summary="重载节日配置")
async def reload_festivals(
    _admin: AdminRequired,
    service: FestivalServiceDep,
) -> dict[str, bool]:
    """强制从 YAML 重新加载节日配置。"""
    service._loader.load(force=True)
    return {"reloaded": True}


__all__ = ["router"]
