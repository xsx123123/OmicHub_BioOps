"""add_mcp_skill_version_control

MCP 服务与技能的版本控制（快照 / 回滚 / 审计）：
- mcp_versions 新增 config_snapshot（连接/行为配置快照）与 source（快照来源 builder/admin/rollback），
  使 admin 手工更新与回滚也能留档完整配置；
- 新建 skill_versions 表：技能内容版本快照（revision 平台递增序号 + 声明版本留档），
  支撑技能变更历史与回滚。

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-07-30 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'n2o3p4q5r6s7'
down_revision: str | None = 'm1n2o3p4q5r6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. mcp_versions 扩展：配置快照 + 快照来源
    op.add_column('mcp_versions', sa.Column('config_snapshot', sa.JSON(), nullable=True))
    op.add_column(
        'mcp_versions',
        sa.Column('source', sa.String(length=20), nullable=False, server_default='builder'),
    )

    # 2. skill_versions — 技能版本历史快照
    op.create_table('skill_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('skill_id', sa.String(length=50), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('prompt', sa.Text(), nullable=False, server_default=''),
        sa.Column('tool_definition', sa.JSON(), nullable=True),
        sa.Column('icon', sa.String(length=10), nullable=False, server_default=''),
        sa.Column('category', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('frontmatter', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='admin'),
        sa.Column('changelog', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.skill_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill_id', 'revision', name='uq_skill_versions_skill_revision'),
    )
    op.create_index('ix_skill_versions_skill_id', 'skill_versions', ['skill_id'])


def downgrade() -> None:
    op.drop_index('ix_skill_versions_skill_id', table_name='skill_versions')
    op.drop_table('skill_versions')
    op.drop_column('mcp_versions', 'source')
    op.drop_column('mcp_versions', 'config_snapshot')
