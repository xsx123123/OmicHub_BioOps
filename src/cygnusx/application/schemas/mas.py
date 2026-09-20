"""Request and response schemas for MAS run metadata APIs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema
from cygnusx.domain.mas.models import ExecutionPlan, MASArtifact


class MASRunCreateRequest(CygnusXBaseSchema):
    plan: ExecutionPlan
    context_summary: dict[str, Any] = Field(default_factory=dict)
    session_id: UUID | None = None
    workspace_id: UUID | None = None
    project_id: str | None = Field(None, max_length=64)


class MASRunResponse(CygnusXBaseSchema):
    id: UUID
    plan_id: UUID
    status: str
    version: int
    context_summary: dict[str, Any]
    project_id: str | None = None
    created_at: datetime
    finished_at: datetime | None


class MASArtifactRegisterRequest(CygnusXBaseSchema):
    artifact: MASArtifact


class MASArtifactResponse(CygnusXBaseSchema):
    id: UUID
    logical_name: str
    kind: str
    workspace_path: str
    media_type: str
    size_bytes: int
    sha256: str
    state: str
    version: int
    project_id: str | None = None
    created_at: datetime


class MASNodeProgressResponse(CygnusXBaseSchema):
    key: str
    agent_id: str
    intent: str
    status: str
    attempt_count: int


class MASRunProgressResponse(CygnusXBaseSchema):
    run_id: UUID
    status: str
    version: int
    nodes: list[MASNodeProgressResponse]


class MASApprovalResolveRequest(CygnusXBaseSchema):
    approved: bool
    response: dict[str, Any] = Field(default_factory=dict)


class MASApprovalResponse(CygnusXBaseSchema):
    id: UUID
    node_key: str | None
    kind: str
    prompt: str
    options: list[dict[str, Any]]
    status: str
    response: dict[str, Any] | None
    created_at: datetime
