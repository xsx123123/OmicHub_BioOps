"""add_kb_chunks

补齐知识库语义块表 kb_chunks（ORM 模型 KbChunkModel 早已定义，但一直缺少对应迁移，
导致 sync_knowledge_from_files.py 在 JOIN kb_documents↔kb_chunks 时报
UndefinedTableError: relation "kb_chunks" does not exist）。

表结构与 models/knowledge_chunk.py 完全一致：
- document_id 外键指向 kb_documents.doc_id（字符串业务键），ON DELETE CASCADE，
  与 KbDocumentModel.chunks 关系（primaryjoin doc_id == document_id）对应；
- (document_id, chunk_index) 唯一约束 uq_kb_chunks_doc_index。

注意：模型注释里提到的 embedding vector(1024) 列**本次不建**——当前 Postgres 镜像未安装
pgvector（pg_available_extensions 无 vector），且暂无任何代码读写该列（混合检索尚未落地）。
待引入 pgvector 后再单独加迁移补 embedding 列，避免此处硬依赖扩展导致迁移失败。

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-08-01 02:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p4q5r6s7t8u9"
down_revision: str | None = "o3p4q5r6s7t8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.doc_id"],
            name="fk_kb_chunks_document_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_kb_chunks"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_doc_index"),
    )
    op.create_index("ix_kb_chunks_document_id", "kb_chunks", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_document_id", table_name="kb_chunks")
    op.drop_table("kb_chunks")
