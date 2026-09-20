"""熔断计分按 failure_kind 区分 + 最终错误保留真实根因。

覆盖：
- 连续 tool_error / validation / file_reference 失败不把健康外部 server 打成 degraded、
  不触发熔断短路（模型传坏参数不应误伤 server）；
- 超时 / 连接错误 / 未知异常仍计入熔断（保守口径）；
- builtin 不经熔断门控，维持原有全量统计；
- 半开试探收到 tool_error 时释放试探占位（熔断不永久卡死）；
- 无兜底可用时最终错误以前缀 + 根因形式保留原始错误，不被固定文案覆盖。
"""

from __future__ import annotations

from uuid import uuid4

from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.value_objects import Transport
from cygnusx.infrastructure.mcp.client import MCPClient
from cygnusx.infrastructure.mcp.reliability import (
    CIRCUIT_EXCLUDED_FAILURE_KINDS,
    MCPHealthRegistry,
    ToolRetryPolicy,
    counts_toward_circuit_breaker,
)


def _server(name: str = "remote-bio", transport: Transport = Transport.SSE) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        name=name,
        transport=transport,
        tools=[MCPToolRegistry(tool_name="some_tool", server_id=uuid4())],
    )


def _client() -> MCPClient:
    client = MCPClient(MCPHealthRegistry())
    client.retry_policy = ToolRetryPolicy(max_attempts=1, backoff_seconds=())
    return client


def test_counts_toward_circuit_breaker_classification() -> None:
    for kind in CIRCUIT_EXCLUDED_FAILURE_KINDS:
        assert counts_toward_circuit_breaker(kind) is False
    for kind in ("timeout", "connection_error", "command_not_found", None, ""):
        assert counts_toward_circuit_breaker(kind) is True


async def _call_failing(client: MCPClient, server: MCPServer, failure: dict) -> dict:
    async def fake_call(*_args: object, **_kwargs: object) -> dict:
        return {"success": False, **failure}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]
    return await client.call_tool(server, "some_tool", {})


async def test_repeated_tool_errors_do_not_open_circuit() -> None:
    """LLM 连续幻觉坏参数（tool_error）不应短路健康 server。"""
    client = _client()
    server = _server()
    key = "remote-bio:some_tool"
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        return {
            "success": False,
            "error": "invalid genetic code",
            "failure_kind": "tool_error",
        }

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    for _ in range(5):
        await client.call_tool(server, "some_tool", {"sequence": "?"})

    assert calls == 5, "tool_error 不应触发熔断短路，每次都真实打到 server"
    snapshot = client.health_registry.snapshot(key)
    assert snapshot["status"] == "healthy"
    assert snapshot["failure_count"] == 0
    assert client.health_registry.try_acquire_call(key) == "closed"


async def test_validation_and_file_reference_excluded_timeout_counted() -> None:
    """validation/file_reference 不计入；timeout 计入且第 3 次打开熔断。"""
    client = _client()
    server = _server()
    key = "remote-bio:some_tool"

    await _call_failing(client, server, {"error": "bad args", "failure_kind": "validation"})
    await _call_failing(client, server, {"error": "no file", "failure_kind": "file_reference"})
    assert client.health_registry.snapshot(key)["status"] == "healthy"

    await _call_failing(client, server, {"error": "timed out", "failure_kind": "timeout"})
    await _call_failing(client, server, {"error": "reset", "failure_kind": "connection_error"})
    assert client.health_registry.snapshot(key)["consecutive_failures"] == 2

    await _call_failing(client, server, {"error": "timed out", "failure_kind": "timeout"})
    assert client.health_registry.snapshot(key)["status"] == "degraded"
    assert client.health_registry.try_acquire_call(key) == "open"


async def test_unknown_failure_kind_counts_conservatively() -> None:
    """无 failure_kind 的异常失败（如未捕获异常）按 server 级错误保守计入。"""
    client = _client()
    server = _server()
    key = "remote-bio:some_tool"

    for _ in range(3):
        await _call_failing(client, server, {"error": "boom"})

    assert client.health_registry.snapshot(key)["status"] == "degraded"


async def test_builtin_failures_still_recorded() -> None:
    """builtin 不经熔断门控、每次照常调用；其统计口径保持不变（tool_error 也记录）。"""
    client = _client()
    server = _server(name="local-bio", transport=Transport.BUILTIN)
    calls = 0

    async def fake_call(*_args: object, **_kwargs: object) -> dict:
        nonlocal calls
        calls += 1
        return {"success": False, "error": "broken", "failure_kind": "tool_error"}

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    for _ in range(4):
        await client.call_tool(server, "some_tool", {})

    assert calls == 4
    assert client.health_registry.snapshot("local-bio:some_tool")["status"] == "degraded"


async def test_half_open_probe_with_tool_error_releases_probe_slot() -> None:
    """冷却过后半开试探收到 tool_error：释放占位，熔断不永久卡死。"""
    client = _client()
    registry = client.health_registry
    server = _server()
    key = "remote-bio:some_tool"

    for _ in range(3):
        await _call_failing(client, server, {"error": "timeout", "failure_kind": "timeout"})
    assert registry.try_acquire_call(key) == "open"

    registry._get(key).circuit_open_until = 0.0  # 冷却结束
    result = await _call_failing(
        client, server, {"error": "invalid arg", "failure_kind": "tool_error"}
    )
    assert result["success"] is False
    # 占位已释放且未追加失败计数：冷却已过，可再次获准试探
    assert registry._get(key).probe_in_flight is False
    assert registry._get(key).consecutive_failures == 3
    assert registry.try_acquire_call(key) == "half_open"


async def test_final_error_preserves_root_cause() -> None:
    """无兜底可用时，固定文案作前缀，原始错误作为根因保留。"""
    client = _client()
    server = _server(name="ensmbl")

    async def fake_call(*_args: object, **_kwargs: object) -> dict:
        return {
            "success": False,
            "error": "HTTP 502 upstream enrichment failed",
            "failure_kind": "tool_error",
        }

    client._call_tool_inner = fake_call  # type: ignore[method-assign]

    result = await client.call_tool(server, "some_tool", {})

    assert result["success"] is False
    assert "HTTP 502 upstream enrichment failed" in result["error"]
    assert result["error"].startswith("当前外部服务暂时不可用")
    assert result["failure_kind"] == "tool_error"
