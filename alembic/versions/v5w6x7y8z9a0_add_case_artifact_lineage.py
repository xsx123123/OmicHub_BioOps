"""add case artifact lineage tables (case_artifact_versions / case_artifact_dependencies, F1)

产物血缘：产物登记强制写 version 行（checksum + environment_snapshot +
producing_event_id 复用审计因果链），依赖边构成 case 内产物 DAG。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v5w6x7y8z9a0"
down_revision: str | Sequence[str] | None = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_artifact_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("artifact_id", sa.String(length=512), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("producing_event_id", sa.String(length=128), nullable=True),
        sa.Column("work_item_id", sa.String(length=128), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column(
            "environment_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "case_id",
            "artifact_id",
            "version_no",
            name="uq_case_artifact_versions_case_artifact_version",
        ),
    )
    op.create_index("ix_case_artifact_versions_case_id", "case_artifact_versions", ["case_id"])
    op.create_index(
        "ix_case_artifact_versions_checksum", "case_artifact_versions", ["checksum_sha256"]
    )
    op.create_table(
        "case_artifact_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("downstream_artifact_id", sa.String(length=512), nullable=False),
        sa.Column("upstream_artifact_id", sa.String(length=512), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False, server_default="input_to"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "case_id",
            "downstream_artifact_id",
            "upstream_artifact_id",
            "relation",
            name="uq_case_artifact_dependencies_edge",
        ),
    )
    op.create_index(
        "ix_case_artifact_dependencies_case_id", "case_artifact_dependencies", ["case_id"]
    )
    op.create_index(
        "ix_case_artifact_dependencies_upstream",
        "case_artifact_dependencies",
        ["case_id", "upstream_artifact_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_case_artifact_dependencies_upstream", table_name="case_artifact_dependencies")
    op.drop_index("ix_case_artifact_dependencies_case_id", table_name="case_artifact_dependencies")
    op.drop_table("case_artifact_dependencies")
    op.drop_index("ix_case_artifact_versions_checksum", table_name="case_artifact_versions")
    op.drop_index("ix_case_artifact_versions_case_id", table_name="case_artifact_versions")
    op.drop_table("case_artifact_versions")
