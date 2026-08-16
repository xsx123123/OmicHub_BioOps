"""知识库文档语义块表（chunk）

将文档正文按 Markdown 标题层级切分为语义块，
每块携带 embedding 向量，用于混合检索（向量 + 关键词）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from omichub.infrastructure.database.base import Base, TimestampMixin
from omichub.infrastructure.database.vector import Vector

EMBEDDING_DIMENSIONS = 1024


class KbChunkModel(Base, TimestampMixin):
    """知识库文档语义块"""

    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_doc_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        # FK 在迁移中声明（ON DELETE CASCADE）
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[str] = mapped_column(
        String(512), nullable=False, default="", server_default=""
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
