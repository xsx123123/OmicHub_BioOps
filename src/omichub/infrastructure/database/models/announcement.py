"""首页条幅通知 ORM 模型"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class AnnouncementModel(Base, TimestampMixin):
    """首页条幅通知表

    管理员后台配置的全局公告，前端首页取「生效中、优先级最高」的一条展示在 Hero 下方。

    - type: info / success / warning / feature，控制渐变配色与默认图标
    - start_time / end_time: 展示时间窗口；end_time 为空则永久
    - dismiss_behavior: daily（当天不再显示）/ forever（永久不再显示）/ none（不可关闭）
    - priority: 数字越大越优先；同优先级取最新创建
    """

    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="通知标题")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="通知描述")
    type: Mapped[str] = mapped_column(
        String(20), default="info", comment="info/success/warning/feature"
    )
    icon: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="emoji 或 lucide 图标名"
    )
    link: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="跳转链接（站内路径或外链）"
    )
    button_text: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="按钮文字，默认「立即查看」"
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="生效开始时间"
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效结束时间，空则永久"
    )
    dismiss_behavior: Mapped[str] = mapped_column(
        String(20), default="none", comment="daily/forever/none"
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="优先级，越大越优先")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
