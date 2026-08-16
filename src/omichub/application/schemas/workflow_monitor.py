"""Workflow monitor DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from omichub.application.schemas.base import OmicsHubBaseSchema


class MonitorTemplateListItem(OmicsHubBaseSchema):
    id: str
    name: str
    version: str = "1.0.0"
    scope: str = "user"
    description: str = ""


class MonitorTemplateListResponse(OmicsHubBaseSchema):
    items: list[MonitorTemplateListItem]
    total: int


class MonitorTemplateResponse(OmicsHubBaseSchema):
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    scope: str = "user"
    refresh: dict[str, Any] = {}
    permissions: dict[str, Any] = {}
    filters: list[dict[str, Any]] = []
    layout: dict[str, Any] = {}
    widgets: list[dict[str, Any]] = []


class WorkflowMonitorSummary(OmicsHubBaseSchema):
    running_count: int = 0
    failed_today: int = 0
    avg_running_progress: float = 0.0
    stale_task_count: int = 0
    warning_count_10m: int = 0
    error_count_10m: int = 0
    total: int = 0


class WorkflowTaskSnapshot(OmicsHubBaseSchema):
    id: str
    name: str
    flow_id: str
    user_id: str
    username: str | None = None
    nickname: str | None = None
    status: str
    progress: float
    progress_percent: float
    progress_details: str = ""
    current_rule: str = ""
    current_job_id: int | None = None
    last_event_at: str | None = None
    last_error: str = ""
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class WorkflowEvent(OmicsHubBaseSchema):
    schema_version: str = "omichub.workflow_event.v1"
    task_id: str
    flow_id: str | None = None
    user_id: str | None = None
    project_name: str | None = None
    timestamp: str | None = None
    timestamp_ns: str | None = None
    level: str = "info"
    source: str = "snakemake"
    message: str
    caller: str | None = None
    snakemake: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    raw: dict[str, Any] = {}


class WorkflowOverviewResponse(OmicsHubBaseSchema):
    summary: WorkflowMonitorSummary
    tasks: list[WorkflowTaskSnapshot]
    events: list[WorkflowEvent]
    errors: list[WorkflowEvent]


class WorkflowEventListResponse(OmicsHubBaseSchema):
    items: list[WorkflowEvent]
    total: int


class WorkflowMonitorWsMessage(OmicsHubBaseSchema):
    type: Literal["event", "task_snapshot", "summary", "error", "pong"]
    event: WorkflowEvent | None = None
    task: WorkflowTaskSnapshot | None = None
    summary: WorkflowMonitorSummary | None = None
    detail: str | None = None


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
