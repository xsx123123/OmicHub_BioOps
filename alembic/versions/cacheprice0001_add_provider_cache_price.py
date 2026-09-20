"""add input/output cache price to ai_provider_configs

Revision ID: cacheprice0001
Revises: k8l9m0n1o2p3q
Create Date: 2026-09-20

工作台会话费用估算：每个模型 Provider 可配置输入/输出的缓存命中单价
（元/M tokens），缓存 tokens 按对应缓存单价计费，未命中部分按输入/输出
单价计费；NULL = 未配置，回退到用户设置页的全局缓存单价。
"""

import sqlalchemy as sa
from alembic import op

revision = "cacheprice0001"
down_revision = "k8l9m0n1o2p3q"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("input_cache_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "ai_provider_configs",
        sa.Column("output_cache_price", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_provider_configs", "output_cache_price")
    op.drop_column("ai_provider_configs", "input_cache_price")
