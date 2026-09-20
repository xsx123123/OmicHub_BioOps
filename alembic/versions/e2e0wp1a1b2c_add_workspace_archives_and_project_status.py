"""add workspace_archives table and projects.status column

Revision ID: e2e0wp1a1b2c
Revises: s1t2u3v4w5x6
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e2e0wp1a1b2c"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WP1 会话工作区生命周期：归档包元数据表
    op.create_table(
        "workspace_archives",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("package_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 幂等键：一个会话同时最多一个 active 包（未删除且未恢复）
    op.create_index(
        "uq_workspace_archives_session_active",
        "workspace_archives",
        ["session_id"],
        unique=True,
        postgresql_where="deleted_at IS NULL AND restored_at IS NULL",
    )
    op.create_index(
        "idx_workspace_archives_user_created",
        "workspace_archives",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_workspace_archives_expires_at",
        "workspace_archives",
        ["expires_at"],
    )
    op.create_index(
        "idx_workspace_archives_session_id", "workspace_archives", ["session_id"]
    )
    op.create_index(
        "idx_workspace_archives_user_id", "workspace_archives", ["user_id"]
    )

    # 项目状态：active（NULL 视为进行中）/ completed / handed_over
    op.add_column(
        "projects",
        sa.Column("status", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "status")
    op.drop_table("workspace_archives")
