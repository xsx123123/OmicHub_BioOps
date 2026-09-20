"""文件域 ORM 模型 — 文件记录 / 上传会话 / 样本

所有表均强制 user_id 外键，仓储层查询统一带 WHERE user_id = ?，
彻底杜绝跨租户水平越权。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class FileRecordModel(Base, TimestampMixin):
    """文件记录 — 替代磁盘扫描，承载配额计量与生命周期

    storage_path 为相对 storage_path 根目录的相对路径，落盘绝对路径由
    FileService 拼接，避免环境迁移导致绝对路径失效。
    """

    __tablename__ = "file_records"
    __table_args__ = (
        Index("ix_file_records_lifecycle_cleanup", "lifecycle_status", "cleanup_after"),
        Index("ix_file_records_owner_scope_team_id", "owner_scope", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    file_type: Mapped[str] = mapped_column(String(32), default="other")
    # uploading(分片未合并) / active(可用) / archived(冷归档) / deleted(已删)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 用户自定义目录（相对 raw/ 的子路径，如 "projectA" 或 "projectA/sub1"，"" = raw 根）
    directory: Mapped[str] = mapped_column(String(500), default="", index=True)
    # 文件来源模块：upload / pipeline / blast / enrichment / fastq_qc / phylogenetic / download /
    # ai_chat / sandbox / report / studio / chat_sandbox / agentteams
    source: Mapped[str] = mapped_column(String(32), default="upload", server_default="upload", index=True)
    # 产生此文件的任务 ID（可为空，如手动上传）
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # 存储后端：local / s3；阶段 1 为双后端共存做准备
    storage_backend: Mapped[str] = mapped_column(String(16), default="local", server_default="local", index=True)
    # 生命周期状态：active / archived / pending_delete
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", index=True
    )
    # 自动清理时间（由 cleanup_policy 计算）
    cleanup_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 权属范围：personal（个人空间） / team（团队空间）
    owner_scope: Mapped[str] = mapped_column(
        String(20), default="personal", server_default="personal", nullable=False, index=True
    )
    # 团队空间文件归属的团队；个人文件为 NULL
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )


class UploadSessionModel(Base, TimestampMixin):
    """分块上传会话 — 持久化传输状态与分片 MD5，支持断点续传"""

    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_chunks: Mapped[int] = mapped_column(nullable=False)
    # 已上传分片：[{"index": 0, "md5": "..."}, ...]
    uploaded_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    file_md5: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # pending / uploading / merging / completed / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 上传目标目录（相对 raw/ 子路径），merge 时据此落盘
    directory: Mapped[str] = mapped_column(String(500), default="", server_default="")


class SampleModel(Base, TimestampMixin):
    """样本聚合根 — 关联用户与文件，供分析流水线读取"""

    __tablename__ = "samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    species: Mapped[str] = mapped_column(String(100), default="")
    tissue: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # Python 属性名不能用 metadata（SQLAlchemy Declarative 保留），DB 列名仍为 metadata
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    file_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class DirectoryModel(Base, TimestampMixin):
    """用户自定义目录 — 支持上传/下载归类与分析时按目录选数据。

    path 为相对用户数据根的相对路径（如 "projectA" / "projectA/sub1"），
    不含首尾斜杠。同一用户下 path 唯一。物理目录由 FileService 在落盘时创建。
    """

    __tablename__ = "user_directories"
    __table_args__ = (UniqueConstraint("user_id", "path", name="uq_user_directories_user_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 完整相对路径，如 "projectA" 或 "projectA/sub1"
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # 末级目录名，如 "sub1"（便于树展示）
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 父目录路径，如 "projectA"；根级目录 parent_path 为 NULL
    parent_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 系统默认目录（raw_data / workspace / temp）—— 不可删除/重命名
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
