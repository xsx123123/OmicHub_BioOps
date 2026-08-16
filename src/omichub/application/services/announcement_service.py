"""首页条幅通知应用服务"""

import uuid

from omichub.infrastructure.database.models.announcement import AnnouncementModel
from omichub.infrastructure.database.repositories.announcement_repository import (
    SqlAlchemyAnnouncementRepository,
)


class AnnouncementService:
    """首页条幅通知应用服务"""

    def __init__(self, repo: SqlAlchemyAnnouncementRepository):
        self._repo = repo

    async def list_all(self) -> list[AnnouncementModel]:
        """管理端：全部通知"""
        return await self._repo.list_all()

    async def get_active(self) -> list[AnnouncementModel]:
        """公开：当前生效通知列表（按优先级倒序）"""
        return await self._repo.get_active()

    async def get_active_one(self) -> AnnouncementModel | None:
        """公开：取当前生效的最高优先级一条"""
        items = await self._repo.get_active()
        return items[0] if items else None

    async def get_by_id(self, announcement_id: str) -> AnnouncementModel | None:
        return await self._repo.get_by_id(uuid.UUID(announcement_id))

    async def create(self, **kwargs) -> AnnouncementModel:
        announcement = AnnouncementModel(**kwargs)
        return await self._repo.create(announcement)

    async def update(self, announcement_id: str, **kwargs) -> AnnouncementModel | None:
        announcement = await self._repo.get_by_id(uuid.UUID(announcement_id))
        if announcement is None:
            return None
        # 直接赋值 kwargs 中所有字段（route 层用 exclude_unset 仅传需更新字段），
        # 这样允许把 end_time 等显式置 None（表示永久），不会被 None 跳过。
        for key, value in kwargs.items():
            setattr(announcement, key, value)
        return await self._repo.update(announcement)

    async def delete(self, announcement_id: str) -> bool:
        return await self._repo.delete(uuid.UUID(announcement_id))
