"""add MAS runs, artifacts and durable event tables

Revision ID: x2y3z4a5b6c7
Revises: w1x2y3z4a5b6
Create Date: 2026-07-18 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x2y3z4a5b6c7"
down_revision: str | None = "w1x2y3z4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    json = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "mas_plans",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("plan_json", json, nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", uuid, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "mas_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("session_id", uuid),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", uuid),
        sa.Column("plan_id", uuid, nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("context_summary", json, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "mas_nodes",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("mas_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("intent", sa.String(256), nullable=False),
        sa.Column("depends_on", json, nullable=False),
        sa.Column("input_contract", json, nullable=False),
        sa.Column("output_contract", json, nullable=False),
        sa.Column("parameters", json, nullable=False),
        sa.Column("resources", json, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True),
        sa.Column("version", sa.Integer, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("run_id", "node_key", name="uq_mas_nodes_run_node_key"),
    )
    op.create_table(
        "mas_artifacts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("mas_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", uuid),
        sa.Column("logical_name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("workspace_path", sa.String(1024), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("summary", json, nullable=False),
        sa.Column("metadata", json, nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("storage_class", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("reference_count", sa.Integer, nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "run_id", "logical_name", "version", name="uq_mas_artifacts_run_name_version"
        ),
    )
    op.create_table(
        "mas_a2a_events",
        sa.Column("event_id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("mas_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", uuid),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", json, nullable=False),
        sa.Column("dedupe_key", sa.String(512), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_status", sa.String(32), nullable=False),
    )
    op.create_table(
        "mas_approvals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("mas_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", uuid),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("options", json, nullable=False),
        sa.Column("response", json),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_table(
        "mas_rework_guards",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("mas_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", uuid, nullable=False),
        sa.Column("input_artifact_id", uuid, nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=False),
        sa.Column("remediation_kind", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "run_id", "target_node_id", "fingerprint", name="uq_mas_rework_guards_fingerprint"
        ),
    )
    for table, column in (
        ("mas_runs", "user_id"),
        ("mas_runs", "status"),
        ("mas_nodes", "run_id"),
        ("mas_nodes", "status"),
        ("mas_artifacts", "run_id"),
        ("mas_artifacts", "sha256"),
        ("mas_a2a_events", "run_id"),
        ("mas_a2a_events", "published_at"),
        ("mas_approvals", "run_id"),
        ("mas_rework_guards", "run_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "mas_rework_guards",
        "mas_approvals",
        "mas_a2a_events",
        "mas_artifacts",
        "mas_nodes",
        "mas_runs",
        "mas_plans",
    ):
        op.drop_table(table)
