"""站点首页文案路由 — 公开读取（无需登录）"""

from fastapi import APIRouter

from omichub.application.schemas.site_content import SiteContentDTO
from omichub.application.services.site_content_service import SiteContentService

router = APIRouter()

service = SiteContentService()


@router.get("", response_model=SiteContentDTO, summary="获取首页文案（公开）")
async def get_site_content() -> SiteContentDTO:
    """公开接口：返回首页文案（hero / 快捷入口 / 引导步骤）。

    文案由 data/OmicHub.yaml 驱动，修改文件后刷新即生效，无需重启。
    """
    return service.get_content()
