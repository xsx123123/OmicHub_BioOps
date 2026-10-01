"""Durable Run event/outbox records."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class RunEventModel(Base, TimestampMixin):
    __tablename__ = "platform_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_platform_run_event_sequence"),
        Index("ix_platform_run_events_run_occurred", "run_id", "occurred_at"),
        Index("ix_platform_run_events_published", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    project_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    executor: Mapped[str] = mapped_column(String(64), nullable=False, default="snakemake")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False, default="task")
    progress: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
