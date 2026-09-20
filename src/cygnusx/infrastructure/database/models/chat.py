"""Cherry Studio 架构聊天系统 ORM 模型

对应 Cherry Studio 的 Topic(Session) + Message + Assistant 三层结构。
会话绑定 ai_provider_configs（复用现有 Provider 配置表，PK 为 UUID）。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cygnusx.infrastructure.database.base import Base, TimestampMixin


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
    last_settled_message_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
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

    __table_args__ = (
        UniqueConstraint("session_id", name="chat_sessions_session_id_key"),
        Index("idx_chat_sessions_user_updated", "user_id", "updated_at"),
    )


class AgentTeamsRoomModel(Base, TimestampMixin):
    """AgentTeams 协作室房间：持久的轻量会话实体（会话-工单解耦，Part 2）。

    房间先于 Case 存在：纯聊天/澄清阶段只有房间，``case_id`` 为 NULL；
    用户在房间内确认立项卡后才创建正式 Case 并回写绑定。房间级事件流
    承载于 Bridge 的 room 命名空间记录（case_id 形如 ``room-<room_id>``）。
    ``proposal`` 保存当前待确认的立项卡（含一次性 confirm_token）。
    ``origin_ref`` 记录来源引用（如 L2→L4 升级时来源 L2 会话 id；
    ``origin`` 仅 20 字符放不下，故单列）。
    """

    __tablename__ = "agentteams_rooms"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    room_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default="协作室会话", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    origin_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    matrix_room_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("room_id", name="uq_agentteams_rooms_room_id"),
        Index("idx_agentteams_rooms_owner_updated", "owner_id", "updated_at"),
    )


class AgentTeamsRoomMemberModel(Base, TimestampMixin):
    """协作室邀请与已接受成员；owner 始终由 ``AgentTeamsRoomModel.owner_id`` 表示。"""

    __tablename__ = "agentteams_room_members"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    room_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    invited_by: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_agentteams_room_members_room_user"),
        Index("idx_agentteams_room_members_user_status", "user_id", "status"),
    )


class AgentTeamsTurnRecordModel(Base):
    """Case 每次 LLM 调用的可查询摘要，全文由 ``s3_uri`` 指向 MinIO。"""

    __tablename__ = "agentteams_turn_records"

    record_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    call_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    requester_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    s3_uri: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "work_item_id",
            "round_number",
            "call_seq",
            name="uq_agentteams_turn_records_call",
        ),
        Index("idx_agentteams_turn_records_case_work_round", "case_id", "work_item_id", "round_number"),
    )


class CaseArtifactVersionModel(Base, TimestampMixin):
    """协作室产物版本行（产物血缘 F1）：每次产物登记强制写一行。

    ``artifact_id`` 是 Case 内逻辑名（``{work_item_id}/{相对路径}``），同一
    (case_id, artifact_id) 重复登记时 ``version_no`` 递增；行 id 即对外的
    version_id（血缘清单/交付 manifest 引用它，避免同名文件歧义）。
    ``producing_event_id`` 指向触发本次登记的审计事件（复用 causation 因果链）。
    ``environment_snapshot`` 只记可复现最小事实（执行 agent、平台版本/git sha、
    执行摘要），不做 ENVS 声明式环境抽象。
    """

    __tablename__ = "case_artifact_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    artifact_id: Mapped[str] = mapped_column(String(512), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    producing_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    work_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    environment_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "artifact_id",
            "version_no",
            name="uq_case_artifact_versions_case_artifact_version",
        ),
        Index("ix_case_artifact_versions_checksum", "checksum_sha256"),
    )


class CaseArtifactDependencyModel(Base, TimestampMixin):
    """协作室产物依赖边（产物血缘 F1）：下游产物 ← 上游产物 的 DAG 边。"""

    __tablename__ = "case_artifact_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    downstream_artifact_id: Mapped[str] = mapped_column(String(512), nullable=False)
    upstream_artifact_id: Mapped[str] = mapped_column(String(512), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), default="input_to", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "downstream_artifact_id",
            "upstream_artifact_id",
            "relation",
            name="uq_case_artifact_dependencies_edge",
        ),
        Index(
            "ix_case_artifact_dependencies_upstream",
            "case_id",
            "upstream_artifact_id",
        ),
    )


class QcVerificationCheckModel(Base, TimestampMixin):
    """agent-qc 结构化判决行（证据化验收 F2）：每条 claim 的核查判决一行。

    qc 会诊输出的 checks[] 逐行落库，判决因此可统计（pass/warn/fail 分布、
    与后续返工率交叉验证）、可复核（claim_snapshot 留存断言原文快照）。
    ``claim_hash`` 是断言内容指纹（statement+location+claim_type 的 sha256），
    同一断言重复核查时可按 hash 聚合；``evidence_event_id`` 是指向审计事件或
    产物血缘 version_id 的字符串指针。权威 schema 见
    ``cygnusx.application.schemas.qc_verification``。
    """

    __tablename__ = "qc_verification_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    claim_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer_agent: Mapped[str] = mapped_column(String(80), nullable=False)
    claim_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    __table_args__ = (Index("ix_qc_verification_checks_case_verdict", "case_id", "verdict"),)


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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

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
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="complete", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSessionModel | None] = relationship(
        "ChatSessionModel", back_populates="messages"
    )

    __table_args__ = (
        UniqueConstraint("message_id", name="chat_messages_message_id_key"),
        Index("idx_chat_messages_session_created", "session_id", "created_at"),
        Index(
            "uq_chat_messages_matrix_event",
            "session_id",
            text("(metadata_json ->> 'matrix_event_id')"),
            unique=True,
            postgresql_where=text("(metadata_json ->> 'matrix_event_id') IS NOT NULL"),
        ),
    )


class ChatMessageEventModel(Base):
    """AI 消息过程态事件表（append-only）。

    WP2：流式执行期间逐 chunk 追加 tool_output 等过程事件，(message_id, seq)
    联合主键保证消息内单调有序；代码层只提供插入与查询，不提供更新/删除路径。
    历史重建时按 message_id 回放事件还原工具卡过程输出，无事件的旧消息
    完全回落 metadata_json.tool_invocations 终态快照。
    """

    __tablename__ = "chat_message_events"

    message_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )


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
    default_max_tokens: Mapped[int] = mapped_column(Integer, default=65536, nullable=False)

    icon: Mapped[str] = mapped_column(String(10), default="\U0001f916", nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#4f8ef7", nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("assistant_id", name="chat_assistants_assistant_id_key"),
        Index("ix_chat_assistants_category", "category", "is_active"),
    )
