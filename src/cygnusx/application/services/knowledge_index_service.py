"""Chunk and embed published knowledge-base documents for pgvector retrieval."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.models.knowledge_chunk import (
    EMBEDDING_DIMENSIONS,
    KbChunkModel,
)
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MAX_CHUNK_CHARS = 1800


class KnowledgeIndexService:
    """Keeps ``kb_chunks`` aligned with each published document revision."""

    def __init__(self, db: AsyncSession, embedding_client: Any | None = None) -> None:
        self._db = db
        self._embedding_client = embedding_client

    async def index_document(
        self,
        document: KbDocumentModel,
        content: str,
        *,
        include_unreferenced_assets: bool = True,
    ) -> int:
        """Replace a document's chunks atomically in the caller transaction."""
        indexable_content = self._prepare_indexable_content(
            document,
            content,
            include_unreferenced_assets=include_unreferenced_assets,
        )
        return await self._replace_chunks(document, indexable_content)

    async def ensure_document_indexed(
        self,
        document: KbDocumentModel,
        content: str,
        *,
        include_unreferenced_assets: bool = True,
    ) -> tuple[bool, int]:
        """Rebuild only when chunk content or the active embedding model changed."""
        indexable_content = self._prepare_indexable_content(
            document,
            content,
            include_unreferenced_assets=include_unreferenced_assets,
        )
        chunks = self._split(indexable_content)
        model = get_settings().agent_memory_embedding_model.strip() or None
        result = await self._db.execute(
            select(
                KbChunkModel.chunk_index,
                KbChunkModel.content_hash,
                KbChunkModel.embedding_model,
            )
            .where(KbChunkModel.document_id == document.doc_id)
            .order_by(KbChunkModel.chunk_index)
        )
        existing = [(int(row[0]), str(row[1]), row[2]) for row in result.all()]
        expected = [
            (index, hashlib.md5(chunk.encode("utf-8")).hexdigest(), model)
            for index, (_section, chunk) in enumerate(chunks)
        ]
        if existing == expected:
            return False, len(chunks)
        return True, await self._replace_chunks(document, indexable_content)

    async def ensure_published_indexes(
        self, *, include_unreferenced_assets: bool = True
    ) -> tuple[int, int]:
        """Incrementally align all published documents with their current source assets."""
        rows = (
            await self._db.execute(
                select(KbDocumentModel, DocRevisionModel.content)
                .join(DocRevisionModel, KbDocumentModel.current_rev == DocRevisionModel.id)
                .where(KbDocumentModel.status == 1)
                .order_by(KbDocumentModel.updated_at.asc())
            )
        ).all()
        rebuilt = 0
        skipped = 0
        for document, content in rows:
            changed, _chunk_count = await self.ensure_document_indexed(
                document,
                content,
                include_unreferenced_assets=include_unreferenced_assets,
            )
            if changed:
                rebuilt += 1
            else:
                skipped += 1
        return rebuilt, skipped

    def _prepare_indexable_content(
        self,
        document: KbDocumentModel,
        content: str,
        *,
        include_unreferenced_assets: bool,
    ) -> str:
        from cygnusx.application.services.knowledge_asset_service import KnowledgeAssetService

        indexable_content, asset_report = KnowledgeAssetService().enrich_markdown(
            content,
            source_path=document.file_path,
            include_unreferenced_assets=include_unreferenced_assets,
        )
        if asset_report.indexed:
            logger.info(
                "知识库文档 {} 已加入 {} 个附件资产块（发现 {} 个）",
                document.doc_id,
                asset_report.indexed,
                asset_report.discovered,
            )
        return indexable_content

    async def _replace_chunks(self, document: KbDocumentModel, content: str) -> int:
        await self._db.execute(
            delete(KbChunkModel).where(KbChunkModel.document_id == document.doc_id)
        )
        model = get_settings().agent_memory_embedding_model.strip()
        chunks = self._split(content)
        for chunk_index, (section_path, chunk_content) in enumerate(chunks):
            embedding = await self._embed(chunk_content, model) if model else None
            self._db.add(
                KbChunkModel(
                    document_id=document.doc_id,
                    chunk_index=chunk_index,
                    section_path=section_path,
                    content=chunk_content,
                    content_hash=hashlib.md5(chunk_content.encode("utf-8")).hexdigest(),
                    embedding=embedding,
                    embedding_model=model or None,
                )
            )
        await self._db.flush()
        return len(chunks)

    @staticmethod
    def _split(content: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        headings = list(_HEADING.finditer(content))
        if not headings:
            headings = []
        for index, heading in enumerate(headings):
            start = heading.end()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            body = content[start:end].strip()
            if body:
                sections.append((heading.group(2).strip(), body))
        if not sections and content.strip():
            sections.append(("", content.strip()))

        chunks: list[tuple[str, str]] = []
        for section_path, body in sections:
            for offset in range(0, len(body), _MAX_CHUNK_CHARS):
                chunk = body[offset : offset + _MAX_CHUNK_CHARS].strip()
                if chunk:
                    chunks.append((section_path, chunk))
        return chunks

    async def _embed(self, content: str, model: str) -> list[float] | None:
        try:
            if self._embedding_client is None:
                from cygnusx.infrastructure.ai_provider.litellm_provider import LiteLLMProvider

                self._embedding_client = LiteLLMProvider()
            values = await self._embedding_client.embeddings(content, model=model)
            embedding = [float(value) for value in values] if values else None
            if embedding is not None and len(embedding) != EMBEDDING_DIMENSIONS:
                logger.warning(
                    "知识库向量维度不匹配，期望 {}、实际 {}，回退关键词检索",
                    EMBEDDING_DIMENSIONS,
                    len(embedding),
                )
                return None
            return embedding
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识库分块向量生成失败，保留关键词检索: {}", exc)
            return None
