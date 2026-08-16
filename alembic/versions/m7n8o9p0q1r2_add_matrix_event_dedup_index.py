"""add unique dedup index for persisted Matrix room events

Revision ID: m7n8o9p0q1r2
Revises: k6l7m8n9o0p1
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m7n8o9p0q1r2"
down_revision: str | Sequence[str] | None = "k6l7m8n9o0p1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_chat_messages_matrix_event"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "chat_messages",
        ["session_id", sa.text("(metadata_json->>'matrix_event_id')")],
        unique=True,
        postgresql_where=sa.text("metadata_json->>'matrix_event_id' IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="chat_messages")
