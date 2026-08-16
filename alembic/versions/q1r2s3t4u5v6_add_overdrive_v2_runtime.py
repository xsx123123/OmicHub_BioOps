"""add durable overdrive v2 runtime

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-08-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "q1r2s3t4u5v6"
down_revision: str | None = "p0q1r2s3t4u5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json = postgresql.JSONB(astext_type=sa.Text())
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "overdrive_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(50),
            sa.ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("root_request", sa.Text(), nullable=False),
        sa.Column("lead_planner_agent_id", sa.String(128)),
        sa.Column("research", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plan", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("manager_tasks", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tasks", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("assistant_instances", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("manager_reviews", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifact_index", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("control", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("event_cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_overdrive_runs_session_id", "overdrive_runs", ["session_id"])
    op.create_index("ix_overdrive_runs_user_id", "overdrive_runs", ["user_id"])
    op.create_index("ix_overdrive_runs_status", "overdrive_runs", ["status"])
    op.create_index("ix_overdrive_runs_session_updated", "overdrive_runs", ["session_id", "updated_at"])

    op.create_table(
        "overdrive_events",
        sa.Column("event_id", uuid, primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("payload", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dedupe_key", sa.String(256)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "sequence", name="uq_overdrive_events_run_sequence"),
        sa.UniqueConstraint("run_id", "dedupe_key", name="uq_overdrive_events_run_dedupe"),
    )
    op.create_index("ix_overdrive_events_run_id", "overdrive_events", ["run_id"])
    op.create_index("ix_overdrive_events_event_type", "overdrive_events", ["event_type"])
    op.create_index("ix_overdrive_events_run_occurred", "overdrive_events", ["run_id", "occurred_at"])

    op.create_table(
        "overdrive_commands",
        sa.Column("command_id", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("command_type", sa.String(64), nullable=False),
        sa.Column("payload", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_overdrive_commands_run_id", "overdrive_commands", ["run_id"])

    op.create_table(
        "overdrive_task_results",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("overdrive_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("result", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "task_id", "attempt", name="uq_overdrive_task_results_attempt"),
    )
    op.create_index("ix_overdrive_task_results_run_id", "overdrive_task_results", ["run_id"])


def downgrade() -> None:
    op.drop_table("overdrive_task_results")
    op.drop_table("overdrive_commands")
    op.drop_table("overdrive_events")
    op.drop_table("overdrive_runs")
