"""DTOs for the schedules and reminders API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    timezone: str = "Asia/Shanghai"
    description: str | None = None
    end_at: datetime | None = None
    recurrence_rule: str | None = Field(default=None, max_length=500)
    reminder_offsets_minutes: list[int] = Field(default_factory=lambda: [0], max_length=10)
    workspace_id: UUID | None = None
    team_id: UUID | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reminder_offsets_minutes")
    @classmethod
    def validate_offsets(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 60 * 24 * 365 for value in values):
            raise ValueError("reminder_offsets_minutes 必须在 0 到 525600 之间")
        return sorted(set(values))


class ScheduleUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str | None = None
    recurrence_rule: str | None = Field(default=None, max_length=500)
    status: str | None = None
    reminder_offsets_minutes: list[int] | None = None
    metadata_json: dict[str, Any] | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    workspace_id: UUID | None
    team_id: UUID | None
    title: str
    description: str | None
    timezone: str
    start_at: datetime
    end_at: datetime | None
    duration_seconds: int
    recurrence_rule: str | None
    next_fire_at: datetime | None
    last_fired_at: datetime | None
    status: str
    source: str
    metadata_json: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class OccurrenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    schedule_id: UUID
    occurrence_key: str
    scheduled_at: datetime
    status: str
    fired_at: datetime | None
    completed_at: datetime | None


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    schedule_id: UUID
    occurrence_id: UUID
    user_id: UUID
    channel: str
    reminder_offset_minutes: int
    due_at: datetime
    sent_at: datetime | None
    status: str
    attempt_count: int
    next_retry_at: datetime | None
    last_error: str | None
    notification_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(BaseModel):
    items: list[ScheduleResponse]
    total: int


class SnoozeRequest(BaseModel):
    minutes: int = Field(ge=1, le=60 * 24 * 30)
