"""限流中间件 — 基于 Redis ZSET 的滑动窗口

策略：全局每 IP 每 window 秒最多 max_requests 次请求。
- 滑动窗口用 Redis Sorted Set 实现：score=请求时间戳，member=唯一标识；
  每次请求先清过期成员，再 ZADD 当前请求，ZCARD 计数判定。
- Redis 不可用时静默放行（沿用 stats_cache.py 降级范式，绝不影响可用性）。
- 命中限流返回 429 + Retry-After。
"""

import json
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# 不限流的路径前缀/精确匹配：静态资源、健康检查、API 文档、WebSocket
_SKIP_PATH_PREFIXES = ("/docs-static", "/assets", "/static")
_SKIP_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"})
# 分块上传路径豁免限流：大文件分片数多（5MiB/片，1GB=200 片），
# 3 路并发密集打请求会撞 100/60s 上限导致 429，上传失败。
_SKIP_UPLOAD_PREFIX = "/api/v1/files/upload/"


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。nginx 已注入 X-Forwarded-For / X-Real-IP（见 nginx.conf）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


def _should_skip(request: Request) -> bool:
    path = request.url.path
    if path in _SKIP_PATHS:
        return True
    if request.scope.get("type") == "websocket":
        return True
    # 分块上传豁免限流（分片密集，见 _SKIP_UPLOAD_PREFIX 注释）
    if path.startswith(_SKIP_UPLOAD_PREFIX):
        return True
    return any(path.startswith(p) for p in _SKIP_PATH_PREFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """每 IP 滑动窗口限流。Redis 异常时降级放行。"""

    def __init__(
        self, app, max_requests: int = 100, window_seconds: int = 60, enabled: bool = True
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or _should_skip(request):
            return await call_next(request)

        ip = _client_ip(request)
        key = f"ratelimit:{ip}"
        now = time.time()
        window_start = now - self.window_seconds

        try:
            from omichub.infrastructure.cache.redis_client import get_redis

            client = get_redis()
            # pipeline 原子化：清过期 → 记当前 → 计数 → 续期
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)  # 移除窗口外旧请求
            pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})  # 记录本次请求
            pipe.zcard(key)  # 当前窗口内请求数
            pipe.expire(key, self.window_seconds)  # 空闲后自动清理 key
            results = await pipe.execute()
            count = results[2]
        except Exception:
            # Redis 不可用：静默放行，绝不因限流组件故障阻断业务
            return await call_next(request)

        if count > self.max_requests:
            retry_after = max(1, int(self.window_seconds - (now - window_start)))
            return Response(
                content=json.dumps({"detail": "请求过于频繁，请稍后再试"}, ensure_ascii=False),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
