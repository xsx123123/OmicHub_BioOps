"""merge_cookie_adjust_heads

Revision ID: i6j7k8l9m0n1
Revises: h4i5j6k7l8m9, g3h4i5j6k7l8
Create Date: 2026-07-02 22:50:00

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'i6j7k8l9m0n1'
down_revision: str | Sequence[str] | None = ('h4i5j6k7l8m9', 'g3h4i5j6k7l8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
