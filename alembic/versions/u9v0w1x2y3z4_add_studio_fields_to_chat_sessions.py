"""add studio fields to chat_sessions

OmicStudio AI 分析工作台：会话支持 studio 模式（沙盒工作区绑定）。
- mode: chat / studio，默认 chat
- workspace_id: 沙盒工作区标识（通常等于 session_id）
- sandbox_meta: 沙盒运行时元数据（镜像、容器、最近活跃等，JSONB）

Revision ID: u9v0w1x2y3z4
Revises: b7e2d4a91f30
Create Date: 2026-07-16 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u9v0w1x2y3z4"
down_revision: str | None = "b7e2d4a91f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "mode",
            sa.String(length=16),
            nullable=False,
            server_default="chat",
        ),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("sandbox_meta", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        op.f("ix_chat_sessions_mode"),
        "chat_sessions",
        ["mode"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_sessions_mode"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "sandbox_meta")
    op.drop_column("chat_sessions", "workspace_id")
    op.drop_column("chat_sessions", "mode")
