from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.value_objects import Transport
from cygnusx.infrastructure.mcp.client import MCPClient
from cygnusx.infrastructure.mcp.reliability import MCPHealthRegistry


@pytest.mark.asyncio
async def test_builtin_mcp_resolves_workspace_file_refs_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPServer(
        id=uuid4(),
        name="test-builtin",
        transport=Transport.BUILTIN,
        tools=[MCPToolRegistry(tool_name="plot", server_id=uuid4())],
    )
    captured: dict[str, object] = {}

    async def handler(arguments: dict[str, object], **_kwargs: object) -> dict[str, object]:
        captured.update(arguments)
        return {"success": True, "received": arguments}

    resolver = AsyncMock(return_value={"data_text": "ENSEMBL,log2FoldChange,padj\nTP53,2,0.01"})
    monkeypatch.setattr("cygnusx.infrastructure.mcp.client.get_preset_by_name", lambda _: {
        "handlers": {"plot": handler},
    })
    monkeypatch.setattr(
        "cygnusx.infrastructure.mcp.client.resolve_workspace_file_refs", resolver
    )

    client = MCPClient(MCPHealthRegistry())
    context = MagicMock()
    result = await client._call_tool_inner(
        server,
        "plot",
        {"data_text": f"file://{uuid4()}"},
        user_id="user-1",
        context=context,
    )

    assert result["success"] is True
    assert captured["data_text"].startswith("ENSEMBL")
    resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_mcp_receives_resolved_workspace_file_refs_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPServer(
        id=uuid4(),
        name="remote-bio",
        transport=Transport.SSE,
        tools=[MCPToolRegistry(tool_name="plot", server_id=uuid4())],
    )
    resolver = AsyncMock(return_value={"data_text": "ENSEMBL,log2FoldChange,padj\nTP53,2,0.01"})
    monkeypatch.setattr(
        "cygnusx.infrastructure.mcp.client.resolve_workspace_file_refs", resolver
    )
    client = MCPClient(MCPHealthRegistry())
    async def call_external(
        _server: MCPServer, _tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert arguments["data_text"].startswith("ENSEMBL")
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(client, "_call_tool_external", call_external)
    safe_external = AsyncMock(
        return_value={"content": [{"type": "text", "text": "ok"}], "isError": False}
    )  # type: ignore[method-assign]
    client._safe_external = safe_external  # type: ignore[method-assign]

    result = await client._call_tool_inner(
        server,
        "plot",
        {"data_text": f"file://{uuid4()}"},
        user_id="user-1",
    )

    assert result["success"] is True
    resolver.assert_awaited_once()
    safe_external.assert_awaited_once()
