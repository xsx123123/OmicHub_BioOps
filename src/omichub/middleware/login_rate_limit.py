"""登录端点限流 — 针对 /login 和 /2fa/login 的 IP 级防爆破。

策略：同一 IP 在 5 分钟内登录失败达到 5 次，封禁 15 分钟。
优先使用 Redis（多实例共享），Redis 不可用时降级为进程内存（单实例有效）。
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, Request

from omichub.core.exceptions import AuthenticationError

_WINDOW_SECONDS = 300  # 统计窗口：5 分钟
_MAX_FAILURES = 5  # 窗口内最大失败次数
_BLOCK_SECONDS = 900  # 封禁时长：15 分钟

# 内存兜底：仅当前进程内有效
_memory_failures: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    """取真实客户端 IP（与全局限流中间件保持一致）。

    在反向代理环境下，X-Forwarded-For 可能包含客户端伪造的前置 IP，
    因此取链中最后一个（即最靠近服务端、由 nginx 追加的）IP。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


def _key(ip: str) -> str:
    return f"login_rate_limit:{ip}"


async def _record_failure(ip: str) -> None:
    now = time.time()
    key = _key(ip)
    try:
        from omichub.infrastructure.cache.redis_client import get_redis

        redis = get_redis()
        await redis.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        await redis.zadd(key, {str(now): now})
        await redis.expire(key, _BLOCK_SECONDS)
    except Exception:
        # Redis 不可用：降级内存
        timestamps = _memory_failures.get(key, [])
        timestamps = [t for t in timestamps if t > now - _WINDOW_SECONDS]
        timestamps.append(now)
        _memory_failures[key] = timestamps


async def _check_limit(ip: str) -> None:
    now = time.time()
    key = _key(ip)
    try:
        from omichub.infrastructure.cache.redis_client import get_redis

        redis = get_redis()
        await redis.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        count = await redis.zcard(key)
        if count >= _MAX_FAILURES:
            oldest = await redis.zrange(key, 0, 0, withscores=True)
            if oldest and now - oldest[0][1] < _BLOCK_SECONDS:
                raise AuthenticationError("登录尝试过于频繁，请 15 分钟后再试")
    except AuthenticationError:
        raise
    except Exception:
        # Redis 不可用：降级内存
        timestamps = _memory_failures.get(key, [])
        timestamps = [t for t in timestamps if t > now - _WINDOW_SECONDS]
        if len(timestamps) >= _MAX_FAILURES:
            oldest = min(timestamps)
            if now - oldest < _BLOCK_SECONDS:
                raise AuthenticationError("登录尝试过于频繁，请 15 分钟后再试") from None


async def _clear(ip: str) -> None:
    key = _key(ip)
    try:
        from omichub.infrastructure.cache.redis_client import get_redis

        redis = get_redis()
        await redis.delete(key)
    except Exception:
        _memory_failures.pop(key, None)


class LoginRateLimiter:
    """登录限流依赖：在端点里 check / record_failure / clear。"""

    async def check(self, request: Request) -> None:
        await _check_limit(_client_ip(request))

    async def record_failure(self, request: Request) -> None:
        await _record_failure(_client_ip(request))

    async def clear(self, request: Request) -> None:
        await _clear(_client_ip(request))


async def get_login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter()


LoginRateLimitDep = Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)]
