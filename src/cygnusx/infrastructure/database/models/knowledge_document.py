"""知识库文档主表"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cygnusx.infrastructure.database.base import Base, TimestampMixin
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel

if TYPE_CHECKING:
    from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel


class KbDocumentModel(Base, TimestampMixin):
    """知识库文档主表"""

    __tablename__ = "kb_documents"
    __table_args__ = (
        UniqueConstraint("doc_id", name="uq_kb_documents_doc_id"),
        Index("ix_kb_documents_category", "category"),
        Index("ix_kb_documents_status", "status"),
        Index("ix_kb_documents_created_by", "created_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # 1=已发布 2=待审核 3=已拒绝
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    current_rev: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_revisions.id"), nullable=True
    )
    pending_rev: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doc_revisions.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # 所属知识库（knowledge_bases.id）；NULL 视为实验室知识库（向后兼容）
    kb_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("knowledge_bases.id"), nullable=True, index=True
    )

    # 关联关系（仅用于编程便利，不依赖级联删除，避免误删历史）
    current_revision: Mapped[DocRevisionModel | None] = relationship(
        "DocRevisionModel",
        foreign_keys=[current_rev],
        lazy="selectin",
    )
    pending_revision: Mapped[DocRevisionModel | None] = relationship(
        "DocRevisionModel",
        foreign_keys=[pending_rev],
        lazy="selectin",
    )
    # 语义块（kb_chunks）：文档删除时级联清理
    chunks: Mapped[list[KbChunkModel]] = relationship(
        "KbChunkModel",
        primaryjoin="KbDocumentModel.doc_id == foreign(KbChunkModel.document_id)",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
