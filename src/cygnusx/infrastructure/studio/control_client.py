"""Celery worker 调用 Web Studio 沙盒控制面的受限客户端。"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from cygnusx.core.config import Settings, get_settings

_CONTROL_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
_CONTROL_TOKEN_CONTEXT = b"cygnusx-studio-control-v1"


def resolve_studio_control_token(settings: Settings | None = None) -> str:
    """返回显式控制 token，或从 APP_SECRET_KEY 派生域隔离 token。"""
    current = settings or get_settings()
    if current.studio_control_token:
        return current.studio_control_token
    return hmac.new(
        current.app_secret_key.encode("utf-8"),
        _CONTROL_TOKEN_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


class StudioControlClient:
    """通过内部 HTTP 控制面执行沙盒操作，Worker 无需 Docker socket。"""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.studio_control_internal_url).rstrip("/")
        self.token = token if token is not None else resolve_studio_control_token(settings)
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.token)

    def _headers(self) -> dict[str, str]:
        return {"X-CygnusX-Studio-Control-Token": self.token}

    async def exec(
        self,
        session_id: str,
        language: str,
        code: str,
        timeout_sec: int,
        image: str | None,
        user_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "user_id": user_id,
            "language": language,
            "code": code,
            "timeout_sec": timeout_sec,
            "image": image,
        }
        async with (
            httpx.AsyncClient(timeout=_CONTROL_TIMEOUT, transport=self._transport) as client,
            client.stream(
                "POST",
                f"{self.base_url}/sessions/{session_id}/exec",
                headers=self._headers(),
                json=payload,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    yield json.loads(line)

    async def recycle_idle(self) -> int:
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            response = await client.post(
                f"{self.base_url}/recycle-idle", headers=self._headers()
            )
            response.raise_for_status()
            return int(response.json().get("recycled", 0))

    async def purge_workspace(self, session_id: str) -> str:
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            response = await client.delete(
                f"{self.base_url}/sessions/{session_id}/workspace",
                headers=self._headers(),
            )
            response.raise_for_status()
            return str(response.json().get("status") or "missing")
