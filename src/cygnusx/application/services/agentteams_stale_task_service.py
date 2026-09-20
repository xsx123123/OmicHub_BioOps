"""Recover analysis tasks that stayed queued without ever starting."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.flow_service import FlowService
from cygnusx.core.exceptions import NotFoundError
from cygnusx.domain.task.value_objects import TaskStatus
from cygnusx.infrastructure.celery_app.tasks.analysis import run_snakemake
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.infrastructure.task_queue.dispatcher import enqueue_task

_WATCHDOG_ATTEMPTS_KEY = "_agentteams_watchdog_requeue_attempts"
_WATCHDOG_SOURCE = "agentteams-watchdog"


class AgentTeamsStaleTaskService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        flow_service: FlowService | None = None,
        enqueue: Callable[..., Any] = enqueue_task,
    ) -> None:
        self._db = db
        self._flow_service = flow_service or FlowService()
        self._enqueue = enqueue

    async def scan(
        self, *, stale_after_seconds: int = 600, now: datetime | None = None
    ) -> dict[str, int]:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(seconds=stale_after_seconds)
        result = await self._db.scalars(
            select(TaskModel)
            .where(
                TaskModel.status == TaskStatus.QUEUED.value,
                TaskModel.started_at.is_(None),
                TaskModel.updated_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        summary = {"scanned": 0, "requeued": 0, "failed": 0, "skipped": 0}
        for task in result.all():
            summary["scanned"] += 1
            outcome = await self._handle_task(task, current)
            summary[outcome] += 1
        return summary

    async def _handle_task(self, task: TaskModel, now: datetime) -> str:
        try:
            flow_config = self._flow_service.get_flow_config(task.flow_id)
            flow_detail = self._flow_service.get_flow(task.flow_id)
        except NotFoundError:
            await self._mark_failed(
                task,
                now,
                f"任务无法自动重投：流程 {task.flow_id} 不存在或已停用。",
            )
            return "failed"

        parameters = dict(task.parameters or {})
        attempts = int(parameters.get(_WATCHDOG_ATTEMPTS_KEY) or 0)
        if attempts >= 1:
            await self._mark_failed(task, now, "任务重投后仍未被 Worker 消费，已由看门狗标记失败。")
            return "failed"

        config_file = Path(task.work_dir) / flow_config.execution.config_file_name
        if not task.work_dir or not config_file.is_file():
            await self._mark_failed(task, now, f"任务重投失败：配置文件不存在：{config_file}")
            return "failed"

        parameters[_WATCHDOG_ATTEMPTS_KEY] = attempts + 1
        task.parameters = parameters
        task.updated_at = now
        self._append_log(task, now, "检测到 queued 超时，正在执行唯一一次自动重投。", "warning")
        await self._db.flush()
        await self._db.commit()

        try:
            self._enqueue(
                run_snakemake,
                flow_detail.execution["snakefile"],
                str(task.id),
                task_id=f"analysis-{task.id}-attempt-{attempts + 1}",
                config_file=str(config_file),
                config_file_param=flow_detail.execution.get("config_file_param") or "analysisyaml",
                work_dir=task.work_dir,
                cores=flow_detail.execution.get("default_resources", {}).get("cores", 4),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("AgentTeams stale task requeue failed: {}", task.id)
            await self._mark_failed(task, now, f"任务自动重投失败：{exc}")
            return "failed"
        return "requeued"

    async def _mark_failed(self, task: TaskModel, now: datetime, message: str) -> None:
        task.status = TaskStatus.FAILED.value
        task.finished_at = now
        task.updated_at = now
        task.error_message = message
        self._append_log(task, now, message, "error")
        await self._db.flush()
        await self._db.commit()

    @staticmethod
    def _append_log(task: TaskModel, now: datetime, message: str, level: str) -> None:
        logs = list(task.logs or [])
        logs.append(
            {
                "timestamp": now.isoformat(),
                "level": level,
                "message": message,
                "source": _WATCHDOG_SOURCE,
            }
        )
        task.logs = logs


__all__ = ["AgentTeamsStaleTaskService"]
