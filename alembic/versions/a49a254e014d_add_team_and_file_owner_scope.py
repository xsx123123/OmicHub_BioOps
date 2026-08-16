"""add team and file owner scope

Revision ID: a49a254e014d
Revises: d481d0a3b1c6
Create Date: 2026-08-15

阶段 3.1：新增 team / team_members 表，并在 file_records 上增加
owner_scope / team_id 字段，支撑团队协作空间文件全局可见性。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "a49a254e014d"
down_revision: str | None = "d481d0a3b1c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== teams =====
    op.create_table(
        "teams",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== team_members =====
    op.create_table(
        "team_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="reader"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    # ===== file_records owner_scope / team_id =====
    op.add_column(
        "file_records",
        sa.Column(
            "owner_scope",
            sa.String(20),
            nullable=False,
            server_default="personal",
            index=True,
        ),
    )
    op.add_column(
        "file_records",
        sa.Column(
            "team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    op.create_index(
        "ix_file_records_owner_scope_team_id",
        "file_records",
        ["owner_scope", "team_id"],
    )
    # 回填存量行（默认值已处理，显式执行更稳妥）
    op.execute("UPDATE file_records SET owner_scope = 'personal' WHERE owner_scope IS NULL")


def downgrade() -> None:
    op.drop_index("ix_file_records_owner_scope_team_id", table_name="file_records")
    op.drop_column("file_records", "team_id")
    op.drop_column("file_records", "owner_scope")

    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_table("teams")
