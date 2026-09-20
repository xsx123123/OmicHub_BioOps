"""Hybrid knowledge retrieval query and ranking contracts."""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from cygnusx.application.services.vector_retrieval_service import (
    KnowledgeCitation,
    VectorRetrievalService,
)
from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel


def test_project_visibility_allows_global_and_matching_project_only() -> None:
    service = VectorRetrievalService(db=None)  # type: ignore[arg-type]
    statement = select(KbDocumentModel.doc_id).where(*service._visibility_filters("project-a"))
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "kb_documents.project_id IS NULL OR kb_documents.project_id =" in compiled
    assert "knowledge_bases.ai_searchable IS true" in compiled
    assert "knowledge_bases.is_enabled IS true" in compiled


def test_vector_recall_uses_cosine_distance_operator() -> None:
    service = VectorRetrievalService(db=None)  # type: ignore[arg-type]
    distance = KbChunkModel.embedding.cosine_distance([0.1] * 1024)
    statement = (
        select(KbDocumentModel.doc_id)
        .join(KbChunkModel, KbChunkModel.document_id == KbDocumentModel.doc_id)
        .where(*service._visibility_filters(None), KbChunkModel.embedding.is_not(None))
        .order_by(distance)
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "<=>" in compiled
    assert "kb_chunks.embedding IS NOT NULL" in compiled


def test_keyword_rerank_returns_traceable_citations() -> None:
    service = VectorRetrievalService(db=None)  # type: ignore[arg-type]
    candidates = [
        KnowledgeCitation(
            doc_id="generic",
            title="Guide",
            category="general",
            excerpt="unrelated notes",
            section_path="",
            url="/knowledge/generic",
            score=0.92,
        ),
        KnowledgeCitation(
            doc_id="project-guide",
            title="RNA-seq guide",
            category="analysis",
            excerpt="RNA-seq alignment and quality control",
            section_path="Alignment",
            url="/knowledge/project-guide",
            score=0.86,
        ),
    ]

    ranked = service._keyword_rerank(candidates, "RNA-seq alignment", limit=1)

    assert ranked[0].doc_id == "project-guide"
    assert ranked[0].url == "/knowledge/project-guide"
