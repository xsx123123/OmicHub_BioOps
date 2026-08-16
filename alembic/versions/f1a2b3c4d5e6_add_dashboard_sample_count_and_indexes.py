"""add dashboard sample_count and trend indexes

Revision ID: f1a2b3c4d5e6
Revises: e4f5a6b7c8d9
Create Date: 2026-06-30 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仪表板样本计数：提交时由 len(sample_sheet) 一次性落库
    op.add_column(
        'tasks',
        sa.Column(
            'sample_count',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    # 趋势查询按 created_at 范围扫描 + 按日聚合，原表无 created_at 索引
    op.create_index('ix_tasks_created_at', 'tasks', ['created_at'], unique=False)
    # 个人趋势：WHERE user_id=? AND created_at>=? GROUP BY date(created_at)
    op.create_index(
        'ix_tasks_user_id_created_at',
        'tasks',
        ['user_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_tasks_user_id_created_at', table_name='tasks')
    op.drop_index('ix_tasks_created_at', table_name='tasks')
    op.drop_column('tasks', 'sample_count')
