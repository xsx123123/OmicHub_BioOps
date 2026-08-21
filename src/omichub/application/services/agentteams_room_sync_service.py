"""Matrix → 平台反向同步：Element 侧发言回投为 Case 的 ``room.user_message``。

房管生命周期：建房成功后 ``record_room_binding`` 把 case→room 绑定登记进
Redis hash；Celery beat 周期性驱动 ``AgentTeamsRoomSyncService.run`` 为每个
绑定房间开一条有界 Gateway ``/rooms/{id}/sync`` SSE 消费，sync cursor 持久化
在 Redis（断线/重启后从上次位置继续，beat 间隔即重连退避）。

防回声：平台镜像进 Matrix 的消息由 Gateway matrix_client 打上
``com.omichub.source=omichub`` 标记，SSE 载荷 ``origin != "external"`` 的一律
不回投；回投事件的 payload 带 ``via="matrix"``，bridge 侧 room_mirror 据此
跳过，杜绝双向循环。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import uuid4

from loguru import logger

from omichub.application.services.agentteams_room_gateway_service import (
    AgentTeamsRoomGatewayService,
)
from omichub.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    ROOM_NAMESPACE_ID_PREFIX,
    AgentTeamsService,
)
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.infrastructure.cache.redis_client import get_redis

ROOM_BINDINGS_HASH_KEY = "agentteams:room-sync:bindings"
ROOM_SYNC_CURSOR_KEY_PREFIX = "agentteams:room-sync:cursor:"
ROOM_SYNC_LOCK_KEY = "agentteams:room-sync:lock"
ROOM_SYNC_EVENT_DEDUP_KEY_PREFIX = "agentteams:room-sync:seen:"
TERMINAL_STATUSES = frozenset({"closed", "cancelled"})
_MAX_MESSAGES_PER_ROOM = 200
_EVENT_DEDUP_TTL_SECONDS = 24 * 60 * 60

_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


async def record_room_binding(
    case_id: str,
    room_id: str,
    requester_ref: str,
    *,
    redis_getter: Callable[[], Any] = get_redis,
) -> None:
    """建房成功后登记 case→room 绑定（best-effort；失败仅记日志，不影响建房）。"""
    try:
        redis = redis_getter()
        await redis.hset(
            ROOM_BINDINGS_HASH_KEY,
            case_id,
            f"{room_id}|{requester_ref}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.bind(case_id=case_id).warning("AgentTeams room binding record failed: {}", exc)


def _default_responder(case_id: str, requester_ref: str, content: str) -> None:
    from omichub.infrastructure.celery_app.tasks.agentteams import (
        respond_to_room_message,
        respond_to_room_namespace_message,
    )

    if case_id.startswith(ROOM_NAMESPACE_ID_PREFIX):
        # 房间命名空间（未立项房间）的 Matrix 回投发言走房间级响应链路，
        # 避免误触发 Case 态的 start_chat_planning。
        respond_to_room_namespace_message.delay(
            case_id.removeprefix(ROOM_NAMESPACE_ID_PREFIX), requester_ref, content
        )
        return
    respond_to_room_message.delay(case_id, requester_ref, content)


class AgentTeamsRoomSyncService:
    """Bounded per-room Gateway SSE consumer that reprojects external messages."""

    def __init__(
        self,
        agentteams: AgentTeamsService,
        *,
        gateway: AgentTeamsRoomGatewayService | None = None,
        redis_getter: Callable[[], Any] = get_redis,
        responder: Callable[[str, str, str], None] | None = None,
        lock_ttl_seconds: int = 120,
    ) -> None:
        self._agentteams = agentteams
        self._gateway = gateway or AgentTeamsRoomGatewayService()
        self._redis_getter = redis_getter
        self._responder = responder or _default_responder
        self._lock_ttl = lock_ttl_seconds

    async def run(self, *, watch_seconds: int) -> dict[str, int | str]:
        if not self._gateway.available:
            return {"status": "skipped_unavailable", "rooms": 0, "messages": 0}
        redis = self._redis_getter()
        lock_token = uuid4().hex
        acquired = bool(await redis.set(ROOM_SYNC_LOCK_KEY, lock_token, nx=True, ex=self._lock_ttl))
        if not acquired:
            return {"status": "skipped_locked", "rooms": 0, "messages": 0}
        try:
            bindings = await redis.hgetall(ROOM_BINDINGS_HASH_KEY)
            rooms = messages = failed = 0
            for case_id, raw in bindings.items():
                room_id, _, requester_ref = str(raw).partition("|")
                if not room_id:
                    continue
                rooms += 1
                try:
                    room_stats = await self._sync_room(
                        case_id, room_id, requester_ref, watch_seconds=watch_seconds
                    )
                    messages += room_stats["messages"]
                except (NotFoundError, BusinessError) as exc:
                    if not isinstance(exc, NotFoundError) and (
                        exc.code != "NOT_FOUND" and exc.detail != "协作案例不存在"
                    ):
                        failed += 1
                        logger.bind(case_id=case_id, room_id=room_id).warning(
                            "AgentTeams room sync failed: {}", exc
                        )
                        continue
                    await redis.hdel(ROOM_BINDINGS_HASH_KEY, case_id)
                    logger.bind(case_id=case_id, room_id=room_id).info(
                        "AgentTeams room sync removed stale Case binding"
                    )
                except Exception as exc:  # noqa: BLE001 - 单房间失败不影响其他房间
                    failed += 1
                    logger.bind(case_id=case_id, room_id=room_id).warning(
                        "AgentTeams room sync failed: {}", exc
                    )
            return {"status": "ok", "rooms": rooms, "messages": messages, "failed": failed}
        finally:
            try:
                await redis.eval(_RELEASE_LOCK_LUA, 1, ROOM_SYNC_LOCK_KEY, lock_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentTeams room sync lock release failed: {}", exc)

    async def _sync_room(
        self, case_id: str, room_id: str, requester_ref: str, *, watch_seconds: int
    ) -> dict[str, int]:
        redis = self._redis_getter()
        if requester_ref:
            case = await self._agentteams.get_case(case_id, requester_ref)
            if str(case.get("status") or "") in TERMINAL_STATUSES:
                await redis.hdel(ROOM_BINDINGS_HASH_KEY, case_id)
                return {"messages": 0}
        cursor = await redis.get(f"{ROOM_SYNC_CURSOR_KEY_PREFIX}{case_id}")
        deadline = time.monotonic() + max(1, watch_seconds)
        messages = 0
        stream = self._gateway.stream_room_events(room_id, since=cursor or None)
        try:
            async for payload in stream:
                next_batch = payload.get("next_batch")
                if isinstance(next_batch, str) and next_batch:
                    cursor = next_batch
                    await redis.set(f"{ROOM_SYNC_CURSOR_KEY_PREFIX}{case_id}", cursor)
                    if time.monotonic() >= deadline:
                        break
                    continue
                if self._is_echo(payload):
                    continue
                content = str(payload.get("content") or "").strip()
                if not content:
                    continue
                dedup_key = self._event_dedup_key(case_id, payload)
                if dedup_key and await redis.get(dedup_key):
                    logger.bind(case_id=case_id, event_id=payload.get("event_id")).info(
                        "AgentTeams room sync skipped duplicate external event"
                    )
                    continue
                await self._reproject(case_id, requester_ref, content, payload)
                if dedup_key:
                    await redis.set(
                        dedup_key,
                        "1",
                        nx=True,
                        ex=_EVENT_DEDUP_TTL_SECONDS,
                    )
                messages += 1
                if messages >= _MAX_MESSAGES_PER_ROOM or time.monotonic() >= deadline:
                    break
        finally:
            await stream.aclose()
        return {"messages": messages}

    @staticmethod
    def _is_echo(payload: dict[str, Any]) -> bool:
        """平台自己镜像进房间的消息（origin=omichub）不回投。"""
        return str(payload.get("origin") or "") != "external"

    @staticmethod
    def _event_dedup_key(case_id: str, payload: dict[str, Any]) -> str | None:
        event_id = str(payload.get("event_id") or "").strip()
        if event_id:
            fingerprint = f"event:{event_id}"
        else:
            content = str(payload.get("content") or "").strip()
            if not content:
                return None
            fingerprint = "message:{}:{}:{}".format(
                str(payload.get("message_type") or "room.user_message").strip(),
                str(payload.get("sender_matrix_id") or payload.get("sender_identity") or "").strip(),
                content,
            )
        digest = sha256(fingerprint.encode("utf-8")).hexdigest()
        return f"{ROOM_SYNC_EVENT_DEDUP_KEY_PREFIX}{case_id}:{digest}"

    async def _reproject(
        self, case_id: str, requester_ref: str, content: str, payload: dict[str, Any]
    ) -> None:
        sender_label = str(
            payload.get("sender_identity") or payload.get("sender_matrix_id") or "matrix-user"
        )
        await self._agentteams.post_case_evidence(
            case_id,
            work_item_id=CASE_LEVEL_WORK_ITEM_ID,
            event_type="room.user_message",
            summary=content[:80],
            payload={
                "actor": sender_label,
                "content": content[:4_000],
                "via": "matrix",
                "matrix_event_id": str(payload.get("event_id") or ""),
                "matrix_sender": str(payload.get("sender_matrix_id") or ""),
            },
        )
        if requester_ref:
            try:
                self._responder(case_id, requester_ref, content)
            except Exception as exc:  # noqa: BLE001 - 响应调度失败不影响消息回投
                logger.bind(case_id=case_id).warning(
                    "AgentTeams room response dispatch failed: {}", exc
                )


__all__ = [
    "AgentTeamsRoomSyncService",
    "ROOM_BINDINGS_HASH_KEY",
    "ROOM_SYNC_CURSOR_KEY_PREFIX",
    "ROOM_SYNC_LOCK_KEY",
    "record_room_binding",
]
