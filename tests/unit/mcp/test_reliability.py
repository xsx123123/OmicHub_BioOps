from __future__ import annotations

from uuid import uuid4

import pytest

from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.value_objects import Transport
from cygnusx.infrastructure.mcp.client import MCPClient
from cygnusx.infrastructure.mcp.reliability import MCPHealthRegistry


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
    monkeypatch.setattr("cygnusx.infrastructure.mcp.client.asyncio.sleep", no_wait)

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


@pytest.mark.asyncio
async def test_degraded_tool_short_circuits_to_builtin_fallback() -> None:
    """degraded 后在冷却窗口内不再打远程，直接走 builtin 备用 server。"""
    registry = MCPHealthRegistry()
    client = MCPClient(registry)
    client.retry_policy = client.retry_policy.__class__(max_attempts=3, backoff_seconds=(0,))
    remote = make_server("remote-bio", Transport.SSE)
    builtin = make_server("local-bio", Transport.BUILTIN)
    remote_calls = 0

    async def fake_call(
        server: MCPServer,
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        nonlocal remote_calls
        if server.name == "remote-bio":
            remote_calls += 1
            return {"success": False, "error": "offline"}
        return {"success": True, "result": {"protein": "MA"}}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    first = await client.call_tool(remote, "translate_sequence", {}, fallback_servers=[builtin])
    assert remote_calls == 3  # 首次打满重试后进入 degraded
    assert first["reliability"]["short_circuited"] is False
    assert first["reliability"]["attempts"] == 3

    second = await client.call_tool(remote, "translate_sequence", {}, fallback_servers=[builtin])
    assert remote_calls == 3  # 熔断短路：不再调用远程
    assert second["success"] is True
    assert second["reliability"]["fallback_used"] == "local-bio"
    assert second["reliability"]["short_circuited"] is True
    assert second["reliability"]["attempts"] == 0
    assert second["reliability"]["primary_status"] == "degraded"


@pytest.mark.asyncio
async def test_degraded_tool_short_circuits_to_structured_failure() -> None:
    """冷却窗口内无可用兜底时，直接返回结构化失败且 failure_kind 为 circuit_open。"""
    registry = MCPHealthRegistry()
    client = MCPClient(registry)
    client.retry_policy = client.retry_policy.__class__(max_attempts=3, backoff_seconds=(0,))
    server = make_server("remote-bio", Transport.SSE)
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": False, "error": "offline"}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    await client.call_tool(server, "translate_sequence", {"sequence": ""})
    assert calls == 3

    result = await client.call_tool(server, "translate_sequence", {"sequence": ""})

    assert calls == 3  # 短路，未再发起远程调用
    assert result["success"] is False
    assert result["failure_kind"] == "circuit_open"
    assert result["reliability"]["short_circuited"] is True
    assert result["reliability"]["attempts"] == 0
    assert result["reliability"]["primary_status"] == "degraded"


@pytest.mark.asyncio
async def test_circuit_half_open_probe_success_recovers() -> None:
    """冷却窗口过后放行一次半开试探，成功则恢复 healthy 并关闭熔断。"""
    registry = MCPHealthRegistry()
    client = MCPClient(registry)
    client.retry_policy = client.retry_policy.__class__(max_attempts=3, backoff_seconds=(0,))
    server = make_server("remote-bio", Transport.SSE)
    key = "remote-bio:translate_sequence"
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": calls > 3, "result": {"protein": "MA"}}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    await client.call_tool(server, "translate_sequence", {})
    assert registry.snapshot(key)["status"] == "degraded"
    assert registry.try_acquire_call(key) == "open"

    # 模拟冷却窗口已过
    registry._get(key).circuit_open_until = 0.0

    recovered = await client.call_tool(server, "translate_sequence", {})
    assert calls == 4  # 半开试探只打一发
    assert recovered["success"] is True
    assert registry.snapshot(key)["status"] == "healthy"
    assert registry.try_acquire_call(key) == "closed"


@pytest.mark.asyncio
async def test_circuit_half_open_probe_failure_reenters_cooldown() -> None:
    """半开试探失败则重新进入冷却，且只尝试一次。"""
    registry = MCPHealthRegistry()
    client = MCPClient(registry)
    client.retry_policy = client.retry_policy.__class__(max_attempts=3, backoff_seconds=(0,))
    server = make_server("remote-bio", Transport.SSE)
    key = "remote-bio:translate_sequence"
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": False, "error": "offline"}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    await client.call_tool(server, "translate_sequence", {"sequence": ""})
    assert calls == 3

    registry._get(key).circuit_open_until = 0.0  # 冷却结束

    await client.call_tool(server, "translate_sequence", {"sequence": ""})
    assert calls == 4  # 半开只打一发，不再打满 3 次重试
    assert registry.try_acquire_call(key) == "open"  # 重新进入冷却


@pytest.mark.asyncio
async def test_builtin_transport_never_short_circuits() -> None:
    """builtin 本地工具不接入熔断：即使连续失败也照常调用。"""
    registry = MCPHealthRegistry()
    client = MCPClient(registry)
    server = make_server("local-bio", Transport.BUILTIN)
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"success": False, "error": "broken", "failure_kind": "tool_error"}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    for _ in range(4):
        await client.call_tool(server, "translate_sequence", {"sequence": ""})

    assert calls == 4  # 每次调用都真实执行，无短路
    assert registry.snapshot("local-bio:translate_sequence")["status"] == "degraded"


def test_try_acquire_call_allows_single_half_open_probe() -> None:
    """熔断门控：冷却中拒绝，冷却后只放行一个试探，并发试探被占位挡住。"""
    registry = MCPHealthRegistry()
    key = "server:tool"

    for _ in range(3):
        registry.record_failure(key, 1.0)

    assert registry.try_acquire_call(key) == "open"

    registry._get(key).circuit_open_until = 0.0  # 冷却结束
    assert registry.try_acquire_call(key) == "half_open"
    assert registry.try_acquire_call(key) == "open"  # 试探占位期间的并发调用被短路

    registry.record_success(key, 1.0)
    assert registry.try_acquire_call(key) == "closed"
