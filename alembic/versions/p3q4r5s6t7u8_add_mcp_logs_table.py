"""add_mcp_logs_table

MCP Server 运行日志表

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-07-05 02:05:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'p3q4r5s6t7u8'
down_revision: str | None = 'o2p3q4r5s6t7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('mcp_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('service_id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False, server_default='internal'),
        sa.ForeignKeyConstraint(['service_id'], ['mcp_servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_mcp_logs_service_timestamp', 'mcp_logs', ['service_id', 'timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_mcp_logs_service_timestamp', table_name='mcp_logs')
    op.drop_table('mcp_logs')
