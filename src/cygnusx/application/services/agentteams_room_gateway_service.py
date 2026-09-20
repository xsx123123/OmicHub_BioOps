"""HTTP-only client for the isolated AgentTeams Matrix Gateway.

CygnusX authenticates to the Gateway as a Manager service.  Matrix homeserver
URLs, Application Service tokens, and Matrix user credentials remain inside the
separately deployed Gateway process.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx

from cygnusx.core.config import get_settings


@dataclass(frozen=True)
class RoomGatewayRuntimeConfig:
    enabled: bool
    gateway_url: str
    manager_token: str
    timeout_seconds: float

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.gateway_url and self.manager_token)


class AgentTeamsRoomGatewayService:
    """Small, failure-isolated proxy for Matrix room operations."""

    def __init__(self, config: RoomGatewayRuntimeConfig | None = None) -> None:
        settings = get_settings()
        self._config = config or RoomGatewayRuntimeConfig(
            enabled=settings.agentteams_gateway_enabled,
            gateway_url=settings.agentteams_gateway_url.strip(),
            manager_token=settings.agentteams_gateway_manager_token,
            timeout_seconds=settings.agentteams_gateway_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return self._config.configured

    async def create_room(self, session_id: str, identities: list[str]) -> dict[str, Any]:
        return await self._request("POST", "/rooms", json={"session_id": session_id, "identities": identities})

    async def ensure_users(self, identities: list[str]) -> dict[str, Any]:
        """批量供给 AppService 持有的 Matrix 账号（幂等）。"""
        return await self._request("POST", "/users/ensure", json={"identities": identities})

    async def health_check(self) -> dict[str, Any]:
        """Report configuration and reachability separately for operational diagnosis."""
        if not self.available:
            return {"configured": False, "connected": False, "reason": "gateway_not_configured"}
        try:
            payload = await self._request("GET", "/healthz")
        except RuntimeError as exc:
            return {
                "configured": True,
                "connected": False,
                "reason": "gateway_unreachable",
                "detail": str(exc),
            }
        connected = payload.get("status") == "ok"
        return {
            "configured": True,
            "connected": connected,
            "reason": None if connected else "gateway_unhealthy",
            "matrix": payload.get("matrix", {}),
        }

    async def create_element_session(self, identity: str, room_id: str | None = None) -> dict[str, Any]:
        """为 AppService 持有的身份申请 Element Web 免登录会话凭据。

        携带 ``room_id`` 时 Gateway 会先幂等入房，避免仅 invited 未 joined
        的房间在 Element 深链下卡黑屏。
        """
        payload: dict[str, Any] = {"identity": identity}
        if room_id:
            payload["room_id"] = room_id
        return await self._request("POST", "/matrix/element-session", json=payload)

    async def leave_matrix_room(self, identity: str, room_id: str) -> dict[str, Any]:
        """让 AppService 持有的身份离开指定 Matrix 房间（删除协作室时调用）。"""
        return await self._request(
            "POST", "/matrix/rooms/leave", json={"identity": identity, "room_id": room_id}
        )

    async def post_message(
        self,
        room_id: str,
        *,
        sender_identity: str,
        content: str,
        sender: dict[str, Any],
        source: str = "cygnusx",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/rooms/{room_id}/messages",
            json={
                "sender_identity": sender_identity,
                "content": content,
                "sender": sender,
                "source": source,
            },
        )

    async def stream_room_events(
        self, room_id: str, *, since: str | None = None
    ) -> AsyncGenerator[dict[str, Any]]:
        if not self.available:
            return
        params = {"since": since} if since else None
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self._config.gateway_url.rstrip("/"),
                    timeout=httpx.Timeout(None),
                ) as client,
                client.stream(
                    "GET", f"/rooms/{room_id}/sync", params=params, headers=self._headers()
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        yield payload
        except httpx.HTTPError as exc:
            raise RuntimeError("Matrix Gateway 暂时不可用") from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("Matrix Gateway 未配置")
        try:
            async with httpx.AsyncClient(
                base_url=self._config.gateway_url.rstrip("/"),
                timeout=self._config.timeout_seconds,
            ) as client:
                response = await client.request(method, path, headers=self._headers(), **kwargs)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("Matrix Gateway 暂时不可用") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Matrix Gateway 返回了无效响应")
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "X-Gateway-Identity": "bioops-manager",
            "X-Gateway-Token": self._config.manager_token,
        }
