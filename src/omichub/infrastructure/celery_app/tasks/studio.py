"""OmicStudio Celery 任务：长时间沙盒执行与空闲沙盒回收。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import select

from omichub.core.config import get_settings
from omichub.domain.task.value_objects import LogLevel, TaskStatus
from omichub.infrastructure.cache.pubsub import publish_arq_progress, publish_task_log

logger = logging.getLogger(__name__)

_MAX_CAPTURE_CHARS = 20_000
_MAX_PERSISTED_LINES = 200


@shared_task(name="omichub.infrastructure.celery_app.tasks.studio.cleanup_expired_workspaces")
def cleanup_expired_workspaces() -> dict[str, Any]:
    """删除超过 Studio 工作区保留期的闲置工作区，报告中心产物不受影响。"""
    return asyncio.run(_cleanup_expired_workspaces())


async def _cleanup_expired_workspaces() -> dict[str, Any]:
    from omichub.application.services.studio_sharing import share_is_active
    from omichub.infrastructure.database.models.chat import ChatSessionModel
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.studio.control_client import StudioControlClient
    from omichub.infrastructure.studio.manager import studio_sandbox_manager

    config = studio_sandbox_manager._config()
    retention_days = max(1, int(config.session.workspace_retention_days))
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = 0
    skipped_shared = 0
    skipped_busy = 0
    missing = 0
    control_client = StudioControlClient()
    workspace_cleaner = (
        control_client
        if get_settings().service_name == "worker" and control_client.enabled
        else studio_sandbox_manager
    )

    async with get_session_factory()() as db:
        result = await db.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.mode == "studio",
                ChatSessionModel.updated_at < cutoff,
            )
        )
        sessions = list(result.scalars().all())
        for session in sessions:
            if share_is_active(session):
                skipped_shared += 1
                continue
            recent_activity = await studio_sandbox_manager.last_activity_at(
                session.session_id
            )
            if recent_activity is not None and recent_activity > cutoff.timestamp():
                skipped_busy += 1
                continue
            status = await workspace_cleaner.purge_workspace(session.session_id)
            if status == "busy":
                skipped_busy += 1
            elif status == "removed":
                removed += 1
            else:
                missing += 1
        await db.commit()

    return {
        "status": "ok",
        "retention_days": retention_days,
        "removed_workspaces": removed,
        "skipped_shared": skipped_shared,
        "skipped_busy": skipped_busy,
        "missing_workspaces": missing,
    }


@shared_task(name="omichub.infrastructure.celery_app.tasks.studio.run_studio_sandbox")
def run_studio_sandbox(
    *,
    task_id: str,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None = None,
) -> dict[str, Any]:
    """在 Celery worker 中执行预计超过 10 分钟的 Studio 代码。"""
    return asyncio.run(
        _run_studio_sandbox(
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
            language=language,
            code=code,
            timeout_sec=timeout_sec,
            image=image,
        )
    )


async def _run_studio_sandbox(
    *,
    task_id: str,
    user_id: str,
    session_id: str,
    language: str,
    code: str,
    timeout_sec: int,
    image: str | None,
) -> dict[str, Any]:
    from omichub.core.config import get_settings
    from omichub.domain.task.services import TaskDomainService
    from omichub.infrastructure.database.repositories.task_repository import TaskRepositoryImpl
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.studio.control_client import StudioControlClient
    from omichub.infrastructure.studio.manager import studio_sandbox_manager

    task_uuid = UUID(task_id)
    settings = get_settings()
    control_client = StudioControlClient()
    sandbox_executor = (
        control_client
        if settings.service_name == "worker" and control_client.enabled
        else studio_sandbox_manager
    )
    session_factory = get_session_factory()
    async with session_factory() as db:
        repo = TaskRepositoryImpl(db)
        domain = TaskDomainService(repo)
        task = await repo.get_by_id(task_uuid)
        if task is None:
            return {"status": "failed", "message": f"任务 {task_id} 不存在"}
        if task.status != TaskStatus.QUEUED:
            return {"status": task.status.value, "task_id": task_id}

        async def publish_progress(phase: str, progress: float, message: str) -> None:
            task.progress = max(0.0, min(1.0, progress))
            await repo.save(task)
            await db.commit()
            await publish_arq_progress(task_id, phase, task.progress, message)

        async def publish_log(level: LogLevel, message: str, source: str = "studio") -> None:
            await domain.add_log(task_uuid, level, message, source=source)
            await publish_task_log(task_id, level.value, message, source=source)

        task = await domain.transition_status(task, TaskStatus.RUNNING)
        await db.commit()
        await publish_log(LogLevel.INFO, "Studio 长任务开始执行", source="celery")
        await publish_progress("STARTING", 0.05, "正在启动 Studio 沙盒")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        result_event: dict[str, Any] = {}
        started = time.monotonic()
        last_progress_update = started

        try:
            async for event in sandbox_executor.exec(
                session_id,
                language,
                code,
                timeout_sec=timeout_sec,
                image=image,
                user_id=user_id,
            ):
                event_type = str(event.get("type") or "")
                if event_type in {"stdout", "stderr"}:
                    data = str(event.get("data") or "")
                    target = stdout_parts if event_type == "stdout" else stderr_parts
                    _append_bounded(target, data)
                    await publish_task_log(
                        task_id,
                        LogLevel.INFO.value if event_type == "stdout" else LogLevel.WARNING.value,
                        data,
                        source=f"studio_{event_type}",
                    )
                    now = time.monotonic()
                    if now - last_progress_update >= 2:
                        elapsed_ratio = min((now - started) / max(timeout_sec, 1), 1.0)
                        await publish_progress(
                            "RUNNING",
                            min(0.9, 0.1 + elapsed_ratio * 0.8),
                            f"沙盒执行中，已运行 {int(now - started)} 秒",
                        )
                        last_progress_update = now
                elif event_type == "result":
                    result_event = event

            exit_code = int(result_event.get("exit_code", -1))
            timed_out = bool(result_event.get("timed_out"))
            artifacts = result_event.get("artifacts") or []
            stdout = "\n".join(stdout_parts)
            stderr = "\n".join(stderr_parts)
            task.parameters = {
                **task.parameters,
                "studio_result": {
                    "exit_code": exit_code,
                    "duration_ms": int(result_event.get("duration_ms", 0)),
                    "timed_out": timed_out,
                    "stdout": stdout[-10_000:],
                    "stderr": stderr[-10_000:],
                    "artifacts": artifacts,
                    "output_files": result_event.get("truncated_output_files") or [],
                },
            }
            task.result_path = f"/api/v1/studio/sessions/{session_id}/artifacts"

            for line in stdout.splitlines()[-_MAX_PERSISTED_LINES:]:
                if line.strip():
                    await publish_log(LogLevel.INFO, line, source="studio_stdout")
            for line in stderr.splitlines()[-_MAX_PERSISTED_LINES:]:
                if line.strip():
                    await publish_log(LogLevel.WARNING, line, source="studio_stderr")

            if exit_code == 0 and not timed_out:
                task.progress = 1.0
                task = await repo.save(task)
                task = await domain.transition_status(task, TaskStatus.SUCCESS)
                await publish_log(LogLevel.INFO, "Studio 长任务执行完成", source="celery")
                await db.commit()
                await publish_arq_progress(task_id, "COMPLETED", 1.0, "执行完成，产物已刷新")
                return {"status": "success", "task_id": task_id, **task.parameters["studio_result"]}

            task.error_message = str(
                result_event.get("error")
                or (f"沙盒执行退出码 {exit_code}" if not timed_out else "沙盒执行超时")
            )
            task.progress = 1.0
            task = await repo.save(task)
            task = await domain.transition_status(task, TaskStatus.FAILED)
            await publish_log(LogLevel.ERROR, task.error_message, source="celery")
            await db.commit()
            await publish_arq_progress(task_id, "FAILED", 1.0, task.error_message)
            return {"status": "failed", "task_id": task_id, **task.parameters["studio_result"]}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Studio 长任务执行失败: %s", task_id)
            fresh = await repo.get_by_id(task_uuid)
            if fresh is not None and fresh.status == TaskStatus.RUNNING:
                fresh.error_message = str(exc)
                fresh.progress = 1.0
                fresh = await repo.save(fresh)
                await domain.transition_status(fresh, TaskStatus.FAILED)
                await db.commit()
            await publish_task_log(task_id, LogLevel.ERROR.value, str(exc), source="celery")
            await publish_arq_progress(task_id, "FAILED", 1.0, f"执行失败：{exc}")
            return {"status": "failed", "task_id": task_id, "error": str(exc)}


def _append_bounded(parts: list[str], value: str) -> None:
    parts.append(value)
    total = sum(len(item) for item in parts)
    while parts and total > _MAX_CAPTURE_CHARS:
        total -= len(parts.pop(0))


@shared_task(name="omichub.infrastructure.celery_app.tasks.studio.recycle_idle_sandboxes")
def recycle_idle_sandboxes() -> dict[str, Any]:
    """每 5 分钟回收空闲超 TTL 的 Studio 沙盒容器（默认 30min）。"""
    return asyncio.run(_run_recycle())


async def _run_recycle() -> dict[str, Any]:
    from omichub.core.config import get_settings
    from omichub.infrastructure.studio.control_client import StudioControlClient
    from omichub.infrastructure.studio.manager import studio_sandbox_manager

    try:
        control_client = StudioControlClient()
        if get_settings().service_name == "worker" and control_client.enabled:
            count = await control_client.recycle_idle()
        else:
            count = await studio_sandbox_manager.recycle_idle()
        if count:
            logger.info("[Studio] 回收空闲沙盒 %s 个", count)
        return {"recycled": count}
    except Exception as exc:  # noqa: BLE001
        logger.error("[Studio] 空闲沙盒回收失败: %s", exc)
        return {"recycled": 0, "error": str(exc)}
