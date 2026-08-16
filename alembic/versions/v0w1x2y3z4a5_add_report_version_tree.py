"""add report version tree columns

OmicStudio 产物回填（artifact_register / 保存为新版本）：报告支持版本树。
- parent_id: 指向被优化的原报告（自引用 FK，原报告删除时置 NULL）
- version: 版本号，挂接版本树时为父版本+1，普通报告恒为 1

Revision ID: v0w1x2y3z4a5
Revises: u9v0w1x2y3z4
Create Date: 2026-07-16 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v0w1x2y3z4a5"
down_revision: str | None = "u9v0w1x2y3z4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        op.f("ix_reports_parent_id"),
        "reports",
        ["parent_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_reports_parent_id",
        "reports",
        "reports",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_reports_parent_id", "reports", type_="foreignkey")
    op.drop_index(op.f("ix_reports_parent_id"), table_name="reports")
    op.drop_column("reports", "version")
    op.drop_column("reports", "parent_id")
