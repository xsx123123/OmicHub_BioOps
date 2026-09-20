"""ARQ 任务队列配置与连接池。

ARQ 0.28+ 基于 redis-py，与 FastAPI asyncio 生态原生兼容。
Worker 启动命令（示例）：
    python -m cygnusx.infrastructure.task_queue.arq_worker
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from cygnusx.core.config import get_settings


class ArqQueueConfig:
    """ARQ 队列配置。"""

    @staticmethod
    def redis_settings() -> RedisSettings:
        settings = get_settings()
        password_part = f":{settings.redis_password}@" if settings.redis_password else ""
        # ARQ 默认使用 db 0，这里复用主 Redis
        return RedisSettings.from_dsn(
            f"redis://{password_part}{settings.redis_host}:{settings.redis_port}/0"
        )


_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """获取全局 ARQ Redis 连接池（懒加载）。"""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(ArqQueueConfig.redis_settings())
    return _arq_pool


async def close_arq_pool() -> None:
    """关闭 ARQ 连接池。"""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
