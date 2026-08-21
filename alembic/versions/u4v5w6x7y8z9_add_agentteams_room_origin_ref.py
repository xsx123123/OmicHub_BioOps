"""add origin_ref to agentteams_rooms (L2->L4 upgrade source session link)"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "u4v5w6x7y8z9"
down_revision: str | Sequence[str] | None = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agentteams_rooms",
        sa.Column("origin_ref", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agentteams_rooms", "origin_ref")
