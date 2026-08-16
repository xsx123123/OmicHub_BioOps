"""add cookie pricing sample cost columns

Revision ID: l9m0n1o2p3q4
Revises: k8l9m0n1o2p3
Create Date: 2026-07-04 16:00:00.000000

- cookie_pricing 表新增 per_sample_cost 和 per_comparison_cost 列
- 更新 chk_pricing_unit 约束以支持 per_sample 和 per_comparison
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l9m0n1o2p3q4"
down_revision: str | None = "k8l9m0n1o2p3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cookie_pricing",
        sa.Column("per_sample_cost", sa.Numeric(10, 4), server_default="0"),
    )
    op.add_column(
        "cookie_pricing",
        sa.Column("per_comparison_cost", sa.Numeric(10, 4), server_default="0"),
    )
    op.drop_constraint("chk_pricing_unit", "cookie_pricing", type_="check")
    op.create_check_constraint(
        "chk_pricing_unit",
        "cookie_pricing",
        "unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', "
        "'per_session', 'per_user', 'per_sample', 'per_comparison')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_pricing_unit", "cookie_pricing", type_="check")
    op.create_check_constraint(
        "chk_pricing_unit",
        "cookie_pricing",
        "unit IN ('per_task', 'per_hour', 'per_core_hour', 'per_gb_hour', "
        "'per_session', 'per_user')",
    )
    op.drop_column("cookie_pricing", "per_comparison_cost")
    op.drop_column("cookie_pricing", "per_sample_cost")
