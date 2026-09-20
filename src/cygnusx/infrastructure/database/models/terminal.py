"""终端域 ORM 模型 - 终端会话"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class TerminalSessionModel(Base, TimestampMixin):
    """终端会话表"""

    __tablename__ = "terminal_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    image_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    container_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    host_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="creating", index=True)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
