"""add customer to projects

项目增加 customer（客户）字段：记录项目归属客户/课题组，可选，默认空串。

Revision ID: a6b7c8d9e0f1
Revises: y8z9a0b1c2d3
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "y8z9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "customer",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "customer")
