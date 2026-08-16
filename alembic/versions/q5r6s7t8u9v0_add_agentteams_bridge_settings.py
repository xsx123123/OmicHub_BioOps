"""add agentteams bridge settings and merge active heads

Revision ID: q5r6s7t8u9v0
Revises: a7b8c9d0e1f2, p4q5r6s7t8u9
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q5r6s7t8u9v0"
down_revision: str | Sequence[str] | None = ("a7b8c9d0e1f2", "p4q5r6s7t8u9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agentteams_bridge_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("bridge_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("manager_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_steward_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("workflow_operator_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="10"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("agentteams_bridge_settings")
