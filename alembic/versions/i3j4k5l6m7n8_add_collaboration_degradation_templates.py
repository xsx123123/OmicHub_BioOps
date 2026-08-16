"""add collaboration degradation templates

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: str | Sequence[str] | None = "h2i3j4k5l6m7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column("collaboration_degradation_locale", sa.String(length=8), nullable=False, server_default="zh-CN"),
    )
    op.add_column(
        "site_settings",
        sa.Column("collaboration_degradation_template_zh", sa.String(length=1000), nullable=False, server_default=""),
    )
    op.add_column(
        "site_settings",
        sa.Column("collaboration_degradation_template_en", sa.String(length=1000), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "collaboration_degradation_template_en")
    op.drop_column("site_settings", "collaboration_degradation_template_zh")
    op.drop_column("site_settings", "collaboration_degradation_locale")
