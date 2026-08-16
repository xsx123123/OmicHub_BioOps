"""聊天会话内 AgentTeams Case 状态事件的 Redis Pub/Sub 通道。"""

from __future__ import annotations

import json
from typing import Any

from omichub.infrastructure.cache.redis_client import get_redis

_CHANNEL_PREFIX = "chat:agentteams_case:"
_DEDUP_PREFIX = "chat:agentteams_case:dedup:"
_HISTORY_PREFIX = "chat:agentteams_case:history:"
_PUBLISH_DEDUP_LUA = """
if redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[2]) then
  redis.call('RPUSH', KEYS[3], ARGV[1])
  redis.call('LTRIM', KEYS[3], -500, -1)
  redis.call('EXPIRE', KEYS[3], ARGV[2])
  return redis.call('PUBLISH', KEYS[2], ARGV[1])
end
return 0
"""


def get_chat_case_channel(session_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{session_id}"


async def publish_chat_case_event(session_id: str, event: dict[str, Any]) -> None:
    redis = get_redis()
    channel = get_chat_case_channel(session_id)
    cursor = str(
        event.get("event_cursor")
        or event.get("idempotency_key")
        or event.get("event_id")
        or event.get("message_id")
        or ""
    )
    if cursor:
        event = {**event, "event_cursor": cursor}
    payload = json.dumps(event, ensure_ascii=False, default=str)
    idempotency_key = event.get("idempotency_key")
    if isinstance(idempotency_key, str) and idempotency_key:
        await redis.eval(
            _PUBLISH_DEDUP_LUA,
            3,
            f"{_DEDUP_PREFIX}{session_id}:{idempotency_key}",
            channel,
            f"{_HISTORY_PREFIX}{session_id}",
            payload,
            7 * 24 * 60 * 60,
        )
        return
    async with redis.pipeline(transaction=True) as pipe:
        history_key = f"{_HISTORY_PREFIX}{session_id}"
        pipe.rpush(history_key, payload)
        pipe.ltrim(history_key, -500, -1)
        pipe.expire(history_key, 7 * 24 * 60 * 60)
        pipe.publish(channel, payload)
        await pipe.execute()


async def replay_chat_case_events(session_id: str, cursor: str | None) -> list[str]:
    rows = await get_redis().lrange(f"{_HISTORY_PREFIX}{session_id}", 0, -1)
    payloads = [row.decode() if isinstance(row, bytes) else str(row) for row in rows]
    if not cursor:
        return payloads
    for index, payload in enumerate(payloads):
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if str(event.get("event_cursor") or "") == cursor:
            return payloads[index + 1 :]
    return payloads


async def subscribe_chat_case_events(session_id: str):
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(get_chat_case_channel(session_id))
    return pubsub
