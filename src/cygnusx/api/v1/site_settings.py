"""站点设置路由 — 公开读取 + 管理员更新"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from cygnusx.api.deps import AdminTotpRequired, CurrentUserId, DbSession
from cygnusx.application.schemas.site_settings import SiteSettingsDTO, UpdateSiteSettingsDTO
from cygnusx.application.services.site_settings_service import SiteSettingsService
from cygnusx.core.exceptions import AuthorizationError
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_session_factory

router = APIRouter()


async def require_admin(current_user_id: CurrentUserId) -> None:
    """校验当前用户为管理员"""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserModel.role).where(UserModel.id == UUID(current_user_id))
        )
        role = result.scalar_one_or_none()
        if role != "admin":
            raise AuthorizationError("需要管理员权限")


AdminRequired = Annotated[None, Depends(require_admin)]


@router.get("", response_model=SiteSettingsDTO, summary="获取站点设置（公开）")
async def get_site_settings(db: DbSession) -> SiteSettingsDTO:
    """公开接口：返回站点级开关（如是否开放注册）"""
    return await SiteSettingsService(db).get_settings()


@router.put("", response_model=SiteSettingsDTO, summary="更新站点设置（管理员+TOTP）")
async def update_site_settings(
    req: UpdateSiteSettingsDTO,
    _admin: AdminRequired,
    _totp: AdminTotpRequired,
    db: DbSession,
) -> SiteSettingsDTO:
    """管理员更新站点设置；请求头须附带 X-TOTP-Code 二次验证码。"""
    return await SiteSettingsService(db).update_settings(req)
