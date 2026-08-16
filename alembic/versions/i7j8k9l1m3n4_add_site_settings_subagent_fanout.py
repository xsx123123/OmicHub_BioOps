"""add site_settings.subagent_fanout_enabled

Revision ID: i7j8k9l1m3n4
Revises: h6i7j8k9l1m3
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision: str = "i7j8k9l1m3n4"
down_revision: str | None = "h6i7j8k9l1m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column(
            "subagent_fanout_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "subagent_fanout_enabled")
