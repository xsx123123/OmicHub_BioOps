"""Redis 异步客户端"""

import asyncio

import redis.asyncio as redis

from omichub.core.config import get_settings

_redis: redis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> redis.Redis:
    """获取 Redis 客户端（按当前 event loop 缓存）。

    Celery 任务用 asyncio.run() 每次新建事件循环；async redis 客户端绑定到首次使用的 loop，
    跨 loop 复用会抛 "Event loop is closed" / "attached to a different loop"。
    故按 get_running_loop() 缓存：同一 loop 内复用，loop 变化时重建。
    web(FastAPI 单 loop) 与 celery(每任务新 loop) 均安全。进程内同一时刻仅一个 loop 在跑，单缓存即可。
    """
    global _redis, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis is None or _redis_loop is not loop:
        settings = get_settings()
        _redis = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        _redis_loop = loop
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接"""
    global _redis, _redis_loop
    if _redis is not None:
        await _redis.close()
        _redis = None
        _redis_loop = None
