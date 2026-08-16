"""add unified storage fields to file_records

Revision ID: y3z4a5b6c7d8
Revises: x2y3z4a5b6c7
Create Date: 2026-07-21

为统一文件管理方案扩展 file_records 表：
- source: 文件来源模块（upload/pipeline/blast/enrichment 等）
- task_id: 产生此文件的任务 ID
- lifecycle_status: 生命周期状态（active/archived/pending_delete）
- cleanup_after: 自动清理时间
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "y3z4a5b6c7d8"
down_revision = "x2y3z4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_records",
        sa.Column("source", sa.String(32), nullable=False, server_default="upload"),
    )
    op.add_column(
        "file_records",
        sa.Column("task_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "file_records",
        sa.Column("lifecycle_status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "file_records",
        sa.Column("cleanup_after", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_file_records_source", "file_records", ["source"])
    op.create_index("ix_file_records_task_id", "file_records", ["task_id"])
    op.create_index("ix_file_records_lifecycle_status", "file_records", ["lifecycle_status"])
    op.create_index(
        "ix_file_records_lifecycle_cleanup",
        "file_records",
        ["lifecycle_status", "cleanup_after"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_records_lifecycle_cleanup", table_name="file_records")
    op.drop_index("ix_file_records_lifecycle_status", table_name="file_records")
    op.drop_index("ix_file_records_task_id", table_name="file_records")
    op.drop_index("ix_file_records_source", table_name="file_records")
    op.drop_column("file_records", "cleanup_after")
    op.drop_column("file_records", "lifecycle_status")
    op.drop_column("file_records", "task_id")
    op.drop_column("file_records", "source")
