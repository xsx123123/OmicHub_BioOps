"""MCP Builder ORM 模型 — 构建记录 / 版本历史 / 可见性 / 审核.

设计文档：docs/26.7.30/mcp_builder_framework.md §2
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cygnusx.infrastructure.database.base import Base, TimestampMixin


class MCPBuildModel(Base, TimestampMixin):
    """MCP 生成构建记录（Builder 核心表）"""

    __tablename__ = "mcp_builds"
    __table_args__ = (
        Index("idx_mcp_builds_server", "mcp_server_id"),
        Index("idx_mcp_builds_status", "status"),
        Index("idx_mcp_builds_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))

    # 需求与规划
    requirement: Mapped[str] = mapped_column(Text)
    plan_summary: Mapped[str] = mapped_column(Text, default="")
    search_queries: Mapped[list[Any]] = mapped_column(JSON, default=list)
    search_results: Mapped[list[Any]] = mapped_column(JSON, default=list)

    # 生成产物
    generated_code: Mapped[str] = mapped_column(Text, default="")
    runtime: Mapped[str] = mapped_column(String(20), default="python")
    safety_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 版本关联
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    parent_build_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("mcp_builds.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 状态流转
    status: Mapped[str] = mapped_column(String(30), default="planning")

    # 测试
    test_cases: Mapped[list[Any]] = mapped_column(JSON, default=list)
    test_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # 文档
    build_doc: Mapped[str] = mapped_column(Text, default="")
    architecture_doc: Mapped[str] = mapped_column(Text, default="")

    # 元数据
    model_used: Mapped[str] = mapped_column(String(50), default="")
    tokens_consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MCPVersionModel(Base, TimestampMixin):
    """MCP 版本历史快照"""

    __tablename__ = "mcp_versions"
    __table_args__ = (
        UniqueConstraint("mcp_server_id", "version", name="uq_mcp_versions_server_version"),
        Index("idx_mcp_versions_server", "mcp_server_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE")
    )
    build_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("mcp_builds.id", ondelete="SET NULL"),
        nullable=True,
    )

    version: Mapped[str] = mapped_column(String(20))
    version_tag: Mapped[str] = mapped_column(String(50), default="")
    is_major: Mapped[bool] = mapped_column(Boolean, default=False)

    code_snapshot: Mapped[str] = mapped_column(Text, default="")
    tools_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # 连接/行为配置快照（transport/command/args/url/env/registry/working_dir/timeout/
    # auto_restart/is_enabled/description），admin 手工更新与回滚场景据此完整还原
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 快照来源：builder（构建发布）/ admin（手工更新）/ rollback（回滚产生）/ publish（转正发布）
    source: Mapped[str] = mapped_column(String(20), default="builder")
    changelog: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class MCPVisibilityModel(Base):
    """用户级 MCP 可见性（细粒度共享授权）"""

    __tablename__ = "mcp_visibility"
    __table_args__ = (
        UniqueConstraint("mcp_server_id", "user_id", name="uq_mcp_visibility_server_user"),
        Index("idx_mcp_visibility_server", "mcp_server_id"),
        Index("idx_mcp_visibility_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))

    access_level: Mapped[str] = mapped_column(String(20), default="read")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MCPReviewModel(Base):
    """MCP 构建审核记录"""

    __tablename__ = "mcp_reviews"
    __table_args__ = (Index("idx_mcp_reviews_build", "build_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mcp_builds.id", ondelete="CASCADE")
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))

    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
