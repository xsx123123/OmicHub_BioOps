"""Matrix Gateway HTTP proxy contract tests; OmicHub never handles Matrix credentials."""

from __future__ import annotations

import json

import httpx
import pytest

from omichub.application.services.agentteams_room_gateway_service import (
    AgentTeamsRoomGatewayService,
    RoomGatewayRuntimeConfig,
)


@pytest.mark.asyncio
async def test_room_gateway_uses_only_gateway_manager_headers(monkeypatch) -> None:
    service = AgentTeamsRoomGatewayService(
        RoomGatewayRuntimeConfig(True, "http://gateway.test", "gateway-secret", 10)
    )
    calls: list[httpx.Request] = []

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def request(self, method, path, **kwargs):
            request = httpx.Request(method, f"http://gateway.test{path}", headers=kwargs["headers"], json=kwargs["json"])
            calls.append(request)
            return httpx.Response(200, json={"room_id": "!room:test"}, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await service.create_room("session-1", ["bioops-manager"])

    assert result == {"room_id": "!room:test"}
    assert calls[0].headers["x-gateway-identity"] == "bioops-manager"
    assert calls[0].headers["x-gateway-token"] == "gateway-secret"
    assert "matrix" not in json.dumps(dict(calls[0].headers)).lower()


@pytest.mark.asyncio
async def test_room_gateway_unconfigured_fails_without_network() -> None:
    service = AgentTeamsRoomGatewayService(RoomGatewayRuntimeConfig(False, "", "", 10))

    with pytest.raises(RuntimeError, match="未配置"):
        await service.create_room("session-1", ["bioops-manager"])
