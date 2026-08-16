"""Durable state for the overdrive v2 orchestration runtime."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class OverdriveRunModel(Base, TimestampMixin):
    """Authoritative run snapshot; workspace files are readable projections only."""

    __tablename__ = "overdrive_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    root_request: Mapped[str] = mapped_column(Text, nullable=False)
    lead_planner_agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    research: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    manager_tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    assistant_instances: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    manager_reviews: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    artifact_index: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    control: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    event_cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_overdrive_runs_session_updated", "session_id", "updated_at"),
    )


class OverdriveEventModel(Base):
    """Monotonically sequenced domain event for cursor replay."""

    __tablename__ = "overdrive_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_overdrive_events_run_sequence"),
        UniqueConstraint("run_id", "dedupe_key", name="uq_overdrive_events_run_dedupe"),
        Index("ix_overdrive_events_run_occurred", "run_id", "occurred_at"),
    )


class OverdriveCommandModel(Base):
    """Idempotency record for user and scheduler commands."""

    __tablename__ = "overdrive_commands"

    command_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OverdriveTaskResultModel(Base):
    """Exactly-once result envelope for a task attempt."""

    __tablename__ = "overdrive_task_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id", "task_id", "attempt", name="uq_overdrive_task_results_attempt"
        ),
    )
