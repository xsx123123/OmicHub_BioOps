"""联网搜索服务商配置 ORM 模型。"""

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class SearchProviderConfigModel(Base, TimestampMixin):
    __tablename__ = "search_provider_configs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
