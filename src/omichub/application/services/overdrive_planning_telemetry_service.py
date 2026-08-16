"""Low-overhead telemetry for Overdrive Manager planning."""

from __future__ import annotations

import asyncio
import socket
import threading
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from queue import Empty, Queue
from typing import Any

import redis.asyncio as redis
from loguru import logger

from omichub.core.config import get_settings
from omichub.infrastructure.cache.redis_client import get_redis

_KEY_PREFIX = "omichub:overdrive:planning:"
_UNAVAILABLE_HOSTS_LOGGED: set[str] = set()


@lru_cache(maxsize=8)
def _resolve_host_fast(host: str, timeout_seconds: float = 0.05) -> str | None:
    """Resolve without using asyncio's shared executor, which can delay loop shutdown."""
    results: Queue[str | None] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            results.put_nowait(str(addresses[0][4][0]) if addresses else None)
        except (OSError, IndexError):
            results.put_nowait(None)

    thread = threading.Thread(target=resolve, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    try:
        return results.get_nowait()
    except Empty:
        return None


class OverdrivePlanningTelemetryService:
    async def record_runtime(
        self,
        *,
        planning_mode: str,
        repair_outcome: str | None = None,
        llm_speech_overridden: bool = False,
    ) -> None:
        """Record through a disposable short-timeout connection on the Web request path."""
        settings = get_settings()
        resolved_host = _resolve_host_fast(settings.redis_host)
        if not resolved_host:
            if settings.redis_host not in _UNAVAILABLE_HOSTS_LOGGED:
                _UNAVAILABLE_HOSTS_LOGGED.add(settings.redis_host)
                logger.warning(
                    "Overdrive planning telemetry skipped: Redis host did not resolve promptly ({})",
                    settings.redis_host,
                )
            return
        client: Any | None = None
        try:
            client = redis.Redis(
                host=resolved_host,
                port=settings.redis_port,
                password=settings.redis_password or None,
                db=settings.redis_db,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.05,
                socket_timeout=0.05,
                retry_on_timeout=False,
            )
            await self._record_with_client(
                client,
                planning_mode=planning_mode,
                repair_outcome=repair_outcome,
                llm_speech_overridden=llm_speech_overridden,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Overdrive runtime planning telemetry failed: {}", exc)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.aclose(), timeout=0.1)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Overdrive runtime telemetry close failed: {}", exc)

    async def record(
        self,
        *,
        planning_mode: str,
        repair_outcome: str | None = None,
        llm_speech_overridden: bool = False,
    ) -> None:
        await self._record_with_client(
            get_redis(),
            planning_mode=planning_mode,
            repair_outcome=repair_outcome,
            llm_speech_overridden=llm_speech_overridden,
        )

    async def _record_with_client(
        self,
        client: Any,
        *,
        planning_mode: str,
        repair_outcome: str | None,
        llm_speech_overridden: bool,
    ) -> None:
        key = f"{_KEY_PREFIX}{datetime.now(UTC).date().isoformat()}"
        values = {
            f"overdrive_planning_total:{planning_mode}": 1,
            "overdrive_llm_speech_overridden_total": int(llm_speech_overridden),
        }
        if repair_outcome:
            values[f"overdrive_plan_repair_total:{repair_outcome}"] = 1
        try:
            async with asyncio.timeout(0.1):
                async with client.pipeline(transaction=True) as pipe:
                    for field, value in values.items():
                        pipe.hincrby(key, field, value)
                    pipe.expire(key, 8 * 24 * 60 * 60)
                    await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Overdrive planning telemetry record failed: {}", exc)

    async def summary(self, *, days: int = 7) -> dict[str, Any]:
        totals: dict[str, int] = {}
        try:
            async with asyncio.timeout(0.5):
                redis = get_redis()
                for offset in range(max(1, min(days, 30))):
                    date = (datetime.now(UTC).date() - timedelta(days=offset)).isoformat()
                    row = await redis.hgetall(f"{_KEY_PREFIX}{date}")
                    for field, value in row.items():
                        totals[str(field)] = totals.get(str(field), 0) + int(value or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Overdrive planning telemetry summary failed: {}", exc)
        return totals


__all__ = ["OverdrivePlanningTelemetryService"]
