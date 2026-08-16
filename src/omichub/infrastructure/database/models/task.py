"""任务域 ORM 模型"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from omichub.domain.task.value_objects import ExecutionMode, TaskStatus
from omichub.infrastructure.database.base import Base, TimestampMixin


class TaskModel(Base, TimestampMixin):
    """任务表"""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[str] = mapped_column(
        String(100), index=True, nullable=False
    )  # 对应流程 YAML 中 meta.id
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING.value, index=True)
    execution_mode: Mapped[str] = mapped_column(String(20), default=ExecutionMode.LOCAL.value)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    work_dir: Mapped[str] = mapped_column(String(500), default="")
    result_path: Mapped[str] = mapped_column(String(500), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # 提交时由 len(sample_sheet) 落库
    logs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
