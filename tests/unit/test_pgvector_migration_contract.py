"""Schema-level contract for the pgvector and project-boundary migration."""

from pathlib import Path

_MIGRATION = Path("alembic/versions/j4k5l6m7n8o9_add_pgvector_project_boundaries.py")


def test_pgvector_migration_enables_extension_and_hnsw_indexes() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    assert 'CREATE EXTENSION IF NOT EXISTS vector' in source
    assert 'ALTER TABLE agent_memories ALTER COLUMN embedding TYPE vector(1024)' in source
    assert "WHEN jsonb_typeof(embedding) <> 'array' THEN NULL" in source
    assert "WHEN jsonb_array_length(embedding) <> 1024 THEN NULL" in source
    assert 'ALTER TABLE kb_chunks ADD COLUMN embedding vector(1024)' in source
    assert 'CREATE INDEX ix_agent_memories_embedding_hnsw' in source
    assert 'CREATE INDEX ix_kb_chunks_embedding_hnsw' in source
    assert 'vector_cosine_ops' in source


def test_pgvector_migration_covers_all_requested_project_boundaries() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    for table in (
        '"agent_templates"',
        '"chat_sessions"',
        '"agent_memories"',
        '"knowledge_bases"',
        '"kb_documents"',
        '"mas_artifacts"',
    ):
        assert table in source
    assert 'sa.Column("project_id", sa.String(length=64), nullable=True)' in source
