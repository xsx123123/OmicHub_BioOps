"""add studio share token columns

Revision ID: w1x2y3z4a5b6
Revises: v0w1x2y3z4a5
Create Date: 2026-07-17 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "w1x2y3z4a5b6"
down_revision: str | None = "v0w1x2y3z4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("share_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("share_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_chat_sessions_share_token_hash"),
        "chat_sessions",
        ["share_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_sessions_share_token_hash"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "shared_at")
    op.drop_column("chat_sessions", "share_expires_at")
    op.drop_column("chat_sessions", "share_token_hash")
