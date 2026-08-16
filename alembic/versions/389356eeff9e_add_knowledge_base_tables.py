"""add knowledge base tables

Revision ID: 389356eeff9e
Revises: t8u9v0w1x2y3
Create Date: 2026-07-10 14:47:50.000000

- 新增知识库文档主表 kb_documents
- 新增文档版本历史表 doc_revisions
- 新增编辑者记录表 doc_editors
- 新增 Issue 留言表 kb_issues
- 新增文档审核日志表 doc_audit_logs（与全局 audit_logs 区分）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "389356eeff9e"
down_revision: str | None = "t8u9v0w1x2y3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 文档主表（先不加 current_rev / pending_rev 外键，避免与 doc_revisions 循环依赖）
    op.create_table(
        "kb_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_rev", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pending_rev", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", name="uq_kb_documents_doc_id"),
    )
    op.create_index("ix_kb_documents_category", "kb_documents", ["category"], unique=False)
    op.create_index("ix_kb_documents_status", "kb_documents", ["status"], unique=False)
    op.create_index("ix_kb_documents_created_by", "kb_documents", ["created_by"], unique=False)

    # 2. 版本历史表
    op.create_table(
        "doc_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("edit_summary", sa.String(length=500), nullable=True),
        sa.Column("edited_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name="fk_doc_revisions_document_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by"],
            ["users.id"],
            name="fk_doc_revisions_edited_by",
        ),
    )
    op.create_index("ix_doc_revisions_document_id", "doc_revisions", ["document_id"], unique=False)
    op.create_index("ix_doc_revisions_status", "doc_revisions", ["status"], unique=False)

    # 3. 编辑者记录表
    op.create_table(
        "doc_editors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_name", sa.String(length=128), nullable=False),
        sa.Column("edit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_edit",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_edit",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name="fk_doc_editors_document_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_doc_editors_user_id",
        ),
        sa.UniqueConstraint(
            "document_id", "user_id", name="uk_doc_editors_document_user"
        ),
    )
    op.create_index("ix_doc_editors_document_id", "doc_editors", ["document_id"], unique=False)

    # 4. Issue 留言表
    op.create_table(
        "kb_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_name", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reply_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name="fk_kb_issues_document_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_kb_issues_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to"],
            ["kb_issues.id"],
            name="fk_kb_issues_reply_to",
        ),
    )
    op.create_index("ix_kb_issues_document_id", "kb_issues", ["document_id"], unique=False)
    op.create_index("ix_kb_issues_reply_to", "kb_issues", ["reply_to"], unique=False)

    # 5. 文档审核日志表
    op.create_table(
        "doc_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_name", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name="fk_doc_audit_logs_document_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["doc_revisions.id"],
            name="fk_doc_audit_logs_revision_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_doc_audit_logs_actor_id",
        ),
    )
    op.create_index(
        "ix_doc_audit_logs_document_id", "doc_audit_logs", ["document_id"], unique=False
    )
    op.create_index("ix_doc_audit_logs_action", "doc_audit_logs", ["action"], unique=False)

    # 6. 为 kb_documents 补上循环外键（current_rev / pending_rev → doc_revisions.id）
    op.create_foreign_key(
        "fk_kb_documents_current_rev",
        "kb_documents",
        "doc_revisions",
        ["current_rev"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_kb_documents_pending_rev",
        "kb_documents",
        "doc_revisions",
        ["pending_rev"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_kb_documents_pending_rev", "kb_documents", type_="foreignkey")
    op.drop_constraint("fk_kb_documents_current_rev", "kb_documents", type_="foreignkey")

    op.drop_index("ix_doc_audit_logs_action", table_name="doc_audit_logs")
    op.drop_index("ix_doc_audit_logs_document_id", table_name="doc_audit_logs")
    op.drop_table("doc_audit_logs")

    op.drop_index("ix_kb_issues_reply_to", table_name="kb_issues")
    op.drop_index("ix_kb_issues_document_id", table_name="kb_issues")
    op.drop_table("kb_issues")

    op.drop_index("ix_doc_editors_document_id", table_name="doc_editors")
    op.drop_table("doc_editors")

    op.drop_index("ix_doc_revisions_status", table_name="doc_revisions")
    op.drop_index("ix_doc_revisions_document_id", table_name="doc_revisions")
    op.drop_table("doc_revisions")

    op.drop_index("ix_kb_documents_created_by", table_name="kb_documents")
    op.drop_index("ix_kb_documents_status", table_name="kb_documents")
    op.drop_index("ix_kb_documents_category", table_name="kb_documents")
    op.drop_table("kb_documents")
