"""add_mcp_builder_tables

MCP Builder 自生成框架：mcp_builds / mcp_versions / mcp_visibility / mcp_reviews
四张新表 + mcp_servers 扩展字段（pool / expires_at / created_by / current_version /
generation_meta / review_status / is_template）。

设计文档：docs/26.7.30/mcp_builder_framework.md §2

Revision ID: h6i7j8k9l1m3
Revises: g4h5i6j7k8l9
Create Date: 2026-07-29 23:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h6i7j8k9l1m3'
down_revision: str | None = 'g4h5i6j7k8l9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. mcp_builds — MCP 生成构建记录（核心）
    op.create_table('mcp_builds',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('requirement', sa.Text(), nullable=False),
        sa.Column('plan_summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('search_queries', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('search_results', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('generated_code', sa.Text(), nullable=False, server_default=''),
        sa.Column('runtime', sa.String(length=20), nullable=False, server_default='python'),
        sa.Column('safety_report', sa.JSON(), nullable=True),
        sa.Column('mcp_server_id', sa.UUID(), nullable=True),
        sa.Column('version', sa.String(length=20), nullable=False, server_default='1.0.0'),
        sa.Column('parent_build_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='planning'),
        sa.Column('test_cases', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('test_passed', sa.Boolean(), nullable=True),
        sa.Column('build_doc', sa.Text(), nullable=False, server_default=''),
        sa.Column('architecture_doc', sa.Text(), nullable=False, server_default=''),
        sa.Column('model_used', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('tokens_consumed', sa.Integer(), nullable=True),
        sa.Column('generation_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_build_id'], ['mcp_builds.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_mcp_builds_user', 'mcp_builds', ['user_id'], unique=False)
    op.create_index('idx_mcp_builds_status', 'mcp_builds', ['status'], unique=False)
    op.create_index('idx_mcp_builds_server', 'mcp_builds', ['mcp_server_id'], unique=False)

    # 2. mcp_versions — MCP 版本历史
    op.create_table('mcp_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('mcp_server_id', sa.UUID(), nullable=False),
        sa.Column('build_id', sa.UUID(), nullable=True),
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('version_tag', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('is_major', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('code_snapshot', sa.Text(), nullable=False, server_default=''),
        sa.Column('tools_snapshot', sa.JSON(), nullable=True),
        sa.Column('changelog', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['build_id'], ['mcp_builds.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mcp_server_id', 'version', name='uq_mcp_versions_server_version'),
    )
    op.create_index('idx_mcp_versions_server', 'mcp_versions', ['mcp_server_id'], unique=False)

    # 3. mcp_visibility — 用户级 MCP 可见性
    op.create_table('mcp_visibility',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('mcp_server_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('access_level', sa.String(length=20), nullable=False, server_default='read'),
        sa.Column('granted_by', sa.UUID(), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['mcp_server_id'], ['mcp_servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mcp_server_id', 'user_id', name='uq_mcp_visibility_server_user'),
    )
    op.create_index('idx_mcp_visibility_user', 'mcp_visibility', ['user_id'], unique=False)
    op.create_index('idx_mcp_visibility_server', 'mcp_visibility', ['mcp_server_id'], unique=False)

    # 4. mcp_reviews — 审核记录
    op.create_table('mcp_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('build_id', sa.UUID(), nullable=False),
        sa.Column('reviewer_id', sa.UUID(), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=True),
        sa.Column('comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['build_id'], ['mcp_builds.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_mcp_reviews_build', 'mcp_reviews', ['build_id'], unique=False)

    # 5. mcp_servers 扩展字段
    op.add_column('mcp_servers', sa.Column('pool', sa.String(length=20), nullable=False, server_default='production'))
    op.add_column('mcp_servers', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mcp_servers', sa.Column('created_by', sa.UUID(), nullable=True))
    op.add_column('mcp_servers', sa.Column('current_version', sa.String(length=20), nullable=False, server_default='1.0.0'))
    op.add_column('mcp_servers', sa.Column('generation_meta', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column('mcp_servers', sa.Column('review_status', sa.String(length=20), nullable=False, server_default='approved'))
    op.add_column('mcp_servers', sa.Column('is_template', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_index('idx_mcp_servers_pool', 'mcp_servers', ['pool'], unique=False)
    op.create_index('idx_mcp_servers_expires_at', 'mcp_servers', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_mcp_servers_expires_at', table_name='mcp_servers')
    op.drop_index('idx_mcp_servers_pool', table_name='mcp_servers')
    op.drop_column('mcp_servers', 'is_template')
    op.drop_column('mcp_servers', 'review_status')
    op.drop_column('mcp_servers', 'generation_meta')
    op.drop_column('mcp_servers', 'current_version')
    op.drop_column('mcp_servers', 'created_by')
    op.drop_column('mcp_servers', 'expires_at')
    op.drop_column('mcp_servers', 'pool')

    op.drop_index('idx_mcp_reviews_build', table_name='mcp_reviews')
    op.drop_table('mcp_reviews')
    op.drop_index('idx_mcp_visibility_server', table_name='mcp_visibility')
    op.drop_index('idx_mcp_visibility_user', table_name='mcp_visibility')
    op.drop_table('mcp_visibility')
    op.drop_index('idx_mcp_versions_server', table_name='mcp_versions')
    op.drop_table('mcp_versions')
    op.drop_index('idx_mcp_builds_server', table_name='mcp_builds')
    op.drop_index('idx_mcp_builds_status', table_name='mcp_builds')
    op.drop_index('idx_mcp_builds_user', table_name='mcp_builds')
    op.drop_table('mcp_builds')
