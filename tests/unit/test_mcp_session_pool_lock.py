"""外部 MCP 会话池：并发多路复用（去队头阻塞）与关闭竞态测试。

覆盖：
- per-server 锁只保护建立/重建阶段：同一 server 的慢调用不阻塞其他调用
  （两个请求可在同一 ClientSession 上并发在途）；
- 并发首建时 double-check：只建立一个会话；
- close_external_connections 在建连锁下置 closing 标志，关闭在途期间拒绝新借用，
  完成后复位并清空池，允许后续重新建池；
- 损坏连接按对象身份失效，不误关他人重建的新会话。
"""

from __future__ import annotations

import asyncio

import mcp
import pytest

from cygnusx.domain.mcp.entities import MCPServer
from cygnusx.domain.mcp.value_objects import ServerStatus, Transport
from cygnusx.infrastructure.mcp import client as client_module
from cygnusx.infrastructure.mcp.reliability import MCPExternalCallError


class _FakeStreamPair:
    def __init__(self) -> None:
        self.entered = False
        self.exiting = False

    async def __aenter__(self):
        self.entered = True
        return (object(), object())

    async def __aexit__(self, *exc):
        self.exiting = True
        return None


class _FakeSession:
    """call_tool 在 session 内等待 gate 事件，用于制造并发/在途窗口。"""

    def __init__(self, gate: asyncio.Event | None) -> None:
        self.gate = gate
        self.entered = False
        self.exited = False
        self.active = 0
        self.max_active = 0
        self.call_log: list[str] = []

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return None

    async def initialize(self):
        return None

    async def call_tool(self, tool_name: str, arguments: dict):
        self.call_log.append(tool_name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            return type("R", (), {"content": [], "isError": False})
        finally:
            self.active -= 1


def _server() -> MCPServer:
    return MCPServer(
        id="11111111-2222-3333-4444-555555555555",
        name="fake",
        description="",
        transport=Transport.STDIO,
        command="node",
        args=["x"],
        status=ServerStatus.ONLINE,
        is_enabled=True,
        tools=[],
    )


@pytest.fixture(autouse=True)
async def _clean_pool():
    yield
    await client_module.close_external_connections()


def _patch_sessions(monkeypatch, sessions: list, gate: asyncio.Event | None = None):
    def fake_open(_self, _server):
        return _FakeStreamPair()

    def fake_client_session(read, write):
        sess = _FakeSession(gate)
        sessions.append(sess)
        return sess

    monkeypatch.setattr(client_module.MCPClient, "_open_session", fake_open)
    monkeypatch.setattr(mcp, "ClientSession", fake_client_session)


@pytest.mark.asyncio
async def test_slow_call_does_not_block_others(monkeypatch):
    """同一 server 的慢调用（持会话等待 gate）不再串行卡住后续请求：并发复用同一会话。"""
    gate = asyncio.Event()
    sessions: list[_FakeSession] = []
    _patch_sessions(monkeypatch, sessions, gate=gate)

    mc = client_module.MCPClient()
    server = _server()
    first = asyncio.create_task(mc._call_tool_external(server, "slow", {}))
    # 让 first 借用会话并停在 gate 上
    for _ in range(10):
        await asyncio.sleep(0)
    assert sessions[0].call_log == ["slow"]

    second = asyncio.create_task(mc._call_tool_external(server, "fast", {}))
    for _ in range(10):
        await asyncio.sleep(0)
    assert "fast" in sessions[0].call_log, "慢调用不应持锁阻塞第二个请求进入会话"
    assert sessions[0].active == 2, "两个请求应在同一会话上并发在途"

    gate.set()
    await asyncio.gather(first, second)
    assert sessions[0].max_active == 2
    assert len(sessions) == 1, "并发调用应复用同一会话，不重复建连"


@pytest.mark.asyncio
async def test_concurrent_first_borrow_builds_single_session(monkeypatch):
    """并发首建在锁上 double-check：同 server 只建立一个会话，双方共用。"""
    sessions: list[_FakeSession] = []
    gate = asyncio.Event()
    gate.set()
    _patch_sessions(monkeypatch, sessions, gate=gate)

    mc = client_module.MCPClient()
    server = _server()
    await asyncio.gather(*(mc._call_tool_external(server, f"t{i}", {}) for i in range(5)))

    assert len(sessions) == 1
    assert sorted(sessions[0].call_log) == [f"t{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_close_rejects_new_borrow_until_done(monkeypatch):
    """关闭在途（持建连锁等 __aexit__）期间，新借用被 closing 标志拒绝；完成后可再建池。"""
    sessions: list[_FakeSession] = []
    gate = asyncio.Event()
    gate.set()
    _patch_sessions(monkeypatch, sessions, gate=gate)

    mc = client_module.MCPClient()
    server = _server()
    await mc._call_tool_external(server, "t1", {})
    conn = client_module._external_connections[str(server.id)]

    release = asyncio.Event()
    original_aexit = type(conn.session_cm).__aexit__

    async def slow_aexit(self, *exc):
        await release.wait()
        return await original_aexit(self, *exc)

    monkeypatch.setattr(type(conn.session_cm), "__aexit__", slow_aexit)

    closer = asyncio.create_task(client_module.close_external_connections())
    for _ in range(10):
        await asyncio.sleep(0)
    assert client_module._external_pool_closing is True, "close 应处于置位关闭中"

    with pytest.raises(MCPExternalCallError) as exc_info:
        await mc._acquire_external_connection(_server())
    assert exc_info.value.kind == "pool_closing"

    release.set()
    await closer
    assert client_module._external_connections == {}
    assert client_module._external_pool_closing is False, "关闭完成后应复位，允许重新建池"

    # 池可复用：下一次借用建立全新会话
    await mc._call_tool_external(server, "t2", {})
    assert len(sessions) == 2
    assert sessions[1].entered is True


@pytest.mark.asyncio
async def test_invalidate_identity_guard():
    """失效操作按对象身份摘除：旧坏连接不会误关/误删池中新会话。"""
    mc = client_module.MCPClient()
    server = _server()
    key = str(server.id)

    old = client_module._ExternalConnection("fp-old", None, None)
    new = client_module._ExternalConnection("fp-new", None, None)
    client_module._external_connections[key] = new

    await mc._invalidate_external_connection(server, old)
    assert client_module._external_connections.get(key) is new, "不应误删他人新建的会话"
    assert new.closed is False, "新会话不应被关闭"

    await mc._invalidate_external_connection(server, new)
    assert key not in client_module._external_connections
    assert new.closed is True
