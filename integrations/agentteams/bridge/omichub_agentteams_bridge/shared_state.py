"""Redis-backed coordination primitive for multi-replica Bridge state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException, status


class RedisStateBackend:
    """Serialize a small Bridge control-plane snapshot across replicas."""

    def __init__(self, url: str, key_prefix: str) -> None:
        try:
            from redis.asyncio import Redis, from_url
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("Redis state backend requires the redis package") from exc
        self._client: Redis = from_url(url, decode_responses=True)
        self._key_prefix = key_prefix.rstrip(":")
        self._local_lock = __import__("asyncio").Lock()

    @property
    def client(self) -> Any:
        return self._client

    @property
    def data_key(self) -> str:
        return f"{self._key_prefix}:snapshot"

    @property
    def lock_key(self) -> str:
        return f"{self._key_prefix}:lock"

    @asynccontextmanager
    async def lock(self) -> AsyncIterator[None]:
        async with self._local_lock:
            lock = self._client.lock(self.lock_key, timeout=30, blocking_timeout=10)
            acquired = await lock.acquire()
            if not acquired:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Bridge shared state is busy; retry the request",
                )
            try:
                yield
            finally:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001
                    pass

    async def get_snapshot(self) -> str | None:
        return await self._client.get(self.data_key)

    async def set_snapshot(self, value: str) -> None:
        await self._client.set(self.data_key, value)

    async def aclose(self) -> None:
        await self._client.aclose()
