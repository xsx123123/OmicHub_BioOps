"""Single task submission API for Celery and RocketMQ coexistence."""

from __future__ import annotations

import fnmatch
import uuid
from typing import Any

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.task_queue.rocketmq import QueuedTask, publish_task, store_task_state


def _uses_rocketmq(task_name: str) -> bool:
    settings = get_settings()
    if settings.task_queue_backend == "rocketmq":
        return True
    if settings.task_queue_backend == "celery":
        return False
    return any(fnmatch.fnmatchcase(task_name, pattern) for pattern in settings.rocketmq_task_routes)


def enqueue_task(
    task: Any,
    *args: Any,
    task_id: str | None = None,
    queue: str | None = None,
    countdown: int | float | None = None,
    **kwargs: Any,
) -> Any:
    """Queue a registered task through the configured transport.

    ``hybrid`` mode routes only tasks matching ``ROCKETMQ_TASK_ROUTES`` to
    RocketMQ. All other tasks stay on Celery, so the two worker fleets can run
    safely at the same time without duplicate side effects.
    """
    if not _uses_rocketmq(task.name):
        options: dict[str, Any] = {}
        if task_id is not None:
            options["task_id"] = task_id
        if queue is not None:
            options["queue"] = queue
        if countdown is not None:
            options["countdown"] = countdown
        return task.apply_async(args=args, kwargs=kwargs, **options)

    resolved_task_id = task_id or str(uuid.uuid4())
    publish_task(
        task_name=task.name,
        args=list(args),
        kwargs=kwargs,
        task_id=resolved_task_id,
        queue=queue or getattr(task, "queue", None),
        countdown=countdown,
    )
    store_task_state(resolved_task_id, "PENDING")
    return QueuedTask(id=resolved_task_id)
