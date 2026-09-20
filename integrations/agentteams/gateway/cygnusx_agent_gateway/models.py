"""Public Gateway contracts; raw CygnusX sessions and tool traces never cross this boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCIENTIFIC_INTERPRETATION_SCHEMA_VERSION = "1.0"
ConsultationStatus = Literal["completed", "manual_review", "rejected"]


class ConsultationRequest(BaseModel):
    """Manager request limited to logical references and an approved read-only capability."""

    case_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=8_000)
    capability: Literal[
        "interpretation",
        "planning_advice",
        "result_interpretation",
        "qc_advice",
        "project-preflight",
        "quality-gate",
        "delivery-pack",
        "workspace_execution",
    ]
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    requested_tools: list[str] = Field(default_factory=list, max_length=20)
    requester_ref: str = Field(min_length=1, max_length=256)
    work_item_id: str | None = Field(default=None, min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, min_length=1, max_length=128)
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = (
        "readonly_consultation"
    )


class ConsultationError(BaseModel):
    code: str
    message: str
    retry_after_seconds: int | None = None


class ScientificInterpretationResponse(BaseModel):
    """Fixed output envelope exposed to AgentTeams Manager."""

    schema_version: str = SCIENTIFIC_INTERPRETATION_SCHEMA_VERSION
    status: ConsultationStatus
    conclusion: str
    recommendations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    agent_id: str
    schema_ver: str = SCIENTIFIC_INTERPRETATION_SCHEMA_VERSION
    duration_ms: int = 0
    token_usage: int = 0
    error: ConsultationError | None = None
    proposed_submission: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    hard_gate: dict[str, Any] | None = None


class UpstreamConsultationResponse(BaseModel):
    conclusion: str
    recommendations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    token_usage: int = 0
    proposed_submission: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    hard_gate: dict[str, Any] | None = None


class RoomCreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    identities: list[str] = Field(default_factory=list, max_length=32)


class EnsureUsersRequest(BaseModel):
    identities: list[str] = Field(min_length=1, max_length=64)


class ElementSessionRequest(BaseModel):
    """为 AppService 持有的身份申请一个 Element Web 免登录会话。"""

    identity: str = Field(min_length=1, max_length=128)
    # 携带房间 id 时先幂等入房：仅 invited 未 joined 的房间在 Element 深链下会卡黑屏。
    room_id: str | None = Field(default=None, max_length=255)


class ElementSessionResponse(BaseModel):
    """Element 会话凭据；access_token 仅经本响应交给 CygnusX 主后端，不落日志。"""

    user_id: str
    device_id: str
    access_token: str
    homeserver_url: str
    element_base_url: str | None = None


class RoomLeaveRequest(BaseModel):
    """让 AppService 持有的身份离开指定 Matrix 房间（删除协作室时调用）。"""

    identity: str = Field(min_length=1, max_length=128)
    room_id: str = Field(min_length=1, max_length=255)


class RoomCreateResponse(BaseModel):
    room_id: str
    room_name: str
    element_room_url: str | None = None


class RoomMessageRequest(BaseModel):
    sender_identity: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=32_000)
    sender: dict[str, Any] = Field(default_factory=dict)
    source: Literal["cygnusx", "external"] = "cygnusx"


class RoomMessage(BaseModel):
    event_id: str
    room_id: str
    sender_identity: str | None = None
    sender_matrix_id: str | None = None
    content: str
    origin: Literal["cygnusx", "external"] = "external"
    sender: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class RoomMessagesResponse(BaseModel):
    events: list[RoomMessage] = Field(default_factory=list)
    next_batch: str | None = None
