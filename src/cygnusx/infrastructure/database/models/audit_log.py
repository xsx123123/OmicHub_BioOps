"""审计日志 ORM 模型

记录写操作（POST/PUT/PATCH/DELETE）的请求审计：谁、在何时、对什么资源、
做了什么、结果如何。由 AuditMiddleware 自动写入，供管理员审查与追溯。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base


class AuditLogModel(Base):
    """审计日志表"""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 操作者；未登录请求（如登录失败）为 NULL
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str] = mapped_column(String(10), index=True)  # POST/PUT/PATCH/DELETE
    path: Mapped[str] = mapped_column(String(500), index=True)
    # 从路径启发式解析，如 /api/v1/tasks/{id} → resource_type=task, resource_id={id}
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, server_default=func.now()
    )
