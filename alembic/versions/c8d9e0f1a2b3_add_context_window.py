"""add per-model context window for chat compaction"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "masroom0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("context_window", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE ai_provider_configs SET context_window = 262144 WHERE context_window IS NULL")
    op.alter_column("ai_provider_configs", "context_window", nullable=False, server_default="262144")


def downgrade() -> None:
    op.drop_column("ai_provider_configs", "context_window")
