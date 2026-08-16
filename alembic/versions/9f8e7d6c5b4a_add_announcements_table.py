"""add announcements table

Revision ID: 9f8e7d6c5b4a
Revises: 7ec7e0105527
Create Date: 2026-07-07 12:00:00.000000

- 新增 announcements 表：首页条幅通知，管理员后台配置
- 插入一条种子公告（RNA-seq / ATAC-seq 已就绪）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9f8e7d6c5b4a"
down_revision: Union[str, None] = "7ec7e0105527"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "type", sa.String(length=20), nullable=False, server_default="info"
        ),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("button_text", sa.String(length=50), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dismiss_behavior",
            sa.String(length=20),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "priority", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 种子公告：首页默认展示一条（固定 UUID 便于幂等重跑时先删除再插）
    # 注意：asyncpg 不允许单条 prepared statement 含多条 SQL，须拆成两个 op.execute
    op.execute(
        "DELETE FROM announcements WHERE id = '00000000-0000-0000-0000-000000000001'"
    )
    op.execute(
        """
        INSERT INTO announcements
            (id, title, description, type, icon, link, button_text,
             start_time, end_time, dismiss_behavior, priority, is_enabled,
             created_at, updated_at)
        VALUES
            ('00000000-0000-0000-0000-000000000001',
             'RNA-seq / ATAC-seq 分析已就绪',
             '转录组与表观遗传分析流程均已上线，点击立即开始',
             'success', '🎉', '/flows', '立即查看',
             now(), NULL, 'daily', 100, true,
             now(), now())
        """
    )


def downgrade() -> None:
    op.drop_table("announcements")
