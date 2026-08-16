"""add festival claims table

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
Create Date: 2026-07-09 14:58:42.214000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "t8u9v0w1x2y3"
down_revision: str | None = "s7t8u9v0w1x2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "festival_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("festival_id", sa.String(length=50), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "festival_id", "year",
            name="uq_festival_claim_user_festival_year",
        ),
    )
    op.create_index("idx_festival_claim_user", "festival_claims", ["user_id", "claimed_at"])
    op.create_index("idx_festival_claim_festival", "festival_claims", ["festival_id", "year"])


def downgrade() -> None:
    op.drop_index("idx_festival_claim_festival", table_name="festival_claims")
    op.drop_index("idx_festival_claim_user", table_name="festival_claims")
    op.drop_table("festival_claims")
