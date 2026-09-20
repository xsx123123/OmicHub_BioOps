"""HTTP-only adapter for CygnusX's controlled professional consultation endpoint."""

from __future__ import annotations

import httpx

from .config import GatewaySettings
from .models import ConsultationRequest, UpstreamConsultationResponse


class CygnusXConsultationClient:
    def __init__(self, settings: GatewaySettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.cygnusx_base_url,
            timeout=settings.request_timeout_seconds,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def consult(self, request: ConsultationRequest) -> UpstreamConsultationResponse:
        headers = self._auth_headers()
        payload = {
            "case_id": request.case_id,
            "agent_id": request.agent_id,
            "question": request.question,
            "capability": request.capability,
            "evidence_refs": request.evidence_refs,
            "requested_tools": request.requested_tools,
            "requester_ref": request.requester_ref,
            "work_item_id": request.work_item_id,
            "trace_id": request.trace_id,
            "execution_mode": request.execution_mode,
            "read_only": request.execution_mode == "readonly_consultation",
            "allow_task_actions": False,
            "allow_file_write": request.execution_mode == "workspace_execution",
            "allow_database_access": False,
            "allow_shell": False,
        }
        response = await self._client.post(
            self._settings.cygnusx_consultation_path,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return UpstreamConsultationResponse.model_validate(response.json())

    async def capabilities(self) -> dict:
        response = await self._client.get(
            "/api/v1/agent-teams/capabilities",
            headers=self._auth_headers() | {"X-Integration-Token": self._settings.cygnusx_integration_token},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _auth_headers(self) -> dict[str, str]:
        if self._settings.cygnusx_integration_token:
            return {"X-Integration-Token": self._settings.cygnusx_integration_token}
        return {}
