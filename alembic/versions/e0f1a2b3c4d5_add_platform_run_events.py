"""add durable platform Run event outbox"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_slug", sa.String(length=200), nullable=False),
        sa.Column("executor", sa.String(length=64), nullable=False, server_default="snakemake"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False, server_default="task"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rule", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["platform_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_platform_run_event_sequence"),
    )
    op.create_index("ix_platform_run_events_run_occurred", "platform_run_events", ["run_id", "occurred_at"])
    op.create_index("ix_platform_run_events_published", "platform_run_events", ["published_at"])
    op.create_index("ix_platform_run_events_task_id", "platform_run_events", ["task_id"])
    op.create_index("ix_platform_run_events_status", "platform_run_events", ["status"])


def downgrade() -> None:
    op.drop_table("platform_run_events")
