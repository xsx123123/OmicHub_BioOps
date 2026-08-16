"""merge heads and add user lab_group

Revision ID: 7f8e9d0c1b2a
Revises: b2c3d4e5f6a7, c2d3e4f5a6b7
Create Date: 2026-07-02 20:00:00.000000

合并已有两个 head（b2c3d4e5f6a7 / c2d3e4f5a6b7），并为 users 表新增 lab_group 列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f8e9d0c1b2a'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', 'c2d3e4f5a6b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 所属课题组：用户归属的研究组/实验室，用于资产看板分组与检索；可空
    op.add_column(
        'users',
        sa.Column('lab_group', sa.String(length=120), nullable=True),
    )
    op.create_index('ix_users_lab_group', 'users', ['lab_group'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_users_lab_group', table_name='users')
    op.drop_column('users', 'lab_group')
