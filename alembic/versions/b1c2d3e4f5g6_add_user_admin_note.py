"""add user admin_note column

Revision ID: b1c2d3e4f5g6
Revises: a9b0c1d2e3f4
Create Date: 2026-07-02 11:10:00.000000

- users 表新增 admin_note（Text，可空），供管理员记录辅助信息
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5g6"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("admin_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "admin_note")
