"""add_image_id_to_terminal_sessions

为终端会话表增加 image_id 字段，用于记录会话启动时选择的镜像。

Revision ID: 3e76881cadbc
Revises: 0c574b584a21
Create Date: 2026-07-08 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3e76881cadbc'
down_revision: str | None = '0c574b584a21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('terminal_sessions', sa.Column('image_id', sa.String(length=32), nullable=True))
    op.create_index('ix_terminal_sessions_image_id', 'terminal_sessions', ['image_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_terminal_sessions_image_id', table_name='terminal_sessions')
    op.drop_column('terminal_sessions', 'image_id')
