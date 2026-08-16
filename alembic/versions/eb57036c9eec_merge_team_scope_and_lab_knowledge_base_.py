"""merge team scope and lab knowledge base heads

Revision ID: eb57036c9eec
Revises: a49a254e014d, s2t3u4v5w6x7
Create Date: 2026-08-15 18:01:54.631008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb57036c9eec'
down_revision: Union[str, None] = ('a49a254e014d', 's2t3u4v5w6x7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
