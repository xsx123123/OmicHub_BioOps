"""show only lab knowledge base

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-08-13 22:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "s2t3u4v5w6x7"
down_revision: str | None = "r1s2t3u4v5w6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE kb_documents SET kb_id = 'lab' WHERE kb_id IS NULL")
    op.execute("UPDATE knowledge_bases SET show_in_lab = false WHERE id <> 'lab'")
    op.execute("UPDATE knowledge_bases SET show_in_lab = true WHERE id = 'lab'")


def downgrade() -> None:
    op.execute("UPDATE knowledge_bases SET show_in_lab = true WHERE id IN ('qc', 'cloud')")
