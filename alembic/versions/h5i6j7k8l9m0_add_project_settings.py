"""add_project_settings

WP3 任务 3：projects 表新增 nullable JSONB ``settings`` 列，
承载项目级设置（当前仅 ``research_mode`` 科研模式三开关），
创建会话时继承为会话 ``sandbox_meta.research_mode`` 初始值。

Revision ID: h5i6j7k8l9m0
Revises: g4b5c6d7e8f9a
Create Date: 2026-09-18

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h5i6j7k8l9m0"
down_revision = "g4b5c6d7e8f9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "settings")
