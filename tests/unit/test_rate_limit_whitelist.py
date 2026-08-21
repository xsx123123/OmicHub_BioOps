from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from omichub.core.config import Settings
from omichub.middleware.rate_limit import (
    RateLimitMiddleware,
    _is_trusted_ip,
    _parse_trusted_networks,
)


def _request(path: str, host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": (host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_local_networks_are_trusted_by_default() -> None:
    networks = _parse_trusted_networks(None)

    assert _is_trusted_ip("127.0.0.1", networks)
    assert _is_trusted_ip("192.168.10.20", networks)
    assert _is_trusted_ip("10.20.30.40", networks)
    assert _is_trusted_ip("172.20.1.2", networks)
    assert _is_trusted_ip("fc00::1", networks)
    assert not _is_trusted_ip("8.8.8.8", networks)


def test_custom_trusted_networks_are_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_NETWORKS", '["203.0.113.0/24"]')

    settings = Settings(_env_file=None)

    assert settings.rate_limit_trusted_networks == ["203.0.113.0/24"]


@pytest.mark.asyncio
async def test_trusted_ip_bypasses_redis_rate_limit(monkeypatch) -> None:
    redis = AsyncMock()
    monkeypatch.setattr("omichub.infrastructure.cache.redis_client.get_redis", lambda: redis)
    call_next = AsyncMock(return_value=PlainTextResponse("ok"))
    middleware = RateLimitMiddleware(
        lambda scope, receive, send: None,
        trusted_networks=["192.168.0.0/16"],
    )

    response = await middleware.dispatch(_request("/api/v1/test", "192.168.1.10"), call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()
    redis.get.assert_not_awaited()
    redis.pipeline.assert_not_called()
