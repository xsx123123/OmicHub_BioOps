"""add_terminal_sessions_table

云端沙盒终端会话表

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2026-07-07 20:50:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'q4r5s6t7u8v9'
down_revision: str | None = '9f8e7d6c5b4a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('terminal_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', sa.String(length=32), nullable=False),
        sa.Column('container_id', sa.String(length=100), nullable=True),
        sa.Column('host_port', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='creating'),
        sa.Column('last_activity', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_terminal_sessions_user_id', 'terminal_sessions', ['user_id'], unique=False)
    op.create_index('ix_terminal_sessions_session_id', 'terminal_sessions', ['session_id'], unique=True)
    op.create_index('ix_terminal_sessions_status', 'terminal_sessions', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_terminal_sessions_status', table_name='terminal_sessions')
    op.drop_index('ix_terminal_sessions_session_id', table_name='terminal_sessions')
    op.drop_index('ix_terminal_sessions_user_id', table_name='terminal_sessions')
    op.drop_table('terminal_sessions')
