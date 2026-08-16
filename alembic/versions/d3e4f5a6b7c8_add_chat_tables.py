"""add_chat_tables

Cherry Studio 架构聊天系统：chat_sessions / chat_messages / chat_assistants

Revision ID: d3e4f5a6b7c8
Revises: a1b2c3d4e5f6
Create Date: 2026-06-27 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 助手表（先建，会话表外键依赖它）
    op.create_table('chat_assistants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('assistant_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('default_model_id', sa.UUID(), nullable=True),
        sa.Column('default_temperature', sa.Float(), nullable=False),
        sa.Column('default_max_tokens', sa.Integer(), nullable=False),
        sa.Column('icon', sa.String(length=10), nullable=False),
        sa.Column('color', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['default_model_id'], ['ai_provider_configs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('assistant_id'),
    )
    op.create_index(op.f('ix_chat_assistants_assistant_id'), 'chat_assistants', ['assistant_id'], unique=True)
    op.create_index('ix_chat_assistants_category', 'chat_assistants', ['category', 'is_active'], unique=False)

    # 会话表
    op.create_table('chat_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('assistant_id', sa.String(length=50), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('model_id', sa.UUID(), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assistant_id'], ['chat_assistants.assistant_id'], ),
        sa.ForeignKeyConstraint(['model_id'], ['ai_provider_configs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )
    op.create_index(op.f('ix_chat_sessions_session_id'), 'chat_sessions', ['session_id'], unique=True)
    op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)
    op.create_index('idx_chat_sessions_user_updated', 'chat_sessions', ['user_id', 'updated_at'], unique=False)

    # 消息表
    op.create_table('chat_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.String(length=50), nullable=False),
        sa.Column('session_id', sa.String(length=50), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=20), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )
    op.create_index(op.f('ix_chat_messages_message_id'), 'chat_messages', ['message_id'], unique=True)
    op.create_index(op.f('ix_chat_messages_session_id'), 'chat_messages', ['session_id'], unique=False)
    op.create_index('idx_chat_messages_session_created', 'chat_messages', ['session_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_chat_messages_session_created', table_name='chat_messages')
    op.drop_index(op.f('ix_chat_messages_session_id'), table_name='chat_messages')
    op.drop_index(op.f('ix_chat_messages_message_id'), table_name='chat_messages')
    op.drop_table('chat_messages')

    op.drop_index('idx_chat_sessions_user_updated', table_name='chat_sessions')
    op.drop_index(op.f('ix_chat_sessions_user_id'), table_name='chat_sessions')
    op.drop_index(op.f('ix_chat_sessions_session_id'), table_name='chat_sessions')
    op.drop_table('chat_sessions')

    op.drop_index('ix_chat_assistants_category', table_name='chat_assistants')
    op.drop_index(op.f('ix_chat_assistants_assistant_id'), table_name='chat_assistants')
    op.drop_table('chat_assistants')
