"""仪表板统计缓存 — 基于 Redis 的轻量 JSON 缓存。

设计要点：
- 命中直接返回反序列化结果，未命中执行 factory 后回写；
- 任何 Redis 异常（未连接/超时）都静默降级到 factory，绝不影响接口可用性；
- 仅缓存聚合统计（管理员 5 min、个人 60 s），实时性要求高的查询不缓存。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

from omichub.core.config import get_settings
from omichub.infrastructure.cache.redis_client import get_redis

T = TypeVar("T")


async def cached_json(
    key: str,
    ttl: int,
    factory: Callable[[], Awaitable[T]],
) -> T:
    """先查 Redis，未命中则执行 factory 并回写。

    - 配置 `enable_stats_cache=False` 时直接走 factory（便于本地/测试）；
    - Redis 不可用时静默降级为直查 DB，绝不影响接口可用性。
    """
    if not get_settings().enable_stats_cache:
        return await factory()

    try:
        client = get_redis()
        cached = await client.get(key)
    except Exception:
        return await factory()

    if cached is not None:
        with contextlib.suppress(Exception):
            return json.loads(cached)  # 脏数据则落库重算

    value = await factory()
    with contextlib.suppress(Exception):
        await get_redis().setex(
            key, ttl, json.dumps(value, default=_json_default)
        )  # 回写失败不影响本次返回
    return value


async def invalidate(prefix: str) -> None:
    """按前缀失效缓存（如提交任务后清除该用户统计）。best-effort。"""
    if not get_settings().enable_stats_cache:
        return
    with contextlib.suppress(Exception):
        client = get_redis()
        async for key in client.scan_iter(match=f"{prefix}*", count=100):
            await client.delete(key)


def _json_default(obj: object) -> str:
    """处理 datetime / UUID / Decimal 等非原生 JSON 类型。"""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
