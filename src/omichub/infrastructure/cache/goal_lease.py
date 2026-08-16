"""Redis-backed ownership lease for one Goal continuation worker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from omichub.infrastructure.cache.redis_client import get_redis

_RENEW_LEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def get_goal_lease_key(goal_id: str) -> str:
    return f"goal:{goal_id}:lease"


class GoalRedisLease:
    """Keeps an exclusive Goal worker lease alive for a bounded execution step."""

    def __init__(
        self,
        goal_id: str,
        owner: str,
        ttl_seconds: int,
        *,
        redis_getter: Callable[[], Any] = get_redis,
    ) -> None:
        self._key = get_goal_lease_key(goal_id)
        self._owner = owner
        self._ttl_seconds = max(1, ttl_seconds)
        self._redis_getter = redis_getter
        self._heartbeat_task: asyncio.Task[None] | None = None
        self.acquired = False
        self.lost = False

    async def __aenter__(self) -> GoalRedisLease:
        redis = self._redis_getter()
        self.acquired = bool(
            await redis.set(self._key, self._owner, nx=True, ex=self._ttl_seconds)
        )
        if self.acquired:
            self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
        if self.acquired:
            # The expiry is the safe fallback if Redis becomes unavailable during cleanup.
            with suppress(Exception):
                await self._redis_getter().eval(
                    _RELEASE_LEASE_LUA, 1, self._key, self._owner
                )

    async def _heartbeat(self) -> None:
        interval = max(1, self._ttl_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._redis_getter().eval(
                    _RENEW_LEASE_LUA,
                    1,
                    self._key,
                    self._owner,
                    str(self._ttl_seconds),
                )
            except Exception:  # noqa: BLE001
                self.lost = True
                return
            if not renewed:
                self.lost = True
                return
