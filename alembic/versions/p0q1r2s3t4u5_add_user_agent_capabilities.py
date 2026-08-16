"""add per-user agent capability selections

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-08-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p0q1r2s3t4u5"
down_revision = "o9p0q1r2s3t4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_agent_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(length=50),
            sa.ForeignKey("agent_templates.agent_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_provider_configs.id"),
            nullable=True,
        ),
        sa.Column(
            "mcp_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "skill_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "agent_id", name="uq_user_agent_capabilities_user_agent"),
    )
    op.create_index("ix_user_agent_capabilities_user_id", "user_agent_capabilities", ["user_id"])
    op.create_index("idx_user_agent_capabilities_agent", "user_agent_capabilities", ["agent_id"])


def downgrade() -> None:
    op.drop_index("idx_user_agent_capabilities_agent", table_name="user_agent_capabilities")
    op.drop_index("ix_user_agent_capabilities_user_id", table_name="user_agent_capabilities")
    op.drop_table("user_agent_capabilities")
