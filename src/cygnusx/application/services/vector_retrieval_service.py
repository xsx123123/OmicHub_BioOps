"""Permission-aware hybrid retrieval backed by PostgreSQL pgvector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from cygnusx.infrastructure.database.models.knowledge_chunk import (
    EMBEDDING_DIMENSIONS,
    KbChunkModel,
)
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel


@dataclass(frozen=True)
class KnowledgeCitation:
    """A compact, traceable knowledge-base retrieval result."""

    doc_id: str
    title: str
    category: str
    excerpt: str
    section_path: str
    url: str
    score: float


class VectorRetrievalService:
    """Executes permission filter → vector recall → keyword rerank → citations."""

    def __init__(self, db: AsyncSession, embedding_client: Any | None = None) -> None:
        self._db = db
        self._embedding_client = embedding_client

    async def search_knowledge(
        self,
        *,
        query: str,
        limit: int = 5,
        project_id: str | None = None,
    ) -> list[KnowledgeCitation]:
        normalized_query = " ".join(query.split())[:1000]
        if not normalized_query:
            return []
        candidates = await self._vector_recall(
            normalized_query, project_id=project_id, candidate_limit=max(limit * 8, 40)
        )
        if not candidates:
            candidates = await self._keyword_recall(
                normalized_query, project_id=project_id, candidate_limit=max(limit * 8, 40)
            )
        return self._keyword_rerank(candidates, normalized_query, limit)

    async def _vector_recall(
        self, query: str, *, project_id: str | None, candidate_limit: int
    ) -> list[KnowledgeCitation]:
        embedding = await self._embed(query)
        if not embedding:
            return []
        distance = KbChunkModel.embedding.cosine_distance(embedding)
        statement = (
            select(
                KbDocumentModel.doc_id,
                KbDocumentModel.title,
                KbDocumentModel.category,
                KbChunkModel.content,
                KbChunkModel.section_path,
                (1 - distance).label("score"),
            )
            .join(KbChunkModel, KbChunkModel.document_id == KbDocumentModel.doc_id)
            .outerjoin(KnowledgeBaseModel, KbDocumentModel.kb_id == KnowledgeBaseModel.id)
            .where(*self._visibility_filters(project_id), KbChunkModel.embedding.is_not(None))
            .order_by(distance)
            .limit(candidate_limit)
        )
        try:
            rows = (await self._db.execute(statement)).all()
        except Exception as exc:  # no extension / dimension mismatch must not break chat
            logger.warning("知识库 pgvector 召回失败，回退关键词检索: {}", exc)
            return []
        return [self._citation(*row) for row in rows]

    async def _keyword_recall(
        self, query: str, *, project_id: str | None, candidate_limit: int
    ) -> list[KnowledgeCitation]:
        terms = self._terms(query)
        if not terms:
            return []
        matches = or_(
            *(KbChunkModel.content.ilike(f"%{term}%") for term in terms),
            *(KbDocumentModel.title.ilike(f"%{term}%") for term in terms),
        )
        statement = (
            select(
                KbDocumentModel.doc_id,
                KbDocumentModel.title,
                KbDocumentModel.category,
                KbChunkModel.content,
                KbChunkModel.section_path,
                func.count().label("score"),
            )
            .join(KbChunkModel, KbChunkModel.document_id == KbDocumentModel.doc_id)
            .outerjoin(KnowledgeBaseModel, KbDocumentModel.kb_id == KnowledgeBaseModel.id)
            .where(*self._visibility_filters(project_id), matches)
            .group_by(
                KbDocumentModel.doc_id,
                KbDocumentModel.title,
                KbDocumentModel.category,
                KbChunkModel.id,
            )
            .order_by(KbChunkModel.updated_at.desc())
            .limit(candidate_limit)
        )
        rows = (await self._db.execute(statement)).all()
        return [self._citation(*row) for row in rows]

    def _visibility_filters(self, project_id: str | None) -> list[Any]:
        # Project sessions may use platform/global knowledge (NULL) plus their own
        # project-bound documents; unrelated project documents never participate.
        project_visibility = (
            or_(KbDocumentModel.project_id.is_(None), KbDocumentModel.project_id == project_id)
            if project_id
            else KbDocumentModel.project_id.is_(None)
        )
        return [
            KbDocumentModel.status == 1,
            project_visibility,
            or_(
                KbDocumentModel.kb_id.is_(None),
                and_(
                    KnowledgeBaseModel.ai_searchable.is_(True),
                    KnowledgeBaseModel.is_enabled.is_(True),
                    or_(
                        KnowledgeBaseModel.project_id == project_id
                        if project_id
                        else KnowledgeBaseModel.project_id.is_(None),
                        KnowledgeBaseModel.project_id.is_(None),
                    ),
                ),
            ),
        ]

    @staticmethod
    def _terms(query: str) -> list[str]:
        return list(dict.fromkeys(term.lower() for term in query.split() if len(term) > 1))[:12]

    def _keyword_rerank(
        self, candidates: list[KnowledgeCitation], query: str, limit: int
    ) -> list[KnowledgeCitation]:
        terms = self._terms(query)

        def score(item: KnowledgeCitation) -> tuple[float, str]:
            haystack = f"{item.title} {item.section_path} {item.excerpt}".lower()
            keyword_score = sum(term in haystack for term in terms) / max(len(terms), 1)
            return item.score + keyword_score * 0.15, item.doc_id

        return sorted(candidates, key=score, reverse=True)[:limit]

    @staticmethod
    def _citation(
        doc_id: str,
        title: str,
        category: str,
        content: str,
        section_path: str,
        score: float,
    ) -> KnowledgeCitation:
        excerpt = " ".join(str(content).split())[:600]
        return KnowledgeCitation(
            doc_id=str(doc_id),
            title=str(title),
            category=str(category),
            excerpt=excerpt + ("…" if len(str(content)) > 600 else ""),
            section_path=str(section_path or ""),
            url=f"/knowledge/{doc_id}",
            score=float(score or 0),
        )

    async def _embed(self, text: str) -> list[float]:
        from cygnusx.core.config import get_settings

        model = get_settings().agent_memory_embedding_model.strip()
        if not model:
            return []
        try:
            if self._embedding_client is None:
                from cygnusx.infrastructure.ai_provider.litellm_provider import LiteLLMProvider

                self._embedding_client = LiteLLMProvider()
            values = await self._embedding_client.embeddings(text, model=model)
            embedding = [float(value) for value in values] if values else []
            if embedding and len(embedding) != EMBEDDING_DIMENSIONS:
                logger.warning(
                    "知识库查询向量维度不匹配，期望 {}、实际 {}，回退关键词检索",
                    EMBEDDING_DIMENSIONS,
                    len(embedding),
                )
                return []
            return embedding
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识库查询向量生成失败，回退关键词检索: {}", exc)
            return []
