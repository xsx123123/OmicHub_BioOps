"""RocketMQ task transport compatible with the existing Celery task definitions.

Celery remains available for scheduled jobs and gradual rollback.  This module only
changes task delivery: the RocketMQ consumer calls the registered Celery task
locally so task bodies, retries, progress updates, and Redis result records keep
their existing behavior.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cygnusx.core.config import get_settings

logger = logging.getLogger(__name__)

_DELAY_LEVELS_SECONDS = (1, 5, 10, 30, 60, 120, 180, 240, 300, 360, 420, 480, 540, 600)
_producer_lock = threading.Lock()
_producer: Any | None = None


@dataclass(frozen=True)
class QueuedTask:
    """Small AsyncResult-compatible handle returned after task submission."""

    id: str


def topic_for(queue: str | None = None) -> str:
    """Return the RocketMQ topic used for a logical CygnusX task queue."""
    settings = get_settings()
    logical_queue = queue or "analysis"
    return f"{settings.rocketmq_topic_prefix}_{logical_queue}"


def _get_producer() -> Any:
    """Create the process-local RocketMQ producer on first use."""
    global _producer
    if _producer is not None:
        return _producer

    with _producer_lock:
        if _producer is not None:
            return _producer
        try:
            from rocketmq.client import Producer
        except ImportError as exc:  # pragma: no cover - depends on deployment extra
            raise RuntimeError(
                "RocketMQ 已启用，但未安装 rocketmq-client-python；请重新安装 CygnusX 依赖"
            ) from exc

        settings = get_settings()
        producer = Producer(settings.rocketmq_producer_group)
        producer.set_name_server_address(settings.rocketmq_namesrv_addr)
        producer.start()
        _producer = producer
        return producer


def _delay_level(countdown: int | float | None) -> int | None:
    if countdown is None or countdown <= 0:
        return None
    for level, seconds in enumerate(_DELAY_LEVELS_SECONDS, start=1):
        if countdown <= seconds:
            return level
    return len(_DELAY_LEVELS_SECONDS)


def publish_task(
    *,
    task_name: str,
    args: list[Any],
    kwargs: dict[str, Any],
    task_id: str,
    queue: str | None = None,
    countdown: int | float | None = None,
    attempt: int = 0,
) -> None:
    """Publish a JSON task envelope to RocketMQ synchronously.

    Synchronous acknowledgement makes HTTP submission fail fast instead of
    reporting a task as queued when the broker cannot accept it.
    """
    try:
        from rocketmq.client import Message
    except ImportError as exc:  # pragma: no cover - depends on deployment extra
        raise RuntimeError(
            "RocketMQ 已启用，但未安装 rocketmq-client-python；请重新安装 CygnusX 依赖"
        ) from exc

    envelope = {
        "task_name": task_name,
        "args": args,
        "kwargs": kwargs,
        "task_id": task_id,
        "queue": queue or "analysis",
        "attempt": attempt,
    }
    message = Message(topic_for(queue))
    message.set_keys(task_id)
    message.set_body(json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"))
    delay_level = _delay_level(countdown)
    if delay_level is not None:
        message.set_delay_time_level(delay_level)
    _get_producer().send_sync(message)


def store_task_state(task_id: str, state: str, result: Any = None) -> None:
    """Mirror RocketMQ execution state into Celery's existing result backend."""
    from cygnusx.infrastructure.celery_app.celery import celery_app

    celery_app.backend.store_result(task_id, result=result, state=state)


def close_producer() -> None:
    """Stop the producer during controlled process shutdown."""
    global _producer
    with _producer_lock:
        if _producer is not None:
            _producer.shutdown()
            _producer = None


def decode_envelope(body: bytes) -> dict[str, Any]:
    """Decode and validate a RocketMQ task payload."""
    envelope = json.loads(body.decode("utf-8"))
    required = ("task_name", "args", "kwargs", "task_id", "queue")
    missing = [key for key in required if key not in envelope]
    if missing:
        raise ValueError(f"RocketMQ 任务缺少字段: {', '.join(missing)}")
    if not isinstance(envelope["args"], list) or not isinstance(envelope["kwargs"], dict):
        raise ValueError("RocketMQ 任务参数格式无效")
    return envelope


def execute_task(envelope: dict[str, Any], retry: Callable[[dict[str, Any]], None]) -> None:
    """Execute a registered Celery task locally and republish Celery retries."""
    from cygnusx.infrastructure.celery_app.celery import celery_app

    task_name = str(envelope["task_name"])
    task = celery_app.tasks.get(task_name)
    if task is None:
        raise ValueError(f"未注册的任务: {task_name}")

    task_id = str(envelope["task_id"])
    store_task_state(task_id, "STARTED")
    result = task.apply(
        args=envelope["args"],
        kwargs=envelope["kwargs"],
        task_id=task_id,
        throw=False,
    )
    if result.status == "RETRY":
        next_attempt = int(envelope.get("attempt", 0)) + 1
        if next_attempt > int(getattr(task, "max_retries", 0)):
            store_task_state(task_id, "FAILURE", result.result)
            raise RuntimeError(f"任务重试次数耗尽: {task_name}")
        store_task_state(task_id, "RETRY", result.result)
        retry({**envelope, "attempt": next_attempt})
    elif result.status == "FAILURE":
        store_task_state(task_id, "FAILURE", result.result)
        logger.error("RocketMQ task failed without retry: %s: %s", task_name, result.result)
    else:
        store_task_state(task_id, "SUCCESS", result.result)
