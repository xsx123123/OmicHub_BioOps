"""首页条幅通知路由"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementResponse,
    AnnouncementUpdate,
)
from cygnusx.application.services.announcement_service import AnnouncementService
from cygnusx.core.exceptions import AuthorizationError, NotFoundError
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.repositories.announcement_repository import (
    SqlAlchemyAnnouncementRepository,
)

router = APIRouter()


async def require_admin(current_user_id: CurrentUserId, db: DbSession) -> None:
    """校验当前用户为管理员（与 notification 路由同模式）"""
    user = await db.get(UserModel, UUID(current_user_id))
    if user is None or user.role != "admin":
        raise AuthorizationError("需要管理员权限")


AdminRequired = Annotated[None, Depends(require_admin)]


@router.get(
    "/active",
    response_model=list[AnnouncementResponse],
    summary="获取当前生效的通知（公开，首页调用）",
)
async def get_active_announcements(db: DbSession):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    return await service.get_active()


@router.get(
    "",
    response_model=list[AnnouncementResponse],
    summary="获取全部通知（管理员）",
)
async def list_announcements(_admin: AdminRequired, db: DbSession):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    return await service.list_all()


@router.get(
    "/{announcement_id}",
    response_model=AnnouncementResponse,
    summary="获取单个通知（管理员）",
)
async def get_announcement(announcement_id: UUID, _admin: AdminRequired, db: DbSession):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    announcement = await service.get_by_id(str(announcement_id))
    if announcement is None:
        raise NotFoundError("通知不存在")
    return announcement


@router.post(
    "",
    response_model=AnnouncementResponse,
    summary="创建通知（管理员）",
)
async def create_announcement(req: AnnouncementCreate, _admin: AdminRequired, db: DbSession):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    return await service.create(**req.model_dump())


@router.put(
    "/{announcement_id}",
    response_model=AnnouncementResponse,
    summary="更新通知（管理员）",
)
async def update_announcement(
    announcement_id: UUID,
    req: AnnouncementUpdate,
    _admin: AdminRequired,
    db: DbSession,
):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    announcement = await service.update(str(announcement_id), **req.model_dump(exclude_unset=True))
    if announcement is None:
        raise NotFoundError("通知不存在")
    return announcement


@router.delete("/{announcement_id}", summary="删除通知（管理员）")
async def delete_announcement(announcement_id: UUID, _admin: AdminRequired, db: DbSession):
    repo = SqlAlchemyAnnouncementRepository(db)
    service = AnnouncementService(repo)
    ok = await service.delete(str(announcement_id))
    if not ok:
        raise NotFoundError("通知不存在")
    return {"deleted": True}
