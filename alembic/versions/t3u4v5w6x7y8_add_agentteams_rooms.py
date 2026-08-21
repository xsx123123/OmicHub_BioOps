"""add agentteams_rooms table (room-case decoupling, Part 2)"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "t3u4v5w6x7y8"
down_revision: str | Sequence[str] | None = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agentteams_rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", sa.String(length=80), nullable=False),
        sa.Column("owner_id", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="协作室会话"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("case_id", sa.String(length=80), nullable=True),
        sa.Column("matrix_room_id", sa.String(length=128), nullable=True),
        sa.Column("proposal", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("room_id", name="uq_agentteams_rooms_room_id"),
    )
    op.create_index("ix_agentteams_rooms_room_id", "agentteams_rooms", ["room_id"], unique=True)
    op.create_index("ix_agentteams_rooms_owner_id", "agentteams_rooms", ["owner_id"])
    op.create_index(
        "idx_agentteams_rooms_owner_updated", "agentteams_rooms", ["owner_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_agentteams_rooms_owner_updated", table_name="agentteams_rooms")
    op.drop_index("ix_agentteams_rooms_owner_id", table_name="agentteams_rooms")
    op.drop_index("ix_agentteams_rooms_room_id", table_name="agentteams_rooms")
    op.drop_table("agentteams_rooms")
