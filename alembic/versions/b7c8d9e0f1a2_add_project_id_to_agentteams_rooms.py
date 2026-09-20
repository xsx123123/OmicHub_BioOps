"""add project_id to agentteams_rooms

协作室房间纳入项目维度：project_id 可空（手动创建可不绑项目），
供项目总览按项目聚合房间列表。

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agentteams_rooms",
        sa.Column("project_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_agentteams_rooms_project_id", "agentteams_rooms", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agentteams_rooms_project_id", table_name="agentteams_rooms")
    op.drop_column("agentteams_rooms", "project_id")
