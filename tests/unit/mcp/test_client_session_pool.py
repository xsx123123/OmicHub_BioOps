"""外部 stdio/SSE MCP 会话复用池行为测试。

覆盖：
- 同一 server 连续调用复用同一会话（不重复起进程）；
- 空闲超期后惰性回收并重建；
- 调用失败后关闭会话，下次调用重新连接；
- 连接配置变化（fingerprint）后重建。
"""

from __future__ import annotations

import mcp
import pytest

from omichub.domain.mcp.entities import MCPServer
from omichub.domain.mcp.value_objects import ServerStatus, Transport
from omichub.infrastructure.mcp import client as client_module


class _FakeStreamPair:
    def __init__(self, server_id: str) -> None:
        self.server_id = server_id

    async def __aenter__(self):
        return (object(), object())

    async def __aexit__(self, *exc):
        return None


class _FakeSession:
    def __init__(self, server_id: str, connect_counter: list[str]) -> None:
        self.server_id = server_id
        self.connect_counter = connect_counter
        self.entered = False
        self.exited = False
        self.fail_calls = 0
        self.call_log: list[str] = []

    async def __aenter__(self):
        self.entered = True
        self.connect_counter.append(self.server_id)
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return None

    async def initialize(self):
        return None

    async def list_tools(self):
        return type("R", (), {"tools": []})

    async def call_tool(self, tool_name: str, arguments: dict):
        self.call_log.append(tool_name)
        if self.fail_calls:
            self.fail_calls -= 1
            raise RuntimeError("boom")
        return type("R", (), {"content": [], "isError": False})


def _server(transport=Transport.STDIO, command="node", args=("x",)) -> MCPServer:
    return MCPServer(
        id="11111111-2222-3333-4444-555555555555",
        name="fake",
        description="",
        transport=transport,
        command=command,
        args=list(args),
        status=ServerStatus.ONLINE,
        is_enabled=True,
        tools=[],
    )


@pytest.fixture(autouse=True)
async def _clean_pool():
    yield
    await client_module.close_external_connections()


def _patch(monkeypatch, server: MCPServer, connect_counter: list[str], sessions: list, *, fail_first_call: int = 0):
    created_count = 0

    def fake_open(_self, _server):
        return _FakeStreamPair(str(_server.id))

    def fake_client_session(read, write):
        nonlocal created_count
        sess = _FakeSession(str(server.id), connect_counter)
        if fail_first_call and created_count == 0:
            sess.fail_calls = fail_first_call
        created_count += 1
        sessions.append(sess)
        return sess

    monkeypatch.setattr(client_module.MCPClient, "_open_session", fake_open)
    monkeypatch.setattr(mcp, "ClientSession", fake_client_session)


@pytest.mark.asyncio
async def test_same_server_reuses_session(monkeypatch):
    server = _server()
    counter: list[str] = []
    sessions: list = []
    _patch(monkeypatch, server, counter, sessions)

    mc = client_module.MCPClient()
    await mc._call_tool_external(server, "t1", {})
    await mc._call_tool_external(server, "t2", {})
    assert len(sessions) == 1, "应复用同一会话，不重复连接"


@pytest.mark.asyncio
async def test_failure_closes_and_reconnects(monkeypatch):
    server = _server()
    counter: list[str] = []
    sessions: list = []
    _patch(monkeypatch, server, counter, sessions, fail_first_call=1)

    mc = client_module.MCPClient()
    with pytest.raises(RuntimeError):
        await mc._call_tool_external(server, "boom", {})
    # 失败后旧会话应被关闭并从池中移除
    assert sessions[0].exited is True
    assert str(server.id) not in client_module._external_connections
    # 下次调用重新连接
    await mc._call_tool_external(server, "t2", {})
    assert len(sessions) == 2
    assert sessions[1].entered is True


@pytest.mark.asyncio
async def test_config_change_rebuilds(monkeypatch):
    server = _server(command="node", args=("a",))
    counter: list[str] = []
    sessions: list = []
    _patch(monkeypatch, server, counter, sessions)

    mc = client_module.MCPClient()
    await mc._call_tool_external(server, "t1", {})
    changed = _server(command="node", args=("b",))
    await mc._call_tool_external(changed, "t2", {})
    assert len(sessions) == 2, "连接配置变化应重建会话"


@pytest.mark.asyncio
async def test_idle_timeout_rebuilds(monkeypatch):
    server = _server()
    counter: list[str] = []
    sessions: list = []
    _patch(monkeypatch, server, counter, sessions)

    mc = client_module.MCPClient()
    await mc._call_tool_external(server, "t1", {})
    # 模拟空闲超期
    conn = client_module._external_connections[str(server.id)]
    conn.last_used = conn.last_used - (client_module._MCP_SESSION_IDLE_TIMEOUT + 10)
    await mc._call_tool_external(server, "t2", {})
    assert len(sessions) == 2, "空闲超期应惰性回收并重建"
