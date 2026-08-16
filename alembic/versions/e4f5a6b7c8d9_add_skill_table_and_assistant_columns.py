"""add_skill_table_and_assistant_columns

1. 新建 skills 表（纯 prompt 注入型技能）
2. ai_conversations 加 assistant_id（会话绑定助手）
3. chat_assistants 加 is_default（默认助手标记）

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-28 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: str | None = 'd3e4f5a6b7c8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. skills 表
    op.create_table('skills',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('skill_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('tool_definition', sa.JSON(), nullable=True),
        sa.Column('icon', sa.String(length=10), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill_id'),
    )
    op.create_index(op.f('ix_skills_skill_id'), 'skills', ['skill_id'], unique=True)
    op.create_index('ix_skills_category_active', 'skills', ['category', 'is_active'], unique=False)

    # 2. ai_conversations 加 assistant_id
    op.add_column('ai_conversations',
        sa.Column('assistant_id', sa.String(length=50), nullable=True),
    )

    # 3. chat_assistants 加 is_default
    op.add_column('chat_assistants',
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('chat_assistants', 'is_default')
    op.drop_column('ai_conversations', 'assistant_id')
    op.drop_index('ix_skills_category_active', table_name='skills')
    op.drop_index(op.f('ix_skills_skill_id'), table_name='skills')
    op.drop_table('skills')
