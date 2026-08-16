"""add AgentTeams Element chat room URL

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa


revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agentteams_bridge_settings",
        sa.Column("element_url", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.alter_column("agentteams_bridge_settings", "element_url", server_default=None)


def downgrade() -> None:
    op.drop_column("agentteams_bridge_settings", "element_url")
