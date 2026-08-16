"""MCP 域 ORM 模型 — MCP Server 注册表"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class MCPServerModel(Base, TimestampMixin):
    """MCP Server 注册表"""

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    transport: Mapped[str] = mapped_column(String(20), default="builtin")
    command: Mapped[str] = mapped_column(String(500), default="")
    args: Mapped[list[str]] = mapped_column(JSON, default=list)
    url: Mapped[str] = mapped_column(String(500), default="")
    env: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    package_registry: Mapped[str] = mapped_column("registry", String(50), default="default")
    working_dir: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="offline", index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    timeout: Mapped[int] = mapped_column(Integer, default=30)
    auto_restart: Mapped[bool] = mapped_column(Boolean, default=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    # --- MCP Builder 扩展（见 alembic h6i7j8k9l1m3）---
    pool: Mapped[str] = mapped_column(String(20), default="production", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    current_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    generation_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(20), default="approved")
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
