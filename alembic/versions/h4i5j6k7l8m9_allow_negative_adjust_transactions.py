"""allow_negative_adjust_transactions

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-07-02 22:43:12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h4i5j6k7l8m9'
down_revision: str | None = '9a5b6c7d8e1f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 管理员调账（adjust）需要同时支持充值（正数）与扣减（负数），
    # 原约束强制 adjust >= 0，导致扣减时触发数据库校验错误。
    op.drop_constraint('chk_txn_amount_sign', 'cookie_transactions', type_='check')
    op.create_check_constraint(
        'chk_txn_amount_sign',
        'cookie_transactions',
        sa.text(
            "(txn_type != 'earn' OR amount >= 0) AND "
            "(txn_type != 'refund' OR amount >= 0) AND "
            "(txn_type != 'unfreeze' OR amount >= 0) AND "
            "(txn_type NOT IN ('spend', 'freeze') OR amount <= 0)"
        ),
    )


def downgrade() -> None:
    op.drop_constraint('chk_txn_amount_sign', 'cookie_transactions', type_='check')
    op.create_check_constraint(
        'chk_txn_amount_sign',
        'cookie_transactions',
        sa.text(
            "(txn_type NOT IN ('earn', 'adjust') OR amount >= 0) AND "
            "(txn_type NOT IN ('spend', 'freeze') OR amount <= 0)"
        ),
    )
