"""add chat session title lock

Revision ID: a7b8c9d0e1f2
Revises: a5b6c7d8e9f0
Create Date: 2026-07-23 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "a5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'chat_sessions' AND column_name = 'title_locked'"
        )
    ).scalar()
    if result:
        return

    op.add_column(
        "chat_sessions",
        sa.Column("title_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("chat_sessions", "title_locked", server_default=None)


def downgrade() -> None:
    op.drop_column("chat_sessions", "title_locked")
