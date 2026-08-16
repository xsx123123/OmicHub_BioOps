"""add_agent_templates

多智能体协作平台：agent_templates 表 + chat_sessions.agent_id 归属列

Revision ID: 9a5b6c7d8e1f
Revises: 7f8e9d0c1b2a
Create Date: 2026-07-02 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9a5b6c7d8e1f'
down_revision: str | None = '7f8e9d0c1b2a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('agent_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('avatar', sa.String(length=10), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('model_id', sa.UUID(), nullable=True),
        sa.Column('model_engine', sa.String(length=100), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('welcome_message', sa.Text(), nullable=False),
        sa.Column('mcp_ids', sa.JSON(), nullable=False),
        sa.Column('skill_ids', sa.JSON(), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('max_tokens', sa.Integer(), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['model_id'], ['ai_provider_configs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id'),
    )
    op.create_index(op.f('ix_agent_templates_agent_id'), 'agent_templates', ['agent_id'], unique=True)
    op.create_index('idx_agent_templates_category', 'agent_templates', ['category', 'is_active'], unique=False)

    # 会话归属 Agent
    op.add_column('chat_sessions', sa.Column('agent_id', sa.String(length=50), nullable=True))
    op.create_foreign_key(
        'fk_chat_sessions_agent_id', 'chat_sessions', 'agent_templates',
        ['agent_id'], ['agent_id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_chat_sessions_agent_id', 'chat_sessions', type_='foreignkey')
    op.drop_column('chat_sessions', 'agent_id')

    op.drop_index('idx_agent_templates_category', table_name='agent_templates')
    op.drop_index(op.f('ix_agent_templates_agent_id'), table_name='agent_templates')
    op.drop_table('agent_templates')
