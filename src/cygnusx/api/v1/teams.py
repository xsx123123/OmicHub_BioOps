"""团队空间路由"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.team import TeamListResponse
from cygnusx.application.services.team_service import TeamService

router = APIRouter()


def get_team_service(db: DbSession) -> TeamService:
    """获取团队服务实例"""
    return TeamService(db)


TeamServiceDep = Annotated[TeamService, Depends(get_team_service)]


@router.get("", response_model=TeamListResponse, summary="获取我的团队列表")
async def list_my_teams(
    current_user_id: CurrentUserId,
    service: TeamServiceDep,
) -> TeamListResponse:
    """返回当前用户作为 owner / writer / reader 所属的团队列表。"""
    items = await service.list_my_teams(UUID(current_user_id))
    return TeamListResponse(items=items, total=len(items))
