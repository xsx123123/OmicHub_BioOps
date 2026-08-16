from __future__ import annotations

from uuid import uuid4

import pytest

from omichub.domain.mcp.entities import MCPServer, MCPToolRegistry
from omichub.domain.mcp.value_objects import Transport
from omichub.infrastructure.mcp.client import MCPClient
from omichub.infrastructure.mcp.reliability import MCPHealthRegistry


def make_server(name: str, transport: Transport) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        name=name,
        transport=transport,
        tools=[MCPToolRegistry(tool_name="translate_sequence", server_id=uuid4())],
    )


@pytest.mark.asyncio
async def test_external_tool_retries_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MCPClient(MCPHealthRegistry())
    server = make_server("remote-bio", Transport.SSE)
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": calls == 2, "result": {"protein": "MA"}}

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client, "_call_tool_inner", fake_call)
    monkeypatch.setattr("omichub.infrastructure.mcp.client.asyncio.sleep", no_wait)

    result = await client.call_tool(server, "translate_sequence", {})

    assert result["success"] is True
    assert result["reliability"] == {"attempts": 2, "recovered": True}
    assert client.health_registry.snapshot("remote-bio:translate_sequence")["status"] == "healthy"


@pytest.mark.asyncio
async def test_failed_external_tool_uses_builtin_fallback() -> None:
    client = MCPClient(MCPHealthRegistry())
    remote = make_server("remote-bio", Transport.SSE)
    builtin = make_server("local-bio", Transport.BUILTIN)

    async def fake_call(
        server: MCPServer,
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        if server.name == "remote-bio":
            return {"success": False, "error": "offline"}
        return {"success": True, "result": {"protein": "MA"}}

    client.retry_policy = client.retry_policy.__class__(max_attempts=1)
    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    result = await client.call_tool(remote, "translate_sequence", {}, fallback_servers=[builtin])

    assert result["success"] is True
    assert result["reliability"]["fallback_used"] == "local-bio"


@pytest.mark.asyncio
async def test_three_failures_mark_tool_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MCPClient(MCPHealthRegistry())
    client.retry_policy = client.retry_policy.__class__(max_attempts=3, backoff_seconds=(0,))
    server = make_server("remote-bio", Transport.SSE)

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"success": False, "error": "offline"}

    monkeypatch.setattr(client, "_call_tool_inner", fake_call)

    result = await client.call_tool(server, "translate_sequence", {})

    assert result["success"] is False
    assert result["reliability"]["primary_status"] == "degraded"


@pytest.mark.asyncio
async def test_translate_sequence_falls_back_to_local_biopython(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MCPClient(MCPHealthRegistry())
    client.retry_policy = client.retry_policy.__class__(max_attempts=1)
    server = make_server("ensmbl", Transport.STDIO)

    async def failed_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"success": False, "error": "server exited", "failure_kind": "connection_error"}

    monkeypatch.setattr(client, "_call_tool_inner", failed_call)

    result = await client.call_tool(
        server,
        "translate_sequence",
        {"sequence": "ATGGCC", "genetic_code": 1},
    )

    assert result["success"] is True
    assert result["result"]["protein"] == "MA"
    assert result["reliability"]["fallback_used"] == "local"


@pytest.mark.asyncio
async def test_external_mcp_is_error_is_not_counted_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MCPClient(MCPHealthRegistry())
    server = make_server("ensmbl", Transport.STDIO)

    async def tool_error(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "content": [{"type": "text", "text": "invalid genetic code"}],
            "isError": True,
        }

    monkeypatch.setattr(client, "_safe_external", tool_error)

    result = await client._call_tool_inner(server, "translate_sequence", {})

    assert result == {
        "success": False,
        "error": "invalid genetic code",
        "failure_kind": "tool_error",
    }
