"""add incremental memory settlement cursor and idempotency table"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n6o7p8q9r0s1"
down_revision: str | Sequence[str] | None = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("last_settled_message_id", sa.String(length=50), nullable=True))
    op.create_table(
        "memory_settlements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("range_key", sa.String(length=180), nullable=False),
        sa.Column("session_id", sa.String(length=50), nullable=False),
        sa.Column("start_message_id", sa.String(length=50), nullable=True),
        sa.Column("end_message_id", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("range_key", name="uq_memory_settlements_range_key"),
    )
    op.create_index("ix_memory_settlements_session_id", "memory_settlements", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_settlements_session_id", table_name="memory_settlements")
    op.drop_table("memory_settlements")
    op.drop_column("chat_sessions", "last_settled_message_id")
