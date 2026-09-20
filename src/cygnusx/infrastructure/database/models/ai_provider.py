"""AI Provider 配置 ORM 模型"""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class AIProviderConfigModel(Base, TimestampMixin):
    """AI Provider 配置表"""

    __tablename__ = "ai_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider_type: Mapped[str] = mapped_column(
        String(30), default="openai_compatible", nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    top_p: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    timeout: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    # 输入/输出/输入缓存/输出缓存单价（元 / M tokens），用于工作台会话费用估算；None = 未配置
    input_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_cache_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_cache_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
