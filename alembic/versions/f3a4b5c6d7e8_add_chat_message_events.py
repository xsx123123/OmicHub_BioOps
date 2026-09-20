"""add chat_message_events table (WP2 append-only event stream)

Revision ID: f3a4b5c6d7e8
Revises: e2e0wp1a1b2c
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2e0wp1a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WP2 消息过程态事件流：append-only，(message_id, seq) 联合主键保证
    # 消息内单调有序；不对 chat_messages / metadata_json 做任何破坏性改造。
    op.create_table(
        "chat_message_events",
        sa.Column("message_id", sa.String(50), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id", "seq", name="pk_chat_message_events"),
    )
    # 重建链路的便宜存在性判定（message_id limit 1）走主键前缀，无需额外索引


def downgrade() -> None:
    op.drop_table("chat_message_events")
