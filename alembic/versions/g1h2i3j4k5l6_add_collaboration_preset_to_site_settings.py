"""add collaboration preset to site settings

Revision ID: g1h2i3j4k5l6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("collaboration_preset", sa.String(length=16), nullable=False, server_default="custom"),
    )
    op.add_column(
        "site_settings",
        sa.Column("multi_expert_consultation_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "site_settings",
        sa.Column("unified_intent_router_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "unified_intent_router_enabled")
    op.drop_column("site_settings", "multi_expert_consultation_enabled")
    op.drop_column("site_settings", "collaboration_preset")
