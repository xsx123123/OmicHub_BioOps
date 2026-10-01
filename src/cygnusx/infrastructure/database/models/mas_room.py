"""生物信息部门（MAS 房间）持久化模型：房间消息、run 账本与节点事件。

独立新表（手册红线 8）：不碰 chat_sessions / chat_messages / overdrive_* /
mas_*（旧 A2A 系统）任何结构。权威状态账本为 mas_room_runs / mas_room_events，
LangGraph checkpoint 只作图执行恢复载体。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class MASRoomMessageModel(Base, TimestampMixin):
    """部门房间消息：null agent_id = 用户发言；role 区分 user/assistant/mas_trace/plan_card。"""

    __tablename__ = "mas_room_messages"
    __table_args__ = (Index("ix_mas_room_messages_room_created", "room_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[str] = mapped_column(String(64), nullable=False, default="bioinfo-dept", index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class MASRoomRunModel(Base, TimestampMixin):
    """部门房间 run 权威快照（对齐 overdrive_runs 的账本角色，但无 chat_sessions 依赖）。"""

    __tablename__ = "mas_room_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(64), nullable=False, default="bioinfo-dept", index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="running", index=True)
    root_request: Mapped[str] = mapped_column(Text, nullable=False)
    orchestration_rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    plan_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MASRoomEventModel(Base):
    """run 节点级领域事件（单调 sequence，供审计与光标回放）。"""

    __tablename__ = "mas_room_events"
    __table_args__ = (
        Index("ix_mas_room_events_run_seq", "run_id", "sequence"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("mas_room_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
