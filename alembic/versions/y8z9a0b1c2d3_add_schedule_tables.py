"""add persistent schedules and reminder deliveries"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "y8z9a0b1c2d3"
down_revision: str | None = "x7y8z9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recurrence_rule", sa.String(500), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_schedules_user_status", "schedules", ["user_id", "status"])
    op.create_index("idx_schedules_next_fire", "schedules", ["next_fire_at", "status"])
    op.create_index("idx_schedules_workspace", "schedules", ["workspace_id", "status"])

    op.create_table(
        "schedule_occurrences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_key", sa.String(64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "occurrence_key", name="uq_schedule_occurrences_key"),
    )
    op.create_index("idx_occurrences_schedule", "schedule_occurrences", ["schedule_id", "scheduled_at"])

    op.create_table(
        "reminder_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False, server_default="in_app"),
        sa.Column("reminder_offset_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["occurrence_id"], ["schedule_occurrences.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrence_id", "channel", "reminder_offset_minutes", name="uq_reminder_delivery"),
    )
    op.create_index("idx_deliveries_due", "reminder_deliveries", ["due_at", "status"])
    op.create_index("idx_deliveries_user", "reminder_deliveries", ["user_id", "status", "created_at"])
    op.create_index("idx_deliveries_retry", "reminder_deliveries", ["next_retry_at", "status", "attempt_count"])


def downgrade() -> None:
    op.drop_index("idx_deliveries_retry", table_name="reminder_deliveries")
    op.drop_index("idx_deliveries_user", table_name="reminder_deliveries")
    op.drop_index("idx_deliveries_due", table_name="reminder_deliveries")
    op.drop_table("reminder_deliveries")
    op.drop_index("idx_occurrences_schedule", table_name="schedule_occurrences")
    op.drop_table("schedule_occurrences")
    op.drop_index("idx_schedules_workspace", table_name="schedules")
    op.drop_index("idx_schedules_next_fire", table_name="schedules")
    op.drop_index("idx_schedules_user_status", table_name="schedules")
    op.drop_table("schedules")
