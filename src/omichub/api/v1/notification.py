"""通知提醒路由"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.services.notification_service import NotificationService
from omichub.core.exceptions import AuthorizationError, NotFoundError
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.repositories.notification_repository import (
    SqlAlchemyNotificationRepository,
)

router = APIRouter()


def _notification_to_dict(n) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "content": n.content,
        "level": n.level,
        "created_by": str(n.created_by),
        "is_global": n.is_global,
        "target_user_id": str(n.target_user_id) if n.target_user_id else None,
        "read_by": [str(uid) for uid in (n.read_by or [])],
        "expires_at": n.expires_at.isoformat() if n.expires_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


async def require_admin(current_user_id: CurrentUserId, db: DbSession) -> None:
    user = await db.get(UserModel, UUID(current_user_id))
    if user is None or user.role != "admin":
        raise AuthorizationError("需要管理员权限")


AdminRequired = Annotated[None, Depends(require_admin)]


class CreateNotificationRequest(BaseModel):
    title: str
    content: str
    level: str = "info"
    is_global: bool = True
    target_user_id: str | None = None
    expires_at: datetime | None = None


class UpdateNotificationRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    level: str | None = None
    is_global: bool | None = None
    target_user_id: str | None = None
    expires_at: datetime | None = None


class MarkReadResponse(BaseModel):
    id: str
    read_by: list[str]


@router.get("", summary="当前用户通知列表")
async def list_notifications(
    current_user_id: CurrentUserId,
    db: DbSession,
):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    notifications = await service.list_for_user(current_user_id)
    return [_notification_to_dict(n) for n in notifications]


@router.post("", summary="管理员发布通知")
async def create_notification(
    req: CreateNotificationRequest,
    _admin: AdminRequired,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    notification = await service.create(
        created_by=current_user_id,
        title=req.title,
        content=req.content,
        level=req.level,
        is_global=req.is_global,
        target_user_id=req.target_user_id,
        expires_at=req.expires_at,
    )
    return _notification_to_dict(notification)


@router.get("/all", summary="全部通知列表（管理员）")
async def list_all_notifications(_admin: AdminRequired, db: DbSession):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    notifications = await service.list_all()
    return [_notification_to_dict(n) for n in notifications]


@router.put("/{notification_id}", summary="管理员编辑通知")
async def update_notification(
    notification_id: UUID,
    req: UpdateNotificationRequest,
    _admin: AdminRequired,
    db: DbSession,
):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    notification = await service.update(str(notification_id), **req.model_dump(exclude_unset=True))
    if notification is None:
        raise NotFoundError("通知不存在")
    return _notification_to_dict(notification)


@router.patch("/{notification_id}/read", summary="标记通知已读")
async def mark_read(
    notification_id: UUID,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    notification = await service.mark_read(str(notification_id), current_user_id)
    if notification is None:
        raise NotFoundError("通知不存在")
    return _notification_to_dict(notification)


@router.delete("/{notification_id}", summary="管理员删除通知")
async def delete_notification(
    notification_id: UUID,
    _admin: AdminRequired,
    db: DbSession,
):
    repo = SqlAlchemyNotificationRepository(db)
    service = NotificationService(repo)
    ok = await service.delete(str(notification_id))
    if not ok:
        raise NotFoundError("通知不存在")
    return {"deleted": True}
