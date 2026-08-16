"""add user_directories table and file_records.directory column

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5g6
Create Date: 2026-07-02 15:00:00.000000

- 新建 user_directories 表（用户自定义目录，path 唯一）
- file_records 加 directory 列（相对 raw/ 子路径，默认 "" = 根）+ 索引
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== user_directories 表 =====
    op.create_table(
        "user_directories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("parent_path", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "path", name="uq_user_directories_user_path"),
    )
    op.create_index("ix_user_directories_user_id", "user_directories", ["user_id"], unique=False)

    # ===== file_records.directory 列 =====
    op.add_column(
        "file_records",
        sa.Column("directory", sa.String(length=500), nullable=False, server_default=sa.text("''")),
    )
    op.create_index("ix_file_records_directory", "file_records", ["directory"], unique=False)

    # ===== upload_sessions.directory 列（上传目标目录，merge 时据此落盘）=====
    op.add_column(
        "upload_sessions",
        sa.Column("directory", sa.String(length=500), nullable=False, server_default=sa.text("''")),
    )


def downgrade() -> None:
    op.drop_column("upload_sessions", "directory")
    op.drop_index("ix_file_records_directory", table_name="file_records")
    op.drop_column("file_records", "directory")
    op.drop_index("ix_user_directories_user_id", table_name="user_directories")
    op.drop_table("user_directories")
