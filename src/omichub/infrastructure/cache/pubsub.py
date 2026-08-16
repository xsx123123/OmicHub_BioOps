"""Redis Pub/Sub 工具 — 任务日志实时推送"""

from __future__ import annotations

import json
from typing import Any

from omichub.infrastructure.cache.redis_client import get_redis

TASK_LOG_CHANNEL_PREFIX = "task_logs:"


def get_task_log_channel(task_id: str) -> str:
    """获取任务日志频道名"""
    return f"{TASK_LOG_CHANNEL_PREFIX}{task_id}"


async def publish_task_log(
    task_id: str,
    level: str,
    message: str,
    source: str = "",
    timestamp: str | None = None,
) -> None:
    """发布单条任务日志到 Redis Pub/Sub"""
    redis_client = get_redis()
    payload = {
        "task_id": task_id,
        "level": level,
        "message": message,
        "source": source,
        "timestamp": timestamp,
    }
    await redis_client.publish(get_task_log_channel(task_id), json.dumps(payload))


async def subscribe_task_logs(task_id: str) -> Any:
    """异步订阅任务日志频道，返回 pubsub 对象。"""
    redis_client = get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(get_task_log_channel(task_id))
    return pubsub


async def subscribe_arq_progress(task_id: str) -> Any:
    """订阅 ARQ 任务进度频道。"""
    redis_client = get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"task:{task_id}:progress")
    return pubsub


async def publish_arq_progress(
    task_id: str,
    phase: str,
    progress: float,
    message: str,
) -> None:
    """发布 ARQ 任务进度到 Redis Pub/Sub。"""
    redis_client = get_redis()
    payload = {
        "task_id": task_id,
        "phase": phase,
        "progress": progress,
        "message": message,
    }
    await redis_client.publish(f"task:{task_id}:progress", json.dumps(payload, ensure_ascii=False))
