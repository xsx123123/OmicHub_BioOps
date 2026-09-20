"""Studio 工作区归档包 ORM 模型（WP1 会话工作区生命周期）。

每个归档包对应 ``{storage_path}/studio-archive/{user_id}/`` 下的一个 tar.gz
及库表一行。幂等语义：同一 session_id 同时只允许一个未删除且未恢复的包
（部分唯一索引 uq_workspace_archives_session_active 保证， restored_at /
deleted_at 均 NULL 才视为 active）。
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base


class WorkspaceArchiveModel(Base):
    """Studio 会话工作区归档包记录。"""

    __tablename__ = "workspace_archives"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 平台侧包文件宿主绝对路径（LocalArchiveStorage 下位于 studio-archive/ 内）
    package_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # created_at + archive.retention_days；到期清理任务据此删除包文件
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 幂等键：一个会话同时最多一个 active 包；重复打包走"直接返回已有包"。
        # PG 部分唯一索引：仅对未删除未恢复的行生效。
        Index(
            "uq_workspace_archives_session_active",
            "session_id",
            unique=True,
            postgresql_where="deleted_at IS NULL AND restored_at IS NULL",
        ),
        Index("idx_workspace_archives_user_created", "user_id", "created_at"),
        Index("idx_workspace_archives_expires_at", "expires_at"),
    )
