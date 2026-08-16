"""add storage_backend to file_records

Revision ID: d481d0a3b1c6
Revises: z4a5b6c7d8e9
Create Date: 2026-08-15

阶段 1：为 file_records 增加 storage_backend 字段，支撑 local/s3 双后端共存。
"""

import sqlalchemy as sa
from alembic import op

revision = "d481d0a3b1c6"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_records",
        sa.Column(
            "storage_backend",
            sa.String(16),
            nullable=False,
            server_default="local",
        ),
    )
    op.create_index(
        "ix_file_records_storage_backend",
        "file_records",
        ["storage_backend"],
    )
    # 回填存量行（理论上默认值已处理，显式执行更稳妥）
    op.execute("UPDATE file_records SET storage_backend = 'local' WHERE storage_backend IS NULL")


def downgrade() -> None:
    op.drop_index("ix_file_records_storage_backend", table_name="file_records")
    op.drop_column("file_records", "storage_backend")
