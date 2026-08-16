"""add chat handoff events

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_handoff_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("source_agent_id", sa.String(length=50), nullable=False),
        sa.Column("target_agent_id", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("handoff_summary", sa.Text(), nullable=False),
        sa.Column("user_intent", sa.Text(), nullable=False),
        sa.Column(
            "artifacts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("hop_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_handoff_events_session_id", "chat_handoff_events", ["session_id"])
    op.create_index("ix_chat_handoff_events_user_id", "chat_handoff_events", ["user_id"])
    op.create_index(
        "idx_chat_handoff_session_created",
        "chat_handoff_events",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("chat_handoff_events")
