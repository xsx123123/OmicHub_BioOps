"""Knowledge chunking contracts used by pgvector indexing."""

import hashlib
from types import SimpleNamespace

import pytest

from omichub.application.services.knowledge_index_service import KnowledgeIndexService


def test_knowledge_index_splits_headings_and_long_sections() -> None:
    content = "# Overview\n" + "A" * 1900 + "\n## Details\nsecond section"

    chunks = KnowledgeIndexService._split(content)

    assert len(chunks) == 3
    assert chunks[0][0] == "Overview"
    assert len(chunks[0][1]) == 1800
    assert chunks[1][0] == "Overview"
    assert chunks[2] == ("Details", "second section")


def test_knowledge_index_uses_document_body_when_no_heading_exists() -> None:
    assert KnowledgeIndexService._split(" plain knowledge ") == [("", "plain knowledge")]


@pytest.mark.asyncio
async def test_knowledge_index_ignores_wrong_dimension_embeddings() -> None:
    class EmbeddingClient:
        async def embeddings(self, _content: str, *, model: str) -> list[float]:
            assert model == "embedding-1024"
            return [0.1, 0.2]

    service = KnowledgeIndexService(db=None, embedding_client=EmbeddingClient())

    assert await service._embed("test", "embedding-1024") is None


@pytest.mark.asyncio
async def test_knowledge_index_skips_unchanged_document(monkeypatch) -> None:
    content = "# Overview\nunchanged knowledge"
    chunk = "unchanged knowledge"
    expected_hash = hashlib.md5(chunk.encode("utf-8")).hexdigest()

    class Result:
        def all(self):
            return [(0, expected_hash, None)]

    class Database:
        async def execute(self, _statement):
            return Result()

    monkeypatch.setattr(
        "omichub.application.services.knowledge_index_service.get_settings",
        lambda: SimpleNamespace(agent_memory_embedding_model=""),
    )
    document = SimpleNamespace(doc_id="doc-1", file_path="/missing/source.md")
    changed, chunks = await KnowledgeIndexService(Database()).ensure_document_indexed(
        document, content
    )

    assert changed is False
    assert chunks == 1
