"""BLAST 工具 ORM 模型"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin


class BlastDatabaseModel(Base, TimestampMixin):
    """BLAST 数据库元数据表"""

    __tablename__ = "blast_databases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    db_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    db_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # nucl | prot
    source_species: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version_group: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_mb: Mapped[float] = mapped_column(Float, default=0.0)
    sequence_count: Mapped[int] = mapped_column(Integer, default=0)
    build_status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending | building | ready | failed | deprecated
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    build_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlastTaskModel(Base):
    """BLAST 查询任务记录表"""

    __tablename__ = "blast_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    db_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("blast_databases.id"), nullable=False
    )

    # 查询参数
    program: Mapped[str] = mapped_column(String(16), nullable=False)
    query_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    query_sequence: Mapped[str] = mapped_column(Text, nullable=False)
    query_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    evalue: Mapped[float] = mapped_column(Float, default=1e-5)
    max_target_seqs: Mapped[int] = mapped_column(Integer, default=10)
    word_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gapopen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gapextend: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 任务状态
    status: Mapped[str] = mapped_column(
        String(32), default="queued", index=True
    )  # queued | running | completed | failed | cancelled | cleaned
    progress: Mapped[int] = mapped_column(Integer, default=0)

    # 结果信息
    result_format: Mapped[str] = mapped_column(String(16), default="xml")
    result_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_hit_identity: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_hit_evalue: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 时间戳
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
