"""首页条幅通知仓储"""

import uuid
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.announcement import AnnouncementModel


class SqlAlchemyAnnouncementRepository:
    """首页条幅通知仓储的 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[AnnouncementModel]:
        """全部通知，按优先级倒序、创建时间倒序"""
        stmt = select(AnnouncementModel).order_by(
            desc(AnnouncementModel.priority),
            desc(AnnouncementModel.created_at),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self) -> list[AnnouncementModel]:
        """当前生效的通知（启用且在时间窗口内），按优先级倒序、创建时间倒序"""
        now = datetime.now().astimezone()
        stmt = (
            select(AnnouncementModel)
            .where(AnnouncementModel.is_enabled.is_(True))
            .where(AnnouncementModel.start_time <= now)
            .where((AnnouncementModel.end_time.is_(None)) | (AnnouncementModel.end_time >= now))
            .order_by(
                desc(AnnouncementModel.priority),
                desc(AnnouncementModel.created_at),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, announcement_id: uuid.UUID) -> AnnouncementModel | None:
        return await self.session.get(AnnouncementModel, announcement_id)

    async def create(self, announcement: AnnouncementModel) -> AnnouncementModel:
        self.session.add(announcement)
        await self.session.flush()
        await self.session.refresh(announcement)
        return announcement

    async def update(self, announcement: AnnouncementModel) -> AnnouncementModel:
        """更新已加载的通知（session 自动跟踪 dirty 字段）"""
        await self.session.flush()
        await self.session.refresh(announcement)
        return announcement

    async def delete(self, announcement_id: uuid.UUID) -> bool:
        announcement = await self.get_by_id(announcement_id)
        if announcement is None:
            return False
        await self.session.delete(announcement)
        await self.session.flush()
        return True
