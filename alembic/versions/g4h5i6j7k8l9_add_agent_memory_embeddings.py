"""add optional semantic embeddings to agent memories

Revision ID: g4h5i6j7k8l9
Revises: f2a3b4c5d6e7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g4h5i6j7k8l9"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("agent_memories", sa.Column("embedding_model", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_memories", "embedding_model")
    op.drop_column("agent_memories", "embedding")
