"""Workflow monitor service: ingest Snakemake events and build dashboard data."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Row, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.workflow_monitor import (
    WorkflowEvent,
    WorkflowEventListResponse,
    WorkflowMonitorSummary,
    WorkflowOverviewResponse,
    WorkflowTaskSnapshot,
    utc_now_iso,
)
from omichub.core.config import get_settings
from omichub.domain.task.value_objects import TaskStatus
from omichub.infrastructure.cache.pubsub import publish_task_log
from omichub.infrastructure.cache.workflow_monitor_pubsub import (
    get_task_summary,
    list_task_events,
    publish_monitor_message,
    push_task_event,
    save_task_summary,
)
from omichub.infrastructure.database.models.task import TaskModel
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.repositories.task_repository import TaskRepositoryImpl


class WorkflowMonitorService:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._task_repo = TaskRepositoryImpl(db)
        self._settings = get_settings()

    async def overview(
        self,
        *,
        current_user_id: str,
        role: str,
        status: str = "running",
        flow_id: str = "all",
        keyword: str = "",
        limit: int = 100,
    ) -> WorkflowOverviewResponse:
        rows = await self._query_task_rows(
            current_user_id=current_user_id,
            role=role,
            status=status,
            flow_id=flow_id,
            keyword=keyword,
            limit=limit,
        )
        tasks = [await self._row_to_snapshot(row) for row in rows]
        summary = await self._build_summary(current_user_id=current_user_id, role=role, tasks=tasks)
        events = await self._collect_recent_events(tasks, limit=100)
        errors = [event for event in events if event.level in {"warning", "error", "critical"}]
        if not errors:
            errors = self._failed_task_events(tasks)
        return WorkflowOverviewResponse(
            summary=summary,
            tasks=tasks,
            events=events,
            errors=errors[:30],
        )

    async def task_summary(self, task_id: str, current_user_id: str, role: str) -> WorkflowTaskSnapshot:
        row = await self._get_task_row(task_id)
        if row is None:
            from omichub.core.exceptions import NotFoundError

            raise NotFoundError("任务不存在")
        model = row[0]
        if role != "admin" and str(model.user_id) != current_user_id:
            from omichub.core.exceptions import NotFoundError

            raise NotFoundError("任务不存在")
        return await self._row_to_snapshot(row)

    async def task_events(
        self,
        task_id: str,
        current_user_id: str,
        role: str,
        levels: set[str] | None = None,
        limit: int = 200,
    ) -> WorkflowEventListResponse:
        await self.task_summary(task_id, current_user_id, role)
        events = [WorkflowEvent(**event) for event in await self._safe_list_events(task_id, limit)]
        if levels:
            events = [event for event in events if event.level in levels]
        return WorkflowEventListResponse(items=events, total=len(events))

    async def ingest_native_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._normalize_native_event(payload)
        await self._apply_event(event)
        return {"accepted": True, "events": 1}

    async def ingest_loki_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        events = self._events_from_loki_payload(payload)
        for event in events:
            await self._apply_event(event)
        return {"accepted": True, "events": len(events)}

    async def _apply_event(self, event: WorkflowEvent) -> None:
        try:
            task_uuid = UUID(str(event.task_id))
        except ValueError:
            return

        model = await self._db.get(TaskModel, task_uuid)
        if model is None:
            return

        event.flow_id = event.flow_id or model.flow_id
        event.user_id = event.user_id or str(model.user_id)

        progress_percent = self._extract_progress_percent(event)
        if progress_percent is not None:
            model.progress = max(0.0, min(1.0, progress_percent / 100.0))

        if model.status in {TaskStatus.PENDING.value, TaskStatus.QUEUED.value}:
            model.status = TaskStatus.RUNNING.value
            if model.started_at is None:
                model.started_at = datetime.now()

        if event.level in {"error", "critical"}:
            model.error_message = event.message[:2000]

        await self._task_repo.append_log(
            model.id,
            {
                "timestamp": event.timestamp or utc_now_iso(),
                "level": event.level,
                "message": event.message,
                "source": event.source,
            },
        )
        await self._db.flush()

        snapshot = self._model_to_snapshot(model, event)
        event_dict = event.model_dump(mode="json")
        snapshot_dict = snapshot.model_dump(mode="json")

        with contextlib.suppress(Exception):
            await push_task_event(str(model.id), event_dict)
            await save_task_summary(str(model.id), snapshot_dict | {"last_event_ts": time.time()})
            await publish_monitor_message(
                task_id=str(model.id),
                user_id=str(model.user_id),
                message={"type": "event", "event": event_dict},
            )
            await publish_monitor_message(
                task_id=str(model.id),
                user_id=str(model.user_id),
                message={"type": "task_snapshot", "task": snapshot_dict},
            )
            await publish_task_log(
                task_id=str(model.id),
                level=event.level,
                message=event.message,
                source=event.source,
                timestamp=event.timestamp,
            )

    async def _query_task_rows(
        self,
        *,
        current_user_id: str,
        role: str,
        status: str,
        flow_id: str,
        keyword: str,
        limit: int,
    ) -> list[Row]:
        stmt = (
            select(TaskModel, UserModel.username, UserModel.nickname)
            .outerjoin(UserModel, UserModel.id == TaskModel.user_id)
            .order_by(desc(TaskModel.created_at))
            .limit(limit)
        )
        if role != "admin":
            stmt = stmt.where(TaskModel.user_id == UUID(current_user_id))
        if status and status != "all":
            stmt = stmt.where(TaskModel.status == status)
        if flow_id and flow_id != "all":
            stmt = stmt.where(TaskModel.flow_id == flow_id)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    TaskModel.name.ilike(pattern),
                    TaskModel.flow_id.ilike(pattern),
                    TaskModel.error_message.ilike(pattern),
                )
            )
        result = await self._db.execute(stmt)
        return list(result.all())

    async def _get_task_row(self, task_id: str) -> Row | None:
        stmt = (
            select(TaskModel, UserModel.username, UserModel.nickname)
            .outerjoin(UserModel, UserModel.id == TaskModel.user_id)
            .where(TaskModel.id == UUID(task_id))
        )
        result = await self._db.execute(stmt)
        return result.first()

    async def _row_to_snapshot(self, row: Row) -> WorkflowTaskSnapshot:
        model: TaskModel = row[0]
        username = row[1]
        nickname = row[2]
        cached = await self._safe_get_summary(str(model.id))
        if cached:
            cached["username"] = username
            cached["nickname"] = nickname
            cached["name"] = model.name
            cached["status"] = model.status
            cached["progress"] = model.progress
            cached["progress_percent"] = round(model.progress * 100, 2)
            cached["last_error"] = model.error_message or cached.get("last_error", "")
            return WorkflowTaskSnapshot(**cached)
        return self._model_to_snapshot(model, None, username=username, nickname=nickname)

    async def _build_summary(
        self, *, current_user_id: str, role: str, tasks: list[WorkflowTaskSnapshot]
    ) -> WorkflowMonitorSummary:
        today = datetime.now().date()
        stmt = select(func.count(TaskModel.id)).where(
            TaskModel.status == TaskStatus.FAILED.value,
            func.date(TaskModel.created_at) == today,
        )
        if role != "admin":
            stmt = stmt.where(TaskModel.user_id == UUID(current_user_id))
        failed_today = int((await self._db.execute(stmt)).scalar_one() or 0)

        running = [task for task in tasks if task.status == TaskStatus.RUNNING.value]
        avg_progress = (
            round(sum(task.progress_percent for task in running) / len(running), 2) if running else 0.0
        )
        stale_cutoff = datetime.now() - timedelta(seconds=self._settings.workflow_monitor_stale_after_seconds)
        recent_cutoff = datetime.now() - timedelta(minutes=10)
        stale_count = 0
        warning_count = 0
        error_count = 0
        for task in running:
            if task.last_event_at:
                with contextlib.suppress(ValueError):
                    if datetime.fromisoformat(task.last_event_at.replace("Z", "")) < stale_cutoff:
                        stale_count += 1
            for item in await self._safe_list_events(task.id, 20):
                timestamp = str(item.get("timestamp") or "")
                with contextlib.suppress(ValueError):
                    if datetime.fromisoformat(timestamp.replace("Z", "")) < recent_cutoff:
                        continue
                    level = str(item.get("level") or "").lower()
                    if level == "warning":
                        warning_count += 1
                    elif level in {"error", "critical"}:
                        error_count += 1

        return WorkflowMonitorSummary(
            running_count=len(running),
            failed_today=failed_today,
            avg_running_progress=avg_progress,
            stale_task_count=stale_count,
            warning_count_10m=warning_count,
            error_count_10m=error_count,
            total=len(tasks),
        )

    async def _collect_recent_events(
        self, tasks: list[WorkflowTaskSnapshot], limit: int
    ) -> list[WorkflowEvent]:
        collected: list[WorkflowEvent] = []
        for task in tasks[:50]:
            for event in await self._safe_list_events(task.id, 5):
                collected.append(WorkflowEvent(**event))
                if len(collected) >= limit:
                    return collected
        return collected

    @staticmethod
    def _failed_task_events(tasks: list[WorkflowTaskSnapshot]) -> list[WorkflowEvent]:
        events: list[WorkflowEvent] = []
        for task in tasks:
            if task.last_error:
                events.append(
                    WorkflowEvent(
                        task_id=task.id,
                        flow_id=task.flow_id,
                        user_id=task.user_id,
                        level="error",
                        source="task",
                        timestamp=task.finished_at or task.created_at,
                        message=task.last_error,
                    )
                )
        return events

    @staticmethod
    def _model_to_snapshot(
        model: TaskModel,
        event: WorkflowEvent | None,
        *,
        username: str | None = None,
        nickname: str | None = None,
    ) -> WorkflowTaskSnapshot:
        snakemake = event.snakemake if event else {}
        return WorkflowTaskSnapshot(
            id=str(model.id),
            name=model.name,
            flow_id=model.flow_id,
            user_id=str(model.user_id),
            username=username,
            nickname=nickname,
            status=model.status,
            progress=model.progress,
            progress_percent=round(model.progress * 100, 2),
            progress_details=str(snakemake.get("progress_details") or ""),
            current_rule=str(snakemake.get("rule") or ""),
            current_job_id=snakemake.get("job_id"),
            last_event_at=event.timestamp if event else None,
            last_error=model.error_message or "",
            created_at=model.created_at.isoformat() if model.created_at else None,
            started_at=model.started_at.isoformat() if model.started_at else None,
            finished_at=model.finished_at.isoformat() if model.finished_at else None,
        )

    @staticmethod
    def _extract_progress_percent(event: WorkflowEvent) -> float | None:
        value = event.snakemake.get("progress_percent")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _safe_get_summary(self, task_id: str) -> dict[str, Any] | None:
        with contextlib.suppress(Exception):
            return await get_task_summary(task_id)
        return None

    async def _safe_list_events(self, task_id: str, limit: int) -> list[dict[str, Any]]:
        with contextlib.suppress(Exception):
            return await list_task_events(task_id, limit)
        return []

    def _normalize_native_event(self, payload: dict[str, Any]) -> WorkflowEvent:
        task_id = str(
            payload.get("task_id")
            or payload.get("omichub_task_id")
            or payload.get("project_name")
            or ""
        )
        snakemake = payload.get("snakemake") or {}
        return WorkflowEvent(
            task_id=task_id,
            flow_id=payload.get("flow_id") or payload.get("omichub_flow_id"),
            user_id=payload.get("user_id") or payload.get("omichub_user_id"),
            project_name=payload.get("project_name"),
            timestamp=payload.get("timestamp") or utc_now_iso(),
            timestamp_ns=payload.get("timestamp_ns"),
            level=str(payload.get("level") or "info").lower(),
            source=str(payload.get("source") or "snakemake"),
            message=str(payload.get("message") or payload.get("msg") or ""),
            caller=payload.get("caller"),
            snakemake=snakemake,
            runtime=payload.get("runtime") or {},
            raw=payload,
        )

    def _events_from_loki_payload(self, payload: dict[str, Any]) -> list[WorkflowEvent]:
        events: list[WorkflowEvent] = []
        for stream in payload.get("streams") or []:
            labels = stream.get("stream") or {}
            project_id = labels.get("project_id") or labels.get("project") or labels.get("project_name")
            stream_level = str(labels.get("level") or "INFO").lower()
            for ts_ns, raw in stream.get("values") or []:
                try:
                    content = json.loads(raw) if isinstance(raw, str) else raw
                except (TypeError, ValueError):
                    content = {"msg": str(raw)}
                task_id = str(
                    content.get("task_id")
                    or content.get("omichub_task_id")
                    or project_id
                    or ""
                )
                event = WorkflowEvent(
                    task_id=task_id,
                    flow_id=content.get("flow_id") or content.get("omichub_flow_id"),
                    user_id=content.get("user_id") or content.get("omichub_user_id"),
                    project_name=str(project_id) if project_id else None,
                    timestamp=self._ns_to_iso(ts_ns),
                    timestamp_ns=str(ts_ns),
                    level=str(content.get("level") or stream_level or "info").lower(),
                    source="snakemake",
                    message=str(content.get("msg") or content.get("message") or ""),
                    caller=content.get("caller"),
                    snakemake={
                        "rule": content.get("Snakemake_Rule"),
                        "job_id": content.get("Snakemake_JobId"),
                        "event_type": content.get("Event_Type"),
                        "shell_command": content.get("Shell_Command"),
                        "progress_percent": content.get("progress_percent"),
                        "progress_details": content.get("progress_details"),
                    },
                    raw=content,
                )
                events.append(event)
        return events

    @staticmethod
    def _ns_to_iso(ts_ns: Any) -> str:
        try:
            return datetime.fromtimestamp(int(ts_ns) / 1_000_000_000).isoformat()
        except (TypeError, ValueError, OSError):
            return utc_now_iso()
