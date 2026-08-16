"""add_knowledge_bases

知识库资源化管理：
- 新建 knowledge_bases 表（id 为字符串 code，如 lab / scseq），
  含 show_in_lab（是否在实验室知识库页展示）、ai_searchable（是否参与 AI 检索）、is_enabled；
- kb_documents 新增 kb_id 外键；
- 预置 lab（实验室知识库）与 scseq（单细胞知识库，不在实验室知识库页展示），
  并按 doc_id 前缀回填存量文档（scseq-* 归 scseq，其余归 lab）。

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
Create Date: 2026-07-31 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'o3p4q5r6s7t8'
down_revision: str | None = 'n2o3p4q5r6s7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'knowledge_bases',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('show_in_lab', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('ai_searchable', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.add_column('kb_documents', sa.Column('kb_id', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_kb_documents_kb_id', 'kb_documents', 'knowledge_bases', ['kb_id'], ['id']
    )
    op.create_index('ix_kb_documents_kb_id', 'kb_documents', ['kb_id'])

    # 预置两个知识库并回填存量文档
    op.execute(
        "INSERT INTO knowledge_bases (id, name, description, show_in_lab, ai_searchable, is_enabled) VALUES "
        "('lab', '实验室知识库', '实验室公共文档与 SOP', true, true, true), "
        "('scseq', '单细胞知识库', '单细胞测序教程与笔记（仅供 AI 检索，不在实验室知识库页展示）', false, true, true)"
    )
    op.execute("UPDATE kb_documents SET kb_id = 'scseq' WHERE doc_id LIKE 'scseq-%'")
    op.execute("UPDATE kb_documents SET kb_id = 'lab' WHERE kb_id IS NULL")


def downgrade() -> None:
    op.drop_index('ix_kb_documents_kb_id', table_name='kb_documents')
    op.drop_constraint('fk_kb_documents_kb_id', 'kb_documents', type_='foreignkey')
    op.drop_column('kb_documents', 'kb_id')
    op.drop_table('knowledge_bases')
