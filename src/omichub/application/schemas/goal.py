"""API contracts for the persistent Goal runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from omichub.application.schemas.base import OmicsHubBaseSchema


class GoalStartRequest(OmicsHubBaseSchema):
    objective: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(min_length=1, max_length=50)
    manager_agent_id: str = Field(default="agent-general", max_length=128)
    success_criteria: list[Any] = Field(default_factory=list)
    mode: str = Field(default="chat", max_length=32)
    permission: str = Field(default="safe", max_length=32)
    max_turns: int = Field(default=20, ge=1, le=1000)
    token_budget: int | None = Field(default=None, ge=1)
    deadline_at: datetime | None = None


class GoalControlRequest(OmicsHubBaseSchema):
    reason: str = Field(default="", max_length=2000)


class GoalAnswerRequest(OmicsHubBaseSchema):
    answer: str = Field(min_length=1, max_length=10000)


class GoalResponse(OmicsHubBaseSchema):
    id: UUID
    session_id: str | None
    user_id: UUID
    manager_agent_id: str
    objective: str
    success_criteria: list[Any]
    mode: str
    permission: str
    status: str
    plan_snapshot: dict[str, Any]
    turn_count: int
    max_turns: int
    token_budget: int | None
    tokens_used: int
    deadline_at: datetime | None
    version: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GoalEventResponse(OmicsHubBaseSchema):
    id: UUID
    goal_id: UUID
    sequence: int
    event_type: str
    dedupe_key: str | None = None
    payload: dict[str, Any]
    created_at: datetime


class GoalEventPage(OmicsHubBaseSchema):
    items: list[GoalEventResponse]
    next_cursor: int | None = None


def goal_to_response(goal: Any) -> GoalResponse:
    return GoalResponse.model_validate(goal, from_attributes=True)


def event_to_response(event: Any) -> GoalEventResponse:
    return GoalEventResponse.model_validate(event, from_attributes=True)
