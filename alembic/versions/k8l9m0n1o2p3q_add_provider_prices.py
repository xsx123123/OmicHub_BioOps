"""add input/output price to ai_provider_configs

Revision ID: k8l9m0n1o2p3q
Revises: h5i6j7k8l9m0
Create Date: 2026-09-20

工作台会话费用估算：每个模型 Provider 可配置输入/输出单价（元/M tokens），
NULL = 未配置，回退到用户设置页的全局单价。
"""

import sqlalchemy as sa
from alembic import op

revision = "k8l9m0n1o2p3q"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("input_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "ai_provider_configs",
        sa.Column("output_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_provider_configs", "output_price")
    op.drop_column("ai_provider_configs", "input_price")
