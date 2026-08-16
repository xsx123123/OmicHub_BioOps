"""BLAST 任务 Redis 事件通道。"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from typing import Any

import redis

from omichub.core.config import get_settings
from omichub.infrastructure.cache.redis_client import get_redis

BLAST_EVENT_CHANNEL_PREFIX = "blast:task:"


def get_blast_event_channel(task_id: str) -> str:
    return f"{BLAST_EVENT_CHANNEL_PREFIX}{task_id}:events"


async def publish_blast_event(
    task_id: str,
    status: str,
    progress: int,
    message: str,
    *,
    error_message: str | None = None,
) -> None:
    payload = {
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "message": message,
        "error_message": error_message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with contextlib.suppress(Exception):
        await get_redis().publish(
            get_blast_event_channel(task_id),
            json.dumps(payload, ensure_ascii=False),
        )


def publish_blast_event_sync(
    task_id: str,
    status: str,
    progress: int,
    message: str,
    *,
    error_message: str | None = None,
) -> None:
    payload = {
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "message": message,
        "error_message": error_message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with contextlib.suppress(Exception):
        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.publish(
            get_blast_event_channel(task_id),
            json.dumps(payload, ensure_ascii=False),
        )
        client.close()


async def subscribe_blast_events(task_id: str) -> Any:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(get_blast_event_channel(task_id))
    return pubsub
