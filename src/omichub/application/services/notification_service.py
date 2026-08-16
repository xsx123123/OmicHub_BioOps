"""通知提醒应用服务"""

from datetime import datetime
from uuid import UUID

from omichub.infrastructure.database.models.notification import NotificationModel
from omichub.infrastructure.database.repositories.notification_repository import (
    SqlAlchemyNotificationRepository,
)


class NotificationService:
    """通知提醒应用服务"""

    def __init__(self, repo: SqlAlchemyNotificationRepository):
        self._repo = repo

    async def list_for_user(self, user_id: str) -> list[NotificationModel]:
        return await self._repo.list_for_user(UUID(user_id))

    async def list_all(self) -> list[NotificationModel]:
        """管理端：全部通知"""
        return await self._repo.list_all()

    async def update(self, notification_id: str, **kwargs) -> NotificationModel | None:
        notification = await self._repo.get_by_id(UUID(notification_id))
        if notification is None:
            return None
        # target_user_id 是 UUID 字段，传字符串需转换
        if "target_user_id" in kwargs:
            tuid = kwargs["target_user_id"]
            kwargs["target_user_id"] = UUID(tuid) if tuid else None
        for key, value in kwargs.items():
            setattr(notification, key, value)
        return await self._repo.update(notification)

    async def create(
        self,
        created_by: str,
        title: str,
        content: str,
        level: str = "info",
        is_global: bool = True,
        target_user_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> NotificationModel:
        notification = NotificationModel(
            title=title,
            content=content,
            level=level,
            created_by=UUID(created_by),
            is_global=is_global,
            target_user_id=UUID(target_user_id) if target_user_id else None,
            expires_at=expires_at,
            read_by=[],
        )
        return await self._repo.create(notification)

    async def mark_read(self, notification_id: str, user_id: str) -> NotificationModel | None:
        return await self._repo.mark_read(UUID(notification_id), UUID(user_id))

    async def delete(self, notification_id: str) -> bool:
        return await self._repo.delete(UUID(notification_id))
