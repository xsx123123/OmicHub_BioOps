from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services.mcp_service import MCPService
from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.mcp.value_objects import ServerStatus, Transport


def server(name: str, transport: Transport) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        name=name,
        transport=transport,
        status=ServerStatus.ONLINE,
        is_enabled=True,
    )


@pytest.mark.asyncio
async def test_health_audit_reports_probe_failure_without_fallback() -> None:
    service = MCPService(AsyncMock())
    service.ensure_presets = AsyncMock()  # type: ignore[method-assign]
    service._repo.list_all = AsyncMock(
        return_value=[
            server("cygnusx-platform", Transport.BUILTIN),
            server("ensmbl", Transport.STDIO),
        ]
    )
    service._client.list_tools = AsyncMock(return_value=[{"name": "translate_sequence"}])
    service._client._call_tool_inner = AsyncMock(
        side_effect=[
            {"success": True, "result": {"date": "2026-08-07"}},
            {
                "success": False,
                "error": "npx exited before initialize",
                "failure_kind": "connection_error",
            },
        ]
    )

    result = await service.audit_health()

    assert result["summary"] == {"total": 2, "healthy": 1, "unhealthy": 1}
    assert result["servers"][1]["name"] == "ensmbl"
    assert result["servers"][1]["probe"] == "failed"
    assert result["servers"][1]["failure_kind"] == "connection_error"
