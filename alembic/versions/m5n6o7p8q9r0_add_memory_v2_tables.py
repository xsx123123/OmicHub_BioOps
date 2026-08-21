"""add v2 memory blocks and facts tables"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from omichub.infrastructure.database.vector import Vector

revision: str = "m5n6o7p8q9r0"
down_revision: str | Sequence[str] | None = "eb57036c9eec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "memory_blocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("agent_id", sa.String(length=50), nullable=False),
        sa.Column("block_name", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("char_limit", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "agent_id", "block_name", name="uq_memory_blocks_owner_name"),
    )
    op.create_index("idx_memory_blocks_user_agent", "memory_blocks", ["user_id", "agent_id"])
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("agent_id", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=300), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("source_session_id", sa.String(length=50), nullable=True),
        sa.Column("source_message_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.8", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["superseded_by"], ["memory_facts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "agent_id", "content_hash", name="uq_memory_facts_content"),
    )
    op.create_index("idx_memory_facts_user_agent_status", "memory_facts", ["user_id", "agent_id", "status"])
    op.execute(
        "CREATE INDEX idx_memory_facts_embedding_hnsw ON memory_facts "
        "USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_facts_embedding_hnsw")
    op.drop_index("idx_memory_facts_user_agent_status", table_name="memory_facts")
    op.drop_table("memory_facts")
    op.drop_index("idx_memory_blocks_user_agent", table_name="memory_blocks")
    op.drop_table("memory_blocks")
