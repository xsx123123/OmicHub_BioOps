"""报告中心 ORM 模型"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class ReportModel(Base, TimestampMixin):
    """分析报告表"""

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    flow_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    flow_name: Mapped[str] = mapped_column(String(100), default="")
    flow_version: Mapped[str] = mapped_column(String(20), default="")
    flow_icon: Mapped[str] = mapped_column(String(50), default="")

    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="generating", index=True)

    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[int] = mapped_column(Integer, default=0)  # 秒

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)

    # 版本树（OmicStudio 产物回填）：parent_id 指向被优化的原报告，version 为父版本+1
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")

    files: Mapped[list["ReportFileModel"]] = relationship(
        "ReportFileModel", back_populates="report", cascade="all, delete-orphan"
    )


class ReportFileModel(Base, TimestampMixin):
    """报告文件表"""

    __tablename__ = "report_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # html/pdf/png/zip/csv
    size: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(500), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    report: Mapped["ReportModel"] = relationship("ReportModel", back_populates="files")
