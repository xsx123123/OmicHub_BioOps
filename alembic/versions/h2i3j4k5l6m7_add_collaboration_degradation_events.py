"""add collaboration degradation events

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "h2i3j4k5l6m7"
down_revision: str | Sequence[str] | None = "g1h2i3j4k5l6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collaboration_degradation_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("message_id", sa.String(length=50), nullable=True),
        sa.Column("user_id", sa.String(length=50), nullable=True),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_collab_degradation_intent_created",
        "collaboration_degradation_events",
        ["intent", "created_at"],
    )
    op.create_index(
        "idx_collab_degradation_session_created",
        "collaboration_degradation_events",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_collaboration_degradation_events_session_id",
        "collaboration_degradation_events",
        ["session_id"],
    )
    op.create_index(
        "ix_collaboration_degradation_events_message_id",
        "collaboration_degradation_events",
        ["message_id"],
    )
    op.create_index(
        "ix_collaboration_degradation_events_user_id",
        "collaboration_degradation_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("collaboration_degradation_events")
