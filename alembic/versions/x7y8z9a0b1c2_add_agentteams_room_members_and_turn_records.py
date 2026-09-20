"""add AgentTeams room members and turn records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x7y8z9a0b1c2"
down_revision: str | None = "w6x7y8z9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("type", sa.String(length=64), nullable=False, server_default="general"),
    )
    op.add_column(
        "notifications",
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_notifications_type", "notifications", ["type"])
    op.create_table(
        "agentteams_room_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("invited_by", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "user_id", name="uq_agentteams_room_members_room_user"),
    )
    op.create_index("ix_agentteams_room_members_room_id", "agentteams_room_members", ["room_id"])
    op.create_index("ix_agentteams_room_members_user_id", "agentteams_room_members", ["user_id"])
    op.create_index("ix_agentteams_room_members_status", "agentteams_room_members", ["status"])
    op.create_index(
        "idx_agentteams_room_members_user_status",
        "agentteams_room_members",
        ["user_id", "status"],
    )
    op.create_table(
        "agentteams_turn_records",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("work_item_id", sa.String(length=128), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("call_seq", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("actor_user_id", sa.String(length=50), nullable=True),
        sa.Column("requester_ref", sa.String(length=50), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("s3_uri", sa.String(length=1024), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("s3_uri"),
        sa.UniqueConstraint(
            "case_id", "work_item_id", "round_number", "call_seq",
            name="uq_agentteams_turn_records_call",
        ),
    )
    for name, columns in (
        ("ix_agentteams_turn_records_case_id", ["case_id"]),
        ("ix_agentteams_turn_records_work_item_id", ["work_item_id"]),
        ("ix_agentteams_turn_records_actor_user_id", ["actor_user_id"]),
        ("ix_agentteams_turn_records_recorded_at", ["recorded_at"]),
        ("idx_agentteams_turn_records_case_work_round", ["case_id", "work_item_id", "round_number"]),
    ):
        op.create_index(name, "agentteams_turn_records", columns)


def downgrade() -> None:
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_column("notifications", "payload")
    op.drop_column("notifications", "type")
    op.drop_index("idx_agentteams_turn_records_case_work_round", table_name="agentteams_turn_records")
    op.drop_index("ix_agentteams_turn_records_recorded_at", table_name="agentteams_turn_records")
    op.drop_index("ix_agentteams_turn_records_actor_user_id", table_name="agentteams_turn_records")
    op.drop_index("ix_agentteams_turn_records_work_item_id", table_name="agentteams_turn_records")
    op.drop_index("ix_agentteams_turn_records_case_id", table_name="agentteams_turn_records")
    op.drop_table("agentteams_turn_records")
    op.drop_index("idx_agentteams_room_members_user_status", table_name="agentteams_room_members")
    op.drop_index("ix_agentteams_room_members_status", table_name="agentteams_room_members")
    op.drop_index("ix_agentteams_room_members_user_id", table_name="agentteams_room_members")
    op.drop_index("ix_agentteams_room_members_room_id", table_name="agentteams_room_members")
    op.drop_table("agentteams_room_members")
