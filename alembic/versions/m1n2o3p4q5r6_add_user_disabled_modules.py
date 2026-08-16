"""add_user_disabled_modules

用户模块权限管控：users 表新增 disabled_modules（被禁用模块 key 列表，JSON 数组，默认空）

Revision ID: m1n2o3p4q5r6
Revises: i7j8k9l1m3n4
Create Date: 2026-07-30 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'm1n2o3p4q5r6'
down_revision: str | None = 'i7j8k9l1m3n4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('disabled_modules', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column('users', 'disabled_modules')
