"""add chat message feedbacks

Revision ID: k6l7m8n9o0p1
Revises: l6m7n8o9p0q1
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID

revision: str = "k6l7m8n9o0p1"
down_revision: str | Sequence[str] | None = "l6m7n8o9p0q1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_message_feedbacks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_id", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("message_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("rating", sa.String(length=10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_chat_message_feedbacks_feedback_id",
        "chat_message_feedbacks",
        ["feedback_id"],
        unique=True,
    )
    op.create_index(
        "ix_chat_message_feedbacks_session_id",
        "chat_message_feedbacks",
        ["session_id"],
    )
    op.create_index(
        "ix_chat_message_feedbacks_message_id",
        "chat_message_feedbacks",
        ["message_id"],
    )
    op.create_index(
        "ix_chat_message_feedbacks_user_id",
        "chat_message_feedbacks",
        ["user_id"],
    )
    op.create_index(
        "idx_chat_feedbacks_message_user",
        "chat_message_feedbacks",
        ["message_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_chat_feedbacks_created",
        "chat_message_feedbacks",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("chat_message_feedbacks")
