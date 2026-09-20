"""AI 可观测性指标 ORM 模型

- AiCallMetricModel：每次 AI 模型调用一行（provider/model/状态/耗时/token），
  由 core.ai_metrics 缓冲后台批量写入，支撑 Metrics 仪表盘的按日趋势聚合。
- AiMetricAlertModel：告警触发历史，兼作冷却去重依据（同一规则冷却期内不重复告警）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class AiCallMetricModel(Base, TimestampMixin):
    """AI 调用指标明细表（一次模型调用一行）。"""

    __tablename__ = "ai_call_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # success / error
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (Index("ix_ai_call_metrics_created_at", "created_at"),)


class AiMetricAlertModel(Base):
    """AI 指标告警历史（含冷却去重所需的规则与时间戳）。"""

    __tablename__ = "ai_metric_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule: Mapped[str] = mapped_column(String(64), index=True)  # error_rate / p95_latency / daily_cost
    level: Mapped[str] = mapped_column(String(20), default="warning")  # warning / error
    message: Mapped[str] = mapped_column(Text)
    metric_value: Mapped[float] = mapped_column(Float, default=0.0)
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=True
    )
