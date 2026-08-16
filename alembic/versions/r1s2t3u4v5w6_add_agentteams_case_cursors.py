"""add AgentTeams Case cursor state

Revision ID: r1s2t3u4v5w6
Revises: q1r2s3t4u5v6
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r1s2t3u4v5w6"
down_revision: str | None = "q1r2s3t4u5v6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agentteams_case_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "session_id",
            sa.String(length=50),
            sa.ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("event_cursor", sa.String(length=128), nullable=True),
        sa.Column(
            "notified_statuses",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "case_id", name="uq_agentteams_case_cursors_session_case"),
    )
    op.create_index(
        "ix_agentteams_case_cursors_session_id",
        "agentteams_case_cursors",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agentteams_case_cursors_session_id", table_name="agentteams_case_cursors")
    op.drop_table("agentteams_case_cursors")
