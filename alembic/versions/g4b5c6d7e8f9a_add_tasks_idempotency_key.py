"""add tasks.idempotency_key (Studio 长任务 job 幂等键)

Revision ID: g4b5c6d7e8f9a
Revises: f3a4b5c6d7e8
Create Date: 2026-09-18

WP2 任务4：Studio 长任务（>600s 转 Celery）的 job 行即 tasks 行。
幂等键复用现有 command_id 语义（调用方可显式传 command_id，缺省由
服务端按 user/session/代码内容派生），UNIQUE 索引保证并发同键提交
只有一行落库；存量行全部为 NULL，PostgreSQL UNIQUE 允许多个 NULL，
对既有数据零影响。
"""

import sqlalchemy as sa
from alembic import op

revision = "g4b5c6d7e8f9a"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "uq_tasks_idempotency_key",
        "tasks",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_idempotency_key", table_name="tasks")
    op.drop_column("tasks", "idempotency_key")
