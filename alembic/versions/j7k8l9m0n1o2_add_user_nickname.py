"""add user nickname column

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-07-03 10:00:00.000000

- users 表新增 nickname（String(120)，可空），作为展示用别名，空则前端降级为用户名
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j7k8l9m0n1o2"
down_revision: str | Sequence[str] | None = "i6j7k8l9m0n1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("nickname", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "nickname")
