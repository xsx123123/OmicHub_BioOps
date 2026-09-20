"""通知提醒仓储"""

import uuid
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.notification import NotificationModel


class SqlAlchemyNotificationRepository:
    """通知提醒仓储的 SQLAlchemy 实现"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationModel]:
        """获取指定用户可见且未过期的通知，按创建时间倒序"""
        now = datetime.now().astimezone()
        stmt = (
            select(NotificationModel)
            .where(
                (NotificationModel.is_global.is_(True))
                | (NotificationModel.target_user_id == user_id)
            )
            .where((NotificationModel.expires_at.is_(None)) | (NotificationModel.expires_at > now))
            .order_by(desc(NotificationModel.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[NotificationModel]:
        """全部通知（管理端），按创建时间倒序"""
        stmt = select(NotificationModel).order_by(desc(NotificationModel.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, notification_id: uuid.UUID) -> NotificationModel | None:
        return await self.session.get(NotificationModel, notification_id)

    async def create(self, notification: NotificationModel) -> NotificationModel:
        self.session.add(notification)
        await self.session.flush()
        await self.session.refresh(notification)
        return notification

    async def update(self, notification: NotificationModel) -> NotificationModel:
        """更新已加载的通知（session 自动跟踪 dirty 字段）"""
        await self.session.flush()
        await self.session.refresh(notification)
        return notification

    async def mark_read(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationModel | None:
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return None
        # 用新列表替换，避免就地 append 后赋值同对象导致 SQLAlchemy 不标记 dirty（JSONB 无可变跟踪），
        # 否则第二个用户标记已读时 old is value 短路、UPDATE 不发出，已读记录写不进库。
        # 统一存 str：JSONB 用默认 json 编码器，UUID 不可序列化会抛
        # "Object of type UUID is not JSON serializable"；存 str 也与
        # _notification_to_dict / 前端 read_by.includes(uid) 口径一致。
        read_by = [str(uid) for uid in (notification.read_by or [])]
        uid_str = str(user_id)
        if uid_str not in read_by:
            read_by.append(uid_str)
            notification.read_by = read_by
            await self.session.flush()
            await self.session.refresh(notification)
        return notification

    async def delete(self, notification_id: uuid.UUID) -> bool:
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return False
        await self.session.delete(notification)
        await self.session.flush()
        return True
