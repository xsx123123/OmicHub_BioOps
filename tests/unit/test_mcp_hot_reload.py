"""MCP 热加载单元测试 — 注册/更新后自动发现工具，免重启容器."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from omichub.application.schemas.mcp import CreateMCPServerDTO, UpdateMCPServerDTO
from omichub.application.services.mcp_service import MCPService
from omichub.domain.mcp.value_objects import ServerStatus
from omichub.infrastructure.database.models.mcp_builder import MCPVersionModel


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _version_filter(stmt):
    where = stmt.whereclause
    clauses = getattr(where, "clauses", [where] if where is not None else [])
    for clause in clauses:
        left, right = getattr(clause, "left", None), getattr(clause, "right", None)
        if left is not None and str(left) == "mcp_versions.version":
            return getattr(right, "value", None)
    return None


class _FakeSession:
    def __init__(self):
        self.added = []
        self.versions = []

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, MCPVersionModel):
            self.versions.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt):
        if stmt.column_descriptions[0]["name"] == "version":
            return _FakeResult([v.version for v in self.versions])
        rows = list(self.versions)
        wanted = _version_filter(stmt)
        if wanted is not None:
            rows = [v for v in rows if v.version == wanted]
        return _FakeResult(rows)


def _make_service() -> MCPService:
    service = MCPService(MagicMock())
    service._db = _FakeSession()
    service._repo = AsyncMock()
    service._repo.save.side_effect = lambda s: s
    service._domain = AsyncMock()
    service._client = AsyncMock()
    return service


DISCOVERED = [{"name": "echo", "description": "回显", "inputSchema": {"type": "object"}}]


@pytest.mark.unit
async def test_register_autodiscovers_tools_hot():
    """注册后即时发现工具：响应即带工具清单与 online 状态（热加载，免重启）"""
    service = _make_service()
    service._repo.get_by_name.return_value = None
    captured = {}

    async def _register(server):
        captured["server"] = server
        return server

    service._domain.register_server.side_effect = _register
    service._repo.get_by_id.side_effect = lambda _id: captured.get("server")
    service._client.list_tools = AsyncMock(return_value=DISCOVERED)

    dto = await service.register_server(
        CreateMCPServerDTO(name="hot-mcp", transport="stdio", command="python3")
    )

    service._client.list_tools.assert_awaited_once()
    assert dto.tool_count == 1
    assert dto.status == "online"
    server = captured["server"]
    assert [t.tool_name for t in server.tools] == ["echo"]
    assert server.status == ServerStatus.ONLINE


@pytest.mark.unit
async def test_register_succeeds_when_discovery_fails():
    """发现失败不阻断注册：行照常创建，状态标 error 并落日志，可稍后手动测试"""
    service = _make_service()
    service._repo.get_by_name.return_value = None
    captured = {}

    async def _register(server):
        captured["server"] = server
        return server

    service._domain.register_server.side_effect = _register
    service._repo.get_by_id.side_effect = lambda _id: captured.get("server")
    service._client.list_tools = AsyncMock(side_effect=RuntimeError("connection refused"))

    dto = await service.register_server(
        CreateMCPServerDTO(name="dead-mcp", transport="stdio", command="python3")
    )

    assert dto.name == "dead-mcp"
    assert dto.tool_count == 0
    assert dto.status == "error"  # list_tools 失败路径置 error，避免"离线却看似可用"


@pytest.mark.unit
async def test_update_connection_field_rediscovers():
    """连接类字段（command 等）变更后自动重新发现工具"""
    service = _make_service()
    captured = {}

    async def _register(server):
        captured["server"] = server
        return server

    # 先注册（发现成功，1 个工具）
    service._repo.get_by_name.return_value = None
    service._domain.register_server.side_effect = _register
    service._repo.get_by_id.side_effect = lambda _id: captured.get("server")
    service._client.list_tools = AsyncMock(return_value=DISCOVERED)
    await service.register_server(
        CreateMCPServerDTO(name="u-mcp", transport="stdio", command="python3")
    )
    server = captured["server"]
    service._client.list_tools.reset_mock()

    # 更新 command → 触发重新发现
    service._client.list_tools = AsyncMock(
        return_value=[{"name": "echo2", "description": "v2", "inputSchema": {}}]
    )
    dto = await service.update_server(server.id, UpdateMCPServerDTO(command="python3"))

    service._client.list_tools.assert_awaited_once()
    assert [t.tool_name for t in server.tools] == ["echo2"]
    assert dto.tool_count == 1


@pytest.mark.unit
async def test_update_non_connection_field_skips_discovery():
    """仅描述等非连接字段变更时不触发发现（避免无谓连接）"""
    service = _make_service()
    captured = {}

    async def _register(server):
        captured["server"] = server
        return server

    service._repo.get_by_name.return_value = None
    service._domain.register_server.side_effect = _register
    service._repo.get_by_id.side_effect = lambda _id: captured.get("server")
    service._client.list_tools = AsyncMock(return_value=DISCOVERED)
    await service.register_server(
        CreateMCPServerDTO(name="d-mcp", transport="stdio", command="python3")
    )
    server = captured["server"]
    service._client.list_tools.reset_mock()

    await service.update_server(server.id, UpdateMCPServerDTO(description="just a note"))

    service._client.list_tools.assert_not_awaited()
