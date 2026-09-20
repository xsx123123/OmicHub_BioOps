"""Celery 任务日志增强

为每个 Celery 任务自动创建独立的文本日志文件，实现「DB + WebSocket 实时流」之外的
文本备份，便于在宿主机上按任务 ID 直接 tail/grep 排查。

默认日志路径：/app/logs/celery/tasks/{task_id}.log
Docker Worker 通过 CYGNUSX_CELERY_LOG_DIR 覆盖到 /data/cygnusx/logs/celery/tasks。
"""

import os
import time
from contextlib import suppress
from pathlib import Path

from celery import Task
from loguru import logger

from cygnusx.core.telemetry import get_tracer

TASK_LOG_DIR = Path(
    os.getenv(
        "CYGNUSX_CELERY_LOG_DIR",
        str(Path(os.getenv("CYGNUSX_LOG_DIR", "/app/logs")) / "celery" / "tasks"),
    )
)
TASK_LOG_ROTATION = os.getenv("CYGNUSX_CELERY_LOG_ROTATION", "20 MB")
TASK_LOG_RETENTION = os.getenv("CYGNUSX_CELERY_LOG_RETENTION", "7 days")
TASK_LOG_COMPRESSION = os.getenv("CYGNUSX_CELERY_LOG_COMPRESSION", "zip")


def _add_task_file_sink(task_id: str) -> int | None:
    """为单个任务添加文件 sink；失败时降级为仅全局日志。"""
    try:
        TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        sink_path = TASK_LOG_DIR / f"{task_id}.log"
        return logger.add(
            sink_path,
            level="INFO",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                "{name}:{function}:{line} | {message}"
            ),
            rotation=TASK_LOG_ROTATION,
            retention=TASK_LOG_RETENTION,
            compression=TASK_LOG_COMPRESSION,
            enqueue=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Celery task file log disabled for {task_id}: {exc}")
        return None


class LoggedTask(Task):
    """Celery Task 基类：为每个任务自动创建独立日志文件。

    用法：在 Celery 应用实例中设置 task_cls=LoggedTask，所有 @shared_task
    自动继承此行为，无需逐个 task 修改。
    """

    def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        task_id = self.request.id or "no-id"
        handler_id = _add_task_file_sink(task_id)
        tracer = get_tracer("cygnusx.celery")

        try:
            with tracer.start_as_current_span(
                "celery.task",
                attributes={"task.name": self.name or "", "task.id": task_id},
            ) as span:
                start = time.perf_counter()
                status = "success"
                try:
                    logger.info(f"Task {task_id} started: {self.name}")
                    return self.run(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    status = "error"
                    span.record_exception(exc)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    span.set_attribute("task.status", status)
                    span.set_attribute("task.duration_ms", round(duration_ms, 2))
                    logger.bind(
                        event="celery.task",
                        task_name=self.name,
                        task_id=task_id,
                        status=status,
                        duration_ms=round(duration_ms, 2),
                    ).info("celery.task completed")
        finally:
            logger.info(f"Task {task_id} finished: {self.name}")
            if handler_id is not None:
                with suppress(ValueError):
                    logger.remove(handler_id)
