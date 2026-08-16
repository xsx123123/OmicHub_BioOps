"""Cherry Studio 架构聊天系统 ORM 模型

对应 Cherry Studio 的 Topic(Session) + Message + Assistant 三层结构。
会话绑定 ai_provider_configs（复用现有 Provider 配置表，PK 为 UUID）。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from omichub.infrastructure.database.base import Base, TimestampMixin


class ChatSessionModel(Base, TimestampMixin):
    """聊天会话表（对应 Cherry Studio 的 Topic）"""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    assistant_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("chat_assistants.assistant_id"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("agent_templates.agent_id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    title_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_provider_configs.id"), nullable=False
    )

    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ===== OmicStudio AI 分析工作台 =====
    # mode: chat（普通对话）/ studio（工作台会话）；studio 会话绑定沙盒工作区
    mode: Mapped[str] = mapped_column(String(16), default="chat", nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sandbox_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    share_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    share_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["ChatMessageModel"]] = relationship(
        "ChatMessageModel",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.created_at",
    )

    __table_args__ = (Index("idx_chat_sessions_user_updated", "user_id", "updated_at"),)


class AgentTeamsCaseCursorModel(Base, TimestampMixin):
    """聊天会话中 AgentTeams Case 的事件游标与通知去重状态。"""

    __tablename__ = "agentteams_case_cursors"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_cursor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notified_statuses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("session_id", "case_id", name="uq_agentteams_case_cursors_session_case"),
        Index("ix_agentteams_case_cursors_session_id", "session_id"),
    )


class ChatMessageModel(Base):
    """聊天消息表"""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="complete", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSessionModel | None] = relationship(
        "ChatSessionModel", back_populates="messages"
    )

    __table_args__ = (Index("idx_chat_messages_session_created", "session_id", "created_at"),)


class ChatMessageFeedbackModel(Base):
    """用户对 AI 消息的点赞/点踩反馈。

    点踩时会把当时的模型、Agent、回复与提问摘录等快照进 context，
    供管理员在「会话日志排查 → 用户会话反馈」里做提示词 / Agent / 架构优化分析。
    """

    __tablename__ = "chat_message_feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feedback_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_chat_feedbacks_message_user", "message_id", "user_id", unique=True),
        Index("idx_chat_feedbacks_created", "created_at"),
    )


class ChatHandoffEventModel(Base):
    """同一聊天会话内 Agent 转交的可审计事件。"""

    __tablename__ = "chat_handoff_events"
    __table_args__ = (Index("idx_chat_handoff_session_created", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_agent_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_agent_id: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    handoff_summary: Mapped[str] = mapped_column(Text, nullable=False)
    user_intent: Mapped[str] = mapped_column(Text, nullable=False)
    artifacts: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    constraints: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    hop_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollaborationDegradationEventModel(Base):
    """Records a disabled collaboration capability selected by the unified router."""

    __tablename__ = "collaboration_degradation_events"
    __table_args__ = (
        Index("idx_collab_degradation_intent_created", "intent", "created_at"),
        Index("idx_collab_degradation_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    intent: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatAssistantModel(Base, TimestampMixin):
    """AI 助手表（对应 Cherry Studio 的 Assistant）"""

    __tablename__ = "chat_assistants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assistant_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    default_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_provider_configs.id"), nullable=True
    )
    default_temperature: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    default_max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)

    icon: Mapped[str] = mapped_column(String(10), default="\U0001f916", nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#4f8ef7", nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (Index("idx_chat_assistants_category", "category", "is_active"),)
