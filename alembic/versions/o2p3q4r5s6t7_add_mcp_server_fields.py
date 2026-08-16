"""add_mcp_server_fields

MCP Server 扩展字段：args / registry / working_dir / version / is_enabled

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-07-05 02:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'o2p3q4r5s6t7'
down_revision: str | None = 'n1o2p3q4r5s6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('mcp_servers', sa.Column('args', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column('mcp_servers', sa.Column('registry', sa.String(length=50), nullable=False, server_default='default'))
    op.add_column('mcp_servers', sa.Column('working_dir', sa.String(length=500), nullable=False, server_default=''))
    op.add_column('mcp_servers', sa.Column('version', sa.String(length=20), nullable=False, server_default=''))
    op.add_column('mcp_servers', sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('mcp_servers', 'is_enabled')
    op.drop_column('mcp_servers', 'version')
    op.drop_column('mcp_servers', 'working_dir')
    op.drop_column('mcp_servers', 'registry')
    op.drop_column('mcp_servers', 'args')
