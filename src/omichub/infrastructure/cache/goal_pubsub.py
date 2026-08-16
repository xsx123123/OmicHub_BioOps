"""Best-effort realtime delivery for persisted Goal events."""

from __future__ import annotations

import json
from typing import Any

from omichub.infrastructure.cache.redis_client import get_redis

_CHANNEL_PREFIX = "goal:events:"


def get_goal_event_channel(goal_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{goal_id}"


async def publish_goal_event(goal_id: str, event: dict[str, Any]) -> None:
    await get_redis().publish(
        get_goal_event_channel(goal_id),
        json.dumps(event, ensure_ascii=False, default=str),
    )


async def subscribe_goal_events(goal_id: str):
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(get_goal_event_channel(goal_id))
    return pubsub
