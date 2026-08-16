"""平台配置路由 — 公开读取"""

from fastapi import APIRouter

from omichub.api.deps import DbSession
from omichub.application.schemas.site_settings import SiteSettingsDTO
from omichub.application.services.site_settings_service import SiteSettingsService

router = APIRouter()


@router.get("/config", response_model=SiteSettingsDTO, summary="获取平台全局配置（公开）")
async def get_platform_config(db: DbSession) -> SiteSettingsDTO:
    """公开接口：返回平台全局配置（含开放注册、TOTP 策略等）。"""
    return await SiteSettingsService(db).get_settings()
