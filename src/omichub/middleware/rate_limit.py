"""限流中间件 — 基于 Redis ZSET 的滑动窗口

策略：全局每 IP 每 window 秒最多 max_requests 次请求。
- 滑动窗口用 Redis Sorted Set 实现：score=请求时间戳，member=唯一标识；
  每次请求先清过期成员，再 ZADD 当前请求，ZCARD 计数判定。
- Redis 不可用时静默放行（沿用 stats_cache.py 降级范式，绝不影响可用性）。
- 命中限流返回 429 + Retry-After。
"""

import ipaddress
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
_DEFAULT_TRUSTED_NETWORKS = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
)


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


def _parse_trusted_networks(networks: list[str] | tuple[str, ...] | None):
    parsed = []
    for value in networks or _DEFAULT_TRUSTED_NETWORKS:
        try:
            parsed.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(parsed)


def _is_trusted_ip(ip: str, networks) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """每 IP 滑动窗口限流，并对持续攻击源做短时封禁。"""

    def __init__(
        self,
        app,
        max_requests: int = 100,
        window_seconds: int = 60,
        enabled: bool = True,
        ban_enabled: bool = True,
        ban_threshold: int = 3,
        ban_window_seconds: int = 300,
        ban_seconds: int = 900,
        trusted_networks: list[str] | tuple[str, ...] | None = None,
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled
        self.ban_enabled = ban_enabled
        self.ban_threshold = max(1, ban_threshold)
        self.ban_window_seconds = max(1, ban_window_seconds)
        self.ban_seconds = max(1, ban_seconds)
        self.trusted_networks = _parse_trusted_networks(trusted_networks)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or _should_skip(request):
            return await call_next(request)

        ip = _client_ip(request)
        if _is_trusted_ip(ip, self.trusted_networks):
            return await call_next(request)
        key = f"ratelimit:{ip}"
        ban_key = f"rateban:{ip}"
        strike_key = f"rateban:strikes:{ip}"
        now = time.time()
        window_start = now - self.window_seconds

        try:
            from omichub.infrastructure.cache.redis_client import get_redis

            client = get_redis()
            if self.ban_enabled and await client.get(ban_key):
                return Response(
                    content=json.dumps(
                        {"detail": "该 IP 已被临时封禁，请稍后再试"}, ensure_ascii=False
                    ),
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(self.ban_seconds)},
                )
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
            banned = False
            if self.ban_enabled:
                try:
                    strike_pipe = client.pipeline()
                    strike_pipe.zremrangebyscore(
                        strike_key, 0, now - self.ban_window_seconds
                    )
                    strike_pipe.zadd(strike_key, {f"{now}:{uuid.uuid4().hex}": now})
                    strike_pipe.zcard(strike_key)
                    strike_pipe.expire(strike_key, self.ban_window_seconds)
                    strike_count = (await strike_pipe.execute())[2]
                    if strike_count >= self.ban_threshold:
                        await client.setex(ban_key, self.ban_seconds, "1")
                        banned = True
                except Exception:
                    # 封禁组件故障不能阻断业务，仍返回普通限流响应。
                    banned = False
            if banned:
                return Response(
                    content=json.dumps(
                        {"detail": "该 IP 已被临时封禁，请稍后再试"}, ensure_ascii=False
                    ),
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(self.ban_seconds)},
                )
            return Response(
                content=json.dumps({"detail": "请求过于频繁，请稍后再试"}, ensure_ascii=False),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
