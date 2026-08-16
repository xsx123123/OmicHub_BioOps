"""add pgvector retrieval columns and project boundaries.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: str | Sequence[str] | None = "i3j4k5l6m7n8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_TABLES = (
    "agent_templates",
    "chat_sessions",
    "agent_memories",
    "knowledge_bases",
    "kb_documents",
    "mas_runs",
    "mas_artifacts",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    for table in _PROJECT_TABLES:
        op.add_column(table, sa.Column("project_id", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_project_id", table, ["project_id"], unique=False)

    op.execute(
        "ALTER TABLE agent_memories ALTER COLUMN embedding TYPE vector(1024) "
        "USING CASE WHEN embedding IS NULL THEN NULL "
        "WHEN jsonb_typeof(embedding) <> 'array' THEN NULL "
        "WHEN jsonb_array_length(embedding) <> 1024 THEN NULL "
        "ELSE embedding::text::vector(1024) END"
    )
    op.execute("ALTER TABLE kb_chunks ADD COLUMN embedding vector(1024)")
    op.add_column("kb_chunks", sa.Column("embedding_model", sa.String(length=120), nullable=True))
    op.execute(
        "CREATE INDEX ix_agent_memories_embedding_hnsw "
        "ON agent_memories USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding_hnsw "
        "ON kb_chunks USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )
    op.create_index(
        "idx_agent_memories_project_status", "agent_memories", ["project_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_agent_memories_project_status", table_name="agent_memories")
    op.execute("DROP INDEX IF EXISTS ix_kb_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_agent_memories_embedding_hnsw")
    op.drop_column("kb_chunks", "embedding_model")
    op.drop_column("kb_chunks", "embedding")
    op.execute(
        "ALTER TABLE agent_memories ALTER COLUMN embedding TYPE jsonb "
        "USING CASE WHEN embedding IS NULL THEN NULL ELSE embedding::text::jsonb END"
    )
    for table in reversed(_PROJECT_TABLES):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "project_id")
