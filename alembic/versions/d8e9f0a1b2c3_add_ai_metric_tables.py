"""add ai metric tables

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_call_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("duration_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ai_call_metrics_created_at", "ai_call_metrics", ["created_at"]
    )

    op.create_table(
        "ai_metric_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule", sa.String(64), nullable=False, index=True),
        sa.Column("level", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("metric_value", sa.Float, nullable=False, server_default="0"),
        sa.Column("threshold", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("ai_metric_alerts")
    op.drop_index("ix_ai_call_metrics_created_at", table_name="ai_call_metrics")
    op.drop_table("ai_call_metrics")
