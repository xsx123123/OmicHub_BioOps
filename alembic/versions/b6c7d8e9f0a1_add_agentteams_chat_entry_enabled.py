"""add agentteams chat entry enabled

Revision ID: b6c7d8e9f0a1
Revises: q5r6s7t8u9v0
Create Date: 2026-08-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b6c7d8e9f0a1"
down_revision = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("agentteams_chat_entry_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("site_settings", "agentteams_chat_entry_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("site_settings", "agentteams_chat_entry_enabled")
