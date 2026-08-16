"""Redis helpers for workflow monitor realtime state and Pub/Sub."""

from __future__ import annotations

import json
from typing import Any

from omichub.core.config import get_settings
from omichub.infrastructure.cache.redis_client import get_redis

GLOBAL_CHANNEL = "workflow_monitor:global"
USER_CHANNEL_PREFIX = "workflow_monitor:user:"
TASK_CHANNEL_PREFIX = "workflow_monitor:task:"
SUMMARY_KEY_PREFIX = "workflow_monitor:task:"
RUNNING_TASKS_KEY = "workflow_monitor:running_tasks"


def get_user_channel(user_id: str) -> str:
    return f"{USER_CHANNEL_PREFIX}{user_id}"


def get_task_channel(task_id: str) -> str:
    return f"{TASK_CHANNEL_PREFIX}{task_id}"


def get_summary_key(task_id: str) -> str:
    return f"{SUMMARY_KEY_PREFIX}{task_id}:summary"


def get_events_key(task_id: str) -> str:
    return f"{SUMMARY_KEY_PREFIX}{task_id}:events"


async def publish_monitor_message(
    *,
    task_id: str,
    user_id: str | None,
    message: dict[str, Any],
) -> None:
    redis = get_redis()
    payload = json.dumps(message, ensure_ascii=False, default=str)
    await redis.publish(GLOBAL_CHANNEL, payload)
    await redis.publish(get_task_channel(task_id), payload)
    if user_id:
        await redis.publish(get_user_channel(user_id), payload)


async def save_task_summary(task_id: str, summary: dict[str, Any]) -> None:
    settings = get_settings()
    redis = get_redis()
    await redis.set(
        get_summary_key(task_id),
        json.dumps(summary, ensure_ascii=False, default=str),
        ex=settings.workflow_monitor_event_ttl_seconds,
    )
    if summary.get("status") == "running":
        await redis.zadd(RUNNING_TASKS_KEY, {task_id: summary.get("last_event_ts", 0)})
    else:
        await redis.zrem(RUNNING_TASKS_KEY, task_id)


async def get_task_summary(task_id: str) -> dict[str, Any] | None:
    raw = await get_redis().get(get_summary_key(task_id))
    return json.loads(raw) if raw else None


async def push_task_event(task_id: str, event: dict[str, Any]) -> None:
    settings = get_settings()
    redis = get_redis()
    key = get_events_key(task_id)
    await redis.lpush(key, json.dumps(event, ensure_ascii=False, default=str))
    await redis.ltrim(key, 0, settings.workflow_monitor_recent_event_limit - 1)
    await redis.expire(key, settings.workflow_monitor_event_ttl_seconds)


async def list_task_events(task_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = await get_redis().lrange(get_events_key(task_id), 0, max(0, limit - 1))
    return [json.loads(row) for row in rows]


async def subscribe_global():
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(GLOBAL_CHANNEL)
    return pubsub


async def subscribe_user(user_id: str):
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(get_user_channel(user_id))
    return pubsub


async def subscribe_task(task_id: str):
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(get_task_channel(task_id))
    return pubsub
