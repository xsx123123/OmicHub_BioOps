"""Redis Stream adapter for durable MAS A2A event delivery."""

from __future__ import annotations

import json
from typing import Any

from cygnusx.infrastructure.cache.redis_client import get_redis

MAS_EVENT_STREAM = "cygnusx:mas:events"
MAS_SCHEDULER_GROUP = "mas-scheduler"


class RedisStreamPublisher:
    """Publishes only opaque persisted event envelopes to the shared Stream."""

    async def publish(self, event_id: str, payload: dict[str, Any]) -> str:
        redis_client = get_redis()
        return str(
            await redis_client.xadd(
                MAS_EVENT_STREAM,
                {"event_id": event_id, "payload": json.dumps(payload, ensure_ascii=False)},
                maxlen=100_000,
                approximate=True,
            )
        )


class RedisStreamConsumer:
    """Small Redis Stream consumer used by scheduler workers."""

    async def read(self, consumer_name: str, count: int = 25) -> list[tuple[str, str]]:
        redis_client = get_redis()
        try:
            await redis_client.xgroup_create(
                MAS_EVENT_STREAM, MAS_SCHEDULER_GROUP, id="0", mkstream=True
            )
        except Exception as exc:  # BUSYGROUP is the expected concurrent-startup result.
            if "BUSYGROUP" not in str(exc):
                raise
        messages = await redis_client.xreadgroup(
            MAS_SCHEDULER_GROUP,
            consumer_name,
            {MAS_EVENT_STREAM: "0"},
            count=count,
        )
        if not messages:
            messages = await redis_client.xreadgroup(
                MAS_SCHEDULER_GROUP,
                consumer_name,
                {MAS_EVENT_STREAM: ">"},
                count=count,
                block=1,
            )
        return [
            (message_id, str(fields["event_id"]))
            for _, stream_messages in messages
            for message_id, fields in stream_messages
        ]

    async def acknowledge(self, message_id: str) -> None:
        await get_redis().xack(MAS_EVENT_STREAM, MAS_SCHEDULER_GROUP, message_id)
