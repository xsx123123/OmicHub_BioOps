"""add skill_invocations table

技能调用记录：Agent 加载技能（use_skill）时落库，
供资源中心"最近调用 / 累计次数"展示与调用审计。

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_invocations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", sa.String(100), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("skill_version", sa.String(50), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(50), nullable=False, server_default="use_skill"),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_skill_invocations_skill_id", "skill_invocations", ["skill_id"])
    op.create_index("ix_skill_invocations_session_id", "skill_invocations", ["session_id"])
    op.create_index("ix_skill_invocations_user_id", "skill_invocations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_invocations_user_id", table_name="skill_invocations")
    op.drop_index("ix_skill_invocations_session_id", table_name="skill_invocations")
    op.drop_index("ix_skill_invocations_skill_id", table_name="skill_invocations")
    op.drop_table("skill_invocations")
