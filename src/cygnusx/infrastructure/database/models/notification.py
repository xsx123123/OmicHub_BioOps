"""通知提醒 ORM 模型"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class NotificationModel(Base, TimestampMixin):
    """通知提醒表

    - is_global=True：所有用户可见。
    - target_user_id 非空：仅指定用户可见。
    - read_by 记录已读用户 ID 列表。
    - expires_at 为空则永不过期。
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(20), default="info")  # info / warning / error
    type: Mapped[str] = mapped_column(String(64), default="general", nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    is_global: Mapped[bool] = mapped_column(Boolean, default=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    # 已读用户 ID 列表（存 str 形式的 UUID，便于 JSONB 序列化与前后端口径统一）
    read_by: Mapped[list[str]] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
