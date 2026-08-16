"""The sole HTTP adapter to OmicHub's public API."""

from __future__ import annotations

from typing import Any

import httpx

from .config import BridgeSettings


class OmicHubClient:
    def __init__(self, settings: BridgeSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.omichub_base_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_flows(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/flows")

    async def get_agentteams_capabilities(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/agent-teams/capabilities",
            headers={"X-Integration-Token": self._settings.omichub_integration_token},
            authenticate=False,
        )

    async def get_flow_schema(self, flow_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/flows/{flow_id}/schema")

    async def submit_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/tasks", json=payload)

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/tasks/{task_id}")

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/tasks/{task_id}/cancel")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        authenticate = kwargs.pop("authenticate", True)
        if authenticate and self._settings.omichub_api_key:
            headers["X-API-Key"] = self._settings.omichub_api_key
        elif authenticate and self._settings.omichub_service_token:
            headers["Authorization"] = f"Bearer {self._settings.omichub_service_token}"
        response = await self._client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise httpx.HTTPStatusError(
                "OmicHub response must be an object", request=response.request, response=response
            )
        return data


class GatewayClient:
    """Bridge-only adapter for the Gateway's fixed read-only consultation contract."""

    def __init__(self, settings: BridgeSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.gateway_url.rstrip("/"), timeout=settings.request_timeout_seconds
        )
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self._settings.gateway_url and self._settings.gateway_manager_token)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def consult(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Bridge Gateway integration is not configured")
        response = await self._client.post(
            "/v1/scientific-interpretation",
            json=payload,
            headers={
                "X-Gateway-Identity": "bioops-manager",
                "X-Gateway-Token": self._settings.gateway_manager_token,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise httpx.HTTPStatusError(
                "Gateway response must be an object", request=response.request, response=response
            )
        return data

    async def post_room_message(
        self,
        room_id: str,
        *,
        sender_identity: str,
        content: str,
        sender: dict[str, Any],
        source: str = "omichub",
    ) -> dict[str, Any]:
        """Mirror one message into a Matrix room via the Gateway's room contract."""
        if not self.configured:
            raise RuntimeError("Bridge Gateway integration is not configured")
        response = await self._client.post(
            f"/rooms/{room_id}/messages",
            json={
                "sender_identity": sender_identity,
                "content": content,
                "sender": sender,
                "source": source,
            },
            headers={
                "X-Gateway-Identity": "bioops-manager",
                "X-Gateway-Token": self._settings.gateway_manager_token,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise httpx.HTTPStatusError(
                "Gateway response must be an object", request=response.request, response=response
            )
        return data
