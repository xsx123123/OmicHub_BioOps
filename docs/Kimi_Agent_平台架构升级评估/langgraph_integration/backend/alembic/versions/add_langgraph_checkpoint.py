"""
Alembic 迁移: 添加 LangGraph 检查点和 HITL 表
================================================

表:
    - langgraph_checkpoints     LangGraph 状态检查点
    - langgraph_checkpoint_writes   检查点写入操作
    - hitl_requests             HITL 中断请求
    - hitl_responses            HITL 人工响应
    - hitl_history              HITL 历史记录

升级: alembic upgrade head
降级: alembic downgrade -1
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "lg1_langgraph_20260706"
down_revision = None  # 根据你的迁移链调整
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. langgraph_checkpoints ──
    op.create_table(
        "langgraph_checkpoints",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(64), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(64), nullable=True),
        sa.Column("checkpoint", sa.LargeBinary, nullable=False),
        sa.Column("metadata_", sa.LargeBinary, nullable=True),
        sa.Column("user_id", sa.Integer, nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("updated_at", sa.Float, nullable=False),
        sa.UniqueConstraint("thread_id", "checkpoint_ns", "checkpoint_id", name="uix_ckpt_thread_checkpoint"),
    )
    op.create_index("idx_ckpt_user", "langgraph_checkpoints", ["user_id", "created_at"])
    op.create_index("idx_ckpt_session", "langgraph_checkpoints", ["session_id", "created_at"])
    op.create_index("idx_ckpt_status", "langgraph_checkpoints", ["status", "created_at"])

    # ── 2. langgraph_checkpoint_writes ──
    op.create_table(
        "langgraph_checkpoint_writes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(64), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("task_path", sa.String(64), nullable=False, server_default=""),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("value", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_index("idx_ckptwrt_thread", "langgraph_checkpoint_writes", ["thread_id", "checkpoint_ns", "checkpoint_id"])

    # ── 3. hitl_requests ──
    op.create_table(
        "hitl_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("hitl_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("timeout_seconds", sa.Integer, nullable=False, server_default="300"),
        sa.Column("responded_at", sa.Float, nullable=True),
    )
    op.create_index("idx_hitl_user_pending", "hitl_requests", ["user_id", "status"])
    op.create_index("idx_hitl_thread", "hitl_requests", ["thread_id"])
    op.create_index("idx_hitl_session", "hitl_requests", ["session_id", "created_at"])

    # ── 4. hitl_responses ──
    op.create_table(
        "hitl_responses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("human_input", sa.Text, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("responded_by", sa.Integer, nullable=False),
        sa.Column("responded_at", sa.Float, nullable=False),
    )

    # ── 5. hitl_history ──
    op.create_table(
        "hitl_history",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("hitl_type", sa.String(32), nullable=False),
        sa.Column("request_payload", sa.Text, nullable=False),
        sa.Column("response_action", sa.String(20), nullable=False),
        sa.Column("response_input", sa.Text, nullable=False),
        sa.Column("latency_seconds", sa.Float, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
    )
    op.create_index("idx_hithist_user", "hitl_history", ["user_id", "created_at"])
    op.create_index("idx_hithist_thread", "hitl_history", ["thread_id"])


def downgrade() -> None:
    op.drop_index("idx_hithist_thread", "hitl_history")
    op.drop_index("idx_hithist_user", "hitl_history")
    op.drop_table("hitl_history")

    op.drop_table("hitl_responses")

    op.drop_index("idx_hitl_session", "hitl_requests")
    op.drop_index("idx_hitl_thread", "hitl_requests")
    op.drop_index("idx_hitl_user_pending", "hitl_requests")
    op.drop_table("hitl_requests")

    op.drop_index("idx_ckptwrt_thread", "langgraph_checkpoint_writes")
    op.drop_table("langgraph_checkpoint_writes")

    op.drop_index("idx_ckpt_status", "langgraph_checkpoints")
    op.drop_index("idx_ckpt_session", "langgraph_checkpoints")
    op.drop_index("idx_ckpt_user", "langgraph_checkpoints")
    op.drop_table("langgraph_checkpoints")
