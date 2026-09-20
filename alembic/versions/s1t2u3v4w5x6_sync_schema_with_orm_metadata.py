"""sync schema with orm metadata

补齐模型已声明但历史迁移漏建的 DB 对象：
- 索引：agent_memories.source_session、doc_audit_logs.revision_id、
  sandbox_sessions.status，以及 mas_* 一批列级 index=True 索引。
- 外键：kb_documents.created_by -> users.id。
- 列注释：announcements / festival_claims 两张表模型上的 comment。

Revision ID: s1t2u3v4w5x6
Revises: b7c8d9e0f1a2
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s1t2u3v4w5x6"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_memories_source_session", "agent_memories", ["source_session"], unique=False
    )
    op.create_index(
        "ix_doc_audit_logs_revision_id", "doc_audit_logs", ["revision_id"], unique=False
    )
    op.create_index("ix_sandbox_sessions_status", "sandbox_sessions", ["status"], unique=False)

    op.create_foreign_key(
        "fk_kb_documents_created_by", "kb_documents", "users", ["created_by"], ["id"]
    )

    op.create_index(
        "ix_mas_a2a_events_delivery_status", "mas_a2a_events", ["delivery_status"], unique=False
    )
    op.create_index("ix_mas_a2a_events_event_type", "mas_a2a_events", ["event_type"], unique=False)
    op.create_index("ix_mas_a2a_events_node_id", "mas_a2a_events", ["node_id"], unique=False)
    op.create_index("ix_mas_approvals_node_id", "mas_approvals", ["node_id"], unique=False)
    op.create_index("ix_mas_approvals_status", "mas_approvals", ["status"], unique=False)
    op.create_index("ix_mas_artifacts_node_id", "mas_artifacts", ["node_id"], unique=False)
    op.create_index(
        "ix_mas_artifacts_sha256_visibility", "mas_artifacts", ["sha256", "visibility"], unique=False
    )
    op.create_index("ix_mas_artifacts_state", "mas_artifacts", ["state"], unique=False)
    op.create_index("ix_mas_plans_created_by", "mas_plans", ["created_by"], unique=False)
    op.create_index("ix_mas_plans_run_id", "mas_plans", ["run_id"], unique=False)
    op.create_index(
        "ix_mas_rework_guards_input_artifact_id",
        "mas_rework_guards",
        ["input_artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_mas_rework_guards_target_node_id",
        "mas_rework_guards",
        ["target_node_id"],
        unique=False,
    )
    op.create_index("ix_mas_runs_session_id", "mas_runs", ["session_id"], unique=False)
    op.create_index("ix_mas_runs_workspace_id", "mas_runs", ["workspace_id"], unique=False)

    op.alter_column(
        "announcements",
        "title",
        existing_type=sa.VARCHAR(length=200),
        comment="通知标题",
        existing_nullable=False,
    )
    op.alter_column(
        "announcements",
        "description",
        existing_type=sa.TEXT(),
        comment="通知描述",
        existing_nullable=False,
    )
    op.alter_column(
        "announcements",
        "type",
        existing_type=sa.VARCHAR(length=20),
        comment="info/success/warning/feature",
        existing_nullable=False,
        existing_server_default=sa.text("'info'::character varying"),
    )
    op.alter_column(
        "announcements",
        "icon",
        existing_type=sa.VARCHAR(length=100),
        comment="emoji 或 lucide 图标名",
        existing_nullable=True,
    )
    op.alter_column(
        "announcements",
        "link",
        existing_type=sa.VARCHAR(length=500),
        comment="跳转链接（站内路径或外链）",
        existing_nullable=True,
    )
    op.alter_column(
        "announcements",
        "button_text",
        existing_type=sa.VARCHAR(length=50),
        comment="按钮文字，默认「立即查看」",
        existing_nullable=True,
    )
    op.alter_column(
        "announcements",
        "start_time",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment="生效开始时间",
        existing_nullable=False,
    )
    op.alter_column(
        "announcements",
        "end_time",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment="生效结束时间，空则永久",
        existing_nullable=True,
    )
    op.alter_column(
        "announcements",
        "dismiss_behavior",
        existing_type=sa.VARCHAR(length=20),
        comment="daily/forever/none",
        existing_nullable=False,
        existing_server_default=sa.text("'none'::character varying"),
    )
    op.alter_column(
        "announcements",
        "priority",
        existing_type=sa.INTEGER(),
        comment="优先级，越大越优先",
        existing_nullable=False,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "announcements",
        "is_enabled",
        existing_type=sa.BOOLEAN(),
        comment="是否启用",
        existing_nullable=False,
        existing_server_default=sa.text("true"),
    )

    op.alter_column(
        "festival_claims",
        "user_id",
        existing_type=sa.UUID(),
        comment="领取用户 ID",
        existing_nullable=False,
    )
    op.alter_column(
        "festival_claims",
        "festival_id",
        existing_type=sa.VARCHAR(length=50),
        comment="节日标识",
        existing_nullable=False,
    )
    op.alter_column(
        "festival_claims",
        "year",
        existing_type=sa.INTEGER(),
        comment="领取年份",
        existing_nullable=False,
    )
    op.alter_column(
        "festival_claims",
        "amount",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        comment="领取金额",
        existing_nullable=False,
        existing_server_default=sa.text("'0'::double precision"),
    )
    op.alter_column(
        "festival_claims",
        "transaction_id",
        existing_type=sa.INTEGER(),
        comment="关联饼干交易流水 ID",
        existing_nullable=True,
    )
    op.alter_column(
        "festival_claims",
        "claimed_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        comment="领取时间",
        existing_nullable=False,
    )


def downgrade() -> None:
    for table, column in (
        ("festival_claims", "claimed_at"),
        ("festival_claims", "transaction_id"),
        ("festival_claims", "amount"),
        ("festival_claims", "year"),
        ("festival_claims", "festival_id"),
        ("festival_claims", "user_id"),
        ("announcements", "is_enabled"),
        ("announcements", "priority"),
        ("announcements", "dismiss_behavior"),
        ("announcements", "end_time"),
        ("announcements", "start_time"),
        ("announcements", "button_text"),
        ("announcements", "link"),
        ("announcements", "icon"),
        ("announcements", "type"),
        ("announcements", "description"),
        ("announcements", "title"),
    ):
        op.execute(
            f"COMMENT ON COLUMN {table}.{column} IS NULL"
        )

    op.drop_index("ix_mas_runs_workspace_id", table_name="mas_runs")
    op.drop_index("ix_mas_runs_session_id", table_name="mas_runs")
    op.drop_index("ix_mas_rework_guards_target_node_id", table_name="mas_rework_guards")
    op.drop_index("ix_mas_rework_guards_input_artifact_id", table_name="mas_rework_guards")
    op.drop_index("ix_mas_plans_run_id", table_name="mas_plans")
    op.drop_index("ix_mas_plans_created_by", table_name="mas_plans")
    op.drop_index("ix_mas_artifacts_state", table_name="mas_artifacts")
    op.drop_index("ix_mas_artifacts_sha256_visibility", table_name="mas_artifacts")
    op.drop_index("ix_mas_artifacts_node_id", table_name="mas_artifacts")
    op.drop_index("ix_mas_approvals_status", table_name="mas_approvals")
    op.drop_index("ix_mas_approvals_node_id", table_name="mas_approvals")
    op.drop_index("ix_mas_a2a_events_node_id", table_name="mas_a2a_events")
    op.drop_index("ix_mas_a2a_events_event_type", table_name="mas_a2a_events")
    op.drop_index("ix_mas_a2a_events_delivery_status", table_name="mas_a2a_events")

    op.drop_constraint("fk_kb_documents_created_by", "kb_documents", type_="foreignkey")

    op.drop_index("ix_sandbox_sessions_status", table_name="sandbox_sessions")
    op.drop_index("ix_doc_audit_logs_revision_id", table_name="doc_audit_logs")
    op.drop_index("ix_agent_memories_source_session", table_name="agent_memories")
