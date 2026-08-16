"""add blast database version activation fields

Revision ID: b7e2d4a91f30
Revises: 9c57efc91c12
Create Date: 2026-07-15 10:49:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4a91f30"
down_revision: str | None = "9c57efc91c12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blast_databases",
        sa.Column("version_group", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "blast_databases",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("UPDATE blast_databases SET version_group = db_key")
    op.execute(
        "UPDATE blast_databases SET is_active = TRUE "
        "WHERE build_status = 'ready' AND is_public = TRUE"
    )
    op.alter_column("blast_databases", "version_group", nullable=False)
    op.create_index(
        op.f("ix_blast_databases_version_group"),
        "blast_databases",
        ["version_group"],
        unique=False,
    )
    op.create_index(
        op.f("ix_blast_databases_is_active"),
        "blast_databases",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_blast_databases_is_active"), table_name="blast_databases")
    op.drop_index(op.f("ix_blast_databases_version_group"), table_name="blast_databases")
    op.drop_column("blast_databases", "is_active")
    op.drop_column("blast_databases", "version_group")
