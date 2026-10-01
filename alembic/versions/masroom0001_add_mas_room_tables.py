"""add mas room tables (bioinfo department)

Revision ID: masroom0001
Revises: cacheprice0001
Create Date: 2026-09-21

生物信息部门（MAS 房间）独立新表：房间消息、run 账本与节点事件。
不碰 chat_sessions / chat_messages / overdrive_* / mas_*（旧 A2A）任何结构。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "masroom0001"
down_revision = "cacheprice0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mas_room_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", sa.String(64), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), nullable=True, index=True),
        sa.Column("agent_id", sa.String(128), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_mas_room_messages_room_created", "mas_room_messages", ["room_id", "created_at"]
    )

    op.create_table(
        "mas_room_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("room_id", sa.String(64), nullable=False, index=True),
        sa.Column("user_id", sa.String(50), nullable=False, index=True),
        sa.Column("status", sa.String(48), nullable=False, server_default="running", index=True),
        sa.Column("root_request", sa.Text(), nullable=False),
        sa.Column("orchestration_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_plan", JSONB(), nullable=True),
        sa.Column("plan_decision", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "mas_room_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("mas_room_runs.run_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False, index=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_mas_room_events_run_seq", "mas_room_events", ["run_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_mas_room_events_run_seq", table_name="mas_room_events")
    op.drop_table("mas_room_events")
    op.drop_table("mas_room_runs")
    op.drop_index("ix_mas_room_messages_room_created", table_name="mas_room_messages")
    op.drop_table("mas_room_messages")
