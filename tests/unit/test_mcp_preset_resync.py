"""cygnusx-tools 动态 preset 的工具快照重同步测试。

ensure_presets 对 platform/pipelines 每次启动同步工具清单；cygnusx-tools 的
工具来自 tools_schema.yaml + 动态 Flow 配置，同样必须重同步，否则只在首建时
写入快照、之后与 Flow 配置永久漂移。版本 pin / force 语义与 platform 一致。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import cygnusx.application.services.mcp_service as mcp_service
from cygnusx.application.services.mcp_service import MCPService
from cygnusx.domain.mcp.entities import MCPServer, MCPToolRegistry
from cygnusx.domain.mcp.value_objects import ServerStatus, Transport
from cygnusx.infrastructure.database.models.mcp_builder import MCPVersionModel
from cygnusx.infrastructure.mcp.conda_meta_preset import CONDA_META_MCP_SERVER_ID
from cygnusx.infrastructure.mcp.presets import (
    CYGNUSX_TOOLS_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_NAME,
)


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


class _NoopSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class _FakeSession:
    def __init__(self):
        self.versions: list[MCPVersionModel] = []
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, MCPVersionModel):
            self.versions.append(obj)

    async def flush(self):
        pass

    def begin_nested(self):
        return _NoopSavepoint()

    async def execute(self, stmt):
        if stmt.column_descriptions[0]["name"] == "version":
            return _FakeResult([v.version for v in self.versions])
        rows = list(self.versions)
        wanted = _version_filter(stmt)
        if wanted is not None:
            rows = [v for v in rows if v.version == wanted]
        return _FakeResult(rows)


def _tool(name: str, desc: str = "d") -> dict:
    return {"name": name, "description": desc, "inputSchema": {"type": "object"}}


def _cygnusx_server(*tool_names: str, **overrides) -> MCPServer:
    server = MCPServer(
        id=CYGNUSX_TOOLS_SERVER_ID,
        name=CYGNUSX_TOOLS_SERVER_NAME,
        description="旧描述",
        transport=Transport.BUILTIN,
        status=ServerStatus.ONLINE,
        current_version="1.0.0",
        version="1.0.0",
        is_preset=True,
        tools=[
            MCPToolRegistry(
                tool_name=name,
                description="d",
                input_schema={"type": "object"},
                server_id=CYGNUSX_TOOLS_SERVER_ID,
            )
            for name in tool_names
        ],
    )
    for key, value in overrides.items():
        setattr(server, key, value)
    return server


def _make_service(server: MCPServer) -> tuple[MCPService, _FakeSession]:
    db = _FakeSession()
    service = MCPService(MagicMock())
    service._db = db
    service._repo = AsyncMock()
    service._repo.save.side_effect = lambda s: s
    service._repo.list_all.return_value = [server]
    service._repo.get_by_name.side_effect = (
        lambda name: server if name == CYGNUSX_TOOLS_SERVER_NAME else None
    )
    # 预设身份归一化 / conda-meta 早退都依赖 get_by_id：常量 ID 返回同一 server
    service._repo.get_by_id.side_effect = (
        lambda _id: server
        if _id in (CYGNUSX_TOOLS_SERVER_ID, CONDA_META_MCP_SERVER_ID)
        else None
    )
    # conda-meta-mcp 种子化与断言无关：桩掉 test_server 发现环节保证跨环境确定性
    service.test_server = AsyncMock(return_value={"success": True, "tool_count": 0, "status": "online"})
    return service, db


def _patch_presets(monkeypatch, preset_tools: list[dict]) -> dict:
    preset = {
        "name": CYGNUSX_TOOLS_SERVER_NAME,
        "description": "动态工具箱描述",
        "tools": preset_tools,
    }
    monkeypatch.setattr(mcp_service, "PRESET_SERVERS", [])
    monkeypatch.setattr(mcp_service, "_build_cygnusx_tools_preset", lambda: preset)
    return preset


@pytest.mark.unit
async def test_cygnusx_tools_preset_resyncs_on_drift(monkeypatch):
    """Flow 配置变化后 ensure_presets 重同步 cygnusx-tools 工具快照（与 platform 同口径）。"""
    server = _cygnusx_server("old_flow_tool")
    service, db = _make_service(server)
    _patch_presets(monkeypatch, [_tool("kegg_enrich"), _tool("flow_prepare_x")])

    await service.ensure_presets()

    assert [t.tool_name for t in server.tools] == ["kegg_enrich", "flow_prepare_x"]
    assert server.current_version == "1.0.1"
    assert server.version == "1.0.1"
    assert server.description == "动态工具箱描述"
    rows = {v.version: v for v in db.versions}
    assert rows["1.0.0"].source == "register"
    assert rows["1.0.1"].source == "preset"
    assert rows["1.0.1"].changelog == "内置 MCP 预设升级：同步最新工具清单"


@pytest.mark.unit
async def test_cygnusx_tools_preset_no_sync_without_drift(monkeypatch):
    """工具清单一致时不动版本、不打快照。"""
    server = _cygnusx_server("tool_a")
    server.description = "动态工具箱描述"
    service, db = _make_service(server)
    _patch_presets(monkeypatch, [_tool("tool_a")])

    await service.ensure_presets()

    assert [t.tool_name for t in server.tools] == ["tool_a"]
    assert server.current_version == "1.0.0"
    assert db.versions == []


@pytest.mark.unit
async def test_cygnusx_tools_pinned_version_respects_pin_and_force(monkeypatch):
    """回滚 pin 的预设不被普通 ensure_presets 覆盖；force_preset_sync 强制同步并解除 pin。"""
    server = _cygnusx_server("tool_a", generation_meta={"preset_version_pinned": True})
    service, db = _make_service(server)
    _patch_presets(monkeypatch, [_tool("tool_b")])

    await service.ensure_presets()
    assert [t.tool_name for t in server.tools] == ["tool_a"]
    assert server.current_version == "1.0.0"

    await service.ensure_presets(force_preset_sync=True)
    assert [t.tool_name for t in server.tools] == ["tool_b"]
    assert server.current_version == "1.0.1"
    assert not (server.generation_meta or {}).get("preset_version_pinned")


@pytest.mark.unit
async def test_cygnusx_tools_id_holding_foreign_record_is_untouched(monkeypatch):
    """常量 ID 上是别名记录（异常态）时不误同步/覆盖，留待归一化流程处理。"""
    impostor = MCPServer(
        id=uuid4(), name="someone-else", transport=Transport.STDIO, command="node"
    )
    service, _db = _make_service(impostor)
    service._repo.get_by_id.side_effect = lambda _id: (
        impostor if _id == CYGNUSX_TOOLS_SERVER_ID else None
    )
    _patch_presets(monkeypatch, [_tool("tool_b")])

    await service.ensure_presets()

    assert impostor.name == "someone-else"
    assert impostor.tools == []
