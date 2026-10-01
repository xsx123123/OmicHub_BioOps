"""add platform Run shell for Snakemake plans"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_slug", sa.String(length=200), nullable=False),
        sa.Column("flow_id", sa.String(length=100), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(), nullable=False),
        sa.Column("plan_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "request_key", name="uq_platform_runs_user_request"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_platform_runs_status", "platform_runs", ["status"])
    op.create_index("ix_platform_runs_user_project_created", "platform_runs", ["user_id", "project_slug", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_runs_user_project_created", table_name="platform_runs")
    op.drop_index("ix_platform_runs_status", table_name="platform_runs")
    op.drop_table("platform_runs")
