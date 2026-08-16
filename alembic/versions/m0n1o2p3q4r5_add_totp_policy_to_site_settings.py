"""add_totp_policy_to_site_settings

Revision ID: m0n1o2p3q4r5
Revises: l9m0n1o2p3q4
Create Date: 2026-07-05 00:03:25.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'm0n1o2p3q4r5'
down_revision: str | None = 'l9m0n1o2p3q4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'site_settings',
        sa.Column('totp_policy', sa.String(length=16), server_default=sa.text("'optional'"), nullable=False),
    )
    # 同步已存在行（部分数据库 server_default 不自动回填）
    op.execute("UPDATE site_settings SET totp_policy = 'optional' WHERE totp_policy IS NULL OR totp_policy = ''")


def downgrade() -> None:
    op.drop_column('site_settings', 'totp_policy')
